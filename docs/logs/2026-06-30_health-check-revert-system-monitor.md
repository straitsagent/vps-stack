---
Status: executing
Subject: Expand health_check into comprehensive Windmill+VPS system monitor; remove LLM analysis; deprecate health Telegram ping
Date: 2026-06-30
---

# Implementation Log: Health Check → System Monitor

## Summary

Rewrote `health_check.py` into a comprehensive system monitor that tracks not just Windmill workflow health but also VPS host resources (disk, memory, load, Docker) and Drive backup status. Removed the LLM analytical layer (`_synthesise_daily_digest`, `_build_health_narrative`) and Telegram dispatch. Created a host-side system-metrics collector (`system-metrics-collector.py` + systemd timer every 30min). Updated tests, docs, and schedule.

## What was built

- **`scripts/system-metrics-collector.py`** — pure-stdlib host collector: `df`, `/proc/meminfo`, `os.getloadavg`, `docker ps -a`, `systemctl show drive-backup.service`, `/proc/uptime`. Atomic write to `/root/research/system/vps_health.json`. Per-metric error isolation (Hard Rule 4).
- **`scripts/systemd/system-metrics.service`** + **`system-metrics.timer`** — oneshot service + 30-min timer (mirrors the `drive-backup.timer` pattern). Committed copies under `scripts/systemd/`.
- **`health_check.py` rewrite**:
  - Deleted `_build_health_narrative()` (deterministic narrative) and `_synthesise_daily_digest()` (Grok-4 holistic brief).
  - Removed Daily Brief/digest section from email HTML and canonical `.md`.
  - Removed Telegram dispatch block and `_dispatch_formatter("health_check_telegram", …)` call.
  - Dropped `xai_key`, `telegram_bot_token`, `telegram_owner_id` from `main()` signature; kept `deepseek_key` for failure diagnosis.
  - Added `_read_system_metrics()` with staleness/missing-file guards and threshold rules (disk ≥85%/95%, memory <10%/5% avail, load >cores/2×cores, Docker non-running containers, backup failure/stale).
  - Rewrote `_build_md_content()` to emit structured deterministic sections (Schedule Status, System Resources, Backup Status, Token Usage, Spec Checks, Diagnoses).
  - Added System Resources + Backup Status sections to `build_html()` for email.
  - Updated `ARTIFACT_MARKERS` to replace "Digest" with "System Resources"/"Backup Status".
  - Kept `_dispatch_formatter` helper (other scripts use it).
  - Updated `SPEC_RULES["Health Check"]` to `["Schedules", "Telegram Outbox"]`.
- **`health_check_telegram.py`** — added system/backup rendering blocks; formatter retained on disk, tolerant of new schema (HR 18).
- **`health_check_daily.schedule.yaml`** — removed 3 args (`xai_key`, `telegram_bot_token`, `telegram_owner_id`); pushed via REST API (no `wmill sync push`).
- **Tests** — inverted `test_health_check_has_telegram_push` → `test_health_check_no_telegram_push`; deleted 5 digest/xai_key tests; added 2 inverted tests (`test_health_check_no_xai_key`, `test_health_check_no_digest_in_front_matter`); added 4 collector unit tests; updated artifact harness (`_render_health_check_artifacts`) and all downstream tests for new schema.
- **Docs** — ROADMAP.md (health check row, WS-A 🟡, formatter table), WORKFLOW_ARCHITECTURE.md (rewritten Workflow 6.1), CLAUDE.md (added collector timer, health_check_telegram to retired list).

## Key decisions

- **Keep `_dispatch_formatter` helper** (Q4) — it's generic and used by other scripts.
- **Delete 5 digest/xai_key tests** instead of inverting (Q1) — functions are permanently removed.
- **Curl API push for schedule** (Q2) — per OPERATIONS.md recipe, no `wmill sync push`.
- **Live verify ran** (Q3) — one real `health_check` job triggered; confirmed email sent, `.md` written with system+backup, no `telegram_outbox` row for health_check.
- `build_html` changed from taking `digest=` to `system_data=` and `backup_data=`.
- No changes to the Dind/research mount architecture — collector runs on host, worker reads the mounted file.

## Deviation log

None — all deviations from the original plan were pre-approved via owner Q&A before execution.

## Verification output

### G1 Locked Oracle
```
O1 PASS — digest + narrative removed
O2 PASS — Telegram dispatch removed
O3 PASS — xai removed, deepseek kept
O4 PASS — system metrics consumed
O5 PASS — collector emits disk/memory/load/docker/backup
O6 PASS — collector timer enabled
O7 PASS — schedule args cleaned
O8 PASS — suite green + inverted test present
LOCKED ORACLE: PASS
```

### G4 Asserting Verification Script
```
PASS: digest removed
PASS: narrative removed
PASS: telegram dispatch removed
PASS: system metrics consumed
PASS: collector exists
PASS: collector runs
PASS: collector JSON shape
PASS: collector timer enabled
PASS: schedule cleaned
505 passed, 1 skipped in 34.08s
PASS: suite green
PASS: inverted test present
PASS
```

### Live verify (H4.2)
- .md file written with `system`+`backup` front-matter, no `digest`
- `telegram_outbox` count for health_check: 0 rows (no Telegram sent)
- Email sent via SMTP (confirmed by job `Success: True`)

### Collector (H4.1)
- JSON fresh (7 min old), all sections: 24 disk mounts, memory 24031MiB, load 2.34, 16 Docker containers, backup timer active

### Negative check (H4.3)
- Stale data (collected_at 95min ago) correctly flagged as CRIT with 2 alerts

## Remaining items

- WS-B (Analysis takeover) and WS-C (Research `.md` quality) from Hermes integration roadmap are not yet started — this plan partially delivers WS-A.
- The Hermes feedback job (WS-1 of the reflexive roadmap) is unblocked: Hermes can now read `/research/system/vps_health.json` for system visibility.
