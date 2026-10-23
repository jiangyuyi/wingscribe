#!/usr/bin/env pwsh
#===============================================================================
# WingScribe Installer Build Script
#===============================================================================
# This script prepares all components for the Inno Setup installer

param(
    [switch]$SkipWheels = $false,
    [switch]$SkipExifTool = $false,
    [switch]$SkipPython = $false,
    [switch]$SkipDepsInstall = $false,
    [switch]$RefreshWheels = $false,
    [ValidateSet("cpu", "gpu")]
    [string]$Mode = "cpu",
    [string]$Version = "1.0.0",
    [string]$BuildPython = "python",
    [string]$PyTorchWheelBase = "https://download.pytorch.org/whl"
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

# Save version to file for Inno Setup
$VERSION_FILE = Join-Path $INSTALLER_DIR "version.txt"
$Version | Out-File -FilePath $VERSION_FILE -Encoding UTF8
Log-Info "Building version: $Version"

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
        $pthText = ($pthContent -join "`r`n")
        $needsRewrite = $false

        # Remove BOM corruption from first line if present.
        if ($pthContent.Count -gt 0 -and $pthContent[0].StartsWith([char]0xFEFF)) {
            $pthContent[0] = $pthContent[0].TrimStart([char]0xFEFF)
            $pthText = ($pthContent -join "`r`n")
            $needsRewrite = $true
            Log-Info "Cleaning BOM from python311._pth"
        }

        if ($pthText -notmatch "(?m)^Lib/site-packages\s*$") {
            Log-Info "Modifying python311._pth to enable site-packages..."
            $newLines = @($pthContent)
            if ($pthText -notmatch "(?m)^import site\s*$") {
                $newLines += "Lib/site-packages"
                $newLines += "import site"
            } else {
                $newLines += "Lib/site-packages"
            }
            # IMPORTANT: _pth must not contain UTF BOM, otherwise first line becomes invalid path.
            [System.IO.File]::WriteAllLines($pthFile, $newLines, [System.Text.UTF8Encoding]::new($false))
            $needsRewrite = $false
            Log-Success "Python configured for site-packages"
        }

        if ($needsRewrite) {
            [System.IO.File]::WriteAllLines($pthFile, $pthContent, [System.Text.UTF8Encoding]::new($false))
            Log-Success "python311._pth rewritten without BOM"
        }
    }

    # Ensure pip is available in embeddable Python
    $pythonExe = Join-Path $pythonDir "python.exe"
    $pipReady = $false
    if (Test-Path $pythonExe) {
        try {
            & $pythonExe -m pip --version *> $null
            if ($LASTEXITCODE -eq 0) {
                $pipReady = $true
            }
        } catch {
            $pipReady = $false
        }
    }
    if ((-not $pipReady) -and (Test-Path $pythonExe)) {
        Log-Info "Installing pip for embeddable Python..."
        $getPipUrl = "https://bootstrap.pypa.io/get-pip.py"
        $getPipFile = Join-Path $BUILD_DIR "get-pip.py"
        try {
            Invoke-WebRequest -Uri $getPipUrl -OutFile $getPipFile -UseBasicParsing
            & $pythonExe $getPipFile --no-warn-script-location
            Remove-Item $getPipFile -Force
            Log-Success "pip installed"
        } catch {
            Log-Warn "Failed to install pip: $_"
        }
    }
}

#===============================================================================
# Step 2: Download PyTorch wheels (CPU or GPU)
#===============================================================================
function Download-PyTorchWheels {
    Log-Step "Fetching complete hash-locked runtime wheel set..."
    if ($RefreshWheels) { throw "RefreshWheels no longer deletes caches; remove only a diagnosed corrupt file before retrying" }
    if ($PyTorchWheelBase -ne "https://download.pytorch.org/whl") {
        throw "Custom PyTorchWheelBase is not used by the locked fetcher; configure trusted indexes in installer_dependencies.py"
    }
    & $BuildPython (Join-Path $PROJECT_ROOT "scripts\installer_dependencies.py") fetch --mode $modeLower
    if ($LASTEXITCODE -ne 0) { throw "Locked wheel fetch failed" }
    Log-Success "Complete wheel set verified"
}

#===============================================================================
# Step 3: Prepare ExifTool
#===============================================================================
function Prepare-ExifTool {
    Log-Step "Preparing ExifTool..."

    $exifExe = Join-Path $TOOLS_DIR "exiftool.exe"
    $exifFilesDir = Join-Path $TOOLS_DIR "exiftool_files"
    Ensure-Directory $TOOLS_DIR

    # Check if already exists in installer/tools with required runtime files
    if ((Test-Path $exifExe) -and (Test-Path $exifFilesDir)) {
        Log-Info "ExifTool already exists at $exifExe with exiftool_files/"
        return $true
    }

    # Clean stale/incomplete exiftool layout
    if (Test-Path $exifExe) {
        Remove-Item $exifExe -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path $exifFilesDir) {
        Remove-Item $exifFilesDir -Recurse -Force -ErrorAction SilentlyContinue
    }

    Log-Info "Preparing full ExifTool runtime (exe + exiftool_files)..."
    $localExifZip = Join-Path $TOOLS_DIR "exiftool-runtime.zip"
    $downloadedExifZip = Join-Path $BUILD_DIR "exiftool-download.zip"
    $prepared = $false

    $extractFromZip = {
        param([string]$zipPath)
        if (-not (Test-Path $zipPath)) {
            return $false
        }
        $tempExtract = Join-Path $BUILD_DIR "exiftool-extract"
        if (Test-Path $tempExtract) {
            Remove-Item $tempExtract -Recurse -Force -ErrorAction SilentlyContinue
        }
        Expand-Archive -Path $zipPath -DestinationPath $tempExtract -Force
        $foundExe = Get-ChildItem -Path $tempExtract -Filter "exiftool*.exe" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $foundExe) {
            return $false
        }
        Copy-Item $foundExe.FullName -Destination $exifExe -Force
        $sourceDir = Split-Path $foundExe.FullName -Parent
        $sourceFilesDir = Join-Path $sourceDir "exiftool_files"
        if (Test-Path $sourceFilesDir) {
            Copy-Item $sourceFilesDir -Destination $exifFilesDir -Recurse -Force
            return ((Test-Path $exifExe) -and (Test-Path $exifFilesDir))
        }
        return $false
    }

    # 1) Prefer repository bundled runtime archive for CI stability.
    if (Test-Path $localExifZip) {
        try {
            $prepared = & $extractFromZip $localExifZip
            if ($prepared) {
                Log-Info "Prepared ExifTool from bundled archive: $localExifZip"
            }
        } catch {
            Log-Warn "Failed to extract bundled ExifTool archive: $_"
        }
    }

    # 2) Fallback: download archive at build time.
    if (-not $prepared) {
        $exifVersion = "13.26"
        $exifUrls = @(
            "https://github.com/exiftool/exiftool/releases/download/$exifVersion/exiftool-$exifVersion-win64.zip",
            "https://exiftool.org/exiftool-$exifVersion_64.zip"
        )
        foreach ($exifUrl in $exifUrls) {
            try {
                Invoke-WebRequest -Uri $exifUrl -OutFile $downloadedExifZip -UseBasicParsing
                $prepared = & $extractFromZip $downloadedExifZip
                if ($prepared) {
                    Log-Info "Downloaded ExifTool runtime from: $exifUrl"
                    break
                }
            } catch {
                Log-Warn "Failed to download ExifTool package from $exifUrl : $_"
            } finally {
                if (Test-Path $downloadedExifZip) {
                    Remove-Item $downloadedExifZip -Force -ErrorAction SilentlyContinue
                }
            }
        }
    }

    # Fallback: copy from system exiftool install if available
    if (-not $prepared) {
        try {
            $sysCmd = Get-Command exiftool -ErrorAction Stop
            $sysExe = $sysCmd.Source
            $sysDir = Split-Path $sysExe -Parent
            $sysFilesDir = Join-Path $sysDir "exiftool_files"
            if ((Test-Path $sysExe) -and (Test-Path $sysFilesDir)) {
                Copy-Item $sysExe -Destination $exifExe -Force
                Copy-Item $sysFilesDir -Destination $exifFilesDir -Recurse -Force
                $prepared = $true
                Log-Info "Copied ExifTool runtime from system install"
            }
        } catch {
            # No system exiftool available, keep failure below
        }
    }

    if (-not $prepared) {
        Log-Warn "Failed to prepare ExifTool runtime (missing exiftool_files)"
        return $false
    }

    # Final check: executable must run
    & $exifExe -ver *> $null
    if ($LASTEXITCODE -ne 0) {
        Log-Warn "ExifTool executable test failed"
        return $false
    }

    Log-Success "ExifTool runtime prepared"
    return $true
}

#===============================================================================
# Step 4: Install dependencies into embedded Python runtime
#===============================================================================
function Install-Dependencies {
    $pythonExe = Join-Path $BUILD_DIR "python\python.exe"
    if (-not (Test-Path -LiteralPath $pythonExe)) { throw "Embedded Python not found: $pythonExe" }
    Log-Step "Installing locked wheels offline..."
    & $pythonExe (Join-Path $PROJECT_ROOT "scripts\installer_dependencies.py") install --mode $modeLower
    if ($LASTEXITCODE -ne 0) { throw "Locked offline dependency installation failed" }
}

#===============================================================================
# Step 4.5: Copy critical Windows runtime DLLs for PyTorch
#===============================================================================
function Prepare-WindowsRuntimeDlls {
    Log-Step "Preparing Windows runtime DLLs..."

    $pythonDir = Join-Path $BUILD_DIR "python"
    $system32 = Join-Path $env:WINDIR "System32"
    $dlls = @(
        "libomp140.x86_64.dll",
        "vcomp140.dll",
        "vcruntime140.dll",
        "vcruntime140_1.dll",
        "msvcp140.dll"
    )

    foreach ($dll in $dlls) {
        $src = Join-Path $system32 $dll
        $dst = Join-Path $pythonDir $dll
        if (Test-Path $src) {
            Copy-Item $src -Destination $dst -Force
            Log-Info "  Copied $dll"
        } else {
            Log-Warn "  Runtime DLL not found: $src"
        }
    }
}

#===============================================================================
# Step 5: Copy WingScribe source code
#===============================================================================
function Copy-SourceCode {
    Log-Step "Staging audited source, examples and documentation..."
    & $BuildPython (Join-Path $PROJECT_ROOT "scripts\installer_payload.py") --mode $modeLower
    if ($LASTEXITCODE -ne 0) {
        throw "Payload staging failed; do not package this build"
    }
    Log-Success "Audited payload staged (personal configuration excluded)"
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
    $configFile = Join-Path $PROJECT_ROOT "config\settings.example.yaml"
    if (Test-Path $configFile) {
        $configContent = Get-Content $configFile -Raw
        if ($configContent -match 'yolo_model:\s*(\S+\.pt)') {
            $yoloModelFull = $Matches[1].Trim('"', "'")
        }
    }

    # Extract just the filename from the full path
    $yoloModel = [System.IO.Path]::GetFileName($yoloModelFull)
    $modelPath = Join-Path $modelDir $yoloModel

    if (Test-Path $modelPath) {
        Log-Info "  YOLO model already exists: $yoloModel"
    } else {
        Log-Info "  Checking for YOLO model..."

        # 1. Require bundled model in installer/models for offline-friendly installers.
        $localModel = Join-Path $INSTALLER_DIR "models\$yoloModel"
        if (Test-Path $localModel) {
            Copy-Item $localModel -Destination $modelPath -Force
            Log-Success "  Copied YOLO model from installer/models"
            return
        }

        throw "Bundled YOLO model missing: $localModel. Add this file to repository before packaging."
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
if not exist "%APP_ROOT%\python\python.exe" (
    echo Error: Embedded Python not found
    pause
    exit /b 1
)
"%APP_ROOT%\python\python.exe" "%APP_ROOT%\src\web\app.py"
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
# Step 8: Self-test runtime before packaging
#===============================================================================
function Test-EmbeddedRuntime {
    Log-Step "Running embedded runtime self-test..."

    $pythonExe = Join-Path $BUILD_DIR "python\python.exe"
    if (-not (Test-Path $pythonExe)) {
        throw "Self-test failed: embedded python not found"
    }

    & $pythonExe (Join-Path $PROJECT_ROOT "scripts\installer_dependencies.py") check --mode $modeLower
    if ($LASTEXITCODE -ne 0) { throw "Cached runtime differs from the locked variant" }

    & $pythonExe -c "import torch,fastapi,uvicorn; print(torch.__version__)"
    if ($LASTEXITCODE -ne 0) {
        throw "Self-test failed: python import check failed"
    }

    $yoloModelPath = Join-Path $BUILD_DIR "data\models\yolo26n.pt"
    if (Test-Path $yoloModelPath) {
        & $pythonExe -c "from ultralytics import YOLO; YOLO(r'$yoloModelPath'); print('yolo-load-ok')"
        if ($LASTEXITCODE -ne 0) {
            throw "Self-test failed: yolo model load failed ($yoloModelPath)"
        }
    } else {
        Log-Warn "Self-test skip: model not found at $yoloModelPath"
    }

    $requiredStaticFiles = @(
        "src\web\static\css\bootstrap.min.css",
        "src\web\static\js\bootstrap.bundle.min.js",
        "src\web\static\favicon.ico"
    )
    foreach ($relPath in $requiredStaticFiles) {
        $fullPath = Join-Path $BUILD_DIR $relPath
        if (-not (Test-Path $fullPath)) {
            throw "Self-test failed: missing static asset $relPath"
        }
    }

    $bat = Join-Path $BUILD_DIR "scripts\start_web.bat"
    if (-not (Test-Path $bat)) {
        throw "Self-test failed: start_web.bat not found"
    }
    Push-Location $BUILD_DIR
    try {
        cmd /c "scripts\start_web.bat --self-test"
        if ($LASTEXITCODE -ne 0) {
            throw "Self-test failed: start_web.bat --self-test failed"
        }
    } finally {
        Pop-Location
    }

    Log-Success "Embedded runtime self-test passed"
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
    & $BuildPython (Join-Path $PROJECT_ROOT "scripts\export_installer_lock.py") --check
    if ($LASTEXITCODE -ne 0) { throw "Installer lock is stale or build Python is unavailable" }
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
        if (-not (Prepare-ExifTool)) { throw "ExifTool preparation failed" }
    }

    # Even cached/skip mode must have an executable ExifTool runtime.
    $exifExe = Join-Path $TOOLS_DIR "exiftool.exe"
    if (-not (Test-Path -LiteralPath $exifExe)) { throw "ExifTool runtime is missing" }
    & $exifExe -ver
    if ($LASTEXITCODE -ne 0) { throw "ExifTool runtime self-test failed" }

    # Download embeddable Python runtime
    if (-not $SkipPython) {
        Download-Python
        Prepare-WindowsRuntimeDlls
    }

    if ($SkipDepsInstall) {
        Log-Warn "SkipDepsInstall enabled: skipping pip dependency install step"
    } else {
        Install-Dependencies
    }
    # Keep installed wheel contents intact; no post-install package trimming.
    Copy-SourceCode
    Download-YoloModel
    Copy-StartupScripts
    Prepare-FirstRunWizard
    Test-EmbeddedRuntime

    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "  $modeUpper Build Complete!" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Build output:" -ForegroundColor White
    Write-Host "    Embedded Python: $BUILD_DIR\python (portable runtime + packages)" -ForegroundColor Gray
    Write-Host "    Source code: $BUILD_DIR\src" -ForegroundColor Gray
    Write-Host ""
    Write-Host "  Next steps:" -ForegroundColor White
    Write-Host "    1. Download Inno Setup: https://jrsoftware.org/isdl.php" -ForegroundColor Gray
    if ($modeLower -eq "gpu") {
        Write-Host "    2. Run: iscc installer\installer-gpu.iss" -ForegroundColor Gray
    } else {
        Write-Host "    2. Run: iscc installer\installer.iss" -ForegroundColor Gray
    }
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
