# Framework Review Incorporation Plan — Minimax Findings

**Date:** 2026-06-17
**Source review:** `docs/audit/260616_framework_review_minimax.md` (26 findings)
**Status:** Plan approved — execution pending
**Frameworks affected:**
- `windmill/u/admin/portfolio_rationalization.py` (LIVE, monthly) — findings A1–A11
- `docs/portfolio_candidate_eval_framework.md` (DESIGN ONLY, v1.0) — findings B1–B11
- Cross-cutting — findings C1–C5

---

## Context

The minimax review produced 26 findings across the two portfolio frameworks. This document
records the agreed plan for incorporating the still-valid recommendations. Because the
rationalization script is a working production workflow, **Hard Rule 12 applies** — every change
to it is described here, gets sign-off, and follows TDD (Hard Rule 15). The candidate-eval doc is
design-only, so those edits carry zero runtime risk.

### Reconciliation against current code (findings already resolved or mis-stated)

Verified by reading the live script — these need **no code work**:

- **A3 (min-pool guard)** — already implemented. `MIN_POOL_SIZE = 8` (line 42), enforced in
  `_norm` (lines 406–407). Closed as done.
- **A8 (ADR pairs hardcoded)** — already fixed by the prior audit (B7). `_load_adr_pairs`
  (lines 330–350) now queries `consolidation_group` from the DB; the `ADR_PAIRS` dict is gone.
  Only the Grok **prompt example strings** (lines 852, 920) still name BABA/9988.HK, BIDU/9888.HK.
  → handled as a one-line doc note + optional prompt cleanup, not a data-path change.
- **A9 (C1/C2 panels "not rendered")** — premise is inverted. C1 (quant metrics, line 961),
  C2 (scenario ranks, lines 982–984) and C4 (thesis, line 987) **are** rendered per-position;
  C3 (Grok narrative) is the one rendered as a single combined block (lines 1008–1010). The real
  gap: C2 shows ranks only, not the 0–1 factor-score breakdown, and the doc has a duplicate C3
  header. → handled as a **doc correction**, not a missing-panel fix.

### Owner decisions (2026-06-17)

- **A1**: rename `# KEEP` → `# top-half`.
- **B4**: raise candidate-eval `min_pool` from 3 → 5.
- **Cross-cutting**: implement **C2 (show-your-work JSON)** only. **C1 (cost cap), C3 (per-position
  model tag), C4 (--no-llm), C5 (schema normalisation) are explicitly OUT of scope.**

---

## Phase 1 — Doc alignment + candidate-eval design fixes (zero live risk)

### 1a. Rationalization framework doc (`docs/portfolio_rationalization_framework.md`)

- **A1 (doc side):** rename the matrix column from "# scenarios KEEP" to "# top-half" with a
  one-line note that it counts scenarios ranking the position in the top half (rank robustness),
  not a KEEP verdict.
- **A9 (doc correction):** rewrite Section C (lines ~58–113) to match the live renderer — C1/C2/C4
  per-position, C3 as a single combined Grok block. Remove the **duplicate C3 header**
  (lines 99–104 vs 106–108). State that C2 currently shows scenario ranks, not the 0–1 factor
  breakdown (decision: leave code as-is, document accurately).
- **A8 (doc side):** add a sentence noting ADR consolidation is now sourced from
  `portfolio_positions.consolidation_group` (not a hardcoded map), aligning doc with code.
- **A2 (doc side):** clarify the "completeness" language — the column is **factor coverage**
  (all 5 factors computed), distinct from raw-metric coverage; cross-reference the new metric-
  coverage column added in Phase 2.
- **Word-count claim (review §4.3):** soften the "15,000–20,000 words" target to a realistic
  range and label it a soft target — per the review, do not force Grok to pad.
- Bump doc to **v1.2** with a short changelog noting these alignments.

### 1b. Candidate-eval framework doc (`docs/portfolio_candidate_eval_framework.md`) — make build-ready

Apply B1–B11 + C2 so the doc can be implemented cleanly later (Hard Rule 7 sign-off happens at
build time, not now):

- **B1:** spec `_compute_correlation` to validate `price_history` date range — fall back to
  yfinance for both sides if <60d available; `gate2_warn="insufficient_history"` if <30d for the
  candidate; warn (proceed) if the existing side's last update >7d.
- **B2:** add a **fundamental-correlation** sub-check to Gate 2 — cosine similarity of
  (sector, country, factor-triplet vector); surface "price P20 (diversifying) / fundamental P80
  (concentrating)" in the verdict card.
- **B3:** define the factor-gap-fill math explicitly against the existing 31-position
  `portfolio_scores` pool: `pool_median_F`, `pool_p60_F`; a factor is a gap-fill if
  `pool_median_F < 50 AND candidate_F > pool_p60_F`; ≥2 gap-fill factors ⇒ "fills a portfolio gap".
  Add a worked example (e.g. NVDA).
- **B4:** raise `min_pool` to **5**; add a `below_min_universe` flag for 3–4 peers; keep
  `thin_universe` at <5.
- **B5:** replace the `[derive from metrics and sector context]` thesis fallback with explicit
  "NO USER-SUPPLIED THESIS — LLM-derived, not user-validated" language + a prominent verdict-card flag.
- **B6:** add **numeric** ADD/WATCH/PASS thresholds (e.g. ADD: gate1 ok AND universe_composite_pct≥60
  AND no blocking constraint; WATCH: gate1 ok AND ≥40 AND a mutable constraint; PASS otherwise).
  Grok narrates; logic is deterministic/testable.
- **B7:** add optional `replacement_ticker` parameter — recompute Gate 2 sector/country/currency
  counts net of the exit; verdict card states both held-intact and replacement outcomes.
- **B8:** add a **currency-exposure** dimension to Gate 2 (sum `position_usd` by currency via
  `fx_rates`; soft limit e.g. HKD 30%); surface post-addition exposure in the verdict card.
- **B9:** add `_validate_universe` heterogeneity guard for user-supplied `universe_tickers`
  (market-cap CoV>2, >3 sectors, >2 countries ⇒ `universe_heterogeneity` warning).
- **B10:** add a portfolio-baseline staleness check — if latest `portfolio_scores.score_date` >35d,
  warn "run rationalization first".
- **B11:** define `eval_stale_after_days=30`; cache results in a new `portfolio_candidate_evals`
  table with `eval_date`; verdict card shows "Valid until …".
- **C2 (candidate side):** bake structured "show-your-work" JSON into the candidate-eval Grok prompt
  spec from the start (verdict + rationale_sentences with evidence tags).
- Append the `portfolio_candidate_evals` DDL note (table added to `schema.sql` at build time, not now).
- Update the doc's 11-test list to cover the new B-items + the JSON output; bump doc to **v1.1**.

---

## Phase 2 — Live rationalization script hardening (TDD, per-item)

Files: `windmill/u/admin/portfolio_rationalization.py` (+ `.script.yaml`/schema as noted) and tests
in `agent/tests/test_windmill_scripts.py`. Existing rationalization tests are **source-inspection**
style (`_read_pr_source()` + substring asserts, lines 1856–2010) — match that pattern, adding
behavioural import-and-execute tests where the change is logic (insider math, CAGR, red-flag override),
following the `research_tool` mock pattern already in the file.

For **each** item: write the test first (confirm RED) → implement (GREEN) → live Windmill run +
inspect the actual report output. Order = lowest-risk first.

1. **A1 (code):** rename the `# KEEP` table header to `# top-half` (`_build_ranking_table`,
   lines 648–668); rename `n_keep` → `n_top_half` with a clarifying comment. Test: header text +
   variable semantics. *Low.*
2. **A11:** extract a named `_apply_red_flag_override(recommendations, red_flags_map)` and call it
   explicitly in report assembly (currently enforcement is prompt-text only, lines 855–856). New test
   `test_red_flag_overrides_scenario_count`. *Low.*
3. **A5:** verify what `analyst_target` stores in `stock_data_fetcher.py` (read-only). If single-broker,
   switch to median/consensus; if already consensus, add a confirming comment. Test as appropriate. *Low.*
4. **A2 (code):** add a **metric-coverage** column to the renderer alongside factor coverage; rename
   the existing "Completeness" header to "Factor coverage"; compute raw-metric coverage from the
   sub-components in `_compute_factor_scores`. Test: both columns present + ratio math. *Low–Med.*
5. **A4:** normalise the insider sub-component as a **flow ratio** (`net_insider_90d / market_cap`)
   before percentile-ranking, instead of ranking raw net USD (sentiment calc, lines 469–479). Behavioural
   test on the normalisation. *Low–Med.* (changes ranking distribution → verify in live run.)
6. **A6:** make `_cagr` (lines 102–112) return the **negative** result instead of `None` when
   `ratio <= 0`, so negative-CAGR names rank as the pool minimum rather than being excluded.
   Behavioural test: `_cagr` negative input → negative output. *Med* (alters distribution + completeness
   penalty interaction → verify live).
7. **A10:** add `delta_rank_quality`, `delta_rank_growth`, `delta_rank_value` to the `delta_map`
   computation (lines 821–829), the upsert (lines 1062, 1090), `portfolio/schema.sql`, and a live-DB
   migration (`docker exec root-portfolio_postgres-1 psql …`). Test: delta computed for all 4 scenarios. *Med.*
8. **C2 (show-your-work JSON) — highest-leverage, riskiest:** modify Grok Call 1 prompt (lines 851–878)
   to emit structured JSON (`verdict` + `rationale_sentences` each with an `evidence` array of source
   metrics); add a parser + inline evidence rendering in the per-position scorecard. Keep a graceful
   fallback to plain-narrative if JSON parse fails. Test: prompt requests JSON + parser handles
   well-formed and malformed output. *Med–High — verify live output carefully.*
9. **A7:** split Grok **Call 1** into two batches (positions 1–15 / 16–31), concatenate outputs, to
   prevent silent truncation at `max_tokens=8000` (single call today, lines 880–890). Test: two Call-1
   batches issued. *Med — most disruptive to a working LLM flow; do last and inspect the live report for
   completeness/no mid-sentence cut-offs.*

**Schema migrations** (A10, and `portfolio_candidate_evals` when candidate eval is built): add to
`portfolio/schema.sql` AND apply to the live DB; never rely on schema.sql alone.

**Side observation (not a minimax finding):** `_send_email` (lines 737–748) references
`recipient_email` as a free variable but `main` takes it as a parameter (line 770) and the call site
(line 1042) doesn't pass it. The script runs live, so it's likely module-scoped — **verify during
Phase 2 and fix if it's a real `NameError` path.** Low priority.

---

## Explicitly NOT doing (declined / deferred)

- **C1** daily cost cap / rate limit — declined.
- **C3** per-position `synthesiser_model` tag — declined (stays footer-only, lines 1019–1024).
- **C4** `--no-llm` / `synthesis_mode` flag — declined.
- **C5** `eval_runs` schema normalisation — deferred by the review until a third eval-type exists.
- **A3, A8 (data path), A9 (panels)** — already resolved/mis-stated (see Reconciliation); doc-only touches.

---

## Verification

After Phase 1 (docs): re-read both framework docs for internal consistency; no code/test impact.

After each Phase 2 item:
```bash
docker exec root-straitsagent-1 python -m pytest tests/ -v   # green; new test added each item
```

After Phase 2 schema changes:
```bash
docker exec root-portfolio_postgres-1 psql -U portfolio_user portfolio -c "\d portfolio_scores"
# shows delta_rank_quality / _growth / _value
```

Live end-to-end (Windmill UI run of `portfolio_rationalization`), inspect the actual report for:
- `# top-half` header (not `# KEEP`)
- new metric-coverage column + "Factor coverage" rename
- inline evidence tags from the structured-JSON synthesis
- negative-CAGR positions surfacing as low ranks (not missing)
- batched Call-1 narrative complete with no mid-sentence truncation
- delta ranks rendered for all four scenarios

Commit per phase from `/root` (never `cd` into a subdir for git). Push only when asked.
