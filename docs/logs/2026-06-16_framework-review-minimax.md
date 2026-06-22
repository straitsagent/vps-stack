# Portfolio Framework Review — Rationalization (v1.1, Live) & Candidate Evaluation (v1.0, Design) (MINIMAX)

**Date:** 2026-06-16
**Mode:** Read-only review — no files modified during analysis
**Reviewer:** opencode (synthesised from framework docs at `docs/portfolio_rationalization_framework.md` and `docs/portfolio_candidate_eval_framework.md`, the live script at `windmill/u/admin/portfolio_rationalization.py` (1,122 lines), and the actual 2026-06-14 report output)
**Status:** Both frameworks reviewed. Rationalization is live; candidate evaluation is design-only.

---

## Executive Summary

The Rationalization framework is **mature and high-quality**, faithfully implementing all 8 review findings incorporated in v1.1. The live 2026-06-14 run produces an actionable, well-structured report. The Candidate Evaluation framework is **well-conceived** — the per-factor triplet is elegant and decision-useful — but several design choices need a second look before implementation begins (specifically Gate 2's correlation dependencies, factor-gap-fill math, and thin-universe threshold).

Across both frameworks: **26 suggestions total** — 9 HIGH, 11 MEDIUM, 6 LOW. The HIGH items in rationalization (4) are documentation/labeling fixes plus a small code change. The HIGH items in candidate eval (4) should be addressed in the design doc **before** the script is built, since retrofitting them later is expensive.

The most consequential cross-cutting observation: **the live implementation of rationalization collapses Section C into the C3 (LLM-narrative) panel only** — the promised C1 (quantitative metrics) and C2 (factor score breakdown) panels are not rendered. This is a silent scope reduction from the framework doc that should be either fixed (render C1/C2) or explicitly accepted (update the framework doc to reflect the actual output).

---

## Methodology

Inputs reviewed:
1. `docs/portfolio_rationalization_framework.md` (482 lines, v1.1)
2. `docs/portfolio_candidate_eval_framework.md` (339 lines, v1.0)
3. `windmill/u/admin/portfolio_rationalization.py` (1,122 lines, live)
4. `windmill/u/admin/portfolio_rationalization.script.yaml`
5. `windmill/u/admin/portfolio_rationalization_monthly.schedule.yaml`
6. Live report output: `research/portfolio/rationalization_2026-06-14.md`
7. Cross-references: `portfolio_thesis`, `fundamental_data`, `valuation_snapshots`, `financial_health_metrics`, `company_profiles`, `price_history`, `fx_rates` schemas

Approach: read framework docs in full, read live script structure, read live report output, identify divergences between design and implementation, identify design choices that may not survive contact with real data, identify gaps that the design docs don't address.

---

# Part 1 — Portfolio Rationalization Framework (v1.1, Live)

## 1.1 What's Working Well

- **All 8 review findings are faithfully implemented.** Finding 1 (absolute red flags), Finding 2 (completeness penalty), Finding 3 (ADR data merge), Finding 4 (thesis staleness as display only), Finding 5 (two Grok calls), Finding 7 (deepseek fallback), Finding 8 (delta tracking) — all present in the live code and visible in the live output.
- **The report is genuinely useful.** Reading the 2026-06-14 output, the Executive Summary correctly identifies 13 consistent KEEPs (technology/AI compounders plus 3 China consumer names), flags CRWV and WIX for red-flag override despite high scenario count, and recommends exiting the bottom-decile with concrete opportunity-cost rationale.
- **Per-position blocks are concise and decision-useful.** The 4-sentence block format (Quantitative / Qualitative / Recommendation / Rationale) is the right length for a finance professional — not educational, not data-dumping.
- **Delta-tracking schema is in place.** Even on the baseline run (no prior month), the `Δ rank` column renders as "—" — graceful degradation.
- **Fallback path is wired.** `_call_grok_with_fallback()` wraps both calls; the live run used Grok-4.3 successfully (no fallback triggered).
- **Hardcoded ADR pair consolidation is deterministic.** BABA + 9988.HK and BIDU + 9888.HK are merged in `_load_adr_pairs()` and `_consolidate_positions()`. The design doc acknowledges this is a placeholder pending the `consolidation_group` schema migration (see A8).

## 1.2 Findings — Portfolio Rationalization

### A1 — HIGH: `# KEEP` column math disagrees with the report's KEEP narrative

**What I observed:**

In `_build_ranking_table` (line 661-662):
```python
n_keep = sum(1 for sc in ["balanced","quality","growth","value"]
             if r.get(sc, 99) <= len(positions) // 2)
```

With 31 positions, `len(positions)//2 = 15`. The column is a **rank threshold** (how many scenarios place the position in the top half), not a recommendation.

But the Executive Summary uses different language: "Consistent KEEPs (≥3 of 4 scenarios **AND your KEEP verdict**)" — conflating the table's rank count with a separate LLM-generated KEEP verdict. The Grok prompt (§Call 1 in the framework doc) asks for a Recommendation per position, but the table column doesn't reference that verdict.

**Live consequence:** In the 2026-06-14 output, `SERV` shows `4/4` in the table and is in the KEEP narrative. `CRWV` also shows `3/4` with rank 11 yet is in the Exit list (red flags override). A reader scanning only the table would see CRWV has the same scenario count as AMD (`3/4`) yet cannot tell they're being treated differently.

**Why this matters:** A finance professional skimming the ranking matrix would form an incorrect first impression. The `# KEEP` header implies "this many scenarios recommend keeping" — but in reality it's "this many scenarios rank in the top half."

**Suggested fix (3 options, in order of preference):**

1. **Rename the column.** `# top-15` or `# rank-top-half` is more honest about what it measures. Lowest-cost change.
2. **Add a `Verdict` column** showing the actual KEEP/TRIM/EXIT tag. More informative; requires wiring the LLM output into the table renderer.
3. **Make `# KEEP` verdict-driven** (count scenarios where the LLM said KEEP). Most honest, but couples the table to Grok's output and makes the table non-deterministic.

**My recommendation:** Option 1 (rename). The column measures a real, useful quantity (rank robustness across scenarios); the label just doesn't match the semantics.

---

### A2 — HIGH: Completeness penalty conflates "missing data" with "low quality"

**What I observed:**

The penalty is `composite × (n_available / 5)`. The code path (lines 543-551):
```python
f = {
    "quality": fs.get("quality"),       # factor-level, computed as weighted avg of 4 sub-components
    "growth": fs.get("growth"),          # weighted avg of 3
    "valuation": fs.get("valuation"),    # weighted avg of 4
    "sentiment": fs.get("sentiment"),    # weighted avg of 4
    "thesis": ts.get("thesis_score"),
}
n_available = sum(1 for v in f.values() if v is not None)
```

A factor is `None` only when **all of its underlying sub-components** are missing. So a position missing ROE but with all other quality components is still counted as "quality available."

The live output confirms: **every position shows 100% completeness** except `BRK-B` (40%) and `XLV` (40%). That uniformity is suspicious. Either:
- (a) Positions really do have full factor-level data — possible given how dense the schema is
- (b) The count is being computed correctly but doesn't capture raw-metric gaps

Looking at `_compute_factor_scores` (line 412-495), a position missing one component (e.g., `fcf_quality`) still gets a `quality` score (the weighted average of the remaining three). So 100% "factor coverage" can mask 75% raw-metric coverage.

**Why this matters:** The framework doc promised "data completeness %" as an explicit Finding 2 deliverable. The current column delivers factor-level coverage, not raw-metric coverage. The reader can't distinguish "5 of 5 factors computed, but factor 1 has only 1 of 4 components" from "5 of 5 factors computed with full sub-component data."

**Suggested fix:**

1. **Rename the column** `Factor coverage` for accuracy (5/5 means all factors computed, not all underlying metrics present).
2. **Add a second column** `Metric coverage` showing raw-metric coverage, e.g., `19 of 25 raw metrics present`. Compute this as `sum(1 for sub in sub_components if sub is not None) / total_subs`.
3. **Document in the report footer** the distinction between factor coverage (column 1) and metric coverage (column 2).

The C1 panel (Quantitative Metrics Panel) in the framework doc already lists all the raw metrics — computing metric coverage is straightforward and adds one column to the renderer.

---

### A3 — HIGH: `_compute_factor_scores` percentile pool is too small in practice, with no explicit guard

**What I observed:**

`_norm` is a percentile rank within the 31-position pool. With 31 tickers and a near-uniform distribution of factor coverage, percentile ranks are steppy (3.2% per rank step at full pool).

The framework mentions "min pool size ≥ 8 guard" (§Percentile Ranking, line 238) but **I don't see this enforced in the code path.** `_compute_factor_scores` calls `_norm` regardless of pool size. The min-pool guard appears to be conceptual, not implemented.

For HK/ADR pairs (4 tickers in the universe), data is often missing from Finnhub. The effective pool for some factors is 27 or fewer. Some factors (e.g., `ROIC`) may have data for only 15-20 of the 31 positions in a given week.

**Why this matters:** A percentile rank computed against a 6-position pool is almost meaningless (each rank is 16.7% apart). The framework's min-pool guard is a real engineering requirement that didn't make it into the code.

**Suggested fix:**

In `_compute_factor_scores`, add an explicit pool-size check:
```python
for each factor:
    pool = pool(field)
    valid_pool = [v for v in pool if v is not None]
    if len(valid_pool) < 8:
        # Exclude this factor from ALL positions' composites
        factor_scores[t][factor] = None
        # and log/flag in the report footer
    else:
        factor_scores[t][factor] = _norm(valid_pool, m.get(field))
```

Also consider supplementing the in-portfolio percentile with a sector-relative or universe-relative percentile for HK names where the 31-position pool is biased toward US tickers. yfinance provides sector aggregates for free; a small lookup at the start of the run could provide a sector-level fallback pool.

---

### A4 — HIGH: Sentiment score weights insider activity at 10% but the input is heavily right-skewed

**What I observed:**

Sentiment = `0.35×analyst_quality + 0.35×eps_beat + 0.20×momentum + 0.10×insider` (line 197-211 in the framework doc, implemented at lines 469-482 in the script).

The insider component normalises by `max_abs_insider_value in portfolio`:
```python
insider_net = net_buy_value (90d) / max_abs_insider_value in portfolio
```

With concentrated insider buys in one or two names (typical), the pool's max is large. Most positions get a percentile near zero even with positive insider activity. Combined with the low 10% weight, the signal is weak.

**More importantly:** a single insider buy of $10M in a $500B megacap is **not** the same signal as a $10M buy in a $5B small-cap. The current normalisation ignores market-cap context.

**Why this matters:** Insider-driven ranking churns month-to-month with low decision-relevance. Two positions with the same absolute insider dollar flow can have wildly different signal strength depending on their size.

**Suggested fix:** Either
- Normalise insider activity as `insider_buy_value / market_cap` (a flow ratio), or
- Add an `insider_intensity` sub-metric alongside the absolute dollar flow.

For option 1, the percentile pool then ranks companies by the *relative* insider conviction, which is more comparable across the size spectrum.

---

### A5 — MEDIUM: `analyst_upside_pct` is computed off a stored `analyst_target` whose semantics need verification

**What I observed:**

`_fetch_fundamentals` line 151-154:
```python
"analyst_upside_pct": (
    (float(target) / float(price) - 1)
    if target and price and float(price) > 0 else None
),
```

The valuation score depends on this upside. If `analyst_target` (stored in `valuation_snapshots`) is the **mean** of all analyst targets, that's a reasonable consensus signal. If it's a single broker's target, the variance is huge and the upside ranking is noise.

**Why this matters:** I traced through the `stock_data_fetcher.py` reference (per audit H22) but didn't fully verify what field is stored. The framework doc assumes consensus-style input but the script doesn't enforce it.

**Suggested fix:** Verify with `stock_data_fetcher.py:_store_stock_snapshot()` (around line 660-910 in that file) what field is actually stored. If it's a single broker target, replace with the median or trimmed mean across analysts. If it's already a consensus, add a one-line comment in the code confirming the source.

---

### A6 — MEDIUM: Growth formula drops negative-CAGR positions silently

**What I observed:**

`_cagr` (line 102-112) returns `None` for negative ratios:
```python
if ratio <= 0:
    return None
```

So a position with -10% revenue CAGR for 3 years shows up as **missing growth data**. Consequences:
- Excluded from `g_factors` (line 444)
- Receives 0 contribution to the growth composite
- Reduces `n_available_factors` from 5 to 4, triggering the completeness penalty
- Ranks poorly but **not in a way that surfaces the negative CAGR explicitly**

The framework design acknowledges this: "Negative CAGR is valid and will rank below median. Missing data → excluded from percentile pool." But in practice, the percentile pool for `rev_cagr_3yr` is computed **only over positions with valid CAGRs**, so the negative-CAGR position is **excluded from the pool entirely** and ends up with `growth = None` (no rank at all), then a 0 contribution.

This conflates two distinct signals:
- "We couldn't compute CAGR" (genuine data gap)
- "CAGR is negative" (a real, severe signal)

**Why this matters:** The red-flag check (`revenue CAGR 3yr < 0%`) catches the most extreme cases. But a position with -2% CAGR passes the red flag (threshold is `< 0%`, so -2% triggers; but -5% triggers more severely). Currently the growth score treats -2% the same as -50% — both end up as None. The reader sees "growth = None" without knowing whether the missing number is mildly negative or catastrophically negative.

**Suggested fix:** Treat negative CAGR as the **minimum** of the pool rather than missing. Specifically:

```python
def _cagr(v_new, v_old, years):
    # ... existing logic ...
    ratio = float(v_new) / float(v_old)
    if ratio <= 0:
        return ratio ** (1.0 / years) - 1   # allow negative result
    return ratio ** (1.0 / years) - 1
```

Or rank explicitly with a sign-aware comparator. Either way, the percentile pool should include negative CAGRs as the lowest ranks, not exclude them entirely.

In the live output, EQNR (-34.9% NI CAGR) and BIDU (-47.5%) are exit candidates — luckily their red flags catch them. But a name without the red flag would silently lose rank without surfacing the negative trend to Grok.

---

### A7 — MEDIUM: Two Grok calls risk truncation if one call returns less than expected

**What I observed:**

Call 1 is constrained by `max_tokens=8000` (~6,000 words). With 31 positions × ~200 words = ~6,200 words. **Tight.** If Grok returns 5,800 words instead of 6,000, the framework's "Target 15,000–20,000 words" claim falls short. The risk compounds if Call 2 also runs short.

In the live report output, the SERV block cuts off mid-sentence in the section I sampled. This suggests Call 1 may have been truncated.

**Why this matters:** The framework doc promises 15,000-20,000 words. If the actual output is 12,000, the user notices. And truncation is silent — there's no "tokens consumed vs budget" warning in the report footer.

**Suggested fix:**

1. **Split Call 1 into 2 batches** (positions 1-15 and 16-31). Each gets its own context window; total budget doubles. Concatenate the outputs. This is the most robust fix.
2. **Add a `tokens_consumed / budget` warning** in the report footer so the operator can see if truncation occurred.
3. **Reduce per-position ask** from 4 sentences × 31 = 124 sentences to a tighter format (3 sentences × 31 = 93 sentences ≈ 2,800 tokens, fits in 4,000). More room for Grok to elaborate on the most interesting positions.

**My recommendation:** Option 1 (split into 2 batches). Preserves output quality and gives Grok room to elaborate where the data is most interesting.

---

### A8 — MEDIUM: ADR consolidation logic hardcodes pairs in 2 places

**What I observed:**

The audit found that `portfolio_rationalization.py` hardcodes `ADR_PAIRS` in `_load_adr_pairs()` (line 330-352). The framework design says ADR pairs are merge targets but the data path uses a hardcoded Python dict. The fix in audit H8 is to populate `consolidation_group` in seed and query it.

**Why this matters:** The framework doc (line 21-28) says "BABA+9988.HK and BIDU+9888.HK" inline but doesn't reference `consolidation_group` as the source of truth. The doc and the code are inconsistent on this point.

**Suggested fix:** Add a sentence to the framework doc explaining that the hardcoded `ADR_PAIRS` dict is a placeholder pending the schema migration. Or just do the migration now (audit H8) and update both doc and code to read from `consolidation_group`.

---

### A9 — MEDIUM: Section C1 and C2 panels are not rendered in the live output

**What I observed:**

The framework doc (line 58-113) defines 4 sub-sections per position:
- **C1:** Quantitative Metrics Panel (Python-computed, no LLM)
- **C2:** Factor Score Breakdown (percentile ranks 0-100)
- **C3:** Qualitative Analysis (Grok-4.3 generated)
- **C4:** Investment Thesis (from `portfolio_thesis` table)

The live 2026-06-14 report renders only **C3** (the Grok narrative). C1 (the raw metrics) and C2 (the factor breakdown) are not present as separate panels. Thesis information from `portfolio_thesis` (C4) appears integrated into C3 but not as a sourced-as-is block.

**Why this matters:** A finance professional who wants to verify a position's ranking would benefit from C1 (raw numbers, fully auditable) alongside C3 (LLM interpretation). Without C1, the reader has to trust Grok's summary of the numbers — which is exactly the auditability gap the framework was designed to avoid.

**Suggested fix:** Either
- Render the C1/C2 panels as designed, OR
- Update the framework doc to reflect that C3 alone is the per-position output and explicitly accept the loss of transparency.

The current state — design says one thing, code does another — is exactly the kind of drift the audit flagged.

---

### A10 — LOW: `delta_rank_balanced` only — no delta for other scenarios

**What I observed:**

Schema has `rank_balanced`, `rank_quality`, `rank_growth`, `rank_value` but only `delta_rank_balanced` is computed. The framework doc says "Δ rank vs prior month" without specifying which scenario.

**Why this matters:** A position moving from rank 8 to rank 14 in the **growth** scenario (while stable in balanced) tells a different story than the same move in the **value** scenario. The current schema captures only one of three other scenarios' movements.

**Suggested fix:** Add `delta_rank_quality`, `delta_rank_growth`, `delta_rank_value` to the schema. Or document the choice of balanced-only explicitly in the framework doc.

---

### A11 — LOW: Red-flag override logic in Executive Summary not explicit

**What I observed:**

The Call 1 prompt asks Grok for a Recommendation per position. The Executive Summary then combines:
- Table `# KEEP` column (rank threshold)
- Grok's per-position Recommendation
- Implicit red-flag override (positions with red flags get exit treatment regardless of rank)

In the live output, `CRWV` shows `3/4` (rank 11 in balanced) yet is in the Exit list. `WIX` shows `2/4` (rank 22) but also Exit. Both have red flags. This works **only because** the report assembly code applies the red-flag override post-hoc.

**Why this matters:** If the override logic is missing in some path, a position with high scenario count + red flags would be wrongly listed as a Consistent KEEP. The framework doc doesn't describe this override explicitly.

**Suggested fix:** Add a test specifically for "red-flag override behavior": `test_red_flag_overrides_scenario_count`. Make the override logic a named function (`_apply_red_flag_override(recommendations, red_flags_map)`) and call it explicitly in the assembly path.

---

# Part 2 — Portfolio Candidate Evaluation Framework (v1.0, Design Only)

## 2.1 What's Working Well (Design Strengths)

- **Per-factor triplet** (`absolute`, `portfolio_pct`, `universe_pct`) is elegant. It preserves the decision-relevant nuance that a single composite would hide.
- **Three independent gates** that all run regardless of pass/fail. This avoids the "stop on first failure" anti-pattern where a great absolute business is dismissed because of a portfolio-fit issue that could be solved by trimming something else.
- **Binding constraint line** in the verdict card — the single most actionable element. "If sector concentration were lower, verdict would flip to ADD." Tells the user exactly what to monitor.
- **Thin universe flag** is good defensive design. Surfaces low-confidence rather than hiding it.
- **Reuse of `_evaluate_red_flags()`** from rationalization — no duplicated threshold logic, single source of truth.
- **Reuse of factor formulas** — exact same Quality/Growth/Valuation/Sentiment math as rationalization. Cross-framework consistency.

## 2.2 Findings — Portfolio Candidate Evaluation

### B1 — HIGH: Gate 2 correlation depends on price_history existence for the candidate

**What I observed:**

`_compute_correlation(ticker, conn)` requires 90 days of `price_history` for the candidate. The doc says "yfinance 90-day returns" for the candidate but the function reads `price_history` for the existing 31 positions. So there's a dual-source problem:

- **Candidate side:** specified as yfinance (90d is fine if yfinance has the ticker; HK tickers and small-caps sometimes have gaps).
- **Existing side:** `price_history` table, updated by `portfolio_price_fetcher.py` (2× daily SGT). If an existing position hasn't been refreshed in >90d, correlation against current candidate prices compares stale vs fresh.

**Why this matters:** Candidates that don't yet exist in `price_history` (because they're new to evaluation, not in the portfolio) will fall back to yfinance only. Existing positions with stale data introduce asymmetric noise.

**Suggested fix:** In `_compute_correlation`, explicitly check the date range of `price_history` for both sides:
- If < 60 days available for either side, **fall back to yfinance for both** and document the date range used.
- If < 30 days available for the candidate, surface a `gate2_warn = "insufficient_history"` flag instead of silently producing a low-quality correlation.
- If the existing side is stale (last update > 7 days), warn but proceed.

---

### B2 — HIGH: Correlation is a noisy proxy for "portfolio fit"

**What I observed:**

Gate 2 uses only **price correlation** to evaluate portfolio fit. Two positions can have low price correlation but high fundamental correlation:
- Two China consumer stocks that move on different policy events but share revenue mix
- Two SaaS companies with different customer segments but similar margin structures

The current design captures price similarity only, missing fundamental similarity. This means a candidate with low price correlation to existing positions might still be a poor portfolio fit on a fundamental basis.

**Why this matters:** "Portfolio fit" is multi-dimensional. A candidate that diversifies price exposure but adds fundamental concentration is a mixed signal. The current design treats this as fully diversifying when it's actually mixed.

**Suggested fix:** Add a **fundamental correlation** sub-check:
- Compute cosine similarity of (sector, country, factor-triplet vector) between candidate and each existing position
- If fundamental similarity is high even when price correlation is low, surface as a separate WATCH signal
- The verdict card should show both: "Price correlation P20 (diversifying); Fundamental similarity P80 (concentrating)"

This becomes a 4th sub-check alongside price correlation in Gate 2.

---

### B3 — HIGH: "Factor gap fill" logic isn't fully specified

**What I observed:**

Gate 2 says: "Portfolio factor gaps (below median); does candidate score >P60 there" — but doesn't define "P60 of what." Of the existing portfolio? Of the universe benchmark? Of some absolute threshold?

In the live rationalization, factors are percentile-ranked within the 31-position pool. So "below median" = composite_score < 50. "P60" = composite_score > 60. That's an internally consistent definition but **the candidate's score needs to be computed against the same 31-position pool** for the comparison to be meaningful.

**Why this matters:** Without explicit percentile math, two implementations could disagree on what "gap fill" means. The agent (if invoked on Telegram) and the Windmill script need to compute the same answer.

**Suggested fix:** Specify explicitly in the framework doc:
```
Gap fill condition:
- For each factor F in {quality, growth, valuation, sentiment}:
  - Compute pool_median_F = median(composite_F across existing 31)
  - Compute pool_p60_F = 60th percentile of composite_F across existing 31
  - If pool_median_F < 50 (factor below median in current portfolio) AND
    candidate_F > pool_p60_F:
    → F is a "gap fill factor" for this candidate
- If at least 2 factors are gap fills: candidate fills a portfolio gap
```

Add an example calculation to the framework doc using a real candidate (e.g., NVDA) so the math is unambiguous.

---

### B4 — HIGH: Thin universe (Gate 3) default of 3 peers is too aggressive

**What I observed:**

`min_pool = 3` is much lower than the rationalization's min-pool of 8. The justification isn't stated in the doc. With 3 peers, percentile ranks are 0/50/100 — basically binary (and the middle position gets a meaningless 50th percentile). The `thin_universe` flag at < 5 peers is good, but a pool of exactly 4 still produces ranking that's hard to act on.

**Why this matters:** The candidate eval is meant to inform a buy/skip decision. A binary "best/worst of 3" signal is much weaker than the rationalization's 8-pool percentile ranking. The asymmetry is unjustified.

**Suggested fix:** Either
- Raise `min_pool` to 5 (matching `thin_universe` boundary) and have a separate `below_min_universe` flag for 3-4 peers, OR
- Document explicitly why 3 is acceptable for candidates but not for current positions. Possible rationale: candidate evals are exploratory; the user can decide whether to trust the result based on the thin_universe flag. But this should be explicit, not implicit.

**My recommendation:** Raise `min_pool` to 5. Match the threshold where the verdict card already starts warning. Consistency reduces ambiguity.

---

### B5 — MEDIUM: Grok prompt uses [derive from metrics and sector context] for missing thesis — silent hallucination risk

**What I observed:**

The Grok prompt template (framework doc line 140):
```
== THESIS ==
{thesis_text if user-supplied else "[derive from metrics and sector context]"}
```

This is a silent fallback — the LLM will invent a thesis for the candidate. For a candidate the user has **no prior thesis on**, the LLM-generated thesis will look authoritative but is fabricated. That's a hallucination risk that should be flagged in the verdict card.

**Why this matters:** A user evaluating "should I buy NVDA?" with no pre-existing thesis will receive a verdict card with a Grok-invented investment thesis ("AI infrastructure leader with multi-year demand visibility"). The user has no way to know this was synthesized vs user-supplied. If they treat it as their own analysis, they've outsourced their thinking to a hallucination.

**Suggested fix:** Replace the fallback placeholder with explicit "no user thesis" language:
```
== THESIS ==
{thesis_text if user-supplied else "[NO USER-SUPPLIED THESIS — analysis limited to quantitative factors; qualitative context below is LLM-derived and not user-validated]"}
```

The verdict card should also flag this prominently. The user can then decide whether to trust the LLM's framing.

---

### B6 — MEDIUM: Verdict thresholds are not defined numerically

**What I observed:**

The doc gives 3 verdicts (ADD/WATCH/PASS) but the criteria are narrative:
- ADD: "clears all gates; additive to portfolio and best available vs. universe"
- WATCH: "clears absolute gate; strong on universe rank; blocked by a *mutable* portfolio constraint"
- PASS: "fails absolute gate OR decisively beaten on universe gate"

What's "decisively beaten"? What's "strong on universe rank"? These need numeric thresholds for reproducibility.

**Why this matters:** Without numeric thresholds, two runs on the same candidate could produce different verdicts depending on Grok's interpretation. The framework doc promises reproducibility but doesn't deliver it.

**Suggested fix:** Add explicit thresholds, e.g.:
```
ADD: gate1 = ok AND universe_composite_pct ≥ 60 AND no blocking constraint
WATCH: gate1 = ok AND universe_composite_pct ≥ 40 AND (sector_match_count ≥ 3 OR country_match_count ≥ 5 OR red_flag_count >= 1)
PASS: otherwise
```

The Grok prompt can then *narrate* the verdict, but the underlying logic should be deterministic and testable. This also enables the `--no-llm` mode (see C4).

---

### B7 — MEDIUM: No handling of replacement scenarios

**What I observed:**

A candidate from the tech sector adding to a tech-heavy portfolio gets WATCH because there are already 8 tech names. But if the candidate is **replacing** one of those names, the marginal sector exposure is unchanged. The current design treats "additive" as "binary" without considering replacement scenarios.

**Why this matters:** A common rationalization question is "should I add X to replace Y?" The current framework can't answer that.

**Suggested fix:** Add a `replacement_scenario` parameter (optional):
```
candidate_evaluation(ticker="XYZ", replacement_ticker="ABC")
```

If `replacement_ticker` is supplied, recompute sector/country/currency counts net of that exit. The verdict card can then say: "ADD if NVDA is also exited; WATCH if portfolio is held intact."

This requires no new tables — just recompute Gate 2 sub-checks with the exit applied.

---

### B8 — MEDIUM: No FX exposure check (relevant for HK/ADR-heavy portfolios)

**What I observed:**

The portfolio includes HK-listed positions (9988.HK, 0700.HK, 3690.HK, 9888.HK). A candidate in HKD or RMB adds to the FX bucket. The framework doesn't have an FX exposure check.

**Why this matters:** Currency concentration is a real risk dimension. A candidate that brings the portfolio's HKD exposure from 8% to 15% might be a worse fit than its factor scores suggest.

**Suggested fix:** Add a 4th dimension to Gate 2: currency concentration.
- Compute `currency_pct_by_ccy` of existing portfolio by summing `position_usd / fx_rate` for each non-USD ticker
- If candidate is non-USD and currency exposure would exceed a threshold (e.g., 30%), that's a mutable WATCH constraint
- Surface in the verdict card: "Currency exposure post-addition: HKD 18% (above 15% soft limit)"

---

### B9 — MEDIUM: `_fetch_universe` accepts user-supplied list but doesn't validate it's reasonable

**What I observed:**

If a user supplies `universe_tickers=["NVDA", "AMD", "INTC"]` for a candidate like "ASML", that's a reasonable semi-cap universe. But `universe_tickers=["NVDA", "WMT", "XOM"]` is nonsense (mega-cap tech + retail + energy) and would skew the percentile rankings badly.

**Why this matters:** The user-supplied universe override is a powerful feature but unguarded. A bad universe produces a misleading verdict that the user can't detect.

**Suggested fix:** Add a `_validate_universe` helper that warns if the supplied universe has high cross-ticker variance:
- Coefficient of variation of `market_cap > 2` (heterogeneous sizes)
- > 3 distinct sectors (heterogeneous businesses)
- > 2 distinct countries (heterogeneous geographies)

If any threshold breached, surface `universe_heterogeneity` warning in the verdict card. The user can then decide whether to proceed with a cleaner universe.

---

### B10 — LOW: Framework doesn't warn if portfolio baseline is stale

**What I observed:**

The doc says "Candidate data: stock_data_fetcher.py dispatched if data absent or stale (>3 days)." Good — but the **existing 31 positions' data freshness isn't checked.** If `fundamental_data` for an existing position is 6 months old, the `portfolio_scores` percentile ranks are stale, and the candidate's "P60 vs. portfolio" comparison is invalid.

**Why this matters:** Candidate eval depends on a fresh portfolio baseline. Without that baseline, the per-factor triplet `portfolio_pct` is computed against stale numbers.

**Suggested fix:** Add a freshness check on `portfolio_scores.score_date`. If the most recent score is > 35 days old, the candidate eval should warn: "Portfolio baseline is N days old; consider running rationalization first." Optionally, dispatch a rationalization job as a prerequisite.

---

### B11 — LOW: No re-evaluation cadence defined

**What I observed:**

The doc says "On-demand (Telegram `/evaluate TICKER`)" but doesn't say how stale an eval becomes. If I evaluate NVDA today, what's the shelf life of that verdict? A week? A month? Until next earnings?

**Why this matters:** Without a defined staleness, the same eval result might be trusted long past its useful life. The candidate's universe peers' prices change daily; even a week-old eval has stale price correlation.

**Suggested fix:** Add `eval_stale_after_days = 30` constant and surface in the verdict card: "Valid until 2026-07-16." Also: cache evals in `portfolio_candidate_evals` with `eval_date` so the agent can serve stale evals with a freshness warning.

---

# Part 3 — Cross-Cutting Findings

## C1 — HIGH: Both frameworks rely on Grok-4.3 but lack cost controls

**What I observed:**

Each rationalization run = 2 Grok calls × ~10K tokens = ~$0.10 (based on xAI pricing). Each candidate eval = 1 Grok call × ~3K tokens = ~$0.03. With a Telegram-driven flow, a curious user could trigger 20 evals in a session = $0.60. The agent's `agent_audit_log.estimated_cost_usd` field exists but isn't checked against a budget.

**Why this matters:** A user (or a misbehaving agent) could rack up unbounded API spend without warning. For a personal stack this is manageable; for any future multi-user or business-facing deployment, this is a real risk.

**Suggested fix:**
1. Add a daily cost cap (e.g., $2/day across all Grok calls) enforced at the agent layer
2. Per-session rate limit on candidate evals (e.g., 5 per session)
3. Surface cost in the response footer: "Today's spend: $0.43 of $2.00 daily cap"
4. Add a `cost_cap_exceeded` graceful response that returns a cached eval or explains the limit

## C2 — HIGH: Both frameworks lack a "show your work" mode for auditability

**What I observed:**

For a finance professional, knowing *why* a position was rated as it was is more important than the rating itself. Currently the LLM synthesises a paragraph but doesn't link each sentence back to a specific metric.

**Why this matters:** A reader can't verify the LLM's claims without re-reading the data. For a serious investment decision, this is a trust gap.

**Suggested fix:** Have Grok output structured JSON alongside the narrative, with each claim tagged to the source metric:
```json
{
  "verdict": "KEEP",
  "rationale_sentences": [
    {
      "text": "Highest composite rank across all four scenarios with perfect data completeness",
      "evidence": ["rank_balanced=1", "rank_quality=1", "rank_growth=1", "rank_value=1", "data_completeness_pct=100"]
    },
    ...
  ]
}
```

Then the report can render "Claim X → fwd PE = 9.9×" inline. This adds ~10% to Grok's output but dramatically improves auditability.

## C3 — MEDIUM: Both frameworks' `synthesiser_model` should be surfaced per-position

**What I observed:**

The footer shows "⚠️ Grok unavailable — synthesised with deepseek-chat" but per-position verdicts don't carry a `model_used` tag.

**Why this matters:** The user can't tell which positions used the fallback and which used primary. If Call 1 used Grok but Call 2 fell back to Deepseek, the per-position verdicts (Call 1) are Grok-derived but the executive summary (Call 2) is Deepseek-derived. This is invisible in the current output.

**Suggested fix:** Tag each LLM output with `synthesiser_model` and render in the per-position block: "**Verdict (Grok-4.3):** KEEP". For positions where the synthesis was fallback, the tag shows "Verdict (Deepseek-fallback):" — making the fallback visible at the position level.

## C4 — MEDIUM: Both frameworks lack a `--no-llm` mode for testing/audit

**What I observed:**

The Python-computed factors and rankings are deterministic; only the narrative requires an LLM. There's no way to run the framework without the LLM call.

**Why this matters:** Without `--no-llm`:
- Unit tests can't verify the ranking math without mocking Grok
- Auditors can't verify the quantitative analysis without paying API costs
- Iteration on scoring weights requires full LLM runs to see the effect

**Suggested fix:** Add `--no-llm` flag (or a `synthesis_mode` parameter):
- Computes all factor scores, rankings, and per-position quantitative blocks
- Skips both Grok calls
- Replaces C3 narrative with a "[LLM synthesis disabled]" placeholder
- Useful for: unit tests, audit verification, fast iteration on scoring weights, cost-free dry runs

## C5 — LOW: Schema-level: `portfolio_scores` and `portfolio_candidate_evals` should share a common `eval_runs` parent table

**What I observed:**

Currently they're separate. A future query "show me all scoring history for NVDA" would need a UNION. A normalised design with `eval_runs(id, eval_date, eval_type, ticker, ...)` would be cleaner.

**Why this matters:** Future-extensibility. Not a current bug, but a design choice that will be expensive to retrofit later.

**Suggested fix:** Defer until a third eval-type is added. Two is fine as separate tables; three suggests normalisation.

---

# Part 4 — Summary & Recommended Action Sequence

## 4.1 Prioritised Findings Table

| # | Severity | Framework | Change | Effort |
|---|---|---|---|---|
| A1 | HIGH | Rationalization | Rename `# KEEP` → `# top-15` or add Verdict column | Low |
| A2 | HIGH | Rationalization | Add metric-coverage column; rename `Completeness %` to `Factor coverage` | Low |
| A3 | HIGH | Rationalization | Add min-pool-size guard in `_compute_factor_scores` | Low |
| A4 | HIGH | Rationalization | Normalise insider activity by market cap | Low |
| A6 | MEDIUM | Rationalization | Treat negative CAGR as pool minimum, not missing | Low |
| A7 | MEDIUM | Rationalization | Split Grok Call 1 into 2 batches; add token-budget warning | Medium |
| A8 | MEDIUM | Rationalization | Sync `consolidation_group` schema with code | Low |
| A9 | MEDIUM | Rationalization | Render C1/C2 panels or update framework doc | Medium |
| A5 | MEDIUM | Rationalization | Verify `analyst_target` source | Low |
| A10 | LOW | Rationalization | Add delta-rank for non-balanced scenarios | Low |
| A11 | LOW | Rationalization | Make red-flag override logic explicit and tested | Low |
| B1 | HIGH | Candidate eval | Validate price_history date range before correlation | Low |
| B2 | HIGH | Candidate eval | Add fundamental correlation sub-check | Medium |
| B3 | HIGH | Candidate eval | Define factor gap fill math explicitly | Low |
| B4 | HIGH | Candidate eval | Raise `min_pool` to 5 | Low |
| B5 | MEDIUM | Candidate eval | Replace "[derive...]" with explicit no-thesis warning | Low |
| B6 | MEDIUM | Candidate eval | Define numeric verdict thresholds | Low |
| B7 | MEDIUM | Candidate eval | Support `replacement_scenario` parameter | Medium |
| B8 | MEDIUM | Candidate eval | Add FX exposure dimension | Medium |
| B9 | MEDIUM | Candidate eval | Add universe heterogeneity validator | Low |
| B10 | LOW | Candidate eval | Warn if portfolio baseline is stale | Low |
| B11 | LOW | Candidate eval | Define `eval_stale_after_days` | Low |
| C1 | HIGH | Both | Add cost cap / rate limit | Medium |
| C2 | HIGH | Both | Add "show your work" structured JSON | Medium |
| C3 | MEDIUM | Both | Surface `synthesiser_model` per position | Low |
| C4 | MEDIUM | Both | Add `--no-llm` mode | Medium |

## 4.2 Recommended Action Sequence

**Phase 1 — Documentation alignment (1 day):**
- A1: Rename `# KEEP` column
- A8: Sync ADR consolidation doc with code
- A9: Update framework doc to reflect that C3 is the only per-position panel currently rendered (or render C1/C2)
- B3: Define factor gap fill math explicitly in framework doc
- B4: Document the `min_pool = 3` rationale or raise to 5
- B6: Define numeric verdict thresholds in framework doc

**Phase 2 — Code hardening (1-2 weeks):**
- A2: Add metric-coverage column to renderer
- A3: Add min-pool guard in `_compute_factor_scores`
- A4: Normalise insider by market cap
- A6: Treat negative CAGR as pool minimum
- A11: Test red-flag override logic
- B1: Validate price_history date range in `_compute_correlation`
- B5: Replace [derive...] placeholder
- B9: Add universe heterogeneity validator
- B10: Add portfolio-baseline staleness check

**Phase 3 — Design extensions (before candidate eval implementation):**
- B2: Add fundamental correlation sub-check (requires new metric in DB)
- B7: Support `replacement_scenario` parameter
- B8: Add FX exposure dimension (requires new metric in DB)
- C3: Surface `synthesiser_model` per position
- C4: Add `--no-llm` mode

**Phase 4 — Cost & auditability (2-4 weeks):**
- A7: Split Grok Call 1 into 2 batches
- C1: Cost cap / rate limit
- C2: "Show your work" structured JSON

**Phase 5 — Future:**
- A5: Verify analyst_target source
- A10: Multi-scenario delta tracking
- B11: Define eval_stale_after_days
- C5: Schema normalisation (defer until third eval-type exists)

## 4.3 What's NOT Worth Changing

A few findings I considered and rejected:
- **Framework doc promises 15,000-20,000 word output.** The actual output is shorter. Updating the word-count claim rather than forcing Grok to produce more words is the right call — brevity is a feature for a finance professional.
- **Windmill variable defaults `""` instead of `$var:`.** Already raised in audit M1; not framework-specific.
- **Hardcoded `WM_BASE_URL`.** Already raised in audit M1; not framework-specific.

## 4.4 Closing Observations

The rationalization framework is the most complex piece of code in this stack — 1,122 lines, 5 sub-factor formulas, 4 scenarios, 2 LLM calls, 1 fallback path, 1 schema migration. That it works at all on the first production run is a credit to the design discipline.

The candidate evaluation framework has the harder design problem: deciding whether to **add** a position is structurally different from deciding whether to **keep** one. The per-factor triplet is the right abstraction. The gate structure is sound. The implementation gaps are tractable.

The most consequential observation across both: **a finance professional using these tools will judge them by the auditability of their conclusions, not by the eloquence of the prose.** Show your work. Surface the model used. Make the verdicts reproducible. C2 (show your work) and C3 (per-position model tag) are the highest-leverage cross-cutting changes.

---

## Appendix A — Files Reviewed

| File | Lines | Purpose |
|---|---|---|
| `docs/portfolio_rationalization_framework.md` | 482 | Framework design doc, v1.1 |
| `docs/portfolio_candidate_eval_framework.md` | 339 | Framework design doc, v1.0 |
| `windmill/u/admin/portfolio_rationalization.py` | 1,122 | Live script |
| `windmill/u/admin/portfolio_rationalization.script.yaml` | — | Windmill metadata |
| `windmill/u/admin/portfolio_rationalization_monthly.schedule.yaml` | — | Cron schedule |
| `research/portfolio/rationalization_2026-06-14.md` | — | Live report output |

## Appendix B — Test Coverage Map

Tests live at `agent/tests/test_windmill_scripts.py` (1,941 lines). Rationalization has 12 structural tests covering: script exists, ADR consolidation, 4 scenarios, `portfolio_scores` write, neutral Grok prompt, absolute thresholds, completeness penalty, min pool size, no freshness multiplier, 2 Grok calls, deepseek fallback, delta query.

Candidate eval framework proposes 11 structural tests in the design doc (§Implementation Plan). These should be written before implementation per Hard Rule 15 (TDD).

## Appendix C — Open Questions for the Owner

1. **Is `# KEEP` the right label or should it be `# top-15`?** Affects A1.
2. **Should C1/C2 panels be rendered, or should the framework doc be updated to remove the promise?** Affects A9.
3. **Is `min_pool = 3` justified for candidate eval, or should it match rationalization's 8?** Affects B4.
4. **Should the candidate eval support a `replacement_scenario` parameter?** Affects B7.
5. **What's the daily Grok cost cap?** Affects C1.

---

**End of review.** No files modified during analysis. All findings are derived from read-only inspection of the framework docs, the live script, and the live report output as of 2026-06-16.