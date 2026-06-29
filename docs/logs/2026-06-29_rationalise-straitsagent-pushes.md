# Implementation Log — Rationalise StraitsAgent Telegram Pushes
**Date:** 2026-06-29
**Plan:** `docs/plans/2026-06-29_rationalise-straitsagent-pushes.md`
**Executor:** opencode/Deepseek-V4

---

## 1. Summary

Decoupled 4 Windmill automations from Telegram dispatch (macro_research, morning_news_digest, portfolio_email, youtube_monitor). YouTube schedule moved from 6-hourly to daily 18:00 SGT; email now renders the synthesis narrative. 3 formatter scripts retained on disk (reversible). 7 tests removed, 3 inverted to absence-assertions, 1 new. Pre-existing test harness issues (from the yfinance→Finnhub migration) also fixed. Dead `telegram_utils.py` deleted.

---

## 2. What was built / changed

| E# | File | Change |
|----|------|--------|
| E1 | `macro_research.py` | Removed `_dispatch_formatter` def + dispatch call. Params kept in signature. |
| E2 | `morning_news_digest.py` | Removed `_send_telegram` helper + Telegram block (`if telegram_bot_token...`). |
| E3 | `portfolio_email.py` | Removed `_dispatch_formatter` def + dispatch block. |
| E4 | `youtube_monitor.py` | Signature change: `build_email_html(videos, synthesis, prompt_tokens, completion_tokens)`. Reordered main() so email is sent AFTER synthesis is computed. Removed Telegram dispatch + `_dispatch_formatter` def. |
| E5 | `youtube_monitor_hourly.schedule.yaml` | `0 0 */6 * * *` → `0 0 18 * * *` |
| E6 | `test_windmill_scripts.py` | Removed 7 Telegram-dispatch tests; inverted 3 to absence-assertions; added `test_youtube_email_renders_synthesis`. Fixed pre-existing macro_research artifact harness (yfinance→Finnhub migration: `_fetch_yahoo_macro` → `_fetch_finnhub_data`, `"yahoo"` → `"market"` key). Deleted `telegram_utils.py` (dead code). |
| E7 | `CLAUDE.md`, `ROADMAP.md` | Noted retired formatters; Part 1 YouTube cadence → daily 18:00 SGT; Part 7 ticked WS-B/WS-C first increment. |

---

## 3. Key decisions

- **Test asymmetry resolved per owner direction:** Both `test_portfolio_email_has_telegram_params` and `test_youtube_monitor_has_telegram_params` removed (owner chose symmetric removal even though params stay in signature).
- **Pre-existing test failures fixed:** The macro_research artifact harness (from a prior yfinance→Finnhub migration) had 5 broken tests (wrong mock targets, wrong schema keys). These were out of plan scope but blocked the G4 verify script (requires `pytest exit code 0`). Fixed in same pass.
- **`telegram_utils.py` deleted:** No formatter imported it. Test had been asserting it should be deleted since a prior cleanup — this was the first executor to actually delete it.

---

## 4. Deviation log

| Step | Deviation | Resolution |
|------|-----------|------------|
| E6 | Plan only listed 5 tests to remove + 3 to invert. But the parameterized `test_main_script_dispatches_formatter` and the artifact harnesses (`_render_portfolio_email_artifacts`, `_render_youtube_monitor_artifacts`, `_render_macro_research_artifacts`) also broke because they patched `_dispatch_formatter` which no longer exists in some scripts. | Split `_DISPATCH_MAIN_NAMES` from `_MAIN_SCRIPT_NAMES`; removed `_dispatch_formatter` patches from harnesses that no longer have the function. |
| E6 | Pre-existing test failures: 5 macro_research tests from yfinance→Finnhub migration (wrong mock targets, schema key `"yahoo"` → `"market"`). | Fixed harness patches and test assertions. |
| G4 | Verify script's `CURRENT_DATE` outbox query returned 2 (pre-deploy sends at 00:55 and 04:00 UTC). The `sent_at >= deploy_time` query returns 0 — no regression. | Used precise timestamp in final verification; noted in log. |

---

## 5. Verification output

```
=== LOCKED ORACLE ===
LOCKED ORACLE: PASS

=== pytest (agent container) ===
495 passed, 1 skipped in 25.10s

=== YouTube schedule ===
Schedule: 0 0 18 * * *
Enabled: true

=== Outbox: zero sends post-deploy (after 07:45 UTC) ===
PASS sends=0

=== Formatter scripts retained ===
PASS: macro_daily_push_telegram
PASS: portfolio_email_telegram
PASS: youtube_monitor_telegram

OVERALL: PASS
```

---

## 6. Remaining items

- Live email verification (IMAP) pending next scheduled run: youtube_monitor (daily 18:00 SGT), macro_research (07:00 SGT Mon–Fri), portfolio_email (06:00/18:00 SGT). The G3 evidence requirement (email bodies) will be met by these runs.
- StraitsAgent's analytical commands for retired Telegram formatters (`/youtube_digest`, `/portfolio` summary) are unaffected — they use the agent's own Telegram send, not the Windmill formatter dispatch.
