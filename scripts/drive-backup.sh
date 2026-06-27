#!/bin/bash
# drive-backup.sh — Daily backup of uncommitted files + pg_dump to Google Drive
set -euo pipefail

DATE=$(date +%Y-%m-%d)
WORK_DIR=$(mktemp -d)
REMOTE="gdrive-oauth"
REMOTE_ROOT="vps-backup"
LOG_TAG="drive-backup"
RETENTION_DAYS=7

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') $LOG_TAG: $*"
    logger -t "$LOG_TAG" "$@"
}

cleanup() {
    rm -rf "$WORK_DIR"
}
trap cleanup EXIT

log "Starting daily backup for $DATE"

# 1. pg_dump portfolio DB
log "Dumping portfolio database..."
if docker exec root-portfolio_postgres-1 pg_dump -U portfolio_user -d portfolio 2>&1 | gzip > "$WORK_DIR/portfolio_db.sql.gz"; then
    SIZE=$(stat -c%s "$WORK_DIR/portfolio_db.sql.gz" 2>/dev/null || echo 0)
    log "pg_dump complete ($SIZE bytes)"
else
    log "WARNING: pg_dump failed (container down?); skipping DB backup"
    rm -f "$WORK_DIR/portfolio_db.sql.gz"
fi

# 2. Archive uncommitted files
log "Archiving uncommitted files..."
tar czf "$WORK_DIR/uncommitted.tar.gz" \
    -C /root \
    --ignore-failed-read \
    research/ \
    scripts/trigger_youtube_monitor.py \
    windmill/u/admin/factor_scorer.script.yaml \
    windmill/u/admin/idea_extractor.script.yaml \
    windmill/u/admin/replacement_screener.script.yaml \
    windmill/u/admin/telegram_utils.py \
    .env \
    shared/keys.md \
    shared/windmill-sa-key.json \
    .config/rclone/rclone.conf 2>&1 | logger -t "$LOG_TAG" || true
SIZE=$(stat -c%s "$WORK_DIR/uncommitted.tar.gz" 2>/dev/null || echo 0)
log "Archive complete ($SIZE bytes)"

# 3. Upload to Drive
log "Uploading to $REMOTE:$REMOTE_ROOT/$DATE/..."
rclone copy "$WORK_DIR/" "$REMOTE:$REMOTE_ROOT/$DATE/" --progress 2>&1 | logger -t "$LOG_TAG"
log "Upload complete"

# 4. Cleanup folders older than RETENTION_DAYS
log "Cleaning up backups older than $RETENTION_DAYS days..."
CUTOFF=$(date -d "-$RETENTION_DAYS days" +%Y-%m-%d)
rclone lsf "$REMOTE:$REMOTE_ROOT/" --dirs-only 2>/dev/null | while read -r dir; do
    dir_date="${dir%/}"
    if [[ $dir_date =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] && [[ "$dir_date" < "$CUTOFF" ]]; then
        log "Purging old backup: $dir_date"
        rclone purge "$REMOTE:$REMOTE_ROOT/$dir_date" 2>&1 | logger -t "$LOG_TAG" || true
    fi
done
log "Cleanup complete"

log "Backup finished successfully for $DATE"
