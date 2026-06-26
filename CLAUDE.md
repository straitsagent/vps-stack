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
|---|---|---|---|
| tmux config | `~/.tmux.conf` | Ctrl+A prefix, mouse on, 10k scrollback, status bar, `|`/`-` splits |
| Attach script (claude-remote) | `~/scripts/start-claude-remote.sh` | systemd-managed, restarts on boot |
| Attach script (gemini-workspace) | `~/scripts/start-gemini-workspace.sh` | Primary work session — created manually, no systemd |
| systemd service | `~/.config/systemd/user/claude-remote.service` | Enabled, starts `claude-remote` session on boot with Restart=on-failure |
| Shell alias | `cr` in `~/.bashrc` | Shorthand: attach to `claude-remote` or create it |

**Key commands:**

```bash
cr                            # attach to claude-remote session (or create it)
~/scripts/start-gemini-workspace.sh  # attach to or create gemini-workspace session
tmux ls                       # list all sessions
Ctrl+A d                      # detach cleanly — session stays alive
Ctrl+A |                      # split pane vertically
Ctrl+A -                      # split pane horizontally
```

After any SSH login, use `tmux ls` to see active sessions, then attach to the appropriate one. The `claude-remote` session restarts on boot via systemd; `gemini-workspace` is the primary interactive work session.

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
- **Telegram notifications use the markdown-driven formatter architecture.** Each main script writes a canonical `.md` file (JSON front-matter block + ≥500-word LLM narrative + `<!-- DETAIL -->` separator). A dedicated `<name>_telegram.py` formatter script reads that `.md` and builds the self-contained ≥500-word Telegram message. The 9 formatters are: `macro_daily_push_telegram`, `portfolio_email_telegram`, `portfolio_review_telegram`, `portfolio_rationalization_telegram`, `portfolio_move_monitor_telegram`, `portfolio_analyst_alert_telegram`, `health_check_telegram`, `youtube_monitor_telegram`, `position_sentinel_telegram`. Every Telegram send is logged to `telegram_outbox` (Postgres) and to the formatter job logs (`[Telegram] Sending ...`).

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

**Operational recipes** (credential restore, schedule API push, Docker rebuild): see `docs/OPERATIONS.md`.

To pull any changes made in the UI back to disk:
```
cd /root/windmill && wmill sync pull --yes
```

---

## Planning Workflow

Substantive work is specified in a **plan file** before any code is written — a durable artifact capturing the design so it can be executed in a later pass (possibly by a cheaper model) from a clean checkout, without the planning conversation.

**When required:** any new workflow, any change to an existing working workflow, or any multi-file / multi-step change. Trivial work (typo, one-line fix, single rename) needs only an inline description and verbal approval.

**Location & naming:** `docs/plans/YYYY-MM-DD_<slug>.md`, committed to git. When planning in Claude Code plan mode, the working file lives at `.claude/plans/<slug>.md`; **on approval, persist it to `docs/plans/` with `Status: approved` and commit** — that committed copy is the cross-tool handoff artifact (opencode/Deepseek read it from the checkout; they never see `.claude/plans/`).

**Front-matter (required):**
```
---
Subject: <one-line description>
Date: YYYY-MM-DD
Status: draft | approved | executing | done | abandoned
---
```

**Body:** Context (why) → files to create/modify/delete → step-by-step `- [ ]` checklist with success criteria → verification section → an `## Execution` footer (below).

**Handoff standard:** every plan must comply with `docs/EXECUTOR_CONTRACT.md` (Hard Rule 22). In addition to the above, the body carries four mandatory sections so any executor model can run it safely: **Locked Oracle Tests** (G1 — frozen assertions in a `# LOCKED ORACLE — copy verbatim` block; planner-authored for high-risk plans), **RED-proof requirement** (G2), **Asserting Verification Script** (G4 — prints + asserts decisive artifacts, exits non-zero on failure, ends in `PASS`), and **Acceptance Gate** (the reviewer checklist that flips Status to done). New plans copy `docs/plans/_TEMPLATE.md`.

**`## Execution` footer (every plan carries this, so it is portable to any tool/model):**
```
1. Set front-matter Status: executing, commit.
2. Work the checklist top to bottom; tick each `- [ ]` when its success criteria are met.
3. Run the Verification section.
4. Set Status: done, commit.
Satisfy all five gates in `docs/EXECUTOR_CONTRACT.md`; do not modify `# LOCKED ORACLE` assertions; STOP on any deviation.
Do not redesign. If the plan is ambiguous or wrong, stop and report — do not improvise.
```

**Status lifecycle:**

| Status | Set by | When |
|---|---|---|
| `draft` | planner | on writing the plan |
| `approved` | planner, after explicit user approval | user says go (persist to `docs/plans/`, commit) |
| `executing` | executor | when it starts the checklist |
| `done` | executor | all steps complete and committed |
| `abandoned` | either | plan shelved; file kept for record |

**Session start:** scan `docs/plans/` for any file with `Status: approved` or `executing` and surface it (Subject + checklist progress) before other work.

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
7. **For substantive work, document the design as a plan file in `docs/plans/` (see Planning Workflow) and get explicit approval before coding. For trivial work (typo, one-line fix, single rename), describe inline and get verbal approval.** Either way, only start coding after explicit confirmation.
8. **Never delete or overwrite existing Windmill resources** (especially `u/admin/gmail_smtp`) without explicit confirmation. When rewriting a workflow, only touch the script file — leave all resources/variables intact. `gmail_smtp` was accidentally deleted during a Morning Digest rewrite on 2026-06-03 and had to be manually recreated.
9. **Use `wmill script push <path>` for all script deployments.** Never use `wmill sync push` for routine changes — it has caused resource/variable deletion and stale-version deployments. Always run wmill commands from `/root/windmill/`.
10. **Always show the exact LLM prompt text and get explicit approval before coding it.** Domain-specific framing (e.g. "for an infra finance professional") can cause the model to silently skip content — keep prompts generic unless specifically requested.
11. **In Windmill schedule args, always use string format for resource/variable references.** Correct: `"$res:u/admin/portfolio_db"`, `"$var:u/admin/deepseek_key"`. Wrong: `{"$res": "u/admin/portfolio_db"}` (dict form — Windmill does not resolve this and the script receives an unresolved dict, causing KeyError at runtime).
12. **Before modifying any existing working workflow, write a plan file describing the proposed change and get explicit approval.** Do not rebuild, restructure, or redesign a working script on your own judgment — this has caused regressions and a botched revert that wiped Windmill scripts. Rule 7 covers new workflows; this rule covers changes to existing ones.
13. **Google OAuth always requires a browser action — state this upfront before attempting any workaround.** gcloud auth, rclone, FIFO tricks, and service account flows all have this limitation in some form. If a task depends on browser-based auth and a browser is not available, say so immediately and propose an alternative rather than silently burning time on doomed workarounds.
14. **When fetching news or time-series data, always apply a recency date cutoff.** Never return articles older than 48 hours unless explicitly requested. Validate the actual date values of returned articles before declaring a news fetch successful — stale January articles have shipped through tests that only checked for non-empty results.
15. **Artifact-driven TDD is mandatory for ALL code. No exceptions. See `docs/TESTING.md` for the full philosophy.**
16. **Every Telegram/notification message ≥500 words, self-contained. No "see email" pointers. See `docs/TESTING.md`.**
17. **Live-verify rendered artifacts, not `success: True`. Email body (IMAP) + Telegram (outbox) + agreement check. See `docs/TESTING.md`.**
18. **Front-matter schema is a contract.** Changing keys requires updating formatter `_build_message` + round-trip contract test in same commit.
19. **Lock-file deploy rule.** Confirm `*.script.lock` has resolved packages (not bare `# py: 3.12`). No cross-script imports for formatters; all 9 carry identical `_send_telegram`/`_split_telegram_message` copies.
20. **Apply Testing Critic checklist before committing artifact tests.** 5 failure modes: empty-artifact, template-string, tautology, ASD-derived, completeness. See `docs/TESTING.md`.
21. **Verify the response, not the request.** Assert on API response body, not request payload (Telegram silently drops `sendSticker` caption). Applies to all sends.
22. **Cross-model handoff contract.** Any plan intended for execution must satisfy `docs/EXECUTOR_CONTRACT.md`: a locked oracle (G1), RED-before-GREEN proof (G2), artifact evidence not claims (G3), an asserting verify script (G4), and STOP-on-deviation (G5). Completion is gated by review, not self-report. Never edit a `# LOCKED ORACLE` block.

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

See `docs/ROADMAP.md` for the full build status, live workflows, and next-up priorities. This file (CLAUDE.md) is the context+rules reference; ROADMAP.md is the single source for status.

---

## Documentation Workflow

### What to read at session start
Always read this file (`CLAUDE.md`) and `docs/ROADMAP.md`. Read `docs/TESTING.md` before writing any test or modifying a sending script — it is the canonical testing philosophy and harness pattern. Read `docs/WORKFLOW_ARCHITECTURE.md` when building or modifying a specific workflow — it has the full pseudocode spec for every workflow in the stack. Also scan `docs/plans/` for any plan with `Status: approved` or `executing` and surface it (Subject + checklist progress) before other work.

### When to update docs
Update docs at logical stopping points, not just at end of session:

| Trigger | What to update |
|---|---|---|
| Workflow built/tested/scheduled/changed | `ROADMAP.md` (status) or `WORKFLOW_ARCHITECTURE.md` (pseudocode) |
| Artifact harness added | `docs/TESTING.md` (rollout table) |
| New VPS service, credential, or agent tool | `ROADMAP.md` (running services, resources, build status) |
| Phase completed / end of session | `ROADMAP.md` (Current Status + Next Up) |
| Hard rule exception or manual override | `/root/shared/override_log.md` |
| Keys file updated | Update "Last synced" date in `shared/keys.md` |
| Plan file created/approved/executed/abandoned | `docs/plans/` (Status field is the source of truth; commit the file) |

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
