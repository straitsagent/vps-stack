---
Subject: Schedule-Drift Reconciliation — make git match the running Windmill schedules
Date: 2026-06-25
Status: done
Planner model: claude-sonnet-4-6 (Claude Code plan mode)
Executor model: deepseek (opencode) or any
Hard Rules in force: [7, 8, 9, 11]
Files to read before coding: CLAUDE.md, docs/OPERATIONS.md, docs/ROADMAP.md (Part 1 + Part 5)
---

# Plan: Schedule-Drift Reconciliation (Hygiene Initiative 2 of 5)

## Context

A 2026-06-25 audit found the live Windmill schedules have drifted from the `.schedule.yaml`
files in git. Two kinds of drift:

1. **Cron-value drift** — the server runs a different cron than the disk file says.
2. **Name/path drift** — the live schedule lives under a server path that does NOT match its disk
   filename. This is a real footgun: a `wmill sync push` (banned, but still possible by mistake)
   would CREATE DUPLICATE schedules at the disk-filename paths instead of updating the live ones —
   double-firing every affected job.

**Goal:** git reflects exactly what's running. The principle is **"git matches the running server;
change the server only where the running behavior is actually wrong."** Owner decisions (this session)
resolved the two value drifts; everything else is disk-side cleanup.

### Key mechanism the executor must understand
- The `.schedule.yaml` files are **NOT auto-deployed.** The PostToolUse autopush hook fires only on
  `.py` files; `wmill sync push` is banned (Hard Rule 9). So **editing or renaming a `.schedule.yaml`
  has ZERO runtime effect** — it only makes git an accurate record and removes the duplicate-on-sync
  footgun.
- The **only** way a schedule's runtime behavior changes in this plan is the single curl API push in
  Step 1. Every other step is git bookkeeping.

### Decisions (resolved with owner this session)
| Schedule | Drift | Decision | Server change? |
|---|---|---|---|
| `portfolio_earnings_post_check` (server path `schedule_earnings_post_check`) | server 1AM vs disk 7AM | **7 AM SGT** (catches overnight US after-close earnings) | **YES** — push 1AM→7AM |
| `portfolio_price_fetcher` daily + evening | server 7-day vs disk Mon–Fri | **7 days/week** (Sat run captures US Fri close ~Sat 5AM SGT) | NO — align disk to server |
| `fundamentals_fetcher_weekly` | server `0 0 10 * * 7` UTC vs disk `0 0 18 * * 0` SGT | equivalent (both Sun 18:00 SGT) → align disk to server's stored value | NO |
| 5 name mismatches | disk filename ≠ live server path | rename disk files to the server paths | NO |
| `g/all/hub_sync` | server-only, disabled, untracked | Windmill built-in — **leave alone** | NO |

### Environment facts the executor needs
- Run from `/root`. Git commands ALWAYS from `/root`. Schedule yaml files live in
  `/root/windmill/u/admin/`.
- Windmill API base that works: `http://localhost:8080`. Workspace: `admins`.
- Token: `WM_TOKEN=$(grep "WM_TOKEN" /root/agent.env | cut -d= -f2 | tr -d ' ')`
- **Hard Rule 9: never `wmill sync push`.** The one server change uses the curl API below.
- **Hard Rule 8: do not delete/recreate any live schedule.** Renaming a *server* schedule path would
  lose run history — this plan does NOT touch server paths, only disk filenames.

---

## Files changed

| Action | Path | Change |
|--------|------|--------|
| Push (server) | schedule `u/admin/schedule_earnings_post_check` | cron `0 0 1 * * *` → `0 0 7 * * *` (curl API) |
| Rename (git mv) | `macro_research.schedule.yaml` → `macro_research_daily.schedule.yaml` | filename → server path (content already matches) |
| Rename (git mv) | `portfolio_earnings_post_check.schedule.yaml` → `schedule_earnings_post_check.schedule.yaml` | filename → server path (disk cron already 7AM) |
| Rename (git mv) | `portfolio_analyst_alert_daily.schedule.yaml` → `portfolio_analyst_alert_schedule.schedule.yaml` | filename → server path |
| Rename (git mv) | `portfolio_earnings_alert_daily.schedule.yaml` → `portfolio_earnings_alert_schedule.schedule.yaml` | filename → server path |
| Rename (git mv) | `youtube_monitor.schedule.yaml` → `youtube_monitor_hourly.schedule.yaml` | filename → server path |
| Edit | `portfolio_price_fetcher_daily.schedule.yaml` | cron `0 45 5 * * 1-5` → `0 45 5 * * *` + summary |
| Edit | `portfolio_price_fetcher_evening.schedule.yaml` | cron `0 45 17 * * 1-5` → `0 45 17 * * *` + summary |
| Edit | `fundamentals_fetcher_weekly.schedule.yaml` | cron/tz → `0 0 10 * * 7` / UTC + clarifying comment |
| Edit | `/root/docs/ROADMAP.md` | remove drift ⚠️ markers (Part 1) + mark Part 5 item done |
| Create | `/root/docs/logs/2026-06-25_schedule-drift-reconcile.md` | implementation log |

No `.py` files change. No script behavior changes except earnings_post_check firing time.

---

## Checklist

### Step 1 — Server change: push earnings_post_check to 7 AM
This is the ONLY runtime change. Full body required (partial body can blank fields).

```bash
WM_TOKEN=$(grep "WM_TOKEN" /root/agent.env | cut -d= -f2 | tr -d ' ')
curl -s -X POST "http://localhost:8080/api/w/admins/schedules/update/u%2Fadmin%2Fschedule_earnings_post_check" \
  -H "Authorization: Bearer $WM_TOKEN" -H "Content-Type: application/json" \
  -d '{
    "schedule": "0 0 7 * * *",
    "timezone": "Asia/Singapore",
    "no_flow_overlap": false,
    "args": {
      "wm_token": "$var:u/admin/wm_token",
      "finnhub_key": "$var:u/admin/finnhub_key",
      "portfolio_db": "$res:u/admin/portfolio_db"
    }
  }'
```
**Verify:**
```bash
curl -s "http://localhost:8080/api/w/admins/schedules/get/u%2Fadmin%2Fschedule_earnings_post_check" -H "Authorization: Bearer $WM_TOKEN" | python3 -c "import sys,json;d=json.load(sys.stdin);print('cron:',d['schedule'],'| tz:',d['timezone'],'| enabled:',d['enabled'])"
```
**Success:** `cron: 0 0 7 * * * | tz: Asia/Singapore | enabled: True`.
**If error or enabled flipped to False:** STOP and report.

### Step 2 — Rename the 5 mis-named disk files (pure `git mv`, no content change)
Each file's cron/tz/script_path/args already match the live server; only the filename was wrong.
From `/root`:
```bash
cd /root/windmill/u/admin
git mv macro_research.schedule.yaml                  macro_research_daily.schedule.yaml
git mv portfolio_earnings_post_check.schedule.yaml   schedule_earnings_post_check.schedule.yaml
git mv portfolio_analyst_alert_daily.schedule.yaml   portfolio_analyst_alert_schedule.schedule.yaml
git mv portfolio_earnings_alert_daily.schedule.yaml  portfolio_earnings_alert_schedule.schedule.yaml
git mv youtube_monitor.schedule.yaml                 youtube_monitor_hourly.schedule.yaml
cd /root
```
**Success:** `ls /root/windmill/u/admin/*.schedule.yaml` shows the 5 new names and none of the old names.
**Note:** `schedule_earnings_post_check.schedule.yaml` already contains `schedule: '0 0 7 * * *'` on disk
(disk was always 7AM) — so after Step 1 it matches the server. No content edit needed.

### Step 3 — Align price_fetcher disk files to the server (7-day)
Edit `/root/windmill/u/admin/portfolio_price_fetcher_daily.schedule.yaml`:
- `schedule: '0 45 5 * * 1-5'` → `schedule: '0 45 5 * * *'`
- summary `'Portfolio Price Fetcher — AM (5:45 SGT, Mon-Fri)'` → `'Portfolio Price Fetcher — AM (5:45 AM SGT, daily)'`

Edit `/root/windmill/u/admin/portfolio_price_fetcher_evening.schedule.yaml`:
- `schedule: '0 45 17 * * 1-5'` → `schedule: '0 45 17 * * *'`
- summary `'Portfolio Price Fetcher — PM (5:45 PM SGT, Mon-Fri)'` → `'Portfolio Price Fetcher — PM (5:45 PM SGT, daily)'`

**Success:** `grep "schedule:" portfolio_price_fetcher_*.schedule.yaml` shows both `* * *` (no `1-5`).

### Step 4 — Align fundamentals disk file to the server's stored value
Edit `/root/windmill/u/admin/fundamentals_fetcher_weekly.schedule.yaml`:
- `schedule: '0 0 18 * * 0'` → `schedule: '0 0 10 * * 7'`
- `timezone: Asia/Singapore` → `timezone: UTC`
- Add a comment line directly above `schedule:`:
  `# 0 0 10 * * 7 UTC == Sunday 18:00 SGT. Stored in UTC to match the live server schedule.`
- summary stays `'Fundamentals Fetcher — Weekly Sunday 6 PM SGT'` (still accurate).

**Success:** `grep -A1 "10 \* \* 7" fundamentals_fetcher_weekly.schedule.yaml` shows the UTC cron;
file still parses (`python3 -c "import yaml;yaml.safe_load(open('/root/windmill/u/admin/fundamentals_fetcher_weekly.schedule.yaml'))"` exits 0 — note: comments are fine for YAML).

### Step 5 — Reconciliation verification (git == server)
Dump every server schedule and confirm cron/tz match the (now-renamed) disk files:
```bash
WM_TOKEN=$(grep "WM_TOKEN" /root/agent.env | cut -d= -f2 | tr -d ' ')
curl -s "http://localhost:8080/api/w/admins/schedules/list" -H "Authorization: Bearer $WM_TOKEN" \
 | python3 -c "import sys,json;[print(f\"{s['path']:<45} {s['schedule']:<18} {s.get('timezone'):<16} enabled={s['enabled']}\") for s in json.load(sys.stdin)]" | sort
```
**Confirm in the output:**
- `u/admin/schedule_earnings_post_check  0 0 7 * * *  Asia/Singapore  enabled=True`
- `u/admin/portfolio_price_fetcher_daily  0 45 5 * * *` and `..._evening  0 45 17 * * *`
- For each server path, a `<path-tail>.schedule.yaml` now exists on disk with the same cron/tz:
  ```bash
  ls /root/windmill/u/admin/*.schedule.yaml | sed 's#.*/##;s#.schedule.yaml##' | sort
  ```
  Every listed file (except `macro_daily_push` — out of scope, separate plan; and `portfolio_move_monitor_us`/others that already matched) should correspond to a server path tail.
**Success:** no server path lacks a matching disk filename; the two value drifts read as decided.

### Step 6 — Docs + commit
1. Edit `/root/docs/ROADMAP.md`:
   - **Top-of-Part-1 callout** — replace the `> **⚠️ Known drift:** …` block with:
     `> **Schedules reconciled 2026-06-25** — git filenames now match live server paths; cron values verified. earnings_post_check canonicalized to 7 AM SGT; price_fetcher confirmed 7 days/week.`
   - **Daily Price Fetcher row** — change `5:45 AM + 5:45 PM SGT *(⚠️ server runs 7 days/wk; disk `.yaml` says Mon–Fri)*` → `5:45 AM + 5:45 PM SGT, 7 days/week`.
   - **Fundamentals Fetcher row** — change `Sunday 6:00 PM SGT *(⚠️ server schedule differs — see Part 5)*` → `Sunday 6:00 PM SGT`.
   - **Portfolio Earnings Post-Check row** — change `*(⚠️ server: 1AM SGT; disk/docs: 7AM SGT)*` → `7:00 AM SGT daily`.
   - **Part 5 → Schedule-Drift Reconciliation** — change status to ✅ done (2026-06-25); replace the drift table with a one-line "Resolved: see `docs/logs/2026-06-25_schedule-drift-reconcile.md`."
2. Create `/root/docs/logs/2026-06-25_schedule-drift-reconcile.md` (template below).
3. Commit from `/root` (git mv renames are already staged from Step 2; add the rest):
   ```bash
   cd /root
   git add windmill/u/admin/*.schedule.yaml docs/ROADMAP.md docs/logs/2026-06-25_schedule-drift-reconcile.md
   git commit -m "$(printf 'fix(hygiene): reconcile Windmill schedule drift (git matches server)\n\nRename 5 schedule yaml files to match live server paths (removes the\nsync-push duplicate footgun). earnings_post_check canonicalized to 7AM SGT\n(one server push). price_fetcher confirmed 7-day; fundamentals aligned to\nserver UTC value (equivalent). No script behavior change except post-check time.\n\nCo-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>')"
   git push
   ```
**Success:** `git status` clean; `git log --oneline -1` shows the commit; push succeeded.

#### Log template — `/root/docs/logs/2026-06-25_schedule-drift-reconcile.md`
```markdown
# Schedule-Drift Reconciliation — Implementation Log

**Date:** 2026-06-25
**Scope:** Reconcile live Windmill schedules with the `.schedule.yaml` files in git so git
reflects what's actually running, and remove the sync-push duplicate footgun.

## Drift found (2026-06-25 audit)
- Cron-value: earnings_post_check server 1AM vs disk 7AM; price_fetcher daily+evening server
  7-day vs disk Mon–Fri; fundamentals server UTC Sun 10:00 vs disk SGT Sun 18:00 (equivalent).
- Name/path: 5 disk filenames did not match their live server schedule paths.

## Decisions (owner)
- earnings_post_check → 7 AM SGT (server changed). Catches overnight US after-close earnings.
- price_fetcher → 7 days/week (kept). Saturday run captures US Friday close (~Sat 5AM SGT).

## Changes
- 1 server push: schedule_earnings_post_check 1AM → 7AM (curl API; Hard Rule 9 — no sync push).
- 5 git mv renames: macro_research→macro_research_daily, portfolio_earnings_post_check→
  schedule_earnings_post_check, portfolio_analyst_alert_daily→portfolio_analyst_alert_schedule,
  portfolio_earnings_alert_daily→portfolio_earnings_alert_schedule, youtube_monitor→
  youtube_monitor_hourly. (Content already matched server; only filenames were wrong.)
- price_fetcher daily+evening disk cron aligned to 7-day. fundamentals disk aligned to server
  UTC value with a clarifying comment.
- ROADMAP Part 1 drift markers removed; Part 5 item marked done.

## Verification
- schedules/list confirms earnings_post_check 7AM, price_fetcher both 7-day.
- Every live server path now has a matching disk filename (sync-push footgun removed).

## Notes
- macro_daily_push (disabled both sides) and g/all/hub_sync (Windmill built-in) intentionally
  left untouched — macro_daily_push has its own disposition plan.
- Hygiene initiative 2 of 5. Next: portfolio_thesis seeding / earnings_surprises fetcher fix.
```

---

## Verification (run after the checklist)
- `schedules/list` (Step 5 command) shows earnings_post_check `0 0 7 * * *`, price_fetcher daily
  `0 45 5 * * *`, evening `0 45 17 * * *`.
- Every server schedule path has a same-named disk `.schedule.yaml` (except out-of-scope
  `macro_daily_push` and the Windmill built-in `g/all/hub_sync`).
- `git status` clean after commit + push; the 5 renames show as `R` (rename) in `git show --stat`.
- ROADMAP has no remaining `⚠️` drift markers for these schedules.

## Out of scope (subsequent hygiene plans)
`portfolio_thesis` seeding, `earnings_surprises` fetcher fix, `macro_daily_push` disposition,
optional API health monitor. Each gets its own `docs/plans/` file.

## Execution
1. Set front-matter `Status: executing`, commit.
2. Work the checklist top to bottom; tick each `- [ ]` only when its stated success criteria are met.
3. Run the Verification section.
4. Set `Status: done`, commit.
Do not redesign. If any command errors or output differs from "Expected", STOP and report — do not improvise or retry blindly.
