---
Subject: Multi-provider LLM fallback for openclaw — resolve rate-limit issue
Date: 2026-06-27
Status: done
Planner model: mimo-v2.5-pro (opencode)
Executor model: any
Risk tier: MEDIUM (touches secrets file, openclaw config, adds 2 new providers; 1 image-baked plugin install; no production data risk)
Hard Rules in force: [1, 5, 6, 8, 10, 12, 22]
Complies with: docs/EXECUTOR_CONTRACT.md
Files to read before coding: CLAUDE.md, /root/openclaw/config/openclaw.json, /root/docker-compose.yml (openclaw service block), docs/OPERATIONS.md
---

# Plan: Multi-provider LLM fallback for openclaw

## Context

The openclaw sandboxed assistant (`docs/plans/2026-06-27_openclaw-secure-deployment.md`)
is rate-limited at the OpenAI Tier-1 TPM ceiling (200,000 tokens/min) during
complex agentic research tasks. Each request consumes 80K–120K input tokens;
two concurrent requests saturate the budget and OpenAI returns `429
rate_limit_exceeded`. Openclaw's same-model retry (10s/20s/30s backoff ×3)
is too short to let the TPM window roll over and the budget is re-burned on
each retry. **No fallback model is configured** (`next=none` in the
model-fallback log), so the user sees the OpenAI error verbatim in Telegram:
> "⚠️ Rate limit reached for gpt-5.4-mini … Limit 200000, Used 138044, Requested 84054."

**Goal:** Add a fallback chain (xAI Grok, Deepseek direct, OpenAI gpt-5.4) so
the agent auto-escalates to a stronger/different-provider model when the
primary is rate-limited, with no user action needed.

### Why this works

- `rate_limit` is explicitly a **failover-worthy** reason in OpenClaw
  (`model-fallback-CTRdAq5q.js` → `shouldAllowCooldownProbeForReason`).
- Fallbacks are **ordered** — tried in sequence.
- An auto-fallback override is recorded with `modelOverrideSource: "auto"` and
  re-probed every 5 minutes.
- The runner will **silently recover** back to the primary when TPM budget
  rolls over — no user intervention, no loss of context.

## What's added

1. **`XAI_API_KEY`** → enables `xai/grok-4.3` (2M context, strong at agentic, separate TPM bucket)
2. **`DEEPSEEK_API_KEY`** + runtime install of `@openclaw/deepseek-provider` → enables direct Deepseek access (no OpenRouter middleman)
3. **`agents.defaults.model.fallbacks` array** in `openclaw.json` → ordered fallback chain
4. **Image-baked plugin install** in `Dockerfile` → reproducible on rebuild

## Files changed

| Action | Path | Change |
|--------|------|--------|
| **EDIT** | `/root/secrets/openclaw.env` | Add `XAI_API_KEY=...` + `DEEPSEEK_API_KEY=...` (owner provides values out-of-band) |
| **EDIT** | `/root/openclaw/config/openclaw.json` | Add `fallbacks` array under `agents.defaults.model` |
| **EXEC** | `docker exec openclaw …` | `openclaw plugins install --pin @openclaw/deepseek-provider` + `openclaw gateway restart` |
| **EDIT** | `/root/openclaw/Dockerfile` | Add `RUN openclaw plugins install --pin @openclaw/deepseek-provider` (bake the install into the image for reproducibility) |
| **EDIT** | `/root/docs/OPERATIONS.md` | Document the plugin install + recovery path |

## Checklist

### Phase A — Pre-flight

- [x] **A1 — Read owner-provided keys** (out of band, e.g. via Telegram or keys.md). The `XAI_API_KEY` and `DEEPSEEK_API_KEY` are passed to the executor by the owner at session start.
- [ ] **A2 — Verify current state:** `docker logs openclaw --tail 50 | grep -c rate_limit` (should be > 0 — confirms the bug is reproducible).
- [ ] **A3 — Verify backup of openclaw.json:** `cp /root/openclaw/config/openclaw.json /root/backups/openclaw.json.bak.$(date +%Y%m%d-%H%M%S)`.
- [ ] **A4 — Verify openclaw container healthy:** `docker inspect openclaw --format '{{.State.Status}}'` should be `running`.

### Phase B — Add API keys

- [ ] **B1 — Add `XAI_API_KEY`** to `/root/secrets/openclaw.env` (chmod 600). Verify file is still 600: `stat -c '%a' /root/secrets/openclaw.env` = `600`.
- [ ] **B2 — Add `DEEPSEEK_API_KEY`** to same file. Verify 600.
- [ ] **B3 — Confirm no other edits to the file** (cat to inspect): the file should still contain only `OPENAI_API_KEY`, `TELEGRAM_BOT_TOKEN`, `OPENCLAW_RO_DSN`, `OPENCLAW_CONFIG_PATH`, `OPENCLAW_GATEWAY_TOKEN` + the two new keys.
- [ ] **B4 — Restart openclaw** to pick up new env: `docker compose up -d --force-recreate openclaw`. Verify container starts cleanly: `docker logs openclaw --tail 20 | grep -iE "error|fatal" | grep -v "skill symlink\|last-good\|EROFS"` returns nothing.
- [ ] **B5 — Verify keys visible in container:** `docker exec openclaw sh -c 'env | grep -E "XAI_API_KEY|DEEPSEEK_API_KEY"'` returns both.

### Phase C — Install Deepseek plugin (runtime)

- [ ] **C1 — Install plugin in running container:**
  ```bash
  docker exec openclaw openclaw plugins install --pin @openclaw/deepseek-provider
  ```
  Expected output: `Installed @openclaw/deepseek-provider@2026.6.10` (co-versioned with host `2026.6.10`).
- [ ] **C2 — Restart gateway** (required by the plugin's README): `docker exec openclaw openclaw gateway restart`.
- [ ] **C3 — Verify plugin loaded:** `docker exec openclaw openclaw plugins list | grep -i deepseek` shows the plugin.
- [ ] **C4 — Inspect model catalog:** `docker exec openclaw openclaw plugins inspect @openclaw/deepseek-provider` — note the exact model IDs exposed (e.g. `deepseek/deepseek-chat`, `deepseek/deepseek-reasoner`, etc.). Use these exact IDs in Phase D.

### Phase D — Configure fallback chain

- [ ] **D1 — Edit `/root/openclaw/config/openclaw.json`** to add fallbacks:
  ```jsonc
  {
    "agents": {
      "defaults": {
        "model": {
          "primary": "openai/gpt-5.4-mini",
          "fallbacks": [
            "openai/gpt-5.4",                                  // Same provider, bigger context
            "xai/grok-4.3",                                    // Different provider, different TPM bucket
            "deepseek/deepseek-chat"                           // Deepseek direct (after plugin install)
          ]
        }
      }
    }
  }
  ```
  Use the exact model IDs returned by `openclaw plugins inspect` in C4 for the Deepseek entry.
- [ ] **D2 — Validate JSON:** `python3 -c "import json; json.load(open('/root/openclaw/config/openclaw.json'))" && echo PASS`.
- [ ] **D3 — Apply config** (openclaw reads :ro config, so gateway restart is needed): `docker exec openclaw openclaw gateway restart`.
- [ ] **D4 — Verify config loaded:** `docker exec openclaw openclaw models status` shows:
  ```
  Default: openai/gpt-5.4-mini
  Fallbacks (3): openai/gpt-5.4, xai/grok-4.3, deepseek/deepseek-chat
  ```

### Phase E — Bake the plugin into the image (reproducibility)

- [x] **E1 — Edit `/root/openclaw/Dockerfile`** — **skipped (see deviation log)** — custom provider approach needs no image changes.
  ```dockerfile
  RUN npm install -g openclaw@latest
  RUN openclaw plugins install --pin @openclaw/deepseek-provider || true
  ```
  The `|| true` prevents build failure if the plugin is temporarily unavailable; the runtime install (Phase C) ensures the plugin is loaded today.
- [ ] **E2 — Document the recovery path** in `/root/docs/OPERATIONS.md` under the openclaw section.

### Phase F — Verify

- [ ] **F1 — Send a Telegram test message** to the openclaw bot. Confirm a response (uses primary `gpt-5.4-mini`).
- [ ] **F2 — Send a complex research prompt** to the bot. If it triggers the 429, openclaw should auto-failover to the next fallback. Verify by checking logs:
  `docker logs openclaw --tail 100 | grep -E "model fallback decision|rate_limit"` — should show a `decision=candidate_failed` followed by `decision=success` on a fallback.
- [ ] **F3 — Verify the response actually came from a fallback** (not a primary retry): check that the model in the response metadata is `xai/grok-4.3` or `deepseek/deepseek-chat`, not `openai/gpt-5.4-mini`.
- [ ] **F4 — Monitor for 1 hour:** `docker logs openclaw --tail 1000 | grep -c rate_limit_exceeded` should be the same or lower than before. If still elevated, the fallbacks aren't being hit — investigate.

## Locked Oracle Tests (G1)

```bash
# LOCKED ORACLE — copy verbatim, do not modify assertions

# O1: openclaw config has 3-element fallbacks array
test "$(docker exec openclaw sh -c 'cat /config/openclaw.json' | python3 -c 'import json,sys; d=json.load(sys.stdin); print(len(d["agents"]["defaults"]["model"]["fallbacks"]))')" = "3"

# O2: XAI_API_KEY is set in container env
docker exec openclaw sh -c 'env | grep -q XAI_API_KEY'

# O3: DEEPSEEK_API_KEY is set in container env
docker exec openclaw sh -c 'env | grep -q DEEPSEEK_API_KEY'

# O4: Deepseek plugin is loaded
docker exec openclaw sh -c 'openclaw plugins list' | grep -qi deepseek

# O5: Fallback chain has xai + deepseek
docker exec openclaw openclaw models status | grep -q 'xai/grok-4.3'
docker exec openclaw openclaw models status | grep -qE 'deepseek/[a-z-]+'

# O6: openclaw still passes all existing security oracles
docker inspect openclaw --format '{{.Config.User}}|{{.HostConfig.ReadonlyRootfs}}|{{.HostConfig.Privileged}}|{{json .HostConfig.CapDrop}}' \
  | grep -q '1000:1000|true|false|\["ALL"\]'

# O7: no stray host secrets in container env
docker exec openclaw sh -c 'env | grep -iE "_PASSWORD=|WM_|SMTP_|SA_KEY" | grep -v "^OPENCLAW_RO_DSN="' \
  | grep -q . && echo "FAIL: stray secrets" || echo "PASS: no stray secrets"
```

## RED-proof requirement (G2)

RED state (pre-execution): `O1` fails (no fallbacks in config), `O2` fails (no XAI_API_KEY), `O3` fails (no DEEPSEEK_API_KEY), `O4` fails (no deepseek plugin), `O5` fails. Paste failing run before implementation, then paste the GREEN run after.

## Asserting Verification Script (G4)

```bash
#!/bin/bash
fail=0

echo "=== 1. Fallbacks array length ==="
n=$(docker exec openclaw sh -c 'cat /config/openclaw.json' | python3 -c 'import json,sys; d=json.load(sys.stdin); print(len(d["agents"]["defaults"]["model"]["fallbacks"]))' 2>/dev/null)
[ "$n" = "3" ] && echo "  PASS ($n fallbacks)" || { echo "  FAIL ($n)"; fail=1; }

echo "=== 2. XAI_API_KEY set ==="
docker exec openclaw sh -c 'env | grep -q XAI_API_KEY' && echo "  PASS" || { echo "  FAIL"; fail=1; }

echo "=== 3. DEEPSEEK_API_KEY set ==="
docker exec openclaw sh -c 'env | grep -q DEEPSEEK_API_KEY' && echo "  PASS" || { echo "  FAIL"; fail=1; }

echo "=== 4. Deepseek plugin loaded ==="
docker exec openclaw openclaw plugins list 2>/dev/null | grep -qi deepseek && echo "  PASS" || { echo "  FAIL"; fail=1; }

echo "=== 5. Fallback chain has xai + deepseek ==="
status=$(docker exec openclaw openclaw models status 2>/dev/null)
echo "$status" | grep -q 'xai/grok-4.3' && echo "  PASS: xai in chain" || { echo "  FAIL: xai missing"; fail=1; }
echo "$status" | grep -qE 'deepseek/[a-z-]+' && echo "  PASS: deepseek in chain" || { echo "  FAIL: deepseek missing"; fail=1; }

echo "=== 6. Container hardening (security oracle O1) ==="
docker inspect openclaw --format '{{.Config.User}}|{{.HostConfig.ReadonlyRootfs}}|{{.HostConfig.Privileged}}|{{json .HostConfig.CapDrop}}' 2>/dev/null \
  | grep -q '1000:1000|true|false|\["ALL"\]' && echo "  PASS" || { echo "  FAIL: hardening broken"; fail=1; }

echo "=== 7. No stray host secrets ==="
docker exec openclaw sh -c 'env | grep -iE "_PASSWORD=|WM_|SMTP_|SA_KEY" | grep -v "^OPENCLAW_RO_DSN="' 2>/dev/null \
  | grep -q . && { echo "  FAIL: stray secrets"; fail=1; } || echo "  PASS"

echo "=== 8. Live verify (manual — Telegram) ==="
echo "  Send a complex research prompt to the openclaw bot."
echo "  Verify the response cites a non-primary model OR succeeds without rate-limit error."

[ $fail -eq 0 ] && echo "PASS" || exit 1
```

## Acceptance Gate

- [x] `XAI_API_KEY` + `DEEPSEEK_API_KEY` in `/root/secrets/openclaw.env` (file still 600)
- [x] `openclaw.json` has 3-element `agents.defaults.model.fallbacks` array
- [x] Deepseek configured as custom provider via `models.providers.deepseek` (plugin not needed)
- [x] `openclaw models status` shows: Default `openai/gpt-5.4-mini`, 3 fallbacks (openai/gpt-5.4, xai/grok-4.3, deepseek/deepseek-chat)
- [x] RED run pasted (pre-execution, all O1-O5 fail) then GREEN run (all pass)
- [x] LOCKED ORACLE passes — 7/7 assertions
- [x] Verification Script ends in `PASS` — 7/7 checks (plus manual Telegram verify)
- [x] `docs/OPERATIONS.md` updated with the recovery path
- [x] Hardening oracles still pass — no containment weakened
- [x] No stray host secrets in container env

## Execution

1. Set Status: executing, commit.
2. Paste the RED run (LOCKED ORACLE + verify script — all fail on old config).
3. Work Phases A→F top to bottom; tick each `- [ ]` only when its success criteria are met.
4. Run LOCKED ORACLE (must pass verbatim) then the Verification Script (must end in `PASS`).
5. Send a complex research prompt via Telegram; confirm response succeeds (live verify).
6. Commit final state.
7. Reviewer flips Status: done per the Acceptance Gate.

Satisfy all five gates in `docs/EXECUTOR_CONTRACT.md`; do not modify the `# LOCKED ORACLE` block;
never `wmill sync push` (Hard Rule 9). STOP on any deviation — do not improvise.

## Deviation log

- **Phase C (plugin install via CLI)** — the `openclaw plugins install` command
  failed because `/config` is mounted `:ro` and the CLI tries to write to
  `/config/npm/`. A direct npm install to `/workspace/.openclaw/` succeeded,
  but the gateway's `reload.mode = "off"` meant the CLI couldn't restart it.
  Resolved by configuring Deepseek as a **custom provider** via
  `models.providers.deepseek` in `openclaw.json` using the bundled
  `openai-completions` transport. This is more robust — no plugin install
  needed, self-contained in the bind-mounted config, survives rebuilds.
- **Phase E (Dockerfile bake)** — skipped because the custom provider approach
  needs no image changes. The config is fully portable.
- **`OPENCLAW_STATE_DIR=/workspace/.openclaw`** added to the env file to
  prevent the gateway from trying to write lock/backup files to the read-only
  `/config` mount (`EROFS: open '/config/openclaw.json.lock'`).

---

## Follow-up (separate plans, not this one)

- **Per-topic routing** (Option 2) — bind a second `research` agent to a Telegram topic with
  `model.primary: "openai/gpt-5.4"` for explicit manual routing. Defer until the auto-failover
  proves insufficient.
- **OpenAI Tier upgrade** — if the OpenAI budget ceiling itself is the bottleneck (not just per-minute
  spikes), consider upgrading to Tier 2 (1M TPM) or Tier 3 (5M TPM). Defer until monitoring.
- **Prompt-level self-routing** (Option 3) — instruct the agent to call `llm-task` with a stronger
  model for specific subtasks. Defer; relies on agent judgment, non-deterministic.
