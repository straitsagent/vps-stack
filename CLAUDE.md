# CLAUDE.md — VPS Project Context

## Who You Are Working With

${OWNER_NAME}. ${OWNER_TITLE}, ${OWNER_EMPLOYER}. ${OWNER_BACKGROUND}. Building a personal automation stack on this VPS for productivity and intelligence delivery.

---

## VPS Environment

- **OS:** Ubuntu 24.04, Contabo VPS
- **IP:** <YOUR_VPS_IP>
- **You are always logged in as root** unless otherwise stated
- **Docker:** running, IPv6 disabled (`/etc/docker/daemon.json` — `{"ipv6": false}`)
- **Firewall:** UFW inactive — all ports open by default

### Persistent SSH Sessions (tmux)

SSH sessions on this VPS are kept alive via a persistent tmux session that survives disconnects and restarts automatically on boot.

| Component | Location | Notes |
|---|---|---|
| tmux config | `~/.tmux.conf` | Ctrl+A prefix, mouse on, 10k scrollback, status bar, `|`/`-` splits |
| Attach script | `~/scripts/start-claude-remote.sh` | Attaches if session exists, creates fresh if not |
| systemd service | `~/.config/systemd/user/claude-remote.service` | Enabled, starts `claude-remote` session on boot with Restart=on-failure |
| Shell alias | `cr` in `~/.bashrc` | Shorthand: attach to `claude-remote` or create it |

**Key commands:**

```bash
cr                            # attach to claude-remote session (or create it)
tmux ls                       # list all sessions
Ctrl+A d                      # detach cleanly — session stays alive
Ctrl+A |                      # split pane vertically
Ctrl+A -                      # split pane horizontally
```

After any SSH login, run `cr` to re-enter the persistent session.

### Running Services

| Service | Container(s) | Port | Notes |
|---|---|---|---|
| Windmill | `root-windmill_server-1` etc | 8080 | Compose at `/root/docker-compose.yml`. Primary orchestration platform. |
| n8n | `n8n-n8n-1`, `n8n-caddy-1` | 80/443 | Compose at `/opt/n8n/docker-compose.yml`. Kept running but not actively used. Do not build new workflows here. |
| PostgreSQL | `root-portfolio_postgres-1` | 5432 | Portfolio Intelligence System — live in `/root/docker-compose.yml` as `portfolio_postgres` service, volume `portfolio_db_data`. Stores `price_history`, `portfolio_positions`, `fx_rates`. Internal only — not exposed externally. |
| Telegram Agent | `root-straitsagent-1` | 8001 (internal) | FastAPI agent service at `/root/agent/`. Joined to `agent_net` + `default` networks. Receives Telegram webhooks via Caddy. Silent groups (env `SILENT_GROUPS`) — bot only responds to `/`-commands or `@StraitsAgentBot` mentions in listed groups; casual messages ignored. |
| Caddy | `n8n-caddy-1` | 80/443 | Reverse-proxies `https://<YOUR_DOMAIN>` — routes `/webhook/telegram*` → `straitsagent:8001`, everything else → `n8n:5678`. Config at `/opt/n8n/Caddyfile`. |

---

## Architecture Principles

- **Windmill is the only orchestration platform.** All workflows are written and scheduled in Windmill.
- **Email is the delivery layer.** All workflow outputs go to Gmail. No dashboards to maintain. Default recipient for all workflow emails: `<YOUR_RECIPIENT_EMAIL>` unless otherwise specified.
- **Google Sheets is the control layer for simple workflows.** Use Sheets for configuration, watchlists, and toggles. For data-intensive systems (e.g. price history, portfolio positions), use PostgreSQL on the VPS.
- **PostgreSQL is the data layer for the Portfolio Intelligence System.** Windmill scripts connect to it as an internal service — not exposed externally.
- **Claude Code writes all scripts.** Scripts live in Windmill's script editor (Python or TypeScript). No manual coding.
- **Keep it simple.** Each workflow should be buildable in a single Claude Code session and run unattended.
- **Test the artifact the human receives.** A test earns its place only if its failure means the human gets a broken or missing artifact. The authoritative test renders the actual email HTML + Telegram message from one real `main()` run (I/O faked only at the edges) and asserts every user-visible field appears in both. Logs, `success: True`, and subject lines are not verification. See `docs/TESTING.md`.
- **Telegram notifications use the markdown-driven formatter architecture.** Each main script writes a canonical `.md` file (JSON front-matter block + ≥500-word LLM narrative + `<!-- DETAIL -->` separator). A dedicated `<name>_telegram.py` formatter script reads that `.md` and builds the self-contained ≥500-word Telegram message. The 8 formatters are: `macro_daily_push_telegram`, `portfolio_email_telegram`, `portfolio_review_telegram`, `portfolio_rationalization_telegram`, `portfolio_move_monitor_telegram`, `portfolio_analyst_alert_telegram`, `health_check_telegram`, `youtube_monitor_telegram`. Every Telegram send is logged to `telegram_outbox` (Postgres) and to the formatter job logs (`[Telegram] Sending ...`).

---

## Key Paths

| Path | Purpose |
|---|---|
| `/root/docker-compose.yml` | Windmill compose file |
| `/root/windmill/u/admin/` | Windmill scripts — git source of truth |
| `/root/shared/` | Shared configs and credentials |
| `/root/shared/keys.md` | All API keys (chmod 600 — **never commit**) |
| `/root/shared/windmill-sa-key.json` | GCP service account JSON for Sheets/Drive (**never commit**) |
| `/root/shared/override_log.md` | Manual intervention log |
| `/root/docs/ROADMAP.md` | Full workflow roadmap and build status |
| `/root/docs/TESTING.md` | Artifact-driven testing philosophy, test hierarchy, harness pattern, live verify procedure |
| `/root/docs/WORKFLOW_ARCHITECTURE.md` | Per-workflow architecture specs in pseudocode |
| `/root/portfolio/` | Portfolio Intelligence System — DB schema and seed data. Postgres runs in `/root/docker-compose.yml`. |
| `/root/portfolio/schema.sql` | DB schema for `price_history`, `portfolio_positions`, `fx_rates` |
| `/root/portfolio/seed.sql` | Seed data — 33 portfolio positions |
| `/root/agent/` | Telegram agent service — FastAPI, Docker service `straitsagent` |
| `/root/agent.env` | Agent env vars (gitignored) — Telegram token, owner chat_id, DB URL, API keys |
| `/root/agent.env.example` | Env template (committed) |
| `/root/agent/tests/` | pytest unit tests — run `python -m pytest tests/ -v` before every build |
| `/root/scripts/windmill-autopush.py` | PostToolUse hook — auto-pushes edited `.py` files in `windmill/u/admin/` to Windmill after syntax check |
| `/root/.claude/settings.json` | Claude Code global settings — hooks + permissions |
| `/root/.claude/hookify.block-*.local.md` | Hookify block rules — enforces Hard Rules 8 + 9 at tool layer |

---

## Credentials & API Keys

All API keys are stored in three places:

1. **Server:** `/root/shared/keys.md` (chmod 600). Read directly — no auth needed. Contains all keys synced from Drive on 2026-06-03.
2. **Google Drive — Keys spreadsheet:** Access via Drive MCP — run `/mcp` in Claude Code and select "claude.ai Google Drive", then search for file titled `Keys`.
3. **Google Drive — keys.md backup:** Plain-text backup uploaded 2026-06-03. Search Drive for `keys.md` to restore. Includes Gmail app password which is not in the Keys spreadsheet.

**GCP Service Account:** `<YOUR_GCP_SA>`
- Key at `/root/shared/windmill-sa-key.json`
- Project: `<YOUR_GCP_PROJECT>` (n8n-workflows)
- APIs enabled: Google Drive, Google Sheets

**gcloud:** Authenticated as straitsagent@gmail.com. Verify with `gcloud auth print-access-token`.

---

## Script Workflow (GitOps)

Scripts are written as local files and pushed to Windmill — git is the source of truth.

1. **Pre-flight:** List every `$res:` and `$var:` reference the script will use. Verify each exists in Windmill before writing a line of code. Missing resources cause silent runtime failures.
2. Write the script as `windmill/u/admin/<name>.py`
3. Write metadata as `windmill/u/admin/<name>.script.yaml`
4. Push to Windmill: `cd /root/windmill && wmill script push u/admin/<name>.py`
5. Test in Windmill UI, then commit to git

**Git working directory:** Always run git commands from `/root`. Never `cd` into a subdirectory (e.g. `/root/windmill`) for git operations — git will operate against the subdirectory, not the repo root, causing confusion and wrong-directory commits.

**Always use `wmill script push <path>` for individual script changes.** Do NOT use `wmill sync push` for routine updates — it has wiped Windmill resources and variables (`gmail_smtp`, `deepseek_key`) and deployed stale archived versions on multiple occasions (2026-06-03). Only use `wmill sync push` if explicitly needed for a bulk workspace sync.

**Schedule YAML changes require an explicit API push — they are NOT auto-synced.** The PostToolUse autopush hook only fires on `.py` file edits, not `.schedule.yaml` files. After editing a schedule YAML, push the updated args to Windmill via REST API:
```bash
WM_TOKEN=$(grep "WM_TOKEN" /root/agent.env | cut -d= -f2 | tr -d ' ')
curl -s -X POST "http://localhost:8080/api/w/admins/schedules/update/u%2Fadmin%2F<schedule_path>" \
  -H "Authorization: Bearer $WM_TOKEN" -H "Content-Type: application/json" \
  -d '<full_args_json>'
# To create a new schedule (not update): use /schedules/create with "path" in the body
```

To pull any changes made in the UI back to disk:
```
cd /root/windmill && wmill sync pull --yes
```

To restore Windmill credentials if wiped (see `/root/shared/keys.md` for values):
```bash
# Recreate gmail_smtp resource
curl -s -X POST "http://<YOUR_VPS_IP>:8080/api/w/admins/resources/create" \
  -H "Authorization: Bearer <YOUR_WINDMILL_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"path":"u/admin/gmail_smtp","resource_type":"smtp","value":{"host":"smtp.gmail.com","port":587,"username":"straitsagent@gmail.com","password":"<Gmail App Password from keys.md>","tls_implicit":false}}'

# Recreate deepseek_key variable
cd /root/windmill && wmill variable add "<Deepseek key from keys.md>" u/admin/deepseek_key --plain-secrets
```

---

## Claude Code Configuration

Claude Code is configured with hooks and permissions that enforce the Hard Rules at the tool layer — not just as prose instructions.

### Hooks (active now, no restart needed)

**SessionStart — auto-handle outstanding git work** (`~/.claude/settings.json`)
- Runs `python3 /root/scripts/session-git-check.py` at the start of every session
- Checks for uncommitted tracked-file changes and unpushed commits from the previous session
- If outstanding work exists, injects an instruction into session context telling Claude to update docs, commit, and push **before responding to the first user message** — no manual prompting needed
- Designed for SSH/tmux workflows where sessions are killed rather than cleanly exited
- Also fires a standing briefing instruction every session: reads CLAUDE.md and ROADMAP.md and opens with a brief status update (what's live, what's next, outstanding items) before responding to the first user message

**PostToolUse — auto-push Windmill scripts** (`~/.claude/settings.json`)
- After any Write or Edit tool call on a `.py` file under `/root/windmill/u/admin/`, runs `python3 /root/scripts/windmill-autopush.py`
- Script syntax-checks with `python3 -m py_compile` first — will not push broken code
- **Resource/variable preflight:** scans the file for `$res:` and `$var:` references, checks each against the Windmill API, and emits `⚠️ Missing Windmill resource/variable` warnings in the system message if any are absent — so missing credentials are caught at deploy time, not at runtime
- Runs `wmill script push <rel_path>` from `/root/windmill/` and surfaces a `[autopush]` message
- Enforces the GitOps workflow automatically — saving a script file IS the deployment

**Custom skills** (`~/.claude/commands/`)
- `/deploy-windmill` — full Windmill deployment checklist: resource preflight → design approval gate (for existing scripts) → push → live test with output inspection → docs + git commit
- `/digest` — digest-specific build checklist: confirm current live state → design approval → resource preflight → implement with recency date validation → live test with article date inspection → git commit

**Hookify block rules** (`~/.claude/hookify.*.local.md`)
- `hookify.block-wmill-sync-push.local.md` — **blocks** any Bash call matching `wmill sync push` (Hard Rule 9)
- `hookify.block-gmail-smtp-delete.local.md` — **blocks** any Bash call matching `wmill resource/variable delete ... gmail_smtp` (Hard Rule 8)
- Both return a descriptive error message explaining why and what to use instead

### Permissions (`~/.claude/settings.json`)

Broad `wmill sync *` pre-approval removed — replaced with specific `wmill sync pull --yes` only. This closes the gap where `wmill sync push` could be submitted silently without a confirmation prompt (the hookify block is still the primary enforcement layer; removing the pre-approval is defense-in-depth).

---

## Hard Rules

1. Never hardcode API keys — use Windmill's resource/secret system
2. All new automation goes through Windmill only — n8n is kept available but not actively developed
3. Test every script manually in Windmill before scheduling
4. Log all errors — don't silently fail
5. Never commit `shared/keys.md` or `shared/windmill-sa-key.json` to git
6. Always ask which API, model, or resource to use — never assume
7. **Before writing any code for a workflow, describe the full design in plain English / pseudocode and get explicit approval.** Cover: what it does step by step, what data it reads and writes, which APIs/resources it calls, and what the output email looks like. Only start coding after explicit confirmation.
8. **Never delete or overwrite existing Windmill resources** (especially `u/admin/gmail_smtp`) without explicit confirmation. When rewriting a workflow, only touch the script file — leave all resources/variables intact. `gmail_smtp` was accidentally deleted during a Morning Digest rewrite on 2026-06-03 and had to be manually recreated.
9. **Use `wmill script push <path>` for all script deployments.** Never use `wmill sync push` for routine changes — it has caused resource/variable deletion and stale-version deployments. Always run wmill commands from `/root/windmill/`.
10. **Always show the exact LLM prompt text and get explicit approval before coding it.** Domain-specific framing (e.g. "for an infra finance professional") can cause the model to silently skip content — keep prompts generic unless specifically requested.
11. **In Windmill schedule args, always use string format for resource/variable references.** Correct: `"$res:u/admin/portfolio_db"`, `"$var:u/admin/deepseek_key"`. Wrong: `{"$res": "u/admin/portfolio_db"}` (dict form — Windmill does not resolve this and the script receives an unresolved dict, causing KeyError at runtime).
12. **Before modifying any existing working workflow, describe the proposed change and get explicit approval.** Do not rebuild, restructure, or redesign a working script on your own judgment — this has caused regressions and a botched revert that wiped Windmill scripts. Rule 7 covers new workflows; this rule covers changes to existing ones.
13. **Google OAuth always requires a browser action — state this upfront before attempting any workaround.** gcloud auth, rclone, FIFO tricks, and service account flows all have this limitation in some form. If a task depends on browser-based auth and a browser is not available, say so immediately and propose an alternative rather than silently burning time on doomed workarounds.
14. **When fetching news or time-series data, always apply a recency date cutoff.** Never return articles older than 48 hours unless explicitly requested. Validate the actual date values of returned articles before declaring a news fetch successful — stale January articles have shipped through tests that only checked for non-empty results.
15. **Artifact-driven TDD is mandatory for ALL code. No exceptions. See `docs/TESTING.md` for the full philosophy.**
    - **The RED/GREEN target is the rendered artifact** — not source-code substrings or `success: True`. A test earns its place only if its failure means the human gets a broken or missing artifact.
    - **Every sending script must have** an `_render_<script>_artifacts(world)` harness that runs the real `main()` (I/O faked only at the edges) and returns `(email_html, md_content, telegram_message)`. Assert every user-visible field appears in **both** email and Telegram. The `test_<script>_email_and_telegram_agree` test is the single highest-authority correctness check.
    - **Write the ASD first.** Define `_<SCRIPT>_ASD` with the required strings as the spec. Build `_<SCRIPT>_WORLD` from the ASD (world references ASD, not the reverse). Call `_validate_world_vs_asd(world, asd)` at the top of every harness.
    - **Write artifact tests FIRST (RED).** Confirm they fail. Implement. Confirm GREEN. Live-verify (see Rule 17). Apply Testing Critic checklist (Rule 20) before committing.
    - **Tautology ban:** tests must use minimum-viable realistic inputs with distinct strings, never a pre-sized fixture passed into a size assertion. A test that feeds a 500-word fixture into `_build_message` and asserts ≥500 words proves nothing.
    - **Every harness must include `assert len(tg_msg.split()) >= 500`** to verify the world fixture drives sufficient Telegram content. A world fixture that produces <500 words is unrealistically small.
    - **Source-substring tests** (`assert "smtp" in src`) are the lowest-value tier — allowed only where no artifact path exists, and must have a comment explaining why. Never use them to verify rendered content.
    - **Round-trip contract tests** use the real `_build_md_content` (not a test-local copy) so the formatter is tested against exactly what `main()` writes.
    - The PostToolUse hook prints a TDD reminder after every Python file edit. Do not suppress or skip it.
    - For agent code: tests in `agent/tests/`, run `docker exec root-straitsagent-1 python -m pytest tests/ -v`, rebuild container.
    - For Windmill scripts: tests in `agent/tests/test_windmill_scripts.py`, then run a live Windmill job and verify per Rule 17.
16. **Every Telegram/notification message must be a self-contained ≥500-word report. Never tell the user to "refer to email" or "see the full report in email".** Each notification is the complete report, not a pointer to one. The formatter script architecture enforces this: each main script writes a canonical `.md`, and a dedicated `<name>_telegram.py` formatter reads that `.md` and builds the full ≥500-word Telegram message.
17. **Never claim a workflow output works without reading the actual rendered artifact — email body AND Telegram text — and comparing both to the canonical `.md`/DB source.** `success: True` and subject lines are not verification. Full verification requires ALL of:
    - **Email body (IMAP):** fetch the actual email body (not just the subject) from Gmail Sent folder via IMAP. Assert each section present (digest, spec failures, diagnoses, status rows). This is how the health-check digest-missing bug (2026-06-22) would have been caught.
    - **Telegram:** read `[Telegram] Sending (N chars, M words)` in formatter job logs — confirm M ≥ 500. Query `telegram_outbox`: confirm `delivered = true`, `word_count ≥ 500`, `error IS NULL`. Compare header values to front-matter in the `.md`. Confirm no "→ email" pointer.
    - **Agreement check:** the shared field set (digest, diagnoses, spec violations, schedule rows) must appear in **both** email and Telegram. `test_<script>_email_and_telegram_agree` encodes this as an automated test.
    Any report of "it works" without this evidence is invalid. For event-driven formatters (move_monitor, analyst_alert) that haven't fired live, the round-trip contract test (Hard Rule 18) substitutes until a real event occurs.
18. **Front-matter schema is a contract.** Any change to a main script's front-matter keys (adding, renaming, or removing keys) must be accompanied in the same commit by: (a) updating the matching formatter's `_build_message` to use the new keys, and (b) updating the round-trip contract test in `agent/tests/test_windmill_scripts.py` (`test_contract_<name>_*`) to exercise the changed keys. The front-matter schema for all 8 scripts is documented in `docs/WORKFLOW_ARCHITECTURE.md`.
19. **Lock-file deploy rule.** After pushing a `.py` script with `wmill script push`, confirm its `*.script.lock` carries resolved package versions (not bare `# py: 3.12`, which means "no packages" and causes `ModuleNotFoundError` if the script imports third-party libraries). Relative cross-script imports (`from u.admin.other_script import ...`) are disallowed for formatter scripts — the 8 formatters each carry their own identical `_send_telegram`/`_split_telegram_message` copy to avoid single-file-push staleness. The `test_all_formatter_senders_identical` test enforces that all 8 copies stay byte-identical.
20. **Before committing any artifact test, apply the Testing Critic checklist.** A test fails the Critic if "yes" to any of these 5 questions means the test can pass while the human gets a broken artifact:
    1. **Empty-artifact:** Can `email_html` and `tg_msg` both be `None`/empty and all assertions still pass? (Must have explicit `assert email_html is not None` guards.)
    2. **Template-string:** Could any asserted string appear in boilerplate HTML/template text independently of the world fixture? (Use world-fixture-unique strings — not `"Email"`, `"Schedule"`, etc.)
    3. **Tautology:** Is any asserted value derived from a fixture pre-sized to match the threshold? (Use a realistic narrative, not a padded stub; the word-count floor is a minimum, not a target.)
    4. **ASD-derived:** Is every asserted string present in `_SCRIPT_ASD`? Document in a comment if not.
    5. **Completeness:** Does `test_<script>_email_and_telegram_agree` iterate **all** `_SCRIPT_ASD["shared_fields"]`, not a hand-picked subset?
    See `docs/TESTING.md` → "Testing Critic" section for examples of each failure mode.

21. **Verify the response, not the request.** For any API call that delivers a user-visible artifact (Telegram message, sticker, email), the authoritative test and live verification assert on the API *response* body, not the request payload. APIs may return `ok: true` while silently dropping parameters — Telegram's `sendSticker` does this with `caption`.
    - **Tests:** mock the API to return a realistic response (including fields the API actually returns, omitting fields it silently drops). Assert the code detects missing fields and reports failure. A test that asserts `payload["caption"] == X` proves nothing — assert `response["result"]["text"] == X`, or assert the code flags delivery failure when the field is absent.
    - **Live verification:** inspect the actual API response JSON. For Telegram sends: confirm every intended field is present in `result` (e.g. `result.text` for messages, `result.sticker.emoji` for stickers). Resolve delivered `file_id`s back to their properties via `getStickerSet` and assert those properties match expectations.
    - **Applies to all sends** — report or non-report, text or non-text. Rule 16 exemption does not exempt this rule. This is the gap that let Bug 2 (`sendSticker` caption silently dropped) and Bug 1 (angry-emoji sticker paired with loving caption) ship to production on 2026-06-23. Both were caught only by the human reading the group chat, not by tests or live verification — because both checked what the code *sent*, not what Telegram *delivered*.

---

## Earnings Report Standards

See `docs/earnings_report_standards.md` for the 6 mandatory report standards. When modifying `portfolio_earnings_analysis.py`, ensure all six remain in place.

---

## Windmill Access

- URL: `http://<YOUR_VPS_IP>:8080`
- Scripts are written in Python (preferred) or TypeScript
- Resources (API keys, credentials) stored in Windmill's resource system
- Schedules set via Windmill's built-in cron scheduler

---

## Current Status

**Last updated:** 2026-06-25 (Phase C testing rollout complete for `youtube_monitor` — seams factored (`_send_email`, `_write_canonical_md`), ASD written, harness RED→GREEN, 5 artifact tests passing, Hard Rule 17 live-verified (IMAP ✓, telegram_outbox ✓, .md ✓, agreement ✓). Macro Research schedule fixed: cron `0 0 23 * * 1-5` → `0 0 7 * * 1-5` (was running 11PM SGT instead of 7AM SGT); 17 stale queued jobs from the mis-timed schedule cleared; script live-verified via preview (status=sent, 2290 words, email 28k chars, Telegram 667 words delivered). Phase C rollout: `youtube_monitor` ✅ complete. Remaining: `macro_research` → `portfolio_email` → `portfolio_review` → `portfolio_rationalization` → `portfolio_move_monitor` → `portfolio_analyst_alert`. Tests: ~479 passing in container. Repo: `vps-stack`.)

### Phase 0 — Foundation
- [x] Windmill running at `http://<YOUR_VPS_IP>:8080`
- [x] Gmail SMTP credentials in Windmill (`u/admin/gmail_smtp`)
- [x] gcloud CLI authenticated as straitsagent@gmail.com
- [x] Google Drive MCP connected (accessible via `/mcp` in Claude Code)
- [x] PostgreSQL MCP connected — direct queries to `portfolio` DB without `docker exec`. Package: `mcp-postgres`. Port `127.0.0.1:5432` bound in `docker-compose.yml`.
- [x] API keys synced to `/root/shared/keys.md`
- [x] GCP service account created with Drive + Sheets APIs enabled
- [x] PostgreSQL container deployed — `portfolio_postgres` service in `/root/docker-compose.yml`, volume `portfolio_db_data`
- [x] Persistent tmux session configured — `claude-remote` session, systemd-managed, survives SSH disconnects. Alias `cr` in `~/.bashrc`.

### Workflows Built
| Workflow | Status | Scheduled |
|---|---|---|
| 1.1 — Morning News Digest | ✅ Live | 6:30 AM SGT daily — RSS + newsletter AI summaries + programmatic links + token cost header. Recipients: <YOUR_RECIPIENT_EMAIL>, <YOUR_WORK_EMAIL> |
| 1.2 — YouTube Channel Monitor | ✅ Live | Every 6 hours (`0 0 */6 * * *` SGT) — 37 channels, RapidAPI transcripts, Deepseek summaries. Recipient: <YOUR_RECIPIENT_EMAIL> |
| Email Summary | ✅ Live | Manual — uses Deepseek |
| **Macro Research** | ✅ Live | **7:00 AM SGT daily (Mon–Fri)** — 25 Yahoo indicators + 13 FRED series + Fed RSS + Google News. 6-section Deepseek analysis (~2,400+ words). HTML email + Telegram push. Script: `u/admin/macro_research`. Old `macro_daily_push` schedule disabled. |
| 6.1 — Daily Health Check | ✅ Live | **8:00 AM SGT daily** — 3-layer notifications: (A) Deepseek per-schedule diagnosis, (B) error_alert Telegram+diagnosis on crash, (C) host deadman at 08:30 SGT. Content engine: 24h .md collector, spec-check per output type, Grok-4 holistic daily digest. Recipient: <YOUR_RECIPIENT_EMAIL> |
| 6.2 — Windmill Error Alert | ✅ Live | On failure — email + **Telegram** + Deepseek 1-line diagnosis |
| Affection Ping | ✅ Live | Hourly 8AM–10PM SGT (`0 0 8-22 * * *`). Random sticker from 11 packs (BubuDudu, Kittylove, PusheenTheCat, etc.) + Deepseek one-sentence affectionate caption sent to Telegram group. Negative-emoji blacklist. Logs to `affection_outbox` (separate from `telegram_outbox`). Rule 16 exempt (non-report). Script: `u/admin/affection_ping`. |

### Windmill Variables Added
See `docs/ROADMAP.md` → "Windmill Resources" section for the full variable/resource inventory.

### Portfolio System — Build Status
| Component | Status | Notes |
|---|---|---|
| 2.0 — PostgreSQL infra | ✅ Live | `portfolio_postgres` container, schema applied, 33 positions seeded. Resource: `u/admin/portfolio_db` |
| 2.1 — Daily price fetcher | ✅ Live | yfinance EOD + USDHKD rate, inserts last 2 days per ticker. Runs 5:45 AM + 5:45 PM SGT. Script: `u/admin/portfolio_price_fetcher`. |
| 2.2 — Portfolio email | ✅ Live | Twice daily: 6 AM SGT (US Close) + 6 PM SGT (Asia Close). ADR/local consolidation. Script: `u/admin/portfolio_email`. |
| 2.3 — Weekly portfolio review | ✅ Live | Saturday 8AM SGT. Week P&L, top movers, Finnhub news, Deepseek commentary. Script: `u/admin/portfolio_review` |
| 2.4 — Move monitor | ✅ Live | Hourly Mon–Fri 9AM–6PM SGT. Alert on portfolio ±1.5% or position ±5%. Script: `u/admin/portfolio_move_monitor` |
| 2.5 — Advanced analyses | 🔲 Planned | Rolling P&L, benchmark comparison, sector/geo breakdown |

### Analytics & Research Stack — Build Status
| Component | Status | Notes |
|---|---|---|
| 3.0 — API Audit | ✅ Complete | Multi-source field mapping, $0/mo. Research: `docs/audit/260605_fundamentals_api_audit.md` |
| 3.1 — Fundamentals fetcher | ✅ Live | Sunday 6PM SGT. Finnhub (US ratios) + yfinance (all tickers). Table: `fundamental_data`. |
| 3.2 — Financial statements | 🔲 Planned | Quarterly pull, yfinance, all 33 tickers |
| 3.3 — Portfolio Rationalization | ✅ Live | Weekly (9PM SGT, Monday). 5 factors × 4 scenarios. Absolute red flags, completeness penalty, delta tracking, 2× Grok-4.3 calls + fallback (batched Call 1 for truncation prevention). Optional `include_research=True` adds full LLM research into Grok Call 2. Script: `u/admin/portfolio_rationalization`. Schedule: `u/admin/portfolio_rationalization_monthly`. portfolio_scores table in DB. Design doc: `docs/portfolio_rationalization_framework.md` v1.2. |
| 3.4 — Portfolio Candidate Eval | ✅ Live | On-demand (Telegram: `evaluate TICKER`). 3-gate ADD/WATCH/PASS verdict: Gate 1 red flags, Gate 2 portfolio fit (price corr + fundamental sim + sector/geo/currency + gap fill), Gate 3 universe benchmark. **Auto-fetch**: dispatches `stock_data_fetcher` if quant data absent/stale (>3d), then `research_tool` if no recent stock report (>30d) — waits for DB confirmation. Full research report fed into Grok prompt. Grok-4.3 + deepseek fallback, show-your-work JSON. Script: `u/admin/portfolio_candidate_eval`. Table: `portfolio_candidate_evals`. Design doc: `docs/portfolio_candidate_eval_framework.md` v1.1. |
| T1+T2 — Unified Research Tool | ✅ Live | Script: `u/admin/research_tool`. research_type: stock/strategy/macro/project. depth: brief/standard/deep. Sources: Google News + Perplexity + Serper (all depths) → + Tavily (finance, time_range=month) + Brave (freshness=pm) + SA + EDGAR 8-K + Exa (non-stock) + FRED (macro type) (standard/deep) → + Exa (all types) + EDGAR 10-K/10-Q + agentic gap analysis round (deep). Gap analysis: Deepseek identifies 3 coverage gaps → routes to news/sec/analyst/market_data source. Grok-4.3 synthesis, max_tokens=8000 at deep. Stores markdown to `/root/research/` + PostgreSQL `research_reports`. Stock fundamentals: reads from DB first (`_read_structured_stock_data`) — dispatches `stock_data_fetcher` on stale/absent data, live-fetches all 8 if no portfolio_db. Always live-fetches: MD&A synopsis (Deepseek-chat, EDGAR 10-Q) + board of directors (DEF 14A, parser bug). Filename: `YYYY-MM-DD_{depth}_{slug}.md`. |
| Stock Data Fetcher | ✅ Live | Script: `u/admin/stock_data_fetcher`. Single-ticker generic fetcher: company profile, 3yr financials (income/BS/CF/health), valuation, ownership, insider transactions, earnings calendar, key management, peer comparisons. Persists to 14 DB tables. No synthesis, no email. Caller supplies ticker; batching is caller's responsibility (portfolio, watchlist, index). |
| F3 — Signal Collection | 🚫 Parked | Deprioritised in favour of T1/T2 |
| F4 — Stock Idea Generator | 🚫 Parked | Requires F3 first |

### Telegram Agent — Build Status
See `docs/ROADMAP.md` → "Telegram Agent Build Status" section for the full component inventory.

**Summary:** Agent fully live — FastAPI service, Telegram webhook, 15 commands (alphabetical), W2/W3/W4 tools + candidate_evaluation, /macro→macro_brief (24 indicators, 6 groups, per-section commentary + news sources), /candidate fast-path, push notifications from 8 Windmill scripts (all via md-driven formatter architecture), macro_research at 7:00 AM SGT (25 Yahoo + 13 FRED + Fed RSS + 6-section analysis), Telegram push via Deepseek synthesis (~545 words), silent groups routing (`SILENT_GROUPS` — bot ignores casual messages in listed groups, responds only to `/`-commands and `@StraitsAgentBot` mentions), 642 tests passing in container. Pending: Agent Drafts Telegram group (manual owner task).

### Next Up
1. **Phase C — Testing rollout** — `youtube_monitor` ✅ complete. Apply ASD + seam factoring + artifact harness to remaining 6 scripts in order: `macro_research` → `portfolio_email` → `portfolio_review` → `portfolio_rationalization` → `portfolio_move_monitor` → `portfolio_analyst_alert`. Per-script: ASD written → seams factored → harness RED→GREEN → word-count ≥500 → Testing Critic → Tier 0 markers → live verify. See `docs/TESTING.md` rollout table.
2. **Create "Agent Drafts" Telegram group** (owner manual task) — owner + <YOUR_BOT_USERNAME> → copy group chat_id (negative integer) → set `DRAFTS_GROUP_ID` in `/root/agent.env` → `docker compose up -d straitsagent`

---

## Documentation Workflow

### What to read at session start
Always read this file (`CLAUDE.md`) and `docs/ROADMAP.md`. Read `docs/TESTING.md` before writing any test or modifying a sending script — it is the canonical testing philosophy and harness pattern. Read `docs/WORKFLOW_ARCHITECTURE.md` when building or modifying a specific workflow — it has the full pseudocode spec for every workflow in the stack.

### When to update docs
Update docs at logical stopping points, not just at end of session:

| Trigger | What to update |
|---|---|
| Workflow built and tested | `ROADMAP.md` — mark checkbox ✅, update build order |
| Workflow scheduled | `ROADMAP.md` — add schedule confirmed note |
| Workflow design approved | `WORKFLOW_ARCHITECTURE.md` — fill in full pseudocode spec for that workflow |
| Workflow logic changed | `WORKFLOW_ARCHITECTURE.md` — keep the spec in sync with the code |
| Artifact-render harness added to a script | `docs/TESTING.md` — update rollout table |
| Phase completed | `CLAUDE.md` — update Current Status section |
| New credential added to Windmill | `CLAUDE.md` — update Current Status Phase 0 checklist |
| New VPS service deployed (e.g. Postgres) | `CLAUDE.md` — update Running Services table and Phase 0 checklist |
| Portfolio system component built | `CLAUDE.md` — update Portfolio Intelligence System build status table |
| New agent intent, tool, or classifier change | `CLAUDE.md` — update unit test count in Telegram Agent Build Status table |
| Hard rule exception or manual override | `/root/shared/override_log.md` |
| Keys file updated | Update the "Last synced" date in `shared/keys.md` |
| End of session (if work is mid-flight) | `CLAUDE.md` — update Current Status and Next Up |

### What never goes in docs
- Raw API keys or passwords (use `shared/keys.md` for that)
- Git history or who changed what (use `git log`)
- Debugging notes or fix recipes (belongs in commit messages)

---

## Start of Session Prompt

```
Read CLAUDE.md and docs/ROADMAP.md in /root/. We are working on [Phase X / specific workflow name]. Begin.
```

If working on a specific workflow, also read `docs/WORKFLOW_ARCHITECTURE.md` for the full pseudocode spec.
If writing or modifying tests, also read `docs/TESTING.md` for the artifact-driven testing philosophy.
