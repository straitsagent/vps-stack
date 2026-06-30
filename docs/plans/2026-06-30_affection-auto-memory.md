---
Subject: Daily + weekly auto-synthesis of conversation memory for affection bot
Date: 2026-06-30
Status: draft
Planner model: deepseek-v4-flash (opencode)
Executor model: any
Risk tier: LOW-MEDIUM (touches no secrets, no gmail_smtp, no Telegram-send in the synthesis; the synthesis writes to DB but uses the existing portfolio_db resource)
Hard Rules in force: [4, 7, 12, 15, 16, 17, 18, 20, 22]
Complies with: docs/EXECUTOR_CONTRACT.md
Files to read before coding: docs/EXECUTOR_CONTRACT.md, docs/TESTING.md, windmill/u/admin/affection_ping.py, affection/main.py, docs/WORKFLOW_ARCHITECTURE.md
---

# Plan: Affection Bot — Two-Tier Auto-Synthesis Memory

## Context

The affection bot (`/root/affection/main.py`) has 238 conversation messages across 4+ days but zero structured memory. It can search its own history via `search_memory` (ILIKE on `affection_conversation`), but the LLM has no frozen, synthesized context about the people, the dynamic, recent events, or recurring topics — so every conversation starts from zero knowledge of the group's life.

Hermes Agent's "closed learning loop" (MEMORY.md + background self-improvement review) solves this with a frozen snapshot injected at session start. The affection bot has no turn-end background process, but a Windmill cron is the correct substitute (consistent with the `affection_ping` pattern, and already monitored by the dispatch monitor).

This plan implements **two tiers of synthesized memory**, both read by `build_system_prompt()` in the bot and injected as frozen blocks at the start of every conversation:

- **Short-term** (daily via Windmill cron `0 0 2 * * *`): synthesises the last 7 days → 3KB.
- **Long-term** (weekly via Windmill cron `0 30 2 * * 0`): synthesises ALL conversation history (capped at 500 msgs) + integrates the prior long-term memory → 5KB.

The LLM loop (`chat_with_search`) does **not** write to these tables — only the cron (a deterministic Windmill script, no LLM autonomy). This sidesteps Hermes' "agent-modifying-its-own-memory" attack surface.

## Scope decisions

- **Short-term input:** last 7 days of `affection_conversation`, no prior memory needed.
- **Long-term input:** ALL rows, capped at 500 most-recent messages; prior long-term row fed into the prompt with "integrate, don't append" instruction.
- **One script** with a `mode` arg (`"short"` / `"long"`) — two separate schedule files.
- **Output tables:** `affection_short_term_memory` (chat_id PK) + `affection_long_term_memory` (chat_id PK).
- **Output chars:** ≤3,000 for short-term, ≤5,000 for long-term.
- **No manual `/remember` command** — only the cron writes.
- **No write-approval gate** — the synthesis prompt is fixed and the prior-row is read-only, so no privileged-injection path.
- **Model:** Deepseek `deepseek-chat`, temperature 0.3, same as the bot. No reasoner model.

## New components

| Item | Detail |
|---|---|
| Tables | `affection_short_term_memory` + `affection_long_term_memory` (schema in `portfolio/schema.sql`) |
| Script | `windmill/u/admin/affection_memory_synthesis.py` — takes `mode: "short"` or `"long"`, reads conversation, calls Deepseek, UPSERTs into the matching table |
| Schedule (daily) | `windmill/u/admin/affection_memory_synthesis_daily.schedule.yaml` — `0 0 2 * * *`, passes `mode: "short"` |
| Schedule (weekly) | `windmill/u/admin/affection_memory_synthesis_weekly.schedule.yaml` — `0 30 2 * * 0`, passes `mode: "long"` |
| Injection | `_load_memory_blocks()` in `main.py` reads latest rows from both tables, returns rendered frozen-block string; `build_system_prompt()` injects it between `SYSTEM_PROMPT_BASE` and the timestamp line |

## Files changed

| Action | Path | Change |
|--------|------|--------|
| Edit | `portfolio/schema.sql` | Add 2 new tables |
| Create | `windmill/u/admin/affection_memory_synthesis.py` | Synthesis script (one script, two modes) |
| Create | `windmill/u/admin/affection_memory_synthesis_daily.schedule.yaml` | Daily 02:00 SGT, `mode: "short"` |
| Create | `windmill/u/admin/affection_memory_synthesis_weekly.schedule.yaml` | Weekly Sun 02:30 SGT, `mode: "long"` |
| Edit | `affection/main.py` | `_load_memory_blocks()` + update `build_system_prompt()` |
| Edit | `agent/tests/test_windmill_scripts.py` | 10 new tests for synthesis + injection |
| Edit | `docs/ROADMAP.md` | Add 2 new schedules to System table |
| Edit | `docs/WORKFLOW_ARCHITECTURE.md` | Add Workflow 10.1 (short-term) and 10.2 (long-term) |

## Checklist

### Part 0 — Schema migration
- [ ] **H0.1** Add `affection_short_term_memory` and `affection_long_term_memory` tables to `portfolio/schema.sql`.
- [ ] **H0.2** Apply migration live: `docker exec -i root-portfolio_postgres-1 psql -U portfolio_user -d portfolio < portfolio/schema.sql`.
- [ ] **H0.3** Confirm both tables exist: `SELECT to_regclass('affection_short_term_memory'), to_regclass('affection_long_term_memory');`.
- [ ] **H0.4** Commit.

### Part 1 — Synthesis script (two modes, one file)
- [ ] **H1.1** Write `affection_memory_synthesis.py` with:
  - `main(mode: str, portfolio_db: dict, deepseek_key: str, ...)` dispatches to `_synthesise_short(chat_id, db_key, ds_key, n_days=7, max_chars=3000)` or `_synthesise_long(...)`.
  - Short-term: queries `affection_conversation WHERE created_at >= now() - interval '7 days'`, builds prompt, calls Deepseek, UPSERT into `affection_short_term_memory`.
  - Long-term: queries ALL `affection_conversation` (LIMIT 500), reads prior `affection_long_term_memory` row, builds prompt with "integrate, don't append" instruction, UPSERT into `affection_long_term_memory`.
  - Prompt explicitly requests "no verbatim quotes, no PII, output markdown only".
  - Error isolation per Hard Rule 4: on Deepseek failure or DB error, logs warning, does not crash.
- [ ] **H1.2** `py_compile` passes.
- [ ] **H1.3** `wmill script push windmill/u/admin/affection_memory_synthesis.py` from `/root/windmill`.
- [ ] **H1.4** Commit.

### Part 2 — main.py injection
- [ ] **H2.1** Add `_load_memory_blocks(chat_id) -> str` to `/root/affection/main.py`. Reads latest row from each table, renders as:
  ```
  ═══ LONG-TERM MEMORY (synth YYYY-MM-DD, N msgs) ═══
  ...
  ═══ SHORT-TERM MEMORY (synth YYYY-MM-DD, N msgs, window X→Y) ═══
  ...
  ```
  Returns `""` if both tables empty (graceful degradation).
- [ ] **H2.2** Update `build_system_prompt()` to inject `_load_memory_blocks()` output between `SYSTEM_PROMPT_BASE` and the timestamp line.
- [ ] **H2.3** `py_compile` passes.
- [ ] **H2.4** Restart the affection container: `docker compose -f /root/docker-compose.yml restart affectionbot`.
- [ ] **H2.5** Confirm the container restarted and webhook registered: `docker compose -f /root/docker-compose.yml ps affectionbot`.
- [ ] **H2.6** Commit.

### Part 3 — Tests
- [ ] **H3.1** Add 10 new test functions in `agent/tests/test_windmill_scripts.py`:
  | Test | What it asserts |
  |---|---|
  | `test_short_term_synthesis_reads_7d_window` | Inject 8d of fake rows; assert only last 7d appear in prompt |
  | `test_short_term_synthesis_stores_output` | Mock Deepseek → assert INSERT into `affection_short_term_memory` |
  | `test_short_term_synthesis_idempotent` | Run twice; second row replaces first (no duplicates) |
  | `test_long_term_synthesis_reads_all_history` | Fake rows spanning 30d; assert all appear (capped at 500) |
  | `test_long_term_synthesis_includes_prior_memory` | Prior long-term row exists → appears in prompt as "PRIOR" |
  | `test_long_term_synthesis_truncates_at_cap` | Feed 600 fake rows; assert ≤500 in prompt |
  | `test_injection_build_system_prompt_includes_short_term` | Seed short-term row; assert block header in `build_system_prompt()` |
  | `test_injection_build_system_prompt_includes_long_term` | Seed long-term row; assert block header |
  | `test_injection_build_system_prompt_skips_when_empty` | No rows; no memory block in output |
  | `test_injection_build_system_prompt_orders_long_then_short` | Both rows; long-term block appears before short-term |
- [ ] **H3.2** Docker-cp the updated test file into the agent container.
- [ ] **H3.3** Full suite: `docker exec root-straitsagent-1 python -m pytest tests/test_windmill_scripts.py -q 2>&1 | tail -5`. Must pass.
- [ ] **H3.4** Commit.

### Part 4 — Schedules + push
- [ ] **H4.1** Write `affection_memory_synthesis_daily.schedule.yaml`: cron `0 0 2 * * *`, timezone `Asia/Singapore`, args `{mode: "short", deepseek_key, portfolio_db}`.
- [ ] **H4.2** Write `affection_memory_synthesis_weekly.schedule.yaml`: cron `0 30 2 * * 0`, timezone `Asia/Singapore`, args `{mode: "long", deepseek_key, portfolio_db}`.
- [ ] **H4.3** Push daily schedule via curl (OPERATIONS.md recipe, NOT `wmill sync push`).
- [ ] **H4.4** Push weekly schedule via curl.
- [ ] **H4.5** Verify both schedules: `curl .../schedules/get/u%2Fadmin%2Faffection_memory_synthesis_daily` — confirm `enabled: true`, correct cron, `mode: "short"` in args.
- [ ] **H4.6** Commit.

### Part 5 — Docs
- [ ] **H5.1** ROADMAP.md: add "Daily Memory Synthesis" (02:00 SGT) + "Weekly Long-Term Memory Synthesis" (Sun 02:30 SGT) rows to the Part 1 System table.
- [ ] **H5.2** WORKFLOW_ARCHITECTURE.md: add Workflow 10.1 (short-term synthesis) and 10.2 (long-term synthesis) sections after the existing affection_ping spec.
- [ ] **H5.3** Commit.

## Locked Oracle Tests (G1)

```python
# LOCKED ORACLE — copy verbatim, do not modify assertions
import subprocess, os

def run(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd="/root")
    return r.returncode, r.stdout + r.stderr

# O1: Short-term memory table exists
rc, out = run("docker exec root-portfolio_postgres-1 psql -U portfolio_user -d portfolio -tAc \"SELECT to_regclass('affection_short_term_memory')\"")
assert "affection_short_term_memory" in out.rstrip(), f"O1 FAIL — short-term table missing: {out.strip()}"
print("O1 PASS — short-term memory table exists")

# O2: Long-term memory table exists
rc, out = run("docker exec root-portfolio_postgres-1 psql -U portfolio_user -d portfolio -tAc \"SELECT to_regclass('affection_long_term_memory')\"")
assert "affection_long_term_memory" in out.rstrip(), f"O2 FAIL — long-term table missing: {out.strip()}"
print("O2 PASS — long-term memory table exists")

# O3: Synthesis script exists
SE = "windmill/u/admin/affection_memory_synthesis.py"
assert os.path.exists(SE), "O3 FAIL — synthesis script missing"
print("O3 PASS — synthesis script exists")

# O4: Script reads from affection_conversation and writes to memory tables
rc, _ = run(f"grep -q 'affection_conversation' {SE}")
assert rc == 0, "O4 FAIL — does not read affection_conversation"
rc_short, _ = run(f"grep -q 'affection_short_term_memory' {SE}")
rc_long, _ = run(f"grep -q 'affection_long_term_memory' {SE}")
assert rc_short == 0 and rc_long == 0, "O4 FAIL — does not write to memory tables"
print("O4 PASS — script reads conversation and writes both memory tables")

# O5: main.py injects both memory blocks
AF = "/root/affection/main.py"
rc, _ = run(f"grep -q 'LONG-TERM MEMORY' {AF}")
assert rc == 0, "O5 FAIL — main.py does not inject LONG-TERM MEMORY header"
rc, _ = run(f"grep -q 'SHORT-TERM MEMORY' {AF}")
assert rc == 0, "O5 FAIL — main.py does not inject SHORT-TERM MEMORY header"
print("O5 PASS — main.py injects both memory blocks")

# O6: Schedule daily file exists with correct cron
rc, out = run("grep -E '^schedule:' windmill/u/admin/affection_memory_synthesis_daily.schedule.yaml")
assert "0 0 2 * * *" in out, f"O6 FAIL — daily schedule wrong cron: {out.strip()}"
print("O6 PASS — daily schedule has correct cron (0 0 2 * * *)")

# O7: Schedule weekly file exists with correct cron
rc, out = run("grep -E '^schedule:' windmill/u/admin/affection_memory_synthesis_weekly.schedule.yaml")
assert "0 30 2 * * 0" in out, f"O7 FAIL — weekly schedule wrong cron: {out.strip()}"
print("O7 PASS — weekly schedule has correct cron (0 30 2 * * 0)")

# O8: Suite green + correct test names present
rc, out = run("cd /root/agent && python3 -m pytest tests/test_windmill_scripts.py -q -k 'memory_synthesis or short_term or long_term' 2>&1 | tail -5")
assert rc == 0, f"O8 FAIL — tests failed:\n{out}"
for name in ("test_short_term_synthesis_reads_7d_window", "test_long_term_synthesis_reads_all_history",
             "test_injection_build_system_prompt_includes_short_term", "test_injection_build_system_prompt_skips_when_empty",
             "test_injection_build_system_prompt_orders_long_then_short"):
    rc2, _ = run(f"grep -q '{name}' /root/agent/tests/test_windmill_scripts.py")
    assert rc2 == 0, f"O8 FAIL — missing test: {name}"
print("O8 PASS — suite green + all required test names present")

print("\nLOCKED ORACLE: PASS")
```

## RED-proof requirement (G2)

Before any code is written, paste the failing oracle. Expected RED:

```
O1 FAIL — short-term table missing
O2 FAIL — long-term table missing
O3 FAIL — synthesis script missing
O4 FAIL — does not read affection_conversation
O5 FAIL — main.py does not inject LONG-TERM MEMORY header
O6 FAIL — daily schedule wrong cron
O7 FAIL — weekly schedule wrong cron
```

Also confirm the existing `test_affection_ping_picks_valid_sticker` and the rest of the affection test suite still passes before Part 1 (no regression on existing behaviour).

After all Parts, paste GREEN (oracle passes).

## Asserting Verification Script (G4)

```bash
#!/bin/bash
cd /root
fail=0
chk(){ [ "$1" -eq 0 ] && echo "PASS: $2" || { echo "FAIL: $2"; fail=1; }; }

# Tables exist
docker exec root-portfolio_postgres-1 psql -U portfolio_user -d portfolio -tAc \
  "SELECT to_regclass('affection_short_term_memory'), to_regclass('affection_long_term_memory')" \
  | grep -q short_term; chk $? "short-term memory table exists"
docker exec root-portfolio_postgres-1 psql -U portfolio_user -d portfolio -tAc \
  "SELECT to_regclass('affection_short_term_memory'), to_regclass('affection_long_term_memory')" \
  | grep -q long_term; chk $? "long-term memory table exists"

# Script exists
test -f windmill/u/admin/affection_memory_synthesis.py; chk $? "synthesis script exists"

# Main.py injects headers
grep -q 'LONG-TERM MEMORY' affection/main.py; chk $? "main.py LONG-TERM MEMORY header"
grep -q 'SHORT-TERM MEMORY' affection/main.py; chk $? "main.py SHORT-TERM MEMORY header"

# Schedule files exist with correct cron
grep -E "^schedule:" windmill/u/admin/affection_memory_synthesis_daily.schedule.yaml | grep -q "0 0 2 \* \* \*"; chk $? "daily schedule 02:00"
grep -E "^schedule:" windmill/u/admin/affection_memory_synthesis_weekly.schedule.yaml | grep -q "0 30 2 \* \* 0"; chk $? "weekly schedule Sun 02:30"

# Tests pass
( cd agent && python3 -m pytest tests/test_windmill_scripts.py -q -k 'memory_synthesis or short_term or long_term' 2>&1 | tail -3 )
chk ${PIPESTATUS[0]} "memory synthesis tests pass"

[ $fail -eq 0 ] && echo "PASS" || exit 1
```

## Acceptance Gate

- [ ] Both tables exist and are in `schema.sql`
- [ ] `affection_memory_synthesis.py` exists with `mode` arg dispatching to `_synthesise_short` and `_synthesise_long`
- [ ] `main.py` `_load_memory_blocks()` reads both tables; `build_system_prompt()` injects them as frozen blocks
- [ ] Two schedule YAML files with correct cron + `mode` arg; pushed via curl (no `wmill sync push`)
- [ ] 10 tests added: 5 for synthesis logic, 5 for system-prompt injection
- [ ] Full test suite green; no regressions on existing affection_ping tests
- [ ] Container restarted and webhook confirmed
- [ ] LOCKED ORACLE PASS (verbatim) + verify script ends `PASS`
- [ ] ROADMAP.md + WORKFLOW_ARCHITECTURE.md updated

## Execution

1. Set Status: executing, commit.
2. Paste RED (G2).
3. Work Part 0 → 5 top to bottom; tick each `- [ ]` when its success criteria are met.
4. Paste GREEN oracle + run the Asserting Verification Script (must end `PASS`).
5. Set Status: done, commit (by reviewer, per the Acceptance Gate).
Satisfy all five gates in `docs/EXECUTOR_CONTRACT.md`; do not modify `# LOCKED ORACLE` assertions; STOP on any deviation.
Do not redesign. If the plan is ambiguous or wrong, stop and report — do not improvise.
