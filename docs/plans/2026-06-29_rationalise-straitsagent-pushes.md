---
Subject: Rationalise StraitsAgent Telegram pushes — decouple 4 Windmill automations from Telegram, daily-ify YouTube
Date: 2026-06-29
Status: approved
Planner model: claude-sonnet-4-6
Executor: opencode/Deepseek (clean-checkout handoff)
Risk tier: MEDIUM (modifies 4 live workflows + 1 schedule + tests; reversible — formatter scripts retained)
Hard Rules in force: [7, 8, 9, 11, 12, 15, 17, 18, 20, 22]
Files to read before executing: CLAUDE.md, docs/TESTING.md, docs/EXECUTOR_CONTRACT.md
Parent roadmap: docs/plans/2026-06-29_hermes-integration-roadmap.md (first concrete WS-B/WS-C increment)
---

# Plan: Rationalise StraitsAgent Telegram pushes

## Context

The owner's Telegram DM receives ~9–10 proactive pushes/day from Windmill automations. Agreed end-state:
StraitsAgent Telegram becomes a manual-trigger interface only; Windmill automations produce a rich `.md`
(synthesis at the `.md` stage) + an email (the `.md` rendered readable); **Hermes** will later consume
`/research/**.md` and decide what to push. This plan executes the first cut.

**This plan: stop FOUR automations from pushing to Telegram, and convert YouTube to a single daily digest
whose email renders the synthesis narrative + the per-video list.**

## Executor environment caveats (opencode — read first)

- Deploy each script with `wmill script push <path>` run **from `/root/windmill`** — run it yourself
  (no PostToolUse autopush under opencode). **Never** `wmill sync push` (Hard Rule 9).
- Run tests inside the agent container: `docker exec root-straitsagent-1 python -m pytest tests/test_windmill_scripts.py -q`.
- Run git from `/root` only. Schedule args stay string-form `$var:`/`$res:` (Hard Rule 11).
- Do **not** delete any formatter script or any Windmill resource/variable (Hard Rule 8).
- STOP and report on any deviation (G5). Do not edit the `# LOCKED ORACLE` block (G1).

## Scope

| Script | Change |
|---|---|
| `macro_research` | Remove Telegram dispatch (`macro_daily_push_telegram`). Keep `.md` + email. |
| `morning_news_digest` | Remove direct Telegram send block + unused helper. Keep `.md` + email + idea_extractor. |
| `portfolio_email` | Remove Telegram dispatch (`portfolio_email_telegram`) + now-unused `_dispatch_formatter` def. Keep `.md` + email. |
| `youtube_monitor` | (a) schedule 6-hourly → **daily 18:00 SGT**; (b) email renders synthesis + video list; (c) remove Telegram dispatch. Keep idea_extractor. |

**OUT of scope — DO NOT TOUCH:** `portfolio_move_monitor` (×2), `health_check`, `portfolio_analyst_alert`,
`portfolio_earnings_alert`, `portfolio_earnings_post_check`, `portfolio_review`, `portfolio_rationalization`,
`position_sentinel`, `affection_ping`. Their dispatch-assertion tests stay green and unchanged.

**Reversibility:** the 3 orphaned formatter scripts (`macro_daily_push_telegram.py`, `portfolio_email_telegram.py`,
`youtube_monitor_telegram.py`) are **retained on disk** — just no longer dispatched.

---

## Exact edits (anchor on the quoted strings; clean-checkout line numbers may differ)

### E1 — `windmill/u/admin/macro_research.py`

**E1a** Delete the dispatch call. Remove this block verbatim:
```python
    # ── Dispatch Telegram formatter ───────────────────────────────────────────
    _dispatch_formatter(md_path, telegram_bot_token, telegram_owner_id,
                        portfolio_db, deepseek_key, wm_token)

```
**E1b** Delete the now-unused `_dispatch_formatter` function (the whole `def _dispatch_formatter(md_path: str, telegram_bot_token: str, ...)` through its final `return ""`), and its `# ── Telegram formatter dispatch ──` header comment.
**Leave** `main()`'s `telegram_bot_token`/`telegram_owner_id` params in the signature (harmless; keeps schedule args valid).

### E2 — `windmill/u/admin/morning_news_digest.py`

**E2a** Delete the entire `if telegram_bot_token and telegram_owner_id:` block that builds `tg_text` and calls
`_send_telegram(telegram_bot_token, telegram_owner_id, tg_text)` (the block that ends with `"\n\n_Full digest → email_"` then the `_send_telegram(...)` call).
**E2b** Delete the now-unused `def _send_telegram(bot_token: str, chat_id: str, text: str):` helper (through its `except Exception as e: log.warning(f"[Telegram] Failed to send: {e}")`).
**Keep** the `idea_extractor` dispatch (different function) and the email send untouched.

### E3 — `windmill/u/admin/portfolio_email.py`

**E3a** Delete the dispatch block:
```python
    # ── Dispatch Telegram formatter ──────────────────────────────────────────
    if telegram_bot_token and telegram_owner_id:
        _dispatch_formatter(
            "portfolio_email_telegram", md_path,
            telegram_bot_token, telegram_owner_id,
            portfolio_db, wm_token,
        )
```
**E3b** Delete the now-unused `def _dispatch_formatter(formatter_name: str, md_path: str, ...)` function (through its final `return ""`). (Confirm no other caller first: `grep -n _dispatch_formatter portfolio_email.py` must show only the def after E3a — if any other call remains, keep the def and STOP to report.)

### E4 — `windmill/u/admin/youtube_monitor.py`  (largest change)

**E4a — `build_email_html` accepts + renders synthesis.** Change the signature:
```python
def build_email_html(videos: list, prompt_tokens: int, completion_tokens: int) -> str:
```
to
```python
def build_email_html(videos: list, synthesis: str, prompt_tokens: int, completion_tokens: int) -> str:
```
Then, immediately AFTER the est-cost `<p>...est. ${est_cost:.4f}</p>'` line and BEFORE `for v in summarised:`, insert:
```python
    if synthesis:
        _paras = [p.strip() for p in synthesis.split("\n\n") if p.strip()]
        S += '<div style="margin:0 0 24px;padding:16px 18px;background:#f7f9fb;border-left:4px solid #2c3e50;">'
        S += '<p style="margin:0 0 10px;font-size:13px;font-weight:bold;color:#2c3e50;text-transform:uppercase;letter-spacing:0.5px;">Daily Synthesis</p>'
        for _p in _paras:
            S += f'<p style="margin:0 0 10px;font-size:13px;color:#444;line-height:1.6;">{html_mod.escape(_p)}</p>'
        S += '</div>'
```

**E4b — reorder `main()` so the email is sent AFTER `synthesis` is computed.**
Replace the existing email block:
```python
    log.info("Sending email...")
    html = build_email_html(results, total_prompt_tokens, total_completion_tokens)
    now_sgt = datetime.now(SGT).strftime("%d %b %Y, %H:%M SGT")
    n_summarised = sum(1 for v in results if v.get("summary"))
    n_bare = len(results) - n_summarised
    subject = f"YouTube Digest — {now_sgt} ({n_summarised} new)" + (f" + {n_bare} no transcript" if n_bare else "")
    _send_email(smtp_resource, recipient_email, subject, html)

    est_cost = (total_prompt_tokens / 1_000_000) * 0.14 + (total_completion_tokens / 1_000_000) * 0.28
    log.info(f"Deepseek: {total_prompt_tokens:,} prompt + {total_completion_tokens:,} completion tokens · est. ${est_cost:.4f}")
```
with **only the bookkeeping** (drop the email build/send here):
```python
    now_sgt = datetime.now(SGT).strftime("%d %b %Y, %H:%M SGT")
    n_summarised = sum(1 for v in results if v.get("summary"))
    n_bare = len(results) - n_summarised

    est_cost = (total_prompt_tokens / 1_000_000) * 0.14 + (total_completion_tokens / 1_000_000) * 0.28
    log.info(f"Deepseek: {total_prompt_tokens:,} prompt + {total_completion_tokens:,} completion tokens · est. ${est_cost:.4f}")
```
Then, immediately AFTER the `.md` is written — the line `log.info(f"[md] Written {md_path}")` — insert the email send (synthesis now exists):
```python

    # ── Send email (renders the .md synthesis + per-video list) ──────────────
    log.info("Sending email...")
    html = build_email_html(results, synthesis, total_prompt_tokens, total_completion_tokens)
    subject = f"YouTube Digest — {now_sgt} ({n_summarised} new)" + (f" + {n_bare} no transcript" if n_bare else "")
    _send_email(smtp_resource, recipient_email, subject, html)
```

**E4c — remove the Telegram dispatch.** Delete this block (KEEP the `_dispatch_idea_extractor` block above it):
```python
    if telegram_bot_token and telegram_owner_id:
        _dispatch_formatter(
            "youtube_monitor_telegram", md_path,
            telegram_bot_token, telegram_owner_id,
            portfolio_db, wm_token,
        )
```
Leave `youtube_monitor`'s `_dispatch_formatter` def in place ONLY if still referenced; after E4c it is unused → delete it too (mirror E3b; verify with grep first).

### E5 — `windmill/u/admin/youtube_monitor_hourly.schedule.yaml`

Change `schedule: 0 0 */6 * * *` → `schedule: 0 0 18 * * *`. Leave everything else (path stays
`u/admin/youtube_monitor` to avoid schedule drift; filename misnomer is acceptable this round).
Push with: `wmill schedule push u/admin/youtube_monitor_hourly.schedule.yaml u/admin/youtube_monitor_hourly` from `/root/windmill`.

### E6 — Tests (`agent/tests/test_windmill_scripts.py`) — by function name (stable across checkouts)

**Remove** (dispatch no longer exists):
- `test_youtube_monitor_has_telegram_params`
- `test_youtube_monitor_sends_telegram_when_videos_found`
- `test_youtube_monitor_telegram_guarded_by_token_check`
- `test_youtube_telegram_includes_links`
- `test_portfolio_email_telegram_guarded_by_token_check`

**Invert** the dispatch-presence assertions so they assert ABSENCE (rename to `_no_longer_dispatches_telegram`):
- the macro test asserting `"macro_daily_push_telegram" in src` → assert `"macro_daily_push_telegram" not in src`
- the portfolio_email test asserting `"portfolio_email_telegram" in src` → assert `"portfolio_email_telegram" not in src`
- the youtube test asserting `"youtube_monitor_telegram" in src` → assert `"youtube_monitor_telegram" not in src`

**Add** `test_youtube_email_renders_synthesis` (artifact test, see G1 oracle below).

**Do NOT change** `test_portfolio_email_telegram_includes_date` / `_includes_dollar_impact` — those test the
retained `portfolio_email_telegram.py` formatter (unchanged). Also DO NOT touch move_monitor/rationalization/
health_check dispatch tests (out of scope).

If a `morning_news_digest` test asserts it sends Telegram, remove/invert it the same way (grep `morning_news` + `telegram`).

### E7 — Docs

- `CLAUDE.md`: in the "Telegram formatter architecture" note, record that macro/portfolio_email/youtube
  Telegram pushes are **retired** (formatters retained, no longer dispatched); only move_monitor, review,
  rationalization, analyst_alert, health_check still push.
- `docs/ROADMAP.md`: Part 1 — YouTube cadence now daily 18:00 SGT; Part 7 — tick WS-B/WS-C first increment.

---

## LOCKED ORACLE (G1) — copy verbatim, do not modify assertions

```python
# LOCKED ORACLE — copy verbatim, do not modify assertions.
import os
WM = "/root/windmill/u/admin"
def rd(f): return open(os.path.join(WM, f)).read()

# O1: the 4 production paths no longer dispatch/send Telegram
assert "macro_daily_push_telegram" not in rd("macro_research.py"), "macro still dispatches telegram"
assert "_send_telegram(" not in rd("morning_news_digest.py"), "news still sends telegram"
assert "portfolio_email_telegram" not in rd("portfolio_email.py"), "portfolio_email still dispatches telegram"
assert "youtube_monitor_telegram" not in rd("youtube_monitor.py"), "youtube still dispatches telegram"

# O2: coherence seam (idea_extractor) preserved in news + youtube
assert "idea_extractor" in rd("morning_news_digest.py"), "news idea_extractor dropped — REGRESSION"
assert "idea_extractor" in rd("youtube_monitor.py"), "youtube idea_extractor dropped — REGRESSION"

# O3: youtube schedule is daily 18:00, not 6-hourly
sy = rd("youtube_monitor_hourly.schedule.yaml")
assert "0 0 18 * * *" in sy and "*/6" not in sy, "youtube schedule not daily 18:00"

# O4: youtube email renders synthesis (synthesis is a param AND passed in the send call)
ym = rd("youtube_monitor.py")
assert "def build_email_html(videos: list, synthesis: str," in ym, "build_email_html missing synthesis param"
assert "build_email_html(results, synthesis," in ym, "email not built from synthesis"

# O5: formatter scripts retained on disk (reversible)
for f in ["macro_daily_push_telegram","portfolio_email_telegram","youtube_monitor_telegram"]:
    assert os.path.exists(os.path.join(WM, f+".py")), f+" deleted — must be retained"

# O6: out-of-scope pushers UNCHANGED (still dispatch)
assert "portfolio_move_monitor_telegram" in rd("portfolio_move_monitor.py"), "move_monitor wrongly modified"
assert "health_check_telegram" in rd("health_check.py"), "health_check wrongly modified"

print("LOCKED ORACLE: PASS")
```

The pytest test `test_youtube_email_renders_synthesis` must assert (fixture-unique, not boilerplate): build
a fake `results` list + a synthesis string containing the sentinel `"SYNTH_SENTINEL_PARAGRAPH"`, call
`build_email_html(results, synthesis, 0, 0)`, and `assert "SYNTH_SENTINEL_PARAGRAPH" in html` AND
`assert "Daily Synthesis" in html`.

## RED-proof (G2)
Run the LOCKED ORACLE **before** edits — O1, O3, O4 must FAIL (telegram strings still present; schedule still
`*/6`; `build_email_html` has no synthesis param). Paste that RED output. Run `test_youtube_email_renders_synthesis`
before E4 — it must FAIL (TypeError/missing arg). Paste GREEN for both after edits.

## Asserting verify script (G4)

```bash
#!/bin/bash
set -u; fail=0
echo "=== LOCKED ORACLE ==="
python3 - <<'PY' || fail=1
# (paste the LOCKED ORACLE block here verbatim)
PY

echo "=== pytest (agent container) ==="
docker exec root-straitsagent-1 python -m pytest tests/test_windmill_scripts.py -q 2>&1 | tail -5
[ ${PIPESTATUS[0]} -eq 0 ] || fail=1

echo "=== live: zero Telegram sends from retired scripts today ==="
docker exec root-portfolio_postgres-1 psql -U portfolio_user -d portfolio -tAc \
 "SELECT COALESCE(SUM(c),0) FROM (SELECT COUNT(*) c FROM telegram_outbox
   WHERE sent_at >= CURRENT_DATE AND script_name IN
   ('macro_daily_push','portfolio_email','youtube_monitor')) t" \
| { read n; [ "${n:-1}" -eq 0 ] && echo "PASS sends=$n" || { echo "FAIL sends=$n"; fail=1; }; }

[ $fail -eq 0 ] && echo "PASS" || { echo "OVERALL FAIL"; exit 1; }
```
Note: run the outbox check AFTER triggering one live run of each of macro_research / portfolio_email /
youtube_monitor today, so a non-zero count would prove a regression. Confirm each email arrived (IMAP/inbox)
and the YouTube email body contains the synthesis narrative (grep the sent HTML for a synthesis sentence).

## Acceptance Gate (reviewer flips Status → done)
- [ ] LOCKED ORACLE PASS (committed tests diff-clean vs the block).
- [ ] RED pasted for O1/O3/O4 + `test_youtube_email_renders_synthesis`; GREEN pasted.
- [ ] Verify script output pasted, ends `PASS` (outbox query = 0 after live runs).
- [ ] Each of the 4 emails arrived; YouTube email shows synthesis + video list.
- [ ] YouTube schedule confirmed daily 18:00 SGT (Windmill next_run).
- [ ] idea_extractor intact (news + youtube); out-of-scope pushers untouched (O6).
- [ ] Formatter scripts retained on disk.
- [ ] CLAUDE.md + ROADMAP updated.

## Execution
1. Set Status: executing, commit.
2. Run LOCKED ORACLE RED + the youtube test RED; paste.
3. Apply E1→E7. `py_compile` each script; `wmill script push` each; push the schedule.
4. Run LOCKED ORACLE GREEN + full pytest GREEN; paste.
5. Trigger one live run each (macro_research, portfolio_email, youtube_monitor); run the verify script; paste output ending `PASS`.
6. Update docs. Set Status: done, commit.
Do not modify out-of-scope scripts/schedules. Do not delete formatter scripts or any resource/variable.
STOP and report on any deviation.
