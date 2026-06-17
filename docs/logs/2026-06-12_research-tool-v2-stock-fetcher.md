# Implementation Log — Research Tool v2 + Stock Data Fetcher
**Date:** 2026-06-12 (approximate, spanning Jun 12–13)
**Commits:** reconstructed from session transcripts
**Files changed:** `windmill/u/admin/research_tool.py`, `windmill/u/admin/stock_data_fetcher.py`, `windmill/u/admin/research_tool.script.yaml`, `windmill/u/admin/stock_data_fetcher.script.yaml`, `agent/dispatch_research.py`, `agent/tests/test_dispatch_research.py`, `portfolio/schema.sql`, `CLAUDE.md`, `docs/ROADMAP.md`

---

## Plan Completed

Overhauled `research_tool.py` from a basic multi-source search into an investment-grade deep research tool. Added source routing (Serper/Google News, Exa, EDGAR at appropriate depths), structured financial context functions (3yr financials, financial health ratios, ownership, insider transactions, MD&A synopsis from 10-Q), and output depth controls. Separated structured data persistence into a new `stock_data_fetcher.py` script (single-ticker, 8 data types, 14 DB tables), with `research_tool` now reading from DB first and dispatching `stock_data_fetcher` on stale or absent data. Fixed two runtime bugs: a naive/aware datetime crash in the agent's research cache, and a fallback path that silently produced empty reports when `stock_data_fetcher` timed out.

---

## All Tasks Performed

1. Added `search_recency_filter='month'` to all Perplexity queries to enforce freshness
2. Added Serper news search (Google News programmatic access) as a new source at all depths for stock research
3. Added EDGAR 10-K/10-Q search at standard depth for US stock tickers
4. Replaced quarterly financials with annual 3-year P&L, balance sheet, and cash flow (more useful for stock analysis than recent quarters alone)
5. Added Financial Health section: Net Debt/EBITDA, gearing ratio, interest coverage
6. Added ownership structure context (top institutional holders, insider ownership %)
7. Added insider transactions (90-day window) as a context section
8. Added earnings calendar context (next and most recent earnings dates)
9. Added MD&A synopsis: Deepseek summarizes the latest 10-Q MD&A section from EDGAR — provides qualitative management commentary not captured by structured data
10. Fixed output depth: added snippet length caps per depth level, `max_tokens` passed to Grok synthesis, depth-specific instruction language for the synthesis prompt
11. Fixed naive/aware datetime comparison crash in agent research cache (see Bug 1)
12. Designed and built `stock_data_fetcher.py`: single-ticker Windmill script, 8 data types (company profile, 3yr financials, valuation, ownership, insider transactions, earnings calendar, key management, peer comparisons), persists to 14 typed DB tables
13. Added `stock_data_fetcher` script metadata YAML and pushed to Windmill
14. Updated `research_tool.py` to read structured stock data from DB first (`_read_structured_stock_data`); dispatches `stock_data_fetcher` as a Windmill job if data is absent or stale (>7 days old); falls back to live API fetch if dispatch fails or times out
15. Fixed Step 4 fallback path for timed-out `stock_data_fetcher` jobs (see Bug 2)
16. Verified 32 tickers end-to-end with correct output at all three depth levels
17. Updated CLAUDE.md and ROADMAP.md: Step 4 fallback fix noted, 259 tests passing, 32 tickers verified

---

## Bugs Encountered

**Bug 1 — Naive/aware datetime comparison crash in research cache**
**Symptom:** `dispatch_research` in the agent crashed when checking whether a cached research report was recent enough to reuse. Error: `TypeError: can't subtract offset-naive and offset-aware datetimes`.
**Root cause:** `research_reports.created_at` is defined as `TIMESTAMP WITHOUT TIME ZONE` in the live DB schema. psycopg2 returns this as a Python naive datetime (no `tzinfo`). The cache age check compared it against `datetime.now(timezone.utc)`, which is timezone-aware. Python does not allow subtraction between aware and naive datetimes.
**Fix:** Normalized the DB timestamp before comparison: if `created_at.tzinfo is None`, apply `.replace(tzinfo=timezone.utc)` to treat it as UTC. This is safe because all timestamps in this DB are written in UTC.

**Bug 2 — stock_data_fetcher timeout left research_tool with empty quantitative sections**
**Symptom:** Deep stock research for tickers with no prior DB data would dispatch `stock_data_fetcher`, wait the full timeout, then produce a report that contained the introduction and synthesis text but had no quantitative data sections (no financials, no valuation, no ownership).
**Root cause:** When `_dispatch_stock_fetcher()` returned `False` (Windmill job timed out or failed), `sections` was left as an empty dict `{}`. The code had a conditional `if sections: ... else: live_fetch()` — but an empty dict is falsy in Python, so the `else` branch was supposed to fire the live-fetch fallback. In practice, an earlier code path had been added that returned early from the function if `portfolio_db` was set, regardless of whether the dispatch succeeded. The live-fetch branch was structurally unreachable when `portfolio_db` was configured and the dispatch failed.
**Fix:** Replaced the implicit `if sections` truthiness check with an explicit `fetched_from_db: bool` flag. Set `fetched_from_db = True` only when `_read_structured_stock_data` returns non-empty results after a successful dispatch. The live-fetch fallback fires on `fetched_from_db = False`, regardless of whether `portfolio_db` is configured.

---

## Lessons Learned

1. **Always normalize DB timestamps to a consistent timezone before arithmetic.** PostgreSQL `TIMESTAMP WITHOUT TIME ZONE` is a footgun when mixed with Python's `datetime.now(timezone.utc)`. The safest pattern is to normalize immediately after reading from the DB, not at the point of comparison — so the rest of the code can assume all datetimes are UTC-aware.
2. **Separation of concerns between fetching and synthesis pays off immediately.** Moving structured data persistence into `stock_data_fetcher.py` made `research_tool.py` simpler (reads from DB, falls back to live), made `stock_data_fetcher` independently testable and callable from other tools (portfolio rationalization, candidate eval), and made the DB the single source of truth for structured stock data across the whole stack.
3. **Use explicit boolean flags for multi-path fallbacks, not truthiness of collections.** `if sections` fails silently when `sections` is an empty dict — the code looks correct but the fallback never fires. An explicit `fetched_from_db = False` flag initialized before the try/dispatch block, set to `True` only on confirmed success, makes the fallback condition unambiguous and immune to this class of bug.
4. **MD&A synopsis via LLM adds qualitative signal that structured data cannot.** The Deepseek-summarized 10-Q MD&A section consistently surfaces management tone, forward guidance hedging, and risk factor changes that no structured financial field captures. It is worth the extra API call at standard and deep depths.
5. **Test live at each depth level before declaring a research overhaul complete.** The snippet cap and `max_tokens` bugs (too-short previews, truncated synthesis) were only visible in actual Grok output — unit tests that mock the LLM response would not have caught them. One real end-to-end run at brief/standard/deep with a known ticker is the only reliable way to validate output quality.
