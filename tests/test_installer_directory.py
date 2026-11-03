"""Compile the actual directory gate without installing the application."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest


def test_directory_gate_in_both_variants():
    root = Path(__file__).resolve().parents[1]
    for name in ('installer.iss', 'installer-gpu.iss'):
        script = (root / 'installer' / name).read_text(encoding='utf-8-sig')
        assert '#include "install-directory.iss"' in script
        assert script.index('Legacy installation detected') < script.index('Result := CheckInstallDirectory')
        assert script.index('Result := CheckInstallDirectory') < script.index('Result := PrepareVCRuntime')


def test_rejected_directory_keeps_editing_on_the_directory_page():
    source = (Path(__file__).resolve().parents[1] / 'installer/install-directory.iss').read_text()
    handler = source.split('function NextButtonClick', 1)[1]
    assert 'MsgBox(' not in handler
    assert 'InstallDirectoryHint.Caption :=' in handler
    assert 'WizardForm.ActiveControl := WizardForm.DirEdit' in handler
    assert 'Result := False' in handler


def test_actual_inno_directory_gate(tmp_path):
    compiler = os.environ.get('WINGSCRIBE_TEST_ISCC') or shutil.which('ISCC.exe')
    if os.name != 'nt' or not compiler:
        pytest.skip('Windows Inno compiler required')
    root = Path(__file__).resolve().parents[1]
    shutil.copyfile(root / 'installer/install-directory.iss', tmp_path / 'install-directory.iss')
    (tmp_path / 'payload.txt').write_text('test')
    (tmp_path / 'probe.iss').write_text('''[Setup]
AppName=WingScribe directory test
AppVersion=1
DefaultDirName={tmp}\\unused
PrivilegesRequired=lowest
Uninstallable=no
CreateUninstallRegKey=no
UsePreviousAppDir=no
OutputDir=.
OutputBaseFilename=probe
[Files]
Source: "payload.txt"; DestDir: "{app}"
[Code]
#include "install-directory.iss"
function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := CheckInstallDirectory;
end;
''', encoding='utf-8-sig')
    subprocess.run([compiler, str(tmp_path / 'probe.iss')], capture_output=True, check=True, timeout=60)
    for suffix in ('WingScribe', 'WingScribe-GPU'):
        target = tmp_path / 'Program Files' / suffix
        result = subprocess.run([str(tmp_path / 'probe.exe'), '/VERYSILENT', '/SUPPRESSMSGBOXES',
                                 '/SP-', '/NORESTART', f'/DIR={target}'], timeout=60)
        assert result.returncode == 0
        assert (target / 'payload.txt').read_text() == 'test'
    assert not list(tmp_path.glob('*.tmp'))
