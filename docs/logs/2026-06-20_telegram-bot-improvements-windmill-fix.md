# Implementation Log — Telegram Bot Improvements + Windmill Automation Fix
**Date:** 2026-06-19 to 2026-06-20
**Commits:** `0b4f64a`, `a3dc7a6`, `a1eb0a8`, `2671e28`, `68076c0`
**Files changed:** `agent/tools.py`, `agent/planner.py`, `agent/main.py`, `agent/classifier.py`, `agent/config.py`, `agent.env.example`, `CLAUDE.md`, `windmill/u/admin/portfolio_move_monitor.schedule.yaml`, `windmill/u/admin/portfolio_move_monitor_us.schedule.yaml`, `windmill/u/admin/portfolio_review.schedule.yaml`, `windmill/u/admin/youtube_monitor.schedule.yaml`
**Tests:** 409 passing (13 new tests added across test_tools.py, test_planner.py, test_classifier.py, test_routing.py)

---

## Work 1 — macro_indicators Expanded to 24 Indicators (commit `0b4f64a`)

### Motivation

`/macro` was limited to 5 indicators (SGD/USD, HKD/USD, VIX, Brent, 10Y UST). Expanded to provide a full market picture across 6 groups covering 24 indicators.

### Changes

**`agent/tools.py`**

- Added `import asyncio` and `from collections import OrderedDict`
- Replaced flat `SYMBOLS` dict with `_YAHOO_GROUPS` OrderedDict — 19 symbols across 5 groups: Indices (S&P 500, Nasdaq, Hang Seng, STI, Shanghai), Rates (UST 5Y/10Y/30Y), Vol (VIX), Commodities (Brent, WTI, Gold, Copper), FX (USD/SGD, USD/HKD, USD/CNY, DXY, EUR/USD, USD/JPY)
- Added `_FRED_SERIES` dict — 5 FRED economic indicators: Fed Funds, CPI YoY, Core PCE YoY, Unemployment, plus UST 2Y cross-check
- Rewrote `macro_indicators()` as fully async with `asyncio.gather()` — parallelises all Yahoo Finance and FRED HTTP calls, reducing wall time from ~5s sequential to ~1.5s parallel
- FX display: inverted USD/SGD and USD/HKD symbols so output reads as currency pairs natural to a Singapore-based user
- Output groups each section with bold header and divider

**`agent/config.py`** — Added `FRED_KEY = os.environ.get("FRED_KEY", "")`

**`agent.env.example`** — Added `FRED_KEY=` line

**`agent/planner.py`** — Updated `PLANNER_SYSTEM_PROMPT` macro_indicators description to reflect 24 indicators across 6 groups

**Tests added (`test_tools.py`):** `test_macro_indicators_has_24_symbols`, `test_macro_groups_has_six_sections`, `test_macro_indicators_parallel_gather`

---

## Work 2 — /macro Per-Section Commentary + News Sources (commit `a3dc7a6`)

### Motivation

After the 24-indicator expansion, `/macro` output had no commentary and no news sources — just raw data. User expected: per-section in-depth commentary (2-4 sentences), plus news sources with hyperlinks per section.

Two root causes identified:
1. **LLM planner non-determinism** — planner sometimes omitted `news_search` from the plan, so no news data was ever fetched
2. **Contradictory synthesiser prompt** — `MACRO_SYNTHESISER_SYSTEM_PROMPT` instructed both "preserve verbatim" and "400 words" which created ambiguous output

### Changes

**`agent/planner.py`**

- Added `_NEWS_SECTIONS` dict — 5 targeted queries mapped to section names (Indices & Vol, Rates, Commodities, FX, Economics)
- Replaced `MACRO_SYNTHESISER_SYSTEM_PROMPT` — removed word limit, added explicit per-section format: divider (`━━━━━━━━━━━━━━━━━━━━`), data rows verbatim, 2-4 sentences commentary with portfolio implications (~40% HK / ~60% US), news sources as `• [Title](url) — Publication`
- Added `async def run_macro_brief(question: str) -> str` — fires `asyncio.gather(macro_indicators(), 5×news_search())` in parallel, single Deepseek call (max_tokens=2500, timeout=60s); completely bypasses the LLM planner

**`agent/main.py`** — Updated `MULTI_STEP` handler: if `intent == "macro_brief"` → calls `pl.run_macro_brief(text)` directly (not the generic step-loop)

**Tests added (`test_planner.py`):** `test_run_macro_brief_function_exists`, `test_news_sections_has_5_entries`, `test_run_macro_brief_uses_parallel_fetch`, `test_macro_synthesiser_prompt_no_word_limit`, `test_macro_synthesiser_prompt_per_section_format`

**Test added (`test_routing.py`):** `test_macro_brief_calls_run_macro_brief` — source-inspects main.py via `pathlib.Path(__file__).parent.parent / "main.py"` (relative path — absolute path not readable inside Docker container)

---

## Work 3 — Deterministic Classifier Shortcuts (commit `2671e28`)

### Motivation

User sent "macro" to the bot and received "Sorry, I didn't understand that." DB audit confirmed `inbound_text=macro`, `intent_detected=unknown`. Deepseek LLM was ignoring the shortcut instructions in `SYSTEM_PROMPT` and classifying "macro" as unknown.

### Changes

**`agent/classifier.py`**

Added `_SHORTCUTS: dict[str, tuple[str, dict]]` — 14 single-word commands that bypass the LLM entirely:
```python
_SHORTCUTS = {
    "macro": ("macro_brief", {}), "rates": ("macro_brief", {}),
    "health": ("health_check", {}), "news": ("news_digest", {}),
    "morning": ("news_digest", {}), "youtube": ("youtube_digest", {}),
    "yt": ("youtube_digest", {}), "prices": ("live_prices", {}),
    "refresh": ("price_refresh", {}), "portfolio": ("portfolio_digest", {}),
    "analyze": ("portfolio_analysis", {}),
    "rationalize": ("portfolio_rationalize", {"include_research": False}),
    "rationalise": ("portfolio_rationalize", {"include_research": False}),
    "earnings": ("earnings", {"ticker": None}),
}
```

Fast-path at top of `classify()`: if `text.strip().lower()` matches a key, returns `{"intent": ..., "args": ..., "confidence": 1.0, "router_tokens": 0}` without any HTTP call.

**Tests added (`test_classifier.py`):** `test_shortcuts_dict_exists`, `test_shortcuts_covers_key_commands`, `test_shortcuts_macro_routes_to_macro_brief`, `test_classify_macro_bypasses_llm`

**Tests updated (`test_classifier.py`):** `test_classify_returns_parsed_intent` and `test_classify_youtube_returns_youtube_digest` — changed inputs from `"news"` / `"youtube"` to `"what's in the morning news today"` / `"show me the youtube digest"` (shortcut inputs now bypass the mock, breaking the LLM path tests)

---

## Work 4 — Windmill Schedule Args Fix (commit `68076c0`)

### Root Cause Diagnosis

All email-sending Windmill scripts were failing with `SMTPRecipientsRefused: {'': (555, b'5.5.2 Syntax error...')}`. The recipient was an empty string because every schedule had stale args missing `recipient_email`.

The `.schedule.yaml` files on disk (which correctly include `recipient_email` and Telegram params) were **never pushed to Windmill**. The PostToolUse autopush hook only fires on `.py` file edits. Schedules in Windmill reflected a state from early June before `recipient_email` was added as a script parameter.

Additionally, ~15 hours of jobs were stuck in the queue due to a Windmill worker/DB connection issue (`pull took > 0.1s, empty: true, err: true`).

### Fix

**Step 1 — Restart Windmill workers** (cleared the stuck queue):
```bash
docker compose restart windmill_worker windmill_worker_native
```

**Step 2 — Update all 9 schedules via Windmill REST API** using the correct update endpoint (`POST /api/w/admins/schedules/update/{path}`):

| Schedule | Change |
|---|---|
| `portfolio_email_daily` | Added `recipient_email`, `telegram_bot_token`, `telegram_owner_id` |
| `portfolio_email_evening` | Added `recipient_email`, `telegram_bot_token`, `telegram_owner_id` |
| `youtube_monitor_hourly` | Added `recipient_email`, `telegram_bot_token`, `telegram_owner_id` |
| `health_check_daily` | Added `recipient_email` |
| `portfolio_review` | Added `recipient_email` |
| `portfolio_rationalization_monthly` | Added `recipient_email`, `telegram_bot_token`, `telegram_owner_id` |
| `portfolio_move_monitor` | Added `recipient_email`, `telegram_bot_token`, `telegram_owner_id` |
| `portfolio_move_monitor_us` | Added `recipient_email`, `telegram_bot_token`, `telegram_owner_id` |
| `macro_daily_push` | Created new schedule (7:30 AM SGT Mon–Fri) |

Note: first attempt used `POST /schedules/{path}` (wrong — returned 200 but did not update args). Correct endpoint is `POST /schedules/update/{path}`.

**Step 3 — Fix schedule YAMLs on disk** — Added `recipient_email: "$var:u/admin/recipient_email"` to 4 YAML files that were missing it: `portfolio_move_monitor.schedule.yaml`, `portfolio_move_monitor_us.schedule.yaml`, `portfolio_review.schedule.yaml`, `youtube_monitor.schedule.yaml`

**Step 4 — Document in CLAUDE.md** — Added explicit note to Script Workflow section that `.schedule.yaml` changes require a manual API push with the correct curl command pattern.

### Verification

- Triggered `portfolio_email` manually via API → success (7.5s) → email sent, Telegram push delivered
- Triggered `youtube_monitor` manually via API → success (75s) → email sent (8 new videos), Telegram push delivered
- Both scripts: no `[Telegram] Failed to send` warnings in logs

---

## Notes on Windmill API Endpoint Patterns

- **Update existing schedule:** `POST /api/w/{workspace}/schedules/update/{url-encoded-path}`
- **Create new schedule:** `POST /api/w/{workspace}/schedules/create` (with `"path"` in body)
- **Get schedule:** `GET /api/w/{workspace}/schedules/get/{url-encoded-path}`
- **List schedules:** `GET /api/w/{workspace}/schedules/list`
- Path encoding: `u/admin/portfolio_email_daily` → `u%2Fadmin%2Fportfolio_email_daily`
- WM_TOKEN: `$(grep "WM_TOKEN" /root/agent.env | cut -d= -f2 | tr -d ' ')`
