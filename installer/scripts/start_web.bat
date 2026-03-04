@echo off
REM WingScribe Web Server Launcher
REM This script starts the WingScribe web interface

setlocal enabledelayedexpansion

REM Get the directory where this script is located
set "SCRIPT_DIR=%~dp0"
set "APP_ROOT=%SCRIPT_DIR%.."

REM Check if virtual environment exists
if not exist "%APP_ROOT%\venv\Scripts\activate.bat" (
    echo Error: Virtual environment not found!
    echo Please run the configuration wizard first.
    pause
    exit /b 1
)

REM Check if config exists
if not exist "%APP_ROOT%\config\settings.yaml" (
    echo Configuration not found. Starting configuration wizard...
    "%APP_ROOT%\venv\Scripts\python.exe" "%APP_ROOT%\scripts\config_wizard.py"
    if errorlevel 1 (
        echo Configuration failed. Please run the wizard manually.
        pause
        exit /b 1
    )
)

REM Activate virtual environment
call "%APP_ROOT%\venv\Scripts\activate.bat"

REM Change to application directory
cd /d "%APP_ROOT%"

REM Start the web server
echo.
echo ========================================
echo   WingScribe Web Server
echo ========================================
echo.
echo Starting WingScribe Web Server...
echo URL: http://localhost:8000
echo Press Ctrl+C to stop
echo.
echo ========================================
echo.

"%APP_ROOT%\venv\Scripts\python.exe" "%APP_ROOT%\src\web\app.py"

REM If server crashed, show error
if errorlevel 1 (
    echo.
    echo ========================================
    echo Error: Web server stopped unexpectedly
    echo ========================================
    echo.
    pause
)
