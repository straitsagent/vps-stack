# US Fed rate outlook and inflation trajectory

**Type:** macro | **Depth:** standard | **Date:** 2026-06-12 | **Sources:** 66 | **Queries:** 5

### Cost Breakdown
| API | Usage | Est. Cost |
|---|---|---|
| Deepseek (query decomp) | 57 in + 50 out | $0.0001 |
| Perplexity Search API | 1 call(s), 5 queries | $0.0100 |
| Serper news | 10 results (1 call, $0.0003) | $0.0003 |
| Tavily finance search | 2 results (free tier, time_range=month) | $0.0000 |
| Brave Search | 9 results (free tier, freshness=pm) | $0.0000 |
| FRED macro data | 7 series (free) | $0.0000 |
| Exa neural search | 3 queries | $0.0300 |
| Grok-4.3 synthesis (reasoning_effort=medium) | 13635 in + 937 out | $0.0194 |
| **Total** | 14679 tokens | **$0.0598** |

### Source Retrieval Quality
| Source | Count | Content Level |
|---|---|---|
| fred | 7 | 7 full text, 0 snippet |
| google_news | 22 | 22 snippet only |
| perplexity | 5 | 5 snippet only |
| tavily | 2 | 1 full text, 1 snippet |
| brave | 9 | 8 full text, 1 snippet |
| exa | 11 | 5 full text, 6 snippet |
| serper | 10 | 9 full text, 1 snippet |
| edgar_* | 0 | Skipped — standard depth (deep only) |

⚠️ **Partial full-text retrieval.** 30/66 sources retrieved as full article text; remainder are headlines/snippets.
**Tavily:** time_range=month enforced — exact publish dates unavailable but all results within 30 days.

---

**1. Proximate Drivers**  
The immediate driver of the current Fed rate outlook is the May 2026 CPI print showing 4.2% year-over-year inflation—the highest since 2023—driven overwhelmingly by energy prices linked to the Iran conflict. Energy accounted for roughly 60% of the monthly increase, with the index rising 0.5% month-over-month to 333.979. Core CPI rose a softer 0.2% month-over-month and 2.9% year-over-year, but the headline surge has shifted market pricing away from cuts. [1][38][41][56]

A resilient labor market has reinforced this dynamic. The May jobs report added 172,000 positions while unemployment held at 4.3%, prompting forecasters to revise unemployment paths higher only modestly (to 4.4%). Combined with oil prices remaining above $100 per barrel amid Strait of Hormuz disruptions, these data points have eliminated near-term rate-cut expectations that prevailed earlier in 2026. [3][35][41]

**2. Structural Factors**  
Underlying the inflation spike are persistent supply shocks from the U.S.-Iran conflict interacting with demand-side pressures from AI-related capital spending and tariffs. Business investment in AI infrastructure supported Q1 2026 GDP growth of 1.6% annualized, while energy and tariff effects have kept core PCE near 3.3%. This combination blurs traditional supply-shock signals, as wealth effects among high-income households sustain spending even as real disposable incomes fall for lower-income groups. [47][54][56]

A K-shaped recovery and geopolitical uncertainty further complicate the picture. Job gains remain concentrated in government, leisure/hospitality, and healthcare, while non-tech business investment has declined for six quarters. Long-term inflation expectations remain anchored near 2%, but near-term measures have risen, and the absence of a signed ceasefire keeps commodity prices elevated. [43][45][54]

**3. Policy Response**  
The Federal Reserve has held the federal funds rate in the 3.50–3.75% range since late 2025, with the effective rate at 3.63% as of May 2026. Minutes from the April meeting showed a majority of officials prepared to firm policy further if inflation remains persistently above target. Markets now price a 66% probability of at least one 25 bp hike by year-end, though the June 16–17 meeting under new Chair Kevin Warsh is expected to leave rates unchanged. [5][30][42][58]

Most major banks have removed 2026 rate cuts from their forecasts. Goldman Sachs now sees the first cuts only in 2027; Wells Fargo and Reuters polls similarly project no easing this year as war-driven inflation persists. Political pressure from the Trump administration for lower rates exists but has not altered the data-dependent stance. [17][23][27][46]

**4. Asset Transmission**  
Higher-for-longer policy has pushed the 10-year Treasury yield to 4.55% and the 30-year yield above 5.1%, lifting 30-year fixed mortgage rates to the 6.3–6.6% range. The dollar has firmed, with EUR/USD near 1.153 and DXY around 99, supported by rate differentials and sticky U.S. inflation. Gold, silver, and bitcoin have declined as traders price higher odds of Fed hikes. [4][16][21][40][45]

Equities face mixed transmission: AI-exposed sectors continue to attract capex-driven investment, but higher borrowing costs weigh on housing, autos, and lower-income consumption. Credit-card and auto-loan rates remain elevated, while the 2-year Treasury yield near 4.13% reflects limited near-term policy relief. [38][43]

**5. Outlook**  
The base case is for the Fed to hold the funds rate at 3.50–3.75% through 2026, with cuts possible only in 2027 once energy shocks fade and core PCE moves closer to 2%. Inflation is expected to remain above 3% for most of 2026 before moderating, assuming no further escalation in the Middle East. Unemployment is projected to edge up only to 4.4%. [46][54]

Key downside risks include a prolonged Iran conflict that embeds higher energy prices into core inflation, forcing the Fed to hike rather than hold, or political interference that undermines credibility and triggers dollar weakness. Upside risks center on faster ceasefire progress and productivity gains from AI that could accelerate disinflation. [35][44][45]

---

## References

[1] [FRED: CPI (Urban Consumers, SA) (CPIAUCSL)](https://fred.stlouisfed.org/series/CPIAUCSL) — fred
[2] [FRED: US GDP (GDP)](https://fred.stlouisfed.org/series/GDP) — fred
[3] [FRED: US Unemployment Rate (UNRATE)](https://fred.stlouisfed.org/series/UNRATE) — fred
[4] [FRED: 10-Year Treasury Rate (DGS10)](https://fred.stlouisfed.org/series/DGS10) — fred
[5] [FRED: Federal Funds Rate (FEDFUNDS)](https://fred.stlouisfed.org/series/FEDFUNDS) — fred
[6] [FRED: SGD/USD Exchange Rate (DEXSIUS)](https://fred.stlouisfed.org/series/DEXSIUS) — fred
[7] [FRED: USD/EUR Exchange Rate (DEXUSEU)](https://fred.stlouisfed.org/series/DEXUSEU) — fred
[8] [Federal Reserve keeps interest rates steady as inflation uncertainty rises - U.S. Bank](https://news.google.com/rss/articles/CBMipAFBVV95cUxNRHE2X3NqMTh3SDJDcXAyMlBMcE96b2xIc3BBSTJvNXA1WFZuSHlpanRkMnlJdjNYZUdONHVqT3g5VXZONm02UGRzTjVLSU11bldvdHktMjVOVHBrdnYya3RCS0c1TFp1Zl9lX1dDQUhaTTVMM2wzeFlvNGFYNktiVEl2dk50aWhUU3diQUFYaVh1OXpQRnZPdDN5LTdycndSRDVOdw?oc=5) — google_news
[9] [US Economic Forecast Q1 2026 - Deloitte](https://news.google.com/rss/articles/CBMisAFBVV95cUxPenRYbVVidzhLTkVVbXN2VHd4VjY3ZGlZWjBFa0NCQ2xPcEhneHlWZVhud3p2cUVMcWNsdkEzLTlpcmVxREZBbDBkOGFEa0wySEx4YkdoMkdzT3N6NXRnQ19waFNqM3BCdkE1bmczY1pHNVNxQkxoRnpkMk15cERnSklGLTc0ZlZvMzFxeEEtalR1UWF3R0VWNjZCWXFqMUk0VERZWHdpaHplWTdFdmlldQ?oc=5) — google_news
[10] [US Fed to trim rates twice more this year; 2026 rate path very unclear - Reuters](https://news.google.com/rss/articles/CBMisAFBVV95cUxObW1wMzI4ck5KcEhrRXoxQl9VSU8xcjRaaUh1RHBfVjY5Qm9mdldVQmRXQmxqaGRmVmtadnlvSlVFT2lRUk91eW5GRFYyblJ3aVhmS25PT1lXam5pdnFUdHdGbW9pMjRmUjczM19JTktjbEkwVkw1cjRDWG93MFZKRTN4ZlFVdkw5Wmc3WnlKNmZUZTlaSE1iMXJaYzEzRXR1U2FqVkVXR0lHT3FFbGJtRQ?oc=5) — google_news
[11] [March 2026 Fed Dot Plot: Why Cash Yields Are Dropping - Bondsavvy](https://news.google.com/rss/articles/CBMid0FVX3lxTE40ZzdjaHU1a3F1cDliVDJhUWtPU196bHVLVWZ3ejBsNTZ3ZjlrTmdvMjlQTUlUYzhKNGJmNWNhb2M2SE1sZGtDSFlTXzZjRFFYZ090OHM3X2xaallkSkdkVzVfNGt2NFEydWc0T1VEMTZpMXRPclI0?oc=5) — google_news
[12] [Upcoming U.S. jobs report to test Fed’s rate outlook - Finance & Commerce](https://news.google.com/rss/articles/CBMihgFBVV95cUxOZUpkZ2hrQXNSNWtWbkFxbncxSVZER0oxT1ZMV3pYdjFhTndtTWFlRVlyRUdaYk1lVFhtUjNaZ1dqVlVmb2IyRm4tZXgxeGVFMmJHNkJTeUZscm93Q2tLUUhkUzBhVXA0ZU5qLVNJMXhIRGZEQnpMRTFFUVMtRnhlTWZrZTB5Zw?oc=5) — google_news
[13] [Economists Push Fed Rate-Cut Expectations Into 2027, Survey Shows - Bloomberg.com](https://news.google.com/rss/articles/CBMiqAFBVV95cUxPemVQRm9zcTB5amtVa2xWNFRNZzlXdjBNMFJ0RkNxX0dMZEI4cHdMSmRoWWRiQVY4amJ1UUQwUWdWck5jTkhYN0tDTUtqLS1FajhKalBBcGZzc0djOUVqd0hzR3dSdDFDaW8xTTBYYzRqR2lzWlJIdnNaMjNtdkdEVlY1LUdXcVc2cU1tVkdzbDNrUndSODlha3VETnFCSlAxS1Y3NEMyTHA?oc=5) — google_news
[14] [New Fed chief may soon be forced to defy Trump and raise interest rates - The Washington Post](https://news.google.com/rss/articles/CBMitwFBVV95cUxNNFMtaFpTQUd2alhSWEZzMkhCLUZwNDNUcnJtZERyVkY0MUpIV2lHcHktRXEzRERyYUxEN0RJMDk2V1h0Uzg1TDIwS2VyclVxZE9xYWNxelNhTWZwaXltSUYxSklHUkRCYkxFZFMyOEZLbzM4WlNyQ0dBdHJPUF9zVzVEeTM3dnJzUUhkQlliUnlxb3FfdE5zZzR5ekdIVnVyVkxVZVdNdUEtaWVIYVNyNnNpR0dJRkU?oc=5) — google_news
[15] [Inflation is the worst in three years. Kevin Warsh says that’s not the full story - CNN](https://news.google.com/rss/articles/CBMihwFBVV95cUxPTFBBbEtBRjFtbC1fRlFtSXZfblhBSTJ6TzdpcFVfRGtCMEk5anJRTklWNm5pU0VMWndCZW1tOGNBSGdxRUY3Ry1yRW0wcE1Nb3p3a0dxUDVsNkZaelp4ako0akNuNmFsa2dKOVEtLS1HeEJSMXVoeHhMWHJzc1ptdnZZak5IQjg?oc=5) — google_news
[16] [Gold, silver and bitcoin fall as traders up Fed rate hike bets - CNBC](https://news.google.com/rss/articles/CBMipgFBVV95cUxNRnhXZlNwU2VVYzlTY2RITnh1N1NTUzMxUmlicEdweF9CcUwtYzVVUnItLTNyUU10cm5wYzloMXZkZjZQaDZ2WjF4R09Eb0tyVHN5X1NQUUhWdHRfSW5IWjNqRzhBTXFOVHdTM2ZURDF0aFNSRDVSSXI5bVU4QWt6NFZ0XzV4SmFUMUFEa1JDb3g4Y0ZWcWR0SGNTYVJETmIzRUNwMWV30gGrAUFVX3lxTE0yRVFwQnFheVNZbXo4OEM0S2xtQUg1b0tyR0Z3TkdQTjlRM0xHYlhaVHZzZFV3cXZDQ19vSXFmUnA2cWROZ1NhMGZEa1lBQ2hjY3lDYXVJVW1UckpFV3lUelFYVzVKa1R4VUdUa3hzbVJFY0dHLTdURnhKUE9vZjB4SkFmZWw2M1ZTX0lsUjdVYXE3YzZNd3UzYXpoTzhncy1xQ0VVX1RWcjhWZw?oc=5) — google_news
[17] [Why the Fed Is Unlikely to Cut Rates This Year - Goldman Sachs](https://news.google.com/rss/articles/CBMimAFBVV95cUxPbkZXVUpDX2pEeXJnbEZUZ056Ul9nQmxqUzZ2TElPX2RwTkJyOWdfNGp6UzN4QjZFSjBxOGV5VlotUmh0NlYwcGtMYUk5ZVVGV0NZazJNb0JwZVplODF0QWJRRU9aMmVsNmpIZTU4TTEyU3A0M1dHekNoZGdBVWdVb2VFVGlIbmM0X1JHQTVFcVZDaVdIcm1lbQ?oc=5) — google_news
[18] [Uncertainty clouds the US Fed’s future rate path - Deloitte](https://news.google.com/rss/articles/CBMiqgFBVV95cUxPcU1qVkxyMmliczdtRlFsMW5wQVkydGxJaW1XbkJwNlpuNEZDRnFkdm1NN2xMR3BCMGZNZFZPZVpIejVyY0hMbTBlN3BfWWhpeG52b0pNTGh4T3NSRXVqNndJeU5HQlZUMFZEejBMSkQzZ0JLaUVmQ1FPdGRvY0xib2V1UmxhUXAySW82bmplN251dlR0czRlbktkMVR2OHduZnNYRjBwdElvUQ?oc=5) — google_news
[19] [Federal Reserve Monetary Policy - U.S. Bank](https://news.google.com/rss/articles/CBMiswFBVV95cUxOa2V2OFo4WjFPclRZRGtjZXJvb3dsaDVUM3FjRnVCTkxfX184eHRyQjJ2NFlDc09TUlZrUDZGUzQzTjgyV1drNG9PSnc2Y0RELWZ5LVktLTlFcGFFa2s0Qm04RzRoYjNRSE9aSGw3aDljNFEyUEZJS1RNa203WlBLdmxxS2lWNmNXT0pRZGdDcGdqdEZ1YmMxN2lhci1RdVRMTEJtWE5wM3RJSFhGMXJjMjdqZw?oc=5) — google_news
[20] [Will Interest Rates Go Down in June? | Predictions 2026 - The Mortgage Reports](https://news.google.com/rss/articles/CBMijgFBVV95cUxQVDc1cXVCNGFWS2NSSzhlejJuZkN0bW84bEpMYzBoS0RaU0wwZTlqX015RmtYa2dNTVFIUUJxZTZoN1ZWZGZjZ3FjRFlJc0t5WVVkNWRtQzNIb3dxaURmejdqSVo3LXJHUFRSTDhLSERuRmpONmoxS0lJa2tEMjVEeFdYcGNzQVFJd1BhU1ln?oc=5) — google_news
[21] [30-year Treasury yield tops 5.1%, highest in nearly a year - CNBC](https://news.google.com/rss/articles/CBMipwFBVV95cUxNQUJJWTM0SGpOT0IzMEYwdVRaSGF0ZnhlTzFORUdOamFMNGNpbHdaLXRhLUt0eXRqUWJPSmFVMVpZTE1YdzVNSjAyaXJHZ2VlbFJqVDdLNzduXzlyZlJoVnM4WW52YnNMdTdOa2xUV1JHZEc5alZhZEtDS1U5RU1lTTNCMDlDSWZzZ0pHYnlVeWlrRkdnVUNqMGxfZHJtLXUtcHJqMUJPVdIBrAFBVV95cUxOSGhEVE9IWFNFaXN3QWN3ZzB0SnhpRW80elAyZk1ZZGtzOGtyMlNBWTJMM0hfRWVuTllpSnFKbXRlMTZJTDBpZ21COWoxam5JNTdMamVGeVYxakRtY3NHMkVOTXdmNDFEbUlndl9IWUhaa1FxbTRDMlFSazhBMkJYcU14M3dqR1NiVlcwR3BsdEFqYm5FYkZiRlU5bkgyU2tpNXpFdnEwV24xMXh1?oc=5) — google_news
[22] [Mortgage Rates Forecast For 2026: Experts Predict Whether Interest Rates Will Drop - Forbes](https://news.google.com/rss/articles/CBMif0FVX3lxTE9kMlJHRWhRY2owbnpsZWhWOHVVZFR1ZmM3NzhqTUVEVnpHR2xlMHp0QnR2eXFwV2wzQ2FMbXZTN3lTLUJ5OHgxdnk0S3Z2Q3hEQ2pEYW9xcWhrRktVS3B0RXB0NkdnM0hPMzBReG5neWZ1TTdvVWs4bWgxdWFNUkk?oc=5) — google_news
[23] [Fed to hold rates this year, cut calls fade as war inflation persists, economists say: Reuters poll - Reuters](https://news.google.com/rss/articles/CBMivwFBVV95cUxOOGhuMmZ6VkYzNVgzQ2NvRUZma1BjdlJIb2pNU29qeDUyeDQ0b2h1YzZKc21DSXBZSU5lajdWWkNQV1h6SDNpQkdEZXBvanZHdk1URTRMYkZzRGl0RmdOVlBiLU84bmZadjNvdUpnWmdudHQ0LUtKcmNsVlAwbkVKVjhSVTVjRFNJUjdocEJSWnI1ZVAtdlRJbUNDOXByVDJWS2lBbWNZVWV3cjNFa051LVNmQXk1WDZ2TUhqakpzcw?oc=5) — google_news
[24] [When will mortgage rates go down again? - Yahoo Finance](https://news.google.com/rss/articles/CBMitAFBVV95cUxPOWJXa0R6SmRlZzViSXVTNldIR1lUNlhBOTljb1FpSzZhUTN6YjN3a1F6bUo1NFBNa1V2LVpHYVIwT2JJMFUxeGs4YlBwaGlyRjJGcWxPMm1mVm03UkV1VV92OEp0YUxWUDUtWkpDYTNVWWJSWFBtTkYyLWJJdzlOMHQxS0sxV281cEtHSXluMDI2QWE1bmlReEJVeE1yN09DYmVUVC1vZjFOcGtsWjBIZGc2OUo?oc=5) — google_news
[25] [Federal Funds Rate History 1990 to 2026 - Forbes](https://news.google.com/rss/articles/CBMickFVX3lxTE9TNGQzWm9KM3Q5dEd1Y1VHUDcweG5aOWRYRjhWVzQ4dXh5T1pSLVdvc3NwS2h0bWN2M3ZjRDZrdDVtVHBJeFMwTlp6MVdmS284anAzZWVDZm1CRU16U3JsTFV1U19ab21mTzN6WWVvRHQzZw?oc=5) — google_news
[26] [The Fed was expected to cut rates in 2026 — but a new inflation forecast suggests relief could be delayed - Yahoo Finance](https://news.google.com/rss/articles/CBMilwFBVV95cUxPWkJKNk1BMFhmRHBxeUlNVE1zVEM5dmdpckNWR1FQWUJvc2dNSEFhaXZPczF0M3RJNVluQ3loeExiYW1OcFFNLWpCSTd5RnNsbFdnNnNLcmVDRDlBUGRXSkdTS3o2aWRic2wzbFI0OHNrTGpiTy0tMXUyaXhRc0ZkTE1YbGJGOFpmdWNMYWh1X3I4VkZoSEJr?oc=5) — google_news
[27] [Wells Fargo no longer expects Fed rate cuts in 2026 as Iran war drags on - Reuters](https://news.google.com/rss/articles/CBMiswFBVV95cUxNSEtMb3llZ1plTjFsOEZWbE43ZlhYNzlCbFdsVGk5Z2hzUHJKbTdHTi13SUtLS1pSTGQ0Rm5FTUVHa0N1QTdQclpia2VWSmh2dnBmV1lqeVNVVjlKU2FsMmtxUW93bHlEWFd1Z29OZlhwYlIzQlV3emc4eVQ3WTJlNF9wcFpiQ1BFUE9IcTl0Nk5MS1o5RVpTRVBvbHhmc3VzWEJsZFdnTEVpRzRpd1lBQzJycw?oc=5) — google_news
[28] [The Fed Meets This Week—And Savings Rates Could Stay High for Longer Than You Think - Investopedia](https://news.google.com/rss/articles/CBMivgFBVV95cUxOYVRpS01RMHlRb0p3cnVxUnNuYXpueWxheGZPNDF3V0kzbDVvWm1SMXYySHl6RWhMYkVuZXVFV3Brc0VJaTVWYXJKYnQ5QnNaRWs5RkZPbUVBT2lLcm9Vak1RT3ZvYXVIa21JZ2UzVkMwS2U3NzI0ZFdfeHp3U3Ywb3hsbFRZLURYcERYeENSX25rSlphNXk1dDk4ZHhBQ05HSjBIQks5QWZMMVdkMEtlN0ZkbUhhZndab3gxOEJR?oc=5) — google_news
[29] [Goldman delays Fed rate cut outlook amid inflation pressures - MSN](https://news.google.com/rss/articles/CBMi2gFBVV95cUxQTTV4TFZuVGYtTDE4cUpWNmdRbTJMS0k2dzFNUUpUUGxmeGI3M29mWnMxclhrbjBCNElDZVhad3ZwckhmVHVxb0loQUZwYm0wR2pucjNiSlQtNUFQblIzMENlQ2FnaFBRNHlTdmVpWXA4X1ZJUnk0OXQxN2FKZGp6NE45UnRvdGdLcVlZSFBNb1lFSjAwRzYtQmJMRlI4eWN3aXVTUkVpNGdtejQydUdHNUwtZ0V2Vk1ScFpQamM5V0tDNk9RRmdSamhMVEszZV9HNFg4dldVWEx4UQ?oc=5) — google_news
[30] [United States Fed Funds Interest Rate - Trading Economics](https://tradingeconomics.com/united-states/interest-rate) — perplexity
[31] [Minutes of the Federal Open Market Committee](https://www.federalreserve.gov/monetarypolicy/fomcminutes20260429.htm) — perplexity
[32] [Background](https://www.clevelandfed.org/indicators-and-data/simple-monetary-policy-rules) — perplexity
[33] [What is the relationship between inflation, interest rates, and ...](https://equitablegrowth.org/what-is-the-relationship-between-inflation-interest-rates-and-economic-growth-and-what-does-it-mean-for-the-new-federal-reserve-chair/) — perplexity
[34] [5-Year, 5-Year Forward Inflation Expectation Rate (T5YIFRM) - FRED](https://fred.stlouisfed.org/series/T5YIFRM) — perplexity
[35] [Kiplinger Int. Rates Outlook: Long Rates Up while War Lasts | Kiplinger](https://www.kiplinger.com/economic-forecasts/interest-rates) — tavily
[36] [Mortgage Rates Forecast 2026: Expert Predictions & Outlook - Forbes](https://www.forbes.com/advisor/mortgages/mortgage-interest-rates-forecast) — tavily
[37] [Federal Reserve Board - H.15 - Selected Interest Rates (Daily) - June 11, 2026](https://www.federalreserve.gov/releases/h15/) — brave
[38] [10-year Treasury yield is steady even after data showing highest inflation since 2023](https://cnbc.com/amp/2026/06/10/us-treasury-yields-inflation-data.html) — brave
[39] [Inflation Keeps Prospects of a Fed Rate Cut Low - The New York Times](https://nytimes.com/2026/06/10/business/economy/inflation-federal-reserve-interest-rates.html) — brave
[40] [Mortgage Rates Forecast for Next 90 Days: May to July 2026](https://www.noradarealestate.com/blog/mortgage-rates-forecast-next-90-days-may-to-july-2026/) — brave
[41] [CPI Surges to 4.2%, Repricing Fed Funds to Holds, Not Cuts](https://www.interactivecrypto.com/cpi-surges-to-4-2-repricing-fed-funds-to-holds-not-cuts-jun-2026) — brave
[42] [Rate hikes are back on the table amid rising prices, Fed officials say—here's what it means for your money](https://cnbc.com/2026/06/10/interest-rates-may-stay-higherwhat-it-means-for-your-money.html) — brave
[43] [Federal Reserve to Resist the Urge to Hike US Rates | Investing.com](https://investing.com/analysis/federal-reserve-to-resist-the-urge-to-hike-us-rates-200681969) — brave
[44] [The Fed's Independence Problem: What It Means For Rates, Inflation, And Market Confidence](https://www.forbes.com/sites/jasonkirsch/2026/06/10/the-feds-independence-problem-what-it-means-for-rates-inflation-and-market-confidence/) — brave
[45] [USD Forecast 2026: Dollar Outlook for the Next 6 Months](https://cambridgecurrencies.com/usd-forecast-2026/) — brave
[46] [Why the Fed Is Unlikely to Cut Rates This Year | Goldman Sachs](https://www.goldmansachs.com/insights/articles/why-the-fed-is-unlikely-to-cut-rates-this-year) — exa
[47] [SF FedViews: Uncertainty Clouds the Outlook on Inflation and the Economy - San Francisco Fed](https://www.frbsf.org/research-and-insights/publications/fedviews/2026/06/sf-fedviews-june-4-2026/) — exa
[48] [Fed to hold rates this year, cut calls fade as war inflation persists, economists say | MarketScreener](https://www.marketscreener.com/news/fed-to-hold-rates-this-year-cut-calls-fade-as-war-inflation-persists-economists-say-ce7f5dd3d088ff26) — exa
[49] [Macro Signposts | Supply Shocks and AI-Related Demand Blur Inflation Signals for the Fed | PIMCO](https://cmqa.pimco.com/dk/en/insights/supply-shocks-and-ai-related-demand-blur-inflation-signals-for-the-fed) — exa
[50] [U.S. Fed to avoid cutting rates this year; economists still say war-driven inflation is transitory | MarketScreener](https://www.marketscreener.com/news/u-s-fed-to-avoid-cutting-rates-this-year-economists-still-say-war-driven-inflation-is-transitory-ce7f5adbdf8ef323) — exa
[51] [Hot May inflation reading reinforces Fed's path to hold interest rates next week](https://uk.finance.yahoo.com/news/hot-may-inflation-reading-reinforces-feds-path-to-hold-interest-rates-next-week-130456665.html) — exa
[52] [The Federal Reserve's June Inflation Forecast Is In, and It's Not Nightmare Fuel for Wall Street for the First Time in Several Months | The Motley Fool](https://www.fool.com/investing/2026/06/08/fed-june-inflation-forecast-nightmare-fuel-wall-st/) — exa
[53] [Hot CPI Resets Fed Rate-Cut Bets Ahead of Warsh Meeting - TheStreet](https://www.thestreet.com/fed/hot-may-cpi-sticks-a-pin-in-fed-rate-cut-bets) — exa
[54] [Macro Signposts | Supply Shocks and AI-Related Demand Blur Inflation Signals for the Fed | PIMCO](https://www.pimco.com/us/en/insights/supply-shocks-and-ai-related-demand-blur-inflation-signals-for-the-fed) — exa
[55] [United States Economic Outlook](https://lsa.umich.edu/content/dam/econ-assets/Econdocs/RSQE%20PDFs/RSQE_May26_US_Forecast.pdf) — exa
[56] [Here's the inflation breakdown for May 2026 — in one chart](https://www.cnbc.com/2026/06/10/heres-the-inflation-breakdown-for-may-2026-in-one-chart.html) — exa
[57] [Will Interest Rates Go Down in June? | Predictions 2026](https://themortgagereports.com/32667/mortgage-rates-forecast-fha-va-usda-conventional) — serper
[58] [Federal Reserve keeps interest rates steady as inflation uncertainty rises](https://www.usbank.com/investing/financial-perspectives/market-news/federal-reserve-interest-rate.html) — serper
[59] [US Core PCE Inflation Expected to Accelerate as Price Pressures Intensify](https://cryptorank.io/news/feed/6f10f-us-core-pce-inflation-expected-accelerate) — serper
[60] [US Economic Forecast Q1 2026](https://www.deloitte.com/us/en/insights/topics/economy/us-economic-forecast/united-states-outlook-analysis.html) — serper
[61] [As US Fed Holds Steady, Oil Spike Has 2026 Rate Cut Expectations Shrinking Fast](https://global.morningstar.com/en-nd/economy/us-fed-holds-steady-oil-spike-has-2026-rate-cut-expectations-shrinking-fast) — serper
[62] [March 2026 Fed Dot Plot: Why Cash Yields Are Dropping](https://www.bondsavvy.com/fixed-income-investments-blog/fed-dot-plot) — serper
[63] [Federal Reserve Monetary Policy](https://www.usbank.com/investing/financial-perspectives/market-news/federal-reserve-tapering-asset-purchases.html) — serper
[64] [Will the Fed Cut Interest Rates in June 2026? Expert Analysis](https://intellectia.ai/blog/will-fed-cut-interest-rate-june-2026) — serper
[65] [What the Fed’s divided 2026 outlook means for Bitcoin and crypto](https://www.tradingview.com/news/cointelegraph:306a4aac2094b:0-what-the-fed-s-divided-2026-outlook-means-for-bitcoin-and-crypto/) — serper
[66] [European Central Bank 2026 Monetary Policy Outlook And Euro Exchange Rate 2026 Trend How?](https://www.tradingkey.com/analysis/forex/jpy/251427083-eur-ecb-rates-tradingkey) — serper