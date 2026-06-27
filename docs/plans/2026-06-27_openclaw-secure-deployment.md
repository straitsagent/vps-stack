---
Subject: Secure OpenClaw deployment (sandboxed assistant) + phased security reorg
Date: 2026-06-27
Status: approved
Planner model: claude-sonnet-4-6
Risk tier: HIGH (new internet-facing LLM agent with shell capability; touches live stack, DB roles, secrets)
Hard Rules in force: [1, 5, 6, 7, 8, 10, 12]
Complies with: docs/EXECUTOR_CONTRACT.md
Files to read before coding: CLAUDE.md, docs/OPERATIONS.md, /root/docker-compose.yml, /root/agent/Dockerfile, /opt/n8n/Caddyfile
---

# Plan: Secure OpenClaw Deployment + Phased Security Reorg

## Context

Add **OpenClaw** (an open-source self-hosted AI agent runtime — Node.js service that connects
messaging apps to an LLM that executes shell commands, reads/writes files, and browses the web)
to this VPS as a **sandboxed assistant**: it can run code and write files, but only inside its
own throwaway container workspace; it has **no /root access and no secrets**, read-only access to
the research corpus + DB + docs, and is reachable only by the owner over Telegram polling.

**Threat model (the design driver).** OpenClaw is LLM-driven and reads research files and web
pages — a textbook indirect-prompt-injection surface. We therefore treat the openclaw container
as **potentially compromised at all times**. Every control below exists so that a fully-hijacked
openclaw can do nothing worse than: read research the owner already owns, run code inside a
disposable container, and burn the LLM API key. It must NOT be able to reach host secrets, the
privileged `dind` Docker daemon (container-escape vector on `root_default`), the Windmill control
plane, write to research/DB, or pivot to other services.

**Current posture (favorable).** Research (`/root/research`, 221 `.md` files, no secrets) is cleanly
separated from credentials (`/root/shared/keys.md`, `*.env`). `straitsagent` is a ready isolation
template (non-root, no published port, `:ro` mounts). Landmines: privileged `dind:2375` on
`root_default` (compose lines 54-63, 84-93); `portfolio_postgres` has only the full-privilege owner
role (no read-only role); `/root/affection.env` is world-readable (644).

Decisions locked with owner: **Sandboxed assistant** · **Telegram polling, owner-only** ·
**read-only files + DB + docs** · **phased reorg (targeted now, big relocation as follow-up)**.

---

## Phase 0 — Targeted hardening (ship-blocking prerequisites)

- [ ] **Fix secret file perms.** `chmod 600 /root/affection.env` (currently 644). Audit and
  normalize all secret files to `600`: `/root/.env`, `/root/agent.env`, `/root/affection.env`,
  `/root/shared/keys.md`, `/root/shared/windmill-sa-key.json`, `/opt/n8n/stack.env`.
  Success: `find /root -maxdepth 2 -name '*.env' -o -name 'keys.md' | xargs stat -c '%a %n'` all `600`.

- [ ] **Create scoped read-only Postgres role** (allowlist, not denylist). New migration
  `/root/portfolio/openclaw_ro_role.sql`:
  ```sql
  CREATE ROLE openclaw_ro LOGIN PASSWORD :'pw';   -- pw injected at apply time, stored in keys.md
  GRANT CONNECT ON DATABASE portfolio TO openclaw_ro;
  GRANT USAGE ON SCHEMA public TO openclaw_ro;
  ALTER ROLE openclaw_ro SET statement_timeout = '15s';   -- DoS guard
  -- EXPLICIT allowlist — research / quant / market tables only:
  GRANT SELECT ON
    company_profiles, financial_statements_placeholder, income_statements, balance_sheets,
    cashflow_statements, financial_health_metrics, valuation_snapshots, fundamental_data,
    ownership_snapshots, institutional_holders, insider_transactions, peer_comparisons,
    next_earnings, earnings_surprises, earnings_analyses,
    price_history, fx_rates, portfolio_positions, portfolio_scores, portfolio_candidate_evals,
    portfolio_thesis, watchlist_ideas, position_events, position_signals,
    research_reports
  TO openclaw_ro;
  -- DELIBERATELY EXCLUDED (secrets / PII / agent internals — never grant):
  --   key_management, agent_conversation_history, agent_kv, agent_audit_log,
  --   agent_contact_rules, agent_draft_queue, agent_pending_confirmations,
  --   agent_pending_jobs, artifact_verification, telegram_outbox, affection_outbox
  ```
  (Verify exact table names against `/root/portfolio/schema.sql` at apply time; the above is the
  reviewed allowlist. New research tables must be GRANTed explicitly — secure by default.)
  Success: `psql -U openclaw_ro` can `SELECT` from `research_reports`, gets permission-denied on
  `key_management` and `agent_conversation_history`, and `INSERT` fails everywhere.

- [ ] **Confirm LLM provider/model (Hard Rule 6 + 10).** OpenClaw is bring-your-own-key. Memory
  rule: **no Anthropic API** — use Deepseek / OpenRouter / xAI-Grok / Perplexity. Proposed default:
  **OpenRouter** (OpenAI-compatible endpoint, lets owner pick the model). **SIGN-OFF REQUIRED**
  before writing config: (a) provider, (b) exact model id, (c) confirm OpenClaw supports its
  OpenAI-compatible base URL. New key (if OpenRouter) added to `keys.md` + `openclaw.env`.

---

## Phase 1 — Deploy OpenClaw (sandboxed)

### Files to create
| Path | Purpose |
|---|---|
| `/root/openclaw/Dockerfile` | Build from official openclaw image or `node:22-slim` + openclaw; non-root user |
| `/root/openclaw/config/openclaw.json` | Agent config — tool policy, channel allowlist, model (mounted `:ro`) |
| `/root/openclaw.env` | `chmod 600` — ONLY: LLM API key, Telegram bot token, `openclaw_ro` DB connstring |
| `/root/portfolio/openclaw_ro_role.sql` | The RO role migration (Phase 0) |
| `/root/docker-compose.yml` (edit) | Add `openclaw` service + two new networks |

### Container service (add to `/root/docker-compose.yml`)
Mirror the `straitsagent` isolation pattern, then harden further:
```yaml
  openclaw:
    build: ./openclaw
    restart: unless-stopped
    env_file: [ openclaw.env ]          # LLM key + telegram token + openclaw_ro connstring ONLY
    networks: [ openclaw_egress, openclaw_db ]   # NOT default (avoids dind:2375), NOT agent_net
    user: "1000:1000"                    # non-root
    read_only: true                      # immutable rootfs
    tmpfs: [ /tmp ]
    cap_drop: [ ALL ]
    security_opt: [ "no-new-privileges:true" ]
    mem_limit: 1g
    pids_limit: 256
    volumes:
      - /root/research:/research:ro      # corpus, read-only
      - /root/docs:/docs:ro              # reference docs, read-only
      - ./openclaw/config:/config:ro     # agent config, read-only
      - openclaw_workspace:/workspace    # ONLY writable path (agent sandbox)
    # NO ports: — polling mode, zero inbound host exposure
    logging: *default-logging

networks:
  openclaw_egress: {}                    # default bridge → internet egress (LLM/Telegram/web)
  openclaw_db: { internal: true }        # no egress; shared only with portfolio_postgres

# portfolio_postgres: ADD `openclaw_db` to its existing `networks:` list so openclaw can reach
# it by service name WITHOUT either joining root_default.
```
**Why this network split:** `portfolio_postgres` currently sits on `default` (= `root_default`)
alongside privileged `dind`. Putting openclaw on `default` to reach the DB would expose it to the
unauthenticated `dind:2375` escape vector. Instead, give postgres a second network `openclaw_db`
(`internal: true`, no egress) shared only with openclaw; openclaw gets internet via the separate
`openclaw_egress` bridge. Result: openclaw can reach the DB and the internet, but never `dind`,
never the Windmill control-plane `db`, never other app containers.

### OpenClaw config (`/root/openclaw/config/openclaw.json`) — SIGN-OFF on tool policy + prompt
```jsonc
{
  "model": { "primary": "<provider/model — Phase 0 sign-off>", "baseUrl": "<OpenAI-compatible>" },
  "tools": {
    "fs": { "workspaceOnly": true },     // writes confined to /workspace
    "shell": { "enabled": true }          // runs IN-container only; container is the boundary
  },
  "channels": {
    "telegram": { "mode": "polling", "allowFrom": ["<OWNER_TELEGRAM_ID>"] }  // owner-only
  },
  "session": { "scope": "per-sender" }
}
```
- `fs.workspaceOnly:true` + `read_only` rootfs + `:ro` mounts = the agent can READ `/research`
  and `/docs` but can WRITE only `/workspace`. Write-restriction is enforced by the OS (ro mounts),
  not just app config — defense in depth.
- `shell.enabled:true` is acceptable here precisely because the container has nothing valuable,
  can't escalate (cap_drop ALL, no-new-privileges, non-root, read-only), and can't pivot
  (network-isolated). The container IS the sandbox.
- DB access: install `postgresql-client` in the image; the agent queries via `psql "$OPENCLAW_RO_DSN"`
  from its workspace. The `openclaw_ro` role + `statement_timeout` enforce read-only + DoS-safety.
  (Alternative considered: a read-only MCP/HTTP query shim for auditability — deferred; the RO role
  is the security boundary and is sufficient for v1.)

### Telegram bot
- New dedicated bot (BotFather) → token in `openclaw.env`. Distinct from `telegram_bot_token` /
  `affection_bot_token`. Polling mode = no Caddy route, no public webhook, no host port.
- `allowFrom = [owner chat_id]` (reuse the value behind `u/admin/telegram_owner_id`).

---

## Phase 2 — Significant relocation (SEPARATE follow-up plan, not this PR)

Scheduled, not executed here. Promote to its own `docs/plans/` file:
- Relocate shareable artifacts to a dedicated tree outside `/root` (e.g. `/srv/shared/research`),
  so the trust boundary is filesystem-enforced rather than mount-discipline. Touches the
  `windmill_worker` rw mount (compose line 103), the `straitsagent` ro mounts (226-228), the
  `index.json` path prefix, and all 14 research-writing scripts under `windmill/u/admin/`.
- Consolidate every secret under one strict-perm location (`/root/secrets/`, `700`), optionally
  sops/age-encrypted at rest; update every `env_file:` / path reference.
- This is multi-session and regression-prone (every research path changes) → its own plan with its
  own oracle + verification. **Do not start it in this plan.**

---

## Asserting Verification Script (G4)

```bash
#!/bin/bash
fail=0
OC=openclaw   # container name

echo "=== 1. Non-root + hardening ==="
docker inspect $OC --format '{{.Config.User}} ro={{.HostConfig.ReadonlyRootfs}} priv={{.HostConfig.Privileged}} caps={{.HostConfig.CapDrop}}' \
  | grep -q "1000:1000 ro=true priv=false" && echo PASS || { echo "FAIL: hardening"; fail=1; }

echo "=== 2. Cannot reach dind (escape vector) ==="
docker exec $OC sh -c 'getent hosts dind || nc -z -w2 dind 2375' 2>&1 | grep -q . \
  && { echo "FAIL: dind reachable"; fail=1; } || echo "PASS: dind unreachable"

echo "=== 3. No /root, no secrets in container ==="
docker exec $OC sh -c 'ls /root 2>/dev/null; cat /research/../shared/keys.md 2>/dev/null; env | grep -iE "PORTFOLIO_DB_PASSWORD|WM_TOKEN|smtp"' \
  | grep -q . && { echo "FAIL: secret/host leak"; fail=1; } || echo "PASS: no host/secret access"

echo "=== 4. Research read-only ==="
docker exec $OC sh -c 'cat /research/news/*.md >/dev/null 2>&1 && touch /research/x 2>/dev/null' \
  && { echo "FAIL: research writable"; fail=1; } || echo "PASS: research readable, not writable"

echo "=== 5. DB role read-only + scoped ==="
docker exec $OC sh -c 'psql "$OPENCLAW_RO_DSN" -tAc "SELECT count(*) FROM research_reports" >/dev/null 2>&1 \
  && ! psql "$OPENCLAW_RO_DSN" -tAc "SELECT 1 FROM key_management" 2>/dev/null \
  && ! psql "$OPENCLAW_RO_DSN" -tAc "INSERT INTO watchlist_ideas DEFAULT VALUES" 2>/dev/null' \
  && echo "PASS: RO + scoped" || { echo "FAIL: DB scope"; fail=1; }

echo "=== 6. No published host port ==="
docker port $OC 2>/dev/null | grep -q . && { echo "FAIL: port published"; fail=1; } || echo "PASS: no inbound port"

echo "=== 7. Functional: reads a research file via Telegram (manual) ==="
echo "  Send owner-only Telegram msg: 'summarize today's macro research'; confirm it cites a /research/macro file."
echo "  Send from a SECOND account; confirm IGNORED (allowFrom)."

[ $fail -eq 0 ] && echo "PASS" || exit 1
```

## Acceptance Gate
- [ ] Phase 0: secret perms all `600`; `openclaw_ro` role created, SELECT-only, `key_management`/`agent_*` denied
- [ ] LLM provider/model + tool policy + system prompt signed off by owner (Hard Rules 6, 10)
- [ ] Container: non-root, read-only rootfs, cap_drop ALL, no-new-privileges, mem/pids limits, no published port
- [ ] Network: openclaw on `openclaw_egress`+`openclaw_db` only; `dind` and Windmill `db` unreachable (verify script §2)
- [ ] No `/root`, no secret env, research+docs `:ro`, only `/workspace` writable (verify script §3-4)
- [ ] DB read-only + table-scoped (verify script §5)
- [ ] Telegram owner-only confirmed (rejects a second sender)
- [ ] Verify script output pasted, ends in `PASS`
- [ ] Phase 2 relocation written as a separate `docs/plans/` file (not executed here)

## Execution
1. Set Status: executing, commit.
2. Phase 0 (perms, RO role, provider sign-off) → Phase 1 (build, compose, config, bot) top to bottom.
3. Run the Asserting Verification Script — paste output, must end in `PASS`.
4. Write the Phase 2 relocation plan as its own file; do NOT execute it here.
5. Reviewer flips Status: done per the Acceptance Gate.
Satisfy all five gates in `docs/EXECUTOR_CONTRACT.md`; STOP on any deviation. Never weaken a
containment control (network split, cap_drop, ro mounts, RO role allowlist) to make something work —
stop and report instead.
