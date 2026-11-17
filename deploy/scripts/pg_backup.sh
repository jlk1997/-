#!/usr/bin/env bash
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/var/backups/vibe-pg}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
DB_NAME="${POSTGRES_DB:-vibe_sorcery}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

mkdir -p "$BACKUP_DIR"

echo "[$(date)] Starting backup of $DB_NAME..."
pg_dump "$DB_NAME" | gzip > "$BACKUP_DIR/${DB_NAME}_${TIMESTAMP}.sql.gz"
echo "[$(date)] Backup complete: ${DB_NAME}_${TIMESTAMP}.sql.gz"

# Cleanup old backups
find "$BACKUP_DIR" -name "*.sql.gz" -mtime +"$RETENTION_DAYS" -delete
echo "[$(date)] Cleaned backups older than $RETENTION_DAYS days"
