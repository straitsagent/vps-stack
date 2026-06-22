# Full Codebase Audit — VPS Automation Stack

**Date:** 2026-06-16
**Mode:** Read-only — no files modified during audit
**Baseline:** `main` @ `4bdc17d` (clean working tree, up to date with `origin/main`)
**Scope:** Windmill scripts (17), Telegram agent (13 modules, 272 tests), PostgreSQL schema/seed, infra & Claude Code config, documentation (11 docs)

---

## Executive Summary

The stack is **functional and well-tested in the inner core** (Telegram agent tools, `research_tool`, `stock_data_fetcher`, `portfolio_rationalization` — 130 tests covering ~5,200 LOC of the most complex code). But there are **systemic hygiene issues** outside that core: 10 of 17 Windmill scripts have zero test coverage; schema/code drift (`portfolio_scores` table is missing from `schema.sql`; `board_members` is being written by a broken parser); Hard Rule 8 is only enforced for `gmail_smtp`, not for the 18 other Windmill resources; 53 `<YOUR_*>` + 3 `${OWNER_*}` placeholders are still in the docs; and — most critically — **three credentials are recoverable from `git log -p` against the public GitHub remote**.

The single most important finding is #1 (secrets in git history). Everything else is fixable on the current branch; that one needs `git filter-repo` + a force-push + credential rotation.

---

## CRITICAL — Address within 24 hours

### C1. Secrets still in git history on a public remote
> **2026-06-17 update:** This finding was based on the assumption that `windmill-automations` was a public repo. It was always private — no public exposure occurred. A1 and A2 are closed without action. The repo has since been migrated to `vps-stack` (fresh history, public). See `260616_audit_remediation_record.md`.

The `/root` repo is a clone of `github.com/straitsagent/windmill-automations.git` (assessed as public at audit time). The 2026-06-15 security cleanup removed secrets from the working tree but not from history. `git log -G` against `main` recovers three live credentials:

| Credential | First introduced | Last seen in | Removed in |
|---|---|---|---|
| Gmail SMTP app password | `7ca5680` (pre-cleanup) | `7ca5680` | `212e6bc` (cleanup) |
| Portfolio DB password | `c3c4848` (P0 build) | `2e4ac9d` (integration tests) | `212e6bc` |
| Windmill API token | `65d0b86` (session-bug prevention) | `694fcd2` (extended autopush) | `212e6bc` |

The credential values are not reproduced in this document; verify with `git log -p <commit>`.

**Action:**
1. **Rotate all three credentials** — assume they are compromised from the moment they appeared in the tree on a public repo. Even after `git filter-repo`, they are in GitHub's event horizon (forks, GitHub Archive, etc.).
2. **`git filter-repo` + force-push** to purge from `main`. Coordinate first — any open PRs will be invalidated.
3. **Document the new history-purge procedure** in `CLAUDE.md` so the next cleanup incident doesn't repeat the same mistake.

### C2. `portfolio_scores` table is not in `schema.sql`
- `schema.sql` defines 28 tables; the live DB has 29. The missing one — `portfolio_scores` (23 columns) — is referenced by `portfolio_rationalization.py:318, 320, 1031` and asserted by `agent/tests/test_windmill_scripts.py:1851`.
- The rationalization script and the test pass today only because the table happens to exist in the live DB outside version control.
- **Any fresh DB deployment will break the rationalization workflow and the corresponding test.** Add the `CREATE TABLE` to `schema.sql` (insert after `earnings_analyses` at line 186) and mirror the live schema exactly — including the `recommendation text` column which the production `INSERT` does not write but which exists in the DB.

### C3. `board_members` table is written by a broken parser
- 6 garbage rows in the live DB (`"Date and time:"`, `"Location:"`, `"Items of business:"`) confirm the known DEF 14A parser bug — also flagged in `CLAUDE.md:307` ("board of directors (DEF 14A, parser bug)").
- The table is declared in `schema.sql:218–226` but has **no working writer in the repo**. `grep` for `INSERT INTO board_members` returns zero matches in `/root/windmill/` and `/root/agent/`.
- **Action:** either remove the table from `schema.sql` until the parser is fixed, or fix the parser and add a real writer. Don't let it accumulate junk rows.

---

## HIGH — Address within 1 week

### H1. Hard Rule 8 (no resource destruction) is under-enforced
`hookify.block-gmail-smtp-delete.local.md` only blocks deletes for `gmail_smtp`. The other **18 Windmill resources/variables** (`finnhub_key`, `perplexity_key`, `xai_key`, `exa_key`, `telegram_bot_token`, `wm_token`, `serper_key`, `tavily_key`, `brave_key`, `fred_key`, `recipient_email`, `telegram_owner_id`, `gcp_sa_key`, `portfolio_db`, `rapidapi_key`, `deepseek_key`, `youtube_feeds`, `youtube_processed_state`) can be silently wiped.

Compounding the problem: `settings.json:31–32` explicitly allow-lists `Bash(wmill resource *)` and `Bash(wmill variable *)` — the full subcommand set, no restriction. A `wmill variable delete *` will pass both the permissions layer and the hookify layer.

**Action:** change the hookify pattern to `wmill\s+(resource|variable)\s+delete` (no resource name). Restrict permissions to `Bash(wmill resource list*)`, `Bash(wmill resource get *)`, `Bash(wmill resource create *)` (and analogous for `variable`). Have Claude's response when blocked be: "I need explicit confirmation to delete any Windmill resource. Confirm with the name of the resource."

### H2. Earnings Report Standard #5 has a hardcoded model name
`portfolio_earnings_analysis.py:911` writes "Grok-4.3" literally in the report footer. If Grok is down and the Deepseek fallback fires (which is the design — see `agent/tools.py` `_synthesise_with_fallback()`), the report **incorrectly advertises itself as Grok-4.3**. The `result` dict has `call1_model`/`call2_model` fields, but the footer does not use them.

**Action:** use `result.get("synthesiser_model", "Grok-4.3")` (or read it from the call's actual return path). Also affects the cost calculation downstream.

### H3. `portfolio_earnings_post_check.script.yaml` has an empty schema
Lines 5–9:

```yaml
schema:
  $schema: https://json-schema.org/draft/2020-12/schema
  type: object
  properties: {}
  required: []
```

The script's `main()` accepts 4 params (`portfolio_db`, `finnhub_key`, `wm_token`, plus the earnings date) but the schema declares nothing. This is deployment drift from a missing `wmill script push` after a refactor. Re-push from `/root/windmill/`.

### H4. `portfolio_earnings_post_check` schedule is contradictory in 3 places
- File docstring (`portfolio_earnings_post_check.py:6`): "Morning post-earnings detector — runs at 9 AM SGT daily"
- `CLAUDE.md:341`: "9 AM SGT detector"
- `CLAUDE.md:341` schedule arg: `0 0 1 * * *` (00:00 on day 1 of every month — i.e. **monthly, not daily**)

Two of three are wrong. The `0 0 1 * * *` schedule would only fire once per month, which is wildly inconsistent with a "morning 9 AM daily" detector. Reconcile all three — the script and the in-CLAUDE.md description are most likely correct, the schedule arg in CLAUDE.md is the stale one.

### H5. Test coverage gap on 10 of 17 Windmill scripts (Hard Rule 15)
The 10 untested scripts include **7 of the highest-traffic daily ops**:

| Script | Schedule | Lines | Risk |
|---|---|---|---|
| `portfolio_email.py` | 2× daily | 460 | Highest — runs unattended twice a day, no test |
| `portfolio_move_monitor.py` | Hourly Mon–Fri | 261 | High — silent failure = missed move alert |
| `health_check.py` | Daily 7 AM SGT | 432 | High — if broken, system-wide blind |
| `morning_news_digest.py` | Daily 6:30 AM SGT | 514 | High — primary daily touchpoint |
| `portfolio_review.py` | Weekly Sat 8 AM SGT | 464 | Medium |
| `portfolio_price_fetcher.py` | 2× daily | 90 | Medium — bad data = cascading bad rationalization |
| `youtube_monitor.py` | Every 6h | 326 | Medium |
| `fundamentals_fetcher.py` | Weekly Sun 6 PM SGT | 291 | Medium |

The test file `agent/tests/test_windmill_scripts.py` is 1,941 lines focused on `research_tool`, `stock_data_fetcher`, the W2/W3 scripts, and `portfolio_rationalization`. The daily operational scripts are uncovered.

### H6. ~640 LOC of agent orchestration has zero tests
`main.py` (452 LOC, including the 193-line `handle_owner`), `state.py:polling_loop`, `windmill_client.py` (run_job, poll_job_result) — the **dispatch heart of the system** — has no direct unit tests. The `test_routing.py` only re-implements the regex patterns. Failure modes (Windmill 404 vs 500, missing files, draft_* intents misrouted from owner chat, message-splitting edge cases) are not exercised.

**Minimum to close the gap:** a mocked `clf.classify` test that drives `handle_owner` through each of the 5 tool classes and asserts on `db.write_audit` calls.

### H7. Silent failure + missing audit in FIRE branch
`main.py:220–236`: if `FIRE_EXECUTORS.get(intent)` returns `None`, the function silently returns — no Telegram reply, no audit row, no log. Violates Hard Rule 4 ("Log all errors — don't silently fail").

On exception (lines 224–226), the user sees the error but no `status="failed"` audit is written. Two 5-min fixes: add an `else` that sends a user-visible error and writes a `status="unregistered"` audit row; wrap the failure case in an audit-write.

### H8. Schema ↔ seed drift: `consolidation_group` never populated
`portfolio_positions.consolidation_group` was added to the schema for ADR pair consolidation, but `seed.sql` does not populate it for BABA/9988.HK or BIDU/9888.HK. `portfolio_rationalization.py:41–44` then hardcodes a separate `ADR_PAIRS` dict — the exact code/schema drift the column was meant to prevent.

**Action:** set `consolidation_group='Alibaba'` for the BABA and 9988.HK rows, `consolidation_group='Baidu'` for BIDU and 9888.HK, then replace the `ADR_PAIRS` dict with a `SELECT … WHERE consolidation_group IS NOT NULL` query.

---

## MEDIUM — Address within 1 month

### M1. Inconsistent `$var:` / `WM_BASE_URL` patterns
- `research_tool.py:1836–1845` defaults all 14 keys to `""` (no `$var:` defaults); relies entirely on `.script.yaml` to inject. If called as a Windmill job without the schema defaults (e.g. from `portfolio_earnings_analysis.py:340`), the keys will be `""` and the script will silently skip the relevant sources.
- 4 scripts hardcode `http://windmill_server:8000` with no env override: `portfolio_earnings_alert.py:20`, `portfolio_earnings_post_check.py:29`, `portfolio_earnings_analysis.py:50`, `research_tool.py:1649`. Two use `os.environ.get("WM_BASE_URL", ...)`: `health_check.py:13`, `youtube_monitor.py:28`.
- **Action:** pick one pattern (env-overridable `WM_BASE_URL` everywhere) and one `$var:` default style. Update all 6 scripts to match.

### M2. Schema health: missing CHECK constraints, indexes, updated_at

| File:Line | Column | Issue | Fix |
|---|---|---|---|
| `schema.sql:71` | `agent_draft_queue.status` | Bounded set, no CHECK | `CHECK IN ('pending','sent','rejected','expired')` |
| `schema.sql:80` | `agent_conversation_history.role` | Bounded set, no CHECK | `CHECK IN ('user','assistant','tool','system')` |
| `schema.sql:95` | `agent_pending_jobs.status` | Bounded set, no CHECK | `CHECK IN ('running','completed','failed')` |
| `schema.sql:109` | `agent_pending_confirmations.status` | Bounded set, no CHECK | `CHECK IN ('pending','confirmed','cancelled','expired')` |
| `schema.sql:120` | `agent_audit_log.intent_detected` | Bounded set, no CHECK | ENUM or CHECK |
| `schema.sql:129` | `agent_audit_log.status` | Bounded set, no CHECK | `CHECK IN ('ok','error','dispatched','cached')` |
| `schema.sql:170–184` | `earnings_analyses` | No UNIQUE on `(ticker, analysis_type, earnings_date)` | Add UNIQUE — fixes a TOCTOU race in `portfolio_earnings_post_check.py:55–58` |
| `schema.sql:116–132` | `agent_audit_log` | No secondary index (117 rows / 88 KB and growing) | Add `(created_at DESC)` and `(wa_phone, created_at DESC)` |
| `schema.sql:55–64` | `agent_contact_rules.display_name` | `db.py:269` does `lower(display_name) LIKE lower(%s)` — full scan | Add `text_pattern_ops` functional index or `pg_trgm` GIN index |
| `schema.sql:55,66,89,104,134` | 5 tables | Missing `updated_at` despite being mutable | Add `updated_at TIMESTAMPTZ` |
| `schema.sql:8,17,27,49` | First 4 tables | Use `TIMESTAMP` (no TZ) — rest uses `TIMESTAMPTZ` | Standardize on `TIMESTAMPTZ` |

### M3. 7 of 13 scheduled workflows have no `.schedule.yaml` in git
`CLAUDE.md` claims 13 scheduled workflows. Only 6 have `.schedule.yaml` files in git: `morning_news_digest`, `youtube_monitor`, `portfolio_review`, plus 2× `portfolio_move_monitor` (HK and US), and `portfolio_earnings_post_check`. The other 7 are scheduled in the Windmill UI — **outside git, invisible to `wmill sync pull`, and at risk of being wiped on any future sync-push (Hard Rule 9)**.

The missing schedules:
- `portfolio_price_fetcher` (5:45 AM + 5:45 PM SGT)
- `portfolio_email` (6 AM + 6 PM SGT)
- `fundamentals_fetcher` (Sun 6 PM SGT)
- `portfolio_rationalization_monthly` (1st of month 9 PM SGT)
- `health_check` (7 AM SGT daily)
- `portfolio_earnings_alert` (9 PM SGT Mon–Fri)
- `portfolio_analyst_alert` (7:45 AM SGT daily)

**Action:** add `.schedule.yaml` for each, or remove the claim from CLAUDE.md if these run ad-hoc. The drift here is dangerous because schedule changes happen in the Windmill UI but aren't tracked in git.

### M4. `print()` everywhere, `logging` nowhere
- 266 `print()` statements across 15 Windmill scripts
- 13 `print()` statements in agent code (one of which leaks the chat_id to stdout at `main.py:70`)
- Windmill's job log viewer can't filter by level; harder to spot errors vs info
- Top offenders: `research_tool.py` (97), `portfolio_earnings_analysis.py` (31), `stock_data_fetcher.py` (30), `youtube_monitor.py` (19), `portfolio_rationalization.py` (14)

**Action:** replace all with `import logging; log = logging.getLogger(__name__)` + `log.info(...)` etc. One PR, low risk.

### M5. Silent exception swallowing
- 24 `pass` statements in `except` blocks across 5 files
- 28 of 138 `except Exception` clauses use bare `print(...)` and continue
- Violates Hard Rule 4 at scale

Notable: `email_summary.py:47, 56, 63`; `research_tool.py:187, 465, 602, 1185, 1671, 1894`; `stock_data_fetcher.py:129, 403, 536, 810, 827, 859, 875, 898`.

**Action:** at minimum, `log.exception(...)` and continue; or re-raise. The autopush hook already prints a TDD reminder — adding a "no silent except" reminder to the same hook would catch this at deploy time.

### M6. Long `main()` functions
| File | Function | Lines | Recommendation |
|---|---|---|---|
| `portfolio_review.py` | `main` | 438 | Split into `_load_…`, `_compute_…`, `_build_html`, `_send_email` |
| `portfolio_email.py` | `main` | 402 | Same pattern — matches the helper style already in `research_tool.py` |
| `portfolio_rationalization.py` | `main` | 357 | Same pattern |
| `agent/main.py` | `handle_owner` | 193 | Split into 5 per-class dispatchers: `_handle_structured_research`, `_handle_gated_write`, `_handle_async_notify`, `_handle_fire`, `_handle_multi_step`, `_handle_fast` |

All four mix dispatch, computation, rendering, and I/O. Splitting makes them unit-testable — and is a prerequisite for H6 (agent orchestration tests).

### M7. CLAUDE.md is 33 KB / 398 lines — too large
- "Telegram Agent Build Status" (40 lines, 304–343) duplicates ROADMAP.md and WORKFLOW_ARCHITECTURE.md
- "Windmill Variables Added" (lines 252–272) duplicates script.yaml defaults and `agent/tools.py:34–48`
- "Earnings Report Standards" (lines 200–216) is workflow-specific, not session context
- "Current Status" alone is 33% of the file

**Action:** trim to ~250 lines by moving status tables to ROADMAP.md and the Earnings Report Standards to a separate design doc.

### M8. `portfolio_rationalization` is the only Live Windmill script without a section in `WORKFLOW_ARCHITECTURE.md`
It has its own 482-line `portfolio_rationalization_framework.md`, but the per-workflow pseudocode spec is incomplete. WORKFLOW_ARCHITECTURE.md is the canonical spec Claude Code reads before building or modifying any workflow — even a 30-line stub linking to the framework would close the gap.

### M9. README is out of date
- `README.md:38–39` references `docs/INSTRUCTIONS.md` and `docs/progress.md` — **neither file exists** (dead links)
- No mention of `WORKFLOW_ARCHITECTURE.md`, the `portfolio_*_framework.md` design docs, the audit folder, or the Telegram agent
- README is **out of date as a navigation aid** — the project is much larger than the README implies

### M10. Unused imports (dead code)
| File:Line | Item |
|---|---|
| `db.py:3` | `from datetime import datetime, timezone` (both unused) |
| `windmill_client.py:2` | `import json` |
| `tools.py:9` | `import time` |
| `tools.py:11` | `from typing import Any, Optional` — only `Optional` used |
| `tests/conftest.py:5` | `import psycopg2.extras` |
| `tools.py:251, 280, 454, 502` | 4 in-function re-imports (`glob`, `httpx`, `glob as _glob`, `date as _date`) — all already imported at module top |
| `error_alert.py:4`, `portfolio_analyst_alert.py:6`, `portfolio_earnings_analysis.py:23`, `portfolio_move_monitor.py:14`, `portfolio_rationalization.py:15,18`, `portfolio_review.py:17`, `stock_data_fetcher.py:21` | Various unused names in Windmill scripts |

---

## LOW — Hygiene and polish

### L1. Placeholders still in docs (security cleanup was incomplete)
- 3 `${OWNER_*}` in `README.md:3`, `CLAUDE.md:5`, `ROADMAP.md:4`
- 53 `<YOUR_*>` across 9 docs:
  - 17 in `CLAUDE.md` (lines 12, 48, 55, 96, 98, 127–128, 215, 221, 233, 246, 247, 249, 309–311, 358)
  - 22 in `WORKFLOW_ARCHITECTURE.md` (lines 29, 126, 239, 383, 387, 476, 513, 766, 1057, 1187, 1248, 1566, 1924, 1927, 2071, 2075–2076, 2243, 2261, 2264, 2269, 2387)
  - 5 in `ROADMAP.md` (lines 35, 43, 71–72, 93, 134)
  - 2 in `README.md` (lines 4–5)
  - 1 each in `portfolio_rationalization_framework.md:402`, `portfolio_candidate_eval_framework.md:326`, `portfolio_analysis_agent_spec.md:64, 458`, `260612_research_agent_audit.md:37`, `260610_vps_resource_audit.md:3`
- The first-name leak in `WORKFLOW_ARCHITECTURE.md:2387` — the doc still says "Telegram to **<redacted-first-name>** + email to `<YOUR_RECIPIENT_EMAIL>`" — directly contradicts the 2026-06-15 security cleanup claim. Also at `WORKFLOW_ARCHITECTURE.md:3` in the "security cleanup" preamble.

### L2. `morning_news_digest.script.yaml` says "5-section" but the code is 4-section
- `morning_news_digest.script.yaml:3`: "(1) RSS headlines, (2) Google News keyword alerts, (3) AI summaries of key newsletters, (4) additional newsletter headlines not in RSS, (5) all other inbox items."
- `morning_news_digest.py:350, 360, 370, 389`: `section_header(1, "Key Headlines")`, `section_header(2, "Google News Alerts")`, `section_header(3, "Newsletter Summaries")`, `section_header(4, "Other Inbox Items")` — 4 sections.
- `WORKFLOW_ARCHITECTURE.md:40–91`: 4 sections — matches the code.
- The script.yaml description is wrong; the architecture doc is correct.

### L3. Doc freshness — older audit docs
- `260609_codebase_audit_report.md` is itself a 7-day-old audit that pre-dates W2/W3/W4 and the 15-rule Hard Rules list — should be marked as "Superseded by 260616_full_codebase_audit.md".
- `260610_vps_resource_audit.md` is a runtime snapshot (CPU/RAM) from a week ago — may be stale but easy to refresh.
- `software_inventory.md` is 7 days old; versions may have drifted.

### L4. Container runs as root + tests baked into image
- `docker exec root-straitsagent-1 id` returns `uid=0(root)`. `Dockerfile` has no `USER` directive.
- No `.dockerignore` — the 9 test files (~190 KB) are in the production image. Add `tests/`, `__pycache__/`, `*.pyc`, `.pytest_cache/`, `Dockerfile`.

### L5. `.env` and `agent.env` are world-readable (644)
Live production secrets, safe today only because the system has one user. `chmod 600 /root/.env /root/agent.env` is a 1-second defense-in-depth fix. Also `/opt/n8n/stack.env` is 644 and contains the `N8N_ENCRYPTION_KEY` (line 9).

### L6. `PostToolUse` hook has no `matcher`
Fires Python startup + `.env` parse + JSON parse on every Read/Grep/Glob/Bash. Restrict to `Write|Edit|MultiEdit` in `settings.json:47–57`. The script exits early for non-Edit tools, but the JSON parsing + Python startup runs on every single call.

### L7. Broad permissions in `settings.json`
| Pattern | Risk |
|---|---|
| `Bash(wmill resource *)` | **HIGH** — allows `wmill resource delete *` (see H1) |
| `Bash(wmill variable *)` | **HIGH** — allows `wmill variable delete *` (see H1) |
| `Bash(gcloud iam *)` | HIGH — IAM policy edits, service-account impersonation |
| `Bash(gcloud auth *)` | HIGH — can re-authenticate as a different identity |
| `Bash(git add *)` | HIGH — single typo in `.gitignore` exposes all secrets |
| `Bash(docker exec *)` | MEDIUM — exec into any container, including `dind` (Docker-in-Docker root) |
| `Bash(npm install *)` | MEDIUM — supply-chain risk |
| `Read(//etc/**)` in `settings.local.json:7` | MEDIUM — `/etc/passwd`, `/etc/shadow`, SSH keys |

### L8. Hardcoded password in `settings.local.json:87`
`Bash(PGPASSWORD='<redacted-supabase-pw>' psql *)` — a Supabase password from `shared/keys.md` is inlined in a permission allowlist. The file is gitignored, so it does not leak through git, but the principle of "no hardcoded keys" (Hard Rule 1) is violated in the very file that defines Hard Rule enforcement. Verify the actual value via `git grep -n PGPASSWORD .claude/settings.local.json` (file is local-only).

### L9. Windmill worker runs `privileged: true` + plaintext dind API
`docker-compose.yml:55–69, 84, 93, 109`: `DOCKER_TLS_CERTDIR: ""` (no TLS on dind API), `DOCKER_HOST=tcp://dind:2375` (plaintext), `privileged: true` on the worker. Any Windmill script can `docker run` arbitrary containers inside the `dind` daemon. Large blast radius for a script bug or compromise.

### L10. No firewall
UFW inactive — all ports open. The n8n Caddy binds `0.0.0.0:80, 443, [::]:80, [::]:443`. Combined with L7, the VPS is wide open.

### L11. Other minor items
- 11 of 17 Windmill scripts have no docstring on `main()`; 11 of 17 have no module-level docstring
- `verify_signature(raw_body, secret_header)` in `telegram.py:11` — the `raw_body` parameter is dead; function name is misleading (it does not cryptographically verify the body)
- 12 of 13 `.script.lock` files are 0 bytes
- `gcp_sa_key` listed in `CLAUDE.md:259` as "created but not currently used" — orphaned reference, can be deleted from docs
- `send_batch_reports.py` has hardcoded date `2026-06-13` in 4 places (lines 44, 53, 57, 76) — one-shot script that has outlived its purpose
- `db` (Windmill PG) `POSTGRES_PASSWORD: changeme` hardcoded in `docker-compose.yml:23` — should be `${WM_DB_PASSWORD}` from `.env`

---

## What's Working Well

- **272 tests pass in 22s** in the agent container; test count is consistent across `CLAUDE.md`, `ROADMAP.md`, and `pytest --co`
- **Strong schema-safety net**: `test_schema.py` validates every column name in `tools.py` and `db.py` against the live DB — has already caught regressions (comments in `test_tools.py:38–40` confirm prior `source_count` and `analyst_target_usd` bugs were caught here)
- **Tool-class consistency tests** (`test_all_fast_tool_classes_have_executors` and friends in `test_tools.py:178–193`) guarantee no orphan intents in the registry
- **All SQL is fully parameterized** — zero SQL injection risk across `db.py`, `tools.py`, and tests
- **No hardcoded secrets in any production .py file** — verified across 17 Windmill scripts and 13 agent modules
- **Telegram Markdown fallback** in `telegram._send_single:63–68` gracefully retries on 400 (good UX for LLM-generated responses)
- **Polling loop is properly bounded** with `try/except` wrapping the body in `state.py:77`
- **Structured research shortcut** (`/stockresearch`, `/research`, `/deepresearch`) bypasses the classifier for low-latency gated entry — well-designed
- **Superseded doc** (`docs/portfolio_analysis_agent_spec.md`) is properly archived and cross-referenced
- **`.gitignore` covers all secret files** in the working tree (verified via `git check-ignore -v`)
- **Webhook auth** uses Telegram's secret-token header (`X-Telegram-Bot-Api-Secret-Token`)
- **Tooling is rich** — 21 tools across 5 latency classes (FAST, FIRE, GATED_WRITE, ASYNC_NOTIFY, MULTI_STEP); 28 intents; 13 registered Telegram slash commands

---

## Recommended Remediation Order

### Phase A — next 24 hours (fix the leak)
1. **Rotate the 3 exposed credentials** (Gmail SMTP, Portfolio DB, Windmill API) — assume compromised
2. **`git filter-repo` + force-push** to purge from history
3. `chmod 600 /root/.env /root/agent.env /opt/n8n/stack.env`
4. Re-push `portfolio_earnings_post_check.py` to fix the empty schema (H3)

### Phase B — next week (close the high-risk gaps)
5. Generalize the Hard Rule 8 hookify to all `wmill resource/variable delete` (H1)
6. Add `portfolio_scores` to `schema.sql`; remove or fix `board_members` (C2, C3)
7. Fix the model-name hardcoding in `portfolio_earnings_analysis.py:911` (H2)
8. Reconcile the 3 contradictory `portfolio_earnings_post_check` schedules (H4)
9. Split `handle_owner` (193 lines) into per-class dispatchers (M6)
10. Add tests for `main.py` (mock `clf.classify` per intent class) — closes the biggest Hard Rule 15 gap (H6)
11. Add `.dockerignore` and non-root `USER` to the agent Dockerfile (L4)
12. Fix the FIRE-branch silent failure + missing audit (H7)

### Phase C — next month (code health and docs)
13. Add tests for the 10 untested Windmill scripts (H5) — prioritize `portfolio_email`, `portfolio_move_monitor`, `health_check`
14. Replace `print()` with `logging` across both Windmill and agent code (M4)
15. Stop silently swallowing exceptions — `log.exception` everywhere (M5)
16. Split the 4 oversized `main()` functions (M6)
17. Add `.schedule.yaml` for the 7 scheduled workflows that lack one in git (M3)
18. Add CHECK constraints, secondary indexes, and `updated_at` per M2
19. Trim CLAUDE.md to <300 lines; move status tables to ROADMAP.md (M7)
20. Add `portfolio_rationalization` section to WORKFLOW_ARCHITECTURE.md (M8)
21. Update README.md — remove dead links, add agent section (M9)
22. Standardize `$var:` defaults and `WM_BASE_URL` across all 6 Windmill scripts (M1)
23. Remove unused imports (M10)
24. Populate `consolidation_group` in seed.sql and remove the `ADR_PAIRS` dict (H8)

### Phase D — defense in depth
25. Add `permissions.deny` block mirroring hookify blocks
26. Restrict broad `Bash(wmill resource *)`, `Bash(wmill variable *)`, `Bash(gcloud iam *)`, `Bash(git add *)` patterns (L7)
27. Add `matcher: "Write|Edit|MultiEdit"` to the `PostToolUse` hook (L6)
28. Enable UFW — allow 22, 80, 443 (L10)
29. Pin Docker images to digests
30. Sweep 53 `<YOUR_*>` + 3 `${OWNER_*}` placeholders + the first-name leak in WORKFLOW_ARCHITECTURE.md:2387 (L1)
31. Fix `morning_news_digest.script.yaml` "5-section" → "4-section" (L2)
32. Mark `260609_codebase_audit_report.md` as historical (L3)

---

## Appendix A — File Inventory

### Windmill scripts (`/root/windmill/u/admin/`)
17 Python files, 8,948 LOC total. Line counts and test coverage:

| Script | Lines | Has tests? | Schedule in git? |
|---|---|---|---|
| `email_summary.py` | 167 | No | No |
| `error_alert.py` | 44 | No | No |
| `fundamentals_fetcher.py` | 291 | No | No |
| `health_check.py` | 432 | No | No |
| `morning_news_digest.py` | 514 | No | Yes |
| `portfolio_analyst_alert.py` | 138 | Yes (3) | No |
| `portfolio_earnings_alert.py` | 129 | Yes (4) | No |
| `portfolio_earnings_analysis.py` | 964 | Yes (4) | No |
| `portfolio_earnings_post_check.py` | 122 | Yes (1) | No |
| `portfolio_email.py` | 460 | No | No |
| `portfolio_move_monitor.py` | 261 | No | Yes (×2) |
| `portfolio_price_fetcher.py` | 90 | No | No |
| `portfolio_rationalization.py` | 1,098 | Yes (12) | No |
| `portfolio_review.py` | 464 | No | Yes |
| `research_tool.py` | 2,484 | Yes (~70) | No |
| `stock_data_fetcher.py` | 964 | Yes (10) | No |
| `youtube_monitor.py` | 326 | No | Yes |

### Telegram agent (`/root/agent/`)
13 modules, 1,996 LOC source + 272 tests across 9 test files.

| Module | Lines | Has direct tests? |
|---|---|---|
| `main.py` | 452 | No (test_routing.py only re-implements regex) |
| `classifier.py` | 105 | Yes (13) |
| `tools.py` | 754 | Yes (55 unit + 8 integration) |
| `db.py` | 306 | Yes (16) |
| `telegram.py` | 98 | Yes (13) |
| `planner.py` | 93 | Yes (6) |
| `state.py` | 83 | No |
| `windmill_client.py` | 52 | No |
| `formatter.py` | 22 | No |
| `config.py` | 31 | No |
| `tests/` (9 files) | 3,000+ | n/a |
| `Dockerfile` | 11 | n/a |
| `requirements.txt` | 7 | n/a |

### PostgreSQL (`/root/portfolio/`)
- `schema.sql` — 396 lines, 28 tables defined
- `seed.sql` — 38 lines, 33 positions seeded
- Live DB has 29 tables (one extra: `portfolio_scores`)

### Documentation
- `README.md` — 58 lines (out of date)
- `CLAUDE.md` — 398 lines (too large)
- `docs/ROADMAP.md` — 302 lines
- `docs/WORKFLOW_ARCHITECTURE.md` — 2,442 lines
- `docs/portfolio_rationalization_framework.md` — 482 lines
- `docs/portfolio_candidate_eval_framework.md` — 339 lines
- `docs/portfolio_analysis_agent_spec.md` — 621 lines (superseded)
- `docs/software_inventory.md` — 42 lines
- `docs/audit/260605_fundamentals_api_audit.md` — 348 lines
- `docs/audit/260605_api_endpoint_full_audit.md` — 629 lines
- `docs/audit/260609_codebase_audit_report.md` — 59 lines (stale, pre-W2/W3/W4)
- `docs/audit/260610_vps_resource_audit.md` — 188 lines (runtime snapshot)
- `docs/audit/260612_search_api_audit.md` — 436 lines
- `docs/audit/260612_research_agent_audit.md` — 724 lines

### Infra & config
- `docker-compose.yml` — 280 lines, 10 services
- `/opt/n8n/docker-compose.yml` — 24 lines
- `Caddyfile` (root) — 25 lines
- `/opt/n8n/Caddyfile` — 14 lines
- `.claude/settings.json` — 66 lines
- `.claude/settings.local.json` — 150 lines (gitignored)
- `.claude/hookify.*.local.md` — 2 files
- `scripts/` — 5 helper scripts
- `shared/` — keys.md (chmod 600), windmill-sa-key.json (chmod 600), override_log.md

---

## Appendix B — Quick Reference: Top 10 Action Items

| # | Action | File:Line | Why |
|---|---|---|---|
| 1 | Rotate 3 credentials + `git filter-repo` | git history | C1 |
| 2 | Add `portfolio_scores` CREATE TABLE | `schema.sql:186` (insert after) | C2 |
| 3 | Remove or fix `board_members` | `schema.sql:218–226` | C3 |
| 4 | Generalize Hard Rule 8 hookify | `hookify.block-gmail-smtp-delete.local.md` | H1 |
| 5 | Fix model name in earnings report footer | `portfolio_earnings_analysis.py:911` | H2 |
| 6 | Re-push post-check script | `portfolio_earnings_post_check.py` | H3 |
| 7 | Reconcile 3 post-check schedules | `CLAUDE.md:341`, `portfolio_earnings_post_check.py:6` | H4 |
| 8 | Add tests for `main.py` | `agent/main.py:98–290` | H6 |
| 9 | Fix FIRE-branch silent failure | `agent/main.py:220–236` | H7 |
| 10 | Populate `consolidation_group` in seed | `seed.sql:8, 27, 10, 32` | H8 |

---

**End of audit report.** No files were modified during the audit. All findings are derived from read-only inspection of the working tree as of 2026-06-16.
