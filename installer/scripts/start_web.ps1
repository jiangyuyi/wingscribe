# WingScribe Web Server Launcher (PowerShell)
# This script starts the WingScribe web interface

$ErrorActionPreference = "Stop"

# Get the directory where this script is located
$ScriptRoot = Split-Path $MyInvocation.MyCommand.Path
$AppRoot = Split-Path $ScriptRoot -Parent

# Check if virtual environment exists
$VenvActivate = Join-Path $AppRoot "venv\Scripts\Activate.ps1"
if (-not (Test-Path $VenvActivate)) {
    Write-Host "Error: Virtual environment not found!" -ForegroundColor Red
    Write-Host "Please run the configuration wizard first." -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

# Check if config exists
$ConfigPath = Join-Path $AppRoot "config\settings.yaml"
if (-not (Test-Path $ConfigPath)) {
    Write-Host "Configuration not found. Starting configuration wizard..." -ForegroundColor Yellow
    & python (Join-Path $AppRoot "scripts\config_wizard.py")
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Configuration failed. Please run the wizard manually." -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
}

# Activate virtual environment
try {
    & $VenvActivate
} catch {
    Write-Host "Warning: Could not activate virtual environment" -ForegroundColor Yellow
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
    & python (Join-Path $AppRoot "src\web\app.py")
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
