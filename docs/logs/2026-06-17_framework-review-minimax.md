# Implementation Log — Portfolio Framework Review (MINIMAX)
**Date:** 2026-06-17
**Commits:** `e8bf9dd`, `46bceca`
**Session type:** Review + doc update — no live script changes
**Files changed:** `docs/audit/260616_framework_review_minimax.md` (new), `docs/audit/260617_framework_review_incorporation_plan.md` (new), `docs/portfolio_rationalization_framework.md`, `docs/portfolio_candidate_eval_framework.md`

---

## Plan Completed

A read-only MINIMAX review of both portfolio framework documents and the live rationalization script, producing 26 findings. Owner reviewed and approved an incorporation plan. Phase 1 (doc alignment) executed immediately; Phase 2 (live script hardening) and Phase 3 (candidate eval build) deferred to dedicated sessions.

---

## Review Inputs

1. `docs/portfolio_rationalization_framework.md` (482 lines, v1.1)
2. `docs/portfolio_candidate_eval_framework.md` (339 lines, v1.0)
3. `windmill/u/admin/portfolio_rationalization.py` (1,122 lines, live)
4. `windmill/u/admin/portfolio_rationalization.script.yaml`
5. `windmill/u/admin/portfolio_rationalization_monthly.schedule.yaml`
6. Live report output: `research/portfolio/rationalization_2026-06-14.md`
7. DB schemas: `portfolio_thesis`, `fundamental_data`, `valuation_snapshots`, `financial_health_metrics`, `company_profiles`, `price_history`, `fx_rates`

---

## 26 Findings Summary

**Part 1 — Rationalization (A1–A11):** 4 HIGH, 5 MEDIUM, 2 LOW

| ID | Priority | Finding |
|---|---|---|
| A1 | HIGH | `# KEEP` column math is rank-robustness, not a verdict — label misleads |
| A2 | HIGH | Completeness column is factor-level, not raw-metric level — column conflates two concepts |
| A3 | HIGH | Min-pool guard (`≥8`) appears in framework doc but not enforced in `_norm` code path |
| A4 | HIGH | Insider sub-component ranks raw USD, not flow ratio — large-caps dominate |
| A5 | MED | `analyst_target` field origin unclear — may be single broker not consensus |
| A6 | MED | `_cagr` returns `None` for negative ratios — negative-CAGR names excluded from pool ranking |
| A7 | MED | Grok Call 1 sends all 31 positions in one call at `max_tokens=8000` — silent truncation risk |
| A8 | MED | ADR pair consolidation still hardcoded in framework doc comment despite code fix |
| A9 | MED | Framework doc shows C1/C2/C4 panels per position; live renderer collapses to C3 only |
| A10 | LOW | Delta tracking only covers balanced scenario; quality/growth/value deltas computed but not stored |
| A11 | LOW | Red-flag override logic is prompt-text only, not an extractable named function |

**Part 2 — Candidate Eval (B1–B11):** 5 HIGH, 6 MED

| ID | Priority | Finding |
|---|---|---|
| B1 | HIGH | Price history date-range guard unspecified — undefined behaviour for tickers with short history |
| B2 | HIGH | No fundamental correlation sub-check in Gate 2 — price correlation alone misses concentrating adds |
| B3 | HIGH | Factor gap-fill math undefined — "fills a portfolio gap" is unverifiable without explicit thresholds |
| B4 | HIGH | `min_pool=3` too thin for reliable percentile ranking — raise to 5 |
| B5 | HIGH | Thesis fallback `[derive from metrics]` gives LLM implicit authority to invent a thesis |
| B6 | MED | ADD/WATCH/PASS thresholds are descriptive prose, not numeric — verdict is not deterministic |
| B7 | MED | No `replacement_ticker` parameter — can't evaluate swap logic |
| B8 | MED | No currency-exposure dimension in Gate 2 — HKD/USD concentration not checked |
| B9 | MED | No `_validate_universe` heterogeneity guard — user-supplied ticker lists unchecked |
| B10 | MED | No baseline staleness check — stale `portfolio_scores` used silently |
| B11 | MED | No eval TTL / caching — each call re-runs from scratch |

**Cross-cutting (C1–C5):** 0 HIGH, 5 MED/LOW — all declined or deferred

---

## Owner Decisions

- **A1**: rename column — approved.
- **A3, A8 (data), A9 (panels)**: already resolved or mis-stated after code review — closed.
- **C1** (daily cost cap), **C3** (per-position model tag), **C4** (`--no-llm` flag), **C5** (schema normalisation): all explicitly declined.
- **C2** (show-your-work JSON): implement in rationalization only for now (apply to candidate eval at build time).
- **B4**: raise `min_pool` 3 → 5: approved.

---

## Tasks Performed (Phase 1 — Doc Alignment)

1. Created `docs/audit/260616_framework_review_minimax.md` — 724-line full review (findings, evidence, recommendations)
2. Created `docs/audit/260617_framework_review_incorporation_plan.md` — reconciliation of 26 findings, owner decisions, Phase 1/2/3 work breakdown
3. Updated `docs/portfolio_rationalization_framework.md` (v1.1 → v1.2):
   - A1: renamed `# scenarios KEEP` → `# top-half` with explanatory note
   - A9: corrected Section C description — C1/C2/C4 per-position, C3 single combined block; removed duplicate C3 header
   - A8: added sentence noting ADR consolidation now sources from `consolidation_group` (not hardcoded)
   - A2: clarified factor coverage vs raw-metric coverage distinction; cross-referenced new metric-coverage column to be added in Phase 2
   - Softened "15,000–20,000 words" target to a soft range
4. Updated `docs/portfolio_candidate_eval_framework.md` (v1.0 → v1.1) — applied all 11 B-findings + C2 to make the design build-ready:
   - B1: date-range guard spec + `gate2_warn` flag
   - B2: fundamental cosine similarity sub-check
   - B3: gap-fill math (`pool_median_F / pool_p60_F`, ≥2 factors = gap-fill)
   - B4: `min_pool` 3 → 5; `below_min_universe` flag
   - B5: explicit "LLM-derived, not user-validated" thesis fallback language
   - B6: numeric ADD/WATCH/PASS thresholds
   - B7: `replacement_ticker` parameter
   - B8: currency-exposure dimension (HKD 30% soft limit)
   - B9: `_validate_universe` heterogeneity guard
   - B10: baseline staleness check (>35d warns)
   - B11: `eval_stale_after_days=30`, `portfolio_candidate_evals` DDL note
   - C2: show-your-work JSON in Grok prompt spec; test list updated (335 target)

---

## Bugs / Issues

None — this was a doc-only phase with zero live code changes.

---

## Lessons Learned

1. **Review before building.** The candidate eval design had 5 HIGH findings before a single line of code was written. Addressing them in the doc (30 min) prevented expensive retrofits to a 1,000-line script.
2. **Cross-reference doc and code explicitly.** Three findings (A3, A8, A9) were stated as missing in the review but were already implemented in the live code. Future reviews should include a code-verification step for each finding before classifying it as open.
3. **"KEEP" as a column label is a verdict, not a rank metric.** Even experienced readers infer verdict from a column named `# KEEP`. Rank-robustness counts need different naming from the start.
