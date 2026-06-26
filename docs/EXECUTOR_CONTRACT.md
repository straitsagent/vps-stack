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
