#!/usr/bin/env pwsh
#===============================================================================
# WingScribe Installer Build Script
#===============================================================================
# This script prepares all components for the Inno Setup installer

param(
    [switch]$SkipWheels = $false,
    [switch]$SkipExifTool = $false,
    [switch]$SkipPython = $false
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$PROJECT_ROOT = Split-Path $PSScriptRoot -Parent
$INSTALLER_DIR = $PSScriptRoot
$BUILD_DIR = Join-Path $INSTALLER_DIR "build"
$WHEELS_DIR = Join-Path $INSTALLER_DIR "wheels"
$TOOLS_DIR = Join-Path $INSTALLER_DIR "tools"
$ASSETS_DIR = Join-Path $INSTALLER_DIR "assets"

# Colors
function Log-Info   { Write-Host "[INFO]   $($args[0])" -ForegroundColor Green }
function Log-Warn   { Write-Host "[WARN]   $($args[0])" -ForegroundColor Yellow }
function Log-Error  { Write-Host "[ERROR]  $($args[0])" -ForegroundColor Red }
function Log-Step   { Write-Host "[STEP]   $($args[0])" -ForegroundColor Cyan }
function Log-Success{ Write-Host "[OK]     $($args[0])" -ForegroundColor Green }

#===============================================================================
# Step 1: Download Python 3.11 Embedded
#===============================================================================
function Download-Python {
    Log-Step "Downloading Python 3.11.8 embeddable package..."

    $pythonUrl = "https://www.python.org/ftp/python/3.11.8/python-3.11.8-embed-amd64.zip"
    $pythonZip = Join-Path $BUILD_DIR "python-3.11.8-embed-amd64.zip"
    $pythonDir = Join-Path $BUILD_DIR "python"

    if (-not (Test-Path $pythonDir)) {
        if (-not (Test-Path $pythonZip)) {
            Log-Info "Downloading from $pythonUrl..."
            Invoke-WebRequest -Uri $pythonUrl -OutFile $pythonZip -UseBasicParsing
            Log-Success "Python downloaded"
        }

        Log-Info "Extracting Python..."
        Expand-Archive -Path $pythonZip -DestinationPath $pythonDir -Force
        Log-Success "Python extracted to $pythonDir"
    } else {
        Log-Info "Python already exists, skipping download"
    }

    # Modify python311._pth to include site-packages
    $pthFile = Join-Path $pythonDir "python311._pth"
    if (Test-Path $pthFile) {
        $pthContent = Get-Content $pthFile
        if ($pthContent -notmatch "site-packages") {
            Log-Info "Modifying python311._pth to enable site-packages..."
            $pthContent += "Lib/site-packages"
            $pthContent += "import site"
            $pthContent | Set-Content $pthFile -Encoding UTF8
            Log-Success "Python configured for site-packages"
        }
    }
}

#===============================================================================
# Step 2: Download PyTorch CPU wheels
#===============================================================================
function Download-PyTorchWheels {
    Log-Step "Downloading PyTorch CPU wheels..."

    # PyTorch 2.4.0+ is required (>= 2.4)
    $wheels = @(
        "https://download.pytorch.org/whl/cpu/torch-2.4.0%2Bcpu-cp311-cp311-win_amd64.whl",
        "https://download.pytorch.org/whl/cpu/torchvision-0.19.0%2Bcpu-cp311-cp311-win_amd64.whl",
        "https://download.pytorch.org/whl/cpu/torchaudio-2.4.0%2Bcpu-cp311-cp311-win_amd64.whl"
    )

    Ensure-Directory $WHEELS_DIR

    foreach ($wheel in $wheels) {
        $fileName = Split-Path $wheel -Leaf
        $filePath = Join-Path $WHEELS_DIR ($fileName -replace "%2B", "+")

        if (-not (Test-Path $filePath)) {
            Log-Info "Downloading $fileName..."
            Invoke-WebRequest -Uri $wheel -OutFile $filePath -UseBasicParsing
        } else {
            Log-Info "$fileName already exists"
        }
    }

    Log-Success "PyTorch wheels downloaded"
}

#===============================================================================
# Step 3: Download ExifTool
#===============================================================================
function Download-ExifTool {
    Log-Step "Downloading ExifTool..."

    # ExifTool Windows 64-bit version from SourceForge
    $exifVersion = "13.52"
    $exifUrl = "https://sourceforge.net/projects/exiftool/files/exiftool-${exifVersion}_64.zip/download"
    $exifZip = Join-Path $TOOLS_DIR "exiftool.zip"
    $exifExe = Join-Path $TOOLS_DIR "exiftool.exe"

    Ensure-Directory $TOOLS_DIR

    if (-not (Test-Path $exifExe)) {
        if (-not (Test-Path $exifZip)) {
            Log-Info "Downloading ExifTool from $exifUrl..."
            # Use MaximumRedirection to handle SourceForge redirects
            $ProgressPreference = "SilentlyContinue"
            $webClient = New-Object System.Net.WebClient
            $webClient.DownloadFile($exifUrl, $exifZip)
        }

        # Verify zip file is valid (check magic bytes)
        $zipBytes = [System.IO.File]::ReadAllBytes($exifZip)
        if ($zipBytes[0] -ne 0x50 -or $zipBytes[1] -ne 0x4B -or $zipBytes[2] -ne 0x03 -or $zipBytes[3] -ne 0x04) {
            Log-Warn "Downloaded file is not a valid zip (SourceForge mirror issue). Deleting and retrying..."
            Remove-Item $exifZip -Force
            Log-Info "Please download ExifTool manually from: https://exiftool.org/"
            Log-Info "Extract exiftool.exe and place in: $TOOLS_DIR"
            return $false
        }

        Log-Info "Extracting ExifTool..."
        $tempDir = Join-Path $env:TEMP "exiftool_extract"
        if (Test-Path $tempDir) { Remove-Item $tempDir -Recurse -Force }
        Expand-Archive -Path $exifZip -DestinationPath $tempDir -Force

        # Find exiftool.exe (might be in a subdirectory or named exiftool(-k).exe)
        $foundExe = Get-ChildItem -Path $tempDir -Filter "exiftool*.exe" -Recurse | Select-Object -First 1
        if ($foundExe) {
            Copy-Item $foundExe.FullName -Destination $exifExe -Force
            Remove-Item $tempDir -Recurse -Force
            Log-Success "ExifTool extracted to $exifExe"
        } else {
            Log-Error "exiftool.exe not found in downloaded archive"
            return $false
        }
    } else {
        Log-Info "ExifTool already exists"
    }

    return $true
}

#===============================================================================
# Step 4: Prepare virtual environment with all dependencies
#===============================================================================
function Prepare-VirtualEnv {
    Log-Step "Preparing virtual environment..."

    $venvDir = Join-Path $BUILD_DIR "venv"

    # Find system Python
    $systemPython = $null
    foreach ($cmd in @("python3.11", "python3", "python")) {
        try {
            $version = & $cmd --version 2>&1
            if ($version -match "Python 3\.([0-9]+)") {
                $minor = [int]$Matches[1]
                if ($minor -ge 8) {
                    $systemPython = $cmd
                    Log-Info "Found system Python: $version"
                    break
                }
            }
        } catch { }
    }

    if (-not $systemPython) {
        Log-Error "Python 3.8+ not found in system PATH"
        Log-Info "Please install Python from: https://www.python.org/downloads/"
        return $false
    }

    # Create virtual environment using system Python
    if (-not (Test-Path $venvDir)) {
        Log-Info "Creating virtual environment with system Python..."
        & $systemPython -m venv $venvDir
        if ($LASTEXITCODE -ne 0) {
            Log-Error "Failed to create virtual environment"
            return $false
        }
        Log-Success "Virtual environment created"
    } else {
        Log-Info "Virtual environment already exists"
    }

    return $true
}

function Install-Dependencies {
    Log-Step "Installing Python dependencies..."

    $venvPython = Join-Path $BUILD_DIR "venv\Scripts\python.exe"
    $venvPip = Join-Path $BUILD_DIR "venv\Scripts\pip.exe"

    if (-not (Test-Path $venvPip)) {
        Log-Error "pip not found at $venvPip"
        return $false
    }

    # First install PyTorch from local wheels
    Log-Info "Installing PyTorch from local wheels..."
    $torchWheels = Get-ChildItem (Join-Path $WHEELS_DIR "*.whl")
    foreach ($wheel in $torchWheels) {
        Log-Info "  Installing $($wheel.Name)..."
        & $venvPip install --no-index --no-deps $wheel.FullName
    }

    # Then install other dependencies from PyPI
    Log-Info "Installing other dependencies..."
    $requirementsCpu = Join-Path $INSTALLER_DIR "requirements-cpu.txt"
    & $venvPip install -r $requirementsCpu

    if ($LASTEXITCODE -eq 0) {
        Log-Success "Dependencies installed"
        return $true
    } else {
        Log-Error "Failed to install dependencies"
        return $false
    }
}

#===============================================================================
# Step 5: Copy WingScribe source code
#===============================================================================
function Copy-SourceCode {
    Log-Step "Copying WingScribe source code..."

    $sourceDir = Join-Path $BUILD_DIR "src"

    # Remove existing if any
    if (Test-Path $sourceDir) {
        Remove-Item $sourceDir -Recurse -Force
    }

    # Copy from project root
    $dirsToCopy = @("src", "config", "scripts", "tests")
    foreach ($dir in $dirsToCopy) {
        $source = Join-Path $PROJECT_ROOT $dir
        if (Test-Path $source) {
            Copy-Item -Path $source -Destination (Join-Path $BUILD_DIR $dir) -Recurse -Force
            Log-Info "  Copied $dir/"
        }
    }

    # Copy only necessary data subdirectories (references for IOC bird data)
    $dataRefsSource = Join-Path $PROJECT_ROOT "data\references"
    $dataRefsDest = Join-Path $BUILD_DIR "data\references"
    if (Test-Path $dataRefsSource) {
        Ensure-Directory $dataRefsDest
        Copy-Item -Path "$dataRefsSource\*" -Destination $dataRefsDest -Recurse -Force
        Log-Info "  Copied data/references/"
    }

    # Copy individual files
    $filesToCopy = @("requirements.txt", "README.md", "CLAUDE.md")
    foreach ($file in $filesToCopy) {
        $source = Join-Path $PROJECT_ROOT $file
        if (Test-Path $source) {
            Copy-Item -Path $source -Destination (Join-Path $BUILD_DIR $file) -Force
        }
    }

    Log-Success "Source code copied"
}

#===============================================================================
# Step 5.5: Download YOLO model
#===============================================================================
function Download-YoloModel {
    Log-Step "Downloading YOLO model..."

    $modelDir = Join-Path $BUILD_DIR "data\models"
    Ensure-Directory $modelDir

    # Get YOLO model name from config
    $yoloModelFull = "data/models/yolo26n.pt"
    $configFile = Join-Path $PROJECT_ROOT "config\settings.yaml"
    if (Test-Path $configFile) {
        $configContent = Get-Content $configFile -Raw
        if ($configContent -match 'yolo_model:\s*(\S+\.pt)') {
            $yoloModelFull = $Matches[1]
        }
    }

    # Extract just the filename from the full path
    $yoloModel = [System.IO.Path]::GetFileName($yoloModelFull)
    $modelPath = Join-Path $modelDir $yoloModel

    if (Test-Path $modelPath) {
        Log-Info "  YOLO model already exists: $yoloModel"
    } else {
        Log-Info "  Checking for YOLO model..."

        # 1. First check if there's a pre-downloaded model in installer/models
        $localModel = Join-Path $INSTALLER_DIR "models\$yoloModel"
        if (Test-Path $localModel) {
            Copy-Item $localModel -Destination $modelPath -Force
            Log-Success "  Copied YOLO model from installer/models"
            return
        }

        # 2. Try to find in user's cache
        try {
            $cacheDir = Join-Path $env:USERPROFILE ".cache\ultralytics"
            if (Test-Path $cacheDir) {
                $cachedModel = Get-ChildItem -Path $cacheDir -Filter $yoloModel -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
                if ($cachedModel) {
                    Copy-Item $cachedModel.FullName -Destination $modelPath -Force
                    Log-Success "  Copied YOLO model from cache"
                    return
                }
            }
        } catch { }

        # 3. Try to download directly from GitHub
        Log-Info "  Downloading $yoloModel..."
        try {
            if ($yoloModel -match "^yolo26") {
                $githubUrl = "https://github.com/ultralytics/assets/releases/download/v8.4.0/$yoloModel"
            } elseif ($yoloModel -match "^yolo11") {
                $githubUrl = "https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11n.pt"
            } else {
                $githubUrl = "https://github.com/ultralytics/assets/releases/download/v8.4.0/$yoloModel"
            }

            Log-Info "  Trying: $githubUrl"
            Invoke-WebRequest -Uri $githubUrl -OutFile $modelPath -UseBasicParsing
            Log-Success "  YOLO model downloaded to $modelPath"
        } catch {
            Log-Warn "  Failed to download YOLO model: $_"
            Log-Info "  Please manually download from: https://github.com/ultralytics/assets/releases"
            Log-Info "  Place the file as: $localModel"
            Log-Info "  Model will be downloaded on first run"
        }
    }
}

#===============================================================================
# Step 6: Copy startup scripts
#===============================================================================
function Copy-StartupScripts {
    Log-Step "Copying startup scripts..."

    $scriptsDir = Join-Path $BUILD_DIR "scripts"
    $installerScriptsDir = Join-Path $INSTALLER_DIR "scripts"
    Ensure-Directory $scriptsDir

    # Copy start_web.bat from installer/scripts directory
    $sourceBat = Join-Path $installerScriptsDir "start_web.bat"
    if (Test-Path $sourceBat) {
        Copy-Item $sourceBat -Destination (Join-Path $scriptsDir "start_web.bat") -Force
        Log-Info "  Copied start_web.bat"
    } else {
        Log-Warn "  start_web.bat not found in installer/scripts/, creating minimal version..."
        # Fallback to creating the file if it doesn't exist
        $batContent = @"
@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
pushd "%SCRIPT_DIR%\.."
set "APP_ROOT=%CD%"
popd
cd /d "%APP_ROOT%"
if not exist "src\web\app.py" (
    echo Error: Cannot find src\web\app.py
    echo Current directory: %CD%
    pause
    exit /b 1
)
if not exist "%APP_ROOT%\venv\Scripts\python.exe" (
    echo Error: Virtual environment not found
    pause
    exit /b 1
)
"%APP_ROOT%\venv\Scripts\python.exe" "%APP_ROOT%\src\web\app.py"
pause
"@
        $batContent | Out-File (Join-Path $scriptsDir "start_web.bat") -Encoding ASCII
    }

    # Copy start_web.ps1 from installer/scripts directory if it exists
    $sourcePs = Join-Path $installerScriptsDir "start_web.ps1"
    if (Test-Path $sourcePs) {
        Copy-Item $sourcePs -Destination (Join-Path $scriptsDir "start_web.ps1") -Force
        Log-Info "  Copied start_web.ps1"
    }

    # Copy init_env.py for environment initialization
    $sourceInitEnv = Join-Path $installerScriptsDir "init_env.py"
    if (Test-Path $sourceInitEnv) {
        Copy-Item $sourceInitEnv -Destination (Join-Path $scriptsDir "init_env.py") -Force
        Log-Info "  Copied init_env.py"
    }

    Log-Success "Startup scripts copied"
}

#===============================================================================
# Step 7: Prepare first-run wizard
#===============================================================================
function Prepare-FirstRunWizard {
    Log-Step "Preparing first-run configuration wizard..."

    $wizardScript = Join-Path $PROJECT_ROOT "scripts\config_wizard.py"
    $wizardDest = Join-Path $BUILD_DIR "scripts\config_wizard.py"

    if (-not (Test-Path $wizardScript)) {
        # Create the wizard script if it doesn't exist
        Log-Info "Creating config wizard script..."
        # ... wizard creation will be in a separate task
    }

    if (Test-Path $wizardScript) {
        Copy-Item $wizardScript -Destination $wizardDest -Force
        Log-Success "Config wizard copied"
    }
}

#===============================================================================
# Helper Functions
#===============================================================================
function Ensure-Directory {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        New-Item -ItemType Directory -Path $Path -Force | Out-Null
    }
}

#===============================================================================
# Main Build Process
#===============================================================================
function Invoke-Build {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "  WingScribe Installer Build" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host ""

    # Create build directories
    Ensure-Directory $BUILD_DIR
    Ensure-Directory $WHEELS_DIR
    Ensure-Directory $TOOLS_DIR
    Ensure-Directory $ASSETS_DIR

    # Execute build steps
    # Note: We now use system Python instead of downloading embedded Python

    if (-not $SkipWheels) {
        Download-PyTorchWheels
    }

    if (-not $SkipExifTool) {
        Download-ExifTool
    }

    Prepare-VirtualEnv
    Install-Dependencies
    Copy-SourceCode
    Download-YoloModel
    Copy-StartupScripts
    Prepare-FirstRunWizard

    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "  Build Complete!" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Build output:" -ForegroundColor White
    Write-Host "    Virtual environment: $venvDir" -ForegroundColor Gray
    Write-Host "    Source code: $BUILD_DIR\src" -ForegroundColor Gray
    Write-Host ""
    Write-Host "  Next steps:" -ForegroundColor White
    Write-Host "    1. Download Inno Setup: https://jrsoftware.org/isdl.php" -ForegroundColor Gray
    Write-Host "    2. Run: iscc installer\installer.iss" -ForegroundColor Gray
    Write-Host "    3. Output: installer\Output\WingScribe-Setup.exe" -ForegroundColor Gray
    Write-Host ""
}

# Run the build
try {
    Invoke-Build
} catch {
    Log-Error "Build failed: $_"
    exit 1
}
