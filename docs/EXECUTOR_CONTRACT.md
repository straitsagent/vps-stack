# Executor Handoff Contract

**This is the binding standard for executing any plan in `docs/plans/`.** It applies to every
executor — Claude Code, opencode/Deepseek, GLM, Sonnet, a human — so that "done" means the same thing
regardless of who or what runs the plan.

It exists because plan *specificity* (exact commands, code, payloads) is not the same as *verifiable
correctness*. A capable model can still write a test that passes trivially, edit a test to go green,
accept `success: True` without reading the artifact, or improvise past an error. This contract makes
correctness gated by artifacts the executor **cannot fake**, not by trusting its self-report.

Encoded as **Hard Rule 22** in `CLAUDE.md`.

---

## The Five Gates

Every plan execution must satisfy all five.

### G1 — Locked Oracle
Certain test assertions are **frozen**. The plan presents them in a fenced block headed
`# LOCKED ORACLE — copy verbatim, do not modify assertions`. The executor reproduces them **unchanged**
and writes implementation code to pass them — it must never weaken or edit a locked assertion to go
green.
- **Tiered ownership:** for **high-risk** plans (subtle logic, multi-file, anything where a wrong-but-
  green outcome is plausible) the **planner** (frontier / Claude Code) authors the locked assertions
  up front. For **mechanical** plans the executor may author tests, but a reviewer validates them.
- **Enforcement:** the reviewer diffs the committed test file against the plan's `# LOCKED ORACLE`
  block. Any change to a locked assertion ⇒ reject.
- **Planner requirement:** locked assertions must be embedded as copy-pasteable Python code
  (assertion + explicit numeric tolerance), not prose approximations ("≈ -11.5"). Prose forces
  the executor to author the tolerance, defeating "copy verbatim". Reviewers must reject
  HIGH-tier plans whose `# LOCKED ORACLE` block contains prose rather than executable assertions.

### G2 — RED before GREEN
The executor must paste the **failing** test run *before* implementing, and the **passing** run after.
- RED must fail for the *right reason* (e.g. `AttributeError`, missing function, a real assertion
  failure) — **not** an import/collection error that would mask the logic.
- No RED paste ⇒ the work is not done, regardless of a later green run.

### G3 — Evidence, not claims
Every checklist item marked done is backed by **pasted raw output** — `psql` rows, the
`telegram_outbox` body, the IMAP email, the job result JSON. `success: True`, "looks correct", and log
lines are **not** evidence (Hard Rule 17, generalized to all work). The reviewer reads the artifact,
not the summary.

### G4 — Asserting verify script
Each plan ships a `verify` script that **prints and asserts** the decisive artifacts and **exits
non-zero on any failure**, ending in an explicit `PASS`. The script — not the model's word — is the
oracle for the live/integration side. Close-out requires pasting the script's full output ending in
`PASS`.

Standard idiom:
```bash
docker exec root-portfolio_postgres-1 psql -U portfolio_user -d portfolio -tAc \
  "SELECT count(*) FROM earnings_surprises WHERE surprise_pct IS NOT NULL" \
| { read n; [ "${n:-0}" -gt 0 ] && echo "PASS rows=$n" || { echo "FAIL: empty"; exit 1; }; }
```

### G5 — STOP on deviation
If any command's output differs from the plan's "Expected", **halt and report**. Never improvise,
never retry blindly, never edit the oracle to fit, never mark an item done to keep moving. A stop with
a clear report is a success; a silent workaround is a failure.

---

## Review gate (close-out)

The plan `Status` is flipped to `done` only by a reviewer (human or frontier), after confirming:
- **G1** — committed locked tests diff-clean against the plan's `# LOCKED ORACLE` block.
- **G2** — both the RED and GREEN runs were pasted.
- **G4** — the asserting verify script output was pasted and ends in `PASS`.
- **G3** — the pasted artifacts actually match the plan's intent (spot-read, not skim).

Executor self-certification is never sufficient.

---

## Environment caveats for non-Claude-Code executors

The Claude Code safety nets do **not** run under opencode or other harnesses:
- **No hookify block** → `wmill sync push` is *not* blocked for you. **Never run it** (Hard Rule 9);
  deploy with `wmill script push <path>` from `/root/windmill` — run it **yourself**, the PostToolUse
  autopush does not fire either.
- **Run tests inside the agent container:** `docker exec root-straitsagent-1 python -m pytest tests/… -q`.
  Heavy deps (pandas, yfinance, openai) may be absent on bare `python`; load modules with the
  `sys.modules.setdefault(...)` stub pattern used throughout `agent/tests/test_windmill_scripts.py`.
- **Never edit a `# LOCKED ORACLE` block.**
- Run git from `/root` only; string form for `$res:`/`$var:` schedule args (Hard Rule 11).

---

## Pre-done self-check (mirror of the Testing Critic, Hard Rule 20)

Before declaring any task done, answer "no" to all of these:
1. Could every assertion still pass if the artifact were empty/`None`? (empty-artifact)
2. Does any assertion match boilerplate/template text rather than a fixture-unique value? (template-string)
3. Is any asserted value pre-sized to the threshold it's checking? (tautology)
4. Did I change a locked assertion to make it pass? (oracle tampering)
5. Did I mark anything done on `success: True` instead of a read artifact? (claim-not-evidence)

---

## Lessons from caught regressions

Every item below is a real plan that an executor reported as "all PASS," which then **failed when a
reviewer independently re-ran the exact same gates.** These are not hypothetical — check for all five
before writing `PASS` in the log.

1. **Stale-evidence.** Did you paste LOCKED ORACLE / G4 output from a run that happened *before* your
   last code edit? Re-run both, in a fresh process, as the last step before writing the implementation
   log — not from an earlier pass, a warm REPL, or a partial run. A stubbed module (`pytz`) only
   "passed" because an unrelated, earlier-running test had already imported the real package into
   `sys.modules` — the same G4 script failed deterministically the moment it was run standalone.
2. **Dead-branch.** If the plan wires up a previously-unreachable code path (a new API key passed
   through so an LLM/network branch finally executes, a new `if` arm), does the test suite include a
   test that actually *executes* that branch with a mocked success case — not just a test that the
   wiring exists? "The key is now passed in the schedule" is not the same as "the code that runs when
   the key is present doesn't crash." A move-monitor plan wired `deepseek_key` through correctly, but
   every test used the empty-key fallback path — hiding an `AttributeError` in the LLM-prompt branch
   that would have crashed on the very next real alert.
3. **Scope-creep.** Diff your full changeset against the pre-change file. Does every hunk map to a row
   in the plan's Files-Changed table? Large shared test files (500+ tests in one file) make it easy to
   silently revert someone else's unrelated, already-verified fix while making your own edit nearby —
   an affection-bot test constant was reverted to a broken hardcoded path (with a new comment
   justifying the wrong value) while an unrelated move-monitor test was being added, undoing a
   previous reviewer's fix.
4. **Pipe-masking.** Does any verification command pipe test output through `tail`/`head`/`grep` for
   readability? In a shell pipeline, the exit code reflects the *last* command in the pipe, not your
   test runner — `pytest ... | tail -3` can report exit 0 even when pytest failed. Capture the test
   command's own exit code (`${PIPESTATUS[0]}` in bash) before piping, or don't pipe at all.
5. **Prompt-drift.** If the plan contains a Hard-Rule-10 "approved, copy verbatim" LLM prompt block,
   diff your shipped f-string against it character-for-character (outside the named interpolation
   variables). A stray typo (`$$` instead of `$`) changes what the model actually sees and is a
   Hard Rule 10 violation, not a cosmetic slip.
