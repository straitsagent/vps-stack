---
Subject: <one-line description>
Date: YYYY-MM-DD
Status: draft            # draft | approved | executing | done | abandoned
Planner model: <who wrote this>
Executor model: <Claude Code | deepseek/opencode | GLM | any>
Risk tier: <HIGH (planner-locked oracle) | LOW (executor-authored + review)>
Hard Rules in force: [ ... ]
Complies with: docs/EXECUTOR_CONTRACT.md
Files to read before coding: CLAUDE.md, docs/EXECUTOR_CONTRACT.md, <others>
---

# Plan: <name>

## Context
Why this change is being made — the problem, what prompted it, the intended outcome.

## Files changed
| Action | Path | Change |
|--------|------|--------|
| ... | ... | ... |

## Checklist
- [ ] Step with explicit success criteria + expected output to diff against. STOP if output differs.

## Locked Oracle Tests (G1)
> For HIGH-risk plans the planner authors these. Executor reproduces them **verbatim** and may not edit
> any assertion to pass. Reviewer diffs the committed test file against this block.

```python
# LOCKED ORACLE — copy verbatim, do not modify assertions
# <the frozen test assertions>
```
> LOW-risk / mechanical plans: write "No locked oracle — mechanical; reviewer validates executor-authored tests."

## RED-proof requirement (G2)
Paste the failing run (failing for the right reason) BEFORE implementing, then the passing run after:
```bash
docker exec root-straitsagent-1 python -m pytest tests/test_windmill_scripts.py -k "<selector>" -q
```

## Asserting Verification Script (G4)
A script that prints AND asserts the decisive artifacts and exits non-zero on any failure, ending in `PASS`:
```bash
cd /root
fail=0
# <assert decisive live artifacts: psql rows, telegram_outbox, HTTP codes ...>
[ $fail -eq 0 ] && echo "PASS" || exit 1
```

## Acceptance Gate (G2/G3/G5 + review)
Reviewer flips Status to done only after confirming:
- [ ] Locked tests diff-clean vs the `# LOCKED ORACLE` block (G1)
- [ ] RED + GREEN runs pasted (G2)
- [ ] Asserting verify script output pasted, ends in `PASS` (G4)
- [ ] Pasted artifacts match intent — spot-read, not skim (G3)

## Execution
1. Set Status: executing, commit.
2. Work the checklist top to bottom; tick each `- [ ]` when its success criteria are met.
3. Run the Verification section.
4. Set Status: done, commit (by reviewer, per the Acceptance Gate).
Satisfy all five gates in `docs/EXECUTOR_CONTRACT.md`; do not modify `# LOCKED ORACLE` assertions; STOP on any deviation.
Do not redesign. If the plan is ambiguous or wrong, stop and report — do not improvise.
