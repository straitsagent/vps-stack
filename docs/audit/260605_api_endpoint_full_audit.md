# API Endpoint Full Audit — All Sources

**Date:** 2026-06-05  
**Purpose:** Map all available endpoints beyond basic fundamentals across Finnhub, yfinance, Alpha Vantage, and FMP. Document what is confirmed working, what is premium-blocked, and what can be built from each.  
**Companion file:** `260605_fundamentals_api_audit.md` (core fundamentals field mapping)

---

## Rate Limit Summary

| Source | Free Limit | Confirmed Working From VPS |
|---|---|---|
| Finnhub | 60 calls/min, no daily cap | Yes — all free endpoints |
| yfinance | Unofficial; ~100–200 calls/day safe | Yes — with sleep(2) between tickers |
| Alpha Vantage | 25 calls/day per key × 2 keys = 50/day | Yes — burns fast, plan calls carefully |
| FMP | 250 calls/day | Yes — US stocks free, HK mostly premium |

---

## FINNHUB — Live Test Results

**Key:** `d3kq4thr01qp3ucp76vg...` (in keys.md)  
**Base URL:** `https://finnhub.io/api/v1/`

### News

**Company news** — `/company-news` ✅ Free
```
symbol=NVDA, from=2026-05-29, to=2026-06-05
→ 250 articles returned
Sources: Yahoo Finance, Seeking Alpha, Reuters, Benzinga
Fields: headline, summary, url, source, datetime (unix), image, category
```
Confirmed working. No HK ticker tested but likely thin — news is global text search, not HKEX-specific.

**Market news** — `/news?category=general` ✅ Free
```
→ 100 articles returned
Sources: Reuters, CNBC, MarketWatch
Categories available: general, forex, crypto, merger
Good for morning digest macro context.
```

**News sentiment** — `/news-sentiment` ❌ Free tier returns nulls
```
symbol=NVDA → all sentiment fields null
buzz.articlesMentionedInLastWeek: None
companyNewsScore: None
sentiment.bullishPercent: None
→ Endpoint exists but data not available at free tier
```

---

### Earnings Data

**Earnings calendar** — `/calendar/earnings` ✅ Free
```
from=2026-06-05, to=2026-06-12
→ 114 events returned
Fields: symbol, date, epsEstimate, epsActual, revenueEstimate, revenueActual, quarter
Note: estimates often None for small caps; large caps well-covered
```

**Earnings history / surprises** — `/stock/earnings` ✅ Free (US)
```
symbol=AAPL → 4 quarters shown:
  2026-03-31  actual=2.01  est=1.99  surprise=+0.02  surprisePct=+1.09%
  2025-12-31  actual=2.84  est=2.73  surprise=+0.11  surprisePct=+4.19%
  2025-09-30  actual=1.85  est=1.81  surprise=+0.04  surprisePct=+2.35%
  2025-06-30  actual=1.57  est=1.46  surprise=+0.11  surprisePct=+7.34%
Excellent for tracking beat/miss history.
```

**Financial statements (standardized)** — `/stock/financials` ❌ Premium
```
→ "You don't have access to this resource."
```

**Financials as reported (XBRL)** — `/financials-reported` ❌ Rate/access issue
```
→ JSON decode error (empty response) — likely premium or rate limited
```

---

### Analyst Data

**Analyst recommendations** — `/stock/recommendation` ✅ Free (US)
```
symbol=NVDA:
  2026-06-01: buy=39  hold=4  sell=1  strongBuy=24  strongSell=0
  2026-05-01: buy=42  hold=4  sell=1  strongBuy=24  strongSell=0
  2026-04-01: buy=42  hold=4  sell=1  strongBuy=24  strongSell=0
Monthly counts going back ~12 months. Very useful for consensus trend.
```

**Price target** — `/stock/price-target` ❌ Premium
```
→ "You don't have access to this resource."
```

**Upgrade/downgrade feed** — `/stock/upgrade-downgrade` — not tested; likely premium based on pattern.

---

### Insider Transactions

**Insider transactions** — `/stock/insider-transactions` ✅ Free (US)
```
symbol=NVDA → 735 transactions returned
Fields: name, transactionDate, transactionCode, share, transactionPrice, filingDate
Codes: S=Sale, G=Gift, P=Purchase, etc.
Sample:
  2026-06-04  STEVENS MARK A  S  shares=6,399,771  price=$220.37
  2026-06-04  STEVENS MARK A  G  shares=6,092,271  price=$0
HK coverage: No — SEC Form 3/4/5 based, US only
```

---

### SEC Filings

**SEC filings** — `/stock/filings` ✅ Free (US)
```
symbol=AAPL, limit=5:
  2026-05-29  Form 4     (insider ownership change)
  2026-05-28  Form SD    (specialized disclosure)
  2026-05-27  Form 144   (proposed sale of restricted securities)
  2026-05-12  Form 4
  2026-05-08  Form 4
Fields: filedDate, form, description, accessNumber, url (direct SEC link)
Key forms: 4 (insider), 10-K (annual), 10-Q (quarterly), 8-K (material event)
HK: N/A — SEC filings only
```

---

### Economic & Market Calendar

**Economic calendar** — `/calendar/economic` ✅ Free
```
from=2026-06-05, to=2026-06-12 → 589 events
Global coverage (US, EU, UK, CN, PH, IN, etc.)
Fields: time, country, event, impact (low/medium/high), estimate, actual, prev
Sample:
  2026-06-05  PH  Inflation Rate MoM  low   est=0.2   prev=2.6
  High-impact events (Fed, CPI, NFP) included
Best free global macro event calendar across all four sources.
```

**IPO calendar** — `/calendar/ipo` — not fully tested; confirmed endpoint exists, free.

---

### Forex & Commodities

**Forex rates** — `/forex/rates` ❌ Premium
```
→ "You don't have access to this resource."
Use yfinance "USDHKD=X" ticker instead (already in P1 script).
```

---

### Finnhub Summary Table

| Endpoint | Category | Free? | HK? | Confirmed |
|---|---|---|---|---|
| `/company-news` | News | ✅ | Partial | ✅ 250 items |
| `/news` | Market news | ✅ | N/A | ✅ 100 items |
| `/news-sentiment` | Sentiment | ❌ nulls | No | ❌ |
| `/calendar/earnings` | Earnings cal | ✅ | Partial | ✅ 114 events |
| `/stock/earnings` | EPS surprise | ✅ US | No | ✅ 4 qtrs AAPL |
| `/stock/recommendation` | Analyst rec | ✅ US | No | ✅ monthly counts |
| `/stock/price-target` | Price target | ❌ | No | ❌ |
| `/stock/insider-transactions` | Insiders | ✅ US | No | ✅ 735 items |
| `/stock/filings` | SEC filings | ✅ US | N/A | ✅ |
| `/stock/financials` | Fin statements | ❌ | No | ❌ |
| `/calendar/economic` | Macro cal | ✅ | N/A | ✅ 589 events |
| `/forex/rates` | FX | ❌ | N/A | ❌ |

---

## YFINANCE — Live Test Results

**Library:** yfinance 1.4.1 (installed on VPS)

### News

**`.news`** — HK tickers ❌, US tickers untested from VPS
```
9988.HK → returns list of items but all fields null (title=None, publisher=None, url=None)
Not usable for HK stocks. May work for US — not tested.
```

---

### Earnings & Calendar

**`.calendar`** ✅ Works for HK
```
9988.HK result:
  Ex-Dividend Date: 2026-06-10
  Earnings Date: [2026-05-13]
  Earnings High: 2.09 (EPS estimate high)
  Earnings Low: 0.86  (EPS estimate low)
  Earnings Average: 1.42 (consensus EPS)
  Revenue High: 276,089,000,000 (HKD)
  Revenue Low: 258,727,400,000
  Revenue Average: 268,333,270,760
Useful for upcoming earnings context.
```

**`.earnings_dates`** ❌ VPS missing lxml package
```
→ "Import lxml failed" — fixable: pip install lxml
```

---

### Financial Statements

**`.income_stmt`** ✅ Works for HK (9988.HK)
```
Shape: 55 rows × 4 columns (4 annual periods)
Dates: 2026-03-31, 2025-03-31, 2024-03-31, 2023-03-31 (fiscal year end)
Key items: Total Revenue, Net Income, Gross Profit, EBIT, EBITDA, R&D, etc.

9988.HK (most recent FY):
  Total Revenue:  HK$1,023,670,000,000 (~$131B USD)
  Net Income:     HK$103,592,000,000  (~$13.3B USD)

55 line items available — very complete.
```

**`.balance_sheet`** ✅ Works (tested on NVDA)
```
Shape: 80 rows × 5 columns
Line items include: Total Debt, Net Debt, Working Capital, Common Stock Equity,
Tangible Book Value, Invested Capital, Cash & Equivalents, etc.
```

**`.cashflow`** ✅ Works (tested on NVDA)
```
Shape: 56 rows × 5 columns
Key items: Free Cash Flow, Operating Cash Flow, Capex, Debt Repayment, etc.
NVDA Free Cash Flow (latest annual): $96,676,000,000
```

**`.quarterly_income_stmt`, `.quarterly_balance_sheet`, `.quarterly_cashflow`** — not tested but confirmed available; same structure as annual.

---

### Analyst Data

**`.recommendations`** ✅ Works
```
NVDA (monthly aggregated):
  0m:  strongBuy=10  buy=48  hold=2  sell=1  strongSell=0
  -1m: strongBuy=10  buy=48  hold=2  sell=1  strongSell=0
  -2m: strongBuy=10  buy=48  hold=2  sell=1  strongSell=0
DataFrame with period index going back ~12 months.
Note: Uses different scale (strongBuy vs Finnhub) — both useful.
```

---

### yfinance Summary Table

| Property | Category | Free? | HK? | Confirmed |
|---|---|---|---|---|
| `.history()` | Price OHLCV | ✅ | ✅ | ✅ (already in P1) |
| `.info` | Fundamentals | ✅ | ✅ | ✅ (F0 audit) |
| `.calendar` | Earnings dates + estimates | ✅ | ✅ | ✅ ex-div + EPS range |
| `.income_stmt` | Annual income statement | ✅ | ✅ | ✅ 55 items, 4 years |
| `.balance_sheet` | Annual balance sheet | ✅ | ✅ | ✅ 80 items |
| `.cashflow` | Annual cash flow | ✅ | ✅ | ✅ 56 items |
| `.quarterly_income_stmt` | Quarterly P&L | ✅ | ✅ | not tested |
| `.recommendations` | Analyst consensus | ✅ | Partial | ✅ monthly counts |
| `.earnings_dates` | Earnings history | ✅ | Partial | ❌ needs lxml |
| `.news` | News articles | ✅ | ❌ nulls | ❌ HK broken |
| `.dividends` | Dividend history | ✅ | ✅ | ✅ (used in P1) |

**Fix needed:** `pip install lxml` on VPS to enable `.earnings_dates`.

---

## ALPHA VANTAGE — Live Test Results

**Keys:** Key 1 (`T24B2GLPZGY58F90`) and Key 2 (`7C26C98TG8440OBB`) — 25 calls/day each  
**Warning:** Both keys hit their daily limit during testing. Spread calls across time in production — 1 call per second, no more than ~20 calls per key per day to leave buffer.

### News & Sentiment

**`NEWS_SENTIMENT`** ✅ Free — best-in-class for structured news
```
Tested: tickers=NVDA, limit=50

Sample article:
  Source: Japan Wire by Kyodo News
  Title: "Jensen Huang's South Korea visit signals Nvidia's broader bet on Asia"
  overall_sentiment_label: Bullish
  overall_sentiment_score: 0.4416

  NVDA-specific:
    relevance_score: 1.000 (highly relevant)
    ticker_sentiment_label: Bullish
    ticker_sentiment_score: 0.4072

Parameters:
  tickers=   comma-separated ticker list (e.g. NVDA,META,9988.HK)
  topics=    energy_transportation, financial_markets, economy_macro,
             technology, real_estate, manufacturing, life_sciences
  time_from= YYYYMMDDTHHMM
  time_to=   YYYYMMDDTHHMM
  limit=     up to 1000 (default 50)
  sort=      LATEST, EARLIEST, RELEVANCE

Returns per article: title, url, source, authors, summary, banner_image,
  time_published, topics[], overall_sentiment, ticker_sentiment[]

Ticker sentiment fields per article:
  ticker, relevance_score (0-1), ticker_sentiment_score (-1 to +1),
  ticker_sentiment_label (Bearish/Somewhat-Bearish/Neutral/
                          Somewhat-Bullish/Bullish)

HK coverage: Global news — HK tickers may appear if news sources mention them.
  Not as reliable as US tickers but worth testing.

BEST USE: Feeds into F4 Idea Generator (signal scoring) and
  F2 signal collection (newsletter signals alternative).
```

---

### Financial Statements

**`INCOME_STATEMENT`** ✅ Free (Key 2 tested, Key 1 rate-limited)
```
symbol=NVDA, quarterly:
  Quarter: 2026-04-30 (most recent)
  totalRevenue:          $81,615,000,000
  grossProfit:           $61,157,000,000
  operatingIncome:       $53,536,000,000
  netIncome:             $58,321,000,000
  ebitda:                $70,796,000,000
  researchAndDevelopment: $6,321,000,000

Annual periods available: 2026-01-31, 2025-01-31, 2024-01-31, 2023-01-31

Returns: annualReports[] + quarterlyReports[]
  Each report: fiscalDateEnding, reportedCurrency, all P&L line items
HK coverage: Thin — US-focused GAAP mapping.
```

**`BALANCE_SHEET`** and **`CASH_FLOW`** — same structure, not re-tested (rate limited). Known working from documentation.

**`EARNINGS`** — rate limited during testing, confirmed working from docs
```
Returns quarterlyEarnings[] with:
  fiscalDateEnding, reportedDate, reportedEPS, estimatedEPS,
  surprise, surprisePercentage
Best free source for EPS beat/miss history alongside Finnhub.
```

---

### Commodities (confirmed free, rate-limited during test session)

Based on documentation and prior successful calls:

| Function | Data | Intervals |
|---|---|---|
| `WTI` | WTI crude oil price (Henry Hub region) | daily / weekly / monthly |
| `BRENT` | Brent crude (North Sea) | daily / weekly / monthly |
| `NATURAL_GAS` | Henry Hub natural gas spot price | daily / weekly / monthly |
| `COPPER` | LME copper | daily / weekly / monthly |
| `ALUMINUM` | LME aluminum | daily / weekly / monthly |

**Direct portfolio relevance:** WTI, Brent, and Natural Gas — free, no auth beyond API key.

**Note from first test session** (before rate limit hit):
```
WTI   2026-05: $61.59/bbl
Brent 2026-05: $64.83/bbl
NG    2026-05: $3.37/MMBtu
```

---

### Economic Indicators (confirmed free, rate-limited during test)

| Function | Data | Frequency |
|---|---|---|
| `TREASURY_YIELD` | 2Y, 5Y, 10Y, 30Y US Treasury yields | daily / weekly / monthly |
| `FEDERAL_FUNDS_RATE` | Fed funds effective rate | daily / weekly / monthly |
| `CPI` | US Consumer Price Index | monthly / semiannual |
| `INFLATION` | Annual US inflation rate | annual |
| `REAL_GDP` | US real GDP | quarterly / annual |
| `UNEMPLOYMENT_RATE` | US monthly unemployment | monthly |
| `NONFARM_PAYROLL` | US monthly NFP | monthly |

These consume API calls but are static data — fetch once weekly and cache.

---

### Alpha Vantage Summary Table

| Function | Category | Free? | HK? | Confirmed |
|---|---|---|---|---|
| `NEWS_SENTIMENT` | Scored news | ✅ | Partial | ✅ ticker+topic filter, scores |
| `INCOME_STATEMENT` | Financial stmt | ✅ | Thin | ✅ quarterly + annual |
| `BALANCE_SHEET` | Financial stmt | ✅ | Thin | Docs confirmed |
| `CASH_FLOW` | Financial stmt | ✅ | Thin | Docs confirmed |
| `EARNINGS` | EPS actual/est | ✅ | No | Docs confirmed |
| `EARNINGS_CALENDAR` | Upcoming earnings | ✅ (CSV) | No | ⚠️ returns CSV not JSON |
| `WTI` / `BRENT` / `NATURAL_GAS` | Commodities | ✅ | N/A | ✅ prior session |
| `TREASURY_YIELD` | Macro | ✅ | N/A | Docs confirmed |
| `FEDERAL_FUNDS_RATE` | Macro | ✅ | N/A | Docs confirmed |
| `CPI` / `REAL_GDP` / `NFP` | Macro | ✅ | N/A | Docs confirmed |
| `COMPANY_OVERVIEW` | Fundamentals | ❌ Premium | No | ❌ |
| All FX functions | Forex | ❌ Premium | N/A | ❌ |

**`EARNINGS_CALENDAR` note:** Returns CSV text, not JSON. Must use `response.text` and parse with csv module or pandas — `response.json()` will fail.

---

## FMP — Live Test Results

**Key:** `NAASoLZShKZVUvnb7tNNFAzPJlmLFeFg`  
**Base URL:** `https://financialmodelingprep.com/stable/`  
**Note:** v3 API is dead for this key post-Aug 2025. All tests use `/stable/` endpoints.

### Financial Statements

**`/stable/income-statement` (NVDA, US)** ✅ Free
```
NVDA FY2026 (ended 2026-01-25):
  revenue:         $215,938,000,000
  grossProfit:     $153,463,000,000
  operatingIncome: $130,387,000,000
  netIncome:       $120,067,000,000
  ebitda:          $144,552,000,000
  eps:             $4.93
  epsDiluted:      $4.90
Fields: all standard P&L items + period, reportedCurrency, link (SEC filing URL)
```

**`/stable/cash-flow-statement` (NVDA, US)** ✅ Free
```
  operatingCashFlow: $102,718,000,000
  capitalExpenditure: -$6,042,000,000
  freeCashFlow:       $96,676,000,000
  dividendsPaid: None (NVDA pays minimal dividend)
```

**`/stable/income-statement` (9988.HK)** ❌ Premium
```
→ "Special Endpoint: This value set for 'symbol' is not available under
   your current subscription"
Financial statements for non-US tickers require a paid plan.
```

**`/stable/balance-sheet-statement` (9988.HK)** ❌ Premium — same block.

---

### Earnings Calendar

**`/stable/earnings-calendar`** ✅ Free
```
from=2026-06-05, to=2026-06-19:
  2026-06-11  ADBE  epsEstimated=5.83  revenueEstimated=$6,456,970,000
Fields: symbol, date, epsActual, epsEstimated, revenueActual, revenueEstimated, lastUpdated
Coverage: US stocks, major names well-represented
Note: This is the only FMP earnings endpoint confirmed free — surprises and transcripts are premium.
```

---

### News

**`/stable/stock_news_symbol/9988.HK`** ❌ Returns empty array `[]`
News for HK tickers not available at free tier.

**`/stable/stock_news_symbol/NVDA`** — not directly tested but expected to work based on US free tier.

---

### Economic & Market Data

**`/stable/economic_calendar`** ❌ Returns empty array `[]`  
Tested with `from=2026-06-05&to=2026-07-05`. May require different path or premium.  
Use Finnhub `/calendar/economic` instead — confirmed free with 589 events.

**`/stable/economic_indicators`** — not tested; may work.

**`/stable/treasury_rates`** — not tested; likely free per docs.

---

### Insider Trades

**`/stable/insider_trades?symbol=NVDA`** ❌ Returns empty array `[]`  
Path may differ — not confirmed working. Finnhub `insider-transactions` is the reliable free alternative.

---

### FMP Summary Table

| Endpoint | Category | Free? | HK? | Confirmed |
|---|---|---|---|---|
| `/stable/income-statement` | Financial stmt | ✅ US | ❌ Premium | ✅ NVDA |
| `/stable/balance-sheet-statement` | Financial stmt | ✅ US | ❌ Premium | ✅ (assumed) |
| `/stable/cash-flow-statement` | Financial stmt | ✅ US | ❌ Premium | ✅ NVDA |
| `/stable/key-metrics-ttm` | Capital efficiency | ✅ US | ❌ Premium | ✅ AAPL (F0 audit) |
| `/stable/profile` | Company profile | ✅ US+HK | ✅ | ✅ 9988.HK (F0 audit) |
| `/stable/earnings-calendar` | Earnings cal | ✅ | Partial | ✅ ADBE upcoming |
| `/stable/stock_news_symbol` | News | ✅ US | ❌ empty | ❌ HK empty |
| `/stable/economic_calendar` | Macro cal | ❌ empty | N/A | ❌ (use Finnhub) |
| `/stable/insider_trades` | Insiders | ❌ empty | N/A | ❌ path issue |

---

## Cross-Source Confirmed Capability Map

### By Data Category

| Category | Best Free Source | Second Option | HK Coverage |
|---|---|---|---|
| Company news | Finnhub `/company-news` | FMP news (US) | Thin — global news only |
| Market news | Finnhub `/news` | — | N/A |
| **News with sentiment scores** | **Alpha Vantage `NEWS_SENTIMENT`** | — | Partial |
| Earnings calendar | Finnhub `/calendar/earnings` | FMP `/stable/earnings-calendar` | Partial |
| EPS surprise history | Finnhub `/stock/earnings` | AV `EARNINGS` | No |
| Analyst recommendations | Finnhub `/stock/recommendation` | yfinance `.recommendations` | No |
| Insider transactions | Finnhub `/stock/insider-transactions` | — | No (SEC-only) |
| SEC filings feed | Finnhub `/stock/filings` | — | N/A |
| **Global macro calendar** | **Finnhub `/calendar/economic`** | — | N/A |
| US financial statements | AV (quarterly+annual) | FMP `/stable/income-statement` | Thin |
| **HK financial statements** | **yfinance `.income_stmt`** | — | ✅ |
| HK earnings/EPS estimates | yfinance `.calendar` | — | ✅ |
| **Commodity prices** | **AV `WTI`/`BRENT`/`NATURAL_GAS`** | — | N/A |
| **Macro rates** | **AV `TREASURY_YIELD`/`FEDERAL_FUNDS_RATE`** | Finnhub (US Treasuries via ETF) | N/A |
| FX rates | yfinance `USDHKD=X` (already in P1) | — | USD/HKD ✅ |

---

## What We Can Build

### Near-term — extend existing workflows

**1. Earnings preview header in Portfolio Email (P2)**  
Source: Finnhub `/calendar/earnings` or FMP `/stable/earnings-calendar`  
Add a line at the top of the P2 email: "Upcoming earnings: BABA 2026-08-12, NVDA 2026-08-20"  
Cost: 1 Finnhub call/day. Zero incremental budget.

**2. Macro snapshot line in Portfolio Email (P2)**  
Source: AV `WTI`, `BRENT`, `NATURAL_GAS`, `TREASURY_YIELD` (4 AV calls/week)  
Add to email header: "10Y UST: 4.52% | WTI: $71.4 | Brent: $75.1 | NG: $2.8 | USDHKD: 7.83"  
Directly relevant to infrastructure/energy portfolio.

**3. Economic calendar in Morning Digest (1.1)**  
Source: Finnhub `/calendar/economic` (free, 589 events/week)  
Add a "High-impact macro events this week" section filtered by `impact=high`  
Shows Fed decisions, CPI releases, NFP, PBOC/BOJ meetings — no API budget cost.

---

### New workflows

**4. Earnings Surprise Tracker (new script)**  
Source: Finnhub `/stock/earnings` for US portfolio tickers  
Run after each earnings — email alert: "AAPL beat by 7.3% | NVDA missed by 2.1%"  
Trigger: post-earnings (schedule near known dates from earnings calendar)

**5. Insider Trading Alert (new script)**  
Source: Finnhub `/stock/insider-transactions`  
For each portfolio US ticker, check for purchase transactions in last 7 days  
Email alert only when insiders buy (purchases are bullish signal; sales routine)  
Run weekly, 20 Finnhub calls — negligible budget.

**6. SEC 8-K Alert (new script)**  
Source: Finnhub `/stock/filings`  
Filter for form=8-K (material events) for portfolio tickers  
Email alert within hours of filing — catches earnings releases, M&A, management changes  
Run hourly Mon–Fri, ~20 calls/run.

**7. News Sentiment Feed (feeds F4 Idea Generator)**  
Source: AV `NEWS_SENTIMENT`  
Daily call with portfolio tickers grouped (max 50/call) + energy_transportation topic  
Store scored articles in PostgreSQL `news_sentiment` table  
Provides richer signal for F4 than raw headline extraction  
Budget: 2–3 AV calls/day (1 for tickers, 1–2 for topics)

**8. Financial Statement Quarterly Pull (feeds F3 Portfolio Review)**  
Source: yfinance `.income_stmt` + `.balance_sheet` + `.cashflow` for all 33 tickers  
Run quarterly (post-earnings season), store in PostgreSQL `financial_statements` table  
Enables P/E vs earnings growth, FCF yield, debt trend analysis in F3  
Budget: 33 yfinance calls with sleep(2) = ~2 minutes, no API cost

**9. Commodity Price Monitor (standalone or append to P2)**  
Source: AV `WTI`, `BRENT`, `NATURAL_GAS` (3 AV calls/week)  
Weekly or daily price with WoW % change  
Alert if WTI moves >5% WoW or NG moves >10% WoW (relevant to energy holdings EQNR, energy sector exposure)

---

## Data Gaps — No Free Source Available

| Data Type | Why It Matters | Workaround |
|---|---|---|
| HK financial statements (structured) | Quarterly results for Tencent, Alibaba | yfinance `.income_stmt` covers this |
| HK insider transactions | HKEX director dealings | HKEX Disclosure of Interests website (scrapable) |
| HK earnings calendar (reliable) | Upcoming results dates | yfinance `.calendar` partially covers; HKEX website for full list |
| LNG spot prices (JKM, TTF) | Core to infrastructure/energy thesis | S&P Global Platts (paid); trade press |
| Bond/credit spreads (Asia IG) | Relevant for infra finance context | Bloomberg Terminal only |
| Real-time quotes (HK) | Intraday for HK tickers | yfinance `.history(interval="1m")` covers last 7 days |
| Analyst price targets (HK) | Consensus targets for HK names | yfinance `.info` `targetMeanPrice` covers this |

---

## Immediate Actions

- [ ] `pip install lxml` on VPS to enable `yfinance.earnings_dates`
- [ ] Test AV `EARNINGS_CALENDAR` correctly (parse as CSV, not JSON)
- [ ] Test FMP `/stable/stock_news_symbol/NVDA` to confirm US news works
- [ ] Decide priority order for new workflows above (items 4–9) before building F1
