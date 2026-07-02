---
Status: done
Subject: Hermes nudge inbox — inbound Claude Code → Hermes advisory channel + HERMES-PROTOCOL.md
Date: 2026-07-02
---

# Implementation Log: Hermes nudge inbox

## Summary

Built the inbound half of the Claude Code ↔ Hermes communication contract: a file-drop advisory inbox
(`docs/hermes/inbox/`) that Hermes can poll on its own schedule, plus `docs/HERMES-PROTOCOL.md` — a
single governing doc covering both directions (recapping the already-live outbound feedback channel,
fully specifying the new inbound one). Nudge-only by design: Hermes decides what to do with a nudge,
nothing dispatches it, INV-6 (analysis-only, locked) is untouched. CLI-only producer for this pass, per
explicit owner decision — no Windmill script wired in.

## What changed

- **`shared/python/utils/hermes_nudge.py`** (new) — `write_nudge()`: validates all inputs fail-loud
  (`ValueError`), bootstraps `inbox_dir`/`inbox_dir/processed` via `os.makedirs` + `chown` to `kevin`
  (uid/gid 1000, resolved via `pwd.getpwnam`, falls back to hardcoded 1000:1000 if that lookup fails),
  writes atomically (tempfile + `os.rename`, matching `system-metrics-collector.py`'s idiom), and
  returns the written path. Filename/`nudge_id` convention:
  `<created_at UTC secondsZ>_<source-slug>_<subject-slug>.md`.
- **`scripts/nudge-hermes.py`** (new) — thin argparse CLI wrapper over `write_nudge()`. Exit 0 + prints
  path on success; exit 1 + stderr message on `ValueError`/`OSError`.
- **`docs/HERMES-PROTOCOL.md`** (new) — 9 sections (0–8): purpose, standing invariants (INV-6/8/9
  restated for both directions), outbound channel recap, inbound channel full spec (schema, naming,
  urgency vocabulary, `processed/` convention, worked example), expected polling behavior, prompt-
  injection/trust-boundary guidance, future work (Telegram delivery — explicitly not built), versioning,
  changelog.
- **`agent/tests/test_hermes_nudge.py`** (new) — 20 tests: schema round-trip, every validation-failure
  case, atomic-write property, chown/permission bootstrap, filename/`nudge_id` convention + collision
  handling, CLI wrapper (valid + invalid).
- **Docs** — `docs/ROADMAP.md` Part 7: new paragraph noting the inbound channel mechanism live,
  CLI-only, Hermes-side polling cron still pending owner handoff. `docs/plans/2026-06-29_reflexive-alpha-system.md`:
  one-line cross-reference from the WS-1 section to this plan as the mirror-image inbound workstream.

## Key decisions

- **Urgency vocabulary (`whenever`/`soon`/`now`) deliberately disjoint from the feedback channel's
  severity vocabulary (`blocker`/`major`/`minor`/`idea`)** — asserted directly as Oracle O2 (set
  disjointness), so the two can never be confused even out of context.
- **`chown` to `kevin:kevin`, not `chmod 777`.** Investigation during planning found `docker exec hermes
  id` → uid 1000, and existing sibling dirs (`feedback/`, `cron/`) are `kevin:kevin` on the host (kevin
  has uid 1000) — so matching that ownership gives Hermes full access without opening the directory to
  every other user on the box.
- **`processed/` move, not in-place status mutation** — matches this repo's `docs/plans/archive/` idiom;
  a single atomic `rename()`; needs no YAML-editing capability on Hermes' side.
- **No Windmill script wired in (explicit owner decision during planning).** Nothing consumes the inbox
  yet (Hermes hasn't set up its polling cron), so adding a call into a live script now would be an
  unexercised code path — the "dead-branch" pattern `docs/EXECUTOR_CONTRACT.md` exists to catch.
  `health_check.py`'s CRIT branch is named in `HERMES-PROTOCOL.md` §6 as the natural phase-2 candidate.

## Deviations from the plan (both narrow, both documented at the time)

1. **Locked Oracle `run()` harness patched to invoke `/bin/bash` explicitly** (`executable="/bin/bash"`
   passed to `subprocess.run`) instead of relying on the default shell. O7/O9 use process substitution
   (`<(echo ...)`) for `--body-file`, which fails under `/bin/sh` (dash) with a syntax error. This is a
   harness/tooling fix, not an assertion change — every assertion in the Locked Oracle block is verbatim
   from the plan.
2. **Added a `## 0. Purpose & audience` header** to `HERMES-PROTOCOL.md` — the plan's outline listed
   "Purpose & audience" as section 1, but the first draft only had it as unheaded intro prose. Oracle O8
   greps for the literal word "Purpose", which correctly caught this as missing on first run. Fixed by
   adding the header; no content change.

## Verification

### RED proof
```
$ cd agent && python3 -m pytest tests/test_hermes_nudge.py -q
ERROR: file or directory not found: tests/test_hermes_nudge.py
```

### GREEN
```
$ python3 -m pytest tests/test_hermes_nudge.py -q
....................                                                     [100%]
20 passed in 0.33s
```

### G1 Locked Oracle
```
O1 PASS
O2 PASS
O3 PASS
O4 PASS
O5 PASS
O6 PASS
O7 PASS
O8 PASS
O9 PASS

LOCKED ORACLE: PASS
```

### G4 Asserting Verification Script
All 6 checks PASS, including a real live CLI run:
```
--- CLI output ---
/root/docs/hermes/inbox/2026-07-02T031703Z_claude-code_verify-script-check.md
------------------
PASS: nudge file exists at reported path
PASS: inbox dir ownership/permissions correct
PASS: nudge schema valid
PASS: HERMES-PROTOCOL.md exists and non-empty
PASS: new tests green
```
Step 6 ("full existing suite unaffected") failed when run from the bare host shell — 33 errors, all
`psycopg2.OperationalError` from DB-integration tests that require `AGENT_DB_URL`, which isn't set
outside the agent container. Not a regression: re-ran via `docker exec root-straitsagent-1 python -m
pytest tests/ -q` (this repo's established pattern per CLAUDE.md — DB-backed tests run inside the
container) and got a clean **711 passed, 5 skipped**, including all 20 new tests. The plan's G4 script
should have specified `docker exec` for this step; noting it here rather than silently editing the
committed plan file's verify script after the fact.

### Live artifact
One real (non-test) nudge shipped into the live inbox documenting this very build:
`docs/hermes/inbox/2026-07-02T031912Z_claude-code_inbound-nudge-channel-is-live.md`. The four
oracle/verify-script test artifacts generated during verification were moved into
`docs/hermes/inbox/processed/` to keep the live inbox clean.

## Remaining — explicit, not part of this plan's completion criteria

**Hermes has not yet self-authored a polling cron job for `docs/hermes/inbox/`.** This plan cannot build
that — Hermes authors its own jobs in its own `/workspace` state via its consent-first cron-suggestion
flow. Per the plan's "Manual follow-up" section: the owner needs to message Hermes via
`@StraitsHermesBot`, point it at `docs/HERMES-PROTOCOL.md`, and ask it to self-author a job that lists
`docs/hermes/inbox/` (excluding `processed/`) on a cadence of its choosing. Until that happens, the
mechanism is fully built and verified but nothing is actually reading it.

**Windmill integration is deferred** — `health_check.py` CRIT-branch wiring is named but not built, per
explicit owner decision (no consumer exists yet).

**Telegram delivery is deferred** — explicitly out of scope for this phase; would require expanding who
Hermes trusts as a sender beyond the owner's chat_id, a separate decision.
