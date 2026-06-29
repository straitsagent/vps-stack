---
Subject: Testing Phase D — prune Phase C substring tests, harness 3 missing scripts, live-verify all
Date: 2026-06-28
Status: executing
Planner model: claude-sonnet-4-6
Risk tier: MEDIUM (adds tests + modifies test file; no change to production scripts)
Hard Rules in force: [12, 15, 17, 20]
Complies with: docs/EXECUTOR_CONTRACT.md
Files to read before coding: CLAUDE.md, docs/EXECUTOR_CONTRACT.md, docs/TESTING.md, agent/tests/test_windmill_scripts.py
---

# Plan: Testing Phase D

## Context

Testing Phase C (2026-06-23/27) delivered full artifact harnesses for 7 scripts. Two
remaining columns in the TESTING.md rollout table are still open across those 7:
**substring tests pruned** (6 of 7) and **live verified** (6 of 7; only `youtube_monitor`
done). A 2026-06-28 Hermes system review also flagged three scripts with no artifact
harness at all: `morning_news_digest`, `portfolio_price_fetcher`, `fundamentals_fetcher`.

This plan closes all three gaps in one pass.

**Baseline note (added 2026-06-29):** The rationalise-straitsagent-pushes plan
(commit `f136a1c`) executed before this plan. It removed Telegram dispatch from
`macro_research`, `morning_news_digest`, `portfolio_email`, and `youtube_monitor`,
and trimmed ~185 test cases in the process (E6). The test suite baseline entering
Phase D is **495 passing** (not the ~680 assumed when this plan was first written).
Key impacts on scope below.

## Scope

### Part 1 — Prune substring tests (Phase C remainder)

Six scripts have substring tests that should be replaced or subsumed by the artifact-render
harness. Per Hard Rule 20 (Testing Critic), substring tests that overlap with the `_agree`
harness are tautological — they test the same path the ASD was derived from.

Scripts: `macro_research`, `portfolio_email`, `portfolio_review`,
`portfolio_rationalization`, `portfolio_move_monitor`, `portfolio_analyst_alert`.

**Note:** the rationalise E6 already removed Telegram dispatch tests for `macro_research`
and `portfolio_email`. Part 1 for those two scripts is a lighter lift — focus on any
remaining substring tests that duplicate `_agree` fields (not dispatch-related).

For each: identify substring tests in `test_windmill_scripts.py` that duplicate fields
already asserted by the `_agree` test; remove them. Keep any substring test that covers a
code path the harness does not (e.g., edge cases, error branches).

### Part 2 — New artifact harnesses for 3 missing scripts

| Script | Artifact type | Harness pattern |
|--------|--------------|-----------------|
| `morning_news_digest` | Email HTML only (Telegram dispatch removed by rationalise) | Same ASD + `_agree` + word-count pattern as Phase C scripts |
| `portfolio_price_fetcher` | DB write — `price_history` rows | Fake DB cursor; assert correct ticker/date/close/currency written per position |
| `fundamentals_fetcher` | DB write — fundamentals tables | Fake DB cursor; assert correct data written for a mocked API response |

`morning_news_digest` is a delivery script — full artifact treatment (ASD, seams, `_agree`,
word-count, Tier 0 markers). The `_agree` test must assert on the **email HTML only**;
Telegram dispatch was removed by the rationalise plan (no formatter to test). `portfolio_price_fetcher` and `fundamentals_fetcher` are data
pipeline scripts — their artifact is a DB row; the harness verifies correct write behaviour
under a mocked API + mocked cursor.

Per Testing Critic (Hard Rule 20): the `morning_news_digest` `_agree` test must be
ASD-derived and assert every user-visible field (section headers, article count, dates).
Not just `len(body) > 0`.

### Part 3 — Live verify (Hard Rule 17)

After all tests pass, run one live Windmill execution per script (or confirm the next
scheduled run delivers) and verify the actual artifact — email body via IMAP or Telegram
outbox row. Paste confirmation per script in the checklist.

Live verify is required for: `macro_research`, `portfolio_email`, `portfolio_review`,
`portfolio_rationalization`, `portfolio_move_monitor`, `portfolio_analyst_alert`,
`morning_news_digest`. (`portfolio_price_fetcher` and `fundamentals_fetcher` are
verified by confirming DB rows written after a live run.)

## Files changed

| Action | Path | Change |
|--------|------|--------|
| Edit | `agent/tests/test_windmill_scripts.py` | Prune substring tests (Part 1); add 3 new harnesses (Part 2) |
| Edit | `docs/TESTING.md` | Tick remaining columns in rollout table; add 3 new script rows |

## Checklist

### Part 1 — Prune substring tests

- [ ] **D1.1** `macro_research` — audit substring tests; remove those duplicating `_agree` fields; confirm suite still passes
- [ ] **D1.2** `portfolio_email` — same
- [ ] **D1.3** `portfolio_review` — same
- [ ] **D1.4** `portfolio_rationalization` — same
- [ ] **D1.5** `portfolio_move_monitor` — same
- [ ] **D1.6** `portfolio_analyst_alert` — same
- [ ] **D1.7** Full suite passes after all 6 prunings. Paste pass count (must be ≥ prior count − pruned count, no new failures).

### Part 2 — New harnesses

- [ ] **D2.1** `morning_news_digest` — write ASD; factor seams if needed; RED→GREEN harness + `_agree` + word-count test; add Tier 0 `ARTIFACT_MARKERS` entry.
- [ ] **D2.2** `portfolio_price_fetcher` — write RED→GREEN DB-write harness: mock API response + cursor, assert `price_history` INSERT called with correct ticker/date/close/currency values.
- [ ] **D2.3** `fundamentals_fetcher` — write RED→GREEN DB-write harness: mock API + cursor, assert fundamentals table INSERT called with correct fields for a known ticker.
- [ ] **D2.4** Full suite passes. Paste tail with pass count.

### Part 3 — Live verify

- [ ] **D3.1** `macro_research` — paste confirmation (IMAP or outbox)
- [ ] **D3.2** `portfolio_email` — paste confirmation
- [ ] **D3.3** `portfolio_review` — paste confirmation
- [ ] **D3.4** `portfolio_rationalization` — paste confirmation
- [ ] **D3.5** `portfolio_move_monitor` — paste confirmation
- [ ] **D3.6** `portfolio_analyst_alert` — paste confirmation
- [ ] **D3.7** `morning_news_digest` — paste confirmation
- [ ] **D3.8** `portfolio_price_fetcher` — confirm DB rows written (count + sample ticker)
- [ ] **D3.9** `fundamentals_fetcher` — confirm DB rows written (count + sample ticker)

### Docs

- [ ] **D4.1** Tick all remaining columns in TESTING.md rollout table; add rows for 3 new scripts.

## Locked Oracle Tests (G1)

```python
# LOCKED ORACLE — copy verbatim, do not modify assertions.
import subprocess, sys

def run(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd="/root/agent")
    return r.returncode, r.stdout + r.stderr

# O1: test suite passes; count ≥ 505 (495 baseline post-rationalise + ≥10 new from Part 2)
rc, out = run("python3 -m pytest tests/test_windmill_scripts.py -q 2>&1 | tail -5")
assert rc == 0, f"Test suite failed:\n{out}"
import re
m = re.search(r"(\d+) passed", out)
assert m and int(m.group(1)) >= 505, f"Expected ≥505 passed, got: {out}"

# O2: morning_news_digest _agree test exists
rc, _ = run("grep -q 'test_morning_news.*agree\\|agree.*morning_news' tests/test_windmill_scripts.py")
assert rc == 0, "morning_news_digest _agree test not found"

# O3: price_fetcher has an _agree artifact harness (not just substring tests — 4 already exist)
rc, _ = run("grep -qE 'test_price_fetcher.*agree|agree.*price_fetcher' tests/test_windmill_scripts.py")
assert rc == 0, "portfolio_price_fetcher _agree harness not found (substring tests don't count)"

# O4: fundamentals_fetcher has an _agree artifact harness (not just substring tests — 4 already exist)
rc, _ = run("grep -qE 'test_fundamentals.*agree|agree.*fundamentals' tests/test_windmill_scripts.py")
assert rc == 0, "fundamentals_fetcher _agree harness not found (substring tests don't count)"

print("LOCKED ORACLE: PASS")
```

## RED-proof requirement (G2)

Before adding the Part 2 tests, run the oracle — O2/O3/O4 must FAIL (tests don't exist yet).
Paste the RED output. Then add tests and paste GREEN.

## Asserting Verification Script (G4)

```bash
#!/bin/bash
fail=0
cd /root/agent

echo "=== 1. test suite passes ==="
python3 -m pytest tests/test_windmill_scripts.py -q 2>&1 | tail -5
[ ${PIPESTATUS[0]} -eq 0 ] && echo PASS || { echo FAIL; fail=1; }

echo "=== 2. pass count ≥ 505 ==="
count=$(python3 -m pytest tests/test_windmill_scripts.py -q 2>&1 | grep -oP '\d+ passed' | grep -oP '\d+')
[ "$count" -ge 505 ] && echo "PASS: $count" || { echo "FAIL: $count"; fail=1; }

echo "=== 3. _agree tests exist for all Phase C + new scripts ==="
for pattern in \
  "agree.*morning_news|morning_news.*agree" \
  "test_price_fetcher.*agree|agree.*price_fetcher" \
  "test_fundamentals.*agree|agree.*fundamentals"; do
  grep -qP "$pattern" tests/test_windmill_scripts.py && echo "PASS: $pattern" || { echo "FAIL: $pattern"; fail=1; }
done

echo "=== 4. TESTING.md rollout table updated ==="
python3 -c "
t = open('../docs/TESTING.md').read()
scripts = ['morning_news_digest','portfolio_price_fetcher','fundamentals_fetcher']
for s in scripts:
    assert s in t, f'Missing {s} from TESTING.md rollout table'
print('PASS')
" || { echo FAIL; fail=1; }

[ $fail -eq 0 ] && echo "PASS" || exit 1
```

## Acceptance Gate

- [ ] Part 1: substring tests pruned for all 6 Phase C scripts; no new failures
- [ ] Part 2: RED→GREEN harnesses for all 3 new scripts; `_agree` is ASD-derived (not tautological)
- [ ] Part 2: `morning_news_digest` word-count ≥500 test passes
- [ ] Part 2: `morning_news_digest` Tier 0 `ARTIFACT_MARKERS` entry added
- [ ] Part 3: live delivery confirmed for all 7 delivery scripts; DB writes confirmed for 2 pipeline scripts
- [ ] Suite ≥505 passing, 0 new failures
- [ ] LOCKED ORACLE PASS (verbatim, unmodified)
- [ ] Verify script ends `PASS`
- [ ] TESTING.md rollout table complete (all columns ✅ for all 10 scripts)

## Execution

1. Set Status: executing, commit.
2. Work Part 1 → Part 2 → Part 3 → D4.1 top to bottom; tick each `- [ ]` when its success criteria are met.
3. Paste RED oracle run (before Part 2), then GREEN (after Part 2).
4. Run the Asserting Verification Script — paste output, must end in `PASS`.
5. Set Status: done, commit.
Satisfy all five gates in `docs/EXECUTOR_CONTRACT.md`; do not modify `# LOCKED ORACLE` assertions; STOP on any deviation.
Do not redesign. If the plan is ambiguous or wrong, stop and report — do not improvise.
