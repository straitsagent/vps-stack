# Implementation Log — Portfolio Candidate Eval Initial Build
**Date:** 2026-06-17
**Commits:** `b834ae5`, `058a2e5`, `b72a84e`, `8c51416`
**Files changed:** `windmill/u/admin/portfolio_candidate_eval.py` (new, 1,160 → 1,511 lines after email fix), `windmill/u/admin/portfolio_candidate_eval.script.yaml` (new), `portfolio/schema.sql`, `agent/classifier.py`, `agent/tools.py`, `agent/tests/test_windmill_scripts.py`, `agent/tests/test_classifier.py`, `CLAUDE.md`
**Tests:** 17 structural + 2 classifier = 19 new tests; 344 passing, 1 skipped

---

## Plan Completed

Full implementation of `portfolio_candidate_eval` — a 3-gate ADD/WATCH/PASS verdict script built to the v1.1 framework design (incorporating all MINIMAX B-findings). Includes Telegram agent integration (classifier + tools) and DB persistence. Built TDD (tests first, then implementation).

---

## Architecture Implemented

```
INPUT: ticker, universe_tickers (optional), thesis_text (optional),
       replacement_ticker (optional), portfolio_db, gmail_smtp, xai_key,
       deepseek_key, recipient_email

GATE 1 — Absolute red-flag check (same thresholds as rationalization)
  - debt_to_equity > 5, interest_coverage < 1.5, negative_equity, revenue_decline >30%,
    net_margin < -20%, fcf_quality < -0.3
  → Any flag → PASS immediately

GATE 2 — Portfolio fit (6 sub-checks)
  - B1: price correlation vs all 33 positions (date-range guard; yfinance fallback if <60d)
  - B2: fundamental cosine similarity (sector, country, factor vector)
  - Sector / geography overlap counts
  - B8: currency-exposure check (HKD/USD soft 30% limit)
  - B3: factor gap-fill (pool_median_F < 50 AND candidate_F > pool_p60_F; ≥2 = gap-fill)
  - Sizing context (current position count, sector concentrations)

GATE 3 — Universe benchmark (peer_comparisons table)
  - B4: min_pool=5; below_min_universe flag for 3-4 peers; thin_universe for <3
  - B9: _validate_universe heterogeneity guard (market-cap CoV, sector/country diversity)
  - B10: baseline staleness check (portfolio_scores.score_date > 35d → warn)
  - Per-factor triplets: {absolute, portfolio_pct, universe_pct}

VERDICT (deterministic, B6):
  ADD: gate1 ok AND universe_composite_pct ≥ 60 AND no blocking constraint
  WATCH: gate1 ok AND ≥ 40 AND one mutable constraint
  PASS: otherwise

Grok-4.3: narrate with show-your-work JSON (C2: verdict + rationale_sentences with evidence arrays)
Deepseek-chat fallback if Grok unavailable

B7: replacement_ticker parameter → Gate 2 recomputed net of exit ticker
B11: eval cached in portfolio_candidate_evals; TTL=30d; skips re-eval if recent result exists

EMAIL: rich data-driven HTML report (see Change 2 below)
```

---

## All Tasks Performed

1. Added `CREATE TABLE portfolio_candidate_evals` DDL to `portfolio/schema.sql`; applied to live DB
2. Wrote 19 tests (17 structural source-inspection + 2 classifier) — confirmed RED
3. Implemented `portfolio_candidate_eval.py` — 1,160 lines covering all gates, verdict logic, Grok integration, email, DB persistence, Telegram wiring
4. Implemented `portfolio_candidate_eval.script.yaml` — param schema (ticker, universe_tickers, thesis_text, replacement_ticker, portfolio_db, gmail_smtp, xai_key, deepseek_key, recipient_email)
5. Added `candidate_evaluation` intent to `agent/classifier.py`
6. Added `dispatch_candidate_eval` function to `agent/tools.py`; registered in `INTENT_DISPATCH_MAP`
7. Confirmed 19 tests GREEN (344 total)
8. Pushed via `wmill script push u/admin/portfolio_candidate_eval.py`
9. Ran live test → hit Bug 1 (RealDictCursor KeyError) → fixed → Bug 2 (terse Grok-only email) → full email rebuild
10. Updated `CLAUDE.md` — added 3.4 candidate eval to Analytics & Research Stack table

---

## Bugs Encountered

### Bug 1 — `RealDictCursor` aggregate query raises `KeyError: 0`

**Symptom:** First live run failed with `KeyError: 0` when reading the latest eval date from `portfolio_candidate_evals`.

**Code (broken):**
```python
cur.execute("SELECT MAX(eval_date) FROM portfolio_candidate_evals WHERE ticker = %s", (ticker,))
row = cur.fetchone()
latest = row[0] if row else None
```

**Root cause:** psycopg2's `RealDictCursor` (used by the Windmill PostgreSQL resource) returns rows as dicts, not tuples. `row[0]` raises `KeyError: 0` — there is no integer key.

**Fix (commit `b72a84e`):**
```python
cur.execute("SELECT MAX(eval_date) AS latest FROM portfolio_candidate_evals WHERE ticker = %s", (ticker,))
row = cur.fetchone()
latest = row["latest"] if row and row["latest"] else None
```

**Rule for future:** Windmill PostgreSQL resource connections always use `RealDictCursor`. Never use positional index (`row[0]`) for column access — always use a named alias and dict key. This applies to every aggregate query (`COUNT`, `MAX`, `MIN`, `SUM`) since they don't have inherent column names.

---

### Bug 2 — Email report contained only Grok narrative (no data)

**Symptom:** The first clean run (after Bug 1 fix) sent an email containing only the Grok narrative block with no quantitative tables, gate results, or metrics.

**Root cause:** The initial `_build_report_body()` implementation was a placeholder — it rendered only the Grok synthesis output. The rich data-driven email was not yet built.

**Fix (commit `8c51416`):** Complete rebuild of `_build_report_body()` — 336 net new lines — producing a full data-driven HTML report:
- Methodology section (gates, verdict thresholds, blocking constraints)
- Input data table (all fetched metrics with sources)
- Gate 1: threshold vs actual vs result for each of 5 checks
- Gate 2: 6 sub-sections (price correlation, fundamental similarity, sector/geo overlap, currency exposure, factor gap-fill, sizing context)
- Gate 3: peer universe table with per-factor percentile ranks
- Portfolio comparison: full 31-position ranked table with candidate inserted at its score position
- Per-factor triplets (absolute / portfolio-pct / universe-pct)
- Grok narrative (JSON block stripped from display)
- Methodology footer (data freshness, eval validity date)

Also fixed: `recipient_email` default had been hardcoded to `straitsagent@gmail.com`. Changed to `""` with a Windmill variable fallback (`$var:u/admin/recipient_email`).

**Rule for future:** When building a new Windmill script, include the email report structure in the initial test plan — not as an afterthought. A script that emails results should have the email content described in the design sign-off (Hard Rule 7), not discovered to be incomplete on the first live run.

---

## Lessons Learned

1. **Always use named column aliases with `RealDictCursor` aggregate queries.** `SELECT MAX(...) AS col_name` and access via `row["col_name"]`. Every bare `SELECT aggregate_fn(...)` without an alias will fail with `KeyError` on the Windmill PostgreSQL connection.

2. **Email output format belongs in the design sign-off.** The post-commit email rebuild (336 lines) was equivalent in size to a second feature. The original Hard Rule 7 design approval described gates and verdict logic but not the email report structure. Future designs should include the email layout explicitly so it is built correctly the first time.

3. **Test structural coverage ≠ functional coverage for output quality.** The 17 source-inspection tests verified that all gate logic, functions, and DB persistence code was present. They could not verify that the email output was complete and readable. For scripts whose primary output is an email, include a "review the actual email" step in the TDD verification checklist.

4. **TTL caching before live testing can hide bugs.** B11 caching (skip re-eval if result exists within 30d) means a partially-broken first run can be cached and returned on the next test. When debugging, always either clear the cache table or use a ticker with no prior eval.
