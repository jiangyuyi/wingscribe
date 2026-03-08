@echo off
setlocal
set "SELFTEST=0"
if /I "%~1"=="--self-test" set "SELFTEST=1"

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

REM Set Python path (portable runtime bundled with installer)
set "PYTHON_EXE=%APP_ROOT%\python\python.exe"
set "PYTHON_ROOT=%APP_ROOT%\python"
set "TORCH_LIB=%APP_ROOT%\python\Lib\site-packages\torch\lib"
set "TOOLS_DIR=%APP_ROOT%\tools"

REM Ensure PyTorch native DLLs are discoverable
set "PATH=%PYTHON_ROOT%;%PYTHON_ROOT%\Scripts;%TORCH_LIB%;%TOOLS_DIR%;%PATH%"

if not exist "%PYTHON_EXE%" (
    echo Error: Embedded Python not found at %PYTHON_EXE%
    echo Please reinstall the application
    pause
    exit /b 1
)

REM Preflight check for PyTorch native runtime
"%PYTHON_EXE%" -c "import torch" >nul 2>&1
if errorlevel 1 (
    echo Error: PyTorch runtime check failed.
    echo Possible missing runtime dependency, for example libomp140.x86_64.dll.
    echo Please reinstall WingScribe or install Microsoft Visual C++ Redistributable x64.
    pause
    exit /b 1
)

if "%SELFTEST%"=="1" (
    echo Self-test passed.
    exit /b 0
)

REM Run initialization script
if exist "scripts\init_env.py" (
    echo Initializing WingScribe environment...
    "%PYTHON_EXE%" "%APP_ROOT%\scripts\init_env.py"
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

"%PYTHON_EXE%" "%APP_ROOT%\src\web\app.py"

if errorlevel 1 (
    echo.
    echo Error: Web server stopped
    pause
)
