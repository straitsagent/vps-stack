# OpenClaw Deployment — Implementation Log

**Date:** 2026-06-27
**Plan:** `docs/plans/2026-06-27_openclaw-secure-deployment.md`
**Executor:** Deepseek V4 (opencode)
**Result:** GREEN — LOCKED ORACLE 5/5, Verify Script 6/6, bot responding @StraitsClawBot

---

## Bug 1 — psql `:'pw'` variable interpolation fails via Docker exec

**Symptom:** `ERROR: syntax error at or near ":"` when piping migration SQL through `docker exec -i psql`.
Also occurred with `docker cp` + `-f` approach.

**Root cause:** `:'pw'` colon-variable syntax is a psql interactive-mode feature; it does not work reliably when the SQL is passed through `docker exec` or piped via stdin. The colon is treated as a SQL syntax error.

**Fix:** Switched to placeholder substitution: the SQL file uses `__OPENCLAW_RO_PW__` as a token; a Python one-liner reads the template, substitutes the real password, and pipes the result to psql.

---

## Bug 2 — GID/UID 1000 already exists in node:22-slim

**Symptom:**
- `groupadd --system -g 1000 openclaw` → `GID '1000' already exists` (exit 4)
- After fixing group: `useradd -u 1000 -g 1000` → `UID 1000 is not unique` (exit 4)

**Root cause:** The `node:22-slim` image ships with a `node` user pre-created at uid=1000, gid=1000, home=/home/node.

**Fix:** Used the existing `node` user instead of creating a new `openclaw` user. Changed compose `tmpfs` paths from `/home/openclaw` to `/home/node`, then ultimately to `HOME=/workspace` (see Bug 3).

---

## Bug 3 — EACCES on `~/.openclaw/` — tmpfs hides Dockerfile permission setup

**Symptom:** After container start, logs showed:
```
Config health-state write failed: /home/node/.openclaw/logs/config-health.json:
EACCES: permission denied, mkdir '/home/node/.openclaw'
```

**Root cause:** The Dockerfile's `RUN mkdir -p /home/node/.openclaw && chown -R 1000:1000 /home/node` sets permissions in the **image layer**, but compose's `tmpfs: [/home/node]` mounts a clean tmpfs **on top of** that directory at runtime — hiding the Dockerfile's work. The tmpfs is owned by root.

**Fix:** Set `ENV HOME=/workspace` in the Dockerfile and removed `/home/node` from `tmpfs:`. The `/workspace` named volume is created at build time with `chown 1000:1000` and is NOT overlaid by tmpfs, so permissions survive. Removed `/run` from tmpfs as well (unnecessary with HOME on /workspace).

---

## Bug 4 — Gateway blocked: missing `gateway.mode`

**Symptom:**
```
Gateway start blocked: existing config is missing gateway.mode.
```

**Root cause:** The config only had `gateway.bind: "loopback"` but not `gateway.mode`. OpenClaw requires `gateway.mode=local` (or `--allow-unconfigured`) for non-onboarded setups.

**Fix:** Added `gateway.mode: "local"` to `openclaw.json`.

---

## Bug 5 — `config.json.last-good` EROFS (expected, harmless)

**Symptom:**
```
failed to promote config last-known-good backup: Error: EROFS: read-only file system,
open '/config/openclaw.json.last-good'
```

**Root cause:** OpenClaw writes a backup copy of the config file. The config directory is mounted `:ro` (by design — defense in depth). This is contained; the write fails silently on the read-only mount.

**Resolution:** No fix needed. The ro-mount is a security feature; the backup isn't critical.

---

## Bug 6 — Skills symlink failures (expected, harmless)

**Symptom:** Repeated log entries:
```
failed to create plugin skill symlink "/config/plugin-skills/browser-automation" → ...
Error: ENOENT: no such file or directory
```

**Root cause:** OpenClaw tries to create plugin skill symlinks under `/config/plugin-skills/`. The parent `/config` is a read-only bind mount. The symlink write fails.

**Resolution:** No fix needed. Feature loss: browser automation skill unavailable. Not a security issue — the ro-mount is working as intended.

---

## Bug 7 — Model `openai/gpt-5-mini` does not exist

**Symptom:**
```
FailoverError: Unknown model: openai/gpt-5-mini
Embedded agent failed before reply: Unknown model: openai/gpt-5-mini
```

**Root cause:** The model ID `gpt-5-mini` does not exist in the OpenAI API. Available models: `gpt-5.4`, `gpt-5.4-mini`, `gpt-5.3-chat-latest`, etc. No `gpt-5-mini` model has been released.

**Fix:** Switched to `gpt-4.1-mini` — which also failed (see Bug 8).

---

## Bug 8 — `openai/gpt-4.1-mini` available in API but not in OpenClaw profiles

**Symptom:**
```
FailoverError: Unknown model: openai/gpt-4.1-mini
Embedded agent failed before reply: Unknown model: openai/gpt-4.1-mini
```

**Root cause:** `gpt-4.1-mini` returns from the OpenAI `/v1/models` endpoint, and `openclaw models list` shows it as recognized. However, OpenClaw's OpenAI plugin only has **model profiles** for GPT-5.x and o1/o3/o4 families. The agent uses profiles for execution, not raw API model listing.

Running `openclaw models list --provider openai --json` confirmed: only 13 models have profiles (`gpt-5.3-chat-latest` through `o4-mini`). `gpt-4.1-mini` is absent from the profile catalog.

**Fix:** Switched to `openai/gpt-5.4-mini` — the smallest supported GPT model with an OpenClaw profile. Confirmed working.

---

## Verified artifacts

### RED run (G2)
```
error: no such object: openclaw     # (all 12 checks fail — container absent)
```

### GREEN run (G1 + G4)

**LOCKED ORACLE:** 5/5 PASS
```
O1: 1000:1000|true|false|["ALL"]     PASS
O2: Networks = 2, dind excluded       PASS
O3: No host port published            PASS
O4: openclaw_db internal: true        PASS
O5: Memory=1073741824, Pids=256       PASS
```

**Verify Script:** 6/6 PASS
```
§1 Hardening (user/ro/priv/caps)      PASS
§2 Dind unreachable (node probe)      PASS
§3 Mount audit (only ro binds)        PASS
§3b No stray host secrets in env      PASS
§4 Research readable, not writable    PASS
§5 DB privilege enforcement           PASS (3/3 sub-checks)
§6 No published port                  PASS
```

---

## Deviations from plan

1. **Config format:** Plan assumed `model.primary`/`model.baseUrl`/`tools.fs.workspaceOnly` keys. OpenClaw uses JSON5 with `agents.defaults.model.primary`, `channels.telegram.botToken`, etc. Wrote the actual OpenClaw schema.

2. **Model:** Plan proposed OpenRouter; owner chose OpenAI. Plan proposed `gpt-5-mini`; that model doesn't exist. After two iterations, landed on `gpt-5.4-mini` (the only supported "mini" model in OpenClaw's OpenAI profiles).

3. **HOME path:** Plan specified `tmpfs: [/tmp, /run, /home/openclaw]` and `user: "1000:1000"`. Actual: `HOME=/workspace` (named volume), `tmpfs: [/tmp]` only. The `node` user's home `/home/node` was overlaid by tmpfs (Bug 3).

4. **Container user:** Plan specified `container_name: openclaw` (added to plan via review Diff 1). This was correct.

5. **Network name:** Plan's oracle O4 was corrected from `openclaw_db` to `root_openclaw_db` (review Diff 2). This was correct — compose prefixes non-external networks with project name.

---

## Acceptance Gate status

13/13 complete.
- Telegram second-sender rejection: confirmed 2026-06-27 — non-owner messages to @StraitsClawBot receive no response.
- Phase 2 relocation plan: written as `docs/plans/2026-06-28_phase2-relocation.md` (draft, HIGH tier, not executed).

Plan ready for reviewer to flip `Status: executing` → `done`.
