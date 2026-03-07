# Kill processes
taskkill /F /IM python.exe 2>$null
taskkill /F /IM uvicorn.exe 2>$null

# Rename old installer
$oldFile = "D:\Code\gemini\wingscribe\installer\Output\WingScribe-Setup-1.0.0.exe"
$newFile = "D:\Code\gemini\wingscribe\installer\Output\WingScribe-Setup-1.0.0-old.exe"

if (Test-Path $oldFile) {
    try {
        Move-Item -Path $oldFile -Destination $newFile -Force
        Write-Host "Renamed old installer to $newFile"
    } catch {
        Write-Host "Failed to rename: $_"
    }
}

# Compile new installer
cd "D:\Code\gemini\wingscribe\installer"
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
