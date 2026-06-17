# Implementation Log — Portfolio Rationalization v1.1 (3.3)
**Date:** 2026-06-14 to 2026-06-15
**Commits:** reconstructed from session transcripts
**Files changed:** `windmill/u/admin/portfolio_rationalization.py`, `windmill/u/admin/portfolio_rationalization.script.yaml`, `windmill/u/admin/portfolio_rationalization_monthly.schedule.yaml`, `portfolio/schema.sql`, `docs/ROADMAP.md`, `docs/portfolio_rationalization_framework.md`, `docs/WORKFLOW_ARCHITECTURE.md`

---

## Plan Completed

Monthly portfolio rationalization scoring system (Workflow 3.3) — designed, reviewed, built, and put live in Windmill. Scores 31 unique positions (after ADR consolidation) across 5 factors, runs two Grok-4.3 calls for per-position narratives and global synthesis, stores results to a new `portfolio_scores` table, and emails a structured report on the 1st of each month at 9PM SGT.

---

## All Tasks Performed

1. Drafted full design spec for the 5-factor monthly scoring system covering: factor definitions (quality, growth, valuation, sentiment, thesis), ADR consolidation approach (31 unique companies from 33 positions), absolute red flag rules, two-Grok-call architecture, delta tracking across monthly runs, Deepseek fallback, `portfolio_scores` schema, and report email format.
2. Reviewed design — incorporated 8 critical review findings before writing any code: absolute red flags as hard overrides, completeness penalty for data gaps, explicit ADR data merge logic, thesis staleness shown as display-only flag rather than score deduction, split into two Grok calls to avoid context length issues, Deepseek fallback if Grok fails, delta tracking against prior month's ranks, and upsert (not insert) to `portfolio_scores`.
3. Committed approved design to `docs/portfolio_rationalization_framework.md` (v1.0, then v1.1 after review findings).
4. Implemented `portfolio_rationalization.py` — all 5 scoring factors, `_compute_factor_scores`, `_apply_completeness_penalty`, `_fetch_prior_ranks`, `_build_ranking_table`, `_build_position_scorecard`, two Grok call functions, Deepseek fallback, SMTP send, full `main()` orchestration.
5. Created `portfolio_scores` table DDL and added it to `portfolio/schema.sql`; applied DDL to live DB.
6. Pushed script to Windmill via `wmill script push`.
7. Ran first live Windmill job — encountered 3 bugs (see below).
8. Fixed all 3 bugs, re-pushed, ran second live job — clean run, report emailed successfully.
9. Created `portfolio_rationalization_monthly.schedule.yaml` — cron `0 0 13 1 * *` (9PM SGT = 1PM UTC on 1st of month), schedule confirmed in Windmill UI.
10. Updated `ROADMAP.md` — marked 3.3 live; added schedule note.
11. Designed and committed candidate evaluation framework (3.4) at end of session, to be built in the next session.

---

## Bugs Encountered

### Bug 1 — `portfolio_positions` queried for `sector` and `country` columns that don't exist

**Symptom:** First live run crashed on `_fetch_positions` with `psycopg2.errors.UndefinedColumn: column portfolio_positions.sector does not exist`.

**Root cause:** `portfolio_positions` stores ticker, shares, currency, cost_basis, and ADR consolidation group — not sector or country. Those fields live in `company_profiles`. The initial implementation queried `portfolio_positions` for all position metadata including sector and country, assuming they were denormalised into the positions table.

**Fix:** Added `LEFT JOIN company_profiles cp ON pp.ticker = cp.ticker` to `_fetch_positions`, pulling `sector` and `country` from the correct table. All other `portfolio_positions` columns queried as before.

---

### Bug 2 — `_fetch_fundamentals` used stale column name assumptions from the initial schema

**Symptom:** Job crashed on `_fetch_fundamentals` with multiple `psycopg2.errors.UndefinedColumn` errors — column names did not match the actual `fundamental_data` table.

**Root cause:** The script was written against an assumed `fundamental_data` column schema before the actual column names were confirmed. The fundamentals fetcher (built 2026-06-09) uses specific column names (`pe_ratio`, `ev_ebitda`, `revenue_growth_yoy`, etc.) that differ from what was assumed during rationalization design. The two were never cross-referenced.

**Fix:** Read the actual `fundamental_data` table schema via `\d fundamental_data` and rewrote `_fetch_fundamentals` to use the correct column names throughout.

---

### Bug 3 — REPORT_DIR relative path caused silent file write failure

**Symptom:** Rationalization report generated successfully in memory and email was sent, but the email body was empty (no content). No exception raised.

**Root cause:** `REPORT_DIR = "research/portfolio/"` is a relative path. Windmill workers execute in an ephemeral working directory, so the file was written there rather than to `/root/research/portfolio/`. The email assembly step then attempted to read the file from `/root/research/portfolio/`, found nothing, and sent an empty body without raising an error (the read was wrapped in a try/except that silently swallowed the FileNotFoundError).

**Fix:** Changed to `REPORT_DIR = "/root/research/portfolio/"` (absolute path). Windmill workers mount `/root/` as a volume, so the absolute path is stable across job executions.

---

## Lessons Learned

1. **Cross-reference table schemas before writing queries.** When a new script reads from a table built by a different script (e.g. rationalization reading `fundamental_data` built by fundamentals_fetcher), confirm column names against the live schema before writing a single query. `\d tablename` takes 10 seconds; a failed live run takes longer.
2. **Always use absolute paths in Windmill scripts.** Windmill workers run in ephemeral working directories. Relative paths for file I/O will silently resolve to a temp dir that is discarded after the job. Every file read or write in a Windmill script must use an absolute path under `/root/`.
3. **Silence-swallowing try/except blocks are dangerous at boundaries.** The empty email body was a silent failure caused by a broad exception handler around the file read. Exception handlers on I/O boundaries should always log the error and ideally re-raise or send a fallback error email.
4. **Run a first live test immediately after first push, before scheduling.** The three bugs above were all caught in the first live run. If the schedule had been set first, the job would have failed silently on the 1st of the month with no immediate visibility.
5. **Schema design review findings before implementation pays off.** The 8 critical review findings incorporated before coding (absolute red flags, completeness penalty, ADR merge, etc.) all landed cleanly on first implementation. The bugs that did appear were infrastructure/wiring issues, not logic errors — a good ratio.
