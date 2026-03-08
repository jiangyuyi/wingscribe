# WingScribe Web Server Launcher (PowerShell)
# This script starts the WingScribe web interface

$ErrorActionPreference = "Stop"

# Get the directory where this script is located
$ScriptRoot = Split-Path $MyInvocation.MyCommand.Path
$AppRoot = Split-Path $ScriptRoot -Parent

# Check bundled Python runtime
$PythonExe = Join-Path $AppRoot "python\python.exe"
if (-not (Test-Path $PythonExe)) {
    Write-Host "Error: Embedded Python not found!" -ForegroundColor Red
    Write-Host "Please reinstall the application." -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

# Ensure PyTorch native DLLs are discoverable
$TorchLib = Join-Path $AppRoot "python\Lib\site-packages\torch\lib"
$PythonRoot = Join-Path $AppRoot "python"
$ToolsDir = Join-Path $AppRoot "tools"
$env:PATH = "$PythonRoot;$PythonRoot\Scripts;$TorchLib;$ToolsDir;$env:PATH"

# Preflight check for PyTorch runtime
try {
    & $PythonExe -c "import torch" *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "torch import failed"
    }
} catch {
    Write-Host "Error: PyTorch runtime check failed." -ForegroundColor Red
    Write-Host "Possible missing runtime dependency (e.g. libomp140.x86_64.dll)." -ForegroundColor Yellow
    Write-Host "Please reinstall WingScribe or install Microsoft Visual C++ Redistributable (x64)." -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

# Check if config exists
$ConfigPath = Join-Path $AppRoot "config\settings.yaml"
if (-not (Test-Path $ConfigPath)) {
    Write-Host "Configuration not found. Starting configuration wizard..." -ForegroundColor Yellow
    & $PythonExe (Join-Path $AppRoot "scripts\config_wizard.py")
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Configuration failed. Please run the wizard manually." -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
}

# Change to application directory
Set-Location $AppRoot

# Start the web server
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  WingScribe Web Server" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Starting WingScribe Web Server..." -ForegroundColor Green
Write-Host "URL: http://localhost:8000" -ForegroundColor White
Write-Host "Press Ctrl+C to stop" -ForegroundColor Gray
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

try {
    & $PythonExe (Join-Path $AppRoot "src\web\app.py")
} catch {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Red
    Write-Host "Error: Web server stopped unexpectedly" -ForegroundColor Red
    Write-Host "========================================" -ForegroundColor Red
    Write-Host ""
    Write-Host $_.Exception.Message -ForegroundColor Yellow
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}
