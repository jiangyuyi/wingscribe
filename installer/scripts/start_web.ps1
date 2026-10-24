# Share the BAT launcher's configuration-preserving Web entry point.
$ErrorActionPreference = "Stop"
$AppRoot = Split-Path $PSScriptRoot -Parent
$PythonExe = Join-Path $AppRoot "python\python.exe"
if (-not (Test-Path -LiteralPath $PythonExe)) {
    Write-Error "Embedded Python not found. Please reinstall WingScribe."
    exit 1
}
& $PythonExe (Join-Path $AppRoot "scripts\launch_web.py") @args
exit $LASTEXITCODE
