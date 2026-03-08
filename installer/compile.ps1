# Kill processes
taskkill /F /IM python.exe 2>$null
taskkill /F /IM uvicorn.exe 2>$null

# Get version from version.txt (created by build.ps1)
$VERSION_FILE = "D:\Code\gemini\wingscribe\installer\version.txt"
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
$cpuIss = "D:\Code\gemini\wingscribe\installer\installer.iss"
$cpuOutput = "D:\Code\gemini\wingscribe\installer\Output\WingScribe-Setup-CPU-$version.exe"
Write-Host "Compiling CPU installer..."
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" /DAppVersion=$version $cpuIss

# Compile GPU installer
$gpuIss = "D:\Code\gemini\wingscribe\installer\installer-gpu.iss"
$gpuOutput = "D:\Code\gemini\wingscribe\installer\Output\WingScribe-Setup-GPU-$version.exe"
Write-Host "Compiling GPU installer..."
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" /DAppVersion=$version $gpuIss

Write-Host "Done! CPU: $cpuOutput"
Write-Host "Done! GPU: $gpuOutput"
