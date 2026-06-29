# yfinance Rate-Limit Exposure Audit

**Date:** 2026-06-29  
**Trigger:** `macro_research` migration from yfinance to Finnhub ETF proxies + FRED (commit `0c77b35`), prompted by recurring `YFRateLimitError` / `IndexError` on `yf.download()`.  
**Scope:** All live Windmill scripts under `windmill/u/admin/` that import yfinance.

---

## Root Cause of the macro_research Failure

`macro_daily_push.py` called `yf.download(25_tickers_simultaneously)` — a single concurrent batch request that overwhelmed Yahoo Finance's rate limiter. The symptom was an `IndexError` when the response returned an empty or malformed DataFrame. This pattern (batch download of multiple simultaneous tickers) is **specific to `macro_daily_push` and is not used by any other live script**.

---

## Scripts Using yfinance

| Script | Schedule | yfinance calls per run | Endpoint | Sleep between calls |
|---|---|---|---|---|
| `portfolio_price_fetcher` | 5:45 AM + 5:45 PM SGT, 7 days | 1 (USDHKD=X) + 33 (all tickers) = **34** | `.history(period="5d")` | **None** |
| `portfolio_move_monitor` | Hourly Mon–Fri (9 AM–6 PM SGT) | **33** | `.fast_info` | 0.2s |
| `fundamentals_fetcher` | Sunday 18:00 SGT | ~20 (US, Finnhub primary) + 13 (HK) = **33** | `.info` | 0.5s (US Finnhub loop) / 2s (HK) |
| `portfolio_review` | Saturday 08:00 SGT | Up to 15 (HK tickers, news fallback only) | `.news` | None specified |
| `portfolio_candidate_eval` | On-demand | 1 `.fast_info` (live price) + up to 34 `yf.download()` (correlation, only if <60d DB history) | `.fast_info` + `.download()` | None |
| `portfolio_earnings_analysis` | On-demand | 1 ticker | `.income_stmt` / `.balance_sheet` / `.cashflow` | — |
| `research_tool` | On-demand | 1 ticker (multiple calls: `.info`, `.news`, financials, valuation, ownership, insiders, earnings, management) | Multiple | None |
| `stock_data_fetcher` | On-demand (dispatched by research_tool / candidate_eval) | 1 ticker, same as research_tool | Multiple | None |
| `macro_daily_push` | **Disabled** (schedule removed 2026-06-26) | Was 25 (batch) | `yf.download(25_tickers)` | None — **this was the failure mode** |

---

## Risk Assessment

### `portfolio_price_fetcher` — Low-medium risk

- 34 sequential `.history()` calls, twice daily (68 calls/day total).
- **No sleep between ticker calls** — 33 calls fire as fast as the loop iterates.
- `.history()` hits Yahoo's chart API, a different endpoint from the batch download that broke macro. Sequential single-ticker requests are substantially less likely to trigger rate limits.
- However, it has **no retry or fallback** — a rate limit error would silently fail that ticker's price update, and downstream P&L calculations would show `—`.
- **Priority:** High consequence (core data pipeline; everything downstream depends on it), moderate probability. Worth adding a sleep and/or Finnhub fallback for US tickers.

### `portfolio_move_monitor` — Medium risk (highest call volume)

- 33 `.fast_info` calls at 0.2s spacing per run.
- Runs hourly during Mon–Fri market hours: roughly 9–10 runs/day × 33 = **~330 calls/day**.
- `.fast_info` uses Yahoo's `v8/finance/quote` endpoint, which is lighter than `.info` or `.history()`.
- Has been running without reported failures.
- **Primary concern:** cumulative daily volume — 330 calls/day is the highest of any script. If Yahoo tightens rate limits for the VPS IP, this is the first to feel it.
- Partial replacement possible for US tickers (Finnhub `/quote`, 60 calls/min free), but HK tickers (9988.HK, 0700.HK, 3690.HK, 9888.HK) have no free-tier intraday alternative.

### `fundamentals_fetcher` — Low risk

- Weekly run with explicit 2s sleep between HK calls and 0.5s between Finnhub calls.
- Well-spaced; even a rate limit retry next Sunday is acceptable.
- For HK tickers, yfinance `.info` is the **only free source** — Finnhub does not support HK tickers for fundamentals. No alternative exists.

### `portfolio_review` — Low risk

- Weekly run.
- yfinance `.news` for HK tickers only (US tickers use Finnhub `/company-news`).
- Failures gracefully omit the news section; email still sends.

### On-demand scripts (`portfolio_candidate_eval`, `research_tool`, `stock_data_fetcher`, `portfolio_earnings_analysis`) — Low risk

- Single-ticker per invocation.
- Rate limit on one call would affect one research run; no scheduled automation depends on them.
- `portfolio_candidate_eval` does call `yf.download(ticker, period="3mo")` for correlation calculation when DB history is sparse — but this is a single ticker, not a batch.

---

## Summary: Where Action May Be Warranted

| Priority | Script | Action |
|---|---|---|
| 1 | `portfolio_price_fetcher` | Add `time.sleep(0.3)` between ticker calls. Consider Finnhub `/quote` as fallback for US tickers on `429`. |
| 2 | `portfolio_move_monitor` | Monitor for `YFRateLimitError` in Windmill job logs. If rate limits appear, Finnhub `/quote` covers US tickers (20 of 33); HK tickers have no drop-in replacement. |
| — | `fundamentals_fetcher` | No action needed — well-spaced, weekly cadence. |
| — | On-demand scripts | No action needed — single-ticker, low frequency. |

---

## What Was Done

`macro_research.py` was fully migrated away from yfinance on 2026-06-29 (commit `0c77b35`):

- 25 `yf.download()` symbols replaced with 12 Finnhub ETF proxies (SPY, QQQ, IWM, EWJ, EWG, EWU, EWH, FXI, HYG, LQD, CPER, GLD).
- Gold moved from FRED (series GOLDAMGBD228NLBM does not exist) to Finnhub GLD ETF.
- 16 FRED series added: VIXCLS, DGS5/10/30, DTWEXBGS, DEXUS×6, DCOILBRENTEU, DHHNGSP, plus existing series.
- Live-verified: 2,343 words, $0.0038 cost, email delivered.

No other script was migrated. The `macro_daily_push.py` parent script remains on disk but is disabled.
