# Portfolio Rationalization & Optimization Framework

**Version:** 1.1 (review-updated 2026-06-14)  
**Created:** 2026-06-13  
**Status:** Implementation complete — live in Windmill  
**Related roadmap section:** Part 3, Analytics & Research Stack  
**Critical review:** 8 findings incorporated from "Review — Roadmap & Portfolio Rationalization Framework 2026-06-14"

---

## Purpose

The portfolio holds ~33 positions (~31 unique companies after ADR pair consolidation). The goal is to rationalise this to approximately 15 high-conviction positions. This document defines the analytical and computational framework that will score, rank, and evaluate each position across quantitative and qualitative dimensions under multiple weighting philosophies, so that the rationalization decision is data-driven rather than impressionistic.

This is a **monthly deep-analysis framework** — not a brief portfolio email. The output is a comprehensive investment document equivalent to a full portfolio review memo.

---

## Portfolio Universe

**33 tickers → 31 unique companies** (after consolidating 2 ADR/HK pairs):

| ADR | HK Listing | Consolidated Name |
|---|---|---|
| BABA | 9988.HK | Alibaba Group |
| BIDU | 9888.HK | Baidu Inc |

All other tickers scored individually. For each ADR pair, position values are summed. *(Finding 3 — ADR market data rule):* **Fundamentals** (ROE, margins, growth, leverage) are merged — same company, same numbers. **Market data** (valuation multiples, momentum, short interest, analyst coverage) is sourced from the listing that would actually be held — the ADR (BABA, BIDU) by default; the HK listing data is used if Section E designates the HK share as the keep. Not the ticker with more DB rows.

---

## Report Structure

Output: one comprehensive HTML/Markdown document per month. Target 15,000–20,000 words. Delivered by email and saved to `/root/research/portfolio/rationalization_YYYY-MM-DD.md`.

### Section A — Executive Summary

- Portfolio health snapshot: composite scores, sector/geographic breakdown  
- **Consistent KEEPs**: positions recommended to keep in ≥3 of 4 weighting scenarios  
- **Contentious positions**: ranking shifts materially between scenarios — flag for discussion  
- **Clear EXITs**: bottom-ranked in ≥3 of 4 scenarios  
- ADR pair consolidation decisions (which listing to keep)  
- Final recommended 15 with brief rationale each

### Section B — Multi-Scenario Ranking Matrix

Four weighting philosophies applied simultaneously. The goal is to identify which positions are robustly strong (top-ranked across all scenarios) vs. style-dependent (strong only under one weighting philosophy).

| Scenario | Quality | Growth | Valuation | Sentiment | Thesis |
|---|---|---|---|---|---|
| 1. Balanced | 25% | 25% | 20% | 15% | 15% |
| 2. Quality-focused | 35% | 25% | 20% | 10% | 10% |
| 3. Growth-focused | 20% | 35% | 25% | 10% | 10% |
| 4. Value-focused | 20% | 20% | 35% | 15% | 10% |

Table columns: Rank (Scenario 1–4), Composite score (each scenario), # scenarios KEEP, **Δ rank vs prior month** *(Finding 8)*, **Data completeness %** *(Finding 2)*, Red flags count. Sorted by Balanced composite by default.

### Section C — Per-Position Deep Scorecard (~31 entries)

For each position in the portfolio:

#### C1. Quantitative Metrics Panel *(Python-computed from DB — no LLM, fully auditable)*

**Valuation**
- Forward P/E, Trailing P/E, PEG ratio
- EV/EBITDA, EV/Revenue, P/FCF, P/B
- Analyst mean target price (USD), current price, analyst upside %
- Analyst recommendation mean (1=Strong Buy, 5=Sell), analyst count

**Quality**
- ROE (DuPont decomposition: net margin × asset turnover × equity multiplier)
- ROIC (US tickers, from Finnhub)
- Net margin (latest year), Gross margin
- Net debt / EBITDA, Gearing (D/(D+E)), Current ratio
- FCF quality (operating CF / net income)

**Growth**
- Revenue CAGR (1yr, 3yr — computed from `income_statements`)
- Net income CAGR (3yr)
- EPS CAGR (3yr)
- Margin trend: expanding / flat / contracting (net margin year-on-year)

**Momentum & Sentiment**
- Analyst recommendation mean + count
- Average EPS surprise (4 most recent quarters from `earnings_surprises`)
- Short interest % of float
- Beta
- 52-week momentum: (current price − 52wk low) / (52wk high − 52wk low)

**Ownership**
- Insider ownership %
- Institutional ownership %
- Net insider buy/sell value last 90 days (from `insider_transactions`)

#### C2. Factor Score Breakdown *(percentile ranks 0–100 within portfolio)*

Five factor scores (completeness-penalized composite), rank in each of 4 scenarios, Δ vs prior month rank. *(Finding 1):* **Absolute red flags** shown explicitly above the metrics panel when triggered — these are independent of percentile ranking and visible to Grok. *(Finding 2):* Completeness % shown in section header.

#### C3. Qualitative Analysis *(Grok-4.3 generated — 4 sentences per position)*

1. **Quantitative assessment**: what the numbers show — strongest metric, weakest metric
2. **Qualitative assessment**: thesis strength, most important catalyst vs. most important risk
3. **Portfolio fit**: why keep vs. trim vs. exit relative to the other positions
4. **Recommendation**: KEEP / TRIM / EXIT + concise rationale

#### C3. Qualitative Analysis *(Grok Call 1 — 4 sentences per position)*

Quantitative assessment, qualitative thesis, portfolio fit, recommendation. *(Finding 1):* Red flags explicitly referenced. *(Finding 2):* Data uncertainty noted if completeness < 60%.

#### C4. Investment Thesis *(from `portfolio_thesis` table)*

Conviction level (High/Medium/Low), key catalysts, key risks, target price (USD), last updated date. Displayed as sourced — not rewritten by the LLM. *(Finding 4):* **Staleness flag** displayed if thesis > 90 days old — "thesis not reviewed in N days — consider updating" — but staleness is NOT a score multiplier.

### Section D — Portfolio Construction Analysis

- Sector distribution: current vs. post-rationalization (pie/table)
- Geographic exposure: US / China / Europe / Other
- Market cap skew: mega (>$200B) / large ($10–200B) / mid/small (<$10B)
- Concentration risk: top 5 positions as % of total portfolio
- Suggested sizing principles for the recommended 15 (equal weight, conviction-tiered, etc.)

### Section E — Exit / Trim Action Plan

- EXIT candidates ordered by conviction-to-exit (strongest exits first)
- TRIM candidates with suggested reduction rationale
- ADR pair decisions: which listing to keep and why (liquidity, tax efficiency, discount/premium to NAV)
- Note: no trade execution logic — decision support only

---

## Scoring Methodology

All scores are computed in Python from the PostgreSQL database. No LLM is involved in score computation — Grok is used only for narrative synthesis (Section C3 and Executive Summary).

### Data Sources (per position)

| Source Table | Data Used |
|---|---|
| `portfolio_positions` + `price_history` + `fx_rates` | Position USD value, portfolio weight % |
| `fundamental_data` (latest row) | PE, PB, EV/EBITDA, revenue_growth_yoy, net_margin, debt_equity, ROE, ROIC |
| `valuation_snapshots` (latest) | Forward PE, PEG, analyst target, analyst_rec_mean, analyst_count, short_pct_float, 52wk high/low, beta |
| `income_statements` (3yr annual) | Revenue, net income, EPS — for CAGR computation |
| `financial_health_metrics` (latest) | Net debt/EBITDA, gearing, current ratio, DuPont ROE components |
| `cashflow_statements` (latest) | Operating CF, FCF — for FCF quality ratio |
| `earnings_surprises` (4 most recent) | Average EPS surprise % |
| `insider_transactions` (last 90 days) | Net buy/sell value (positive = net buying) |
| `portfolio_thesis` | Conviction level, updated_at (staleness display flag only — not score input) |

### Factor Formulas

All raw scores in 0–1 range, then converted to 0–100 percentile rank within the 31-company pool.

#### Quality Score (raw)
```
Q = 0.35 × ROE_norm
  + 0.25 × net_margin_norm
  + 0.25 × (1 − net_debt_ebitda_norm)
  + 0.15 × fcf_quality_norm

where:
  ROE_norm            = ROE percentile within portfolio; use DuPont ROE for HK names
  net_margin_norm     = net margin percentile within portfolio
  net_debt_ebitda_norm = clip(net_debt_ebitda, -3, 8), normalize to 0–1 (lower = better)
  fcf_quality_norm    = clip(operating_cf / net_income, 0, 2) / 2
```

#### Growth Score (raw)
```
G = 0.40 × rev_cagr_3yr_norm
  + 0.40 × ni_cagr_3yr_norm
  + 0.20 × rev_cagr_1yr_norm

where CAGRs are computed from 3 annual income_statements rows:
  rev_cagr_3yr  = (revenue_t0 / revenue_t-3)^(1/3) − 1
  ni_cagr_3yr   = (net_income_t0 / net_income_t-3)^(1/3) − 1 (sign-aware)
  rev_cagr_1yr  = revenue_t0 / revenue_t-1 − 1
```
Negative CAGR is valid and will rank below median. Missing data → excluded from percentile pool.

#### Valuation Score (raw)
```
V = 0.35 × analyst_upside_norm
  + 0.30 × (1 − fwd_pe_norm)
  + 0.20 × (1 − peg_norm)
  + 0.15 × (1 − ev_ebitda_norm)

where:
  analyst_upside = (analyst_target − current_price) / current_price
                   clipped to [−50%, +100%] before normalization
  fwd_pe_norm    = forward P/E percentile within portfolio (lower PE = higher score)
  peg_norm       = PEG percentile within portfolio (lower PEG = higher score)
  ev_ebitda_norm = EV/EBITDA percentile (lower = higher score)
```
Each sub-component excluded independently if data missing.

#### Sentiment Score (raw)
```
S = 0.35 × analyst_quality_norm
  + 0.35 × eps_beat_norm
  + 0.20 × momentum_norm
  + 0.10 × insider_norm

where:
  analyst_quality = (6 − analyst_rec_mean) / 5
                    × log(1 + analyst_count) / log(1 + max_analyst_count)
                    (credibility-weighted: more analysts = higher weight)
  eps_beat        = avg EPS surprise %, clipped to [−30%, +30%]
  momentum        = (current_price − price_52wk_low) / (price_52wk_high − price_52wk_low)
  insider_net     = net_buy_value (90d) / max_abs_insider_value in portfolio
                    (0 if no recent activity; positive = net buying)
```

#### Thesis Score (raw) *(Finding 4 — freshness decay REMOVED)*
```
T = conviction_raw

where:
  conviction_raw: High=1.0, Medium=0.6, Low=0.2, absent=0.0

Staleness (>90 days) → display flag in C4 only; NOT a score multiplier.
Rationale: freshness_decay penalised stable, well-researched holdings that simply didn't need
updating, pushing them toward EXIT. Conviction is the right signal; staleness is a prompt to review.
```

### Absolute Red Flags *(Finding 1)*

Computed independently of percentile ranking. Five threshold checks:
- Net debt / EBITDA > 4.0 → "Leverage: net debt/EBITDA = X (above 4.0)"
- Revenue CAGR 3yr < 0% → "Declining revenue: 3yr CAGR = X%"
- Forward P/E > 60× (or absent) → "Rich/unknown valuation: fwd PE = X"
- Net income CAGR 3yr < −20% → "Earnings deterioration: 3yr NI CAGR = X%"
- Current ratio < 0.8 → "Liquidity risk: current ratio = X"

Flags appear in Section C above the metrics panel and are passed explicitly to Grok. They give an absolute reference that percentile ranking alone cannot provide.

### Percentile Ranking *(Finding 2 — revised)*

**Minimum pool size:** A factor is only admitted to the composite if ≥8 positions have non-null data for it. Below 8, the factor is excluded from all composites and flagged in the report footer.

**Completeness penalty:** After computing the weighted-average composite, multiply by coverage ratio:
```
composite_penalized = composite_raw × (n_available_factors / n_total_factors)
```
This ensures a position scored on 3 of 5 factors cannot exceed 60% of a fully-covered peer. Prevents HK/China names with thinner Finnhub coverage from gaming the rankings by having their weak factors excluded.

**Data completeness %:** `n_factors_with_data / 5 × 100`. Stored in `portfolio_scores.data_completeness_pct`.

### Composite Score per Scenario *(Finding 2 — updated)*
```
composite_raw = Σ (weight_factor × percentile_factor) / Σ (weight_factor for available factors)
composite_penalized = composite_raw × (n_available / n_total)
```

### Delta Tracking *(Finding 8)*
Before computing current scores, query prior `portfolio_scores` for the most recent `score_date`:
```sql
SELECT ticker, rank_balanced FROM portfolio_scores
WHERE score_date = (SELECT MAX(score_date) FROM portfolio_scores WHERE score_date < CURRENT_DATE)
```
`delta_rank = current_rank_balanced − prior_rank_balanced` (negative = rising). NULL if first run (shown as "–").

---

## Grok-4.3 Synthesis — Two Sequential Calls *(Finding 5)*

*Per Hard Rule 10 — exact prompt text approved before coding. Single call cannot produce 15,000–20,000 words within max_tokens=8000 (~6,000 words). Split into two calls.*

### Call 1 — Per-Position Analysis (31 blocks)

```
You are a senior portfolio manager conducting a monthly rationalization review of a concentrated equity portfolio.
Evaluate {N} positions (including 2 consolidated ADR pairs: Alibaba=BABA+9988.HK, Baidu=BIDU+9888.HK).
Target: approximately 15 final positions. The reader is a finance professional — be analytical and specific, not educational.

IMPORTANT: Positions marked [RED FLAG] carry absolute concerns independent of their relative rank within this portfolio.
These are hard negatives — do not let a high percentile score override a flagged absolute metric.

Positions with data completeness below 60% carry higher uncertainty — name the missing factors and adjust your confidence accordingly.

== SCORING CONTEXT ==
Quantitative factor scores (0–100 percentile rank, completeness-penalized) computed from financial databases.
Four scenarios: Balanced / Quality-focused / Growth-focused / Value-focused.
Data completeness % and Δ rank vs prior month are shown per position.

{MULTI_SCENARIO_RANKING_TABLE}

== PER-POSITION DATA ==
{PER_POSITION_BLOCKS}
Each block format:
[TICKER | Company | Sector | Country | USD Value | Weight % | Completeness: X% | Δ rank: ±N or —]
[RED FLAGS: list if any]
Valuation: fwd PE, PEG, EV/EBITDA, analyst upside, analyst rec (1=Strong Buy), analyst count
Quality: ROE, ROIC, net margin, net debt/EBITDA, current ratio
Growth: revenue CAGR 1yr/3yr, net income CAGR 3yr, EPS CAGR
Sentiment: avg EPS surprise (4Q), short interest %, 52wk momentum
Ownership: insider %, institutional %, net insider activity 90d
Thesis: conviction=[High/Medium/Low/none], catalysts=[...], risks=[...]

== YOUR OUTPUT ==
For EACH position (no skipping, no merging):

**[TICKER] — [Company Name]**
Quantitative: [2 sentences — strongest metric, weakest metric; reference any red flags explicitly]
Qualitative: [2 sentences — thesis strength, key catalyst vs. key risk]
Recommendation: KEEP / TRIM / EXIT
Rationale: [2-3 sentences — opportunity cost relative to other positions; note data uncertainty if completeness < 60%]
```

### Call 2 — Executive Summary + Portfolio Construction

*(Receives Call 1 output as input)*

```
You have just completed per-position analysis of {N} portfolio positions for monthly rationalization.
Below are the position verdicts. Generate the executive summary, portfolio construction assessment, and month-over-month commentary.

== POSITION VERDICTS ==
{CALL_1_OUTPUT}

== PRIOR MONTH DELTA CONTEXT ==
{DELTA_SUMMARY}

== YOUR OUTPUT ==

== EXECUTIVE SUMMARY ==
**Consistent KEEPs** (≥3 of 4 scenarios AND your KEEP verdict): [bulleted, one-line reason each]
**Scenario-Sensitive Positions** (rank shifts >10 places between scenarios): [what drives the sensitivity]
**Trim Candidates**: [list, one-line reason each]
**Exit Candidates**: [list, one-line reason each]
**ADR Pair Decisions**: BABA vs 9988.HK — [which to keep and why]; BIDU vs 9888.HK — [which to keep and why]

== PORTFOLIO CONSTRUCTION (post-rationalization) ==
[4-5 sentences: sector balance, geographic balance, market cap distribution, concentration risk, sizing principle for the 15]

== MONTH-OVER-MONTH ==
[2-3 sentences: most notable rank changes and what they suggest about trajectory; or first-run note]
```

### Fallback *(Finding 7)*

Both calls use `_call_grok_with_fallback()` — primary: Grok-4.3, fallback: `deepseek-chat`. If fallback fires, report footer shows: `⚠️ Grok unavailable for [call name] — synthesised with deepseek-chat`.

---

## Implementation Plan

### New Files

| File | Purpose |
|---|---|
| `windmill/u/admin/portfolio_rationalization.py` | Main Windmill script |
| `windmill/u/admin/portfolio_rationalization.script.yaml` | Windmill metadata |
| `agent/tools.py` | Add `portfolio_rationalize` tool definition |
| `agent/classifier.py` (or equivalent) | Add `portfolio_rationalize` intent |

### Schema Addition

New table added to `portfolio` DB (migration via `docker exec` psql):

```sql
CREATE TABLE IF NOT EXISTS portfolio_scores (
    id SERIAL PRIMARY KEY,
    score_date DATE DEFAULT CURRENT_DATE,
    ticker TEXT,
    consolidated_name TEXT,
    quality_score NUMERIC(5,1),
    growth_score NUMERIC(5,1),
    valuation_score NUMERIC(5,1),
    sentiment_score NUMERIC(5,1),
    thesis_score NUMERIC(5,1),
    composite_score_balanced NUMERIC(5,1),
    composite_score_quality NUMERIC(5,1),
    composite_score_growth NUMERIC(5,1),
    composite_score_value NUMERIC(5,1),
    data_completeness_pct NUMERIC(5,1),   -- % of 5 factors with data (Finding 2)
    red_flag_count INT DEFAULT 0,          -- absolute threshold breaches (Finding 1)
    position_usd NUMERIC(14,2),
    portfolio_pct NUMERIC(6,3),
    recommendation TEXT,
    rank_balanced INT,
    rank_quality INT,
    rank_growth INT,
    rank_value INT,
    delta_rank_balanced INT,               -- rank change vs prior month, NULL if first run (Finding 8)
    UNIQUE (score_date, ticker)
);
```
*Applied — table exists in portfolio DB as of 2026-06-14.*

### Script Execution Flow (`portfolio_rationalization.py`)

1. **Position sizing**: query `portfolio_positions` + latest `price_history` + `fx_rates` → USD value per position + portfolio weights
2. **ADR consolidation**: merge BABA+9988.HK and BIDU+9888.HK into single scored entities; market data sourced from listing to be held
3. **Data pull**: fundamentals, earnings surprises, insider transactions, thesis from all tables
4. **Factor computation**: 5 factors, Python-only, no LLM (see formulas above)
5. **Absolute red-flag evaluation**: 5 threshold checks per position (Finding 1)
6. **Percentile ranking**: min pool size ≥8 guard; completeness penalty applied to all 4 scenario composites (Finding 2)
7. **Delta tracking**: query prior portfolio_scores for rank_balanced (Finding 8)
8. **Grok Call 1**: per-position analysis (31 blocks) — Grok-4.3 with deepseek-chat fallback (Finding 5, 7)
9. **Grok Call 2**: executive summary + portfolio construction + MoM commentary (Finding 5)
10. **Report assembly**: Python string building — insert quantitative tables + Grok narrative
11. **Delivery**: email to `<YOUR_RECIPIENT_EMAIL>` + save to `/root/research/portfolio/rationalization_YYYY-MM-DD.md` + upsert portfolio_scores

### Agent Tool (`portfolio_rationalize`)

- **FAST path**: if latest rationalization file exists and is ≤30 days old → read file → return compact ranked table via Telegram
- **ASYNC path**: if stale/absent → dispatch Windmill job → "Analysis running — full report will be emailed"
- Telegram output: compact ranked table (rank, ticker, score, recommendation) + "Full report emailed"

### TDD Requirements (per Hard Rule 15)

Tests written FIRST, confirmed RED, then implementation:

**`agent/tests/test_windmill_scripts.py`** — 11 tests (5 original + 6 from review findings):
- `test_rationalization_script_exists` — file at `windmill/u/admin/portfolio_rationalization.py`
- `test_rationalization_has_adr_consolidation` — source contains BABA/9988.HK and BIDU/9888.HK merge
- `test_rationalization_has_four_scenarios` — source contains all 4 weighting scenario dicts
- `test_rationalization_has_portfolio_scores_write` — source writes to `portfolio_scores` table
- `test_rationalization_grok_prompt_neutral` — Grok prompt does not contain "infrastructure" or "banker"
- `test_rationalization_has_absolute_thresholds` — red-flag threshold constants present (Finding 1)
- `test_rationalization_has_completeness_penalty` — composite × coverage ratio present (Finding 2)
- `test_rationalization_min_pool_size_enforced` — min pool size ≥8 guard present (Finding 2)
- `test_rationalization_thesis_no_freshness_multiplier` — "freshness_decay" absent (Finding 4)
- `test_rationalization_two_grok_calls` — ≥2 Grok call sites present (Finding 5)
- `test_rationalization_has_grok_fallback` — deepseek-chat fallback present (Finding 7)
- `test_rationalization_has_delta_query` — prior score_date query present (Finding 8)

**`agent/tests/test_classifier.py`:**
- `test_portfolio_rationalize_intent` — "rationalize portfolio" → `portfolio_rationalize` intent

**Total after implementation: 272 tests passing** (259 prior + 12 new + 1 additional during implementation)

---

## Schedule

### Monthly automation (1st of each month)

Two Windmill cron jobs, sequenced:

| Job | Cron (SGT) | What it does |
|---|---|---|
| Monthly data refresh | `0 0 19 1 * *` (7PM, 1st of month) | Re-run `stock_data_fetcher` for all 33 tickers to refresh all 14 research tables. Complements the weekly `fundamentals_fetcher`. |
| Monthly rationalization | `0 0 21 1 * *` (9PM, 1st of month) | Runs `portfolio_rationalization.py` — 2h after data refresh to allow all sub-jobs to settle. |

### On-demand access

- Windmill UI: trigger either script manually at any time
- Telegram: `/rationalize` or "rationalize portfolio" → returns compact summary table; triggers Windmill if no recent cache

---

## Output Location

```
/root/research/portfolio/rationalization_YYYY-MM-DD.md
```

Historical reports retained indefinitely. `portfolio_scores` table maintains per-run history for trend analysis.

---

## Dependencies

All Windmill resources must exist before the script runs:

| Resource | Path |
|---|---|
| Portfolio DB | `$res:u/admin/portfolio_db` |
| xAI/Grok API key | `$var:u/admin/xai_key` |
| Gmail SMTP | `$res:u/admin/gmail_smtp` |

No new resources required — all three already exist.

---

## Future Extensions (not in scope for v1)

- **Scenario customization via Telegram**: `/rationalize quality` triggers the quality-weighted scenario specifically
- **Thesis integration**: auto-trigger thesis_write prompt for any position rated EXIT, so the decision can be logged
- **Beefed-up weekly portfolio review**: incorporate composite scores from `portfolio_scores` as a lighter weekly touchpoint, showing score trends vs. prior month
- **Position sizing optimizer**: given recommended 15 keeps, suggest target weights based on composite score rank and conviction level
