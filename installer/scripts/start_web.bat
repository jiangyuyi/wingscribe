@echo off
setlocal

REM Get script directory
set "SCRIPT_DIR=%~dp0"
set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

REM Get app root (parent of scripts directory)
pushd "%SCRIPT_DIR%\.."
set "APP_ROOT=%CD%"
popd

REM Change to app root
cd /d "%APP_ROOT%"

REM Check for app.py
if not exist "src\web\app.py" (
    echo Error: Cannot find src\web\app.py
    echo Current directory: %CD%
    echo APP_ROOT: %APP_ROOT%
    pause
    exit /b 1
)

REM Set Python path
set "VENV_PYTHON=%APP_ROOT%\venv\Scripts\python.exe"

REM Check for venv Python, if not found try to create it
if not exist "%VENV_PYTHON%" (
    echo Virtual environment not found, creating...
    if exist "%APP_ROOT%\python\python.exe" (
        echo Using embedded Python to create virtual environment...
        "%APP_ROOT%\python\python.exe" -m venv "%APP_ROOT%\venv"
    ) else (
        echo Error: Virtual environment not found and embedded Python not available
        echo Expected: %VENV_PYTHON%
        pause
        exit /b 1
    )
)

REM Check again after creation attempt
if not exist "%VENV_PYTHON%" (
    echo Error: Failed to create virtual environment
    echo Expected: %VENV_PYTHON%
    pause
    exit /b 1
)

REM Run initialization script
if exist "scripts\init_env.py" (
    echo Initializing WingScribe environment...
    "%VENV_PYTHON%" "%APP_ROOT%\scripts\init_env.py"
    if errorlevel 1 (
        echo Warning: Initialization had errors, continuing anyway...
    )
    echo.
)

REM Start web server
echo ========================================
echo   WingScribe Web Server
echo ========================================
echo.
echo Install dir: %APP_ROOT%
echo.
echo Starting WingScribe...
echo URL: http://localhost:8000
echo Press Ctrl+C to stop
echo.
echo ========================================
echo.

"%VENV_PYTHON%" "%APP_ROOT%\src\web\app.py"

if errorlevel 1 (
    echo.
    echo Error: Web server stopped
    pause
)
