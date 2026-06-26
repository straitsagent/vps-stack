---
Subject: macro_daily_push Disposition — formally park the superseded main script, remove its dead schedule
Date: 2026-06-25
Status: done
Planner model: claude-opus-4 (Claude Code)
Executor model: deepseek (opencode) or any
Hard Rules in force: [8, 9, 22]
Risk tier: LOW (mechanical — executor + review, no locked oracle)
Complies with: docs/EXECUTOR_CONTRACT.md
Files to read before coding: CLAUDE.md, docs/OPERATIONS.md, docs/ROADMAP.md (Part 1 + Part 5)
---

# Plan: macro_daily_push Disposition (Hygiene Initiative 5 of 5)

## Context

`macro_daily_push` (the main script) is superseded by `macro_research` (live, 7 AM Mon–Fri) and its
schedule is **disabled on both server and disk**. It lingers as ambiguous state: a disabled schedule on
the server and a `enabled: false` `.schedule.yaml` on disk.

**Decision (owner, this session): park / formally deprecate** — do NOT delete the scripts or tests.
Remove only the dead disabled schedule (server + disk) and document the script as parked.

### Critical distinction — what must NOT be touched
There are **two** assets with similar names; only one is superseded:

| Asset | Status | Action |
|---|---|---|
| `macro_daily_push.py` (main script) | Superseded by `macro_research`; schedule disabled | **Park** — keep file, remove its schedule |
| `macro_daily_push_telegram.py` (formatter) | **LIVE** — `macro_research` dispatches it (test `test_windmill_scripts.py:4570` asserts this); 1 of the 8 formatters in CLAUDE.md | **KEEP UNTOUCHED** |

Deleting or renaming the **formatter** would break the live macro push and the 8-formatter architecture
invariant. This plan does not touch it. The formatter count stays 8 — no CLAUDE.md change.

### Why keep the main script + its tests (not delete)
`macro_daily_push.py` has 4 passing tests (`test_windmill_scripts.py:2844-2867`). Parking (not deleting)
keeps the suite green with zero edits and leaves the code available if the standalone macro push is ever
revived. The only thing that is genuinely dead is the **schedule**.

### Environment facts the executor needs
- Run from `/root`; git from `/root` only.
- Windmill: `http://localhost:8080`, workspace `admins`.
  `WM_TOKEN=$(grep "WM_TOKEN" /root/agent.env | cut -d= -f2 | tr -d ' ')`.
- **Hard Rule 8** is about resources/variables (e.g. `gmail_smtp`) — this plan deletes a **schedule**,
  which is permitted; the hookify block does not cover schedule deletes. Still: only the
  `macro_daily_push` *schedule* is removed, nothing else.
- **Hard Rule 9:** no `wmill sync push`. The `wmill schedule` CLI has no `delete` subcommand, so the
  server delete uses the curl API below.
- Current state (verified 2026-06-25): server schedule `u/admin/macro_daily_push` exists,
  `enabled: False`, cron `0 30 7 * * 1-5`; disk `windmill/u/admin/macro_daily_push.schedule.yaml`
  has `enabled: false`, same cron.

---

## Files changed

| Action | Path / target | Change |
|--------|---------------|--------|
| Delete (server) | schedule `u/admin/macro_daily_push` | Remove the disabled schedule via curl DELETE |
| Delete (git rm) | `windmill/u/admin/macro_daily_push.schedule.yaml` | Remove the dead disk schedule file |
| Edit | `/root/docs/ROADMAP.md` | Part 1: mark `macro_daily_push` parked (schedule removed); Part 5: mark disposition done; Deleted/Parked: add entry |
| Create | `/root/docs/logs/2026-06-25_macro-daily-push-disposition.md` | Implementation log |

**Untouched (explicitly):** `macro_daily_push.py`, `.script.yaml`, `.script.lock`; the entire
`macro_daily_push_telegram.*` formatter; all tests.

---

## Checklist

### Step 1 — Confirm current state
```bash
WM_TOKEN=$(grep "WM_TOKEN" /root/agent.env | cut -d= -f2 | tr -d ' ')
curl -s "http://localhost:8080/api/w/admins/schedules/get/u%2Fadmin%2Fmacro_daily_push" -H "Authorization: Bearer $WM_TOKEN" | python3 -c "import sys,json;d=json.load(sys.stdin);print('enabled:',d.get('enabled'),'| cron:',d.get('schedule'))"
```
**Expected:** `enabled: False | cron: 0 30 7 * * 1-5`. **If `enabled: True`** — STOP and report (it is
not actually superseded/disabled; do not delete a running schedule).

### Step 2 — Delete the disabled server schedule
```bash
WM_TOKEN=$(grep "WM_TOKEN" /root/agent.env | cut -d= -f2 | tr -d ' ')
curl -s -o /dev/null -w "%{http_code}\n" -X DELETE \
  "http://localhost:8080/api/w/admins/schedules/delete/u%2Fadmin%2Fmacro_daily_push" \
  -H "Authorization: Bearer $WM_TOKEN"
```
**Expected:** `200` (or `204`). Verify it is gone:
```bash
curl -s -o /dev/null -w "%{http_code}\n" "http://localhost:8080/api/w/admins/schedules/get/u%2Fadmin%2Fmacro_daily_push" -H "Authorization: Bearer $WM_TOKEN"
```
**Expected:** `404` (not found). **If still 200:** STOP and report.

### Step 3 — Remove the dead disk schedule file
```bash
cd /root && git rm windmill/u/admin/macro_daily_push.schedule.yaml
```
**Success:** file staged for deletion; `ls windmill/u/admin/macro_daily_push.schedule.yaml` → not found.
Leave `macro_daily_push.py`, `.script.yaml`, `.script.lock` in place.

### Step 4 — Confirm nothing live broke
```bash
# formatter still dispatched by the live macro_research workflow:
docker exec root-straitsagent-1 python -m pytest tests/test_windmill_scripts.py -k "macro_daily_push or macro_research" -q
```
**Expected:** all green (parking the main script + removing its schedule changes no code; the formatter
and macro_research tests still pass).

### Step 5 — Docs + commit
1. `/root/docs/ROADMAP.md`:
   - **Part 1 Daily Intelligence**, the `Macro Daily Push` row — change the Notes to:
     `**Parked 2026-06-25** — main script retained for reference; disabled schedule removed (server + disk). macro_research handles the macro push. Its formatter macro_daily_push_telegram remains live (used by macro_research).`
   - **Part 5 "Macro Daily Push — Formal Disposition"** — replace the body with:
     `✅ Done 2026-06-25 — parked. Schedule removed; scripts retained. See log.`
   - **Deleted / Parked** section — add a bullet under a "Parked" note:
     `macro_daily_push (main script) — parked 2026-06-25; schedule removed, code retained. Formatter stays live.`
2. Create `/root/docs/logs/2026-06-25_macro-daily-push-disposition.md`:
   ```markdown
   # macro_daily_push Disposition — Implementation Log

   **Date:** 2026-06-25
   **Decision:** Park (not delete). macro_research supersedes the standalone macro push.

   ## Changes
   - Deleted the disabled server schedule u/admin/macro_daily_push (curl DELETE; Hard Rule 9 — no sync push).
   - git rm windmill/u/admin/macro_daily_push.schedule.yaml.
   - Retained macro_daily_push.py + .script.yaml/.lock and all 4 tests (parked, not removed).

   ## Explicitly untouched
   - macro_daily_push_telegram.* — LIVE formatter dispatched by macro_research (test_windmill_scripts.py:4570);
     1 of the 8 formatters. Formatter count stays 8; no CLAUDE.md change.

   ## Verification
   - schedules/get for macro_daily_push -> 404.
   - macro_daily_push + macro_research tests green.

   ## Notes
   - Final hygiene initiative (5 of 5). Remaining roadmap hygiene item (API health monitor) deferred
     to its own design session per owner.
   ```
3. Commit from `/root`:
   ```bash
   cd /root
   git add windmill/u/admin/macro_daily_push.schedule.yaml docs/ROADMAP.md docs/logs/2026-06-25_macro-daily-push-disposition.md
   git commit -m "$(printf 'chore(hygiene): park macro_daily_push; remove its dead disabled schedule\n\nmacro_research supersedes the standalone macro push. Deleted the disabled\nserver schedule (curl API) + the disk .schedule.yaml. Retained the main\nscript and its 4 tests (parked, not deleted). The macro_daily_push_telegram\nformatter is untouched — it remains LIVE, dispatched by macro_research.\n\nCo-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>')"
   git push
   ```
**Success:** `git status` clean; `git log --oneline -1` shows the commit; push succeeded.

---

## Verification (run after the checklist)
- `schedules/get/u%2Fadmin%2Fmacro_daily_push` → HTTP 404.
- `windmill/u/admin/macro_daily_push.schedule.yaml` no longer exists; `macro_daily_push.py` still does.
- `macro_daily_push_telegram.py` untouched; `docker exec root-straitsagent-1 python -m pytest tests/test_windmill_scripts.py -q` green.
- `git status` clean after commit + push.

## Out of scope
API health monitor (deferred to its own design session). The `research_tool.py:585` column twin-bug
(noted in the earnings_surprises plan) is unrelated to macro and handled separately.

## Locked Oracle Tests (G1)
No locked oracle — this is mechanical (delete a disabled schedule + a disk file; no new code). The
existing `macro_daily_push` / `macro_research` tests stay green unchanged; reviewer validates.

## RED-proof requirement (G2)
N/A (no new tests). Instead, paste the existing suite green after the change:
```bash
docker exec root-straitsagent-1 python -m pytest tests/test_windmill_scripts.py -k "macro_daily_push or macro_research" -q
```

## Asserting Verification Script (G4)
```bash
WM_TOKEN=$(grep "WM_TOKEN" /root/agent.env | cut -d= -f2 | tr -d ' ')
code=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:8080/api/w/admins/schedules/get/u%2Fadmin%2Fmacro_daily_push" -H "Authorization: Bearer $WM_TOKEN")
[ "$code" = "404" ] || { echo "FAIL: schedule still exists ($code)"; exit 1; }
[ ! -f /root/windmill/u/admin/macro_daily_push.schedule.yaml ] || { echo "FAIL: disk schedule still present"; exit 1; }
[ -f /root/windmill/u/admin/macro_daily_push_telegram.py ] || { echo "FAIL: formatter was removed (must stay)"; exit 1; }
echo "PASS"
```
Close-out pastes this output ending in `PASS`.

## Acceptance Gate (G3/G5 + review)
- [ ] Asserting verify script output pasted, ends in `PASS` (G4) — schedule 404, disk gone, formatter kept
- [ ] `macro_daily_push`/`macro_research` tests pasted green (G3)
- [ ] Confirmed the formatter `macro_daily_push_telegram` was NOT touched

## Execution
1. Set front-matter `Status: executing`, commit.
2. Work the checklist top to bottom; Step 1 must show `enabled: False` before Step 2.
3. Run the Verification section.
4. Set `Status: done`, commit.
Do not redesign. If any command errors or output differs from "Expected", STOP and report — do not improvise.
