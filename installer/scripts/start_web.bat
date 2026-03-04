@echo off
REM WingScribe Web Server Launcher
REM This script starts the WingScribe web interface

setlocal enabledelayedexpansion

REM Get the directory where this script is located
set "SCRIPT_DIR=%~dp0"
REM Remove trailing backslash
set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

REM APP_ROOT is the parent of scripts directory
set "APP_ROOT=%SCRIPT_DIR%\.."

REM Normalize APP_ROOT to absolute path
pushd "%APP_ROOT%"
set "APP_ROOT=%CD%"
popd

echo Script directory: %SCRIPT_DIR%
echo App root: %APP_ROOT%

REM Check if virtual environment exists
if not exist "%APP_ROOT%\venv\Scripts\python.exe" (
    echo Error: Virtual environment not found at: %APP_ROOT%\venv\
    echo Please reinstall WingScribe.
    pause
    exit /b 1
)

REM Check if config exists
if not exist "%APP_ROOT%\config\settings.yaml" (
    echo Configuration not found. Starting configuration wizard...
    echo.
    "%APP_ROOT%\venv\Scripts\python.exe" "%APP_ROOT%\scripts\config_wizard.py"
    if errorlevel 1 (
        echo.
        echo Configuration failed. Please run the wizard manually.
        pause
        exit /b 1
    )
    echo.
    echo Configuration completed successfully!
    echo.
)

REM Change to application directory BEFORE starting Python
cd /d "%APP_ROOT%"

REM Verify current directory
echo Current directory: %CD%
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

REM Start the web server from current directory
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
