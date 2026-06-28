---
Title: Hermes Agent (Nous Research) — contained deployment alongside OpenClaw
Date: 2026-06-28
Plan: docs/plans/2026-06-28_hermes-contained-deployment.md
Executor: opencode (mimo-v2.5-pro)
Status: done
---

## Summary

Deployed **Hermes Agent** (Nous Research) as a confined, owner-only assistant
alongside the existing OpenClaw — an A/B trial for self-improving autonomous
agent capability. Model `nousresearch/hermes-4-70b` via OpenRouter, Telegram
bot `@StraitsHermesBot`, long-polling, owner-only allowlist.

The deployment mirrors OpenClaw's security spine (non-root, read_only rootfs,
cap_drop ALL, custom internal networks, RO DB role) but adapts for Hermes's
writable state model: nested rw-over-ro scratch folders at `/research/hermes`
and `/docs/hermes`, config and `.env` mounted as `:ro` overlays on the state
volume, `terminal.backend: local` inside the hardened container.

## What was built

### Phase 0 — Prerequisites

- **`hermes_ro` DB role** — cloned from `openclaw_ro_role.sql`. 24-table SELECT
  allowlist, `statement_timeout=15s`, idempotent. Verified: SELECT
  `research_reports` → 87 rows; SELECT `key_management` → `permission denied`
  (privilege text); INSERT `watchlist_ideas` → `permission denied`.
  Password in `/root/secrets/keys.md`, temp file deleted.
- **Scratch dirs** — `/root/research/hermes` + `/root/docs/hermes`, chown
  1000:1000, 755. Added `research/hermes/` + `docs/hermes/` to `.gitignore`.
- **Env scaffold** — `/root/secrets/hermes.env` (600, gitignored): OpenRouter
  API key, Telegram bot token (from @BotFather), `HERMES_RO_DSN`.

### Phase 1 — Build + deploy

| Component | Location | Notes |
|-----------|----------|-------|
| Dockerfile | `/root/hermes/Dockerfile` | Single-stage `python:3.11-slim`, pip install `hermes-agent[messaging]` at commit `f3d8f20` |
| Config | `/root/hermes/config/config.yaml` | Model `nousresearch/hermes-4-70b`, OpenRouter provider, `terminal.backend: local`, `platform_toolsets.telegram: [hermes-telegram]` |
| Compose | `/root/docker-compose.yml` | `hermes` service + `hermes_egress`/`hermes_db` networks + `hermes_state` volume |

**Containment controls:**

| Control | Value | Oracle |
|---------|-------|--------|
| User | `1000:1000` | O1 |
| Rootfs | `read_only: true` + `/tmp` + `/run` tmpfs | O1 |
| Capabilities | `cap_drop: [ALL]`, `no-new-privileges:true` | O1 |
| Networks | `hermes_egress` (internet) + `hermes_db` (internal, `portfolio_postgres` only) — NOT `root_default` | O2, O3 |
| Limits | `mem_limit: 1g`, `pids_limit: 256` | O4 |
| Ports | none published | O5 |
| Config | `/workspace/config.yaml:ro` overlayed on state volume | O6 |
| Research | `/research:ro` parent + `/research/hermes:rw` scratch | O7 |
| Docs | `/docs:ro` parent + `/docs/hermes:rw` scratch | O8 |
| DB | `hermes_ro` role (24-table SELECT allowlist) | — |
| Telegram | owner-only allowlist (chat ID `1370319633`) | — |

**Secrets:** `/root/secrets/hermes.env` (600, gitignored): OpenRouter API key,
Telegram bot token, `HERMES_RO_DSN`. Mounted `:ro` at `/workspace/.env`.

## Key decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Dockerfile | Single-stage `python:3.11-slim` + pip | Upstream Dockerfile is complex (s6-overlay, docker-cli, host networking). Leaner image, full containment. |
| Config mount | `/workspace/config.yaml:ro` overlay on state volume | Hermes natively reads `$HERMES_HOME/config.yaml`. Overlay gives read-only integrity + writable state in the same volume. |
| Hermes mode | **Model A** — `terminal.backend: local`, no Docker socket | Container IS the sandbox. Deliberately deviates from upstream's Docker backend. No `dind`, no `docker.sock`. |
| `[messaging]` extras only | No `[all]`, no `[anthropic]`, no `[bedrock]` | Only need Telegram. Smaller install, smaller attack surface. |

## Deviation log

- **Dockerfile approach** — upstream Hermes Dockerfile is a complex multi-stage
  build with s6-overlay supervisor, host networking, and docker-cli. Wrote a
  lean single-stage Dockerfile: `python:3.11-slim` → `pip install
  hermes-agent[messaging]` at pinned commit `f3d8f20`. No s6-overlay, no
  docker-cli, no host networking.
- **Config mount path** — plan specified `/config/config.yaml` with
  `HERMES_CONFIG_PATH` env var. Hermes natively reads
  `$HERMES_HOME/config.yaml`. Mounted at `/workspace/config.yaml:ro` instead.
- **Env var name** — the env scaffold used `HERMES_BOT_TOKEN` but Hermes and
  `python-telegram-bot` expect `TELEGRAM_BOT_TOKEN`. Fixed during execution.
- **Multi-stage COPY issue** — initial multi-stage Dockerfile's
  `COPY --from=builder /opt/venv /opt/venv` didn't preserve Python binaries
  in the final stage. Switched to single-stage build.
- **No dashboard service** — upstream includes a `dashboard` service on host
  networking. Deferred per plan scope.

## Verification (G4)

### LOCKED ORACLE — 8/8 PASS

```
O1: PASS — non-root, read_only rootfs, cap_drop ALL
O2: PASS — exactly 2 networks (hermes_egress, hermes_db), no root_default
O3: PASS — hermes_db is internal
O4: PASS — mem=1g, pids=256
O5: PASS — no published ports on 0.0.0.0
O6: PASS — config.yaml mounted ro
O7: PASS — /research ro, /research/hermes rw
O8: PASS — /docs ro, /docs/hermes rw
ALL PASS
```

### Telegram connectivity

```
2026-06-28 09:42:27 INFO gateway.run: Connecting to telegram...
2026-06-28 09:42:30 INFO hermes_plugins.telegram_platform.adapter: [Telegram] Connected to Telegram (polling mode)
2026-06-28 09:42:30 INFO gateway.run: ✓ telegram connected
2026-06-28 09:42:30 INFO gateway.run: Gateway running with 1 platform(s)
```

### Container

```
STATUS: running
MOUNTS: /docs:ro /docs/hermes:rw /workspace/config.yaml:ro /workspace/.env:ro /workspace:rw /research:ro /research/hermes:rw
NETWORKS: root_hermes_db, root_hermes_egress
```

### DB role

```
hermes_ro:
  SELECT research_reports → 87 (OK)
  SELECT key_management → permission denied (BY PRIVILEGE)
  INSERT watchlist_ideas → permission denied (BY PRIVILEGE)
```

## Remaining items

- [x] `hermes_ro` DB role created and verified
- [x] Scratch dirs created, gitignored
- [x] Env file scaffolded (OpenRouter key + bot token + DSN)
- [x] Hermes Dockerfile built and deployed
- [x] Config written and mounted read-only
- [x] Compose edits (service + networks + volume + postgres network join)
- [x] LOCKED ORACLE 8/8 PASS
- [x] Telegram connected (polling, @StraitsHermesBot)
- [x] ROADMAP Part 7 added, CLAUDE.md Running Services updated
- [ ] Live A/B comparison with OpenClaw over the next week
- [ ] Dashboard service (deferred, not in scope)

## Commits

```
fbeaae9 feat(hermes): Phase 0 — DB role, scratch dirs, gitignore, env scaffold
ce5ba21 feat(hermes): Phase 1+2 — deploy + docs (8/8 LOCKED ORACLE PASS)
c7cd0db docs: ROADMAP Part 7 (Hermes) + CLAUDE.md Running Services
```
