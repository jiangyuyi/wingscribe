#!/bin/bash
# ============================================================
#
# Usage: Backup SQLite database safely using Python sqlite3 module
#
# Examples:
#   ./backup_db.sh "data/db/wingscribe.db" "/mnt/nas/backup/wingscribe" 7
#
# Parameters:
#   $1 Source database file (default: data/db/wingscribe.db)
#   $2 Backup destination directory (default: /mnt/nas/backup/wingscribe)
#   $3 Number of days to keep backups (default: 7)
#
# Schedule as daily task (3 AM):
#   # Edit crontab
#   crontab -e
#   # Add this line:
#   0 3 * * * /path/to/scripts/backup_db.sh >> /var/log/wingscribe_backup.log 2>&1
#
# ============================================================

# Default values
SOURCE="${1:-data/db/wingscribe.db}"
DEST_DIR="${2:-/mnt/nas/backup/wingscribe}"
KEEP_DAYS="${3:-7}"

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Check source file
if [[ ! -f "$SOURCE" ]]; then
    echo -e "${RED}Error: Source database file not found: $SOURCE${NC}"
    exit 1
fi

# Absolute path
SOURCE=$(readlink -f "$SOURCE")

# Create destination directory
if [[ ! -d "$DEST_DIR" ]]; then
    echo -e "${YELLOW}Creating backup directory: $DEST_DIR${NC}"
    mkdir -p "$DEST_DIR"
fi

# Generate timestamp
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="wingscribe_${TIMESTAMP}.db"
BACKUP_PATH="$DEST_DIR/$BACKUP_FILE"

echo -e "${CYAN}Starting database backup...${NC}"
echo -e "  Source: $SOURCE"
echo -e "  Target: $BACKUP_PATH"

# Use Python sqlite3 for backup
python3 -c "
import sqlite3
import sys

try:
    source = r'$SOURCE'
    target = r'$BACKUP_PATH'
    conn = sqlite3.connect(source)
    backup = sqlite3.connect(target)
    conn.backup(backup)
    backup.close()
    conn.close()
    print('OK')
except Exception as e:
    print(f'ERROR: {e}', file=sys.stderr)
    sys.exit(1)
"

if [[ $? -eq 0 ]]; then
    FILE_SIZE=$(du -h "$BACKUP_PATH" | cut -f1)
    echo -e "${GREEN}Backup successful! File size: $FILE_SIZE${NC}"
else
    echo -e "${RED}Error: Backup failed${NC}"
    exit 1
fi

# Clean old backups
echo -e "${CYAN}Cleaning old backups (keeping last $KEEP_DAYS days)...${NC}"

# Calculate cutoff date
CUTOFF_DATE=$(date -d "$KEEP_DAYS days ago" +%s)

# Find and delete old backups
OLD_COUNT=0
for backup in "$DEST_DIR"/wingscribe_*.db; do
    if [[ -f "$backup" ]]; then
        FILE_DATE=$(stat -c %Y "$backup" 2>/dev/null || stat -f %m "$backup" 2>/dev/null)
        if [[ $FILE_DATE -lt $CUTOFF_DATE ]]; then
            echo -e "${YELLOW}  Deleting: $(basename "$backup")${NC}"
            rm -f "$backup"
            ((OLD_COUNT++))
        fi
    fi
done

if [[ $OLD_COUNT -gt 0 ]]; then
    echo -e "${GREEN}Cleaned $OLD_COUNT old backup(s)${NC}"
else
    echo -e "No old backups to clean"
fi

# Show current backup list
echo -e "\n${CYAN}Current backup list:${NC}"
ls -lh "$DEST_DIR"/wingscribe_*.db 2>/dev/null | sort -k6 -k7 -k8 -r | while read -r line; do
    echo "  $line"
done

echo -e "\n${GREEN}Backup complete!${NC}"
