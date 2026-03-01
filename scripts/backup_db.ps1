# WingScribe Database Backup Script (Windows PowerShell)
# ============================================================
#
# 用途: 备份 SQLite 数据库文件
# 特性: 使用 SQLite .backup 命令确保备份安全（支持数据库正在使用时备份）
#
# 使用方法:
#   .\backup_db.ps1 -Source "data\db\wingscribe.db" -Destination "Y:\备份\wingscribe"
#
# 参数:
#   -Source     源数据库文件路径 (默认: data\db\wingscribe.db)
#   -Destination 备份目标目录 (默认: Y:\备份\wingscribe)
#   -KeepDays   保留最近几天的备份 (默认: 7)
#
# 定时任务设置 (每天凌晨 3 点执行):
#   schtasks /create /tn "WingScribe Backup" /tr "powershell -File C:\path\to\scripts\backup_db.ps1" /sc daily /st 03:00
#
# ============================================================

param(
    [string]$Source = "data\db\wingscribe.db",      # 源数据库文件（相对于当前目录）
    [string]$Destination = "Y:\备份\wingscribe",      # 备份目标目录
    [int]$KeepDays = 7                               # 保留最近几天的备份
)

$ErrorActionPreference = "Stop"

# 解析绝对路径
$SourcePath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Source)
$DestDir = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Destination)

# 检查源文件是否存在
if (-not (Test-Path $SourcePath)) {
    Write-Host "错误: 源数据库文件不存在: $SourcePath" -ForegroundColor Red
    exit 1
}

# 创建目标目录（如果不存在）
if (-not (Test-Path $DestDir)) {
    Write-Host "创建备份目录: $DestDir" -ForegroundColor Yellow
    New-Item -ItemType Directory -Path $DestDir -Force | Out-Null
}

# 生成备份文件名（带时间戳）
$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$BackupFileName = "wingscribe_$Timestamp.db"
$BackupPath = Join-Path $DestDir $BackupFileName

Write-Host "开始备份数据库..." -ForegroundColor Cyan
Write-Host "  源文件: $SourcePath"
Write-Host "  目标文件: $BackupPath"

# 使用 sqlite3 .backup 命令进行安全备份
$sqliteCmd = "sqlite3 `"$SourcePath`" `".backup '$BackupPath'`""

try {
    Invoke-Expression $sqliteCmd

    if (Test-Path $BackupPath) {
        $fileSize = (Get-Item $BackupPath).Length / 1MB
        Write-Host "备份成功! 文件大小: $([math]::Round($fileSize, 2)) MB" -ForegroundColor Green
    } else {
        Write-Host "错误: 备份文件未创建" -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host "错误: 备份失败 - $_" -ForegroundColor Red
    exit 1
}

# 清理旧备份（保留最近 N 天）
Write-Host "清理旧备份（保留最近 $KeepDays 天）..." -ForegroundColor Cyan

$CutoffDate = (Get-Date).AddDays(-$KeepDays)
$OldBackups = Get-ChildItem -Path $DestDir -Filter "wingscribe_*.db" |
    Where-Object { $_.LastWriteTime -lt $CutoffDate }

if ($OldBackups) {
    foreach ($file in $OldBackups) {
        Write-Host "  删除: $($file.Name)" -ForegroundColor Yellow
        Remove-Item $file.FullName -Force
    }
    Write-Host "已清理 $($OldBackups.Count) 个旧备份" -ForegroundColor Green
} else {
    Write-Host "没有需要清理的旧备份" -ForegroundColor Gray
}

# 显示当前备份列表
Write-Host "`n当前备份列表:" -ForegroundColor Cyan
Get-ChildItem -Path $DestDir -Filter "wingscribe_*.db" |
    Sort-Object LastWriteTime -Descending |
    ForEach-Object {
        $size = [math]::Round($_.Length / 1MB, 2)
        Write-Host "  $($_.Name) - $size MB - $($_.LastWriteTime.ToString('yyyy-MM-dd HH:mm'))"
    }

Write-Host "`n备份完成!" -ForegroundColor Green
