# Implementation Log — Fundamentals Fetcher, Move Monitor, and Portfolio Email Fixes

**Date:** 2026-06-09
**Commits:** reconstructed from session transcripts (6MB JSONL)
**Files changed:** `windmill/u/admin/fundamentals_fetcher.py`, `windmill/u/admin/portfolio_move_monitor.py`, `windmill/u/admin/portfolio_email.py`, associated schedule YAMLs, `docs/ROADMAP.md`, `docs/WORKFLOW_ARCHITECTURE.md`, `CLAUDE.md`

---

## Plan Completed

Built the Fundamentals Fetcher (3.1) and Portfolio Move Monitor (2.4), and fixed a weekend-check regression in the portfolio email. The fundamentals fetcher runs weekly (Sunday 6PM SGT) and populates a `fundamental_data` table from Finnhub and yfinance. The move monitor runs hourly during market hours and fires an alert email when the portfolio moves ±1.5% or any position moves ±5% vs most recent close.

---

## All Tasks Performed

1. Designed and got approval for Fundamentals Fetcher (3.1) architecture: Finnhub for US valuation ratios (P/E, EV/EBITDA, P/S, P/B, dividend yield, revenue growth, net margin, ROE, ROIC), yfinance for analyst targets, sector, market cap, and all HK fields
2. Created `windmill/u/admin/fundamentals_fetcher.py` — weekly Sunday 6PM SGT schedule
3. Added FMP (Financial Modeling Prep) as fallback for US ROE/ROIC — subsequently removed after 402 errors (see Bug 1)
4. Fixed Finnhub percentage normalization — `roeTTM`, `roiTTM`, `netProfitMarginTTM`, `revenueGrowthTTMYoy` divided by 100 before DB insert (see Bug 2)
5. Updated architecture docs — renumbered F2/F3: portfolio review became F2 (prerequisite 3.1 already live), signal collection deferred to F3
6. Fixed `portfolio_email.py` — removed weekend check that was silently killing Friday close emails (see Bug 3)
7. Built Portfolio Move Monitor (2.4, `portfolio_move_monitor.py`) — fetches live prices for all 33 positions, compares to most recent close, fires alert email on breach
8. Fixed move monitor schedule — split single broad schedule into two targeted schedules: HK session (9AM–4PM SGT) and US session (9PM–1AM SGT), eliminating 5 hours of no-op polling between market sessions (see Bug 4)
9. Updated `ROADMAP.md` and `CLAUDE.md` — marked 3.1 and 2.4 as live with schedule details

---

## Bugs Encountered

### Bug 1 — FMP API returned 402 on free tier

**Symptom:** `fundamentals_fetcher` failed for all US tickers with HTTP 402 when calling FMP `/stable/key-metrics-ttm` to fetch ROE and ROIC.

**Root cause:** FMP's key-metrics endpoint requires a paid subscription. The free tier silently rejects it with 402 rather than returning partial data or a clear error message. This was not caught during design because FMP's documentation advertises the endpoint without clearly marking the tier gate.

**Fix:** Dropped FMP entirely. Discovered that Finnhub's `/stock/metric` call — already made for other valuation ratios — returns `roeTTM` and `roiTTM` in the same response payload. No additional API call required, no additional cost.

---

### Bug 2 — Finnhub percentage fields stored as raw values (e.g. 6297% net margin)

**Symptom:** `fundamental_data` table had nonsensical values after the first run: `net_margin` of 6297%, `revenue_growth` of 71 (meaning 7100%). Downstream portfolio rationalization scoring consumed these values directly, awarding maximum scores to any company with high margin or growth.

**Root cause:** Finnhub returns `netProfitMarginTTM`, `revenueGrowthTTMYoy`, `roeTTM`, and `roiTTM` as whole-number percentages (e.g. `62.97` for 62.97%, `70.68` for 70.68%). The script stored them as-is. When portfolio rationalization compared them to thresholds like `net_margin > 20`, a value of 6297 always scored maximum regardless of actual quality. The Finnhub API documentation does note this, but it was missed during implementation.

**Fix:** Divide all four Finnhub percentage fields by 100 before inserting into `fundamental_data`. Architecture doc updated to call out the normalization requirement explicitly.

---

### Bug 3 — Weekend check skipped valid Friday close portfolio email

**Symptom:** Saturday 6AM SGT portfolio email never arrived. Friday US close data was never delivered.

**Root cause:** `portfolio_email.py` contained an early-return guard: `if datetime.now().weekday() >= 5: return`. This was intended to avoid sending empty emails on weekends when markets are closed. However, Windmill schedules a job at the next occurrence of the cron expression after the job is created or edited. A job configured on Thursday evening for "6AM SGT daily" (cron: `0 30 22 * * *` UTC) would schedule its first run for Friday 6AM SGT — but if the edit happened after 6AM SGT Thursday, the first run was Saturday 6AM SGT, which was then killed by the weekend check.

**Fix:** Removed the weekend check entirely. The price fetcher (2.1) handles data availability — if there is no new data for the day, `portfolio_email` shows unchanged prices from the most recent close. The email always sends; it is never empty.

---

### Bug 4 — Move monitor schedule covered wrong hours (5 dead hours between sessions)

**Symptom:** Move monitor fired during Asian trading hours (correct) but then continued polling from 4PM–9PM SGT when neither HK nor US markets were open, consuming API quota and cron slots for zero benefit. US pre-open was not covered.

**Root cause:** The original schedule `0 0 1-10 * * 1-5` (1AM–10AM UTC = 9AM–6PM SGT) was a rough approximation of "business hours." It did not account for the structural gap between HK market close (4PM SGT) and US market open (9:30PM SGT). The 5-hour window in between has no price movement to monitor.

**Fix:** Split into two separate schedules: HK session (`9AM–4PM SGT`, `0 0 1-8 * * 1-5` UTC) and US session (`9PM–1AM SGT`, `0 0 13-17 * * 1-5` UTC). Eliminates the dead-zone polling and aligns alert coverage with actual market activity.

---

## Lessons Learned

1. **Verify API tier gates before designing around an endpoint.** FMP's free tier silently 402s on endpoints that appear available in docs. Spike a live call before committing to a data source in the design.
2. **Always check API field units against documentation.** Finnhub returning 62.97 for 62.97% is a known pattern — it should be in the implementation checklist for any new Finnhub field, not discovered post-deploy via nonsensical DB values.
3. **Do not guard scheduled jobs with time-of-day checks inside the script.** Windmill's scheduler controls when jobs run. Internal guards interact badly with schedule-creation timing and produce silent failures that are hard to diagnose. Push all temporal filtering to the schedule expression itself.
4. **Model trading sessions explicitly when building monitor schedules.** "Business hours" is an underspecified concept — HK, US, and EU sessions have distinct open/close times with gaps between them. Draw the timeline before writing the cron expression.
