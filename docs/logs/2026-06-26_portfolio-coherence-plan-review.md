# Portfolio Coherence Planning Docs — Review & Correction Log

**Date:** 2026-06-26
**Scope:** Review of opencode/Deepseek-written Portfolio Coherence planning docs against CLAUDE.md
standards and the actual codebase; correction of all issues found.

## Background

opencode (with owner consultation) wrote four planning documents in commit `f75c03f`:

- `docs/design/2026-06-26_portfolio-coherence-seams-design.md`
- `docs/plans/2026-06-26_advisor-coherence-a-idea-pipeline.md` (Plan A — Initiative A, build order 2)
- `docs/plans/2026-06-26_advisor-coherence-b-replacement-screener.md` (Plan B — Initiative B, build order 3)
- `docs/plans/2026-06-26_advisor-coherence-c1-close-loop.md` (Plan C1 — Initiative C, build order 1)

The plans were structurally correct — full front-matter, Context sections, Files-changed tables,
RED→GREEN proofs, asserting verify scripts, acceptance gates, and Execution footers — but contained
factual errors about the existing codebase that would have caused executor failures. A plan review
was done before any `approved` status was set, reading the actual scripts alongside the plans.

## Files verified against plans

| File | Key facts checked |
|---|---|
| `windmill/u/admin/portfolio_rationalization.py` | Scoring function names and structure, front-matter dict, report assembly, dispatch helper |
| `windmill/u/admin/portfolio_candidate_eval.py` | main() signature, dispatch helpers, 3-gate logic |
| `windmill/u/admin/youtube_monitor.py` | `_dispatch_formatter` signature and call site |
| `windmill/u/admin/morning_news_digest.py` | main() signature, md write location, dispatch capability |
| `portfolio/schema.sql` | `portfolio_candidate_evals`, `portfolio_scores`, `watchlist_ideas` |

## Issues found and fixed

### Critical (would block executor on first step)

**C1 — Nonexistent function names in Plan A Step 0 and design §Part E.**
Plans described extracting `_score_valuation`, `_score_quality`, `_score_growth`, `_score_sentiment`,
`_score_thesis`, `_compute_composite`, `_apply_scenario_weights` from `portfolio_rationalization.py`.
None of these names exist. The actual functions are:
`_norm` (458), `_evaluate_red_flags` (433), `_cagr`, `_compute_factor_scores` (469) — one function
containing all 4 quant factors inline, `_apply_thesis_scores` (563), `_compute_composites` (590)
— combines compositing and scenario weighting, `_rank_positions` (653).
The 4 scenarios are keyed `balanced`/`quality`/`growth`/`value`, not "Balanced/Quality-tilted/…".
All fixed in Plan A Step 0 and design §Part E with real names and line numbers.

**C2 — Oracle tested trivial sort, not actual scoring.**
`_compute_factor_scores` scores factors as percentile ranks within the pool via `_norm`. A candidate
has no standalone composite — it must be scored in the union pool (33 holdings + candidate).
Plan A's `test_prescreener_rank_insertion` oracle received pre-computed composites and tested only
a trivial sort (tautology, Hard Rule 20 failure mode #3). Fixed: oracle renamed to
`test_compute_candidate_ranks_sort` (accurate about what it tests), union-pool approach
documented in §Step 0 and prescreener section, mandatory executor-authored pooled-scoring test
(`test_prescreener_pooled_scoring`) added as a requirement.

**C3 — idea_extractor dispatch signature mismatch.**
Plan A said to dispatch `idea_extractor` by adding one `_dispatch_formatter(...)` call.
But `_dispatch_formatter` hard-codes `{md_path, telegram_bot_token, telegram_owner_id, portfolio_db}`
— it cannot pass `source` (youtube vs news) or `deepseek_key`, both required by `idea_extractor`.
Fixed: `_dispatch_idea_extractor(md_path, source, portfolio_db, deepseek_key, wm_token)` specified
as a new ~12-line dedicated helper, to be copied into both scan scripts.

**C4 — Stale schedule migration step.**
Plan A Step 8 and design §Part D described migrating rationalization from `'0 0 21 * * 1'` (Monday
9 PM SGT) to `'0 0 6 * * 6'` (Saturday 6 AM SGT). This was already done 2026-06-25 (commits
`2563fc9`, `514f3a1`, `04c16b9`). An executor would waste time or cause a regression attempting
it again. Fixed: Step 8 replaced with "confirm already Saturday AM" grep check; design §Part D
rewritten as "Done 2026-06-25 — no change needed."

### Moderate (correctness / clarity)

**M1 — Plan C1 oracle self-contradictory (stub returning None).**
The oracle defined `_render_monitored_candidates_stub` that `return None`, with a comment
"Replace with actual import in committed code." But G1 says locked assertions may not be edited
— yet `assert out != ""` could only pass if the executor changed the stub. Also, the plan spec
`_render_monitored_candidates(cur, since_days=60)` (takes a DB cursor) cannot be tested with
rows fed directly. Fixed: split into pure `_render_monitored_candidates(rows: list[dict]) -> str`
+ `_query_monitored_candidates(cur, since_days=60) -> list[dict]`; oracle now imports the real
pure function directly with no stub.

**M2 — Oracle/prose function-name mismatch.**
Plan A oracle used `parse_extraction_response` (no underscore), prose used `_parse_extraction_response`.
Plan B oracle used `select_top_replacements`, prose used `_select_top_replacements`.
Fixed: leading underscore applied consistently to oracle names (oracle is the authoritative form).

**M3 — Section D query could list same ticker twice.**
`portfolio_candidate_evals` is UNIQUE(eval_date, ticker) not UNIQUE(ticker) — a ticker evaluated
twice in 60 days produces two rows. Fixed: query updated to
`SELECT DISTINCT ON (ticker) … ORDER BY ticker, eval_date DESC` (latest verdict per ticker).

**M4 — G4 verify items 3&4 passed on empty artifacts.**
Plan A verify items 3&4 printed ">=0 is expected" — they passed with zero candidates, giving a
false green on a HIGH-risk plan (contract §Pre-done #1 empty-artifact failure mode). Fixed: items
now seed a `VERIFY_SEED` row and assert `>= 1`; item 4 (shortlisted rows) asserts `>= 1` after
a full pipeline run.

**M5 — No check on `recommendation` string values.**
`portfolio_scores.recommendation` is bare TEXT with no CHECK constraint. Plan B's
`IN ('EXIT','TRIM')` filter silently returns nothing if the writer emits different case.
Fixed: Step 1b added to Plan B — pre-flight `SELECT DISTINCT recommendation FROM portfolio_scores`
before any code is written.

**M6 — Phantom `factor_scorer` dependency in Plan B.**
Plan B said it "imports `factor_scorer` only for reading the prescreener output structure."
The output structure is plain dict keys (`prescreen_rank`, `prescreen_score`); no import needed.
Fixed: Depends-on line updated; phantom import reference removed.

### Minor / cosmetic

**N1 — Three competing numbering schemes.** Plan files use Initiative letters (A/B/C = idea/
replace/close), subjects use "Phase N" (1/2/3 = close/idea/replace = build order), design uses
"Plan N." An executor opening "Phase 1" would find file `c1`. Fixed: "Initiative X — build order
N of 3" label added to front-matter of all three plans.

**N2 — `.swift` typo.** Design doc and Plan A each called the Python script
`portfolio_rationalization.swift`. Fixed to `.py`.

**N3 — Non-standard risk tier.** Plan C1 used "MEDIUM" — not a valid tier in EXECUTOR_CONTRACT.md
(only HIGH/LOW). Plan C1 has a planner-authored oracle, so it is HIGH. Fixed.

**N4 — Approximate line references.** Plan A front-matter pointed to candidate_eval dispatch at
"1426-1450" as a single block. The actual structure: stock dispatch 1426-1435 (via helper
`_dispatch_stock_fetcher` at 124-130), research dispatch 1437-1450 (via helper
`_dispatch_research_tool` at 186-192). Executor note: **poll loops are in the helpers, not main**.
Fixed in front-matter and prescreener section.

**N5 — Idempotency undocumented.** `watchlist_ideas` UNIQUE(ticker, source) + ON CONFLICT DO NOTHING
means an archived ticker never re-enters the pipeline. This is an intentional design decision but
was undocumented. Fixed: one-sentence idempotency note added to design §4 status lifecycle.

## What was NOT changed

The core designs are sound and were not altered:
- Reuse of rationalization scoring via shared `factor_scorer` module (correct instinct; verified DB-decoupled)
- `watchlist_ideas` as a single convergence store for all three initiatives
- Sector-agnostic replacement selection as an explicit owner decision
- Saturday dispatch chain architecture (A/B/C/pipeline order)
- Cost estimate, all schema-column claims for `portfolio_candidate_evals`/`portfolio_scores`

## Outcome

All four documents were updated in a single commit (`fb10b03`). The three plan files remain
`Status: draft` — owner approval is the next step before any plan proceeds to `executing`.
