---
Subject: Affection Bot Split — give the hourly affection ping its own Telegram bot
Date: 2026-06-25
Status: done
Planner model: claude-sonnet-4-6 (Claude Code plan mode)
Executor model: deepseek (opencode) or any
Hard Rules in force: [7, 8, 9, 11, 17]
Files to read before coding: CLAUDE.md, docs/OPERATIONS.md, windmill/u/admin/affection_ping.schedule.yaml
---

# Plan: Affection Bot Split (Hygiene Initiative 1 of 5)

## Context

The revised roadmap (Part 5 — Infrastructure & Hygiene) calls for moving the hourly affection
sticker ping onto its **own** Telegram bot, so the main agent bot and the affection pings have
distinct identities. This is the first and cleanest hygiene initiative.

A live audit (2026-06-25) confirmed the split is **config-only, zero blast radius**:
- `affection_ping.py` reads no Windmill variable internally. The bot token arrives as the `main()`
  parameter `telegram_bot_token`, injected by the schedule. Confirmed: the live schedule args are
  `{telegram_bot_token, telegram_owner_id, affection_group_id, affection_sticker_packs, deepseek_key,
  portfolio_db}`, with `telegram_bot_token: "$var:u/admin/telegram_bot_token"`.
- The Telegram sender (`_send_message` / `_send_sticker`) is self-contained — inline `requests.post`
  to `api.telegram.org`, no shared helper.
- Every other Telegram script receives `telegram_bot_token` as its own independent schedule arg, so
  editing only this one schedule touches nothing else. The main bot keeps working everywhere.

**Net change: 1 new Windmill secret variable + 1 schedule-arg edit + 1 manual BotFather step. No Python code changes.**

### Environment facts the executor needs
- Run from `/root` (repo root) unless a step says otherwise. Git commands ALWAYS from `/root`.
- Windmill API base that works: `http://localhost:8080`. Workspace: `admins`.
- Get the Windmill token with: `WM_TOKEN=$(grep "WM_TOKEN" /root/agent.env | cut -d= -f2 | tr -d ' ')`
- Postgres: container `root-portfolio_postgres-1`, db `portfolio`. Query via
  `docker exec root-portfolio_postgres-1 psql -U portfolio_user -d portfolio -c "<SQL>"`.
- **Hard Rule 9: never `wmill sync push`.** Schedule changes go through the curl API below.
- **Hard Rule 8: do not delete/overwrite any existing resource or variable.** This plan only ADDS a
  variable and EDITS one schedule's args.

### Why the other 4 hygiene items are NOT in this plan
The audit corrected two roadmap assumptions (they belong to later, separate plans):
- `portfolio_thesis` is load-bearing (feeds the Thesis scoring factor + agent `thesis_read`/`thesis_write`)
  → *keep + seed*, not drop.
- `earnings_surprises` is load-bearing (read by rationalization, candidate_eval, research_tool) and
  empty due to a `stock_data_fetcher` extraction bug → *keep + fix*, not drop.
- Schedule-drift reconciliation needs owner decisions on canonical cron values (e.g. earnings_post_check
  server 1AM vs disk 7AM; price_fetcher 7-day vs Mon–Fri).
- `macro_daily_push` disposition (disabled on both sides).
Each gets its own `docs/plans/` file later. **This plan executes only the affection split.**

---

## Prerequisites — owner-supplied, execution BLOCKED until done

Telegram bot creation needs a phone/desktop Telegram action; it cannot be automated.

- [ ] **P1.** Owner creates a new bot via @BotFather (`/newbot`), sets a name + username, copies the
  HTTP API token (format `NNNNNNNN:AAA...`).
- [ ] **P2.** Owner adds that new bot to the affection group as a member (the chat behind
  `$var:u/admin/affection_group_id`). Without membership, sends return HTTP 403.
- [ ] **P3.** Owner supplies the token to the executor (paste in session, or add a line to
  `/root/shared/keys.md`). The executor must have the literal token string before Step 1.

If P1–P3 are not all satisfied, STOP and request them — do not proceed.

---

## Files changed

| Action | Path / target | Change |
|--------|---------------|--------|
| Create | Windmill secret variable `u/admin/affection_bot_token` | New bot token (server-side, NOT committed) |
| Edit | `/root/windmill/u/admin/affection_ping.schedule.yaml` | Line 10 token var reference |
| Push | Windmill schedule `u/admin/affection_ping` (args) | Via curl API (autopush does not fire on `.schedule.yaml`) |
| Edit | `/root/docs/ROADMAP.md` | Mark affection split done; add new variable to resources table |
| Create | `/root/docs/logs/2026-06-25_affection-bot-split.md` | Implementation log |

No `.py` files change. `affection_ping` `main()` signature and its 11 artifact tests in
`/root/agent/tests/test_windmill_scripts.py` are unaffected (param name stays `telegram_bot_token`).

---

## Checklist

### Step 1 — Create the new secret variable
Replace `<NEW_BOT_TOKEN>` with the literal token from P1.

```bash
WM_TOKEN=$(grep "WM_TOKEN" /root/agent.env | cut -d= -f2 | tr -d ' ')
curl -s -X POST "http://localhost:8080/api/w/admins/variables/create" \
  -H "Authorization: Bearer $WM_TOKEN" -H "Content-Type: application/json" \
  -d '{"path":"u/admin/affection_bot_token","value":"<NEW_BOT_TOKEN>","is_secret":true,"description":"Affection ping bot token (separate from main agent bot)"}'
```
**Success criteria:** command returns the created path (or HTTP 201 / empty success). Verify:
```bash
curl -s "http://localhost:8080/api/w/admins/variables/list" -H "Authorization: Bearer $WM_TOKEN" | python3 -c "import sys,json;print([v['path'] for v in json.load(sys.stdin) if 'affection_bot_token' in v['path']])"
```
Expected output: `['u/admin/affection_bot_token']`.
**If the variable already exists** (HTTP 400 "already exists"): STOP and report — do not overwrite (Hard Rule 8).

### Step 2 — Edit the schedule YAML on disk
Edit `/root/windmill/u/admin/affection_ping.schedule.yaml`. Change exactly this line:
- OLD: `  telegram_bot_token: "$var:u/admin/telegram_bot_token"`
- NEW: `  telegram_bot_token: "$var:u/admin/affection_bot_token"`

Leave every other line (cron `0 0 8-22 * * *`, timezone, enabled, the other 5 args) untouched.
**Success criteria:**
```bash
grep telegram_bot_token /root/windmill/u/admin/affection_ping.schedule.yaml
```
Expected: the line now references `affection_bot_token`.

### Step 3 — Push the new args to the live schedule
The update endpoint requires the FULL schedule body (schedule, timezone, args). Sending a partial
body can blank fields. Use exactly this:

```bash
WM_TOKEN=$(grep "WM_TOKEN" /root/agent.env | cut -d= -f2 | tr -d ' ')
curl -s -X POST "http://localhost:8080/api/w/admins/schedules/update/u%2Fadmin%2Faffection_ping" \
  -H "Authorization: Bearer $WM_TOKEN" -H "Content-Type: application/json" \
  -d '{
    "schedule": "0 0 8-22 * * *",
    "timezone": "Asia/Singapore",
    "no_flow_overlap": true,
    "args": {
      "deepseek_key": "$var:u/admin/deepseek_key",
      "portfolio_db": "$res:u/admin/portfolio_db",
      "telegram_owner_id": "$var:u/admin/telegram_owner_id",
      "affection_group_id": "$var:u/admin/affection_group_id",
      "telegram_bot_token": "$var:u/admin/affection_bot_token",
      "affection_sticker_packs": "$var:u/admin/affection_sticker_packs"
    }
  }'
```
**Success criteria:** verify the server now has the new arg:
```bash
curl -s "http://localhost:8080/api/w/admins/schedules/get/u%2Fadmin%2Faffection_ping" -H "Authorization: Bearer $WM_TOKEN" | python3 -c "import sys,json;d=json.load(sys.stdin);print('TOKEN ARG:',d['args']['telegram_bot_token']);print('CRON:',d['schedule'],'| TZ:',d['timezone'],'| ENABLED:',d['enabled'])"
```
Expected: `TOKEN ARG: $var:u/admin/affection_bot_token` and `CRON: 0 0 8-22 * * * | TZ: Asia/Singapore | ENABLED: True`.
**If the endpoint returns an error or `enabled` flipped to False:** STOP and report — do not retry blindly.

### Step 4 — Live-verify the artifact (Hard Rule 17)
Trigger a one-off run of the deployed script so it sends with the NEW token, then confirm the real
artifact lands. Record the pre-run row count first:

```bash
docker exec root-portfolio_postgres-1 psql -U portfolio_user -d portfolio -t -c "SELECT count(*) FROM affection_outbox;"
```
Trigger the run (returns a job UUID as plain text):
```bash
WM_TOKEN=$(grep "WM_TOKEN" /root/agent.env | cut -d= -f2 | tr -d ' ')
JOB=$(curl -s -X POST "http://localhost:8080/api/w/admins/jobs/run/p/u%2Fadmin%2Faffection_ping" \
  -H "Authorization: Bearer $WM_TOKEN" -H "Content-Type: application/json" \
  -d '{
    "deepseek_key": "$var:u/admin/deepseek_key",
    "portfolio_db": "$res:u/admin/portfolio_db",
    "telegram_owner_id": "$var:u/admin/telegram_owner_id",
    "affection_group_id": "$var:u/admin/affection_group_id",
    "telegram_bot_token": "$var:u/admin/affection_bot_token",
    "affection_sticker_packs": "$var:u/admin/affection_sticker_packs"
  }')
echo "JOB=$JOB"
sleep 20
curl -s "http://localhost:8080/api/w/admins/jobs_u/completed/get/$JOB" -H "Authorization: Bearer $WM_TOKEN" | python3 -c "import sys,json;d=json.load(sys.stdin);print('SUCCESS:',d.get('success'));print('RESULT:',str(d.get('result'))[:300])"
```
**Success criteria — ALL THREE must hold:**
1. Job `SUCCESS: True` (if False, print logs: `curl -s "http://localhost:8080/api/w/admins/jobs_u/completed/get/$JOB" -H "Authorization: Bearer $WM_TOKEN" | python3 -c "import sys,json;print(json.load(sys.stdin).get('logs',''))"` and STOP/report).
2. A new `affection_outbox` row with `delivered = true` and no `error`:
   ```bash
   docker exec root-portfolio_postgres-1 psql -U portfolio_user -d portfolio -c "SELECT sent_at, recipient_id, sticker_pack, delivered, error FROM affection_outbox ORDER BY sent_at DESC LIMIT 1;"
   ```
   Expected: row timestamped just now, `delivered = t`, `error` empty. The count must be pre-count + 1.
3. **Owner visually confirms** a sticker + caption appeared in the affection group, sent by the NEW
   bot (its name/avatar), not the old one. (Executor cannot self-verify this — ask the owner.)

### Step 5 — Confirm no regression on the main bot
Owner sends `/health` (or any command) to the main agent bot `@<YOUR_BOT_USERNAME>` and confirms a
normal reply. This proves the main `telegram_bot_token` is untouched.
**Success criteria:** main bot replies normally.

### Step 6 — Docs + commit
1. Edit `/root/docs/ROADMAP.md`:
   - Part 5 "Affection Bot Separation": change status to ✅ done (with date).
   - Windmill resources table: add row
     `| u/admin/affection_bot_token | variable | Affection ping bot token (separate from main agent) |`
   - Update the `telegram_bot_token` row note: remove "+ affection ping shared token (affection split planned)"; it is now main-agent only.
2. Create `/root/docs/logs/2026-06-25_affection-bot-split.md` (template below).
3. Commit (from `/root`) — only the three tracked files; the secret variable is server-side:
   ```bash
   cd /root
   git add windmill/u/admin/affection_ping.schedule.yaml docs/ROADMAP.md docs/logs/2026-06-25_affection-bot-split.md
   git commit -m "$(printf 'feat(hygiene): split affection ping onto its own Telegram bot\n\nNew u/admin/affection_bot_token variable; affection_ping schedule now\ninjects it instead of the shared telegram_bot_token. No code change.\nLive-verified: sticker delivered from new bot, affection_outbox row written,\nmain agent bot unaffected.\n\nCo-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>')"
   git push
   ```
**Success criteria:** `git log --oneline -1` shows the commit; `git status` clean; push succeeded.

#### Log template — `/root/docs/logs/2026-06-25_affection-bot-split.md`
```markdown
# Affection Bot Split — Implementation Log

**Date:** 2026-06-25
**Scope:** Move the hourly affection sticker ping (`u/admin/affection_ping`) onto its own
Telegram bot, decoupling it from the main agent's `telegram_bot_token`.

## What changed
- New Windmill secret variable `u/admin/affection_bot_token` (server-side).
- `affection_ping.schedule.yaml` arg `telegram_bot_token` now references
  `$var:u/admin/affection_bot_token` (was `$var:u/admin/telegram_bot_token`).
- Pushed to the live schedule via the schedules update API (Hard Rule 9 — no sync push).
- No Python changes; the script is token-agnostic (token is a `main()` param).

## Live verification (Hard Rule 17)
- One-off run job <JOB_UUID>: success=True.
- `affection_outbox`: new row, delivered=t, no error.
- Owner confirmed sticker arrived in the group from the NEW bot identity.
- Main agent bot still replied to /health — main token unaffected.

## Notes
- Blast radius was zero: every other Telegram script takes its own `telegram_bot_token` arg.
- First of 5 Part-5 hygiene initiatives. Next: schedule-drift reconciliation (needs owner
  decisions on canonical cron values).
```

---

## Verification (run after the checklist)
- `affection_outbox` has a fresh `delivered=t` row from the run (count incremented by 1).
- Schedule GET shows `telegram_bot_token: $var:u/admin/affection_bot_token`, cron/tz/enabled unchanged.
- Owner-confirmed: new bot posted the sticker; main bot still answers.
- Optional regression sanity (no code changed, expect green):
  `docker exec root-straitsagent-1 python -m pytest tests/test_windmill_scripts.py -q`
- `git status` clean after commit + push.

## Out of scope (subsequent hygiene plans)
Schedule-drift reconciliation, `portfolio_thesis` seeding, `earnings_surprises` fetcher fix,
`macro_daily_push` disposition, optional API health monitor. Each gets its own `docs/plans/` file.

## Execution
1. Set front-matter `Status: executing`, commit.
2. Confirm Prerequisites P1–P3 are satisfied. If not, STOP and request them.
3. Work the checklist top to bottom; tick each `- [ ]` only when its stated success criteria are met.
4. Run the Verification section.
5. Set `Status: done`, commit.
Do not redesign. If any command errors or output differs from "Expected", STOP and report — do not improvise or retry blindly.
