# Rationalization Schedule Migration — Implementation Log

**Date:** 2026-06-26
**Scope:** Move portfolio rationalization from Monday 9 PM SGT to Saturday 6 AM SGT; drop the
misleading `_monthly` suffix from schedule naming.

## Changes

### Server (Windmill)
- **Deleted** `u/admin/portfolio_rationalization_monthly` — old schedule, Monday 9 PM SGT (`0 0 21 * * 1`).
- **Created** `u/admin/portfolio_rationalization` — new schedule, Saturday 6 AM SGT (`0 0 6 * * 6`).
  All 9 args preserved unchanged (deepseek_key, xai_key, portfolio_db, gmail_smtp, finnhub_key,
  exa_key, telegram_bot_token, telegram_owner_id, recipient_email). Enabled, no_flow_overlap,
  timezone Asia/Singapore — all unchanged.
- Both operations via curl API (Hard Rule 9 — no sync push). Verified: old path → 404, new path
  → 200 with correct cron.

### Disk (git)
- **Deleted** via `git mv`: `portfolio_rationalization_monthly.schedule.yaml`.
- **Created**: `portfolio_rationalization.schedule.yaml` — same content, clean name.
  The `_monthly` suffix was misleading — the schedule had been weekly for some time.

### Documentation
- `ROADMAP.md`: Portfolio System table updated — Saturday 6 AM SGT (was Monday 9 PM).
- `WORKFLOW_ARCHITECTURE.md`: Schedule path reference updated — dropped `_monthly`, updated day/time.
- Coherence plans (`docs/plans/2026-06-26_advisor-coherence-*.md`) and coherence design doc
  (`docs/design/2026-06-26_portfolio-coherence-seams-design.md`) already reference the clean path
  with Saturday timing (written after the schedule migration was conceptually approved, before
  execution).

## Verification
- `schedules/get` for new path → `cron: 0 0 6 * * 6 | tz: Asia/Singapore | enabled: True`.
- `schedules/get` for old path → HTTP 404.
- Disk file at `windmill/u/admin/portfolio_rationalization.schedule.yaml` matches.
- No `_monthly` references remain in live docs (audit/logs preserved as historical).
