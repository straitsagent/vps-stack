# 

**Type:** stock | **Depth:** standard | **Date:** 2026-06-13 | **Ticker:** AMD | **Sources:** 74 | **Queries:** 5

### Cost Breakdown
| API | Usage | Est. Cost |
|---|---|---|
| Deepseek (query decomp) | 55 in + 59 out | $0.0001 |
| Perplexity Search API | 1 call(s), 5 queries | $0.0100 |
| Serper news | 6 results (1 call, $0.0003) | $0.0003 |
| Tavily finance search | 10 results (free tier, time_range=month) | $0.0000 |
| Brave Search | 10 results (free tier, freshness=pm) | $0.0000 |
| FRED macro data | 0 series (free) | $0.0000 |
| Exa neural search | 0 queries | $0.0000 |
| Grok-4.3 synthesis (reasoning_effort=medium) | 20827 in + 1267 out | $0.0292 |
| **Total** | 22208 tokens | **$0.0396** |

### Source Retrieval Quality
| Source | Count | Content Level |
|---|---|---|
| edgar_10k | 1 | 1 full text, 0 snippet |
| edgar_10q | 1 | 1 full text, 0 snippet |
| edgar_8k | 3 | 3 full text, 0 snippet |
| finnhub | 10 | 8 full text, 2 snippet |
| seeking_alpha | 2 | 2 snippet only |
| yfinance | 5 | 4 full text, 1 snippet |
| google_news | 21 | 21 snippet only |
| perplexity | 5 | 5 snippet only |
| tavily | 10 | 4 full text, 6 snippet |
| brave | 10 | 6 full text, 4 snippet |
| serper | 6 | 3 full text, 3 snippet |

⚠️ **Partial full-text retrieval.** 30/74 sources retrieved as full article text; remainder are headlines/snippets.

**Financial statements:** yfinance quarterly income statement, balance sheet, and cash flow included in synthesis context.
**Tavily:** time_range=month enforced — exact publish dates unavailable but all results within 30 days.

---

**Business Overview**

Advanced Micro Devices (AMD) designs and sells high-performance semiconductors across three segments: Data Center, Client and Gaming, and Embedded. The company supplies AI accelerators, CPUs (EPYC and Ryzen), GPUs (Instinct and Radeon), FPGAs, and adaptive SoCs for cloud, edge, and endpoint applications. Its strategy centers on full-stack AI solutions, leveraging chiplet architectures, Infinity Fabric, and an open software stack to serve hyperscalers, OEMs, and enterprises. Data Center has become the primary growth engine, driven by 5th Gen EPYC processors and Instinct MI350/MI450 GPUs. [1][2]

In Q1 2026, Data Center revenue reached $5.78 billion (+57% YoY), fueled by EPYC server CPUs (46.2% server market share) and Instinct GPUs. Client and Gaming benefited from Ryzen AI PC demand, while Embedded saw end-market recovery. AMD’s 2025 full-year revenue hit $34.64 billion, up 34% YoY, reflecting AI infrastructure buildout. A landmark February 2026 agreement with Meta commits the hyperscaler to deploy up to 6 gigawatts of AMD GPUs, including custom MI450-based accelerators and 6th Gen EPYC CPUs, supported by a performance-based warrant for up to 160 million shares. [2][5]

AMD maintains a broad IP portfolio spanning custom SoCs, DPUs, and rack-scale platforms such as Helios. The company employs 31,000 people and generates revenue through direct sales, semi-custom designs (e.g., gaming consoles), and IP licensing. Its roadmap targets annual GPU cadence and expanded AI software enablement to capture both training and inference workloads. [1]

**Financial Position**

AMD’s financials show accelerating top-line growth and margin expansion. Revenue rose from $22.68 billion in 2023 to $25.79 billion in 2024 and $34.64 billion in 2025. Q1 2026 revenue reached $10.3 billion (+38% YoY), with gross margin expanding to 53% (from 50%) due to favorable Data Center mix. Operating income nearly doubled to $1.5 billion, and net income rose to $1.4 billion. Operating cash flow surged to $3.0 billion in the quarter, supporting $221 million in share repurchases. [2]

Balance sheet strength is evident: total debt of $3.85 billion at end-2025 yields low leverage (Debt/Equity 0.1; Net Debt/EBITDA –0.23). Cash and short-term investments stood at $12.3 billion as of March 2026. ROE improved to 7% (DuPont) from 2% in 2023, though trailing metrics remain modest at 0.1%. Free cash flow reached $6.74 billion for 2025. [Financials table]

Valuation remains elevated: trailing P/E 169.4x, forward P/E 39.0x, P/S 22.3x, and EV/EBITDA 111.1x. Market cap is approximately $760.5 billion, with shares trading near $500 amid volatility (52-week range $117.78–$546.44). Analyst consensus target is $482–$486, though recent upgrades point higher. Short interest is low at 2.7%. [Valuation table]

**Competitive Position**

AMD holds a credible but secondary position in AI GPUs behind NVIDIA, while leading or closely challenging Intel in x86 server CPUs. EPYC processors have captured significant share from Intel in hyperscale deployments due to core density and efficiency advantages. In GPUs, Instinct MI350 series and upcoming MI450 provide a lower total-cost-of-ownership alternative for select workloads, evidenced by the Meta 6 GW commitment. [10][60]

Key competitors include NVIDIA (dominant in AI accelerators with $75+ billion quarterly Data Center revenue), Broadcom, Micron, Intel, and Texas Instruments. AMD’s chiplet design and open ecosystem offer differentiation versus NVIDIA’s proprietary stack, yet NVIDIA retains advantages in software (CUDA) and networking scale. AMD’s embedded and client businesses provide diversification that pure-play GPU peers lack. Market share data indicate AMD at roughly 8% of discrete PC GPUs but growing rapidly in servers. [66]

The company’s moat rests on x86 compatibility, advanced packaging IP, and deepening hyperscaler relationships. Recent analyst commentary highlights AMD’s emergence as a “legit second source” in GPUs, with potential to capture substantial Meta volume. [10][60]

**Catalysts**

Near-term upside drivers center on the Meta deployment ramp beginning 2H 2026, with each gigawatt estimated to generate ~$15 billion in revenue. MI450 and Helios rack-scale platforms are expected to accelerate AI GPU adoption. EPYC server momentum continues, with management citing customer forecasts exceeding initial expectations and a broader CPU TAM potentially reaching $137 billion by 2030. [2][60]

Q2 2026 guidance (revenue $11.10–11.64 billion) and the August 4 earnings release provide near-term catalysts. Citi’s June 2026 upgrade to Buy ($575 target) cited underappreciated GPU optionality and raised 2027–2028 AI revenue forecasts to $33–50.8 billion. Macro tailwinds from AI capex and potential rate relief could further support multiples. [10][13]

**Risks**

Execution risk on the MI450 ramp and Meta warrant vesting remains material, as does sustained NVIDIA dominance in software and networking. High valuation (forward P/E 39x) leaves limited margin for error if growth disappoints. Geopolitical exposure, including China export restrictions that previously reduced revenue by $1.5–1.8 billion, persists. [51]

Insider selling has been notable, with multiple officers and directors disposing of shares in 2026. Competitive threats from custom ASICs (Google, Amazon) and emerging players could pressure margins. Macro headwinds—higher-for-longer rates or AI capex digestion—pose downside to sentiment given the stock’s beta of 2.49. [72]

---

## Supporting Data

## Company Profile: AMD

**Sector:** Technology | **Industry:** Semiconductors | **Country:** United States | **Exchange:** NMS | **Employees:** 31,000 | **Website:** https://www.amd.com

Advanced Micro Devices, Inc. operates as a semiconductor company internationally. It operates in three segments: Data Center, Client and Gaming, and Embedded. The company offers artificial intelligence (AI) accelerators, microprocessors, and graphics processing units (GPUs) as standalone devices or as incorporated into accelerated processing units, chipsets, and data center and professional GPUs; ...

## Financials: AMD

### Income Statement (USD, last 3 FY)
| Metric | 2025-12-31 | 2024-12-31 | 2023-12-31 |
|---|---|---|---|
| Revenue | $34.64B | $25.79B | $22.68B |
| Gross Profit | $17.15B | $12.72B | $10.46B |
| Op. Income | $3.69B | $2.09B | $0.40B |
| EBITDA | $7.28B | $5.14B | $4.05B |
| Net Income | $4.33B | $1.64B | $0.85B |
| EPS | 2.67 | 1.01 | 0.53 |

### Balance Sheet
| Metric | 2025-12-31 | 2024-12-31 | 2023-12-31 |
|---|---|---|---|
| Total Assets | $76.93B | $69.23B | $67.89B |
| Total Liabilities | $13.93B | $11.66B | $11.99B |
| Equity | $63.00B | $57.57B | $55.89B |
| Total Debt | $3.85B | $2.21B | $3.00B |
| Cash | $5.54B | $3.79B | $3.93B |

### Cash Flow
| Metric | 2025-12-31 | 2024-12-31 | 2023-12-31 |
|---|---|---|---|
| Operating CF | $7.71B | $3.04B | $1.67B |
| Free CF | $6.74B | $2.40B | $1.12B |
| CapEx | $-0.97B | $-0.64B | $-0.55B |

### Financial Health
| Metric | 2025-12-31 | 2024-12-31 | 2023-12-31 |
|---|---|---|---|
| Net Debt | $-1.69B | $-1.57B | $-0.93B |
| Net Debt/EBITDA | -0.23 | -0.31 | -0.23 |
| Gearing | 0.06 | 0.04 | 0.05 |
| Current Ratio | 2.85 | 2.62 | 2.51 |
| Net Margin % | 0.13 | 0.06 | 0.04 |
| ROE (DuPont) | 0.07 | 0.03 | 0.02 |

## Valuation: AMD

| Metric | Value |
|---|---|
| Trailing P/E | 169.4x |
| Forward P/E | 39.0x |
| P/B | 12.9x |
| P/S (TTM) | 22.3x |
| EV/EBITDA | 111.1x |
| EV/Revenue | 22.0x |
| P/FCF | 116.3x |
| PEG Ratio | 1.23x |
| Beta | 2.49x |
| Trailing EPS | $3.02 |
| Forward EPS | $13.10 |
| 52-wk Range | $117.78 – $546.44 |
| Analyst Target | $486.33 (48 analysts) |
| Rec. Score | 1.5/5 |

**Short Interest:** 2.7% of float
 | **Days to Cover:** 1.1

## Ownership: AMD


### Top Institutional Holders
| Holder | Shares | % Held |
|---|---|---|
| Blackrock Inc. | 145,574,284
| Vanguard Capital Management LLC | 105,940,266
| State Street Corporation | 74,771,220
| Geode Capital Management, LLC | 39,791,086
| Vanguard Portfolio Management LLC | 37,603,675
| Price (T.Rowe) Associates Inc | 28,846,470
| JPMORGAN CHASE & CO | 24,248,547
| Morgan Stanley | 23,781,608
| UBS AM, a distinct business unit of UBS ASSET MANAGEMENT AMERICAS LLC | 19,192,764
| Northern Trust Corporation | 16,427,217

## Insider Transactions: AMD

| Name | Title | Date | Type | Shares | Value |
|---|---|---|---|---|---|
| DENZEL NORA M | Director | 2026-06-02 | N/A | 10,447
| NORROD FORREST EUGENE | Officer | 2026-05-20 | N/A | 8,237
| NORROD FORREST EUGENE | Officer | 2026-05-20 | N/A | 19,487
| VANDERSLICE ELIZABETH W | Director | 2026-05-14 | N/A | 2,613
| HOUSEHOLDER JOSEPH A | Director | 2026-05-14 | N/A | 2,613
| DENZEL NORA M | Director | 2026-05-14 | N/A | 2,613
| SU LISA T | Chief Executive Officer | 2026-05-13 | N/A | 125,000
| PAPERMASTER MARK D | Chief Technology Officer | 2026-05-11 | N/A | 2,350
| GRASBY PAUL DARREN | Officer | 2026-05-08 | N/A | 24,376
| PAPERMASTER MARK D | Chief Technology Officer | 2026-04-24 | N/A | 31,320

## Earnings Calendar: AMD

**Next Earnings:** 2026-08-04
 | Revenue Guide: $11.10B–$11.64B

## MD&A Synopsis (10-Q (2026-05-06))

Based solely on the provided MD&A section for the three months ended March 28, 2026:

**Revenue Drivers:** Net revenue surged 38% year-over-year to $10.3 billion. Growth was driven by strong demand across all segments, led by the Data Center segment (5th Gen AMD EPYC processors and Instinct MI350 Series GPUs). Client and Gaming segments benefited from strong AMD Ryzen processor demand, while the Embedded segment saw increased end-market demand.

**Margin Trends:** Gross margin improved to 53%, up 3% from 50% in the prior year, driven by a favorable product mix from higher Data Center segment revenue. Operating income nearly doubled to $1.5 billion (from $806 million), fueled by higher gross profit, though partially offset by higher operating expenses. Net income rose to $1.4 billion (from $709 million).

**Forward Guidance:** The company highlighted a significant strategic agreement with Meta Platforms, where Meta committed to deploying up to 6 gigawatts of AMD GPUs. This includes custom Instinct MI450-based GPUs and 6th Gen EPYC CPUs. AMD issued Meta a warrant to purchase up to 160 million shares, vesting upon GPU purchase milestones and stock price targets. The company generated $3.0 billion in operating cash flow and returned $221 million to shareholders via stock repurchases.

## Key Management: AMD

| Name | Title | Age | Total Pay |
|---|---|---|---|
| Dr. Lisa T. Su Ph.D. | Chair, President & CEO | 55 | $4,540,876 |
| Mr. Forrest E. Norrod | Executive VP & GM of the Data Center Solutions Business Group | 60 | $1,939,077 |
| Mr. Hasmukh  Ranjan | Senior VP & Chief Information Officer | N/A | N/A |
| Mr. Keivan  Keshvari | Senior Vice President of Global Operations & Quality | N/A | N/A |
| Mr. Mark D. Papermaster | CTO and Executive VP of Technology & Engineering | 63 | $2,165,455 |
| Mr. Matthew D. Ramsay | Vice President of Financial Strategy & Investor Relations | N/A | N/A |
| Mr. Paul Darren Grasby | Executive VP, Chief Sales Officer & President AMD EMEA | 55 | $2,180,902 |
| Ms. Emily  Ellis | Corporate VP, Chief Accounting Officer & Principal Accounting Officer | 42 | N/A |
| Ms. Jean X. Hu Ph.D. | Executive VP, CFO & Treasurer | 62 | $1,976,642 |
| Ms. Ruth  Cotter | Senior VP & Chief Administrative Officer | N/A | N/A |

## Board of Directors: AMD (DEF 14A, 2026-03-27)

| Name | Role | Independence |
|---|---|---|
| QUESTIONS AND ANSWERS |  |  |
| CAUTIONARY STATEMENT REGARDING FORWARD-LOOKING STATEMENTS |  |  |
| ITEM 1—ELECTION OF DIRECTORS |  |  |
| Director Experience, Skills and Qualifications |  |  |
| Director Nominees |  |  |
| Board Demographics |  |  |
| Former Directorships in Public Companies in the Last Five Years |  |  |
| Consideration of Stockholder Nominees for Director |  |  |
| Communications with the Board orNon-ManagementDirectors |  |  |
| Required Vote |  |  |
| Recommendation of the Board of Directors |  |  |
| CORPORATE GOVERNANCE |  |  |
| Independence of Directors |  |  |
| Compensation Committee Interlocks and Insider Participation |  |  |
| Board Leadership Structure |  |  |

## Peer Comparison: AMD

| Ticker | Name | Mkt Cap | Revenue TTM | EBITDA | P/E | P/B |
|---|---|---|---|---|---|---|
| NVDA | NVIDIA Corporation | $4969.9B | $253.5B | $165.5B | 31.4x | 25.4x |
| AVGO | Broadcom Inc. | $1817.7B | $75.5B | $42.1B | 63.7x | 20.7x |
| MU | Micron Technology, Inc. | $1107.0B | $58.1B | $36.8B | 46.3x | 15.3x |
| INTC | Intel Corporation | $626.1B | $53.8B | $14.2B | N/A | 5.6x |
| TXN | Texas Instruments Incorporated | $274.0B | $18.4B | $8.7B | 51.6x | 16.3x |

---

## References

[1] [ADVANCED MICRO DEVICES INC 10-K (2026-02-04)](https://www.sec.gov/Archives/edgar/data/2488/000000248826000018/amd-20251227.htm) — edgar_10k
[2] [ADVANCED MICRO DEVICES INC 10-Q (2026-05-06)](https://www.sec.gov/Archives/edgar/data/2488/000000248826000076/amd-20260328.htm) — edgar_10q
[3] [ADVANCED MICRO DEVICES INC 8-K (2026-05-15)](https://www.sec.gov/Archives/edgar/data/2488/000119312526226746/d118163d8k.htm) — edgar_8k
[4] [ADVANCED MICRO DEVICES INC 8-K (2026-05-05)](https://www.sec.gov/Archives/edgar/data/2488/000000248826000072/amd-20260505.htm) — edgar_8k
[5] [ADVANCED MICRO DEVICES INC 8-K (2026-02-24)](https://www.sec.gov/Archives/edgar/data/2488/000000248826000045/amd-20260223.htm) — edgar_8k
[6] [The Billionaire Move Nobody Saw Coming: Why Starboard Value Abandoned CRM For These 2 Stocks](https://finnhub.io/api/news?id=7fbbe0c7c05f48cbb17b16708115d78ec554430b6b219a2a81d7a0fb852335cf) — finnhub
[7] [Why Intel, AMD, Arm, and Other Artificial Intelligence (AI) Stocks Popped Today](https://finnhub.io/api/news?id=abb6d39c330ea4ba4f9d7360eece965e27c82ee9a03050db1fe4acc7fa19904b) — finnhub
[8] [The Unit Economics Of AI Infrastructure](https://finnhub.io/api/news?id=f8237074d58007743be855d7aa34870d4518d905ed5a5742d552fcf1385a3234) — finnhub
[9] [Why Qualcomm (QCOM) Stock Is Trading Up Today](https://finnhub.io/api/news?id=336f38687c22bda7559c2aabc98161fd2182eedae4f805bff461f6c9be9ac7e9) — finnhub
[10] [Why AMD (AMD) Stock Is Up Today](https://finnhub.io/api/news?id=7bfd1668171890f61799db395495421db805a7236fcc0d8f49ea2aece18922db) — finnhub
[11] [Stocks Rally on Hopes for a Near-term US-Iran Interim Peace Agreement](https://finnhub.io/api/news?id=cf0d5f5b32d21fe62497a93a0a445595738b16c51f978a418dbe236b93f819df) — finnhub
[12] [AMD Stock Ended Friday’s Session Nearly 5% Higher — What Triggered The Rally?](https://finnhub.io/api/news?id=35156aa0c5be2a327645714ebac19557b07506d0099ec22c8742c85efcbf00e5) — finnhub
[13] [Citi Just Upgraded AMD Stock. Here’s Why.](https://finnhub.io/api/news?id=68c1f3bd02e9ff7ee59e152d535f149ea450b5fdc3f4962a1cb98e634ecae3f0) — finnhub
[14] [Sector Update: Tech Stocks Rise Late Afternoon](https://finnhub.io/api/news?id=c153729350f83763ae60271f77cf5aaea0bcda0920d55eb8a1b26b572f01beab) — finnhub
[15] [Discover which S&P500 stocks are making waves on Friday.](https://finnhub.io/api/news?id=ab4801b856c9578b02ee9b031906c635e9d741654385abfdc79c3e06d0d90cbd) — finnhub
[16] [Notable analyst calls this week: Pfizer, AMD and Intel among top picks](https://seekingalpha.com/symbol/AMD/news?source=feed_symbol_AMD) — seeking_alpha
[17] [AMD: The Market Is Still Underpricing Its AI CPU Super Cycle](https://seekingalpha.com/article/4914422-amd-stock-market-is-still-underpricing-its-ai-cpu-super-cycle?source=feed_symbol_AMD) — seeking_alpha
[18] [The Billionaire Move Nobody Saw Coming: Why Starboard Value Abandoned CRM For These 2 Stocks](https://247wallst.com/investing/2026/06/13/the-billionaire-move-nobody-saw-coming-why-starboard-value-abandoned-crm-for-these-2-stocks/) — yfinance
[19] [Why Intel, AMD, Arm, and Other Artificial Intelligence (AI) Stocks Popped Today](https://www.fool.com/investing/2026/06/12/why-intel-amd-arm-ai-stocks-up-today/) — yfinance
[20] [Why Qualcomm (QCOM) Stock Is Trading Up Today](https://finance.yahoo.com/markets/stocks/articles/why-qualcomm-qcom-stock-trading-220520438.html) — yfinance
[21] [Why AMD (AMD) Stock Is Up Today](https://finance.yahoo.com/markets/stocks/articles/why-amd-amd-stock-today-215720676.html) — yfinance
[22] [Stocks Rally on Hopes for a Near-term US-Iran Interim Peace Agreement](https://www.barchart.com/story/news/2447851/stocks-rally-on-hopes-for-a-near-term-us-iran-interim-peace-agreement) — yfinance
[23] [AMD stock plummets despite Q4 earnings beat - Yahoo Finance](https://news.google.com/rss/articles/CBMikwFBVV95cUxOaW05Z05DRFBFUFNHdk56VXF0NTg5aE5NbG5oUGk4ZEo5WHNnZ19QdVo4eWYtTnVxbS1WYUdLNjAySXBHSXpUVWI4MURnTkxneDMzZDBPR2NhM01CcjJ5VzNrbDRzM0prQ082SDBESlhybmxMR1VXRUlHemxzTjhCTkpidVZTMkc0ZElKemczdm5NTzA?oc=5) — google_news
[24] [AMD (AMD) Earnings Report Q1 2026 | Beat, EPS & Revenue - 24/7 Wall St.](https://news.google.com/rss/articles/CBMiWEFVX3lxTFBjSThvR3I1SEg1eVo5aWtRUjJmMzJvVEl6V2ljVWZMMm1zYXd6YWZudnZ6UkYwY1hSelhwcGVONkFIME5IR1VnbC1Ra2dYMTVrMFlUeUpJYkU?oc=5) — google_news
[25] [Despite Solid Q4 Earnings, AMD Doesn’t Enthuse the Market - TradingView](https://news.google.com/rss/articles/CBMivwFBVV95cUxPUFZpb3pXMUFZajJZXzdYYm5HZ3dwMHRyclZaellvWGdKcWd0b0R2UmNTd2Q0YUY0LXFTNjU5aTMzV25DMllKbmpIM3hURks1VVFqYW5MQldPRnBTQXhTSnNNeUctTlpSRS1Ed3BSTjBGWW43LVpUc1Z1YU43b1JXU0N3bVIyWWlpeGZGMzFEcHdHa2xuc2tMS1JPdjhKVWFSeGFReUpJTURXX1ZvZXNMWVpBOWYwMThCbGFmbEpwYw?oc=5) — google_news
[26] [AMD Q4 2025 slides: record revenue and earnings as AI demand surges - Investing.com](https://news.google.com/rss/articles/CBMiwAFBVV95cUxPUmxYNWwwS0R5T1Yxakt2TC1xaHgtTXUyRkVVaDdSRkpDa0psUXRfVkNtdm5KVDhlOXk5ZlJmZlJlLTNMU3d0bU1QdUdpaUZaaURzbUZnLTB1bUNsYkVGNEJDRUdUT2pFUmhpVElnSzhhd05zLWF5Z3BYQ0NpMFdkeWpmQTVQcnE1N3NFOURLeWFlbHFDaGhOaTc4TUxoSkdpSkV2YjJGQkNkUlZQMzFfRXZTTXlxZE1aQXY3N3hwUko?oc=5) — google_news
[27] [AMD Stock Slips Despite 30% Earnings Growth and Stronger-Than-Expected Guidance - The Motley Fool](https://news.google.com/rss/articles/CBMif0FVX3lxTE9Zc2dvTVluZXpIME9KNkI1LVhSNTVNRHVEdDdmV1p3T3hQeVdWUF9taWduMFh2NWlxcVMwcVNaYzFwWkRPVTlMTG9lbFdrMU9MSmgwRXdJLUh4N0RjekM0d3M4b0dLUWFob3dPZGVWRWRTbDRlSFJudEE4ZE5tNm8?oc=5) — google_news
[28] [AMD, Nvidia, Arm, Intel: Inside the $120 Billion CPU Gold Rush - IO Fund](https://news.google.com/rss/articles/CBMidkFVX3lxTFBZa19ENndDakRzU2E3X3F3cFFsRDYzSEN4X3lGYTNzNW55YXNtWjZUaTFFSUZvbTU1Qms4ZEVFRjRRc1FWRF8zNi01QmxXMmNGYzZpem9NSFctcWx3WlFFNDhVekRYV1RxV1ZTM2x6bGhqeHdkR3c?oc=5) — google_news
[29] [AMD Finally Makes More Money On GPUs Than CPUs In A Quarter - The Next Platform](https://news.google.com/rss/articles/CBMitgFBVV95cUxNTkpCZVlvMU9HTlREbTNmMHVEcmtvd3RmNGhBVFRhVmJGVUgxWGc1VnNzS3hMUUVCNDFPRjAxYmRIT1ZqNXdTWW00UFVIaTczZEVrV2xFLXRJNDFNTWxtcEpiMV9mQndVREV4YTkzMm5iMjgwWlRKWGxYVWExTmJCdlpLUFdfSUZ5b0xhUmdnMFlKUzQ5Z2JjM1FCem5mYk5zYkNPYUpqaXp6dTRaRUtwSnh2UnVzUQ?oc=5) — google_news
[30] [AMD Q4 FY 2025: Record Data Center And Client Momentum - The Futurum Group](https://news.google.com/rss/articles/CBMikgFBVV95cUxPVi1NN3ZMazR0Qk9pOFBJc1R5VDZWSkFNLUxJczZVcVFIVDNwb2xUSi1CYlRfc1FEMjJtbC1RNEJoVVJxS2NLTmxEaUhnNjZXSlh3SHUydnJnUGw3Wm8zWWRvb0NnS3A4N2ZaVDQ3TGx4MUFIWUI1WTg1UDhoTUw4cmVNUnoxMlloU1Vkd1FHV3plUQ?oc=5) — google_news
[31] [AMD Sees ‘Very Clear Path’ To Double-Digit Share In Nvidia-Dominated Data Center AI Market - crn.com](https://news.google.com/rss/articles/CBMi0gFBVV95cUxNZ0hCdjNxYlVQcVRpZkhjTDgzUXA3TWVRWF9CM2JXb3VKd0Rsc1E1T0RkOWotR2hWS3BQQV8xU2VsNjBaUnQxdXItYnA3NDYtRjZ0aVNQQU94bHp0RGtKV0NFZmZKMnYzRHoyVjQ2RWZPS1BEcmFnU2NWc0VTb3ZxWERXQXlpSmlmRDhoUXhVVER4N2VfajFJamNMNHUxYTBQc1NWZDRfQnJTZU44NlRHREI4bUU5SVlpRVhGY1NCdlVLaUt5VUFJNF9jeWp6WkdFQXc?oc=5) — google_news
[32] [AMD stock soars after company says its data center revenue will jump 60% over the next 3 to 5 years - Yahoo Finance](https://news.google.com/rss/articles/CBMi3AFBVV95cUxQd055YmlCQnMxNmEya20tUmNHaTltQzZaWUFUTlhaQWNRZkgyLWpIX3QyM0QyalNLa0l1dVBSQ0xub3RfaVRlaVF3MlVKbDRBSF9oN2JPTGgwOE50U1UzaHlhUWFCU2RGcDIwbUdRb3A3LUxsNnoxTmpuc2JZY2NoUlozWDVOMVNfdmZkckd0Y2VINWpaa1MybGh5M3Bnb1ozSWZncXlXX2ZYaGlJR19UUy1LRkZ5WUxXcmk0WndLRVJ3SlFJNUVTTndhTE15bDZKQVVjeVNoVk56eUxN?oc=5) — google_news
[33] [Qualcomm announces AI chips to compete with AMD and Nvidia — stock soars 11% - CNBC](https://news.google.com/rss/articles/CBMigwFBVV95cUxNN2U3bkkwSEVJdXJxZ3IySWRZQlZKcHl4TklYS0tMQjhvSUlNd1pELXc2Q1BaQ1Jfc3ZRX1RYRExXUjUxaDhHNXdXLUtLaTdCS01KNENsU2hkWkJiQWhJUjV5YXFWWTdha1ZaVWRnN1hYUnZHcUNlZlpRNVZ1eEx4Z2phMNIBiAFBVV95cUxNbjBaOWpHSkpIYzAycW5lZGU0UjBzbTNyTDhsdnQ1ejVKRzFpcjYwQjJVc2pFNGpkUDhqM0VoVmZWMEotOC1Jb1kwWEMzd09nUHFJRzZWR3UtWWpUTkx6MEZ6SDRwZzBnZTUweEhSdjk5bmZidFhPWGJBLWVZN24xcmpaRGxZcWh6?oc=5) — google_news
[34] [Nvidia vs. Everybody Else: Competition Mounts Against the Top AI Chip Company - WSJ](https://news.google.com/rss/articles/CBMilgFBVV95cUxNVTFUMnYzc3JtUnhjS3o4aG13TEJ2YlZDTEVCWFFrQ0tsbFgxY0t5R3ZUbU1vT2kxaWR1MUppZzdHamUzcjlzbElHMDZ6R2pOZlE2ZFpYcENpeEsxb2EtWVoweXNjYUFneVB0dlpRRlNoTVpPWmJvdk5oSTVhd3JwSjFKRFdFM0tFbDZNODR0eTB6T1pka3c?oc=5) — google_news
[35] [Top 25+ AI Chip Makers: NVIDIA & Its Competitors - AIMultiple](https://news.google.com/rss/articles/CBMiTkFVX3lxTE9UYlQtNjVDT09maWxpR0pGbEU0MGxYaDdad1VzYnp6cXBTcjc4RlY0TXJ0SVVvb0NTU19DdkVCbFFOVjk1MUNmdUg4UjhEdw?oc=5) — google_news
[36] [Nvidia and other big chipmaker stocks are tanking as AI competition from Google heats up - Business Insider](https://news.google.com/rss/articles/CBMinAFBVV95cUxOTEYxWU55dk5RemN3MlBTc25tQ3lBbkxaLTZhTW01d2Q5RmF5aGZxQUdxeGpzRnZ6akVNcEp6NW1wZ3ZuX1c0N2ZWNjl2ZWx4YW44a19jb3QzNzJHZU9tb29FQWgtWm42dGZIdUlmN1RZTDQxZlk1WF9SRURTbEs2cEtjYzgxZ0c2S05vVmVYaElLLXZnS05HNi0xMGs?oc=5) — google_news
[37] [Nvidia vs AMD: Which AI Chipmaker Will Lead the Next Decade of Compute? - The Motley Fool](https://news.google.com/rss/articles/CBMiigFBVV95cUxPYVJjZzl5MVhPWXJWUUVfaWktdjB4ODVXMW9ldlg3ZUhIVUxDY0g1ZkYwcG5jY2JtZWgyMFg2bG95Sl8wbzd5MEQ3cVlYVkR5RFJkS0cyZTIxSURyQmNrQW1ZSU5QZjJsMGx2RFd4WDhXejhZNEt3Mkw1ZlJzTmFQbVNtNXdObUh6TUE?oc=5) — google_news
[38] [ARM Stock Quote Price and Forecast - CNN](https://news.google.com/rss/articles/CBMiT0FVX3lxTFBiM05XWHp1em9fQ3o1ZUlBbENhRUJqOERhbUxkNE1SSzJZVzE0ZDJuMUhMcXNTa0N0RHk5VXJFYlJSUXhZR1pLaVNhZ3E4bmc?oc=5) — google_news
[39] [AMD Price Prediction: Where Will The Stock be in 2027 - 24/7 Wall St.](https://news.google.com/rss/articles/CBMinAFBVV95cUxOUFQzVWwyejF2V1hUV2hEUWpXUzRvVkhxT1FacHNSSk5TdXNQazJVTEVmbTlRVXI4dWhZVERuRHA5Y2o5Wjg3TVBVck5EaVlWbEJKVDF3M1FLNHFyeWFYQzdVYjJhdkhDZTFSZnVZV3RRVjRrb3Vtc0duQXM2YUdnc2xDSG4zMDNHaDFScEtEOEM0R25jQ0RqVXdteXY?oc=5) — google_news
[40] [AMD Stock Forecast | Meta AI Deal - Capital.com](https://news.google.com/rss/articles/CBMie0FVX3lxTE1LRFg5ZE1GUW51blppWFBWLUFaRXRiemVhNTdBeDZ1QldraGZSMjVsSlIzR1NRUEZFdVc5dlR4UFNIN2FtcEpwZ3NTeGhBcEZsMm9nbWtVRUJRS1RmdjV0YW9NT05EVUhZVFVROExRa2dQWUoxQUhKUmh5cw?oc=5) — google_news
[41] [Advanced Micro Devices Stock (AMD) Opinions on Recent Price Strength and Analyst Coverage - Quiver Quantitative](https://news.google.com/rss/articles/CBMixAFBVV95cUxQOGc5UlJDVDQySnltN0U3aDRRRFFrb254LVR5NzFOLTlSeF9DNUhneWJlRlNOUzFGVmdtcjZHWXB1eWhUaHB2d29wTzJtLWZYZ2sydXBEU3FWNHlubUh4VmtnZXFybFBaRnVYSG0zNTRDZnZRUFhLZDRXcjhjb0dCRG5hTWsyeGRteW5tY1lTckhFRHdvYmlvNzk1Skp6T0JHVmU3QURScktuUFJMRHdTM1dmeExWNDYwcVVBT3Ytd182MTMt?oc=5) — google_news
[42] [Analysts reboot AMD stock price target before earnings - Yahoo Finance](https://news.google.com/rss/articles/CBMiggFBVV95cUxQVXlQNXlJQkFjVlNtTC1ic21ub3hLYUs2MkE3MFNjbHpGVGMtbk9ZNEc1N1oxbnhodU92ckNYREJmVVdHLWFNaFZEUjFKRENmd2ZaZWFlbTNLV1ZiSGlxemlEc3NVU0U2RFRTck1kcy1SVTFsQjktNTlCeFI3TFhxS1pB?oc=5) — google_news
[43] [AMD: The Next $1 Trillion AI Giant Set to Dominate Inference - MLQ.ai](https://news.google.com/rss/articles/CBMibkFVX3lxTE82dEk4VGxsZEVPWXIwMjdEWWViMnJ5bVJ4eXp2dzRQRzZRN3VGa21Ia2FLa1BqbHFJQXRDdGUzSldMTFEyWDdXSDloLVQyVUtybVR4ZXdWZFcyTC1na0J1bWVLZHFoYXpSaFpIYV9B?oc=5) — google_news
[44] [Data Center GPU Market Size, Share | Research Report [2035]](https://www.marketresearchfuture.com/reports/data-center-gpu-market-28828) — perplexity
[45] [AMD Venice vs NVIDIA AI Chips: The Battle That Could End NVIDIA's Dominance — Explained Simply](https://www.youtube.com/watch?v=KHL6fvNIb6s) — perplexity
[46] [Advanced Micro Devices (AMD) Stock Forecast and Price Target 2026](https://www.marketbeat.com/stocks/NASDAQ/AMD/forecast/) — perplexity
[47] [Private equity continues to lean into healthcare services, with global ...](https://www.facebook.com/alvarezandmarsal/posts/private-equity-continues-to-lean-into-healthcare-services-with-global-deal-value/1453752653437222/) — perplexity
[48] [Advanced Micro Devices, Inc. Common Stock (AMD) Earnings](https://www.nasdaq.com/market-activity/stocks/amd/earnings) — perplexity
[49] [Financial Analysis for AMD](https://finance.yahoo.com/quote/AMD/) — tavily
[50] [AMD surpasses $800 billion market cap - Facebook](https://www.facebook.com/groups/youforextraders/posts/1599791311588973) — tavily
[51] [Advanced Micro Devices (AMD) - Fundamental Analysis Report ...](https://deepresearchglobal.substack.com/p/advanced-micro-devices-amd-fundamental-analysis-report) — tavily
[52] [What is Advanced Micro Devices, Inc. (AMD) stock_business overview_development history](https://www.bitget.com/stock/nasdaq-amd/what-is) — tavily
[53] [Advanced Micro Devices (BVL:AMDUS) - 주식 분석 - Simply Wall St](https://simplywall.st/ko/stocks/pe/semiconductors/bvl-amdus/advanced-micro-devices-shares) — tavily
[54] [Instagram](https://www.instagram.com/reel/DYxy0EkRHn3) — tavily
[55] [Will AMD hitting $1 trillion impact Marvel stock? - Facebook](https://www.facebook.com/groups/1236843014530640/posts/1317929216422019) — tavily
[56] [#WesternDigital (#WDC) is showcasing a beautiful ... - Instagram](https://www.instagram.com/reel/DYSrsO_p5p8) — tavily
[57] [Instagram](https://www.instagram.com/reel/DYrwoINxV-7) — tavily
[58] [#HostingJournalist #Cybersecurity... - Hosting Journalist](https://www.facebook.com/HostingJournalist/posts/hostingjournalist-cybersecurity-arpio-raises-15m-to-expand-automated-cloud-recov/1606388738163720) — tavily
[59] [AMD: The Market Is Still Underpricing Its AI CPU Super Cycle (NASDAQ:AMD) | Seeking Alpha](https://seekingalpha.com/article/4914422-amd-stock-market-is-still-underpricing-its-ai-cpu-super-cycle) — brave
[60] [AMD “emerging as a legit second source in the GPU market” says Citi](https://finance.yahoo.com/markets/stocks/articles/amd-emerging-legit-second-source-113049466.html) — brave
[61] [AMD Stock News: Market Insights and Trends](https://gurufocus.com/news/8914063/amd-stock-news-market-insights-and-trends) — brave
[62] [Nvidia vs AMD: The Better AI Stock Is A Better Buy This June](https://finance.yahoo.com/markets/stocks/articles/nvidia-vs-amd-better-ai-165302797.html) — brave
[63] [Bank of America resets AMD stock price target - TheStreet](https://thestreet.com/investing/stocks/bank-of-america-resets-amd-stock-price-target) — brave
[64] [AMD Stock Rises 2% Following Citi Upgrade on GPU Market Potential](https://gurufocus.com/news/8913925/amd-stock-rises-2-following-citi-upgrade-on-gpu-market-potential) — brave
[65] [AMD Stock | Advanced Micro Devices, Inc. Price, Quote, News & Analysis - TipRanks.com](https://tipranks.com/stocks/amd) — brave
[66] [The latest market data shows GPU shipments are holding up for now but AMD isn't making any inroads on Nvidia | PC Gamer](https://pcgamer.com/hardware/graphics-cards/the-latest-market-data-shows-gpu-shipments-are-holding-up-for-now-but-amd-isnt-making-any-inroads-on-nvidia) — brave
[67] [Better Artificial Intelligence (AI) Stock Buy in June: AMD vs. Nvidia (The Winner Might Surprise You) - The Globe and Mail](https://theglobeandmail.com/investing/markets/stocks/AMD/pressreleases/2415265/better-artificial-intelligence-ai-stock-buy-in-june-amd-vs-nvidia-the-winner-might-surprise-you) — brave
[68] [Advanced Micro Devices, Inc. (AMD) Earnings Dates, Call Summary & Reports - TipRanks.com](https://www.tipranks.com/stocks/amd/earnings) — brave
[69] [The AMD Story: Breakthrough Chips, Hyperscale Deals, Valuation Risks](https://www.tradingview.com/news/gurufocus:16e31c9d5094b:0-the-amd-story-breakthrough-chips-hyperscale-deals-valuation-risks/) — serper
[70] [Advanced Micro Devices (NASDAQ: AMD) Price Prediction and Forecast 2026-2030 (January 2026)](https://247wallst.com/forecasts/2026/01/19/advanced-micro-devices-inc-amd-price-prediction-and-forecast/) — serper
[71] [It's Time To Buy AMD Before Earnings (Rating Upgrade) (NASDAQ:AMD)](https://seekingalpha.com/article/4861129-its-time-to-buy-amd-before-earnings-rating-upgrade) — serper
[72] [Advanced Micro Devices (NasdaqGS:AMD) Stock Price](https://simplywall.st/stock/nasdaqgs/amd) — serper
[73] [AMD’s Inflection Is Here (NASDAQ:AMD)](https://seekingalpha.com/article/4868890-amd-inflection-is-here) — serper
[74] [AMD's 2026 An EPYC Year - MI450x Not The Only Tailwind (NASDAQ:AMD)](https://seekingalpha.com/article/4863244-amds-2026-an-epyc-year-mi450x-not-the-only-tailwind) — serper