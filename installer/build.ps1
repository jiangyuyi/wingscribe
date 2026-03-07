#!/usr/bin/env pwsh
#===============================================================================
# WingScribe Installer Build Script
#===============================================================================
# This script prepares all components for the Inno Setup installer

param(
    [switch]$SkipWheels = $false,
    [switch]$SkipExifTool = $false,
    [switch]$SkipPython = $false,
    [ValidateSet("cpu", "gpu")]
    [string]$Mode = "cpu"
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$PROJECT_ROOT = Split-Path $PSScriptRoot -Parent
$INSTALLER_DIR = $PSScriptRoot

# Build output directory depends on mode
$modeLower = $Mode.ToLower()
$BUILD_MODE_DIR = "build-$modeLower"
$BUILD_DIR = Join-Path $INSTALLER_DIR $BUILD_MODE_DIR
$WHEELS_DIR = Join-Path $INSTALLER_DIR "wheels-$modeLower"
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
# Step 2: Download PyTorch wheels (CPU or GPU)
#===============================================================================
function Download-PyTorchWheels {
    Log-Step "Downloading PyTorch $Mode wheels..."

    # PyTorch 2.4.0+ is required (>= 2.4)
    # CPU: cu118 (CUDA 11.8) or cu121 (CUDA 12.1)
    $cudaVersion = "cu118"
    if ($Mode -eq "gpu") {
        $wheels = @(
            "https://download.pytorch.org/whl/$cudaVersion/torch-2.4.0%2B$cudaVersion-cp311-cp311-win_amd64.whl",
            "https://download.pytorch.org/whl/$cudaVersion/torchvision-0.19.0%2B$cudaVersion-cp311-cp311-win_amd64.whl",
            "https://download.pytorch.org/whl/$cudaVersion/torchaudio-2.4.0%2B$cudaVersion-cp311-cp311-win_amd64.whl"
        )
    } else {
        $wheels = @(
            "https://download.pytorch.org/whl/cpu/torch-2.4.0%2Bcpu-cp311-cp311-win_amd64.whl",
            "https://download.pytorch.org/whl/cpu/torchvision-0.19.0%2Bcpu-cp311-cp311-win_amd64.whl",
            "https://download.pytorch.org/whl/cpu/torchaudio-2.4.0%2Bcpu-cp311-cp311-win_amd64.whl"
        )
    }

    Ensure-Directory $WHEELS_DIR

    # Also check common wheels directory as fallback
    $commonWheelsDir = Join-Path $INSTALLER_DIR "wheels"

    foreach ($wheel in $wheels) {
        $fileName = Split-Path $wheel -Leaf
        $filePath = Join-Path $WHEELS_DIR ($fileName -replace "%2B", "+")

        # Check in mode-specific directory first, then common directory
        if (-not (Test-Path $filePath)) {
            $commonPath = Join-Path $commonWheelsDir ($fileName -replace "%2B", "+")
            if (Test-Path $commonPath) {
                Copy-Item $commonPath -Destination $filePath -Force
                Log-Info "$fileName copied from common wheels directory"
            } else {
                Log-Info "Downloading $fileName..."
                try {
                    Invoke-WebRequest -Uri $wheel -OutFile $filePath -UseBasicParsing
                } catch {
                    $errMsg = $_.Exception.Message
                    Log-Warn "Failed to download $fileName - $($errMsg)"
                }
            }
        } else {
            Log-Info "$fileName already exists"
        }
    }

    Log-Success "PyTorch wheels downloaded"
}

#===============================================================================
# Step 3: Prepare ExifTool
#===============================================================================
function Prepare-ExifTool {
    Log-Step "Preparing ExifTool..."

    $exifExe = Join-Path $TOOLS_DIR "exiftool.exe"
    Ensure-Directory $TOOLS_DIR

    # Check if already exists in installer/tools
    if (Test-Path $exifExe) {
        Log-Info "ExifTool already exists at $exifExe"
        return $true
    }

    # If not, try to download from GitHub
    Log-Info "ExifTool not found, downloading..."
    $exifVersion = "13.10"
    $exifUrl = "https://github.com/exiftool/exiftool/releases/download/${exifVersion}/exiftool-${exifVersion}-win64.zip"
    $exifZip = Join-Path $TOOLS_DIR "exiftool.zip"

    try {
        Invoke-WebRequest -Uri $exifUrl -OutFile $exifZip -UseBasicParsing
        Expand-Archive -Path $exifZip -DestinationPath $TOOLS_DIR -Force
        $foundExe = Get-ChildItem -Path $TOOLS_DIR -Filter "exiftool*.exe" -Recurse | Select-Object -First 1
        if ($foundExe) {
            Copy-Item $foundExe.FullName -Destination $exifExe -Force
            Remove-Item $exifZip -Force
            Log-Success "ExifTool downloaded"
        }
    } catch {
        Log-Warn "Failed to download ExifTool: $_"
        return $false
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

#===============================================================================
# Step 4.5: Fix venv pyvenv.cfg for portable use
#===============================================================================
function Fix-VenvConfig {
    Log-Step "Fixing virtual environment configuration..."

    $venvDir = Join-Path $BUILD_DIR "venv"
    $pyvenvCfg = Join-Path $venvDir "pyvenv.cfg"

    if (Test-Path $pyvenvCfg) {
        # Replace hardcoded paths with relative paths
        # This allows venv to work on any machine
        $content = Get-Content $pyvenvCfg -Encoding UTF8
        $newContent = @()
        foreach ($line in $content) {
            if ($line -match "^home\s*=\s*(.+)") {
                # Replace with Scripts relative path
                $newContent += "home = Scripts"
            } elseif ($line -match "^executable\s*=\s*(.+)") {
                $newContent += "executable = Scripts\python.exe"
            } elseif ($line -match "^command\s*=\s*(.+)") {
                $newContent += "command = Scripts\python.exe -m venv"
            } else {
                $newContent += $line
            }
        }

        $newContent | Set-Content $pyvenvCfg -Encoding UTF8
        Log-Info "Fixed pyvenv.cfg - using relative Python paths"
    } else {
        Log-Warn "pyvenv.cfg not found - venv may not be properly created"
    }
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
    if ($Mode -eq "gpu") {
        $requirementsFile = Join-Path $INSTALLER_DIR "requirements-gpu.txt"
    } else {
        $requirementsFile = Join-Path $INSTALLER_DIR "requirements-cpu.txt"
    }
    & $venvPip install -r $requirementsFile

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
    $modeUpper = $Mode.ToUpper()
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "  WingScribe $modeUpper Installer Build" -ForegroundColor Cyan
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
        Prepare-ExifTool
    }

    # Download embeddable Python for venv creation on target machines
    if (-not $SkipPython) {
        Download-Python
    }

    Prepare-VirtualEnv
    Install-Dependencies
    Copy-SourceCode
    Download-YoloModel
    Copy-StartupScripts
    Prepare-FirstRunWizard

    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "  $modeUpper Build Complete!" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Build output:" -ForegroundColor White
    Write-Host "    Virtual environment: $BUILD_DIR\venv" -ForegroundColor Gray
    Write-Host "    Source code: $BUILD_DIR\src" -ForegroundColor Gray
    Write-Host ""
    Write-Host "  Next steps:" -ForegroundColor White
    Write-Host "    1. Download Inno Setup: https://jrsoftware.org/isdl.php" -ForegroundColor Gray
    Write-Host "    2. Run: iscc installer\installer-$Mode.iss" -ForegroundColor Gray
    Write-Host "    3. Output: installer\Output\WingScribe-Setup-$modeUpper.exe" -ForegroundColor Gray
    Write-Host ""
}

# Run the build
try {
    Invoke-Build
} catch {
    Log-Error "Build failed: $_"
    exit 1
}
