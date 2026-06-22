# Fundamentals API Audit — F0 Research

**Date:** 2026-06-05  
**Purpose:** Evaluate candidate APIs for the Analytics & Research Stack (Phase F1 — Fundamentals Infrastructure)  
**Portfolio context:** ~33 tickers, mix of US-listed (AMZN, META, NVDA, BABA, etc.) and HK-listed (9988.HK, 0700.HK, 3690.HK, 9888.HK, etc.)  
**Required fields:** P/E, P/B, EV/EBITDA, revenue growth YoY, net margin, debt/equity, analyst target price, market cap, sector, geography

---

## Keys Already in Hand

All four candidate APIs have keys in `/root/shared/keys.md` — no sign-up friction:

| API | Key ref in keys.md |
|---|---|
| FMP | `FinancialModellingPrep` |
| Alpha Vantage | Two keys: `AlphaVantage (1)` and `AlphaVantage (2)` |
| Finnhub | `Finnhub` |
| yfinance | No key needed |

**Also noted:** A Supabase project named `stock-analysis-db` exists in keys.md with both anon and service role JWTs. This suggests a prior attempt at a stock analysis database. Worth investigating before building new PostgreSQL tables in F1 — the schema or data may be reusable.

---

## Executive Summary

**Architecture: multi-source field mapping, not a single primary API.**

No single API is optimal across all fields and exchanges. The right design calls each source for what it does best — Finnhub's free tier for US valuation ratios, yfinance for HK fundamentals and analyst targets, Alpha Vantage OVERVIEW for income statement fields, FMP as a structured fallback or for historical series if needed. This gives full field coverage at zero or near-zero cost, with no single point of failure.

The fetcher (F1) should have a field-resolution layer: for each field × exchange combination, it knows which source to call first and where to fall back if that source returns null.

---

## Live Test Results (run 2026-06-05 from VPS)

### yfinance — HK tickers

All 4 HK tickers returned cleanly with `sleep(2)` between calls. No rate limiting from VPS IP.

| Ticker | PE | PB | EV/EBITDA | Rev Growth | Net Margin | D/E | Analyst Target | Sector |
|---|---|---|---|---|---|---|---|---|
| 9988.HK (Alibaba) | 19.3 | 1.86 | 21.2 | 2.9% | 10.1% | 25.0 | HK$183.77 | Consumer Cyclical |
| 0700.HK (Tencent) | 16.4 | 3.17 | 14.8 | 9.1% | 30.6% | 33.5 | HK$709.36 | Comm. Services |
| 3690.HK (Meituan) | None† | 2.74 | -10.3† | 5.6% | -10.9%† | 75.3 | HK$109.18 | Consumer Cyclical |
| 9888.HK (Baidu) | None† | 1.12 | 15.0 | -1.2% | 1.0% | 32.2 | HK$179.60 | Comm. Services |

† Null P/E and negative margins for Meituan/Baidu are correct — both loss-making or near-breakeven. Not a data gap.

**Verdict: yfinance confirmed working from VPS for HK fundamentals. Full field coverage. $0 cost.**

---

### Finnhub — US and HK

Endpoint: `/stock/metric?metric=all` (60 calls/min, free)

| Field | NVDA (US) | 9988.HK (HK) |
|---|---|---|
| P/E | 32.35 | ❌ Error — no HK coverage |
| P/B | 28.81 | ❌ |
| EV/EBITDA | 31.17 | ❌ |
| Revenue Growth YoY | 70.68% | ❌ |
| Net Margin | 62.97% | ❌ |
| Debt/Equity | 0.054 | ❌ |
| Analyst Target | None‡ | ❌ |

‡ Analyst targets return null at the free tier — not included in `/stock/metric`.

**Verdict: Excellent for US valuation ratios in a single free call. No HK coverage. No analyst targets.**

---

### Alpha Vantage — US and HK

Endpoint: `OVERVIEW` (25 calls/day per key × 2 keys = 50 calls/day combined)

| Field | NVDA (US) | 9988.HK (HK) |
|---|---|---|
| P/E | 32.89 | ❌ None — no HK data |
| P/B | 27.61 | ❌ |
| EV/EBITDA | 27.61 | ❌ |
| Revenue Growth YoY | 85.2% | ❌ |
| Net Margin | 63.0% | ❌ |
| **Analyst Target** | **$298.07 ✅** | ❌ |
| Sector | TECHNOLOGY | ❌ |
| Country | USA | ❌ |
| Market Cap | $5.20T | ❌ |

**Key finding: Alpha Vantage is the only free source that returns analyst target prices for US stocks.** Finnhub doesn't include them in the free basic financials endpoint.

**Verdict: Essential for US analyst targets and sector/country classification. No HK coverage.**

---

### FMP — Current API State

FMP broke v3 endpoints for non-legacy accounts after August 2025. Stable API (`/stable/`) is the current interface.

| Endpoint | AAPL (US) | 9988.HK (HK) |
|---|---|---|
| `/stable/profile` | ✅ Market cap, sector, country, price | ✅ Works on free tier |
| `/stable/key-metrics-ttm` | ✅ EV multiples, ROE, ROIC, working capital, Graham number | ❌ Empty — paywalled |
| `/stable/financial-ratios-ttm` | ❌ Empty — paywalled | ❌ Empty |

**Note:** FMP `key-metrics-ttm` does NOT include traditional P/E or P/B — it focuses on capital efficiency metrics (ROE, ROIC, ROTA, EV multiples, cash conversion cycle, Graham number). These are supplementary for deeper analysis, not the core valuation fields.

**Verdict: Free tier useful for capital efficiency ratios (US only) and HK company profiles. Traditional valuation ratios not accessible without paid plan. Paid plan not required — yfinance covers HK well and Finnhub covers US valuation ratios.**

---

## Confirmed Coverage Matrix

| Field | yfinance | FMP free | Alpha Vantage | Finnhub free |
|---|---|---|---|---|
| P/E | ✅ US + HK | ❌ | ✅ US only | ✅ US only |
| P/B | ✅ US + HK | ❌ | ✅ US only | ✅ US only |
| EV/EBITDA | ✅ US + HK | ✅ US (key-metrics) | ✅ US only | ✅ US only |
| Revenue Growth YoY | ✅ US + HK | ❌ | ✅ US only | ✅ US only |
| Net Margin | ✅ US + HK | ❌ | ✅ US only | ✅ US only |
| Debt/Equity | ✅ US + HK | ❌ | ❌ (extra call) | ✅ US only |
| **Analyst Target** | ✅ US + HK | ❌ | ✅ **US only** | ❌ |
| ROE / ROIC / ROTA | ✅ partial | ✅ US (key-metrics) | ❌ | ✅ US only |
| Sector / Country | ✅ US + HK | ✅ profile only | ✅ US only | ❌ |
| Market Cap | ✅ US + HK | ✅ US + HK (profile) | ✅ US only | ✅ US only |
| **HK coverage** | ✅ **Full** | Profile only | ❌ | ❌ |
| Rate limit | Unofficial | 250/day | 25/day × 2 keys | 60/min |
| Cost | Free | Free | Free | Free |

---

## Per-API Notes

### 1. yfinance

**What it is:** Unofficial Python scraper of Yahoo Finance. No key, no account. `pip install yfinance`.

**HK coverage:** Full. `yf.Ticker("9988.HK").info` and `yf.Ticker("0700.HK").info` return all required fundamental fields. One of yfinance's strongest use cases vs. competitors.

**Rate limits:** No published limit — unofficial scraping. VPS/datacenter IPs are higher risk than residential IPs. Reported thresholds vary widely (100 to 0 requests before 429). The P1 price fetcher already uses yfinance for EOD prices — fundamentals calls add volume.

**Known reliability issues (2024-2026):**
- `YFRateLimitError` affected many server-deployed users (April 2025 wave)
- `.info` field availability can break silently when Yahoo changes internal endpoints
- Some fields return `None` for specific tickers even when data shows on Yahoo website
- `quarterly_financials`, `balance_sheet` DataFrames have historically returned empty during Yahoo-side changes; `.info` is the most stable surface

**Mitigations for VPS use:**
- `time.sleep(2-3)` between tickers
- Wrap all `.info` access in try/except with graceful `None` handling
- Cache results — fundamentals don't need daily refreshes
- Use `fast_info` for quick market cap / price checks

**Data freshness:** Fundamentals update within 1-2 days of earnings release. Price-based ratios update intraday.

**Verdict:** Free and complete for HK stocks. Build defensive retry + `None` handling everywhere. Not suitable as sole source if uptime reliability matters.

---

### 2. Financial Modeling Prep (FMP)

**Key endpoints:**
- `/v3/profile/{symbol}` — market cap, sector, country, beta, analyst target price
- `/v3/key-metrics-ttm/{symbol}` — PE, PB, EV/EBITDA, debt/equity, margin, revenue growth (all TTM)
- `/v3/ratios-ttm/{symbol}` — additional ratio depth
- `/v3/income-statement/{symbol}` — raw financials for manual YoY calculations

**HK coverage:**
- Free tier: US exchanges only. HK stocks return no data.
- Starter and above: Full HKEX coverage confirmed. FMP website has live data for 9988.HK, 3690.HK, 0700.HK, 9888.HK — clearly in the system.
- Claims 70,000+ securities across 60+ exchanges including HKEX.

**Free tier:** 250 calls/day, US exchanges only.

**Paid plans:**

| Plan | Price | Rate Limit | Notes |
|---|---|---|---|
| Starter | ~$22/mo | 300 calls/min | Unlocks UK/Canada and likely HKEX — confirm before subscribing |
| Premium | ~$59/mo | 750 calls/min | Broader international |
| Ultimate | ~$149/mo | 3,000 calls/min | Full global + transcripts + bulk |

**Call budget for 33 tickers (one full refresh):** ~99 calls (profile + key-metrics + ratios per ticker). Well within Starter's 300/min limit.

**Python client:** `fmpsdk` (pip install fmpsdk) — official SDK, updated Jan 2025. Also works with plain `requests`.

**Data freshness:** Fundamentals update quarterly, same-day on earnings releases.

**Action required before subscribing:**
1. Test existing free key against `https://financialmodelingprep.com/api/v3/key-metrics-ttm/9988.HK?apikey=<key>` — check whether current key tier returns HK data or a paywall error.
2. Confirm via FMP support whether Starter or Premium is required for HKEX API access (website shows HK data exists, but tier gate for API access is ambiguous in public docs).

---

### 3. Alpha Vantage

**Key endpoint:** `OVERVIEW` function — ~50 fields per ticker in one call.

**Confirmed fields:** `PERatio`, `PriceToBookRatio`, `EVToEBITDA`, `AnalystTargetPrice`, `ProfitMargin`, `QuarterlyRevenueGrowthYOY`, `MarketCapitalization`, `Sector`, `Country`. Missing: `DebtToEquity` (requires separate BALANCE_SHEET calls, +2 API calls per ticker).

**HK coverage:** Ambiguous and likely thin. Alpha Vantage lists HKEX for price data but multiple independent sources confirm OVERVIEW fundamentals are US-focused. No confirmed working examples for HK tickers found (2025-2026).

**Free tier:** 25 calls/day, 5 calls/min — below the minimum needed for a 33-ticker portfolio even once per week.

**Paid plans:**

| Plan | Price | Rate Limit |
|---|---|---|
| Starter | $49.99/mo | 75 RPM |
| Professional | $99.99/mo | 150 RPM |
| Enterprise | $149.99/mo | 300 RPM |

**Verdict:** 25-call/day limit is a blocker at the free tier. Paid plans are more expensive than FMP for the same (or worse) HK coverage. Not recommended.

---

### 4. Finnhub

**Key endpoint:** `/stock/metric?symbol=AAPL&metric=all` — 117 data points for US stocks across valuation, margin, growth, and leverage categories.

**HK coverage:** Free tier is US-only for basic financials. International fundamentals including HK require a paid add-on. Pricing for global fundamentals is on a separate page (`finnhub.io/pricing-fundamental-data`) and is add-on based — total cost less transparent than FMP's flat plans.

**Free tier:** 60 calls/min, US real-time quotes, company news, SEC filings, US basic financials.

**Python client:** `finnhub-python` (pip install finnhub-python). Well-maintained.

**Verdict:** Excellent for US-only portfolios but HK requires paid add-ons with opaque pricing. FMP is a cleaner choice at comparable or lower cost for mixed US/HK.

---

## Confirmed Field-by-Field Source Mapping

### US-listed tickers (~20 tickers: AMZN, META, NVDA, BABA ADR, etc.)

| Field | Source | Endpoint / Field name | Fallback |
|---|---|---|---|
| P/E | **Finnhub** | `/stock/metric` → `peBasicExclExtraTTM` | yfinance `trailingPE` |
| P/B | **Finnhub** | same → `pbAnnual` | yfinance `priceToBook` |
| EV/EBITDA | **Finnhub** | same → `evEbitdaTTM` | yfinance `enterpriseToEbitda` |
| Revenue Growth YoY | **Finnhub** | same → `revenueGrowthTTMYoy` | Alpha Vantage `QuarterlyRevenueGrowthYOY` |
| Net Margin | **Finnhub** | same → `netProfitMarginTTM` | Alpha Vantage `ProfitMargin` |
| Debt/Equity | **Finnhub** | same → `totalDebt/totalEquityAnnual` | yfinance `debtToEquity` |
| **Analyst Target** | **Alpha Vantage** | OVERVIEW → `AnalystTargetPrice` | yfinance `targetMeanPrice` |
| Sector | **Alpha Vantage** | OVERVIEW → `Sector` | yfinance `sector` |
| Country | **Alpha Vantage** | OVERVIEW → `Country` | yfinance `country` |
| Market Cap | **Alpha Vantage** | OVERVIEW → `MarketCapitalization` | yfinance `marketCap` |
| ROE / ROIC (supplementary) | **FMP** | `/stable/key-metrics-ttm` → `returnOnEquityTTM`, `returnOnInvestedCapitalTTM` | yfinance partial |

**Rationale:** Finnhub's single `/stock/metric` call covers all core valuation, margin, and leverage ratios in one hit (60/min free). Alpha Vantage OVERVIEW is the only free source with analyst targets for US stocks — two keys gives 50 calls/day, sufficient for weekly refresh of 20 US tickers. FMP provides supplementary capital efficiency ratios (ROE, ROIC, Graham number) not available elsewhere at this depth.

### HK-listed tickers (~13 tickers: 9988.HK, 0700.HK, 3690.HK, 9888.HK, etc.)

| Field | Source | Endpoint / Field name | Fallback |
|---|---|---|---|
| P/E | **yfinance** | `.info` → `trailingPE` | FMP paid (if needed) |
| P/B | **yfinance** | `.info` → `priceToBook` | FMP paid |
| EV/EBITDA | **yfinance** | `.info` → `enterpriseToEbitda` | FMP paid |
| Revenue Growth YoY | **yfinance** | `.info` → `revenueGrowth` | FMP paid |
| Net Margin | **yfinance** | `.info` → `profitMargins` | FMP paid |
| Debt/Equity | **yfinance** | `.info` → `debtToEquity` | FMP paid |
| Analyst Target | **yfinance** | `.info` → `targetMeanPrice` | — |
| Market Cap | **yfinance** | `.info` → `marketCap` | FMP `/stable/profile` |
| Sector / Country | **yfinance** | `.info` → `sector`, `country` | FMP `/stable/profile` |

**Rationale:** Confirmed working from VPS with sleep(2) — full field coverage, no rate limiting. Finnhub and Alpha Vantage confirmed no HK fundamental data. FMP paid plan not needed.

---

## Fetcher Architecture (F1 design implication)

The F1 `fundamentals_fetcher` script should implement a field-resolution function rather than a single API call per ticker:

```
for each ticker:
    exchange = "HK" if ticker ends in ".HK" else "US"
    
    if exchange == "US":
        finnhub_data  = call Finnhub /stock/metric (valuation, margins, leverage)
        av_data       = call Alpha Vantage OVERVIEW (revenue growth, sector, country)
        yf_data       = call yfinance .info (analyst target, market cap, fill nulls)
        merged        = merge all three, preferring primary per field-map above
    
    if exchange == "HK":
        yf_data       = call yfinance .info (all fields)
        if yf_data has nulls and FMP key active:
            fmp_data  = call FMP profile + key-metrics (fill remaining nulls)
        merged        = yf_data with FMP fills

    upsert merged into fundamental_data table
    sleep(1-2s between tickers)
```

Nulls from any source are logged but do not block the upsert — partial data is better than no data, and the fetcher reports a per-field coverage summary after each run.

---

## API Call Budget (weekly refresh, 33 tickers)

| Source | Calls needed | Free limit | Within limit? |
|---|---|---|---|
| Finnhub | 33 (one /metric call per US ticker, ~20 US tickers) | 60/min | Yes — trivially |
| Alpha Vantage | 33 (one OVERVIEW per US ticker) × 2 keys | 25/day × 2 = 50/day | Yes — just fits; spread over 2 days if needed |
| yfinance | 33 (one .info call per ticker) | Unofficial, no hard limit | Yes — with sleep(2) between calls |
| FMP | HK fallback only (~13 HK tickers) | 250/day free (US only) | Paid plan needed for HK; test first |

**Total estimated cost at current key tiers: $0/mo** — pending FMP HK tier test. If FMP HK requires a paid plan and yfinance proves unreliable in production for HK tickers, Starter at ~$22/mo is the call.

---

## API Call Budget (weekly refresh, 33 tickers)

| Source | Calls needed | Free limit | Within limit? |
|---|---|---|---|
| Finnhub | ~20 (one `/stock/metric` per US ticker) | 60/min | ✅ Trivially |
| Alpha Vantage | ~20 (one OVERVIEW per US ticker) across 2 keys | 25/day × 2 = 50/day | ✅ Just fits; stagger across 2 days if needed |
| yfinance | 13 (one `.info` per HK ticker, sleep(2)) | Unofficial, confirmed safe | ✅ Tested from VPS |
| FMP | ~20 (key-metrics-ttm per US ticker, supplementary) | 250/day | ✅ Well within |

**Total estimated cost: $0/mo. No paid plan required.**

---

## Next Steps (F0 → F1 gate)

Tests complete. F0 is done. Before building F1:

- [x] **yfinance HK test** — confirmed working from VPS. Full field coverage, no rate limiting.
- [x] **FMP HK test** — confirmed: v3 legacy endpoints blocked; `/stable/key-metrics-ttm` empty for HK (paywalled); `/stable/profile` works for HK on free tier. Paid plan not needed.
- [x] **Finnhub US test** — confirmed: full valuation/margin/leverage fields for US, no HK coverage.
- [x] **Alpha Vantage test** — confirmed: analyst targets available for US, no HK coverage.
- [ ] **Investigate `stock-analysis-db` Supabase project** — prior n8n stock research agent DB. Check schema before designing F1 PostgreSQL tables — may have reusable structure or historical data.
- [ ] **Sign-off on F1 schema and fetcher design** before building.

---

## Sources

- [yfinance PyPI](https://pypi.org/project/yfinance/)
- [yfinance rate limit GitHub issues](https://github.com/ranaroussi/yfinance/issues/2422)
- [FMP pricing plans](https://site.financialmodelingprep.com/pricing-plans)
- [FMP 9988.HK financial summary](https://site.financialmodelingprep.com/financial-summary/9988.HK)
- [FMP key metrics API docs](https://site.financialmodelingprep.com/developer/docs/company-key-metrics-api)
- [fmpsdk PyPI](https://pypi.org/project/fmpsdk/)
- [Alpha Vantage OVERVIEW endpoint](https://www.macroption.com/alpha-vantage-company-overview/)
- [Alpha Vantage pricing](https://getpulsesignal.com/pricing/alphavantage)
- [Finnhub basic financials docs](https://finnhub.io/docs/api/company-basic-financials)
- [Finnhub pricing](https://finnhub.io/pricing)
- [Best Financial Data APIs 2026](https://www.nb-data.com/p/best-financial-data-apis-in-2026)
