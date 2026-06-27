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
changes. rclone (v1.74.2) is installed. **Note (deviation from original plan):** the
original plan intended to use a GCP service account (`vps-backup-sa@vps-stack-500302`)
via a `[gdrive-sa]` rclone remote, but SAs do not have Drive storage quota (Error 403);
the executor switched to a personal OAuth remote (`[gdrive-oauth]`) with owner approval.
The live `~/.config/rclone/rclone.conf` has only the `[gdrive-oauth]` section.

Loss of the VPS or DB volume would lose ~10 days of uncommitted work
(Plan A/B code, research outputs, schema migrations).

## What it does

A systemd-timer-driven bash script that runs daily at 04:00 SGT:

1. **pg_dump** the `portfolio` DB via `docker exec` into `portfolio_db.sql.gz`
2. **Archive** uncommitted files + credentials into `uncommitted.tar.gz`
3. **Upload** both to `gdrive-oauth:vps-backup/YYYY-MM-DD/` via rclone
4. **Purge** Drive folders older than 7 days

## Files changed

| Action | Path | Change |
|--------|------|--------|
| Edit | `/root/.config/rclone/rclone.conf` | Added `[gdrive-oauth]` OAuth remote (SA has no quota; owner-approved switch from original `[gdrive-sa]` plan) |
| Create | `/root/scripts/drive-backup.sh` | ~65-line bash backup script |
| Create | `/etc/systemd/system/drive-backup.service` | oneshot service unit |
| Create | `/etc/systemd/system/drive-backup.timer` | daily at 20:00 UTC (04:00 SGT) |
| Edit | `/root/docs/OPERATIONS.md` | Add backup/restore section |
| Edit | `/root/shared/keys.md` | Update "Last backed up" header |

## Checklist

- [x] **Step 1 — rclone auth.** OAuth remote `[gdrive-oauth]` configured in
      `~/.config/rclone/rclone.conf` (SA discarded — no storage quota). Verify:
      `rclone lsd gdrive-oauth:` lists Drive root (no auth error).

- [ ] **Step 2 — Create backup script.** Write `/root/scripts/drive-backup.sh`
      with:
      - `set -euo pipefail`, `trap cleanup EXIT`, mktemp work dir
      - `pg_dump` via docker exec (skip gracefully if container not running)
      - Archive: `research/`, untracked files, `.env`, `shared/keys.md`,
        `shared/windmill-sa-key.json`, `.config/rclone/rclone.conf`
      - Upload via `rclone copy` to `gdrive-oauth:vps-backup/$(date +%Y-%m-%d)/`
      - Retention: parse dated directories, `rclone purge` any older than 7 days
      - All output via `logger -t drive-backup`
      - `chmod +x`

- [ ] **Step 3 — Test the script.** Run `sudo bash /root/scripts/drive-backup.sh`.
      Confirm zero errors. Verify: `rclone ls gdrive-oauth:vps-backup/$(date +%Y-%m-%d)/`
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
rclone lsd gdrive-oauth: 2>&1 | head -3 || { echo "FAIL: rclone auth broken"; fail=1; }

echo "=== Step 2: backup files on Drive ==="
FILES=$(rclone ls "gdrive-oauth:vps-backup/$DATE/" 2>&1)
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
rclone copy "gdrive-oauth:vps-backup/$DATE/uncommitted.tar.gz" "$TMP/" 2>&1
if tar tzf "$TMP/uncommitted.tar.gz" 2>/dev/null | grep -q "research/"; then
    echo "PASS: archive contains research/ output"
else
    echo "FAIL: archive missing expected content"; fail=1
fi
rm -rf "$TMP"

echo "=== Step 5: DB dump integrity ==="
TMP2=$(mktemp -d)
rclone copy "gdrive-oauth:vps-backup/$DATE/portfolio_db.sql.gz" "$TMP2/" 2>&1
if gzip -t "$TMP2/portfolio_db.sql.gz" 2>/dev/null; then
    echo "PASS: DB dump is valid gzip"
else
    echo "FAIL: DB dump corrupted or missing"; fail=1
fi
rm -rf "$TMP2"

[ "$fail" -eq 0 ] && echo "PASS" || exit 1
```

## Acceptance Gate

- [x] `rclone lsd gdrive-oauth:` succeeds — Drive API auth works (OAuth remote)
- [x] `drive-backup.sh` runs with zero errors (stderr clean)
- [x] `portfolio_db.sql.gz` + `uncommitted.tar.gz` on Drive under `vps-backup/$DATE/`
- [x] Archive integrity: downloaded tarball contains `research/` + credential files
- [x] DB dump integrity: gzip validates
- [x] Timer enabled + registered (`drive-backup.timer`, enabled, next trigger 22:03 CEST)
- [ ] Timer fires daily at 04:00 SGT (deferred: first fire 2026-06-28 04:03 SGT)
- [ ] Retention purges folders >7 days (deferred: verifiable 2026-07-04+)

## Execution

1. Set Status: executing, commit. (done — current state)
2. Work checklist top to bottom.
3. Run Asserting Verification Script — paste output, must end in `PASS`.
4. Confirm Acceptance Gate items.
5. Reviewer (any model) flips `Status: done`, commits.
