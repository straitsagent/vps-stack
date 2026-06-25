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
- schedules/list confirmed earnings_post_check `0 0 7 * * *`, price_fetcher daily `0 45 5 * * *`,
  evening `0 45 17 * * *`, all enabled=True.
- Every live server path now has a matching disk filename (sync-push footgun removed).
- 10 schedules already matched and were left untouched.

## Notes
- macro_daily_push (disabled both sides) and g/all/hub_sync (Windmill built-in) intentionally
  left untouched — macro_daily_push has its own disposition plan.
- Hygiene initiative 2 of 5. Next: portfolio_thesis seeding / earnings_surprises fetcher fix.
