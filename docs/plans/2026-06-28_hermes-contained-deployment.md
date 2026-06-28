---
Subject: Deploy Hermes Agent (Nous Research) as a contained, owner-only assistant on the VPS
Date: 2026-06-28
Status: executing
Planner model: claude-sonnet-4-6
Executor model: any (Claude Code | opencode/Deepseek)
Risk tier: HIGH (new internet-facing, self-improving LLM agent with shell + write capability; co-hosted with the live portfolio stack, Postgres, and secrets)
Hard Rules in force: [1, 5, 6, 7, 10, 12, 13, 20, 21, 22]
Complies with: docs/EXECUTOR_CONTRACT.md
Template: docs/plans/archive/2026-06-27_openclaw-secure-deployment.md (security pattern reused verbatim where possible)
Files to read before coding: CLAUDE.md, docs/EXECUTOR_CONTRACT.md, /root/docker-compose.yml, /root/openclaw/Dockerfile, /root/openclaw/config/openclaw.json, /root/portfolio/openclaw_ro_role.sql
---

# Plan: Hermes Agent — contained, owner-only deployment (alongside OpenClaw)

## Context

The owner wants to trial **Hermes Agent** (Nous Research) — reportedly stronger than the live OpenClaw —
"maximising capability while balancing security." Hermes is a self-improving autonomous agent
(Python 3.11 + `uv`, Docker/compose in-repo). Its differentiator is a **closed learning loop**:
agent-curated memory, autonomous skill creation, cross-session recall (FTS5 + LLM summarization). It
supports pluggable terminal backends and model providers; models need ≥64k context.

**Central tension.** OpenClaw was built *read-only and disposable* (treat as always-compromised; worst
case "read research the owner already owns + burn the key"). Hermes only delivers value if it can
**write** (memory/skills/workspace) and **execute commands**. We keep OpenClaw's *containment*
philosophy but adapt it to a writable-but-confined agent, using Hermes's `terminal.backend` as the
safety lever. A hijacked Hermes must be able to do nothing worse than: read the research + docs corpora,
read the DB (RO), run commands **inside its own container**, write to its **own scratch subfolders +
state volume**, and spend API tokens — nothing else (no host, no secrets, no privileged Docker daemon,
no Windmill, no overwrite of existing research/docs/DB). This also serves the owner's near-term goal: a
capable assistant that **surfaces the closed-loop outputs** (`watchlist_ideas`, `portfolio_scores`,
candidate evals, research `.md`) over Telegram — lowering dashboard priority.

## Decisions locked (owner, 2026-06-28)

| Decision | Choice |
|---|---|
| Provider | **OpenRouter** (no Anthropic — Hard Rule). Confined; owner controls data. |
| Model | **`nousresearch/hermes-4-70b`** (131k ctx) — signed off. |
| Posture | **Model A — confined sandbox.** `terminal.backend: local`; the hardened container IS the sandbox; OFF the dind/host-Docker network. |
| Rollout | **Run alongside OpenClaw** (A/B trial; independent bot, DB role, networks). |
| Data — read | `/research:ro` **and** `/docs:ro` (owner added `/docs`; note OpenClaw's `/docs` was revoked — Hermes gets it back deliberately, for capability). |
| Data — write | Writable scratch **`/research/hermes/`** and **`/docs/hermes/`** only; rest of both trees read-only. |
| Tools | Web search ON; **browser deferred**; SSRF protections ON. |

## Architecture (mirror OpenClaw; adapt for a writable agent)

### Containment controls

| Control | Value |
|---|---|
| User | `1000:1000` non-root |
| Capabilities | `cap_drop: [ALL]`, `security_opt: [no-new-privileges:true]` |
| Rootfs | `read_only: true` + writable named volume `hermes_state` at `HOME` (`~/.hermes` memory/skills) + `tmpfs /tmp`. Exact write paths verified at execution. |
| Limits | `mem_limit: 1g`, `pids_limit: 256` (confirm VPS free RAM — OpenClaw already holds 1g) |
| Networks | `hermes_egress` (internet) + `hermes_db` (`internal: true`, shared only with `portfolio_postgres`); **NOT `root_default`** (non-negotiable — no dind, no Windmill, no host docker.sock) |
| Host port | none, or loopback-only `127.0.0.1` if Hermes exposes a control/TUI port |
| Research | `/research:ro` (parent) + `/research/hermes:rw` (scratch) |
| Docs | `/docs:ro` (parent) + `/docs/hermes:rw` (scratch) |
| Config | `/config:ro` (read-only) — **see "Config integrity"** |
| DB | new `hermes_ro` role, same 19-table allowlist as `openclaw_ro`, `statement_timeout=15s` |
| Telegram | new BotFather bot; owner-only allowlist (chat id `1370319633`) |
| Secrets | `/root/secrets/hermes.env` (600, gitignored): OpenRouter key, bot token, `HERMES_RO_DSN` |

### Writable scratch subfolders — design + security notes

The owner wants Hermes to persist outputs alongside the corpora, navigable in the same trees. Implement
with **nested rw-over-ro bind mounts**: mount the whole tree `:ro`, then overlay just the `hermes/`
subpath `:rw`:

```yaml
- /root/research:/research:ro
- /root/research/hermes:/research/hermes      # rw scratch (overlays the :ro parent)
- /root/docs:/docs:ro
- /root/docs/hermes:/docs/hermes              # rw scratch
```

- Host dirs `/root/research/hermes` and `/root/docs/hermes` created first, **chown 1000:1000** so the
  non-root container user can write.
- **What this preserves:** Hermes **cannot modify or delete any existing** research/docs file (those stay
  under the `:ro` parent). It can only **add** files under its own `hermes/` subfolder.
- **Residual risk (accepted, documented):** a prompt-injected Hermes could *plant* a file in
  `/research/hermes/`, which OpenClaw and other readers of `/root/research` would also see — a
  cross-agent indirect-injection vector. Contained to the scratch subfolder; existing corpus untouched.
- **gitignore `research/hermes/` + `docs/hermes/`** so agent-generated (possibly injected) content is
  **not** committed into the repo. The daily Drive backup still captures uncommitted files, so Hermes's
  accumulated output is preserved without polluting git history. (Owner can flip this later if they want
  Hermes's notes version-controlled.)
- **Verify the nested-mount behavior at execution** (Docker applies child mounts over parents by
  destination depth) with a touch test — do not assume; assert (oracle O7/O8 below).

### Hermes-specific hardening

- **`approvals.mode: smart`** (never `off`/YOLO); bump `approvals.timeout` (default 60s) so owner has
  time to confirm via Telegram. `cron_mode: deny`.
- **Tirith command scanning + context-file injection scanning ON.**
- **SSRF ON** (`allow_private_urls: false`) — Hermes is an autonomous web-reader on a box with internal
  services; blocks reaching Postgres/Windmill/metadata via fetched URLs.
- **`terminal.docker_forward_env` minimal**; no blanket env passthrough.
- **No host Docker socket mounted anywhere.**

### Config integrity (key catch)

Hermes reads `~/.hermes/config.yaml`, which on our setup would land on the *writable* state volume — a
prompt-injected Hermes could rewrite its own `approvals.mode: off` and disable safety. **Mount our
config read-only and point Hermes at it** (`/config/config.yaml`, via `--config`/`HERMES_CONFIG` —
exact override mechanism verified at execution). Same `:ro` discipline as OpenClaw's config mount.

### Upstream-default deviation (guardrail)

Hermes's official Docker guide configures `terminal.backend: docker` with a **docker socket / daemon**
sandbox. We deliberately do **NOT** follow that — Model A uses `terminal.backend: local`, mounts no
socket, the hardened container itself is the boundary. Executor MUST NOT mount `/var/run/docker.sock`
or join `root_default` to reach `dind`.

## Checklist

### Phase 0 — Prerequisites
- [x] **P0.1 — `hermes_ro` DB role.** Created `/root/portfolio/hermes_ro_role.sql`. Applied idempotently. Verified: SELECT `research_reports` → 87 rows; SELECT `key_management` → `permission denied for table key_management` (privilege text); INSERT `watchlist_ideas` → `permission denied for table watchlist_ideas` (privilege text). Password in `keys.md`, temp file deleted.
- [x] **P0.2 — OpenRouter key + bot.** OpenRouter key in `hermes.env`. Bot created at @StraitsHermesBot, token `8648643255:...`. Added to `keys.md`.
- [x] **P0.3 — Scratch dirs + gitignore.** Directories created at `/root/research/hermes` and `/root/docs/hermes`, chown 1000:1000. `research/hermes/` and `docs/hermes/` added to `.gitignore`. Verified with `git check-ignore`.
- [x] **P0.4 — Model** = `nousresearch/hermes-4-70b` (locked; Hard Rule 6/10).

### Phase 1 — Build + deploy
- [ ] **P1.1 — Dockerfile.** `/root/hermes/Dockerfile` — install Hermes from upstream repo at a
  **pinned tag/commit** (prefer the repo's Dockerfile over `curl|bash`), `postgresql-client` for DB
  queries, non-root `1000:1000`, `HOME=/workspace` (or verified Hermes state dir) on the writable
  volume. Verify package/runtime + state path against the pinned upstream.
- [ ] **P1.2 — Config.** `/root/hermes/config/config.yaml` — `terminal.backend: local`,
  `approvals.mode: smart` (raised timeout), SSRF on, web search on, browser off, Telegram owner-only
  allowlist, model `openrouter`/`nousresearch/hermes-4-70b` with OpenRouter base URL. Mounted `:ro`.
- [ ] **P1.3 — Compose.** Add `hermes` service (mounts: `/research:ro`, `/research/hermes:rw`,
  `/docs:ro`, `/docs/hermes:rw`, `/config:ro`, `hermes_state:/workspace`) + `hermes_egress`/`hermes_db`
  networks to `/root/docker-compose.yml`; attach `portfolio_postgres` to `hermes_db`. Build + `up -d`.
- [ ] **P1.4 — RED→GREEN.** Run LOCKED ORACLE before the container exists (RED, all fail), then after
  (GREEN, all pass).

### Phase 2 — Docs
- [ ] **P2.1** — ROADMAP Part 6 (second sandboxed agent, A/B trial; note `/docs` read + scratch
  folders), CLAUDE.md Running Services row, implementation log (`docs/logs/`, Hard Rule 23).

## Locked Oracle Tests (G1)
```bash
# LOCKED ORACLE — copy verbatim, do not modify assertions. (H = hermes container)
H=hermes
# O1: non-root, read-only rootfs, unprivileged, all caps dropped
test "$(docker inspect $H --format '{{.Config.User}}|{{.HostConfig.ReadonlyRootfs}}|{{.HostConfig.Privileged}}|{{json .HostConfig.CapDrop}}')" = '1000:1000|true|false|["ALL"]'
# O2: on exactly hermes_egress + hermes_db, NOT root_default
test "$(docker inspect $H --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{"\n"}}{{end}}' | grep -vc '^$')" = "2"
docker inspect $H --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{"\n"}}{{end}}' | grep -q 'hermes_egress'
docker inspect $H --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{"\n"}}{{end}}' | grep -q 'hermes_db'
! docker inspect $H --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{"\n"}}{{end}}' | grep -q 'root_default'
# O3: hermes_db is internal (no egress)
test "$(docker network inspect root_hermes_db --format '{{.Internal}}')" = "true"
# O4: resource limits set
test "$(docker inspect $H --format '{{.HostConfig.Memory}}')" = "1073741824"
test "$(docker inspect $H --format '{{.HostConfig.PidsLimit}}')" = "256"
# O5: any published port is loopback-only (no 0.0.0.0)
! docker inspect $H --format '{{json .HostConfig.PortBindings}}' | grep -q '0.0.0.0'
# O6: config mounted read-only (integrity — agent can't flip approvals.mode to off)
docker inspect $H --format '{{range .Mounts}}{{.Destination}}:{{.RW}} {{end}}' | grep -Eq '/config:false'
# O7: research parent read-only, /research/hermes writable
docker exec $H sh -c 'touch /research/__ro_probe 2>/dev/null' && exit 1 || true
docker exec $H sh -c 'touch /research/hermes/__rw_probe && rm /research/hermes/__rw_probe'
# O8: docs parent read-only, /docs/hermes writable
docker exec $H sh -c 'touch /docs/__ro_probe 2>/dev/null' && exit 1 || true
docker exec $H sh -c 'touch /docs/hermes/__rw_probe && rm /docs/hermes/__rw_probe'
```

## RED-proof requirement (G2)
RED = pre-deploy: `hermes` container absent → every O-assertion fails. Paste that run, then deploy and
paste the GREEN run (all pass).

## Asserting Verification Script (G4)
```bash
#!/bin/bash
fail=0; H=hermes
echo "=== 1. hardening (non-root, ro rootfs, caps) ==="
docker inspect $H --format '{{.Config.User}} ro={{.HostConfig.ReadonlyRootfs}} priv={{.HostConfig.Privileged}}' | grep -q "1000:1000 ro=true priv=false" && echo PASS || { echo FAIL; fail=1; }
echo "=== 2. cannot reach dind (escape vector) ==="
docker exec $H sh -c 'node -e "require(\"net\").createConnection({host:\"dind\",port:2375},()=>process.exit(0)).on(\"error\",()=>process.exit(1))"' 2>/dev/null && { echo "FAIL: dind reachable"; fail=1; } || echo "PASS: dind unreachable"
echo "=== 3. no host/secret leak ==="
docker exec $H sh -c 'ls /root 2>/dev/null; env | grep -iE "PORTFOLIO_DB_PASSWORD|WM_TOKEN|smtp"' | grep -q . && { echo "FAIL"; fail=1; } || echo "PASS"
echo "=== 4. research/docs parents read-only; hermes scratch writable ==="
docker exec $H sh -c 'touch /research/x 2>/dev/null' && { echo "FAIL: research writable"; fail=1; } || echo "PASS: /research ro"
docker exec $H sh -c 'touch /docs/x 2>/dev/null' && { echo "FAIL: docs writable"; fail=1; } || echo "PASS: /docs ro"
docker exec $H sh -c 'touch /research/hermes/x && rm /research/hermes/x' && echo "PASS: /research/hermes rw" || { echo "FAIL: scratch not writable"; fail=1; }
docker exec $H sh -c 'touch /docs/hermes/x && rm /docs/hermes/x' && echo "PASS: /docs/hermes rw" || { echo "FAIL: scratch not writable"; fail=1; }
echo "=== 5. DB role RO + scoped ==="
docker exec $H sh -c 'psql "$HERMES_RO_DSN" -tAc "SELECT count(*) FROM research_reports" >/dev/null 2>&1 && ! psql "$HERMES_RO_DSN" -tAc "SELECT 1 FROM key_management" 2>/dev/null && psql "$HERMES_RO_DSN" -tAc "INSERT INTO watchlist_ideas(ticker,source) VALUES (NULL,NULL)" 2>&1 | grep -q "permission denied"' && echo "PASS" || { echo "verify privilege-denial text manually"; }
echo "=== 6. config read-only (approvals integrity) ==="
docker exec $H sh -c 'touch /config/x 2>/dev/null' && { echo "FAIL: config writable"; fail=1; } || echo "PASS"
echo "=== 7. SSRF blocks private URL (manual) ==="
echo "  Ask Hermes to fetch http://portfolio_postgres:5432 or 169.254.169.254; confirm REFUSED."
echo "=== 8. Telegram owner-only (manual) ==="
echo "  Owner msg works; second-sender IGNORED."
[ $fail -eq 0 ] && echo "PASS" || exit 1
```

## Acceptance Gate
- [ ] `hermes_ro` role: SELECT allowlisted tables, denied (privilege text) on `key_management` + INSERT
- [ ] OpenRouter key + dedicated bot token + `HERMES_RO_DSN` in `/root/secrets/hermes.env` (600, gitignored)
- [ ] Scratch dirs created + chown 1000:1000; `research/hermes/` + `docs/hermes/` gitignored
- [ ] Model = `nousresearch/hermes-4-70b`
- [ ] Container: non-root, read-only rootfs, cap_drop ALL, no-new-privileges, mem/pids limits
- [ ] Networks: `hermes_egress`+`hermes_db` only; dind + Windmill unreachable (verify §2)
- [ ] `/research` + `/docs` parents read-only; only `/research/hermes` + `/docs/hermes` + state volume writable (verify §4, oracle O7/O8)
- [ ] `approvals.mode: smart`, SSRF on, browser off; config read-only so mode can't be flipped (verify §6)
- [ ] Upstream socket/dind step NOT applied; no `/var/run/docker.sock` mount anywhere
- [ ] OpenClaw still live (coexistence) — no OpenClaw change
- [ ] RED run then GREEN run pasted; LOCKED ORACLE passes verbatim; verify script ends in `PASS`
- [ ] Telegram owner-only confirmed (rejects second sender)
- [ ] Docs updated (ROADMAP, CLAUDE.md) + implementation log written (Hard Rule 23)

## Execution
1. Set Status: executing, commit.
2. Work Phase 0 → 1 → 2 top to bottom; tick each `- [ ]` when its success criteria are met.
3. Paste RED run, then GREEN run. Run LOCKED ORACLE (verbatim) + the Asserting Verification Script (ends `PASS`).
4. Set Status: done (reviewer) per the Acceptance Gate.
Satisfy all five EXECUTOR_CONTRACT gates; do not modify the `# LOCKED ORACLE` block; never `wmill sync push`.
**Never weaken a containment control** (network split, cap_drop, ro mounts, read-only config, RO role
allowlist, scratch-folder scoping, no docker.sock) to make something work — STOP and report instead.
Do not redesign; if the plan is ambiguous or wrong, stop and report.

---

## Deviation log

- **Dockerfile approach** — upstream Hermes Dockerfile is a complex multi-stage
  build with s6-overlay, host networking, and docker-cli. Wrote a lean
  single-stage Dockerfile from scratch: `python:3.11-slim` → pip install
  `hermes-agent[messaging]` at pinned commit `f3d8f20`. Simpler, no s6-overlay,
  no docker-cli, no host networking.
- **Config mount** — plan specified `/config/config.yaml` with `HERMES_CONFIG_PATH`
  env var. Hermes natively reads `$HERMES_HOME/config.yaml`. Mounted config at
  `/workspace/config.yaml:ro` overlaid on the writable state volume. Same for
  `.env` at `/workspace/.env:ro`.
- **Env var name** — scaffold used `HERMES_BOT_TOKEN` but Hermes/`python-telegram-bot`
  expect `TELEGRAM_BOT_TOKEN`. Fixed during execution.
- **Multi-stage build** — initial multi-stage Dockerfile's COPY from builder
  didn't preserve files in the final stage. Switched to single-stage.
- **No supporting services** — upstream includes a `dashboard` service on host
  networking. Deferred per plan scope.
