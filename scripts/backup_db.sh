#!/bin/bash
# ============================================================
#
# 用途: 备份 SQLite 数据库文件
# 特性: 使用 SQLite .backup 命令确保备份安全（支持数据库正在使用时备份）
#
# 使用方法:
#   ./backup_db.sh "data/db/wingscribe.db" "/mnt/nas/backup/wingscribe" 7
#
# 参数:
#   $1 源数据库文件路径 (默认: data/db/wingscribe.db)
#   $2 备份目标目录 (默认: /mnt/nas/backup/wingscribe)
#   $3 保留最近几天的备份 (默认: 7)
#
# 定时任务设置 (每天凌晨 3 点执行):
#   # 添加到 crontab
#   crontab -e
#   # 添加以下行:
#   0 3 * * * /path/to/scripts/backup_db.sh >> /var/log/wingscribe_backup.log 2>&1
#
# ============================================================

# WingScribe Database Backup Script (Linux/macOS)
# 使用 SQLite .backup 命令确保备份安全

# 默认值
SOURCE="${1:-data/db/wingscribe.db}"
DEST_DIR="${2:-/mnt/nas/backup/wingscribe}"
KEEP_DAYS="${3:-7}"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# 检查源文件
if [[ ! -f "$SOURCE" ]]; then
    echo -e "${RED}错误: 源数据库文件不存在: $SOURCE${NC}"
    exit 1
fi

# 绝对路径
SOURCE=$(readlink -f "$SOURCE")

# 创建目标目录
if [[ ! -d "$DEST_DIR" ]]; then
    echo -e "${YELLOW}创建备份目录: $DEST_DIR${NC}"
    mkdir -p "$DEST_DIR"
fi

# 生成时间戳
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="wingscribe_${TIMESTAMP}.db"
BACKUP_PATH="$DEST_DIR/$BACKUP_FILE"

echo -e "${CYAN}开始备份数据库...${NC}"
echo -e "  源文件: $SOURCE"
echo -e "  目标文件: $BACKUP_PATH"

# 使用 sqlite3 .backup 命令进行安全备份
if sqlite3 "$SOURCE" ".backup '$BACKUP_PATH'"; then
    FILE_SIZE=$(du -h "$BACKUP_PATH" | cut -f1)
    echo -e "${GREEN}备份成功! 文件大小: $FILE_SIZE${NC}"
else
    echo -e "${RED}错误: 备份失败${NC}"
    exit 1
fi

# 清理旧备份
echo -e "${CYAN}清理旧备份（保留最近 $KEEP_DAYS 天）...${NC}"

# 计算截止日期
CUTOFF_DATE=$(date -d "$KEEP_DAYS days ago" +%s)

# 查找并删除旧备份
OLD_COUNT=0
for backup in "$DEST_DIR"/wingscribe_*.db; do
    if [[ -f "$backup" ]]; then
        FILE_DATE=$(stat -c %Y "$backup" 2>/dev/null || stat -f %m "$backup" 2>/dev/null)
        if [[ $FILE_DATE -lt $CUTOFF_DATE ]]; then
            echo -e "${YELLOW}  删除: $(basename "$backup")${NC}"
            rm -f "$backup"
            ((OLD_COUNT++))
        fi
    fi
done

if [[ $OLD_COUNT -gt 0 ]]; then
    echo -e "${GREEN}已清理 $OLD_COUNT 个旧备份${NC}"
else
    echo -e "没有需要清理的旧备份"
fi

# 显示当前备份列表
echo -e "\n${CYAN}当前备份列表:${NC}"
ls -lh "$DEST_DIR"/wingscribe_*.db 2>/dev/null | sort -k6 -k7 -k8 -r | while read -r line; do
    echo "  $line"
done

echo -e "\n${GREEN}备份完成!${NC}"
