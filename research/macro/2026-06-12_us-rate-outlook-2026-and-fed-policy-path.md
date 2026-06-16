# US rate outlook 2026 and Fed policy path

**Type:** macro | **Depth:** standard | **Date:** 2026-06-12 | **Sources:** 66 | **Queries:** 5

### Cost Breakdown
| API | Usage | Est. Cost |
|---|---|---|
| Deepseek (query decomp) | 60 in + 53 out | $0.0001 |
| Perplexity Search API | 1 call(s), 5 queries | $0.0100 |
| Serper news | 10 results (1 call, $0.0003) | $0.0003 |
| Tavily finance search | 3 results (free tier, time_range=month) | $0.0000 |
| Brave Search | 10 results (free tier, freshness=pm) | $0.0000 |
| FRED macro data | 7 series (free) | $0.0000 |
| Exa neural search | 3 queries | $0.0300 |
| Grok-4.3 synthesis (reasoning_effort=medium) | 11721 in + 784 out | $0.0166 |
| **Total** | 12618 tokens | **$0.0570** |

### Source Retrieval Quality
| Source | Count | Content Level |
|---|---|---|
| fred | 7 | 7 full text, 0 snippet |
| google_news | 22 | 22 snippet only |
| perplexity | 5 | 5 snippet only |
| tavily | 3 | 3 snippet only |
| brave | 10 | 7 full text, 3 snippet |
| exa | 9 | 6 full text, 3 snippet |
| serper | 10 | 7 full text, 3 snippet |
| edgar_* | 0 | Skipped — standard depth (deep only) |

⚠️ **Partial full-text retrieval.** 27/66 sources retrieved as full article text; remainder are headlines/snippets.
**Tavily:** time_range=month enforced — exact publish dates unavailable but all results within 30 days.

---

**1. Proximate Drivers**  
May 2026 CPI rose 4.2% year-over-year, the highest reading in three years, with energy accounting for over 60% of the monthly 0.5% increase [11][53]. Core CPI held at 2.9%, while core PCE stood at 3.3% in April [42]. The May employment report showed nonfarm payrolls rising 172,000 with the unemployment rate steady at 4.3%, and prior months revised higher [43][3].  

These prints followed Brent crude near $100 per barrel and national gasoline prices near $4.18, driven by the Iran conflict and uncertainty over Strait of Hormuz traffic [52][64]. Near-term inflation expectations rose while long-term measures remained anchored near 2% [41].  

**2. Structural Factors**  
The economy expanded at a 1.6% annualized rate in Q1 2026, below the 2.0% trend estimate, with consumer spending tempered by higher gasoline and grocery costs [52]. Business investment in AI infrastructure provided the main offset. Wage growth has softened, yet the combination of tariffs, oil shocks, and AI-driven demand is projected to keep year-over-year core PCE above 3% through 2026 [42].  

Geopolitical supply risks and the shift to new Fed Chair Kevin Warsh have lengthened the expected policy pause. The labor market’s resilience—unemployment at 4.3% and solid job gains—has reduced the urgency for easing despite GDP running below potential [3][43].  

**3. Policy Response**  
The FOMC has held the federal funds target at 3.50–3.75% since late 2025, with the June 2026 meeting expected to deliver another unanimous hold under Chair Warsh [58][55]. A Reuters poll of 102 economists found 72 forecasting no change through year-end 2026, up from roughly half the prior month [34][50]. Goldman Sachs now projects the first cuts only in June and December 2027 [42].  

The March 2026 dot plot had shown a median of one 25 bp cut in 2026 and another in 2027; subsequent data have shifted the median toward zero cuts this year [57]. Some officials have signaled openness to hikes if inflation pressures persist [45][47]. The balance sheet runoff continues without announced change [26].  

**4. Asset Transmission**  
The 10-year Treasury yield reached 4.55% in June 2026, up from earlier levels as cut expectations faded [4][51]. Federal funds futures have priced a rising probability of at least one hike by year-end [47]. Equities have faced pressure from higher discount rates, while the dollar has remained firm against major currencies [7][6].  

Gold erased 2026 gains as rate-hike bets increased [21]. Mortgage and other consumer borrowing costs have stayed elevated, consistent with the 3.50–3.75% policy range persisting [43]. Commodity prices, especially energy, remain the key upside risk to inflation and yields.  

**5. Outlook**  
The base case is for the federal funds rate to remain at 3.50–3.75% through 2026, with the first 25 bp cuts now expected in 2027 and a terminal rate near 3.25% [32][44]. Core PCE is projected to stay above 3% this year before easing toward 2.2% by end-2027 [42][57].  

Key downside risks include a sharper oil-price spike that pushes inflation higher and forces the FOMC to hike, or a faster labor-market deterioration that revives cut expectations. Geopolitical de-escalation could accelerate disinflation and allow earlier easing than currently priced.

---

## References

[1] [FRED: CPI (Urban Consumers, SA) (CPIAUCSL)](https://fred.stlouisfed.org/series/CPIAUCSL) — fred
[2] [FRED: US GDP (GDP)](https://fred.stlouisfed.org/series/GDP) — fred
[3] [FRED: US Unemployment Rate (UNRATE)](https://fred.stlouisfed.org/series/UNRATE) — fred
[4] [FRED: 10-Year Treasury Rate (DGS10)](https://fred.stlouisfed.org/series/DGS10) — fred
[5] [FRED: Federal Funds Rate (FEDFUNDS)](https://fred.stlouisfed.org/series/FEDFUNDS) — fred
[6] [FRED: SGD/USD Exchange Rate (DEXSIUS)](https://fred.stlouisfed.org/series/DEXSIUS) — fred
[7] [FRED: USD/EUR Exchange Rate (DEXUSEU)](https://fred.stlouisfed.org/series/DEXUSEU) — fred
[8] [Why the Fed Is Unlikely to Cut Rates This Year - Goldman Sachs](https://news.google.com/rss/articles/CBMimAFBVV95cUxPbkZXVUpDX2pEeXJnbEZUZ056Ul9nQmxqUzZ2TElPX2RwTkJyOWdfNGp6UzN4QjZFSjBxOGV5VlotUmh0NlYwcGtMYUk5ZVVGV0NZazJNb0JwZVplODF0QWJRRU9aMmVsNmpIZTU4TTEyU3A0M1dHekNoZGdBVWdVb2VFVGlIbmM0X1JHQTVFcVZDaVdIcm1lbQ?oc=5) — google_news
[9] [Most brokerages see no Fed policy easing this year - Reuters](https://news.google.com/rss/articles/CBMipwFBVV95cUxOUVpSeEtsNnFwVlpqd0o5ZnFReWtKc1p0OGRxc21XWTNfTTBhVG1UTWdHdFlIbU40TGxEV1hwR25SaGZXZmFvd3g5WlFjRFU5bVppQmhDcTVJTmU1c1kxbHdRLW55RlE2UGpDYTQ0SlhCVGhwcEFYVXdzSDZ1Tmp1WmNoZENuQ1AydDkxT0RLNnBvUnFkN1ViOWZBX2ZReXdWS09pOFdhSQ?oc=5) — google_news
[10] [Markets Brief: Will the US Fed Really Raise Rates in 2026? - Morningstar](https://news.google.com/rss/articles/CBMimgFBVV95cUxNWXBTNnRieHUxa3dLcjB3NE5xSGtzSThxcU13Wl9LZGFFOGlaUXJnUThVeXhxTkRfVmhIdVo3V2w1bUxrdWk4UUN0VU4yQWdPdXRkX1MtQXUzdkxuWnhFbkNYYlpPdjMxN2R4a3JwNkVZSlE4ZTBxSzhGMVZZS3UyckpseFpKWFFvd0pHRHQ4bEltV0xDUUxqWDB3?oc=5) — google_news
[11] [Consumer prices rose 4.2% annually in May, highest in three years - CNBC](https://news.google.com/rss/articles/CBMidEFVX3lxTE8tRFFqM2kyTzM1aHVEUE9lLXNFUFVGLV95RDBmZS1nUjB5eFlaWVh1MU40UklnQ2JjY0pIUl9TOXFqRmlkaUNyUEM4a0FIaTdtZktUcmFabk9aODhxaHhzVy1rZWtWMnBKVUJWTWpVTGlrMk410gF6QVVfeXFMTm5KT2QtSmlfY2N3NnV3VWhoUDVLQmN3UmxRWXJ2WmxWNXRoVVlLWE5IT0hBYV9rc1VldDR1WXlIcmNEMWFKWUczWU0wUEkyQTZXSWR2RzY5RnhvOEM4dFRUZlhiZmJ1UWpVVkY4NW5SVFBxOWI3b1IyY2c?oc=5) — google_news
[12] [US inflation hits new three-year high amid energy price surge - Al Jazeera](https://news.google.com/rss/articles/CBMiqAFBVV95cUxNMlRaYXYwb201U0pIVXBISzZzTDdrOENFSFhQRkhLNVV5WFhBa3VvSllLd2hGeGdFbVpPZ0hWSTQ1MTlZREU4R3V0a2Q1ZUM5aVMzUlFvdUJReFFjUC1mQkk0SUViemF1eGtrdE1vZkVBNi03MUdUcE9PX2dyRGFadUV4Y0JESzVIclRKVlFRU2JrajJlV1lqejM1WXBkUnByMzU1VnZNWEjSAa4BQVVfeXFMTkxjR1FuZGc1YTh5ZW5ITDJLNHUzZFJCNHFRNFFwcWJ6ZGhaYTUzZk5FVS1GbDNIQ1hONVctQVNhX3Fzcmx6eXVMeU9LQWRTeUtsQTdHM2loV01LZndGWWF2dkxRbmhQR1hJQXNsTDFNc3NnZUJfblg4MWhoS1ZuVGloNE53bEt5YVZRVm1ZR2dpaTZIbDZmSHlHQmM0Y29tTDlQOUpISXlHdGZuTWt3?oc=5) — google_news
[13] [Federal Reserve Monetary Policy - U.S. Bank](https://news.google.com/rss/articles/CBMiswFBVV95cUxOa2V2OFo4WjFPclRZRGtjZXJvb3dsaDVUM3FjRnVCTkxfX184eHRyQjJ2NFlDc09TUlZrUDZGUzQzTjgyV1drNG9PSnc2Y0RELWZ5LVktLTlFcGFFa2s0Qm04RzRoYjNRSE9aSGw3aDljNFEyUEZJS1RNa203WlBLdmxxS2lWNmNXT0pRZGdDcGdqdEZ1YmMxN2lhci1RdVRMTEJtWE5wM3RJSFhGMXJjMjdqZw?oc=5) — google_news
[14] [New economic projections signal a tricky Federal Reserve path - Axios](https://news.google.com/rss/articles/CBMicEFVX3lxTE94dUZFdVhWNEdnZmV6bnRpWWgyRUpsNHYzWl95TWFpUkVxdUNsdDhVbjBxTVNJRGJaTDF0b0dFWDN1WTFRVnVrTHNUMkxIUThhVEJxTkxhN0VGcjhzYnhDN2pMMkdHbW0yMjF5ei13b1g?oc=5) — google_news
[15] [March 2026 Fed Dot Plot: Why Cash Yields Are Dropping - Bondsavvy](https://news.google.com/rss/articles/CBMid0FVX3lxTE40ZzdjaHU1a3F1cDliVDJhUWtPU196bHVLVWZ3ejBsNTZ3ZjlrTmdvMjlQTUlUYzhKNGJmNWNhb2M2SE1sZGtDSFlTXzZjRFFYZ090OHM3X2xaallkSkdkVzVfNGt2NFEydWc0T1VEMTZpMXRPclI0?oc=5) — google_news
[16] [Federal Reserve Maintains Rates and Watches Risks From Iran War - The New York Times](https://news.google.com/rss/articles/CBMihgFBVV95cUxObXdQVGN0NlNHN0JKakpoZDZZUzlqcUo2ZS0xS25zX0RxLXIxMVpOYS01RHV1QnV2M19UWXZJVk5QNHlma2o3SEtuSzcyRzRfR3BqR0pBdloybnN5VTdWWC1WeWFDcERpOFZYQ1ZMcng2czJSSDVURWFaVTJfeWtTZEFwZG42Zw?oc=5) — google_news
[17] [US Fed Rate Cuts in 2026? How an Oil Shock Is Complicating the Outlook - Morningstar](https://news.google.com/rss/articles/CBMiqwFBVV95cUxPQnVnbEh0THVOZmlsTVNQczItdTJBcjRibE5jd2lNckt1elN5RlJCd3huNWxPMm9CR2tETktrUDFEQXA4aW9JRkl6dEhGRlVJNGIwZDdwaElGZlZUX0l4UmxBVzFqSXhDekc4V3pzZFdXZlg2d2lwMGVpdS04QXhTU1JkTDc3cE8xamVvNno0U1REdjhEWG1ETFJoajdJanBaTHdhUG1QRWlRZ0U?oc=5) — google_news
[18] [Fed to hold rates this year, cut calls fade as war inflation persists, economists say: Reuters poll - Reuters](https://news.google.com/rss/articles/CBMivwFBVV95cUxOOGhuMmZ6VkYzNVgzQ2NvRUZma1BjdlJIb2pNU29qeDUyeDQ0b2h1YzZKc21DSXBZSU5lajdWWkNQV1h6SDNpQkdEZXBvanZHdk1URTRMYkZzRGl0RmdOVlBiLU84bmZadjNvdUpnWmdudHQ0LUtKcmNsVlAwbkVKVjhSVTVjRFNJUjdocEJSWnI1ZVAtdlRJbUNDOXByVDJWS2lBbWNZVWV3cjNFa051LVNmQXk1WDZ2TUhqakpzcw?oc=5) — google_news
[19] [Gold Price Outlook June 2026: What CPI and the Fed Mean - GoldSilver](https://news.google.com/rss/articles/CBMif0FVX3lxTE9sUTlpSVdDNFo1VTNRampYV3Y0TlFOOWNKZDkxaTZGeUszdjVnMEhfdXM5R0FKWUREV0k0SVhldUVzdENjVEt2TWZIOFJ5aVZUMmVLdVlCUWZ2Wjc0Sng1bzFqd19zQlpaVF91aFBZYl83YWhOalRFSVZjUU9pbkU?oc=5) — google_news
[20] [Fed Interest Rate Decision 2026: Powell Is Out, Warsh Is In, and Markets Are Repricing Everything - Mitrade](https://news.google.com/rss/articles/CBMijwFBVV95cUxQai15RGF1M18xVlY0OWNfenZIYUpuQXJfQ1E3bmlQVzJiTmx5a19YVzJOR05OWm5zOGQ1N211SWw4Z2xrV2d6TVl0MWZ5ZTdMa3ZtQnFzc3BTNzY4ZU9wSjBuanc5eUFDbzh3Rl9uWnJ6Qm05S19zM3k5b3BGSXQyT2VoWmdBdEVjTHBQYVNkRQ?oc=5) — google_news
[21] [Gold Erases Last of 2026 Price Gains as Fed Rate Bets Soar on Strong Jobs Shock - BullionVault](https://news.google.com/rss/articles/CBMijAFBVV95cUxPTmFxRlFZaXdfMTF3b05wZGxQZmU3Zk5uNjU4MlNMTVVldmNHbzRUTUtRZW9QWTlwaTRYY1hnQjJVemhNVDJTdkpnQUI5MEJFWG9Tak9nRXFIdVFTeGJtSHVNLUQ4X3pGQzQzRmtBYW1Gcl8yZldsMU9LdWRtSFVad0RDMUg4VlJDTmpNNg?oc=5) — google_news
[22] [Fed Leaves Rates Unchanged to Start 2026: Is a Cut Coming in March? - J.P. Morgan](https://news.google.com/rss/articles/CBMijwFBVV95cUxQclBRVmJheElTNjZMUVRPalRFeXN6LW95NjdyN29ZVk40VDZIUXdCS3NGczNBYXd4Y2ZGTWhqVC0xWmVJN2F5MkVhM2pMRXVkb1ZvYnRkU2VRVVptTEhaUENkaG5yU25jbV84SjZFem1KRkRLOC1PcGJEbElQQVBLak9pWVNLUk5MNDFIdGdUMA?oc=5) — google_news
[23] [Will the Fed cut interest rates? Here's what to expect at Wednesday's meeting. - CBS News](https://news.google.com/rss/articles/CBMihgFBVV95cUxNdllkeFZNN05JSjJZUkNjeDZObFAzVFF1SnhtYlZwWXd3bjk2dHFoQnVqRXdDd2ppenpnVERnRVpvWjRERERzMkF5eVMzb2drWk1PWGxTaFZOQmRRTkRrOElPX0x5bllnNkZnUmZrVnVYbkJLUjNqbWV2SjByMmxCSXlCN05NZ9IBiwFBVV95cUxPV3g3XzNSUS03VlRPZGd2Nml0cktJMXZmNXVtTHROU0pxYzBBMlVFY251dTd0MmpiOGc5UFpzRDBOTnpzWXMtR0ZnRWFvTm9EdTBJZm5lbmN6SkFfZUhSb2NCejdnV3RrQUxkOWpDLWk3Vm02SVlwbmpXcUI3eldvQkxKaTBsQ3V3dktn?oc=5) — google_news
[24] [Fed to hold rates through May, but Warsh may be too loose with policy, economists say - Reuters](https://news.google.com/rss/articles/CBMivgFBVV95cUxOSzRvcE5HeTBZZGtwTTRWVl9hY2RGZ3ZaVlhNWmNCWGlDSkh5VFdmaXlHbVRuZ1NJQXRRV1VsREFuQl9mX3huRjladGhNdm81bWxBTklkOEpTZk4zOGFIVi1wOFZPME82cUFuQzJnSTFZWXVXMm14cDZvVi1OMFQzZHVjVnVrdmZjQUNWLUdMYXBHblZkdkNfaDZDY1JCQmVHbEZ5WFRJWWRXX1BJNFAtdlhCZ1ozMmZoLWk5bjBR?oc=5) — google_news
[25] [Forecasts for February PCE Report Show Inflation Above Fed’s Target - Morningstar](https://news.google.com/rss/articles/CBMinwFBVV95cUxPRWFyanJCbXRzQVprMVV4TE0yZTYtVzJoSnRobjNDUlV5dVFLV1hudzZILXlUbTJjOEx0eVJBb19ZYXlINjdVUE83OFNISjlMZDlsOW8zZHhpUTNleEFCUHBxSEdSejVoY1hUQmdzbHN5SHA1NnhHR1ZfeFA5M0stLWNkX0ZHV1pKNDRoRjI4V0pGT1J5OTdpM09DdFZJUFk?oc=5) — google_news
[26] [Tracker: The Federal Reserve’s Balance Sheet Assets - The American Action Forum](https://news.google.com/rss/articles/CBMikAFBVV95cUxNR2NrRDdoQ1MwS0paZFliV01BelV0MS1tQkNMSEdJYmYweWctanpzZU5hMllmVUtjQWR2cXBPSVhFeFluSFlMbi1ZVTg1ZS1TYzRMam81MFlRbWxockRRN2RpeEk2OGhpYWVXUVpsX3lvcUx4QUFERERGQVdkeVRndHJNeExJTU9DLS1GRW9GTW0?oc=5) — google_news
[27] [U.S. federal funds rate 2026 - Statista](https://news.google.com/rss/articles/CBMijwFBVV95cUxPV28taUdoN196T2U5SmpSbXhMUWxqYTJZMWtTakxxbDF0cFRkTldkMi1FTHZtdG1jZ0hVSXFKMnRHNHBxYThjS1VuNXVkcU5CUmhRbDFfcDBscU5VVHhDcE9aR0FXQlBDUUg1a0N0LV9ZeXU0VVBtNG5RUEE5Q1FFaVhIeTFxeXlRd2dJbkpOZw?oc=5) — google_news
[28] [Federal Funds Rate History 1990 to 2026 - Forbes](https://news.google.com/rss/articles/CBMickFVX3lxTE9TNGQzWm9KM3Q5dEd1Y1VHUDcweG5aOWRYRjhWVzQ4dXh5T1pSLVdvc3NwS2h0bWN2M3ZjRDZrdDVtVHBJeFMwTlp6MVdmS284anAzZWVDZm1CRU16U3JsTFV1U19ab21mTzN6WWVvRHQzZw?oc=5) — google_news
[29] [Interest rates and monetary policy: Economic indicators - The House of Commons Library](https://news.google.com/rss/articles/CBMickFVX3lxTE92Wm8yQUtBUUMySFA5VHVva05qYlNhMkNTTHY5RThzOVE0VUdsZnRJOUFtYlcyODk3Y0RBWERCV2pSWXlST0xWWUpRX3B4V3JDX3k3am8wenJLcVdzTDh4MDhfM3VpUnllTW5QU19Nc3dCQQ?oc=5) — google_news
[30] [Monetary Policy - Federal Reserve Board](https://www.federalreserve.gov/monetarypolicy.htm) — perplexity
[31] [Anchored to the Dot Plot: Central Bank Projections and Interest Rate ...](https://www.federalreserve.gov/econres/feds/anchored-to-the-dot-plot-central-bank-projections-and-interest-rate-expectations.htm) — perplexity
[32] [Fed: Extended pause before cautious easing – UOB - Mitrade](https://www.mitrade.com/au/insights/news/live-news/article-6-1722580-20260514) — perplexity
[33] [The Fed - Finance and Economics Discussion Series (FEDS) - 2026](https://www.federalreserve.gov/econres/feds/2026.htm) — perplexity
[34] [Fed to Hold Rates This Year, Cut Calls Fade as War Inflation Persists, Economists Say: Reuters Poll](https://money.usnews.com/investing/news/articles/2026-06-09/fed-to-hold-rates-this-year-cut-calls-fade-as-war-inflation-persists-economists-say-reuters-poll) — perplexity
[35] [What Investors Need to Know About Interest Rates (Part 3) - YouTube](https://www.youtube.com/watch?v=MY6vzsaS8gc) — tavily
[36] [Federal Reserve 2026 Outlook Why Interest Rate Cuts May Not Happen Soon - YouTube](https://www.youtube.com/watch?v=PPyBXtE-ZIU) — tavily
[37] [Mortgage Rates Forecast 2026: Expert Predictions & Outlook - Forbes](https://www.forbes.com/advisor/mortgages/mortgage-interest-rates-forecast) — tavily
[38] [Fed to hold rates this year, cut calls fade as war inflation persists, economists say: Reuters poll | Reuters](https://reuters.com/business/fed-hold-rates-this-year-cut-calls-fade-war-inflation-persists-economists-say-2026-06-09) — brave
[39] [Kalshi](https://kalshi.com/markets/kxfeddecision/fed-meeting/kxfeddecision-26jun) — brave
[40] [Federal Reserve Board - H.15 - Selected Interest Rates (Daily) - June 11, 2026](https://www.federalreserve.gov/releases/h15/) — brave
[41] [The Fed - Monetary Policy:](https://www.federalreserve.gov/monetarypolicy/fomcminutes20260429.htm) — brave
[42] [Why the Fed Is Unlikely to Cut Rates This Year | Goldman Sachs](https://goldmansachs.com/insights/articles/why-the-fed-is-unlikely-to-cut-rates-this-year) — brave
[43] [Economists see Fed holding rates steady through 2026, Reuters poll shows | Prism News](https://prismnews.com/news/economists-see-fed-holding-rates-steady-through-2026) — brave
[44] [Economists Push Rate-Cut Expectations Into 2027, Survey Shows | Financial Post](https://financialpost.com/pmn/business-pmn/economists-push-rate-cut-expectations-into-2027-survey-shows) — brave
[45] [More Fed policymakers eye possible rate hike as inflation risks rise | Reuters](https://reuters.com/business/fed-officials-mull-raising-rates-curb-growing-inflation-risk-2026-05-29) — brave
[46] [June 2026 FOMC Preview](https://employamerica.org/fomc-meetings/june-2026-fomc-preview) — brave
[47] [Markets begin eyeing a Fed rate hike around the turn of the year | Reuters](https://reuters.com/markets/us/markets-begin-eyeing-fed-rate-hike-around-turn-year-2026-05-15) — brave
[48] [Why the Fed Is Unlikely to Cut Rates This Year | Goldman Sachs](https://www.goldmansachs.com/insights/articles/why-the-fed-is-unlikely-to-cut-rates-this-year) — exa
[49] [72 of 102 Economists Expect Fed to Hold Rates at 3.50%-3.75% Through 2026, Reuters Survey Shows | Gate News](https://www.gate.com/news/detail/72-of-102-economists-expect-fed-to-hold-rates-at-350-375-through-2026-21736267) — exa
[50] [Fed to hold rates this year, cut calls fade as war inflation persists, economists say: Reuters poll | Kitco News](https://www.kitco.com/news/off-the-wire/2026-06-09/fed-hold-rates-year-cut-calls-fade-war-inflation-persists-economists) — exa
[51] [Fed Funds Rate Forecast 2026-2031 | StreetStats](https://streetstats.finance/rates/fedfunds) — exa
[52] [SF FedViews: Uncertainty Clouds the Outlook on Inflation and the Economy - San Francisco Fed](https://www.frbsf.org/research-and-insights/publications/fedviews/2026/06/sf-fedviews-june-4-2026/) — exa
[53] [Warsh Takes Office as Fed Chair, June FOMC Preview │ PrimeRates](https://primerates.com/warsh-first-week-fed-chair-june-fomc-outlook/) — exa
[54] [Inflation fears push some economists to expect rate hike | Asset Securitization Report](https://asreport.americanbanker.com/news/inflation-fears-push-some-economists-to-expect-rate-hike) — exa
[55] [June 2026 FOMC Meeting Preview: June 16-17 Decision, Dot Plot & Market Impact | EskiSignal](https://eskisignal.com/june-2026-fomc-meeting-preview/) — exa
[56] [Kevin Warsh’s Fed Era: Refining the Average Inflation Framework, Dot Plot Reforms, and a 2026 Interest Rate Outlook | Gate Blog](https://www.gate.com/blog/kevin-warsh-fed-era-trimmed-mean-inflation-framework-dot-plot-reform-and-2026-rate-path-outlook) — exa
[57] [March 2026 Fed Dot Plot: Why Cash Yields Are Dropping](https://www.bondsavvy.com/fixed-income-investments-blog/fed-dot-plot) — serper
[58] [Fed’s Interest Rate Decision: April 29, 2026](https://www.advisorperspectives.com/dshort/updates/2026/04/29/feds-interest-rate-decision-april-29-2026) — serper
[59] [What’s Next for the US Fed in 2026?](https://global.morningstar.com/en-gb/markets/whats-next-us-fed-2026) — serper
[60] [Daily: S&P 500 closes in on record high after Fed cuts rates](https://www.ubs.com/global/en/wealthmanagement/insights/chief-investment-office/house-view/daily/2025/latest-11122025.html) — serper
[61] [Federal Reserve lowers policy rate by 25 basis points, dot plot signals 25 basis points in cuts for 2026](https://sherwood.news/markets/federal-reserve-rate-cut-december-2025-fomc-jerome-powell/) — serper
[62] [Fed Interest Rate Predictions for the Next 3 Years: 2026-2028](https://www.noradarealestate.com/blog/fed-interest-rate-predictions-for-the-next-3-years-2026-2028/) — serper
[63] [Will the Fed Cut Interest Rates in June 2026? Expert Analysis](https://intellectia.ai/blog/will-fed-cut-interest-rate-june-2026) — serper
[64] [April 2026 FOMC: Will Fed Cut Rates? What You Must Know](https://www.bitget.com/academy/april-2026-fomc-will-fed-cut-rates-what-you-must-know) — serper
[65] [Fed votes to hold rates steady, notes 'uncertain' impacts from Iran war](https://www.cnbc.com/2026/03/18/fed-interest-rate-decision-march-2026.html) — serper
[66] [The business environment Q1 2026](https://www.bbh.com/us/en/insights/capital-partners-insights/the-business-environment-q1-2026.html) — serper