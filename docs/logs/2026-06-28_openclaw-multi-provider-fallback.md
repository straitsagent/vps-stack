---
Title: Multi-provider LLM fallback for openclaw — resolve rate-limit issue
Date: 2026-06-28
Plan: docs/plans/2026-06-27_openclaw-multi-provider-fallback.md
Executor: opencode (mimo-v2.5-pro)
Status: done
---

## Summary

Added a 3-element `fallbacks` array to openclaw's model config so the agent
auto-escalates when `gpt-5.4-mini` hits OpenAI's Tier-1 TPM ceiling
(200,000 tokens/min) during complex research tasks.

The fallback chain: `openai/gpt-5.4-mini` (primary) → `openai/gpt-5.4`
→ `xai/grok-4.3` → `deepseek/deepseek-chat`. Each is in a different TPM
bucket, so rate-limit errors on one provider trigger an automatic failover
to the next without user intervention. OpenClaw's built-in model-fallback
logic (`model-fallback-CTRdAq5q.js`) treats `rate_limit` explicitly as a
failover-worthy error.

## What was built

### 1. API keys added to `/root/secrets/openclaw.env`

| Key | Value (truncated) | Sourced from |
|-----|-------------------|--------------|
| `XAI_API_KEY` | `xai-j2h1EQgZOStkjTQL...` | `/root/secrets/keys.md` |
| `DEEPSEEK_API_KEY` | `sk-59ec4a4c01514c15a9f...` | `/root/secrets/keys.md` |
| `OPENCLAW_STATE_DIR` | `/workspace/.openclaw` | New — prevents EROFS on `/config` mount |

File remains chmod 600 and gitignored (`secrets/` in `.gitignore`).

### 2. Fallback chain configured in `openclaw.json`

```jsonc
"agents": {
  "defaults": {
    "model": {
      "primary": "openai/gpt-5.4-mini",
      "fallbacks": [
        "openai/gpt-5.4",
        "xai/grok-4.3",
        "deepseek/deepseek-chat"
      ]
    }
  }
}
```

### 3. Deepseek custom provider configured

Added `models.providers.deepseek` — uses the bundled `openai-completions`
API transport against `https://api.deepseek.com` with `${DEEPSEEK_API_KEY}`.
Model catalog includes `deepseek-chat` and `deepseek-reasoner` (both from
the plugin's `openclaw.plugin.json`).

### 4. `OPENCLAW_STATE_DIR` env var

Prevents the gateway from trying to write lock/backup files to the read-only
`/config` mount (`EROFS: open '/config/openclaw.json.lock'`,
`EROFS: open '/config/openclaw.json.last-good'`).

### 5. `docs/OPERATIONS.md` updated

Added "OpenClaw: Multi-Provider LLM Setup" section documenting the fallback
chain, recovery path, and key management.

## Key decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Deepseek via custom provider vs plugin | Custom `models.providers` entry | Plugin install (`openclaw plugins install --pin`) failed due to read-only `/config` mount. Custom provider is self-contained in the bind-mounted config, survives rebuilds, needs no image changes. |
| Fallback model selection | `gpt-5.4` (escalation) → `grok-4.3` (cross-provider) → `deepseek-chat` (deep reasoning) | Each in a separate TPM bucket. `gpt-5.4` is same-provider escalation. `grok-4.3` has 2M context, strong at agentic. `deepseek-chat` is cheap, large context, good fallback-of-last-resort. |
| Image rebuild vs runtime config | No image rebuild | All changes are in bind-mounted files (`openclaw.json`, `openclaw.env`). Survives `--force-recreate` and image rebuild. |

## Deviation log

- **Phase C (plugin install via CLI)** failed because `/config` is mounted
  `:ro`. The CLI tried to create `/config/npm/` → `ENOENT`. A direct npm
  install to `/workspace/.openclaw/` succeeded, but the gateway's
  `reload.mode = "off"` meant the CLI couldn't restart the gateway (PID 1
  runs the foreground gateway). Resolved by configuring Deepseek as a
  **custom provider** via `models.providers.deepseek` — no plugin install
  needed, self-contained in the bind-mounted config.
- **Phase E (Dockerfile bake)** skipped — the custom provider approach
  is portable and needs no image changes.
- **`OPENCLAW_STATE_DIR`** was not in the original plan but was required to
  prevent EROFS errors on the read-only `/config` mount.

## Verification (G4)

### RED run (pre-execution)

```
O1: FAIL — no fallbacks in config
O2: FAIL — no XAI_API_KEY
O3: FAIL — no DEEPSEEK_API_KEY
O4: FAIL — no deepseek in models status
O5: FAIL — no xai/grok-4.3 or deepseek/... in fallback chain
O6: PASS — hardening (security invariant)
O7: PASS — no stray secrets (security invariant)
```

### GREEN run (post-execution)

```
O1: PASS — fallbacks include deepseek
O2: PASS — XAI_API_KEY set
O3: PASS — DEEPSEEK_API_KEY set
O4: PASS — models status shows deepseek
O5: PASS — xai/grok-4.3 and deepseek/... in chain
O6: PASS — container hardening
O7: PASS — no stray secrets
ALL PASS
```

### Verification Script (G4)

```
=== 1. Fallbacks array has deepseek ===  PASS
=== 2. XAI_API_KEY set ===                PASS
=== 3. DEEPSEEK_API_KEY set ===            PASS
=== 4. Deepseek provider loaded ===        PASS
=== 5. Fallback chain has xai + deepseek   PASS
=== 6. Container hardening ===             PASS
=== 7. No stray secrets ===                PASS
=== 8. Live verify (Telegram) ===          INFO
PASS
```

### Models status (final state)

```
Default       : openai/gpt-5.4-mini
Fallbacks (3) : openai/gpt-5.4, xai/grok-4.3, deepseek/deepseek-chat

Providers w/ OAuth/tokens:
- deepseek effective=env:sk-59ec4... | source=env: DEEPSEEK_API_KEY
- openai   effective=env:sk-proj-...  | source=env: OPENAI_API_KEY
- xai      effective=env:xai-j2h1...  | source=env: XAI_API_KEY
```

## Remaining items

- [x] Add XAI_API_KEY + DEEPSEEK_API_KEY to openclaw.env
- [x] Configure fallback chain in openclaw.json
- [x] Configure Deepseek as custom models.providers entry
- [x] Add OPENCLAW_STATE_DIR to env file
- [x] Update docs/OPERATIONS.md
- [x] RED→GREEN proven: all 5 oracle assertions that failed pre-execution now pass
- [x] LOCKED ORACLE 7/7 PASS
- [x] Verification Script ends in PASS
- [ ] Live Telegram test — user should send a complex research prompt to
  @StraitsClawBot to confirm auto-failover works end-to-end when rate-limit
  is triggered. Also monitor `docker logs openclaw | grep rate_limit` for
  decreased frequency over the next week.

## Commits

```
0bef409 plan(openclaw): set Status to executing — multi-provider fallback chain
b1bc0df feat(openclaw): multi-provider fallback chain — OpenAI / xAI / Deepseek
```
