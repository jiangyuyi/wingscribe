# WingScribe Database Backup Script (Windows PowerShell)
# ============================================================
#
# Usage: Backup SQLite database safely using Python sqlite3 module
#
# Examples:
#   .\backup_db.ps1 -Source "..\data\db\wingscribe.db" -Destination "Y:\Backup\wingscribe"
#
# Parameters:
#   -Source      Source database file (default: ..\data\db\wingscribe.db)
#   -Destination Backup destination directory (default: Y:\Backup\wingscribe)
#   -KeepDays    Number of days to keep backups (default: 7)
#
# Schedule as daily task (3 AM):
#   schtasks /create /tn "WingScribe Backup" /tr "powershell -File C:\path\to\scripts\backup_db.ps1" /sc daily /st 03:00
#
# ============================================================

param(
    [string]$Source = "..\data\db\wingscribe.db",
    [string]$Destination = "Y:\Backup\wingscribe",
    [int]$KeepDays = 7
)

$ErrorActionPreference = "Stop"

# Resolve absolute paths
$SourcePath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Source)
$DestDir = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Destination)

# Check source file exists
if (-not (Test-Path $SourcePath)) {
    Write-Host "Error: Source database file not found: $SourcePath" -ForegroundColor Red
    exit 1
}

# Create destination directory if needed
if (-not (Test-Path $DestDir)) {
    Write-Host "Creating backup directory: $DestDir" -ForegroundColor Yellow
    New-Item -ItemType Directory -Path $DestDir -Force | Out-Null
}

# Generate backup filename with timestamp
$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$BackupFileName = "wingscribe_$Timestamp.db"
$BackupPath = Join-Path $DestDir $BackupFileName

Write-Host "Starting database backup..." -ForegroundColor Cyan
Write-Host "  Source: $SourcePath"
Write-Host "  Target: $BackupPath"

# Use Python sqlite3 for backup
$pythonScript = @"
import sqlite3
import sys
try:
    source = r'$SourcePath'
    target = r'$BackupPath'
    conn = sqlite3.connect(source)
    backup = sqlite3.connect(target)
    conn.backup(backup)
    backup.close()
    conn.close()
    print('OK')
except Exception as e:
    print(f'ERROR: {e}', file=sys.stderr)
    sys.exit(1)
"@

try {
    $result = python -c $pythonScript 2>&1

    if ($LASTEXITCODE -eq 0 -and $result -eq "OK") {
        if (Test-Path $BackupPath) {
            $fileSize = (Get-Item $BackupPath).Length / 1MB
            Write-Host "Backup successful! File size: $([math]::Round($fileSize, 2)) MB" -ForegroundColor Green
        } else {
            Write-Host "Error: Backup file was not created" -ForegroundColor Red
            exit 1
        }
    } else {
        Write-Host "Error: Backup failed - $result" -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host "Error: Failed to run Python - $_" -ForegroundColor Red
    exit 1
}

# Clean old backups (keep last N days)
Write-Host "Cleaning old backups (keeping last $KeepDays days)..." -ForegroundColor Cyan

$CutoffDate = (Get-Date).AddDays(-$KeepDays)
$OldBackups = Get-ChildItem -Path $DestDir -Filter "wingscribe_*.db" |
    Where-Object { $_.LastWriteTime -lt $CutoffDate }

if ($OldBackups) {
    foreach ($file in $OldBackups) {
        Write-Host "  Deleting: $($file.Name)" -ForegroundColor Yellow
        Remove-Item $file.FullName -Force
    }
    Write-Host "Cleaned $($OldBackups.Count) old backup(s)" -ForegroundColor Green
} else {
    Write-Host "No old backups to clean" -ForegroundColor Gray
}

# Show current backup list
Write-Host "`nCurrent backup list:" -ForegroundColor Cyan
Get-ChildItem -Path $DestDir -Filter "wingscribe_*.db" |
    Sort-Object LastWriteTime -Descending |
    ForEach-Object {
        $size = [math]::Round($_.Length / 1MB, 2)
        Write-Host "  $($_.Name) - $size MB - $($_.LastWriteTime.ToString('yyyy-MM-dd HH:mm'))"
    }

Write-Host "`nBackup complete!" -ForegroundColor Green
