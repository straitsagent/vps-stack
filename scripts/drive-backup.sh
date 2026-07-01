#!/bin/bash
# drive-backup.sh — Daily backup of non-git assets to Google Drive
# Git-tracked files (windmill, docs, scripts, agent, hermes, openclaw, docker-compose etc.)
# are excluded — they are recoverable from the git remote.
set -euo pipefail

DATE=$(date +%Y-%m-%d)
WORK_DIR=$(mktemp -d)
REMOTE="gdrive-oauth"
DEST="$REMOTE:$DATE"
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

# 1. pg_dump — live DB state (schema/seed in git; price_history/positions/fx_rates are not)
log "Dumping portfolio database..."
if docker exec root-portfolio_postgres-1 pg_dump -U portfolio_user -d portfolio 2>&1 | gzip > "$WORK_DIR/portfolio_db.sql.gz"; then
    SIZE=$(stat -c%s "$WORK_DIR/portfolio_db.sql.gz" 2>/dev/null || echo 0)
    log "pg_dump complete ($SIZE bytes)"
    rclone copy "$WORK_DIR/portfolio_db.sql.gz" "$DEST/" 2>&1 | logger -t "$LOG_TAG"
    log "portfolio_db.sql.gz uploaded"
else
    log "WARNING: pg_dump failed (container down?); skipping DB backup"
fi

# 1b. Affection DB — separate database (affection bot data)
log "Dumping affection database..."
if docker exec root-portfolio_postgres-1 pg_dump -U affection_user -d affection 2>&1 | gzip > "$WORK_DIR/affection_db.sql.gz"; then
    SIZE=$(stat -c%s "$WORK_DIR/affection_db.sql.gz" 2>/dev/null || echo 0)
    log "affection pg_dump complete ($SIZE bytes)"
    rclone copy "$WORK_DIR/affection_db.sql.gz" "$DEST/" 2>&1 | logger -t "$LOG_TAG"
    log "affection_db.sql.gz uploaded"
else
    log "WARNING: affection pg_dump failed (container down?); skipping"
fi

# 2. Secrets — gitignored by design
log "Syncing secrets/..."
rclone copy /root/secrets/ "$DEST/secrets/" 2>&1 | logger -t "$LOG_TAG"
log "secrets/ sync complete"

# 3. Research — runtime LLM outputs, not committed
log "Syncing research/..."
rclone copy /root/research/ "$DEST/research/" 2>&1 | logger -t "$LOG_TAG"
log "research/ sync complete"

# 4. Config files not tracked in git
log "Uploading config files..."
mkdir -p "$WORK_DIR/config"
cp /root/.config/rclone/rclone.conf "$WORK_DIR/config/rclone.conf"
cp /etc/systemd/system/drive-backup.service "$WORK_DIR/config/drive-backup.service"
cp /etc/systemd/system/drive-backup.timer "$WORK_DIR/config/drive-backup.timer"
cp /root/.claude/settings.json "$WORK_DIR/config/claude-settings.json"
rclone copy "$WORK_DIR/config/" "$DEST/config/" 2>&1 | logger -t "$LOG_TAG"
rclone copy /root/.claude/commands/ "$DEST/config/claude-commands/" 2>&1 | logger -t "$LOG_TAG"
rclone copy /root/.claude/projects/-root/memory/ "$DEST/config/claude-memory/" 2>&1 | logger -t "$LOG_TAG"
log "Config files uploaded"

# 5. Hermes agent state — the hermes_state Docker volume (authoritative /workspace/.env,
#    config.yaml, self-authored skills, cron jobs, memory). Caches excluded (regenerable).
HERMES_VOL=/var/lib/docker/volumes/root_hermes_state/_data
if [ -d "$HERMES_VOL" ]; then
    log "Syncing hermes_state volume (excluding caches)..."
    rclone copy "$HERMES_VOL" "$DEST/hermes_state/" \
        --exclude '.cache/**' --exclude '.npm/**' \
        --exclude 'audio_cache/**' --exclude 'node_modules/**' \
        --exclude 'skills/.hub/**' \
        2>&1 | logger -t "$LOG_TAG"
    log "hermes_state sync complete"
else
    log "WARNING: hermes_state volume not found at $HERMES_VOL; skipping"
fi

# 6. Purge dated backup folders older than RETENTION_DAYS
log "Cleaning up backups older than $RETENTION_DAYS days..."
CUTOFF=$(date -d "-$RETENTION_DAYS days" +%Y-%m-%d)
rclone lsf "$REMOTE:" --dirs-only 2>/dev/null | while read -r dir; do
    dir_date="${dir%/}"
    if [[ $dir_date =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] && [[ "$dir_date" < "$CUTOFF" ]]; then
        log "Purging old backup: $dir_date"
        rclone purge "$REMOTE:$dir_date" 2>&1 | logger -t "$LOG_TAG" || true
    fi
done
log "Cleanup complete"

log "Backup finished successfully for $DATE"
