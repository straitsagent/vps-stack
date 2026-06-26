# DeepSeek Implementation Review — 2026-06-26

**Reviewer:** Claude Opus 4.8 (Claude Code)
**Reviewed commits:** `215689d` → `6af7de9` (4 plan-execution commits)
**Plans reviewed:** earnings-surprises-fetcher-fix, macro-daily-push-disposition, portfolio-thesis-seeding, position-sentinel-phase1
**Cleanup commit:** `8a8e76e`

---

## Review Method

Independent artifact verification — did not trust implementation logs. Queried live DB directly,
ran the full test suite inside the container, diffed committed tests against the locked-oracle
blocks in each plan, and inspected the actual code changes. The review gate from
`docs/EXECUTOR_CONTRACT.md` was the checklist.

---

## Findings by Plan

### 1. `earnings-surprises-fetcher-fix` — ACCEPTED

**Root cause fix correct.** `_pick_col` helper broadens detection from `"actual" in name` to
`["reported", "actual"]`, catching yfinance's `Reported EPS` column. One-line, clean.

**Helpers well-isolated.** `_pick_col`, `_is_blank`, `_extract_surprises` are pure functions with
no pandas dependency — exactly as specified in the plan.

**Locked oracle honored.** The critical anti-tautology trap: the plan's oracle required asserting
the *recomputed* `surprise_pct` of `3.608` (from `(2.01-1.94)/1.94×100`), not the fixture's
native `3.46`. The committed test asserts `abs(first["surprise_pct"] - 3.608) < 0.01`. This is
the strongest signal that DeepSeek read and respected the oracle rather than gaming it.

**Live DB verified:**
- `earnings_surprises`: 132 rows / 33 tickers, all `surprise_pct` non-null
- AAPL sample: `[3.6082, 6.3670, 4.5198, 9.7902]` — matches oracle exactly

**Secondary issue discovered and resolved by executor.** `lxml` was missing from the Windmill
worker; `t.earnings_dates` was silently throwing during worker runs. Executor added `lxml==5.3.0`
to the lock file and redeployed. This was not in the plan but was a correct, necessary fix.

**Noted out-of-scope item.** `research_tool.py:585` has an identical column-detection bug
affecting earnings markdown in research reports (does not touch the DB table). Logged for a
later hygiene pass.

**Test count:** 3 new tests (RED→GREEN confirmed). Full suite: 481 passed, no regressions at that point.

---

### 2. `macro-daily-push-disposition` — ACCEPTED

**Mechanical plan, executed correctly.**

**Server schedule deleted.** `schedules/get/u%2Fadmin%2Fmacro_daily_push` → HTTP 404 (verified live).

**Disk file removed.** `windmill/u/admin/macro_daily_push.schedule.yaml` — gone (git rm, not delete).

**Critical invariant respected.** `macro_daily_push_telegram.py` (the LIVE formatter dispatched by
`macro_research`) was not touched. Formatter count held at 8 (at that point). The test at
`test_windmill_scripts.py:4570` asserting `macro_research must dispatch macro_daily_push_telegram`
still passes.

**`macro_daily_push.py` retained.** 4 tests for the main (parked) script still green.

**No regressions.** `macro_daily_push` + `macro_research` tests: 33 passed.

---

### 3. `portfolio-thesis-seeding` — ACCEPTED WITH CONFIRMED MODEL DEVIATION

**Model deviation: Grok-4.3 substituted for Deepseek-chat (owner confirmed in this review session).**
The plan specified `deepseek-chat`. The executor used `grok-4.3` with `reasoning_effort=medium`.
Per G5, this should have been reported to the owner mid-execution rather than self-certified in
the log. The swap was legitimate (owner had already approved Grok-4.3 for reasoning tasks), but
the process deviation was noted. Owner has since confirmed the swap was approved. Hard Rule 10
respected — the LLM prompt was unchanged from plan approval.

**Seeder design correct.** `_build_thesis_prompt`, `_parse_thesis_response` are pure helpers.
Write-if-absent guard (no-clobber) verified: re-run shows all 33 `skipped_existing`.

**Locked oracle honored:**
- `"high"` → `"High"` (normalization) ✓
- `"Strong"` → `"Medium"` (invalid conviction default) ✓
- blank/malformed → `None` (empty-artifact guard) ✓
- Prompt contains JSON schema keys + `"ONLY"`, no persona words ✓

**Live DB verified:**
- `portfolio_thesis`: 33 rows, 22 Medium / 11 High
- Conviction domain: only `{Medium, High}` present — no `Low` seeded (plausible given research quality; domain constraint satisfied)
- `[auto-draft]` prefix present on all rows (no-clobber marker)

**Downstream effect confirmed.** `portfolio_rationalization` Thesis factor (10% weight) now has
data. Previously all 33 positions scored 0 on this factor.

**Test count:** 4 new tests (RED→GREEN). Full suite: 485 passed.

---

### 4. `position-sentinel-phase1` — ACCEPTED AFTER CLEANUP

**Functionally complete. Three required documentation checklist items were skipped before the
plan was flipped to `done`. This is a review-gate violation (G3/Acceptance Gate).**

#### Code and schema — correct

- `position_events` and `position_signals` tables exist in live DB.
- `position_sentinel.py`: 7 pure helpers, all unit-tested.
- `position_sentinel_telegram.py`: 9th formatter, markdown-driven architecture.
- Deepseek materiality triage prompt used as approved.
- Thresholds correct: ≤-8%/3d, ≤-12%/5d, ≤-20% vs 20d-high.
- Schedule YAML present for Phase 2 activation (not yet enabled — correct for Phase 1).

#### Locked oracle — honored (with one observation)

The plan's BABA oracle was authored as prose (`≈ -11.5`, `≈ -27.3`) rather than exact
code snippets, which meant DeepSeek had to author the tolerance. It chose `< 2.0` for both
assertions. This is defensible (the underlying math is correct) but illustrates that
**prose oracles don't fully deliver "copy verbatim"** — future HIGH-tier plans should embed
the assertion as code, not prose. The structural logic oracles (price_signal fires, silent on
calm, parse_materiality clamps, confluence requires both) were fully correct.

**BABA live check:** 0 signals fired on the 2026-06-26 run. Expected — BABA prices have
recovered from the June crash that motivated this build. The math is proven by the unit tests;
the absence of a live signal is not a miss.

#### Test count: 8 new tests (RED→GREEN). Full suite: 492 passed, 1 skipped.

#### Documentation gaps (closed by cleanup commit `8a8e76e`)

Three items from the plan's Files-changed checklist were not executed:

| Skipped item | Plan reference | Status |
|---|---|---|
| `CLAUDE.md` formatter count 8→9; list `position_sentinel_telegram` | Plan line 150 | Fixed in `8a8e76e` |
| `ROADMAP.md` Position Sentinel pillar | Plan line 150 | Fixed in `8a8e76e` |
| `WORKFLOW_ARCHITECTURE.md` sentinel spec | Plan line 150 | Fixed in `8a8e76e` |

Hard Rule 19 (`all 8 carry identical _send_telegram copies`) also updated to 9.

---

## Other Items Resolved

### Uncommitted `stock_data_fetcher.script.yaml`

Working-tree modification was present but uncommitted after the fetcher-fix commit. The diff was
a metadata normalization: field reorder, `format: resource-postgresql` annotation on `portfolio_db`,
`finnhub_key` and `ticker` default values adjusted. No behavioral change. Committed in `8a8e76e`.

### Grok-4.3 model swap for thesis-seeding

Owner confirmed during this review session that the Grok-4.3 swap was approved at execution time.
Accepted. Model deviation noted above for process hygiene.

---

## Test Suite — Final State

```
492 passed, 1 skipped
```

No regressions across any of the 4 plan executions. New test breakdown:
- earnings-surprises: +3 (481 total after)
- thesis-seeding: +4 (485 total after)
- position-sentinel: +8 (492 total after, 1 skipped)
- macro-disposition: +0 (mechanical — no new code)

---

## Process Observations (for future handoffs)

1. **Prose oracles in HIGH plans create ambiguity.** The sentinel plan embedded expected values
   as prose (`≈ -11.5`) rather than as copy-pasteable Python assertions. Future HIGH-tier plans
   should embed the assertion as a frozen code block so "copy verbatim" is unambiguous.

2. **Plan flipped to `done` before docs gate was satisfied.** The acceptance gate explicitly
   listed the three CLAUDE.md/ROADMAP/WORKFLOW_ARCHITECTURE edits. The executor marked done
   without completing them. The review gate caught this — which is the system working correctly —
   but the executor should self-check the acceptance gate before self-certifying.

3. **Model deviation should be reported, not self-certified.** G5 (STOP on deviation) applies
   to model selection changes, not just code surprises. The executor chose Grok-4.3 and noted it
   in the implementation log rather than stopping to report. The outcome was fine (owner approved),
   but the process should be: deviation → report → continue after confirmation.

4. **Secondary bug discovery handled correctly.** The `lxml` missing-dependency issue was not in
   the plan. Executor identified it, fixed it (lock file + redeploy), and logged it clearly.
   This is the correct behavior for G5: improvise on environment issues only when the fix is
   minimal, reversible, and clearly logged.

---

## Conclusion

All four plans are now fully accepted. The implementation quality is high — locked oracles were
respected, tests are substantive (not rubber-stamp), and live DB state matches every claimed
artifact. The review gate worked as designed: it surfaced the sentinel docs gap that would
otherwise have left three architecture documents inconsistent with live code.
