@echo off
REM WingScribe Web Server Launcher
REM This script starts the WingScribe web interface

setlocal

REM ========================================
REM IMPORTANT: Do NOT change the working directory context
REM We must always operate from the installation directory
REM ========================================

REM Get the directory where this script is located
set "SCRIPT_DIR=%~dp0"

REM Remove trailing backslash from script directory
set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

REM The installation directory (APP_ROOT) is the parent of scripts directory
REM Since we're in {APP_ROOT}\scripts\, going up one level gives us {APP_ROOT}\
pushd "%SCRIPT_DIR%\.."
set "APP_ROOT=%CD%"
popd

REM Now APP_ROOT is the absolute path to the installation directory

REM Check for --config-guide flag
if "%1"=="--config-guide" (
    echo.
    echo ========================================
    echo   WingScribe - 配置指南
    echo ========================================
    echo.
    echo 安装完成后，您需要完成以下配置步骤：
    echo.
    echo 1. Web 服务即将启动...
    echo 2. 在浏览器中打开: http://localhost:8000
    echo 3. 首次访问将自动进入配置页面
    echo 4. 在配置页面中设置：
    echo    - 照片根目录（存放照片的位置）
    echo    - Web 服务端口（默认 8000）
    echo 5. 点击"保存配置"完成设置
    echo.
    echo 按任意键启动 Web 服务...
    pause > nul
)

REM Check if virtual environment exists
if not exist "%APP_ROOT%\venv\Scripts\python.exe" (
    echo Error: Virtual environment not found at: %APP_ROOT%\venv\
    echo Please reinstall WingScribe.
    echo.
    echo Current directory: %CD%
    echo APP_ROOT: %APP_ROOT%
    pause
    exit /b 1
)

REM IMPORTANT: Change to APP_ROOT BEFORE starting Python
REM This ensures all relative paths in the app are resolved correctly
cd /d "%APP_ROOT%"

REM Verify we're in the right place
if not exist "src\web\app.py" (
    echo Error: Cannot find src\web\app.py
    echo Current directory: %CD%
    echo Expected location: %APP_ROOT%
    echo.
    echo Please check if WingScribe is installed correctly.
    pause
    exit /b 1
)

REM Start the web server
echo.
echo ========================================
echo   WingScribe Web Server
echo ========================================
echo.
echo Installation directory: %APP_ROOT%
echo.
echo Starting WingScribe Web Server...
echo URL: http://localhost:8000
echo Press Ctrl+C to stop
echo.
echo ========================================
echo.

REM Use absolute path to Python to avoid any path resolution issues
"%APP_ROOT%\venv\Scripts\python.exe" "src\web\app.py"

REM If server crashed, show error
if errorlevel 1 (
    echo.
    echo ========================================
    echo Error: Web server stopped unexpectedly
    echo ========================================
    echo.
    pause
)
