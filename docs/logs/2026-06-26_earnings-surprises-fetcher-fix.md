# earnings_surprises Fetcher Fix — Implementation Log

**Date:** 2026-06-26
**Scope:** Repair the yfinance column-detection bug in `stock_data_fetcher` that left the
load-bearing `earnings_surprises` table empty; backfill all 33 portfolio positions.

## Root cause

`_fetch_earnings_calendar` detected the actual-EPS column with `"actual" in name`, but yfinance
names it `Reported EPS`. `actual_col` was always None → surprises block never ran → 0 rows.

Second issue discovered during live verification: yfinance `Ticker.earnings_dates` requires
`lxml` for HTML table parsing. The Windmill worker didn't have it, causing the entire
`t.earnings_dates` call to throw an exception (caught and logged). Added `lxml==5.3.0` to the
script lock, redeployed, and the data populated.

## Fix

- Added pure helpers `_pick_col`, `_is_blank`, `_extract_surprises` — pandas-free, unit-tested.
- Broadened actual-column detection to `["reported", "actual"]`; recomputed `surprise_pct` from
  estimate/actual with native `Surprise(%)` fallback; future (NaN-actual) rows excluded.
- Replaced the surprises sub-block in `_fetch_earnings_calendar` to use the new helpers.
- 3 regression tests added (RED→GREEN): `test_pick_col_detects_reported_eps_actual_column`,
  `test_extract_surprises_from_real_yfinance_records`, `test_extract_surprises_empty_when_no_actuals`.
- Full test suite: 481 passed (no regressions).

## Live verification (Hard Rule 17)

- AAPL one-off run: `ok: True`, `tables_written` included `earnings_surprises`.
  After lxml fix, psql showed 4 rows with non-null `surprise_pct` (3.6082, 6.3670, 4.5198, 9.7902).
- Backfill: 33/33 positions processed, all OK. Final coverage: 132 rows / 33 tickers — full.

## Downstream effect

- `portfolio_rationalization` EPS-beat factor now has data at the next Monday 9 PM run.
- `portfolio_candidate_eval` `AVG(surprise_pct)` queries now return real numbers.
- `research_tool` earnings section now has actual surprise data.
- No reader code changed.

## Note

- `research_tool.py:585` has an identical column-detection bug in its own `_fetch_earnings_calendar`
  (affects research-report earnings markdown only; it does not write the table). One-line fix
  pending — fold into a later hygiene pass.
