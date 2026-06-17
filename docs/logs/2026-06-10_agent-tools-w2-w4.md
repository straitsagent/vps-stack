# Implementation Log — Agent Tools W2/W3/W4 Expansion
**Date:** 2026-06-10 (continued from Telegram agent session)
**Commits:** reconstructed from session transcripts
**Files changed:** `agent/tools/thesis.py`, `agent/tools/earnings_calendar.py`, `agent/tools/news_search.py`, `agent/tools/macro_indicators.py`, `agent/planner.py`, `agent/intent_classifier.py`, `agent/tool_registry.py`, `windmill/u/admin/portfolio_earnings_alert.py`, `windmill/u/admin/portfolio_analyst_alert.py`, `windmill/u/admin/portfolio_earnings_analysis.py`, `agent/tests/`, `scripts/windmill-autopush.py`, `CLAUDE.md`, `docs/ROADMAP.md`

---

## Plan Completed

Expanded the live Telegram agent from its W1 baseline (intent classification + research dispatch) to W2 (direct tool calls for common queries), W3 (Windmill-based proactive alert scripts), and W4 (multi-step planner for compound questions). Also built the earnings analysis tool — a pre/post earnings briefing script with Grok-4.3 synthesis and EDGAR 8-K sourcing. Established TDD as a mandatory gate by adding a PostToolUse hook that injects a TDD reminder after every Python file edit and codifying Hard Rule 15 in CLAUDE.md.

---

## All Tasks Performed

1. Added `portfolio_thesis` W2 tool: `thesis_read` (FAST) and `thesis_write` (GATED_WRITE) intents; `portfolio_thesis` table added to DB schema; upsert on write
2. Added `earnings_calendar` W2 tool: FAST intent, direct Finnhub API call, returns upcoming earnings dates for portfolio tickers
3. Added `news_search` W2 tool: FAST intent, Exa search API, returns recent headlines for a named company or topic
4. Added `macro_indicators` W2 tool: FAST intent, httpx against Yahoo Finance v8 JSON API directly (no yfinance dependency — avoids the yfinance install overhead in the agent container)
5. Built `planner.py` for W4 multi-step reasoning: `_parse_plan()`, `plan()`, `synthesise()` using Deepseek; `MULTI_STEP` tool latency class added to tool registry
6. Added W4 intents: `portfolio_analysis`, `thesis_check`, `macro_brief` — all routed through the planner
7. Built `portfolio_earnings_alert.py` Windmill script (W3): scans all portfolio tickers for earnings in next 7 days; alerts on EPS surprises >5%; sends Telegram message via agent webhook
8. Built `portfolio_analyst_alert.py` Windmill script (W3): checks for analyst upgrades/downgrades via Finnhub; sends Telegram alert
9. Updated CLAUDE.md and ROADMAP.md: 84 tests, W2/W3/W4 all marked live
10. Fixed research cache SQL bug — `source_count` column does not exist (see Bug 1)
11. Added `test_check_research_cache_selects_correct_columns` to capture the SQL and assert `source_count` is not referenced directly
12. Built `portfolio_earnings_analysis.py` Windmill script: pre-earnings briefing (estimates, quarterly trend, prior 8-K) and post-earnings analysis; Grok-4.3 synthesis; EDGAR filings as primary source
13. Fixed EDGAR 8-K fetch path (see Bug 2)
14. Fixed `fundamental_data` column name mismatches (see Bug 3)
15. Added portfolio position context, research synopsis, token tracking, dated section headers, and correct email recipient to earnings analysis script
16. Added TDD PostToolUse hook to `windmill-autopush.py`: injects a TDD reminder message after every Python file edit
17. Added Hard Rule 15 (TDD mandatory) to CLAUDE.md
18. Created `/deploy-windmill` custom skill: resource preflight → design approval gate → push → live test with output inspection → docs + git commit
19. Synced all docs to current state (W2/W3/W4 + earnings analysis + TDD)

---

## Bugs Encountered

**Bug 1 — Research cache query referenced non-existent `source_count` column**
**Symptom:** The first `/research` command sent via Telegram failed before any search was performed. Agent logs showed a PostgreSQL error: `column "source_count" does not exist`.
**Root cause:** `_check_research_cache()` in `dispatch_research` contained `WHERE source_count > 0`. The `research_reports` table stores sources as a `text[]` array column named `sources` — there is no integer `source_count` column. The query was checking a column that had never been created.
**Fix:** Changed the predicate to `WHERE array_length(sources, 1) > 0`. Also added a structural unit test `test_check_research_cache_selects_correct_columns` that extracts the SQL string from the function and asserts that `source_count` is not referenced directly — catches future regressions at the red-phase.

**Bug 2 — EDGAR 8-K URL construction produced 404s**
**Symptom:** `portfolio_earnings_analysis.py` failed to retrieve any EDGAR 8-K press releases. Every EDGAR fetch returned HTTP 404.
**Root cause:** The script was constructing the document URL from the EDGAR submissions API (`data.sec.gov/submissions/CIK*.json`), which returns accession numbers in `XXXXXXXXXX-XX-XXXXXX` format. The URL template used this format directly, but the EDGAR `archives/` path requires the accession number with dashes stripped (`XXXXXXXXXXXXXXXXXX`). These are two incompatible representations of the same accession ID, and the mismatch produced well-formed but nonexistent URLs.
**Fix:** Switched to the EDGAR full-text search API (`efts.sec.gov/hits.json?q="CIK"&dateRange=custom&...`), which returns `_id` fields that map directly to the correct `archives/edgar/data/CIK/accession/` paths without any format transformation needed.

**Bug 3 — `fundamental_data` query used wrong column names**
**Symptom:** `portfolio_earnings_analysis.py` crashed with `KeyError: 'revenue_ttm'` on first live run when trying to read fundamentals for the ticker being analyzed.
**Root cause:** The query selected `revenue_ttm` and `fetched_at` — but the actual `fundamental_data` table has those columns named `net_margin` and `updated_at` respectively. The column names in the query were copied from an earlier draft of the schema that had since changed.
**Fix:** Updated the query to select the correct column names (`net_margin`, `updated_at`) as confirmed by reading `portfolio/schema.sql`.

---

## Lessons Learned

1. **SQL against real tables must be tested against the live schema, not assumptions.** Both the `source_count` and `fundamental_data` bugs arose from queries written against a mental model of the schema that had drifted from reality. A test that runs a `EXPLAIN` or parses the SQL for column names catches this before deployment.
2. **The EDGAR submissions API and the EDGAR archives URL format are not interchangeable.** The submissions API uses dashed accession numbers; the archives path requires them without dashes. When constructing EDGAR URLs, always use the EFTS search endpoint, which returns pre-built paths, or explicitly strip dashes when forming archive paths.
3. **The TDD PostToolUse hook is a forcing function, not just a reminder.** Adding the hook to `windmill-autopush.py` means TDD cannot be silently skipped — the reminder fires on every Python file edit. The hook makes omission visible rather than relying on discipline alone.
4. **Test the DB layer with real SQL parsing, not just mocked return values.** The `_check_research_cache` test that mocked the DB return would have passed even with the wrong column name. The fix was a test that inspects the SQL string itself. When a function's correctness depends on a specific SQL query, the test should assert the query, not just the return value.
5. **Yahoo Finance httpx direct calls are preferable to yfinance in the agent container.** yfinance is a large dependency and adds install time to every container rebuild. For simple macro indicator pulls, hitting the YF v8 JSON API directly with httpx is faster and avoids the dependency.
