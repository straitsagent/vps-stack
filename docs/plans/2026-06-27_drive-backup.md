---
Subject: Daily Google Drive backup — pg_dump + uncommitted files
Date: 2026-06-27
Status: done
Planner model: deepseek-v4-flash (opencode)
Executor model: deepseek-v4-flash (opencode)
Risk tier: LOW (mechanical — no scoring, no LLM, no new DB tables)
Hard Rules in force: [9, 15, 17]
Complies with: docs/EXECUTOR_CONTRACT.md
Files to read before coding: docs/OPERATIONS.md, shared/keys.md
---

# Plan: Daily Google Drive Backup

## Context

No automated backup exists for the portfolio DB or uncommitted working tree
changes. rclone (v1.74.2) is installed and a GCP service account
(`vps-backup-sa@vps-stack-500302`) with Drive API access exists, but they
are not wired together. The backup config (`rclone.conf.bak.20260627`) has a
`[gdrive-sa]` section using the SA key; the live config is bare (no auth).

Loss of the VPS or DB volume would lose ~10 days of uncommitted work
(Plan A/B code, research outputs, schema migrations).

## What it does

A systemd-timer-driven bash script that runs daily at 04:00 SGT:

1. **pg_dump** the `portfolio` DB via `docker exec` into `portfolio_db.sql.gz`
2. **Archive** uncommitted files + credentials into `uncommitted.tar.gz`
3. **Upload** both to `gdrive-sa:vps-backup/YYYY-MM-DD/` via rclone
4. **Purge** Drive folders older than 7 days

## Files changed

| Action | Path | Change |
|--------|------|--------|
| Edit | `/root/.config/rclone/rclone.conf` | Replace bare `[gdrive]` with `[gdrive-sa]` using SA key |
| Create | `/root/scripts/drive-backup.sh` | ~65-line bash backup script |
| Create | `/etc/systemd/system/drive-backup.service` | oneshot service unit |
| Create | `/etc/systemd/system/drive-backup.timer` | daily at 20:00 UTC (04:00 SGT) |
| Edit | `/root/docs/OPERATIONS.md` | Add backup/restore section |
| Edit | `/root/shared/keys.md` | Update "Last backed up" header |

## Checklist

- [ ] **Step 1 — Restore rclone auth.** Write the `[gdrive-sa]` section from
      the backup config into the live config, omitting the empty `team_drive =`
      line. Verify: `rclone lsd gdrive-sa:` lists Drive root (no auth error).

- [ ] **Step 2 — Create backup script.** Write `/root/scripts/drive-backup.sh`
      with:
      - `set -euo pipefail`, `trap cleanup EXIT`, mktemp work dir
      - `pg_dump` via docker exec (skip gracefully if container not running)
      - Archive: `research/`, untracked files, `.env`, `shared/keys.md`,
        `shared/windmill-sa-key.json`, `.config/rclone/rclone.conf`
      - Upload via `rclone copy` to `gdrive-sa:vps-backup/$(date +%Y-%m-%d)/`
      - Retention: parse dated directories, `rclone purge` any older than 7 days
      - All output via `logger -t drive-backup`
      - `chmod +x`

- [ ] **Step 3 — Test the script.** Run `sudo bash /root/scripts/drive-backup.sh`.
      Confirm zero errors. Verify: `rclone ls gdrive-sa:vps-backup/$(date +%Y-%m-%d)/`
      shows both files. Verify archive integrity: `tar tzf` on the downloaded archive
      shows expected files.

- [ ] **Step 4 — Create systemd units.**
      - Service unit: `Type=oneshot`, `ExecStart=/root/scripts/drive-backup.sh`
      - Timer unit: `OnCalendar=*-*-* 20:00:00`, `RandomizedDelaySec=30m`
      - `systemctl daemon-reload && systemctl enable drive-backup.timer && systemctl start drive-backup.timer`

- [ ] **Step 5 — Verify the timer.** `systemctl list-timers --all | grep drive-backup`
      shows registered + next trigger. `systemctl is-enabled drive-backup.timer`
      returns `enabled`.

- [ ] **Step 6 — Docs + commit.** Update `docs/OPERATIONS.md` with backup/restore
      runbook. Update `shared/keys.md` header with today's date. Commit.

## G1 Locked Oracle

No locked oracle — mechanical plan with executor-authored verification.

## G2 RED-before-GREEN

No test suite changes — verification is via live Drive artifact evidence (G3).

## Asserting Verification Script (G4)

```bash
#!/bin/bash
fail=0
DATE=$(date +%Y-%m-%d)

echo "=== Step 1: rclone auth ==="
rclone lsd gdrive-sa: 2>&1 | head -3 || { echo "FAIL: rclone auth broken"; fail=1; }

echo "=== Step 2: backup files on Drive ==="
FILES=$(rclone ls "gdrive-sa:vps-backup/$DATE/" 2>&1)
echo "$FILES"
if echo "$FILES" | grep -q "portfolio_db.sql.gz" && \
   echo "$FILES" | grep -q "uncommitted.tar.gz"; then
    echo "PASS: both files present"
else
    echo "FAIL: missing backup files for $DATE"; fail=1
fi

echo "=== Step 3: systemd timer ==="
if systemctl is-enabled drive-backup.timer | grep -q enabled; then
    echo "PASS: timer enabled"
else
    echo "FAIL: timer not enabled"; fail=1
fi

TIMER=$(systemctl list-timers --all 2>/dev/null | grep drive-backup || true)
if [ -n "$TIMER" ]; then
    echo "PASS: timer registered: $TIMER"
else
    echo "FAIL: timer not registered"; fail=1
fi

echo "=== Step 4: archive integrity ==="
TMP=$(mktemp -d)
rclone copy "gdrive-sa:vps-backup/$DATE/uncommitted.tar.gz" "$TMP/" 2>&1
if tar tzf "$TMP/uncommitted.tar.gz" 2>/dev/null | grep -q "research/"; then
    echo "PASS: archive contains research/ output"
else
    echo "FAIL: archive missing expected content"; fail=1
fi
rm -rf "$TMP"

echo "=== Step 5: DB dump integrity ==="
TMP2=$(mktemp -d)
rclone copy "gdrive-sa:vps-backup/$DATE/portfolio_db.sql.gz" "$TMP2/" 2>&1
if gzip -t "$TMP2/portfolio_db.sql.gz" 2>/dev/null; then
    echo "PASS: DB dump is valid gzip"
else
    echo "FAIL: DB dump corrupted or missing"; fail=1
fi
rm -rf "$TMP2"

[ "$fail" -eq 0 ] && echo "PASS" || exit 1
```

## Acceptance Gate

- [ ] `rclone lsd gdrive-sa:` succeeds — Drive API auth works
- [ ] `drive-backup.sh` runs with zero errors (stderr clean)
- [ ] `portfolio_db.sql.gz` + `uncommitted.tar.gz` on Drive under `vps-backup/$DATE/`
- [ ] Archive integrity: downloaded tarball contains `research/` + credential files
- [ ] DB dump integrity: gzip validates
- [ ] Timer enabled + registered
- [ ] Timer fires daily at 04:00 SGT (deferred: check next day)
- [ ] Retention purges folders >7 days (deferred: check after 7 days)

## Execution

1. Set Status: executing, commit. (done — current state)
2. Work checklist top to bottom.
3. Run Asserting Verification Script — paste output, must end in `PASS`.
4. Confirm Acceptance Gate items.
5. Reviewer (any model) flips `Status: done`, commits.
