---
Subject: Fix research_tool.py column-detection bug — "Reported EPS" silently dropped
Date: 2026-06-27
Status: draft
Planner model: claude-opus-4-8
Executor model: Claude Code | deepseek/opencode
Risk tier: LOW (one-line fix, touches a working script — RED test required)
Hard Rules in force: [12, 15, 17]
Complies with: docs/EXECUTOR_CONTRACT.md
Files to read before coding: CLAUDE.md, docs/EXECUTOR_CONTRACT.md, windmill/u/admin/research_tool.py (lines 560-650), windmill/u/admin/stock_data_fetcher.py (lines 480-570)
---

# Plan: Fix research_tool.py "Reported EPS" column-detection bug

## Context

`windmill/u/admin/research_tool.py:581` uses `next((c for c in ed_df.columns if "actual"
in str(c).lower()), None)` to find the realized-EPS column in `yfinance.Ticker.earnings_dates`.
Current yfinance labels that column **"Reported EPS"** (not "EPS Actual" / "Actual"), so
`actual_col` resolves to `None`, the `if actual_col:` guard at line 583 fails, and the
**"### Recent EPS Surprises"** table (lines 586-588) plus the structured `data["surprises"]`
list are silently dropped from every research report email.

The identical bug was already fixed in `stock_data_fetcher.py:566` — that script uses
`_pick_col(ed_df.columns, ["reported", "actual"])`, which matches "Reported EPS" first and
falls back to the legacy "actual" label. This plan applies the same pattern to
`research_tool.py`.

This change is prompted by the 2026-06-27 implementation-log review which explicitly flagged
the twin bug at `research_tool.py:585` as "identified, not yet fixed" (earnings-fix log,
deepseek-implementation-review log).

## Files changed

| Action | Path | Change |
|--------|------|--------|
| Edit | `windmill/u/admin/research_tool.py` | Line 581 — add `"reported"` to keyword check |
| Edit | `agent/tests/test_windmill_scripts.py` | Add `test_earnings_calendar_reported_eps_column` — RED before GREEN |

## Checklist

- [ ] **Step 1 — RED test.** Add `test_earnings_calendar_reported_eps_column` to
  `agent/tests/test_windmill_scripts.py` after the existing earnings-calendar tests (~line
  1446). The test builds a minimal fake `earnings_dates` DataFrame with a `"Reported EPS"`
  column (and a matching `"EPS Estimate"` column) and asserts that `_fetch_earnings_calendar`
  (called on a mock Ticker that returns this DataFrame) renders a non-empty
  `"Recent EPS Surprises"` section. Run — must FAIL on current code (RED). Paste the RED
  output.

- [ ] **Step 2 — Apply fix.** At `research_tool.py:581` change:
  ```python
  actual_col = next((c for c in ed_df.columns if "actual" in str(c).lower()), None)
  ```
  to:
  ```python
  actual_col = next((c for c in ed_df.columns if "reported" in str(c).lower() or "actual" in str(c).lower()), None)
  ```
  (Mirrors `stock_data_fetcher.py:566` `_pick_col(ed_df.columns, ["reported", "actual"])`.)

- [ ] **Step 3 — GREEN.** Run the same test — must PASS. Paste GREEN output.

- [ ] **Step 4 — Full suite.** `python3 -m pytest tests/test_windmill_scripts.py -q`.
  Must show ≥ previous pass count (≥493 with new test added), no new failures. Paste tail.

- [ ] **Step 5 — Deploy.** The autopush hook handles `wmill script push` on save. Confirm
  the `[autopush]` message shows a successful push with no missing-resource warnings.

- [ ] **Step 6 — Live verify.** Run `research_tool` in Windmill for AAPL (or any US ticker
  with recent earnings). Inspect the rendered markdown (or email body). Assert the
  `### Recent EPS Surprises` table is present with ≥1 dated row. Paste the table.

## Locked Oracle Tests (G1)

No locked oracle — LOW-risk one-line fix; executor authors the RED test; reviewer validates
it is not tautological (test must fail on un-patched code, pass after the one-line change).

## RED-proof requirement (G2)

Paste the failing run BEFORE the fix:
```bash
python3 -m pytest agent/tests/test_windmill_scripts.py -k "test_earnings_calendar_reported_eps_column" -v
```
Expected: `FAILED … AssertionError` (surprises section absent). Then paste the GREEN run after patching.

## Asserting Verification Script (G4)

```bash
#!/bin/bash
fail=0

# 1. Test green
echo "=== pytest ==="
cd /root/agent
python3 -m pytest tests/test_windmill_scripts.py -k "test_earnings_calendar_reported_eps_column" -q 2>&1
[ ${PIPESTATUS[0]} -eq 0 ] && echo "PASS: test green" || { echo "FAIL: test failed"; fail=1; }

# 2. Fix present in source
echo "=== source check ==="
if grep -n '"reported"' /root/windmill/u/admin/research_tool.py | grep -q "actual_col"; then
    echo "PASS: reported keyword present in column detection"
else
    echo "FAIL: fix not applied"; fail=1
fi

# 3. Live AAPL verify (manual step — paste the Surprises table below)
echo "=== Live verify: run research_tool for AAPL in Windmill ==="
echo "Paste the '### Recent EPS Surprises' table from the output below:"

[ "$fail" -eq 0 ] && echo "PASS" || exit 1
```

## Acceptance Gate

- [ ] RED test added and FAILS on unpatched code (G2)
- [ ] One-line fix applied at `research_tool.py:581`
- [ ] GREEN test — same test passes after fix (G2)
- [ ] Full suite ≥493 passed, no new failures (G2)
- [ ] Live research report for AAPL shows populated "Recent EPS Surprises" table (G3/G4)
- [ ] Autopush confirms `wmill script push` succeeded with no missing-resource warnings

## Execution

1. Set Status: executing, commit.
2. Work checklist top to bottom; tick each `- [ ]` when its success criteria are met.
3. Run the Asserting Verification Script — paste output, must end in `PASS`.
4. Set Status: done, commit (by reviewer, per Acceptance Gate).
Satisfy all five gates in `docs/EXECUTOR_CONTRACT.md`; do not modify `# LOCKED ORACLE` assertions; STOP on any deviation.
Do not redesign. If the plan is ambiguous or wrong, stop and report — do not improvise.
