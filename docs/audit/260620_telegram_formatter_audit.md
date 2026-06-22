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

| Script | Tests Pass | Deployed | Live E2E | Word Count | `.md` Match |
|---|---|---|---|---|---|
| `macro_daily_push` + `_telegram` | ✅ | ✅ | ✅ 2026-06-21 | 715 ✅ | ✅ all indicators |
| `portfolio_email` + `_telegram` | ✅ | ✅ | ✅ 2026-06-21 | 701 ✅ | ✅ all values |
| `portfolio_review` + `_telegram` | ✅ | ✅ | ✅ 2026-06-21 | 620 ✅ | ✅ ticker bug fixed (was `"ticker"` → `"label"`) |
| `portfolio_rationalization` + `_telegram` | ✅ | ✅ | ✅ 2026-06-21 | 951 ✅ | ✅ scores/verdicts match |
| `portfolio_move_monitor` + `_telegram` | ✅ | ✅ | ⏳ On next ±1.5%/±5% breach | — | — |
| `portfolio_analyst_alert` + `_telegram` | ✅ | ✅ | ⏳ On next rating change | — | — |
| `health_check` + `_telegram` | ✅ | ✅ | ✅ 2026-06-21 | 817 ✅ | ✅ status rows match |
| `youtube_monitor` + `_telegram` | ✅ | ✅ | ⏳ Next 6-hourly run with new videos | — | ✅ `_collect_24h_videos` verified inline |

## Bugs Fixed (2026-06-21)

- **`portfolio_review_telegram.py`**: `_mover()` read `p.get("ticker")` but front-matter uses `"label"` — all tickers rendered as `?`. Fixed to `p.get("label", p.get("ticker", "?"))`.
- **`macro_daily_push.py`**: `max_tokens=900` caused narrative to be cut mid-sentence. Increased to `max_tokens=1400`.
- **`youtube_monitor_telegram.py`**: formatter ignored `narrative` param and built output only from per-video front-matter — always under 500 words on low-video days. Redesigned to use 24h synthesis as body.
- **`youtube_monitor.py`**: added `_collect_24h_videos` (scans all 24h `.md` files from `/research/youtube/`) and `_synthesise_24h` (Deepseek 600-700w digest). Per-video sections moved below `<!-- DETAIL -->`.

## Test Coverage

- 330 tests passing (330 passed, 1 skipped) — rebuilt container
- 8 per-formatter behavioral tests: `_build_message` pure function, ≥500 words, no email pointer, content-specific assertions
- 24 main-script guard tests: dispatches formatter, writes canonical md, no direct `_send_telegram`
- YouTube: 24 tests (includes `_collect_24h_videos` exists, `_synthesise_24h` exists, synthesis is body of message)
- Splitting, Markdown-fallback, rationalization data tests included

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
