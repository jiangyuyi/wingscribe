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
    [string]$Version = "3.0.0",
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
$TOOLS_DIR = Join-Path $BUILD_DIR "tools"
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
    Log-Step "Preparing hash-pinned Python and pip runtime..."
    & $BuildPython (Join-Path $PROJECT_ROOT "scripts\installer_runtime.py") --mode $modeLower
    if ($LASTEXITCODE -ne 0) { throw "Pinned Python runtime preparation failed" }
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
    Log-Step "Preparing pinned bundled ExifTool runtime..."
    & $BuildPython (Join-Path $PROJECT_ROOT "scripts\installer_runtime.py") --mode $modeLower --component exiftool | Out-Host
    return ($LASTEXITCODE -eq 0)
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

    $previousYoloConfig = $env:YOLO_CONFIG_DIR
    $env:YOLO_CONFIG_DIR = Join-Path $BUILD_DIR "data\runtime-config"
    Ensure-Directory $env:YOLO_CONFIG_DIR
    try {
    $yoloModelPath = Join-Path $BUILD_DIR "data\models\yolo26n.pt"
    if (Test-Path $yoloModelPath) {
        & $pythonExe -c "from ultralytics import YOLO; YOLO(r'$yoloModelPath'); print('yolo-load-ok')"
        if ($LASTEXITCODE -ne 0) {
            throw "Self-test failed: yolo model load failed ($yoloModelPath)"
        }
    } else {
        throw "Self-test failed: model not found at $yoloModelPath"
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
    } finally {
        $env:YOLO_CONFIG_DIR = $previousYoloConfig
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

    & $BuildPython (Join-Path $PROJECT_ROOT "scripts\installer_runtime.py") --mode $modeLower --component exiftool --check
    if ($LASTEXITCODE -ne 0) { throw "Pinned ExifTool runtime verification failed" }

    # Download embeddable Python runtime
    if (-not $SkipPython) {
        Download-Python
    }

    & $BuildPython (Join-Path $PROJECT_ROOT "scripts\installer_runtime.py") --mode $modeLower --check
    if ($LASTEXITCODE -ne 0) { throw "Pinned Python runtime verification failed" }

    if ($SkipDepsInstall) {
        Log-Warn "SkipDepsInstall enabled: skipping pip dependency install step"
    } else {
        Install-Dependencies
    }
    # Keep installed wheel contents intact; no post-install package trimming.
    & (Join-Path $PROJECT_ROOT "scripts\prepare_vcredist.ps1") -Mode $modeLower
    Copy-SourceCode
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
