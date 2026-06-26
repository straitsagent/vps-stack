# Project AI Agent Instructions

This file is the entry point for AI agents working in this repository. It is
**user-owned** — `wmill` never overwrites it. Add your project-specific
guidance below the include line.

The line below pulls in Windmill's managed CLI guidance (skills, deploy flow,
debugging jobs, etc.). Refresh it with `wmill refresh prompts`. Remove the
include line if you don't want the managed guidance in this project.

@AGENTS.cli.md

## Project-specific instructions

### Executing a plan from `docs/plans/` — MANDATORY

Before executing **any** plan file in `../docs/plans/`, read `../docs/EXECUTOR_CONTRACT.md` and comply
with its **Five Gates**:
- **G1 Locked Oracle** — reproduce any `# LOCKED ORACLE — copy verbatim` test block **unchanged**;
  never weaken or edit a locked assertion to pass.
- **G2 RED before GREEN** — paste the failing test run (failing for the right reason) *before*
  implementing, then the passing run after.
- **G3 Evidence, not claims** — back every "done" with pasted raw output (psql rows, `telegram_outbox`
  body, job result). `success: True` is not evidence.
- **G4 Asserting verify script** — run the plan's verify script; paste its output; it must end in `PASS`.
- **G5 STOP on deviation** — if any output differs from "Expected", halt and report; do not improvise.

Completion is gated by review, not self-report.

### Deploy / environment (this harness lacks the Claude Code safety nets)
- **Never `wmill sync push`** (Hard Rule 9). The Claude Code hookify block does NOT run here, so this is
  manual: deploy with `wmill script push <path>` from `/root/windmill`, run it yourself.
- Run tests inside the agent container: `docker exec root-straitsagent-1 python -m pytest tests/… -q`.
- Run git from `/root` only. Use string form for `$res:`/`$var:` schedule args (Hard Rule 11).
- Full project rules: `../CLAUDE.md`. Testing philosophy: `../docs/TESTING.md`.
