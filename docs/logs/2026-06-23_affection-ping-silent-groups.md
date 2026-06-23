# Affection Ping — Hourly Sticker + Caption with Silent Groups Routing
**Date:** 2026-06-23
**Scope:** `affection_ping.py` (new), `agent/config.py`, `agent/main.py`, `agent.env`, `portfolio/schema.sql`, schedule YAML, 18 new tests.

---

## Motivation

Two requirements from the owner:

1. **Hourly affection ping** — send a random cute sticker with a short LLM-generated affectionate caption to a Telegram group containing the owner and `@ESL1604`. This is a personal automation, not a financial report — Hard Rule 16 (≥500-word self-contained report) does not apply.
2. **Group silence** — the bot must not respond to casual messages in that group (no draft-approval notifications, no auto-replies). It should only respond to `/`-commands or messages prefixed with `@StraitsAgentBot`.

The second requirement was necessary because the agent's existing routing sends all non-owner messages to `handle_contact`, which generates a draft reply and notifies the owner for approval. Without a silence mechanism, every casual message in the affection group would clutter the drafts queue.

---

## Design Decisions

### Group-based delivery (not DM + CC)
Initial plan was to send two DMs per run (recipient + owner CC). Owner proposed a group instead — cleaner: one send per run, both members see the same message, no separate owner CC needed.

### Sticker source: runtime `getStickerSet`
Fetch stickers at runtime via `getStickerSet` API rather than hardcoding `file_id` strings. File IDs can expire if stickers are re-uploaded; runtime fetch is resilient. Default pack: `BubuDudu` (77 stickers — the famous panda couple pack, verified to resolve).

### Emoji filtering (added post-bug-discovery)
The BubuDudu pack has 77 stickers covering many emotions: 50 affectionate (🥰😍😊🤗😘...) and 27 negative (😡😢😭😈😤😰😒😟...). The initial implementation used `random.choice` over the full set, pairing angry/sad/devil stickers with loving captions. Fixed by adding `_AFFECTIONATE_EMOJIS` allowlist — `_fetch_stickers` filters to only affectionate emojis before random selection.

### Caption: Deepseek one-sentence, sent as separate `sendMessage`
`deepseek-chat`, `temperature=0.9`, `max_tokens=80`. Originally designed to be sent as the `caption` parameter of `sendSticker` (single API call). **This did not work** — see Bug #2 below. Caption is now sent as a separate `sendMessage` before the `sendSticker`. Falls back to a hardcoded rotation list of 8 short captions if Deepseek fails — ensures the sticker always sends.

### Separate `affection_outbox` table
Owner requested logging "separate from the other messages to main user". New `affection_outbox` table (7 columns: `recipient_id`, `sticker_pack`, `sticker_file_id`, `caption`, `llm_model`, `delivered`, `error`) — fully isolated from `telegram_outbox`. No `word_count` column (Rule 16 exempt). Health check audits `telegram_outbox` only — unaffected.

### Silent groups: `SILENT_GROUPS` env var
Comma-separated group chat_ids, same pattern as the existing `DRAFTS_GROUP_ID`. New routing branch in `handle_message` — before `handle_contact`, after `DRAFTS_GROUP_ID`. If the message is from a silent group:
- `/command` → strip leading slash, route to `handle_owner` (reuses existing command handler)
- `@StraitsAgentBot text` → strip mention, route to `handle_owner`
- anything else → return immediately (no draft, no auto-reply, no audit row)

`BOT_USERNAME` env var added (default `StraitsAgentBot`) so the mention regex is configurable.

---

## Changes Made

### `windmill/u/admin/affection_ping.py` (new)
- `_AFFECTIONATE_EMOJIS` — allowlist of ~35 positive emojis for sticker filtering
- `_fetch_stickers(bot_token, pack_names)` — calls `getStickerSet` for each pack, filters by affectionate emojis, returns flat list
- `_generate_caption(deepseek_key)` — Deepseek one-sentence caption with fallback rotation
- `_send_message(bot_token, chat_id, text)` — `POST /sendMessage`, returns `(delivered, error)`
- `_send_sticker(bot_token, chat_id, file_id, caption)` — sends caption via `_send_message`, then sticker via `POST /sendSticker` (two API calls — see Bug #2)
- `_log_affection(db, recipient_id, sticker_pack, file_id, caption, llm_model, delivered, error)` — inserts into `affection_outbox`
- `main(...)` — hour-window check (8AM–10PM SGT), fetch stickers, pick random, generate caption, send, log, return result dict

### `windmill/u/admin/affection_ping.script.yaml` + `.script.lock`
- Schema with 6 params: `telegram_bot_token`, `telegram_owner_id`, `affection_group_id`, `affection_sticker_packs`, `deepseek_key`, `portfolio_db`
- Lock file: `requests`, `psycopg2-binary` (+ transitive deps)

### `windmill/u/admin/affection_ping.schedule.yaml`
- Cron: `0 0 8-22 * * *` (Asia/Singapore) — 15 sends/day
- Args use string-form `$var:`/`$res:` references (Hard Rule 11)

### `agent/config.py`
- `SILENT_GROUPS` — set parsed from `SILENT_GROUPS` env var (comma-separated)
- `BOT_USERNAME` — from env, default `StraitsAgentBot` (lstrip `@`)

### `agent/main.py`
- Import `SILENT_GROUPS`, `BOT_USERNAME` from config
- New routing branch in `handle_message`: `elif phone in SILENT_GROUPS: await _handle_silent_group(phone, text, t0)`
- New `_handle_silent_group(group_id, text, t0)` function:
  - `/command` → `cleaned = text[1:]` (strip only leading slash, matches `handle_owner`)
  - `@StraitsAgentBot text` → regex strip mention, route remainder
  - bare mention → return (nothing to act on)
  - anything else → return (silent ignore)

### `agent.env` + `agent.env.example`
- `SILENT_GROUPS=-4830227987` (the affection group chat_id)

### `portfolio/schema.sql`
- New `affection_outbox` table + index on `sent_at DESC`
- Applied to live Postgres via `docker exec psql`

### `shared/override_log.md`
- Rule 16 exemption entry for affection_ping (permanent by design)

---

## Bugs Caught and Fixed

### Bug 0 — `lstrip` vs slice (caught by TDD, pre-deploy)

`test_silent_group_double_slash_only_strips_first` failed on the first run. The initial implementation used `text.lstrip("/")` which strips ALL leading slashes (`//portfolio` → `portfolio`). The test expected `//portfolio` → `/portfolio` (strip only the first, matching `handle_owner`'s `text[1:]` behavior).

**Fix:** Changed `text.lstrip("/")` to `text[1:]` in both `main.py` and the test mirror. This is exactly the kind of subtle inconsistency TDD catches — `lstrip` looks correct at a glance but has different semantics than slice.

### Bug 1 — Negative-emotion stickers paired with affectionate captions (caught by owner, post-deploy)

The BubuDudu pack has 77 stickers: 50 affectionate and 27 negative (😡 angry x3, 😢 crying, 😭 sobbing, 😈 devil, 😤 steaming, 😰 anxious, 😒 unamused, 😟 worried, etc.). The initial implementation used `random.choice` over the full set with no emotion filter. Live-delivered stickers included 😡 paired with the caption "This little guy made me think of you and smile like a goof."

**Fix:** Added `_AFFECTIONATE_EMOJIS` allowlist (~35 positive emojis). `_fetch_stickers` now filters stickers by their `emoji` field before random selection. 50 of 77 stickers pass; 27 negative-emotion stickers are excluded.

**Live verified:** delivered sticker emoji is 😇 (angelic), caption "Just wanted your smile to sneak into my day like this little guy."

### Bug 2 — `sendSticker` caption parameter silently dropped by Telegram (caught by owner, post-deploy)

**This was the most serious bug.** The initial implementation sent the caption as the `caption` parameter of `sendSticker`:

```python
requests.post(f".../sendSticker", json={"chat_id": ..., "sticker": ..., "caption": caption})
```

Telegram's API accepts this parameter without error (`"ok": true`), but **silently drops it** — the caption never appears in the chat. Verified by inspecting the API response: no `caption` field in the returned `result` object, tested with both JSON and form-data payloads.

The owner reported: "none of the captions are being delivered. only stickers are being delivered." This was correct — all 4 stickers sent before the fix had no caption visible in the group.

**Fix:** `_send_sticker` now makes two API calls:
1. `sendMessage` with the caption text (verified: `text` field present in API response)
2. `sendSticker` with just the sticker, no caption (verified: `sticker` field present, emoji 🤭)

**Live verified:** `sendMessage` response has `text: "This sticker's got more bounce than my heart when I think of you."` (msg 2132), `sendSticker` response has `sticker` with emoji 🤭 (msg 2133). Both messages appear in the group.

---

## ⚠️ METHODOLOGY FAILURE — Testing Principles Not Followed

This session committed a serious violation of the artifact-driven testing philosophy documented in `docs/TESTING.md` and encoded as Hard Rules 15–20 in `CLAUDE.md`. Two bugs (Bug #1 and Bug #2) shipped to production because the testing methodology was not followed. A third (Bug #0) was caught only because TDD happened to cover that specific code path — not because the methodology was applied holistically.

### What the methodology requires

From `docs/TESTING.md` → "The Principle":

> A test earns its place only if its failure means the human gets a broken or missing artifact.
>
> Logs, `success: True`, and subject lines are **not** verification.

From `docs/TESTING.md` → "Live Verification Procedure (Hard Rule 17)":

> After any live run of a sending script, all of the following must be true before declaring it works:
> - Fetch the actual delivered artifact body
> - `success: True` / subject line is **not** verification

From CLAUDE.md Hard Rule 17:

> Never claim a workflow output works without reading the actual rendered artifact — email body AND Telegram text — and comparing both to the canonical source. `success: True` and subject lines are not verification.

### What actually happened

1. **Bug #2 (silent caption drop) shipped** because live verification checked `delivered: True` in the Windmill job result and the `affection_outbox` DB row, but **never inspected the actual Telegram API response** to confirm the `caption` field was present. The `sendSticker` API returns `"ok": true` even when it silently drops the caption — exactly the kind of false-positive that Hard Rule 17 exists to catch. The DB row showed `caption: "You're my favorite reason to smile today..."` and `delivered: True`, which was treated as proof of delivery. It was not — the caption was never visible in the group.

2. **Bug #1 (angry stickers) shipped** because there was no test asserting that the **actual delivered sticker's emoji** was affectionate. The test `test_affection_ping_picks_valid_sticker` checked that `_fetch_stickers` returned a non-empty list, but never checked the emoji of the chosen sticker against the affectionate allowlist (because no allowlist existed). The live verification checked the `file_id` in the DB row but never resolved it back to its emoji marker. A simple check of the delivered sticker's emoji — which is visible in the `getStickerSet` response and the `sendSticker` response — would have immediately revealed that 😡 was being sent.

3. **The owner had to report both bugs.** Both were visible in the group chat — angry stickers with no captions. The testing methodology exists precisely so that the human does not have to be the QA layer. Both bugs should have been caught before declaring "done."

### Root cause

The affection_ping script was treated as exempt from the artifact-driven methodology because it is "not a report" (Rule 16 exempt). This is wrong. Rule 16 exempts the ≥500-word requirement — it does not exempt the fundamental principle that **the actual delivered artifact must be inspected, not the metadata about it.** The caption text and the sticker emoji are user-visible fields. They must be verified in the actual Telegram API response, not just in the DB row or job result.

### What should have been done

1. **Before declaring "live verified":** inspect the actual `sendSticker` API response JSON — does it contain a `caption` field? (It did not. This would have caught Bug #2 immediately.)
2. **Before declaring "live verified":** resolve the delivered `file_id` back to its emoji via `getStickerSet` — is the emoji affectionate? (It was 😡. This would have caught Bug #1 immediately.)
3. **Test coverage:** a test that mocks `sendSticker` and asserts the response includes the caption in the `result` object — this test would have failed, revealing that Telegram drops the caption.
4. **Test coverage:** a test that asserts `_fetch_stickers` returns only stickers with affectionate emojis — this test did not exist until Bug #1 was reported.

### Lesson

> **Rule 16 exemption does not mean methodology exemption.** Every sending script — report or not — must verify the actual delivered artifact, not the metadata. `ok: true` is not verification. A DB row with `delivered: True` is not verification. The only verification is reading what the user actually sees.

---

## TDD Evidence

18 new tests across two files:

| File | Section | Tests | Result |
|---|---|---|---|
| `test_windmill_scripts.py` | affection_ping | 9 | GREEN |
| `test_routing.py` | silent groups | 9 | GREEN |

**affection_ping tests:**
1. `test_affection_ping_picks_valid_sticker` — fake getStickerSet, assert valid file_id chosen, angry emoji filtered
2. `test_affection_ping_filters_negative_emojis` — 😡😢😭😈 explicitly filtered out, 🥰😊 kept
3. `test_affection_ping_caption_one_sentence` — fake Deepseek, assert ≤1024 chars, ≤1 sentence
4. `test_affection_ping_send_sticker_payload` — two API calls: sendMessage (text) + sendSticker (no caption)
5. `test_affection_ping_outbox_row_written` — fake psycopg2, assert INSERT with all 7 fields
6. `test_affection_ping_deepseek_failure_fallback` — Deepseek raises, assert fallback caption used
7. `test_affection_ping_skips_outside_window` — patch datetime to 3AM, assert `skipped: True`
8. `test_affection_ping_no_sticker_pack_resolved` — getStickerSet fails, assert RuntimeError
9. `test_affection_ping_group_id_is_negative` — static check: group_id passed through unchanged

**silent group tests:**
1. `test_silent_group_ignores_plain_message` — "hey what's for dinner" → None (ignored)
2. `test_silent_group_ignores_question` — question without / or @ → None
3. `test_silent_group_responds_to_slash_command` — `/macro` → `macro`
4. `test_silent_group_responds_to_mention` — `@StraitsAgentBot macro` → `macro`
5. `test_silent_group_mention_case_insensitive` — `@straitsagentbot` → works
6. `test_silent_group_mention_only_returns_none` — bare mention → None
7. `test_silent_group_double_slash_only_strips_first` — `//portfolio` → `/portfolio`
8. `test_silent_group_config_imported_in_main` — source check: SILENT_GROUPS imported
9. `test_silent_group_config_in_config_py` — source check: SILENT_GROUPS + BOT_USERNAME defined

**Full suite: 643 passed, 1 skipped** (was 625 before this session)

---

## Live Verification (post-fix)

### Sticker + caption delivery

**Final live run** (job `019ef323...`):
```
INFO [Stickers] BubuDudu: 77 total, 50 affectionate (emoji-filtered)
INFO [Affection] Caption (65 chars): This sticker's got more bounce than my heart when I think of you.
INFO [Affection] Sticker delivered to group
```

**Telegram API response verified for both messages:**

`sendMessage` (caption) → message_id 2132:
```
ok: True
text field present: True
text: "This sticker's got more bounce than my heart when I think of you."
```

`sendSticker` (sticker) → message_id 2133:
```
ok: True
sticker field present: True
sticker emoji: 🤭
has caption: False  (expected — caption sent as separate message)
```

**`affection_outbox` row verified:**
```
recipient_id=-4830227987 | sticker_pack=BubuDudu | caption="This sticker's got more bounce..." | llm_model=deepseek-chat | delivered=t | error=NULL
```

### Agent silence in group

**Plain message** ("hey what is for dinner tonight") → webhook returned `{"status":"ok"}`, no new draft in `agent_draft_queue`, no conversation history row. Bot stayed silent.

**`/macro` command** → webhook returned `{"status":"ok"}`, conversation history shows:
```
-4830227987 | user | macro | 2026-06-23 05:55:55
-4830227987 | assistant | ━━━━━━━━━━━━━━━━━━━━ **Indices** S&P 500 7,473 ▼1.1%... | 2026-06-23 05:56:21
```
Bot responded with full macro brief in the group. No draft created.

### Old draft cleanup
Draft row 219 (the original test message `@StraitsAgentBot hello this is a test message`) was resolved as `rejected` to clear the stale pending state from before the silence routing was deployed.

---

## Windmill Resources Created

| Path | Type | Value |
|---|---|---|
| `u/admin/affection_group_id` | variable | `-4830227987` (group chat_id) |
| `u/admin/affection_sticker_packs` | variable | `BubuDudu` |

Schedule created via REST API `POST /api/w/admins/schedules/create` — path `u/admin/affection_ping`, cron `0 0 8-22 * * *`, timezone `Asia/Singapore`, enabled.

---

## Docs Updated

- `CLAUDE.md` — Current Status, Workflows Built table (affection_ping row), Running Services (silent groups note), Telegram Agent summary (643 tests, silent groups)
- `docs/ROADMAP.md` — Windmill Resources table (2 new variables)
- `docs/WORKFLOW_ARCHITECTURE.md` — Section 9: affection_ping spec (non-report, Rule 16 exempt)
- `shared/override_log.md` — Rule 16 exemption entry
- `agent.env.example` — `SILENT_GROUPS` documented

---

## Commits

| Commit | Description |
|---|---|
| `1355d3c` | feat: affection_ping hourly sticker + caption with silent groups routing |
| `d1d3777` | docs: implementation log (initial — pre-bug-discovery) |
| `f6dbe4e` | fix: filter stickers by affectionate emoji — exclude angry/sad/devil stickers |
| `69504ab` | fix: send caption as separate sendMessage — sendSticker caption silently dropped |
| (this commit) | docs: rewrite implementation log with methodology failure note |
