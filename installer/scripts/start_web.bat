@echo off
setlocal
set "APP_ROOT=%~dp0.."
set "PYTHON_EXE=%APP_ROOT%\python\python.exe"
if not exist "%PYTHON_EXE%" (
    echo Error: Embedded Python not found. Please reinstall WingScribe.
    exit /b 1
)
"%PYTHON_EXE%" "%APP_ROOT%\scripts\launch_web.py" %*
exit /b %ERRORLEVEL%
