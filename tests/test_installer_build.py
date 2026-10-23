from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_installer_variants_follow_the_authoritative_lock():
    from scripts.installer_dependencies import requirements
    from scripts.export_installer_lock import check
    check(PROJECT_ROOT)
    for mode, channel in [('cpu', 'cpu'), ('gpu', 'cu128')]:
        entry = PROJECT_ROOT / 'installer' / f'requirements-{mode}.txt'
        assert f'-r locks/{channel}.txt' in entry.read_text()
        locked = {r.name: r for r, _ in requirements(
            PROJECT_ROOT / 'installer/locks' / f'{channel}.txt')}
        assert str(locked['torch'].specifier) == f'==2.10.0+{channel}'
        assert str(locked['torchvision'].specifier) == f'==0.25.0+{channel}'


def test_manual_installer_build_does_not_publish_release_by_default():
    workflow = (
        PROJECT_ROOT / ".github" / "workflows" / "build-installer.yml"
    ).read_text(encoding="utf-8")

    assert "publish_release:" in workflow
    assert "type: boolean" in workflow
    assert "default: false" in workflow
    assert "if: github.event_name == 'push' || inputs.publish_release" in workflow


def test_uninstaller_does_not_recursively_remove_user_data():
    for name in ['installer.iss', 'installer-gpu.iss']:
        text = (PROJECT_ROOT / 'installer' / name).read_text(encoding='utf-8-sig')
        assert '[UninstallDelete]' not in text
        assert '[InstallDelete]' not in text
        assert 'filesandordirs' not in text


def test_exiftool_preparation_failure_stops_build_before_install(tmp_path):
    import shutil
    import subprocess
    import pytest
    shell = shutil.which('pwsh') or shutil.which('powershell')
    if not shell:
        pytest.skip('PowerShell required for installer behavior test')
    script = tmp_path / 'check.ps1'
    script.write_text(r"""
param([string]$BuildScript)
$ErrorActionPreference = 'Stop'
$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($BuildScript, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw 'Invalid PowerShell syntax' }
$fn = $ast.Find({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Invoke-Build'}, $true)
Invoke-Expression $fn.Extent.Text
function Fake-Python { $global:LASTEXITCODE = 0 }
function Ensure-Directory {}
function Prepare-ExifTool { return $false }
function Install-Dependencies { throw 'UNEXPECTED_INSTALL' }
$BuildPython = 'Fake-Python'; $PROJECT_ROOT = '.'; $Mode = 'cpu'
$SkipWheels = $true; $SkipExifTool = $false
try { Invoke-Build; throw 'Build unexpectedly succeeded' }
catch { if ($_.Exception.Message -ne 'ExifTool preparation failed') { throw }; Write-Output 'EXPECTED_FAILURE' }
""", encoding='utf-8-sig')
    result = subprocess.run([shell, '-NoProfile', '-File', str(script),
                             str(PROJECT_ROOT / 'installer/build.ps1')],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'EXPECTED_FAILURE' in result.stdout
