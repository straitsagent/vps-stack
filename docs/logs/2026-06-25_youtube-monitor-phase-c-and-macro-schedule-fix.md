# youtube_monitor Phase C + Macro Research Schedule Fix — Implementation Log

**Date:** 2026-06-25  
**Scope:** Complete Phase C artifact testing rollout for `youtube_monitor`; fix `macro_research` schedule running at 11PM SGT instead of 7AM SGT; Hard Rule 17 live verification for both

---

## Bug 1 — Macro Research schedule running at 11PM SGT

**File:** `windmill/u/admin/macro_research.schedule.yaml`

**Problem:** Cron expression `0 0 23 * * 1-5` with `timezone: Asia/Singapore` fires at 23:00 SGT (11PM), not 7AM SGT as intended. Health check ops status showed "❌ Macro Research — No runs found" with AI diagnosis "never been executed or scheduled" — because on a 7AM check, the most recent scheduled run from the night before was outside the lookback window.

**Root cause:** Wrong hour field in cron. `0 0 23 * * 1-5` = 23:00. For 7AM: `0 0 7 * * 1-5`.

**Fix:** Changed line 1 of the schedule YAML from `schedule: '0 0 23 * * 1-5'` to `schedule: '0 0 7 * * 1-5'` and pushed to Windmill API via `wmill script preview` (which pushes schedule changes).

**Side effect:** 17 stale queued jobs had accumulated — one per scheduled tick that fired at 11PM each night. Since `no_flow_overlap: true` was set, each run queued the next one, and the queue backed up. All 17 were cancelled via the Windmill jobs API. One remaining job (the legitimate next-run future tick) could not be cancelled — Windmill correctly rejected it with "Cannot cancel a future tick of a schedule, cancel the schedule directly."

**Verification (Hard Rule 17):**
- Email: Subject "Macro Research — Thu 25 Jun 2026, 2:15 PM SGT" received, body 28,335 chars, VIX ✓, 10Y ✓
- Telegram: `delivered=true`, `word_count=667` ≥500, `error=null` (sent at 14:16 SGT)
- `.md` file: `/root/research/macro/2026-06-25_1415.md` written with valid JSON front-matter + indicators data

---

## Bug 2 — `html.escape()` breaks `_agree` test for video titles with apostrophes

**File:** `agent/tests/test_windmill_scripts.py`

**Problem:** `build_email_html` in `youtube_monitor.py` calls `html.escape(v["title"])` on video titles before inserting them into the email HTML. An apostrophe (`'`) in the ASD video title was stored as `&#x27;` in the rendered email, so `assert email_html contains _YTM_ASD_VIDEO_TITLE` failed even though the title was correctly present.

**Initial ASD title:** `"AI infrastructure transformation: Deepseek's latest benchmarks"`

**Error:**
```
AssertionError: ASD shared field 'video title'
("AI infrastructure transformation: Deepseek's latest benchmarks")
not found in email_html
```

**Fix:** Changed `_YTM_ASD_VIDEO_TITLE` to `"AI infrastructure transformation: Deepseek benchmark deep dive"` — no apostrophe. All ASD strings used in `_agree` assertions must be apostrophe-free (and more broadly, must not contain any character that `html.escape()` would transform).

**Lesson:** When asserting world-fixture strings against rendered HTML, verify the fixture strings round-trip through any HTML escaping the template applies. Safe characters: alphanumeric, spaces, hyphens, colons, periods.

---

## Bug 3 — `Edit` tool ambiguity: two matches for inline SMTP block

**File:** `windmill/u/admin/youtube_monitor.py`

**Problem:** After factoring out `_send_email` as a named seam function (which contains the same SMTP boilerplate), the `Edit` tool found 2 matches when trying to replace the inline SMTP block in `main()` — one in the new `_send_email` definition and one in the original inline location.

**Fix:** Expanded the `old_string` to include unique surrounding context — the `subject = f"YouTube Digest..."` line above and `est_cost` reference below — making the match unique to the `main()` occurrence.

**Lesson:** When factoring out inline code into a named function, always replace the inline occurrence *after* defining the new function, and use enough surrounding context to ensure uniqueness.

---

## Bug 4 — Direct Windmill API trigger with `$var:` references passes `None`

**File:** N/A (operational, not code)

**Problem:** When triggering `youtube_monitor` via the Windmill REST API and passing `"$var:u/admin/youtube_feeds"` as a literal string in the `args` payload, the script received `youtube_feeds=None`. The Windmill worker recognizes the `$var:` prefix and attempts to resolve it, but fails silently in worker context (the variable is resolved only by the scheduler, not the worker). The result is `None` passed to `json.loads()`, causing `TypeError: the JSON object must be str, bytes or bytearray, not NoneType`.

**Fix:** Use `wmill script preview u/admin/youtube_monitor.py` instead. The CLI resolves all `$var:` and `$res:` references locally before sending the job to the API, so the worker receives fully-resolved values.

**Lesson:** `$var:` and `$res:` strings are only auto-resolved in two contexts: (1) scheduled runs, where Windmill resolves before enqueuing; (2) `wmill script preview`, where the CLI resolves locally. Direct REST API calls with `$var:` strings → `None` on the worker.

---

## Bug 5 — `patch.object(mod, "os", mock_os)` fails for locally-imported `os`

**File:** `agent/tests/test_windmill_scripts.py`

**Problem:** `youtube_monitor.py` had `import os as _os` inside `main()` (local import to avoid a name collision with a parameter). `patch.object(mod, "os", mock_os)` patches the module-level `os` attribute, but a local `import os` inside a function re-imports from `sys.modules` and is not affected by the patch. `os.makedirs` was still being called for real, creating directories on the test runner's filesystem.

**Fix:** Replaced `patch.object(mod, "os", mock_os)` with `patch("os.makedirs")` (patching the global `os.makedirs` directly). This intercepts the call regardless of whether `os` was imported at module level or inside the function.

**Lesson:** `patch.object(mod, "os", ...)` only works if the module uses the module-level `os` binding. For functions that do `import os` internally, patch the target directly: `patch("os.makedirs")` or `patch("os.path.exists")`.

---

## Phase C Rollout Summary

All 7 Phase C scripts now have artifact harnesses:

| Script | Seams | ASD | Tests | Live verify |
|---|---|---|---|---|
| `portfolio_email` | ✅ | ✅ | ✅ | — |
| `portfolio_review` | ✅ | ✅ | ✅ | — |
| `portfolio_rationalization` | ✅ | ✅ | ✅ | — |
| `portfolio_move_monitor` | ✅ | ✅ | ✅ | — |
| `portfolio_analyst_alert` | ✅ | ✅ | ✅ | — |
| `youtube_monitor` | ✅ | ✅ | ✅ | ✅ (2026-06-25) |
| `macro_research` | — | — | — | ✅ (2026-06-25, schedule fix) |

`macro_research` is next for Phase C artifact harness — seams and ASD still to be written.
