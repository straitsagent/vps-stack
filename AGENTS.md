# AGENTS.md

VPS automation stack — Windmill orchestration + Telegram/email delivery, PostgreSQL-backed
portfolio intelligence, FastAPI agent service. Full context: `CLAUDE.md`. **Read that first.**

> **Before executing any plan in `docs/plans/`, read `docs/EXECUTOR_CONTRACT.md` — the Five Gates
> are the binding standard for every executor (Claude Code, opencode/Deepseek, GLM, human), not
> just high-risk work.** This file is the quick-start; the contract is what reviewers diff against.

## Executing a plan

Plans live in `docs/plans/YYYY-MM-DD_<slug>.md`, git-tracked, copy `docs/plans/_TEMPLATE.md`.

1. Read the plan in full. If it is ambiguous, wrong, or missing detail, **stop and report** — do not improvise.
2. Set front-matter `Status: executing`, commit (from `/root` only — see Git below).
3. Work the `- [ ]` checklist top to bottom; tick each item only when its success criteria are met.
4. Run the plan's `## Asserting Verification Script` — paste its full output; it must end in `PASS`.
5. Write a detailed implementation log at `docs/logs/YYYY-MM-DD_<slug>.md` documenting what was
   built, key decisions, deviations, verification output, and remaining items. Commit before
   flipping to done. See existing logs in `docs/logs/` for the required format.
6. **Before flipping to `done`:** confirm every item in the plan's `## Acceptance Gate` is satisfied,
   including docs edits (ROADMAP, CLAUDE.md, WORKFLOW_ARCHITECTURE). A skipped docs item is a
   review-gate violation even if the code is correct. The reviewer (human or frontier) flips `done` —
   self-certification is never sufficient.

### Five Gates (apply to every plan)

- **G1 Locked Oracle** — any `# LOCKED ORACLE — copy verbatim` block is frozen. Reproduce assertions
  unchanged; never weaken or edit a locked assertion to go green.
- **G2 RED before GREEN** — paste the failing test run *before* implementing, then the passing run after.
  RED must fail for the right reason (not an import error that masks logic).
- **G3 Evidence, not claims** — back every "done" with pasted raw output (psql rows, `telegram_outbox`
  body, IMAP email body, job result). `success: True`, "looks correct", and log lines are not evidence.
- **G4 Asserting verify script** — runs and asserts the decisive artifacts, exits non-zero on failure,
  ends in `PASS`. The script — not the executor's word — is the oracle.
- **G5 STOP on deviation** — if any output differs from the plan's "Expected", halt and report. Never
  improvise, retry blindly, edit the oracle, or mark an item done to keep moving.

### Before writing "PASS" in the log — 5 real failures, now checklist items

`docs/EXECUTOR_CONTRACT.md` → "Lessons from caught regressions" has the full detail. Five real plans
were reported "all PASS" by the executor and then **failed when a reviewer independently re-ran the
same gates.** Check for all five, every time:

1. **Stale-evidence** — re-run the LOCKED ORACLE and G4 fresh, in a new process, as the last step
   before writing the log. A pasted result from an earlier or partial run is not evidence.
2. **Dead-branch** — if this plan makes a previously-unreachable code path reachable (e.g. wiring a
   key so an LLM branch finally runs), the test suite must *execute* that branch with a mocked success
   case, not just assert the wiring exists.
3. **Scope-creep** — diff your full changeset against the pre-change file; every hunk must map to the
   plan's Files-Changed table. Shared test files make it easy to silently revert someone else's
   unrelated, already-verified fix.
4. **Pipe-masking** — `pytest ... | tail -3` reports the exit code of `tail`, not `pytest`. Capture the
   test command's own exit code (`${PIPESTATUS[0]}`) or don't pipe verification commands at all.
5. **Prompt-drift** — a Hard-Rule-10 "approved, copy verbatim" prompt block must match character-for-
   character (outside named interpolation variables). A stray typo is a Hard Rule 10 violation.

## Hard Rules every executor must internalize

These are the highest-cost mistakes from prior sessions — see `CLAUDE.md` for the full list.

- **Hard Rule 9 — never `wmill sync push`.** Always `wmill script push <path>` from `/root/windmill`.
  `wmill sync push` has wiped Windmill resources/variables and deployed stale archived versions.
  The Claude Code hookify block catches this; opencode does **not** have that safety net — be manual.
- **Hard Rule 11 — string form for `$res:`/`$var:` schedule args.** Correct: `"$res:u/admin/portfolio_db"`.
  Wrong: `{"$res": "u/admin/portfolio_db"}` — Windmill does not resolve the dict form, causing KeyError.
- **Hard Rule 15 — artifact-driven TDD is mandatory for all code.** See `docs/TESTING.md`.
- **Hard Rule 17 — verify the rendered artifact, not `success: True`.** Email body via IMAP, Telegram via
  outbox table, agreement check across both.
- **Hard Rule 22 — cross-model handoff contract.** Any plan must satisfy EXECUTOR_CONTRACT.md.
- **Hard Rule 23 — always write the implementation log.** After verification passes and before
  flipping a plan's status to `done`, write `docs/logs/YYYY-MM-DD_<slug>.md` documenting the
  implementation. See existing logs in `docs/logs/` for the required format (Summary, What was
  built, Key decisions, Deviation log, Verification output, Remaining items). Missing or
  placeholder logs are a review-gate violation.
- **Never edit a `# LOCKED ORACLE` block.** Reviewers diff the committed test file against the plan;
  any change ⇒ reject.

## Repo layout (entrypoints only)

| Path | Purpose |
|---|---|
| `/root/windmill/u/admin/` | 32 Windmill scripts + 18 schedules (`.py` + `.script.yaml` + `.script.lock` + `.schedule.yaml`). Git source of truth. |
| `/root/windmill/AGENTS.md` | Windmill-specific agent instructions (executor rules for this subdir). |
| `/root/agent/` | FastAPI Telegram agent — `main.py`, `db.py`, `tools.py`, `planner.py`, `formatter.py`. Tests in `agent/tests/`. |
| `/root/portfolio/` | Portfolio DB schema + migrations + seed (33 positions). |
| `/root/affection/` | Standalone affection-bot service (split from agent 2026-06-25). |
| `/root/secrets/keys.md` | API keys (chmod 600, **never commit**). |
| `/root/secrets/windmill-sa-key.json` | GCP SA key (**never commit**). |
| `/root/docs/ROADMAP.md` | Single source for build status / live workflows / next-up. |
| `/root/docs/TESTING.md` | Artifact-driven testing philosophy + harness pattern. |
| `/root/docs/WORKFLOW_ARCHITECTURE.md` | Per-workflow pseudocode specs. |
| `/root/docs/OPERATIONS.md` | Operational runbooks (credential restore, schedule API push, Docker rebuild). |
| `/root/docs/logs/` | Implementation logs for every executed plan — one per plan. |
| `/root/docs/earnings_report_standards.md` | 6 mandatory report standards for `portfolio_earnings_analysis.py`. |
| `/root/scripts/` | Hooks: `session-git-check.py` (SessionStart), `windmill-autopush.py` (PostToolUse). |

## Commands the executor will use

Run all git from `/root` only — git in a subdir operates against the subdir, causing wrong-directory commits.

```bash
# Run agent tests (opencode lacks Claude Code's env, so run inside the agent container)
docker exec root-straitsagent-1 python -m pytest tests/ -q                    # full suite
docker exec root-straitsagent-1 python -m pytest tests/<file>.py -q -k "name" # focused

# Deploy a single Windmill script (NEVER use wmill sync push)
cd /root/windmill && wmill script push u/admin/<name>.py

# Pull UI edits back to disk
cd /root/windmill && wmill sync pull --yes

# Inspect live Windmill jobs (use these, not speculation)
wmill job list --failed --limit 20
wmill job list --script-path u/admin/<name>.py
wmill job logs <id>
wmill job result <id>

# PostgreSQL — internal only, not exposed externally
docker exec root-portfolio_postgres-1 psql -U portfolio_user -d portfolio -tAc "<SQL>"
```

## Conventions

- **Date-prefix all new docs.** Files under `docs/` (and subdirs `plans/`, `logs/`, `audit/`, `opencode/`,
  `design/`, `research/`) use `YYYY-MM-DD_<slug>.md`. This is the binding naming pattern, not a style
  suggestion.
- **Windmill scripts get three files together:** `<name>.py` + `<name>.script.yaml` + `<name>.script.lock`.
  Lock file must show resolved packages (e.g. `# py: 3.12`) — not bare package lists.
- **Telegram formatter architecture:** each main script writes a canonical `.md` (JSON front-matter +
  ≥500-word narrative + `<!-- DETAIL -->` separator); a dedicated `<name>_telegram.py` formatter builds
  the self-contained Telegram message. The 9 formatters carry identical `_send_telegram` /
  `_split_telegram_message` copies — no cross-script imports.
- **Schedule `enabled: false` is normal for parked jobs** (e.g. `macro_daily_push` parked 2026-06-26).
  Don't "fix" by enabling without an approved plan.

## Deviations

A deviation is **any** change from the plan as written — including owner-approved model swaps
(e.g. Deepseek → Grok-4.3), prompt text rewording, or threshold constant changes. G5 covers them all:
**stop and report it before proceeding.** The owner confirming the change does not exempt the
executor from reporting. Do not self-certify a deviation in the implementation log and continue.

## Status lifecycle (plans)

`draft` (planner) → `approved` (planner, after explicit user approval) → `executing` (executor) →
`done` (reviewer only) | `abandoned` (either). At session start, scan `docs/plans/` for any file with
`Status: approved` or `executing` and surface its Subject + checklist progress before other work.
