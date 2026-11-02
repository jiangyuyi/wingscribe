"""VC prerequisite integrity and installer wiring regression checks."""
from pathlib import Path
import os
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_corrupt_vcredist_cache_stops_before_staging(tmp_path):
    shell = shutil.which('pwsh') or shutil.which('powershell')
    if not shell:
        pytest.skip('PowerShell required')
    scripts = tmp_path / 'scripts'
    scripts.mkdir()
    shutil.copyfile(ROOT / 'scripts/prepare_vcredist.ps1', scripts / 'prepare_vcredist.ps1')
    cache = tmp_path / 'installer/runtime-cache'
    cache.mkdir(parents=True)
    (cache / 'vc_redist-14.51.36247.x64.exe').write_bytes(b'corrupt runtime')
    result = subprocess.run([shell, '-NoProfile', '-File', str(scripts / 'prepare_vcredist.ps1')],
                            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30)
    assert result.returncode != 0
    assert 'VC++ cache hash mismatch' in result.stdout + result.stderr
    assert not (tmp_path / 'installer/build-cpu').exists()


@pytest.mark.parametrize('mode,name', [('cpu', 'installer.iss'), ('gpu', 'installer-gpu.iss')])
def test_prerequisite_is_shared_and_follows_legacy_guard(mode, name):
    source = (ROOT / 'installer' / name).read_text(encoding='utf-8-sig')
    assert f'Source: "build-{mode}\\prerequisites\\vc_redist.x64.exe"; Flags: dontcopy' in source
    assert '#include "vcredist.iss"' in source
    assert source.index('Legacy installation detected') < source.index('PrepareVCRuntime(NeedsRestart)')
    assert "if Result = '' then Result := PrepareVCRuntime" in source


def test_silent_missing_dependency_does_not_launch_installer():
    source = (ROOT / 'installer/vcredist.iss').read_text()
    assert source.index('if WizardSilent then exit') < source.index("ShellExec('runas'")
    assert '/install /norestart' in source
    assert 'if Code <> 0 then begin' in source
    assert '(Code = 3010) or (Code = 1641)' in source
    assert "if HasVCRuntime then Result := ''" in source


def test_inno_handles_runtime_exit_codes_before_copying_payload(tmp_path):
    """Exercise Inno's real PrepareToInstall result handling with injected child results."""
    compiler = os.environ.get('WINGSCRIBE_TEST_ISCC') or shutil.which('ISCC.exe')
    if os.name != 'nt' or not compiler:
        pytest.skip('Windows and Inno Setup compiler required for installer execution')

    source = (ROOT / 'installer/vcredist.iss').read_text(encoding='utf8')
    # Only replace the external prerequisite interaction. Compile the remaining
    # production code verbatim, including its final runtime registration check.
    _, boundary, tail = source.partition('ewWaitUntilTerminated, Code) then begin')
    assert boundary
    _, boundary, result_handling = tail.partition('\n  end;\n')
    assert boundary
    (tmp_path / 'payload.txt').write_text('QA marker')
    fixture = tmp_path / 'probe.iss'
    fixture.write_text('''[Setup]
AppName=WingScribe prerequisite probe
AppVersion=1
DefaultDirName={tmp}\\WingScribeProbe
PrivilegesRequired=lowest
Uninstallable=no
CreateUninstallRegKey=no
UsePreviousAppDir=no
OutputDir=.
OutputBaseFilename=probe
[Files]
Source: "payload.txt"; DestDir: "{app}"
[Code]
function HasVCRuntime: Boolean;
begin
  Result := ExpandConstant('{param:registered|0}') = '1';
end;
function PrepareToInstall(var NeedsRestart: Boolean): String;
var Code: Integer;
begin
  Code := StrToInt(ExpandConstant('{param:childcode|0}'));
  Result := 'Runtime missing';
''' + result_handling, encoding='utf-8-sig')
    subprocess.run([compiler, str(fixture)], check=True, capture_output=True, timeout=60)
    for code, registered, expected_exit, expected_message in [
        (3010, 1, 8, 'Microsoft runtime requires a Windows restart'),
        (1641, 0, 8, 'Microsoft runtime requires a Windows restart'),
        (1603, 0, 7, 'Microsoft runtime installation failed (exit 1603)'),
        (0, 0, 7, 'Runtime missing'),
        (0, 1, 0, 'Installation process succeeded'),
    ]:
        target = tmp_path / f'app-{code}-{registered}'
        log = target.with_suffix('.log')
        result = subprocess.run([str(tmp_path / 'probe.exe'), '/VERYSILENT', '/SUPPRESSMSGBOXES',
                                 '/SP-', '/NORESTART', f'/DIR={target}', f'/LOG={log}',
                                 f'/childcode={code}', f'/registered={registered}'], timeout=60)
        assert result.returncode == expected_exit, (code, registered, result.returncode)
        assert expected_message in log.read_text(encoding='utf-8-sig', errors='replace')
        assert (target / 'payload.txt').exists() == (expected_exit == 0)
