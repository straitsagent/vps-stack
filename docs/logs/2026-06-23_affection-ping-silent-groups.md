# Affection Ping — Hourly Sticker + Caption with Silent Groups Routing
**Date:** 2026-06-23
**Scope:** `affection_ping.py` (new), `agent/config.py`, `agent/main.py`, `agent.env`, `portfolio/schema.sql`, schedule YAML, 17 new tests.

---

## Motivation

Two requirements from the owner:

1. **Hourly affection ping** — send a random cute sticker with a short LLM-generated affectionate caption to a Telegram group containing the owner and `@ESL1604`. This is a personal automation, not a financial report — Hard Rule 16 (≥500-word self-contained report) does not apply.
2. **Group silence** — the bot must not respond to casual messages in that group (no draft-approval notifications, no auto-replies). It should only respond to `/`-commands or messages prefixed with `@StraitsAgentBot`.

The second requirement was necessary because the agent's existing routing sends all non-owner messages to `handle_contact`, which generates a draft reply and notifies the owner for approval. Without a silence mechanism, every casual message in the affection group would clutter the drafts queue.

---

## Design Decisions

### Group-based delivery (not DM + CC)
Initial plan was to send two DMs per run (recipient + owner CC). Owner proposed a group instead — cleaner: one `sendSticker` call per run, both members see the same message, no separate owner CC needed.

### Sticker source: runtime `getStickerSet`
Fetch stickers at runtime via `getStickerSet` API rather than hardcoding `file_id` strings. File IDs can expire if stickers are re-uploaded; runtime fetch is resilient. Default pack: `BubuDudu` (77 stickers — the famous panda couple pack, verified to resolve).

### Caption: Deepseek one-sentence
`deepseek-chat`, `temperature=0.9`, `max_tokens=80`. Sent as the `caption` parameter of `sendSticker` (single API call, sticker + caption appear together in chat). Falls back to a hardcoded rotation list of 8 short captions if Deepseek fails — ensures the sticker always sends.

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

### `windmill/u/admin/affection_ping.py` (new — 7.2 KB)
- `_fetch_stickers(bot_token, pack_names)` — calls `getStickerSet` for each pack, returns flat list
- `_generate_caption(deepseek_key)` — Deepseek one-sentence caption with fallback rotation
- `_send_sticker(bot_token, chat_id, file_id, caption)` — `POST /sendSticker`, returns `(delivered, error)`
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

## Bug Caught by TDD

`test_silent_group_double_slash_only_strips_first` failed on the first run. The initial implementation used `text.lstrip("/")` which strips ALL leading slashes (`//portfolio` → `portfolio`). The test expected `//portfolio` → `/portfolio` (strip only the first, matching `handle_owner`'s `text[1:]` behavior).

**Fix:** Changed `text.lstrip("/")` to `text[1:]` in both `main.py` and the test mirror. Test passed on re-run.

This is exactly the kind of subtle inconsistency TDD catches — `lstrip` looks correct at a glance but has different semantics than slice.

---

## TDD Evidence

17 new tests across two files:

| File | Section | Tests | Result |
|---|---|---|---|
| `test_windmill_scripts.py` | affection_ping | 8 | GREEN |
| `test_routing.py` | silent groups | 9 | GREEN |

**affection_ping tests:**
1. `test_affection_ping_picks_valid_sticker` — fake getStickerSet, assert valid file_id chosen
2. `test_affection_ping_caption_one_sentence` — fake Deepseek, assert ≤1024 chars, ≤1 sentence
3. `test_affection_ping_send_sticker_payload` — capture requests.post, assert URL + payload
4. `test_affection_ping_outbox_row_written` — fake psycopg2, assert INSERT with all 7 fields
5. `test_affection_ping_deepseek_failure_fallback` — Deepseek raises, assert fallback caption used
6. `test_affection_ping_skips_outside_window` — patch datetime to 3AM, assert `skipped: True`
7. `test_affection_ping_no_sticker_pack_resolved` — getStickerSet fails, assert RuntimeError
8. `test_affection_ping_group_id_is_negative` — static check: group_id passed through unchanged

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

**Full suite: 642 passed, 1 skipped** (was 625 before this session)

---

## Live Verification

### Sticker delivery (2 runs)

**Run 1** (job `019ef309...`, no DB — test run):
```
INFO [Affection] Fetching stickers from 1 pack(s)...
INFO [Stickers] BubuDudu: 77 stickers
INFO [Affection] Chose sticker file_id=CAACAgUAAxUAAWo5... (pack=BubuDudu)
INFO [Affection] Caption (59 chars): This little guy made me think of you and smile like a goof.
INFO [Affection] Sticker delivered to group
```
Result: `delivered: True`, `caption: "This little guy made me think of you and smile like a goof."`

**Run 2** (job `019ef30a...`, with real `portfolio_db` resource):
```
INFO [Affection] Caption (86 chars): You're my favorite reason to smile today, all wrapped up in this silly little sticker.
INFO [Affection] Sticker delivered to group
```

**`affection_outbox` row verified:**
```
id=1 | recipient_id=-4830227987 | sticker_pack=BubuDudu | caption="You're my favorite reason to smile today..." | llm_model=deepseek-chat | delivered=t | error=NULL
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

- `CLAUDE.md` — Current Status, Workflows Built table (affection_ping row), Running Services (silent groups note), Telegram Agent summary (642 tests, silent groups)
- `docs/ROADMAP.md` — Windmill Resources table (2 new variables)
- `docs/WORKFLOW_ARCHITECTURE.md` — Section 9: affection_ping spec (non-report, Rule 16 exempt)
- `shared/override_log.md` — Rule 16 exemption entry
- `agent.env.example` — `SILENT_GROUPS` documented

---

## Commit

`1355d3c` — feat: affection_ping hourly sticker + caption with silent groups routing
