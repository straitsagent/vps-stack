---
Status: executing
Subject: Portfolio Move Monitor — prices/shares/news/index context in .md + retire Telegram ping
Date: 2026-07-01
---

# Implementation Log: Move Monitor enrichment + Telegram retirement

## Summary

Rewrote `portfolio_move_monitor.py` to enrich the `.md` output with per-ticker news (4 sources), index-move context, price/share data, and accurate trigger descriptions. Removed the Telegram dispatch (`_dispatch_formatter` + the entire telegram gate). The `.md` is now written unconditionally when a threshold is breached (not gated by telegram params), matching the Hermes-consumption pattern.

## What changed

- **6 new pure functions** — `_fetch_finnhub_news`, `_fetch_seeking_alpha_news`, `_fetch_yfinance_news`, `_fetch_google_news_for_ticker`, `_fetch_ticker_news`, `_fetch_index_moves`. Each independently try/excepted. Copied from existing `research_tool.py` implementations per the plan's reuse directive.
- **`_build_move_narrative`** — rewritten with `trigger_desc`, `index_desc`, `breadth`, per-ticker price/price/share/news in the LLM prompt. Fallback path also fixed: uses `trigger_desc` (no more false "exceeding ±1.5%"), no `[:5]` truncation, enriched per-ticker info.
- **main()** — removed `telegram_bot_token`, `telegram_owner_id` params; added `finnhub_key`. `.md` write block moved outside the (now-deleted) telegram gate — always runs on any threshold breach. New front-matter keys: `session`, `total_portfolio_value_usd`, `portfolio_triggered`, `position_triggered`, `breadth`, `index_moves`. Each `position_alerts` item now has `previous_close`, `current_price`, `shares`, `news`.
- **`_dispatch_formatter`** deleted entirely.
- **Schedules** — both schedule yamls updated: removed telegram params, added `deepseek_key` and `finnhub_key`. Pushed via API (no `wmill sync push`).
- **Tests** — replaced 3 telegram-parameter tests with 1 inverted test (`test_move_monitor_no_longer_dispatches_telegram`). Updated `_render_portfolio_move_monitor_artifacts` harness: removed telegram patches + params, added `_fetch_ticker_news` + `_fetch_index_moves` patches.
- **Docs** — CLAUDE.md: formatter retired. ROADMAP.md: Move Monitor row updated, formatter table row updated.

## Key decisions

- **Removed `portfolio_move_monitor` from `_DISPATCH_MAIN_NAMES`** to avoid the parameterized test failure.
- **`pytz` stub in test harness** — changed from `MagicMock()` to `type(sys)(mod_name)` + `timezone` lambda, matching the health_check pattern.
- **`.md` is always written** when breached — no gating by telegram params. This was the most critical correctness point from the plan.

## Verification

### G1 Locked Oracle
```
O1-O9 all PASS
LOCKED ORACLE: PASS
```

### G4 Asserting Verification Script
All checks PASS. Full suite: 509 passed, 5 skipped.

## Remaining

- Live verify: next time a move event triggers, confirm the `.md` has the new enriched fields and no Telegram is sent.
