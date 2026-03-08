# Kill processes
taskkill /F /IM python.exe 2>$null
taskkill /F /IM uvicorn.exe 2>$null

$INSTALLER_DIR = $PSScriptRoot
$PROJECT_ROOT = Split-Path $INSTALLER_DIR -Parent

# Get version from version.txt (created by build.ps1)
$VERSION_FILE = Join-Path $INSTALLER_DIR "version.txt"
if (Test-Path $VERSION_FILE) {
    $version = Get-Content $VERSION_FILE -Raw -Encoding UTF8
    $version = $version.Trim()
    # Remove BOM if present
    if ($version.StartsWith([char]0xFEFF)) {
        $version = $version.Substring(1)
    }
    if ([string]::IsNullOrWhiteSpace($version)) {
        $version = "1.0.0"
    }
} else {
    $version = "1.0.0"
    Write-Host "Warning: version.txt not found, using default: $version"
}

Write-Host "Compiling installer version: $version"

# Compile CPU installer
$cpuIss = Join-Path $INSTALLER_DIR "installer.iss"
$cpuOutput = Join-Path $INSTALLER_DIR "Output\WingScribe-Setup-CPU-$version.exe"
Write-Host "Compiling CPU installer..."
$iscc = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $iscc)) {
    $iscc = "C:\Program Files\Inno Setup 6\ISCC.exe"
}
& $iscc /DAppVersion=$version $cpuIss

# Compile GPU installer
$gpuIss = Join-Path $INSTALLER_DIR "installer-gpu.iss"
$gpuOutput = Join-Path $INSTALLER_DIR "Output\WingScribe-Setup-GPU-$version.exe"
Write-Host "Compiling GPU installer..."
& $iscc /DAppVersion=$version $gpuIss

Write-Host "Done! CPU: $cpuOutput"
Write-Host "Done! GPU: $gpuOutput"
