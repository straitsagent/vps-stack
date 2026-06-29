# Implementation Log — `macro_research` yfinance → Finnhub + FRED Migration
**Date:** 2026-06-29
**Scope:** Replace all Yahoo Finance data fetches in `macro_research.py` with Finnhub ETF proxies and expanded FRED series. yfinance was rate-limiting all 25 tickers simultaneously, causing `IndexError` on every scheduled run. Concurrent fix: `morning_news_digest` IndentationError.

---

## 1. Trigger

Health check on 2026-06-29 showed two failing scripts:

| Script | Error | Failing since |
|---|---|---|
| `morning_news_digest` | `IndentationError: unexpected indent` (line 67) | 2026-06-26 |
| `macro_research` | `YFRateLimitError` → `IndexError: single positional indexer is out-of-bounds` | Recent consecutive runs |

### Root Cause — `morning_news_digest`
`def _send_telegram(bot_token: str, chat_id: str, text: str):    import urllib.request as _urlreq` — the function definition and first import statement were on one line with no newline after the colon. Caused `IndentationError: unexpected indent` at every import.

**Fix:** Split into two lines via `python3 -c` string replace, pushed. One-line change, no plan required.

### Root Cause — `macro_research`
`yf.download(25_tickers, period="5d")` returned an empty DataFrame when Yahoo Finance rate-limited all tickers simultaneously. `data["Close"].ffill().iloc[-1]` on an empty DataFrame → `IndexError`. No retry logic, no fallback.

**User decision:** Migrate to Finnhub + FRED rather than adding retry logic around a rate-limited dependency.

---

## 2. Data Coverage Analysis

Before writing any code, verified what each Yahoo symbol could be replaced with:

### Can move to FRED (1-day lag, acceptable for daily brief)

| Yahoo symbol | FRED series | Notes |
|---|---|---|
| `^VIX` | `VIXCLS` | CBOE Volatility Index — daily |
| `^FVX` | `DGS5` | 5Y Treasury |
| `^TNX` | `DGS10` | 10Y Treasury |
| `^TYX` | `DGS30` | 30Y Treasury |
| `DX-Y.NYB` | `DTWEXBGS` | USD Broad Index |
| `EURUSD=X` | `DEXUSEU` | EUR/USD |
| `GBPUSD=X` | `DEXUSUK` | GBP/USD |
| `JPY=X` | `DEXJPUS` | USD/JPY |
| `CNY=X` | `DEXCHUS` | USD/CNY |
| `SGD=X` | `DEXSIUS` | USD/SGD |
| `HKD=X` | `DEXHKUS` | USD/HKD |
| `BZ=F` | `DCOILBRENTEU` | Brent Crude |
| `NG=F` | `DHHNGSP` | Nat Gas Henry Hub |

### Finnhub ETF proxies (real-time quotes, free tier confirmed working)

Direct index symbols (`^GSPC`, `^NDX`, `^N225` etc.) return NO_DATA on Finnhub free tier. ETF proxies tested and confirmed:

| Yahoo symbol | Finnhub symbol | ETF description |
|---|---|---|
| `^GSPC` | `SPY` | S&P 500 ETF |
| `^NDX` | `QQQ` | Nasdaq 100 ETF |
| `^RUT` | `IWM` | Russell 2000 ETF |
| `^N225` | `EWJ` | iShares Japan |
| `^GDAXI` | `EWG` | iShares Germany |
| `^FTSE` | `EWU` | iShares UK |
| `^HSI` | `EWH` | iShares Hong Kong |
| `000300.SS` | `FXI` | iShares China Large Cap |
| `HYG` | `HYG` | HY Corporate Bond ETF (direct) |
| `LQD` | `LQD` | IG Corporate Bond ETF (direct) |
| `HG=F` | `CPER` | Copper ETF |
| `GC=F` | `GLD` | Gold ETF |

**Gold note:** FRED series `GOLDAMGBD228NLBM` does not exist (HTTP 400). GLD via Finnhub used instead. `BZ=F` and `NG=F` were moved to FRED (`DCOILBRENTEU`, `DHHNGSP`) where they returned valid values.

---

## 3. Implementation

All changes made to `/root/windmill/u/admin/macro_research.py` (726 lines in, ~753 out).

### 3.1 Dependency change

Removed from requirements header: `# yfinance>=0.2.40`
Removed import: `import yfinance as yf`
Removed import: `import math` (was only used for `math.isnan` in the deleted Yahoo fetch function)

### 3.2 `FINNHUB_SYMBOLS` dict (new, replaces `YAHOO_SYMBOLS`)

12 entries: 3 US equity ETFs, 5 global ETFs, 2 credit ETFs, 2 commodity ETFs.

### 3.3 `FRED_SERIES` expansion

13 → 29 series. New entries:
- `DGS5`, `DGS10`, `DGS30` — full rate curve
- `VIXCLS` — volatility index
- `DTWEXBGS`, `DEXUSEU`, `DEXUSUK`, `DEXJPUS`, `DEXCHUS`, `DEXSIUS`, `DEXHKUS` — FX rates
- `DCOILBRENTEU`, `DHHNGSP` — commodities

### 3.4 `_fetch_finnhub_data(api_key)` (replaces `_fetch_yahoo_macro()`)

Per-symbol `GET /quote` calls. Per-symbol error handling: one bad ticker does not abort the entire fetch. Returns `{"value": None, "change_pct": None}` on exception.

### 3.5 `_FRED_FMT` dispatch dict (new)

Added a dispatch dict for non-percentage FRED series that would otherwise format incorrectly with the default `f"{val:.2f}%"` formatter (e.g. VIX=18.89 → `18.89%`, FX rates, commodity prices):

```python
_FRED_FMT: dict = {
    "NFCI":         lambda v: f"{v:.3f}",
    "VIXCLS":       lambda v: f"{v:.1f}",
    "DEXUSEU":      lambda v: f"{v:.4f}",
    "DEXJPUS":      lambda v: f"{v:.2f}",
    "DCOILBRENTEU": lambda v: f"${v:.1f}",
    "DHHNGSP":      lambda v: f"${v:.3f}",
    ...
}
```

`_fmt_fred_val()` checks `_FRED_FMT` first, falls back to `f"{val:.2f}%"` for rate/spread/inflation series.

### 3.6 Renamed helpers

| Old | New | Note |
|---|---|---|
| `YAHOO_SYMBOLS` | `FINNHUB_SYMBOLS` | |
| `_YAHOO_FMT` | `_MARKET_FMT` | 11 entries — ETF proxies only, no rates/FX |
| `_YAHOO_DISPLAY` | `_MARKET_DISPLAY` | Shows ETF ticker: `SP500 (SPY)` |
| `_fmt_yahoo_cell()` | `_fmt_market_cell()` | |
| `_yahoo_data_str()` | `_market_data_str()` | |
| `_YAHOO_GROUPS` | `_MARKET_GROUPS` | 4 groups vs 5 |
| `yahoo` variable | `market` | In `main()` and `_build_email_html()` |

### 3.7 Section data assembly changes

| Section | Old data source | New data source |
|---|---|---|
| `equity_data` | `_yahoo_data_str(yahoo, ["VIX","SP500",...])` | `_market_data_str(market, ["SP500",...])` + `_fred_data_str(fred, ["VIXCLS"])` |
| `rates_data` | Yahoo rates (UST5Y/10Y/30Y) + FRED | `_market_data_str(market, ["HYG","LQD"])` + `_fred_data_str(fred, ["DFF","SOFR","DGS2","DGS5","DGS10","DGS30","T10Y2Y","T10Y3M"])` |
| `fx_data` | `_yahoo_data_str(yahoo, ["DXY","EURUSD",...])` + credit FRED | All FRED: `["DTWEXBGS","DEXUSEU",...,"BAMLH0A0HYM2","BAMLC0A0CM"]` |
| `comm_data` | `_yahoo_data_str(yahoo, ["Gold","Brent","Copper","NatGas"])` | `_market_data_str(market, ["Copper","Gold"])` + `_fred_data_str(fred, ["DCOILBRENTEU","DHHNGSP"])` |
| `hk_data` | `_yahoo_data_str(yahoo, ["HSI","CSI300","USDHKD","USDCNY"])` | `_market_data_str(market, ["HSI","CSI300"])` + `_fred_data_str(fred, ["DEXHKUS","DEXCHUS"])` |

### 3.8 `main()` signature change

Added `finnhub_key: str` (second positional parameter, after `fred_api_key`).
Front-matter key renamed: `indicators.yahoo` → `indicators.market`.

### 3.9 Windmill resources

`$var:u/admin/finnhub_key` was already present in Windmill. Schedule YAML updated to pass it.

---

## 4. Files Changed

| File | Change |
|---|---|
| `windmill/u/admin/macro_research.py` | MODIFIED — yfinance removed; Finnhub + expanded FRED |
| `windmill/u/admin/macro_research.script.yaml` | MODIFIED — `finnhub_key` added to properties + required |
| `windmill/u/admin/macro_research_daily.schedule.yaml` | MODIFIED — `finnhub_key: $var:u/admin/finnhub_key` added |

**Commit:** `0c77b35` — pushed to `vps-stack` main.

---

## 5. Live Verification (Hard Rule 17)

Test run triggered immediately after push (job `019f10de`):

```
INFO [MacroResearch] Fetching Finnhub market data...
INFO [MacroResearch] Fetching FRED data...
INFO [MacroResearch]   equity: 408 words
INFO [MacroResearch]   rates: 445 words
INFO [MacroResearch]   fed: 447 words
INFO [MacroResearch]   fx_credit: 469 words
INFO [MacroResearch]   commodities: 250 words
INFO [MacroResearch]   hk_china: 324 words
INFO [MacroResearch] Deepseek: 1599p + 3101c · est. $0.0038
INFO [Email] Sent: Macro Research — Mon 29 Jun 2026, 8:54 AM SGT
INFO [Dispatch] macro_daily_push_telegram job_id=019f10df-...
```

Result: `{"status": "sent", "total_words": 2343, "est_cost_usd": 0.0038}` ✅

---

## 6. Data Source Map (post-migration)

| Indicator | Source | Symbol/ID | Lag |
|---|---|---|---|
| SP500, NDX, RUT | Finnhub | SPY, QQQ, IWM | Real-time |
| Nikkei, DAX, FTSE, HSI, CSI300 | Finnhub | EWJ, EWG, EWU, EWH, FXI | Real-time |
| HYG, LQD | Finnhub | HYG, LQD | Real-time |
| Gold | Finnhub | GLD | Real-time |
| Copper | Finnhub | CPER | Real-time |
| VIX | FRED | VIXCLS | 1 day |
| Fed Funds, SOFR | FRED | DFF, SOFR | 1 day |
| UST 2Y/5Y/10Y/30Y | FRED | DGS2/5/10/30 | 1 day |
| Yield curve | FRED | T10Y2Y, T10Y3M | 1 day |
| Breakeven inflation | FRED | T5YIE, T10YIE | 1 day |
| CPI/PCE | FRED | CPIAUCSL, PCEPI (units=pc1) | Monthly |
| Unemployment, NFCI | FRED | UNRATE, NFCI | Monthly/Weekly |
| HY/IG OAS | FRED | BAMLH0A0HYM2, BAMLC0A0CM | 1 day |
| USD Broad Index | FRED | DTWEXBGS | 1 day |
| EUR/GBP/JPY/CNY/SGD/HKD | FRED | DEXUSEU/UK/JP/CH/SI/HK | 1 day |
| Brent Crude | FRED | DCOILBRENTEU | 1 day |
| Nat Gas | FRED | DHHNGSP | 1 day |

---

## 7. Outstanding Items

| Item | Status |
|---|---|
| `macro_daily_push_telegram.py` front-matter key | Changed `indicators.yahoo` → `indicators.market`. Confirm formatter handles new subkey — backward compat block reads by subkey presence. |
| `morning_news_digest` live verify | IndentationError fixed; next scheduled run (6:30 AM SGT) will confirm. |
| Testing Phase D (`docs/plans/2026-06-28_testing-phase-d.md`) | `macro_research` harness will need updating: mock target is now `_fetch_finnhub_data`, not `_fetch_yahoo_macro`. |
