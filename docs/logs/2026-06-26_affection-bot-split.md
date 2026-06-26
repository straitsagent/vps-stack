# Affection Bot Split — Implementation Log

**Date:** 2026-06-26
**Scope:** Move the hourly affection sticker ping (`u/admin/affection_ping`) onto its own
Telegram bot, decoupling it from the main agent's `telegram_bot_token`.

## What changed
- New Windmill secret variable `u/admin/affection_bot_token` (server-side).
- `affection_ping.schedule.yaml` arg `telegram_bot_token` now references
  `$var:u/admin/affection_bot_token` (was `$var:u/admin/telegram_bot_token`).
- Pushed to the live schedule via the schedules update API (Hard Rule 9 — no sync push).
- No Python changes; the script is token-agnostic (token is a `main()` param).

## Live verification (Hard Rule 17)
- One-off run job `019f0160-d296-8456-85a3-a935a7b36c6f`: success=True.
- `affection_outbox`: new row, delivered=t, no error. Count 49→50.
- Owner confirmed sticker arrived in the group from the NEW bot identity (StraitsAffectionBot).
- Main agent bot still replied to /health — main token unaffected.

## Notes
- Blast radius was zero: every other Telegram script takes its own `telegram_bot_token` arg.
- First of 5 Part-5 hygiene initiatives. Next: schedule-drift reconciliation (already done), earnings_surprises fetcher fix.
