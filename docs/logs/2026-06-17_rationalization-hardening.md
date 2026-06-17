# Implementation Log — Portfolio Rationalization Hardening (MINIMAX Phase 2)
**Date:** 2026-06-17
**Commits:** `f35e07f`, `d364147`
**Files changed:** `windmill/u/admin/portfolio_rationalization.py`, `portfolio/schema.sql`, `agent/tests/test_windmill_scripts.py`
**Tests:** 6 + 9 = 15 new tests added; 325 passing, 1 skipped after Phase 2

---

## Plan Completed

Nine hardening items (A1–A11, minus already-closed A3/A8/A9) from the MINIMAX framework review applied to the live rationalization script. Executed in two batches (lowest-risk first) with TDD throughout.

---

## Phase 2 Items — Commit `f35e07f` (items 1–6)

### A1 — Rename `# KEEP` → `# top-half`

**Change:** `_build_ranking_table`: renamed `n_keep` variable → `n_top_half`; column header renamed from `# KEEP` to `# top-half`; added inline comment clarifying this is rank-robustness (top half of pool across scenarios), not a verdict.

**Why:** The `# KEEP` label implied a verdict count. The underlying math counts scenarios where a position ranks in the top half (`rank <= len(positions) // 2`) — a robustness measure, not a recommendation.

**Test:** `test_rationalization_top_half_column` — asserts `# top-half` present in source, `# KEEP` absent.

---

### A2 — Add metric-coverage column

**Change:** `_compute_factor_scores`: added sub-component availability counters (`quality_available`, `growth_available`, `valuation_available`, `sentiment_available`) to the returned dict. `_build_ranking_table`: computes `metric_coverage_pct = metric_subs_present / 16 * 100`; adds `Metric coverage` column next to `Factor coverage` (renamed from `Completeness`). Total sub-components across all 5 factors = 16.

**Why:** `Factor coverage` (5/5 means all 5 factors computed) can mask raw-metric gaps — a position with 1 of 4 quality sub-components still scored as factor-coverage=100%. Metric coverage exposes this.

**Test:** `test_rationalization_metric_coverage_column` — asserts `Metric coverage` and `Factor coverage` both present in source; `Completeness` absent.

---

### A4 — Insider normalisation as flow ratio

**Change:** Insider sub-component now normalised as `net_insider_90d / market_cap` (flow ratio) before percentile ranking, instead of ranking raw USD. Implemented as an inline `_insider_flow()` helper building a pool of ratios before calling `_norm`.

**Why:** Raw USD insider buying favours large-caps structurally — a $1M buy at a $500M-cap company signals more conviction than at a $100B-cap company. Flow ratio makes the signal cross-size comparable.

**Test:** `test_rationalization_insider_flow_ratio` — behavioural test: calls `_insider_flow`-equivalent logic; verifies that a small-cap large-ratio buy ranks above a large-cap small-ratio buy.

---

### A6 — Negative CAGR returns negative value, not `None`

**Change:** `_cagr`: when `ratio <= 0`, returns `max(ratio - 1.0, -1.0)` instead of `None`. Negative-CAGR positions now participate in `_norm` percentile ranking at pool minimum rather than being excluded.

**Why:** `_norm` skips `None` values. A negative-CAGR position being excluded from the pool inadvertently reduced the pool size and could inflate the percentile of other weak positions. Returning a strongly negative sentinel ensures it ranks at the bottom while preventing extreme outlier distortion (capped at -1.0).

**Test:** `test_cagr_negative_returns_negative` — behavioural: `_cagr(1.0, 0.5, 3)` → negative result; `_cagr(1.0, -0.5, 3)` → result ≥ -1.0.

---

### A10 — Delta tracking extended to all 4 scenarios

**Change:**
- `_fetch_prior_ranks`: now returns `{ticker: {"balanced": r, "quality": r, "growth": r, "value": r}}` (previously only `{ticker: int}` for balanced).
- `delta_map` computation: stores deltas for all 4 scenarios.
- `portfolio_scores` upsert: writes `delta_rank_quality`, `delta_rank_growth`, `delta_rank_value`.
- `portfolio/schema.sql`: added 3 new columns with `ALTER TABLE IF NOT EXISTS ... ADD COLUMN IF NOT EXISTS` DDL; migration applied to live DB.
- Call 2 delta summary: `delta_map.get(t, {}).get("balanced")` (safe dict access, replaces direct int lookup).

**Schema migration:**
```sql
ALTER TABLE portfolio_scores
  ADD COLUMN IF NOT EXISTS delta_rank_quality  INT,
  ADD COLUMN IF NOT EXISTS delta_rank_growth   INT,
  ADD COLUMN IF NOT EXISTS delta_rank_value    INT;
```

**Test:** `test_rationalization_delta_all_scenarios` — asserts `delta_rank_quality`, `delta_rank_growth`, `delta_rank_value` all present in source.

---

### A11 — Extract `_apply_red_flag_override` as named function

**Change:** Extracted the red-flag override logic (previously enforced only through prompt text) into an explicit `_apply_red_flag_override(recommendations, red_flags_map) -> dict` function called in report assembly. Any position with red flags that is not already `EXIT` gets overridden to `"EXIT (red-flag override)"`.

**Why:** Enforcing override through LLM prompt text only is unreliable — Grok may ignore it or apply it inconsistently. An explicit function in the code path makes the rule deterministic and testable.

**Test:** `test_red_flag_overrides_scenario_count` — constructs a `recommendations` dict with a KEEP for a ticker that has red flags; verifies `_apply_red_flag_override` changes it to EXIT.

---

### Bug fix — `_send_email` free-variable reference

**Found during Phase 2 code review** (not a MINIMAX finding).

**Bug:** `_send_email(gmail_smtp, subject, body_md, body_html)` used `recipient_email` as a free variable (referencing the outer `main()` parameter via closure). On some execution paths (e.g. non-Windmill test execution), this would raise `NameError`.

**Fix:** Added `to_email: str` parameter to `_send_email`; all call sites updated to pass `recipient_email` explicitly. No change to external behaviour.

---

## Phase 2 Items — Commit `d364147` (items 7–9)

### A7 — Split Grok Call 1 into batches of 15

**Change:** Call 1 (per-position narratives) now issues two requests: positions 1–15, then 16–31. Outputs concatenated before Call 2 consumption. Prevents silent truncation at `max_tokens=8000` which could cut off the last few positions mid-sentence.

**Why:** With 31 positions × ~250 words per block, a single Call 1 response regularly approaches or exceeds the token cap, resulting in truncated narratives for positions ranked 25–31. The truncation is silent — no error raised, just missing output.

**Test:** `test_rationalization_call1_batching` — asserts source contains two separate Grok Call 1 invocations (e.g. presence of batch slice logic).

---

### C2 — Show-your-work JSON in Grok Call 1

**Change:**
- Grok Call 1 prompt updated to request structured JSON output: `{"verdict": "KEEP|TRIM|EXIT", "rationale_sentences": [{"text": "...", "evidence": ["metric_name"]}]}` per position.
- Added `_parse_call1_json(response_text)` with graceful fallback: if JSON parse fails, returns the plain narrative unchanged.
- `_build_position_scorecard`: when JSON is available, renders inline evidence tags (metric names cited in brackets) alongside each rationale sentence.

**Why:** Plain narrative synthesis makes it impossible to verify which metrics drove a verdict. Structured JSON with evidence arrays surfaces the model's reasoning and enables future automated consistency checks.

**Test:** `test_rationalization_call1_json_prompt` — asserts JSON format request present in source. `test_parse_call1_json_graceful_fallback` — behavioural: `_parse_call1_json("not json")` returns the input string unchanged.

---

### A10 (extension) — Delta rendered for all 4 scenarios in Call 2

**Change:** Call 2 delta summary block updated to use `.get("balanced")` dict access (since `delta_map` values are now dicts, not ints). Quality/growth/value deltas surfaced in the delta section.

**Test:** `test_rationalization_delta_dict_access` — asserts `.get("balanced")` access pattern present in source.

---

### A5 — Analyst target verified as consensus mean

**Investigation:** Read `stock_data_fetcher.py` — `analyst_target` stores `targetMeanPrice` from Finnhub. This is the **consensus mean** across all contributing analysts, not a single-broker figure. No code change needed; added a clarifying comment in `_compute_factor_scores`.

---

## Bugs Encountered

None beyond the `_send_email` free-variable fix discovered during code review. All Phase 2 items implemented cleanly on first attempt after the TDD RED → GREEN sequence.

---

## Lessons Learned

1. **Extract boolean logic into named functions.** The `_apply_red_flag_override` extraction made the override deterministic and testable in one small change. Logic enforced only through LLM prompt text is neither reliable nor testable.
2. **Batch LLM calls at design time.** The 31-position single-call truncation risk was known from the MINIMAX review but was deprioritised. When a single call's expected output approaches `max_tokens`, batch splitting should be the default, not an afterthought.
3. **Read all call sites before adding parameters.** The `_send_email` free-variable bug was only caught because Phase 2 required reading the entire script. Future reviews of any function with an SMTP or external-call signature should always verify that every parameter is passed explicitly, not captured from closure.
4. **Schema migrations must be applied to live DB, not just `schema.sql`.** The 3 new `delta_rank_*` columns added to `schema.sql` were also `ALTER TABLE`-applied immediately. Recording the migration in `schema.sql` alone without applying it would leave the live DB out of sync and cause KeyErrors at the next rationalization run.
