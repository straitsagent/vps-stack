# macro_daily_push Disposition — Implementation Log

**Date:** 2026-06-26
**Decision:** Park (not delete). `macro_research` supersedes the standalone macro push.

## Changes
- Deleted the disabled server schedule `u/admin/macro_daily_push` (curl DELETE; Hard Rule 9 — no sync push).
- `git rm windmill/u/admin/macro_daily_push.schedule.yaml`.
- Retained `macro_daily_push.py` + `.script.yaml`/.lock and all 4 tests (parked, not removed).

## Explicitly untouched
- `macro_daily_push_telegram.*` — LIVE formatter dispatched by `macro_research` (`test_windmill_scripts.py:4570`);
  1 of the 8 formatters. Formatter count stays 8; no CLAUDE.md change.

## Verification
- `schedules/get` for `macro_daily_push` → 404.
- `macro_daily_push` + `macro_research` tests: 33 passed, green.
- `macro_daily_push.py` and `macro_daily_push_telegram.py` still present on disk.

## Notes
- Final hygiene initiative (5 of 5). Remaining roadmap hygiene item (API health monitor) deferred.
