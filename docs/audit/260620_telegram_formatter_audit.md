# Telegram Formatter Architecture — Audit Record
**Date:** 2026-06-20
**Scope:** 8 `<name>_telegram.py` formatter scripts + canonical `.md` + `telegram_outbox`

## Architecture Summary

Each main script now:
1. Writes a canonical `.md` to `/research/<type>/<date>.md` (JSON front-matter + ≥500w narrative + `<!-- DETAIL -->`)
2. Dispatches its `<name>_telegram.py` formatter via Windmill REST API (fire-and-forget)

Each formatter:
1. Reads the `.md`, parses front-matter JSON + narrative
2. Builds ≥500-word self-contained Telegram message (no "→ email" footer)
3. Sends via shared sender; logs full text to job logs + writes `telegram_outbox`

## Verification Status

| Script | Tests Pass | Deployed | Schedule Updated | Live E2E |
|---|---|---|---|---|
| `macro_daily_push` + `macro_daily_push_telegram` | ✅ | ✅ | ✅ `portfolio_db` + `wm_token` added | ⏳ Next scheduled run |
| `portfolio_email` + `portfolio_email_telegram` | ✅ | ✅ | N/A (args already present) | ⏳ Next scheduled run |
| `portfolio_review` + `portfolio_review_telegram` | ✅ | ✅ | N/A | ⏳ Next scheduled run (Saturday) |
| `portfolio_rationalization` + `_telegram` | ✅ | ✅ | N/A | ⏳ Next Monday 9PM |
| `portfolio_move_monitor` + `_telegram` | ✅ | ✅ | N/A | ⏳ On next ±1.5%/±5% breach |
| `portfolio_analyst_alert` + `_telegram` | ✅ | ✅ | N/A | ⏳ On next rating change |
| `health_check` + `health_check_telegram` | ✅ | ✅ | ✅ `portfolio_db` + `wm_token` added | ⏳ Next 7AM SGT |
| `youtube_monitor` + `youtube_monitor_telegram` | ✅ | ✅ | ✅ `portfolio_db` + `wm_token` added | ⏳ Next 6-hourly run |

## Test Coverage

- 521 tests passing (521 passed, 1 skipped) in rebuilt container
- 8 per-formatter behavioral tests: `_build_message` pure function, ≥500 words, no email pointer, content-specific assertions
- 24 main-script guard tests: dispatches formatter, writes canonical md, no direct `_send_telegram`
- Splitting, Markdown-fallback, rationalization data tests included
- Container rebuilt and all tests baked in

## Content Verification Protocol (for live E2E runs)

For each script when it fires:
1. `wmill job list --script-path u/admin/<name>_telegram` → get formatter job_id
2. `wmill job logs <formatter_job_id>` → read `[Telegram] Sending (N chars, M words):\n<full_text>`
3. Assert: M ≥ 500 words; no "→ email" or "full report in email" in text
4. `SELECT * FROM telegram_outbox ORDER BY sent_at DESC LIMIT 1;` → confirm `delivered=true`, `word_count >= 500`
5. Compare first paragraph of Telegram text to canonical `.md` narrative

## Data Fixes (portfolio_rationalization)

- `_rec_tag`: was reading `"recommendation"`, now reads `"verdict"` — verdict tags now show in output
- `_score`: now returns composite balanced score (float, e.g. `55.5`) not rank integer
- DB upsert: `recommendation` column now populated with `verdict` value
- Dead code `_apply_red_flag_override` still present but isolated (wiring it = behavioral change, deferred)
