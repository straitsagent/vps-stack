---
Title: Daily Google Drive backup — implementation log
Date: 2026-06-27
Plan: docs/plans/2026-06-27_drive-backup.md
Executor: deepseek-v4-flash (opencode)
Status: done
---

## Summary

Implemented a daily backup system for the portfolio DB and uncommitted working
tree files to Google Drive. Uses rclone with OAuth (personal Drive token) for
auth, a bash script for the backup logic, and a systemd timer for scheduling.

## What was built

1. **rclone remote `gdrive-oauth`** — OAuthed against the user's personal Google
   Drive using a token generated via `rclone authorize "drive"` on the user's
   local machine. Points at the `vps-backup` folder (`root_folder_id` from URL).

2. **`/root/scripts/drive-backup.sh`** — Standalone bash script (69 lines):
   - Dumps `portfolio` DB via `docker exec root-portfolio_postgres-1 pg_dump`
   - Archives `research/`, untracked Windmill files, credential files (`.env`,
     `keys.md`, `windmill-sa-key.json`, `rclone.conf`) into a tarball
   - Uploads both files to `gdrive-oauth:vps-backup/YYYY-MM-DD/`
   - Purges dated folders older than 7 days
   - Logs to syslog via `logger -t drive-backup`

3. **Systemd units** — `drive-backup.service` (oneshot) + `drive-backup.timer`
   (daily at 20:00 UTC / 04:00 SGT, 30min random delay, persistent).

4. **Docs** — `docs/OPERATIONS.md` updated with backup/restore runbook.
   `shared/keys.md` header date updated.

## Key decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Auth method | OAuth (personal token) | Service account could authenticate but can't write to personal Drive (no storage quota). Google Shared Drives not available (personal account). |
| Remote name | `gdrive-oauth` | Chosen to distinguish from the SA-based `gdrive-sa`; script references this explicitly. |
| Retention | 7 days | User chose 7-day rolling window with auto-cleanup. |
| Scheduling | systemd timer | User chose standalone shell + systemd over Windmill script (avoids Windmill dependency). |
| Logging | syslog via `logger` | User chose syslog over dedicated log file. |

## Deviation log

- **OAuth method:** The plan originally specified SA-based auth (`gdrive-sa`).
  The SA could authenticate but received
  `googleapi: Error 403: Service Accounts do not have storage quota` when
  writing to the user's personal Drive. Switched to OAuth token generated via
  `rclone authorize "drive"` on the user's local machine. User approved.

## Verification (G4)

Full verification script output — all 5 checks passed, ending in `PASS`:

```
=== Step 1: rclone auth ===
           0 2026-06-16 17:48:39        -1 2026-06-16
           0 2026-06-27 10:02:40        -1 auth-test
           0 2026-06-27 11:01:49        -1 vps-backup
=== Step 2: backup files on Drive ===
  1224072 uncommitted.tar.gz
  1321829 portfolio_db.sql.gz
PASS: both files present
=== Step 3: systemd timer ===
PASS: timer enabled
PASS: timer registered: Sat 2026-06-27 22:03:14 CEST  10h ... drive-backup.timer
=== Step 4: archive integrity ===
PASS: archive contains research/ output
=== Step 5: DB dump integrity ===
PASS: DB dump is valid gzip
PASS
```

## Remaining items

- [x] rclone auth works with Drive
- [x] Manual backup run succeeds (both files uploaded)
- [x] Archive contains expected content
- [x] DB dump gzip-valid
- [ ] Timer first fire at 04:00 SGT (deferred — will trigger tonight)
- [ ] 7-day retention (deferred — verifiable after 7 days)
