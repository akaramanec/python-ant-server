#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DB_FILE="$PROJECT_DIR/heart_data.db"
BACKUP_DIR="$PROJECT_DIR/backups"
RETENTION_DAYS=14

mkdir -p "$BACKUP_DIR"

if [[ ! -f "$DB_FILE" ]]; then
  echo "DB file not found: $DB_FILE"
  exit 1
fi

TS="$(date +%F_%H-%M-%S)"
TMP_FILE="$BACKUP_DIR/heart_data_${TS}.db.tmp"
FINAL_FILE="$BACKUP_DIR/heart_data_${TS}.db"

# Consistent SQLite backup even when DB is in use.
sqlite3 "$DB_FILE" ".backup '$TMP_FILE'"
mv "$TMP_FILE" "$FINAL_FILE"

# Delete backups older than retention period.
find "$BACKUP_DIR" -type f -name "heart_data_*.db" -mtime +$RETENTION_DAYS -delete

echo "Backup created: $FINAL_FILE"
