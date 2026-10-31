"""VC prerequisite integrity and installer wiring regression checks."""
from pathlib import Path
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
