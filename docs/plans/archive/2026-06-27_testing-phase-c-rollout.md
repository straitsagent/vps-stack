---
Subject: Testing Phase C Rollout — ASD + artifact harness for 7 remaining scripts
Date: 2026-06-27
Status: draft
Planner model: claude-opus-4-8
Executor model: Claude Code | deepseek/opencode (one script per session)
Risk tier: LOW per script (read + test additions only, no behavior change)
Hard Rules in force: [12, 15, 17, 20]
Complies with: docs/EXECUTOR_CONTRACT.md
Files to read before coding: CLAUDE.md, docs/TESTING.md, docs/EXECUTOR_CONTRACT.md, docs/logs/2026-06-23_testing-gap-analysis-implementation.md
---

# Plan: Testing Phase C Rollout

## Context

`docs/logs/2026-06-23_testing-gap-analysis-implementation.md:79,96` explicitly marked
"Phase C rollout — apply ASD + seam factoring + harness + word-count test + Tier 0
markers to 7 remaining scripts" as **Pending**.

The reference implementation is `health_check.py` + its tests — it has an `_HC_ASD` dict
(Artifact Specification Document), `ARTIFACT_MARKERS`, seam-factored pure functions, a
≥500-word Telegram test, and 10 artifact tests. Every other sending script in the stack
should reach the same level.

This is a multi-session, one-script-at-a-time effort. This plan is the framework; each
script gets its own sub-checklist in a dedicated session. **Do not batch multiple scripts
in one session** (feedback_batch_testing: one unit → verify → next).

The 7 scripts, in the defined execution order (testing-gap log line 79):

1. `macro_research`
2. `portfolio_email`
3. `portfolio_review`
4. `portfolio_rationalization`
5. `portfolio_move_monitor`
6. `portfolio_analyst_alert`
7. `youtube_monitor`

## What gets applied to each script (the Phase C pattern)

From `docs/TESTING.md` and the health_check reference:

- **ASD dict** (`_<SCRIPT>_ASD`) — pre-implementation spec with named constants for every
  user-visible artifact field (subject line, key financial figures, section headers, Telegram
  min word count). Tests source from this, never from the rendered output.
- **Seam factoring** — pure functions that take data → return formatted strings/dicts,
  testable without API calls or DB.
- **Artifact harness** — ≥1 end-to-end test that calls `main()` with I/O faked only at the
  edges and asserts all ASD constants appear in the rendered email body AND Telegram message.
- **Word-count test** — `len(msg.split()) >= 500` for every Telegram sending script (Hard
  Rule 16).
- **Tier 0 markers** — `ARTIFACT_MARKERS` list in the script; health_check reports against
  it; used to detect partial/missing output sections.

## Files changed (per script — template)

| Action | Path | Change |
|--------|------|--------|
| Edit | `windmill/u/admin/<script>.py` | Add `_<SCRIPT>_ASD`, `ARTIFACT_MARKERS`, seam-factored pure functions |
| Edit | `windmill/u/admin/<script>_telegram.py` | (if Telegram formatter exists) Add `ARTIFACT_MARKERS` |
| Edit | `agent/tests/test_windmill_scripts.py` | Add ASD-driven artifact tests + word-count test |

## Per-script checklist (apply to each, in order)

For **each** of the 7 scripts, in a dedicated session:

- [ ] **Read the script** — understand current output structure (sections, fields).
- [ ] **Author the ASD dict** — define every user-visible field as a named constant.
  Get owner approval on the ASD before writing any test (Hard Rule 10 analogue — the ASD
  is the contract).
- [ ] **Write RED tests** — artifact harness tests that FAIL on current code (because ASD
  constants don't exist yet). Run RED, paste output.
- [ ] **Add ASD + seam factor + markers** — edit the script to introduce the ASD, any
  pure-function seams, and `ARTIFACT_MARKERS`. Tests must now pass (GREEN). Run GREEN, paste.
- [ ] **Add word-count test** (if sends Telegram) — `len(msg.split()) >= 500`.
- [ ] **Full suite** — paste tail confirming ≥previous pass count, no new failures.
- [ ] **Deploy** — autopush or `wmill script push`. Confirm no missing-resource warnings.
- [ ] **Live verify** — run the script in Windmill; confirm email + Telegram artifacts match
  ASD fields. Paste evidence (table, email subject, outbox row).

## Locked Oracle Tests (G1)

No global locked oracle — each script is LOW-risk (test + marker additions, no logic change).
Per-script RED→GREEN proof is the verification gate. Reviewer validates the harness test is
not tautological (must fail on pre-ASD code).

## RED-proof requirement (G2)

Per script, paste:
```bash
python3 -m pytest agent/tests/test_windmill_scripts.py -k "test_<script>_artifact" -v
# BEFORE ASD addition: FAILED
# AFTER ASD addition: PASSED
```

## Asserting Verification Script (G4)

Per script:
```bash
fail=0
# 1. Test count increased by at least 2 (ASD harness + word-count)
PREV=<N>; NEW=$(python3 -m pytest agent/tests/test_windmill_scripts.py -q 2>&1 | grep -oP '\d+ passed' | head -1 | grep -oP '\d+')
[ "$NEW" -ge "$((PREV+2))" ] && echo "PASS: test count grew" || { echo "FAIL: expected ≥$((PREV+2)) got $NEW"; fail=1; }
# 2. ASD present in script source
grep -q "_<SCRIPT>_ASD" /root/windmill/u/admin/<script>.py && echo "PASS: ASD present" || { echo "FAIL"; fail=1; }
# 3. ARTIFACT_MARKERS present
grep -q "ARTIFACT_MARKERS" /root/windmill/u/admin/<script>.py && echo "PASS: markers present" || { echo "FAIL"; fail=1; }
# 4. Live artifact (paste email subject + Telegram word count from Windmill run)
[ $fail -eq 0 ] && echo "PASS" || exit 1
```

## Acceptance Gate (per script)

- [ ] ASD authored and owner-approved (contract in place before tests written)
- [ ] RED proof pasted (G2)
- [ ] GREEN proof pasted (G2)
- [ ] Full suite ≥previous+2 passed (G2)
- [ ] Live email + Telegram artifacts match ASD fields (G3/G4)
- [ ] No behavior change — existing tests still pass, no functional diff

## Execution

This is a framework plan. Per-script execution:

1. Set Status: executing when the first script session begins; update the per-script checklist as
   each script is completed (tick the ✓ for that script's sub-checklist).
2. Work one script at a time. Do not proceed to the next until the current one's Acceptance Gate
   is satisfied and committed.
3. Set Status: done when all 7 scripts are complete.
Satisfy all five gates in `docs/EXECUTOR_CONTRACT.md`; STOP on any deviation.
Do not redesign. If the plan is ambiguous or wrong, stop and report — do not improvise.

## Progress tracker

- [ ] 1. macro_research
- [ ] 2. portfolio_email
- [ ] 3. portfolio_review
- [ ] 4. portfolio_rationalization
- [ ] 5. portfolio_move_monitor
- [ ] 6. portfolio_analyst_alert
- [ ] 7. youtube_monitor
