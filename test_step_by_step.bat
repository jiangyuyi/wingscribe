@echo off
setlocal

echo Step 1: Testing SCRIPT_DIR...
set "SCRIPT_DIR=%~dp0"
echo SCRIPT_DIR=%SCRIPT_DIR%

echo Step 2: Testing SCRIPT_DIR without trailing backslash...
set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
echo SCRIPT_DIR=%SCRIPT_DIR%

echo Step 3: Testing APP_ROOT...
pushd "%SCRIPT_DIR%\.."
set "APP_ROOT=%CD%"
popd
echo APP_ROOT=%APP_ROOT%

echo Step 4: Testing cd command...
cd /d "%APP_ROOT%"
echo Current directory: %CD%

echo Step 5: Testing VENV_PYTHON variable...
set "VENV_PYTHON=%APP_ROOT%\venv\Scripts\python.exe"
echo VENV_PYTHON=%VENV_PYTHON%

echo Step 6: Testing file existence...
if exist "src\web\app.py" (
    echo File exists: src\web\app.py
) else (
    echo File NOT found: src\web\app.py
)

echo.
echo All tests passed!
pause
