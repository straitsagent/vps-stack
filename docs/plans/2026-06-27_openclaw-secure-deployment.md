---
Subject: Secure OpenClaw deployment (sandboxed assistant) + phased security reorg
Date: 2026-06-27
Status: approved
Planner model: claude-sonnet-4-6 (revised after opencode/Deepseek-V4 review 2026-06-27)
Risk tier: HIGH (new internet-facing LLM agent with shell capability; touches live stack, DB roles, secrets)
Hard Rules in force: [1, 5, 6, 7, 8, 10, 12, 20, 21]
Complies with: docs/EXECUTOR_CONTRACT.md
Review: docs/opencode/2026-06-27_openclaw-plan-review.md (B1, B2, C1, C2, V1-V3, P1-P8 incorporated)
Files to read before coding: CLAUDE.md, docs/OPERATIONS.md, docs/EXECUTOR_CONTRACT.md, /root/docker-compose.yml, /root/agent/Dockerfile, /root/Caddyfile
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
separated from credentials (`/root/shared/keys.md`, `*.env`). Landmines: privileged `dind:2375` on
`root_default` (compose lines 54-63, 84-93); `portfolio_postgres` has only the full-privilege owner
role (no read-only role); `/root/affection.env` is world-readable (644) — and it is the ONLY such
file (`.env`, `agent.env`, `keys.md`, `windmill-sa-key.json`, `/opt/n8n/stack.env` are already 600).

**On the `straitsagent` precedent (P5).** `straitsagent` is non-root (`USER agent` in its
Dockerfile) with `:ro` mounts and no published port — but it has NO `read_only` rootfs, NO
`cap_drop`, NO `no-new-privileges`, and NO `mem_limit`/`pids_limit`, and it sits on `default`
(= `root_default`, exposed to `dind`). It is a partial reference, not a template to copy. **The
openclaw service block below is the authoritative spec** — it hardens substantially beyond
straitsagent. Do not copy straitsagent's compose block expecting it to carry these controls.

Decisions locked with owner: **Sandboxed assistant** · **Telegram polling, owner-only** ·
**read-only files + DB + docs** · **phased reorg (targeted now, big relocation as follow-up)**.

---

## Phase 0 — Targeted hardening (ship-blocking prerequisites)

- [ ] **Fix secret file perms (P1).** Today only `/root/affection.env` is 644; everything else is
  already 600 — so this is a one-file change. Apply and then verify with a correctly-grouped find:
  ```bash
  chmod 600 /root/affection.env
  find /root /opt/n8n -maxdepth 2 \
    \( -name '*.env' -o -name 'keys.md' -o -name 'windmill-sa-key.json' \) \
    | xargs stat -c '%a %n'
  ```
  Success: every line of the find output begins with `600`.

- [ ] **Create scoped read-only Postgres role** (allowlist, not denylist). New migration
  `/root/portfolio/openclaw_ro_role.sql`. Idempotent per the repo convention (P2); the password is
  passed via a psql variable read from a `chmod 600` temp file, NEVER on the CLI (no `ps`/history
  leak):
  ```sql
  -- Apply:  psql -U portfolio_user -d portfolio -v pw="$(cat /root/.openclaw_ro_pw)" \
  --              -f /root/portfolio/openclaw_ro_role.sql
  -- (/root/.openclaw_ro_pw is chmod 600, deleted after apply; pw also recorded in keys.md)
  DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'openclaw_ro') THEN
      EXECUTE format('CREATE ROLE openclaw_ro LOGIN PASSWORD %L', :'pw');
    END IF;
  END $$;
  GRANT CONNECT ON DATABASE portfolio TO openclaw_ro;
  GRANT USAGE ON SCHEMA public TO openclaw_ro;
  ALTER ROLE openclaw_ro SET statement_timeout = '15s';   -- DoS guard
  -- EXPLICIT allowlist — research / quant / market tables only.
  -- (B1: financial_statements_placeholder REMOVED — it does not exist; a multi-table GRANT
  --  aborts atomically if any relation is missing, granting NOTHING. Annual financials are
  --  already covered by income_statements / balance_sheets / cashflow_statements.)
  GRANT SELECT ON
    company_profiles, income_statements, balance_sheets, cashflow_statements,
    financial_health_metrics, valuation_snapshots, fundamental_data,
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
  (The allowlist is frozen and reviewed against the live schema — every name above exists as a
  relation. New research tables must be GRANTed explicitly — secure by default.)
  Success: `openclaw_ro` can `SELECT` from `research_reports`; gets `permission denied` (asserted
  by error text, not just non-zero exit) on `key_management`; and every write is denied **by
  privilege** (asserted by error text — see verify §5, B2).

- [ ] **Confirm LLM provider/model (Hard Rule 6 + 10).** OpenClaw is bring-your-own-key. Memory
  rule: **no Anthropic API** — use Deepseek / OpenRouter / xAI-Grok / Perplexity. Proposed default:
  **OpenRouter** (OpenAI-compatible endpoint, lets owner pick the model). **SIGN-OFF REQUIRED**
  before writing config: (a) provider, (b) exact model id, (c) confirm OpenClaw supports its
  OpenAI-compatible base URL. New key (if OpenRouter) added to `keys.md` + `openclaw.env`.
  *(O1: this is a mandatory STOP partway through an "approved" plan — the executor must surface it
  at session start and round-trip with the owner before writing config.)*

---

## Phase 1 — Deploy OpenClaw (sandboxed)

### Files to create
| Path | Purpose |
|---|---|
| `/root/openclaw/Dockerfile` | `node:22-slim` + openclaw + a guaranteed net probe; non-root user `1000`; **`mkdir -p /workspace && chown 1000:1000 /workspace`** (P4 — named volumes are root-owned; without this the sandbox's only writable path is unwritable) |
| `/root/openclaw/config/openclaw.json` | Agent config — tool policy, channel allowlist, model (mounted `:ro`) |
| `/root/openclaw.env` | `chmod 600` — ONLY: LLM API key, Telegram bot token, `openclaw_ro` DSN (`OPENCLAW_RO_DSN`) |
| `/root/portfolio/openclaw_ro_role.sql` | The RO role migration (Phase 0) |
| `/root/docker-compose.yml` (edit) | Add `openclaw` service + two new networks |

### Required-write-paths discovery (P3 — build-time, do FIRST)
`read_only: true` with only `/tmp` + `/workspace` writable **may prevent OpenClaw from booting** —
Node/OpenClaw commonly write to `~/.npm`, `~/.config`, a session/log dir, and `/run`. Before
finalizing the compose block, run the image once and enumerate every path it writes at startup
(strace/`--read-only` dry run / inspect docs), then add a matching `tmpfs:` for each (candidates:
`/home/openclaw`, `/run`). **G5 HARD CONSTRAINT: if the container won't boot read-only, add the
specific tmpfs path — do NOT drop `read_only: true`.** Dropping it weakens a containment control;
stop and report instead.

### Container service (add to `/root/docker-compose.yml`)
```yaml
  openclaw:
    build: ./openclaw
    restart: unless-stopped
    env_file: [ openclaw.env ]          # LLM key + telegram token + OPENCLAW_RO_DSN ONLY
    networks: [ openclaw_egress, openclaw_db ]   # NOT default (avoids dind:2375), NOT agent_net
    user: "1000:1000"                    # non-root
    read_only: true                      # immutable rootfs
    tmpfs:                               # writable scratch ONLY (extend per P3 discovery)
      - /tmp
      - /run
      - /home/openclaw
    cap_drop: [ ALL ]
    security_opt: [ "no-new-privileges:true" ]
    mem_limit: 1g                        # P6: KEEP this v2 key — do NOT convert to
    pids_limit: 256                      #     deploy.resources (ignored by non-swarm compose →
                                         #     would silently DROP enforcement; G5 weakening).
    volumes:
      - /root/research:/research:ro      # corpus, read-only
      - /root/docs:/docs:ro              # reference docs, read-only
      - ./openclaw/config:/config:ro     # agent config, read-only
      - openclaw_workspace:/workspace    # ONLY writable volume (agent sandbox; chowned in Dockerfile)
    # NO ports: — polling mode, zero inbound host exposure
    logging: *default-logging

volumes:
  openclaw_workspace: {}

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
  `affection_bot_token`. Polling mode = no Caddy route, no public webhook, no host port. (Confirmed:
  the live Caddyfile is `/root/Caddyfile` (compose line 264, `./Caddyfile`); read it to confirm no
  webhook route is needed — none is, openclaw polls. P7.)
- `allowFrom = [owner chat_id]`. Retrieve the owner id with
  `wmill variable get u/admin/telegram_owner_id` (P8) — it is sensitive: write it only into
  `openclaw.json`/`openclaw.env`, NEVER echo it into the plan, a log, or a commit message.

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

## Locked Oracle Tests (G1) — `# LOCKED ORACLE — copy verbatim` (C1)

Frozen assertions; the reviewer diffs the running container against these. Do NOT modify.

```bash
# LOCKED ORACLE — copy verbatim
# Run after the openclaw container is up. Each asserts an exact runtime fact.

# O1: container is non-root, read-only rootfs, unprivileged, all caps dropped
test "$(docker inspect openclaw --format '{{.Config.User}}|{{.HostConfig.ReadonlyRootfs}}|{{.HostConfig.Privileged}}|{{json .HostConfig.CapDrop}}')" \
  = '1000:1000|true|false|["ALL"]'

# O2: openclaw is on EXACTLY the two intended networks, and NOT on root_default
test "$(docker inspect openclaw --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}' | tr ' ' '\n' | grep -vc '^$')" = "2"
docker inspect openclaw --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{"\n"}}{{end}}' | grep -q 'openclaw_egress'
docker inspect openclaw --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{"\n"}}{{end}}' | grep -q 'openclaw_db'
! docker inspect openclaw --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{"\n"}}{{end}}' | grep -q 'root_default'

# O3: no host port published
test -z "$(docker inspect openclaw --format '{{json .NetworkSettings.Ports}}' | tr -d '{}null')"

# O4: openclaw_db network is internal (no egress)
test "$(docker network inspect openclaw_db --format '{{.Internal}}')" = "true"

# O5: enforcing resource limits are set in the v2 keys (P6)
test "$(docker inspect openclaw --format '{{.HostConfig.Memory}}')" = "1073741824"
test "$(docker inspect openclaw --format '{{.HostConfig.PidsLimit}}')" = "256"
```

## RED-before-GREEN requirement (G2) (C2)

The RED state is **pre-deployment**: before the `openclaw` service is built, run the LOCKED ORACLE
and the Verification Script — every check fails because `docker inspect openclaw` errors
(`No such object: openclaw`). Paste that failing run. Then build/up and paste the GREEN run where
all assertions pass. This proves the oracle discriminates (not a tautology that passes on an empty
stack).

## Asserting Verification Script (G4)

```bash
#!/bin/bash
fail=0
OC=openclaw   # container name

echo "=== 1. Non-root + hardening (incl. caps — V1) ==="
docker inspect $OC --format '{{.Config.User}} ro={{.HostConfig.ReadonlyRootfs}} priv={{.HostConfig.Privileged}} caps={{json .HostConfig.CapDrop}}' \
  | grep -q '1000:1000 ro=true priv=false caps=\["ALL"\]' && echo PASS || { echo "FAIL: hardening"; fail=1; }

echo "=== 2. Cannot reach dind (escape vector) — node probe, no nc/getent dep (V2) ==="
docker exec $OC node -e "require('net').createConnection({host:'dind',port:2375},()=>process.exit(0)).on('error',()=>process.exit(1))" 2>/dev/null \
  && { echo "FAIL: dind reachable"; fail=1; } || echo "PASS: dind unreachable"

echo "=== 3. Mounts are exactly the intended ro binds + writable scratch (V3) ==="
# Assert against actual mount table, not a never-mounted path. No host bind may expose /root content.
docker exec $OC sh -c 'mount | grep -E " on /(research|docs|config) "' | grep -q 'ro,' \
  && ! docker exec $OC sh -c 'mount | grep -qE " on /(root|shared|home/.*/.ssh) "' \
  && echo "PASS: only intended ro binds present" || { echo "FAIL: unexpected/unsafe mount"; fail=1; }

echo "=== 3b. Env carries ONLY intended vars — no stray host secrets (V3) ==="
docker exec $OC sh -c 'env | grep -iE "_PASSWORD=|WM_|DATABASE_URL=|SMTP_|SA_KEY" | grep -v "^OPENCLAW_RO_DSN="' \
  | grep -q . && { echo "FAIL: stray host secret in env"; fail=1; } || echo "PASS: no stray host secrets"

echo "=== 4. Research read-only ==="
docker exec $OC sh -c 'cat /research/news/*.md >/dev/null 2>&1 && touch /research/x 2>/dev/null' \
  && { echo "FAIL: research writable"; fail=1; } || echo "PASS: research readable, not writable"

echo "=== 5. DB role read-only + scoped — assert error TEXT, not exit code (B2) ==="
docker exec $OC sh -c 'psql "$OPENCLAW_RO_DSN" -tAc "SELECT count(*) FROM research_reports"' >/dev/null 2>&1 \
  && echo "  PASS: SELECT research_reports OK" || { echo "  FAIL: cannot read research_reports"; fail=1; }
docker exec $OC sh -c 'psql "$OPENCLAW_RO_DSN" -tAc "SELECT 1 FROM key_management" 2>&1' \
  | grep -q "permission denied for table key_management" \
  && echo "  PASS: key_management denied BY PRIVILEGE" || { echo "  FAIL: key_management not privilege-denied"; fail=1; }
docker exec $OC sh -c 'psql "$OPENCLAW_RO_DSN" -tAc "INSERT INTO watchlist_ideas(ticker,source) VALUES ('"'"'X'"'"','"'"'t'"'"')" 2>&1' \
  | grep -q "permission denied for table watchlist_ideas" \
  && echo "  PASS: INSERT denied BY PRIVILEGE" || { echo "  FAIL: write not privilege-denied"; fail=1; }

echo "=== 6. No published host port ==="
docker port $OC 2>/dev/null | grep -q . && { echo "FAIL: port published"; fail=1; } || echo "PASS: no inbound port"

echo "=== 7. Functional: reads a research file via Telegram (manual) ==="
echo "  Send owner-only Telegram msg: 'summarize today's macro research'; confirm it cites a /research/macro file."
echo "  Send from a SECOND account; confirm IGNORED (allowFrom)."

[ $fail -eq 0 ] && echo "PASS" || exit 1
```
Note (B2): the write probe now supplies the NOT NULL `ticker`+`source` columns and matches on
`permission denied for table watchlist_ideas`, so the assertion proves the *privilege* denies the
write — not a schema constraint. Same pattern for `key_management`.

## Acceptance Gate
- [ ] Phase 0: `affection.env` → 600 (find output all `600`); `openclaw_ro` role created idempotently, SELECT-only, `key_management`/`agent_*` denied **by privilege** (error-text asserted)
- [ ] LLM provider/model + tool policy + system prompt signed off by owner (Hard Rules 6, 10)
- [ ] RED run pasted (pre-build: `No such object: openclaw`) then GREEN run (G2/C2)
- [ ] LOCKED ORACLE block passes verbatim against the running container (G1)
- [ ] Container: non-root, read-only rootfs (with the P3 tmpfs paths it actually needs — `read_only` NOT dropped), cap_drop ALL, no-new-privileges, mem/pids limits in v2 keys, no published port
- [ ] `/workspace` chowned to 1000:1000 and writable by the agent (P4)
- [ ] Network: openclaw on `openclaw_egress`+`openclaw_db` only; `dind` and Windmill `db` unreachable (verify §2, oracle O2)
- [ ] Mounts: only `/research`+`/docs`+`/config` ro + scratch tmpfs + `/workspace`; no `/root` exposure; env carries only intended vars (verify §3/§3b)
- [ ] DB read-only + table-scoped, denials proven by privilege (verify §5)
- [ ] Telegram owner-only confirmed (rejects a second sender); owner id never committed/echoed (P8)
- [ ] Verify script output pasted, ends in `PASS`
- [ ] Phase 2 relocation written as a separate `docs/plans/` file (not executed here) (doc-deliverable, O2)

## Execution
1. Set Status: executing, commit.
2. Paste the RED run (pre-build LOCKED ORACLE + verify all fail — container absent).
3. Phase 0 (perms, RO role, provider sign-off — STOP for owner on the LLM choice) → Phase 1
   (P3 write-path discovery → build w/ chowned workspace → compose → config → bot) top to bottom.
4. Run the LOCKED ORACLE (must pass verbatim) and the Asserting Verification Script (must end in `PASS`).
5. Write the Phase 2 relocation plan as its own file; do NOT execute it here.
6. Reviewer flips Status: done per the Acceptance Gate.
Satisfy all five gates in `docs/EXECUTOR_CONTRACT.md`; do not modify the `# LOCKED ORACLE` block;
STOP on any deviation. Never weaken a containment control (network split, cap_drop, ro mounts +
their tmpfs, the v2 resource-limit keys, RO role allowlist) to make something work — stop and
report instead.
