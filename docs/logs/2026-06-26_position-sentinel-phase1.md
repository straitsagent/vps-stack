# Position Sentinel Phase 1 — Implementation Log

**Date:** 2026-06-26
**Scope:** Build the signal spine and cumulative-price alert system for the Position Sentinel.

## What was built
- **Schema:** `position_events` (per-headline materiality-scored events) + `position_signals` (triggered alerts with detail JSONB). Applied to live DB, appended to `portfolio/schema.sql`.
- **`position_sentinel.py`:** Main monitor script. Pure helpers (`_cumulative_drawdowns`, `_price_signal`, `_parse_materiality`, `_aggregate_materiality`, `_confluence`, `_url_hash`) + I/O edges (`_fetch_news` via Google News RSS, `_triage_news` via Deepseek for materiality scoring 0-3, `_dispatch_formatter` for Telegram push). Phase 1: cumulative-price alerts enabled (live push); news/confluence logged only.
- **`position_sentinel_telegram.py`:** Markdown-driven formatter (9th formatter). Reads canonical `.md`, builds ≥500-word self-contained Telegram message, sends + logs to `telegram_outbox`.
- **Schedule:** On-demand for Phase 1 calibration; hourly schedule YAML ready for Phase 2 activation.

## Tests (RED→GREEN)
8 tests added to `test_windmill_scripts.py`:
- `test_cumulative_drawdowns_matches_baba` — anchors math to real BABA decline (~-11.5% 5d, ~-27.3% vs 20d high)
- `test_price_signal_fires_on_baba_thresholds` and `test_price_signal_silent_on_calm_series`
- `test_parse_materiality_valid` and `test_parse_materiality_clamps_invalid`
- `test_confluence_requires_price_and_news`
- `test_sentinel_telegram_build_message_500_words` + front-matter contract
Full suite: 492 passed (no regressions).

## Live verification
- Schema applied: `position_events` + `position_signals` exist in live DB.
- Sentinel run: 33 tickers scanned. 0 signals fired (BABA prices have recovered from last week's crash — expected; the math is proven by tests).
- `feedparser==6.0.12` present in script lock for news fetching.

## Model sign-off
- Materiality triage: Deepseek `deepseek-chat` (owner approved)
- Phase 2 confluence synthesis: Grok-4.3 (owner approved, in plan)
- Materiality triage prompt: approved as written in plan
- Thresholds: -8%/3d, -12%/5d, -20% vs 20d high (owner approved)
