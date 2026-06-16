# Portfolio Candidate Evaluation Framework

**Version:** 1.0  
**Status:** Design approved — not yet implemented  
**Design date:** 2026-06-15  
**Proposal source:** [Portfolio Addition Evaluation Framework](https://claude.ai/public/artifacts/61fb73b8-0cd8-45e0-8b7a-a80a55c087ef)

---

## Purpose

The Portfolio Rationalization Framework (`portfolio_rationalization.py`) decides which of the *current 31 positions* to KEEP/TRIM/EXIT. This framework addresses the complementary decision: whether to ADD a *new candidate stock* to the portfolio.

The two frameworks are designed as a pair:
- **Rationalization** (existing): "Which of what I own do I keep?"
- **Candidate Evaluation** (this doc): "Should I buy this new name?"

---

## Architecture: Three Gates

Each candidate is evaluated through three independent gates. A gate breach does not automatically terminate evaluation — all three gates run regardless, and the verdict reflects their combined output.

### Gate 1 — Absolute Check

Hard thresholds that identify unacceptable risk, independent of how the candidate ranks relative to peers or the portfolio.

| Condition | Threshold | Flag text |
|---|---|---|
| Net debt / EBITDA | > 4.0× | "Leverage: net debt/EBITDA = X" |
| Current ratio | < 0.8 | "Liquidity risk: current ratio = X" |
| Forward P/E | > 60× or absent | "Rich valuation: fwd PE = X" |
| Revenue CAGR (3yr) | < 0% | "Declining revenue: 3yr CAGR = X%" |
| Net income CAGR (3yr) | < −20% | "Earnings deterioration: 3yr NI CAGR = X%" |

**Same thresholds as `_evaluate_red_flags()` in `portfolio_rationalization.py`.** No new logic needed.

Gate 1 output: `gate1_status = "ok" | "breach"` + list of flag strings.

### Gate 2 — Portfolio Fit

Evaluates the *marginal* value of adding this candidate given the current portfolio composition. A great business that adds concentration or duplicates existing factor exposure may still receive WATCH or PASS.

**Sub-checks:**

| Sub-check | Data source | Output |
|---|---|---|
| Price correlation | Candidate 90-day returns (yfinance) vs. `price_history` for 31 positions | `max_corr` (0–1), `closest_existing` ticker |
| Sector concentration | `company_profiles` for existing 31 vs. candidate sector | `sector_match_count` |
| Country concentration | `company_profiles` for existing 31 vs. candidate country | `country_match_count` |
| Factor gap fill | `portfolio_scores` pool averages; which factors below median; does candidate score >P60 there | `gap_factors`, `fill_factors` |
| Sizing headroom | `portfolio_scores.position_usd` distribution | `smallest_pct`, `median_pct`, `largest_pct` |

Gate 2 output: structured dict passed to Grok for qualitative interpretation. No pass/fail binary — Grok reads the signals.

### Gate 3 — Universe Benchmark

Scores the candidate against a named peer set to determine whether it is the best available vehicle for the intended exposure.

**Universe construction:** Populated from the `peer_comparisons` table (fetched by `stock_data_fetcher.py` when data is pulled for the candidate). User may optionally supply an explicit `universe_tickers` list to override.

**Thin universe flag:** If `peer_comparisons` returns fewer than 5 peers, `thin_universe = True` is surfaced in the verdict card and passed to Grok. `min_pool = 3` (not 8, unlike portfolio rationalization).

**Per-factor universe scoring:** Same `_norm()` function used in rationalization, applied to the peer pool rather than the 31-position portfolio pool.

Gate 3 output: per-factor universe percentile ranks (quality, growth, valuation); `thin_universe` flag.

---

## Per-Factor Triplet

Instead of collapsing each factor to a single composite, the evaluation produces a **triplet** per factor:

```
{
  "absolute":     "ok" | "breach",   ← Gate 1
  "portfolio_pct": 0–100,            ← Gate 2: percentile vs. current 31
  "universe_pct":  0–100             ← Gate 3: percentile vs. peer set
}
```

This preserves decision-relevant nuance. A candidate can rank P90 vs. peers (universe_pct=90) but only P40 vs. the existing portfolio (portfolio_pct=40) — signalling the portfolio is already strong in that factor.

Factors: quality, growth, valuation, sentiment. Thesis is excluded from the composite for candidates (no `portfolio_thesis` row exists); Grok generates it inline or accepts user-supplied text.

---

## Verdict Card

**Three verdicts:**

| Verdict | Meaning |
|---|---|
| **ADD** | Clears all gates; additive to portfolio and best available vs. universe |
| **WATCH** | Clears absolute gate; strong on universe rank; blocked by a *mutable* portfolio constraint (e.g., sector already heavy) |
| **PASS** | Fails absolute gate OR decisively beaten on universe gate by an existing/alternative holding |

**Binding constraint line:** One sentence identifying the single factor or condition that, if changed, would flip the verdict. This is the most actionable element of the card — it defines the re-evaluation trigger.

---

## Grok Prompt (approved)

Single synthesis call, `max_tokens=3000`, model: Grok-4.3 with deepseek-chat fallback.

```
SYSTEM: You are a quantitative portfolio analyst producing a structured verdict card for a stock being evaluated for portfolio addition. Be analytical and specific. Finance-professional tone — no educational framing.

USER:
== CANDIDATE EVALUATION ==
Candidate: {ticker} ({company_name}) | Sector: {sector} | Country: {country}
Date: {date}

== GATE 1 — ABSOLUTE CHECK ==
Red flags: {red_flags or "None"}
Gate 1 status: {BREACH | OK}

== GATE 2 — PORTFOLIO FIT ==
Max correlation to existing positions: {max_corr:.2f} (closest match: {closest_existing})
Sector overlap: {sector_match_count} existing positions in same sector
Country overlap: {country_match_count} existing positions in same country
Portfolio factor gaps (below median): {gap_factors}
Candidate fills gap in: {fill_factors}
Sizing headroom: Smallest existing position {smallest_pct:.1f}%, median {median_pct:.1f}%

== GATE 3 — UNIVERSE BENCHMARK ==
Universe: {universe_tickers} ({universe_size} peers{", THIN UNIVERSE — treat with lower confidence" if thin_universe else ""})
Candidate vs universe — Quality: {q_uni}th pct | Growth: {g_uni}th pct | Valuation: {v_uni}th pct

== PER-FACTOR TRIPLETS ==
Quality:   absolute={abs_q}, vs portfolio={portfolio_q}th pct, vs universe={q_uni}th pct
Growth:    absolute={abs_g}, vs portfolio={portfolio_g}th pct, vs universe={g_uni}th pct
Valuation: absolute={abs_v}, vs portfolio={portfolio_v}th pct, vs universe={v_uni}th pct
Sentiment: absolute={abs_s}, vs portfolio={portfolio_s}th pct, vs universe={s_uni}th pct

== KEY METRICS ==
fwd_pe, ev_ebitda, rev_cagr_3yr, ni_cagr_3yr, roe, net_margin, current_ratio, net_debt_ebitda

== THESIS ==
{thesis_text if user-supplied else "[derive from metrics and sector context]"}

== OUTPUT FORMAT (exact) ==

**VERDICT: [ADD | WATCH | PASS]**
**Binding constraint:** [One sentence: the single factor that, if changed, would flip this verdict]

**Gate summary:**
- Gate 1 (Absolute): [one sentence]
- Gate 2 (Portfolio fit): [one sentence on correlation + concentration + gap fill]
- Gate 3 (Universe): [one sentence on peer ranking]

**Sizing recommendation (ADD/WATCH only):** [Suggested weight %; skip for PASS]

**Watch items:** [2-3 bullet points on what to monitor]
```

---

## Scoring Methodology

### Data Sources (all pre-existing)

Same tables used by `portfolio_rationalization.py` and `stock_data_fetcher.py`:

| Data | Source |
|---|---|
| Fundamentals | `valuation_snapshots`, `fundamental_data`, `financial_health_metrics`, `income_statements`, `cashflow_statements`, `earnings_surprises`, `ownership_snapshots`, `insider_transactions` |
| Company profile | `company_profiles` |
| Portfolio baseline | `portfolio_scores` (most recent score_date) |
| Price history | `price_history` (existing 31 positions) |
| Peer universe | `peer_comparisons` |
| Candidate data | `stock_data_fetcher.py` dispatched if data absent or stale (>3 days) |

### Factor Formulas

Same formulas as `portfolio_rationalization.py` — copied verbatim into the new script (Windmill scripts are standalone; no cross-script imports).

**Quality** = 0.35×ROE + 0.25×net_margin + 0.25×(1 − net_debt_ebitda_norm) + 0.15×fcf_quality

**Growth** = 0.4×rev_cagr_3yr + 0.4×ni_cagr_3yr + 0.2×rev_cagr_1yr

**Valuation** = 0.35×analyst_upside + 0.30×(1 − fwd_pe) + 0.20×(1 − peg) + 0.15×(1 − ev_ebitda)

**Sentiment** = 0.35×analyst_rec + 0.35×eps_beat + 0.20×momentum + 0.10×insider

**Portfolio-relative percentile:** `_norm()` applied against the 31-position `portfolio_scores` pool (pool size 31, well above minimum).

**Universe-relative percentile:** `_norm()` applied against `peer_comparisons` pool; `min_pool = 3`; `thin_universe = True` if fewer than 5 peers.

---

## DB Schema

New table — no existing tables modified:

```sql
CREATE TABLE IF NOT EXISTS portfolio_candidate_evals (
    id                  SERIAL PRIMARY KEY,
    eval_date           DATE NOT NULL DEFAULT CURRENT_DATE,
    ticker              TEXT NOT NULL,
    company_name        TEXT,
    red_flag_count      INT,
    red_flags           JSONB,
    gate1_status        TEXT,           -- 'ok' | 'breach'
    max_correlation     NUMERIC(5,3),
    closest_existing    TEXT,
    sector_match_count  INT,
    country_match_count INT,
    factor_gap_fills    JSONB,          -- list of factors candidate fills
    universe_tickers    JSONB,
    universe_size       INT,
    thin_universe       BOOLEAN,
    quality_triplet     JSONB,          -- {absolute, portfolio_pct, universe_pct}
    growth_triplet      JSONB,
    valuation_triplet   JSONB,
    sentiment_triplet   JSONB,
    portfolio_composite NUMERIC(5,1),
    universe_composite  NUMERIC(5,1),
    verdict             TEXT,           -- 'ADD' | 'WATCH' | 'PASS'
    binding_constraint  TEXT,
    synthesiser_model   TEXT,
    input_tokens        INT,
    output_tokens       INT,
    UNIQUE (eval_date, ticker)
);
```

---

## Implementation Plan

### Step 1 — TDD: Write Tests First (RED)

**`agent/tests/test_windmill_scripts.py`** — 11 structural tests:

| Test | Checks |
|---|---|
| `test_candidate_eval_script_exists` | File exists at `windmill/u/admin/portfolio_candidate_eval.py` |
| `test_candidate_eval_main_has_correct_params` | Required: ticker, portfolio_db, gmail_smtp, xai_key, deepseek_key; optional: universe_tickers=[], thesis_text="" |
| `test_candidate_eval_returns_verdict_dict` | Source contains `"verdict"` and `"binding_constraint"` |
| `test_evaluate_red_flags_reused` | `_evaluate_red_flags` present in source |
| `test_compute_correlation_function_exists` | `_compute_correlation` in source |
| `test_compute_sector_geo_overlap_function_exists` | `_compute_sector_geo_overlap` in source |
| `test_compute_factor_gap_function_exists` | `_compute_factor_gap` in source |
| `test_fetch_universe_function_exists` | `_fetch_universe` in source |
| `test_candidate_eval_writes_to_evals_table` | Source contains `portfolio_candidate_evals` |
| `test_candidate_eval_has_grok_fallback` | `deepseek` in source |
| `test_candidate_eval_thin_universe_flag` | Source contains `thin_universe` |

**`agent/tests/test_classifier.py`** — 2 intent tests:

| Test | Checks |
|---|---|
| `test_candidate_evaluation_intent` | `"candidate_evaluation"` in `SYSTEM_PROMPT` |
| `test_candidate_evaluation_shortcuts` | `"evaluate"` shortcut in prompt |

**Target test count after build: 272 + 13 = 285 passing**

### Step 2 — DB Migration

Apply DDL above via:
```bash
docker exec root-portfolio_postgres-1 psql -U portfolio_user -d portfolio -c "<DDL>"
```

### Step 3 — Windmill Script (`portfolio_candidate_eval.py`)

Implementation order — each function builds on the previous:

1. Copy helper functions from `portfolio_rationalization.py`: `_conn`, `_cagr`, `_norm`, `_evaluate_red_flags`, `_call_grok_with_fallback`
2. `_fetch_fundamentals_for_ticker(cur, ticker, price_map)` — single-ticker adaptation of `_fetch_fundamentals()`
3. `_ensure_data_fetched(ticker, wm_token, finnhub_key)` — dispatch `stock_data_fetcher` job; poll 120s max
4. `_compute_correlation(ticker, conn)` — yfinance 90d for candidate; `price_history` for existing 31; Pearson; return `{max_corr, closest_existing}`
5. `_compute_sector_geo_overlap(ticker, conn)` — count sector/country matches in `company_profiles`
6. `_compute_factor_gap(ticker, conn, candidate_scores)` — compare candidate vs. pool averages from `portfolio_scores`
7. `_compute_sizing_headroom(conn)` — `portfolio_scores` position weight distribution
8. `_fetch_universe(ticker, universe_tickers, conn)` — `peer_comparisons` or user list
9. `_score_in_universe(candidate_metrics, universe_metrics)` — `_norm()` with `min_pool=3`
10. `_assemble_prompt(...)` — build Grok prompt string
11. `main(ticker, portfolio_db, gmail_smtp, xai_key, deepseek_key, universe_tickers=[], thesis_text="", wm_token="", finnhub_key="")` — orchestrates all steps; DB write; email; return dict

`portfolio_candidate_eval.script.yaml` — clone from `portfolio_rationalization.script.yaml`; adjust schema.

### Step 4 — Agent Integration

**`agent/tools.py`** additions:
- `SCRIPT_CANDIDATE_EVAL = "u/admin/portfolio_candidate_eval"`
- `"candidate_evaluation": ASYNC_NOTIFY` in `TOOL_CLASSES`
- `dispatch_candidate_eval(args, phone)` — no file cache (always run fresh); dispatch with ticker + optional universe_tickers + thesis_text; follow `dispatch_earnings_analysis` pattern
- Register in `ASYNC_NOTIFY_EXECUTORS`

**`agent/classifier.py`** — add to `SYSTEM_PROMPT`:
```
- candidate_evaluation: {"ticker": "SYMBOL", "universe_tickers": ["optional"], "thesis_text": "optional"} — evaluate a stock as a portfolio addition candidate; 3-gate analysis (absolute + portfolio-fit + universe benchmark); produces ADD/WATCH/PASS verdict card with binding constraint
```
Shortcuts: `"evaluate TICKER"` / `"should I add TICKER"` / `"candidate TICKER"` → `candidate_evaluation`

### Step 5 — CLAUDE.md Update

- Add `candidate_evaluation` tool to Telegram Agent build status table
- Update test count: 272 → 285
- Add `portfolio_candidate_evals` table to Portfolio System build status

---

## Files Changed

| File | Change |
|---|---|
| `windmill/u/admin/portfolio_candidate_eval.py` | NEW — main Windmill script |
| `windmill/u/admin/portfolio_candidate_eval.script.yaml` | NEW — Windmill metadata |
| `agent/tools.py` | Add tool constant, dispatcher function, register |
| `agent/classifier.py` | Add intent + shortcuts to SYSTEM_PROMPT |
| `agent/tests/test_windmill_scripts.py` | 11 structural tests |
| `agent/tests/test_classifier.py` | 2 intent tests |
| `CLAUDE.md` | Update test count + build status tables |
| DB (psql) | CREATE TABLE portfolio_candidate_evals |

---

## Verification

1. `docker exec root-straitsagent-1 python -m pytest tests/ -v` → **285 tests green**
2. Schema migration applied → `portfolio_candidate_evals` table confirmed in psql
3. `wmill script push windmill/u/admin/portfolio_candidate_eval.py` → no errors
4. Windmill UI: run with `{"ticker": "AAPL", ...}` → verdict dict returned; DB row inserted; email received at <YOUR_RECIPIENT_EMAIL>
5. Telegram: `evaluate NVDA` → ASYNC_NOTIFY ACK; job runs; completion notification with verdict card
6. Edge case: `evaluate 9888.HK` → `thin_universe = True` visible in card
7. Fallback test: disable xai_key → deepseek-chat completes synthesis; `synthesiser_model` = `"deepseek-fallback"` in DB row

---

## Relationship to Existing Frameworks

| Framework | Decision | Cadence | Output |
|---|---|---|---|
| `portfolio_rationalization.py` | Which of current 31 to KEEP/TRIM/EXIT | Monthly (1st of month, 9PM SGT) | 31-row ranking, Section C scorecards, email + file |
| `portfolio_candidate_eval.py` *(this)* | Whether to ADD a new name | On-demand (Telegram `/evaluate TICKER`) | Single verdict card, email + Telegram |
| `portfolio_earnings_analysis.py` | Pre/post earnings assessment for held positions | Event-driven (alert-triggered) | Earnings report, email + file |
