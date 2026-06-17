# Implementation Log — Portfolio Intelligence System P0–P2

**Date:** 2026-06-04
**Sessions:** bdb56caa (1.2MB), d02bc164 (714KB)
**Files changed:** `docker-compose.yml`, `portfolio/schema.sql`, `portfolio/seed.sql`, `windmill/u/admin/portfolio_price_fetcher.py`, `windmill/u/admin/portfolio_email.py`, associated schedule YAMLs, `docs/ROADMAP.md`, `docs/WORKFLOW_ARCHITECTURE.md`, `CLAUDE.md`

---

## Plan Completed

Built the Portfolio Intelligence System from scratch: PostgreSQL infrastructure (P0), daily price fetcher (P1), and twice-daily portfolio email (P2). The system tracks 33 positions across US equities, HK equities (with FX conversion), and ADR pairs. Price history is stored in Postgres on the VPS; portfolio P&L emails are delivered twice daily.

---

## All Tasks Performed

1. Evaluated Google Sheets as a data backend — rejected after user could not grant service account permissions to a personal Sheets file
2. Decided on self-hosted PostgreSQL container on the VPS as the data layer
3. Updated `docs/ROADMAP.md` — added Portfolio Intelligence System as next major build, added PostgreSQL infra details, added Portfolio P0–P3 build status table, moved unimplemented workflows to Ideaboard
4. Updated `docs/WORKFLOW_ARCHITECTURE.md` — full pseudocode for P0 (Postgres infra, schema, 33-position seed), stubs for P1 (price fetcher), P2 (portfolio email), P3 (advanced analyses)
5. Built P0 — PostgreSQL infrastructure:
   - Added `portfolio_postgres` service to `docker-compose.yml` (postgres:16, internal only, no external port binding)
   - Created `portfolio/schema.sql` — tables: `portfolio_positions`, `price_history`, `fx_rates`
   - Created `portfolio/seed.sql` — 33 positions including ADR pairs (BABA/9988.HK, etc.)
   - Applied schema and seed to live DB via `docker exec`
   - Created Windmill resource `u/admin/portfolio_db` (postgres connection string)
6. Built P1 — `portfolio_price_fetcher.py`:
   - Fetches EOD prices for all 33 tickers via yfinance
   - Inserts into `price_history`
   - Fetches live USDHKD rate into `fx_rates` table
7. Built P2 — `portfolio_email.py`:
   - Reads positions and 2 days of prices from Postgres
   - Computes day P&L per position
   - Top 5 movers (up/down by $ impact)
   - Full positions table with local + USD prices
8. Upgraded P1: changed to insert last 2 trading days per ticker (`yfinance tail(2)`) on every run so P&L is immediately available on first run
9. Upgraded P2: consolidated ADR pairs (BABA + 9988.HK shown as one line), FX conversion for HKD positions to USD
10. Added twice-daily schedules for P1 (5:45 AM + 5:45 PM SGT) and P2 (6:00 AM + 6:00 PM SGT) via Windmill YAML
11. Fixed BRK-B ticker format in `seed.sql` (was `BRK.B`, yfinance requires `BRK-B`)
12. Enhanced P2 email: added portfolio impact % per mover, new "% Movers — Market Context" section ranking top 5 positions by % change with Finnhub news lookup
13. Enhanced P2 email: showed prev → curr price (native currency) in % Movers section alongside % change
14. Aligned all docs to current P2 state

---

## Bugs Encountered

**Bug 1 — `$res:` references in schedule YAML using dict form instead of string form**

- Symptom: all 4 portfolio schedules (P1 twice-daily + P2 twice-daily) failed on the first scheduled run with `KeyError: 'host'` — the `portfolio_db` resource was never resolved, so the script received an unresolved object instead of a live DB connection
- Root cause: schedule YAML files were written with `{"$res": "u/admin/portfolio_db"}` (dict form). Windmill only resolves resource references when they are plain strings in the format `"$res:u/admin/portfolio_db"`. The dict form is passed as-is to the script, which then calls `.get('host')` on a dict containing only a `$res` key — KeyError
- Fix: updated all 4 schedule YAML files to use plain string form. Documented as Hard Rule 11 in `CLAUDE.md` to prevent recurrence

**Bug 2 — BRK-B ticker format (`BRK.B` vs `BRK-B`)**

- Symptom: yfinance returned no data for the Berkshire position; `price_history` had no rows for BRK
- Root cause: yfinance uses a hyphen (`BRK-B`) not a dot (`BRK.B`) as the separator for share class notation. The dot format is the standard brokerage convention but not what yfinance accepts
- Fix: updated `seed.sql` to use `BRK-B`

**Bug 3 — First run returned no P&L data because only one day of prices existed**

- Symptom: on P1's first run, `price_history` contained only today's close. P2 requires two consecutive days to compute day-over-day P&L — the first email showed no change figures
- Root cause: P1 was initially designed to insert only the most recent price on each run (yfinance `tail(1)`). Without yesterday's price already in the table, the day-over-day delta was undefined
- Fix: changed P1 to insert the last 2 trading days (`yfinance tail(2)`) on every run. This is idempotent — existing rows are skipped on conflict — and ensures P2 always has both days from the first run onward

---

## Lessons Learned

1. Windmill schedule args must use plain string form for resource/variable references — `"$res:path"` not `{"$res": "path"}`. Dict form is silently passed unresolved. Test every schedule by running it manually before trusting it will work at cron time.
2. When inserting time-series data that will be used for delta computation on day one, seed the last N days on first insert — not just today's value.
3. yfinance ticker conventions differ from brokerage conventions — verify each non-standard ticker (share classes, HK equities) against yfinance before seeding the positions table.
4. Google Sheets as a data backend for a service account workflow requires manual sharing steps that may not be feasible. For VPS-hosted automation, a self-managed Postgres container is simpler to grant access to and more appropriate for structured time-series data.
