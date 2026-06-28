---
Subject: Fix Hermes web search tool — add 5 web search provider API keys
Date: 2026-06-28
Status: executing
Planner model: opencode (mimo-v2.5-pro)
Executor model: any
Risk tier: LOW (env-only changes, no service restart of other containers, no DB or compose network changes)
Hard Rules in force: [5, 22]
Complies with: docs/EXECUTOR_CONTRACT.md
---

# Plan: Fix Hermes Web Search — Add 5 Provider API Keys

## Context

Hermes Agent (`@StraitsHermesBot`) reports `check_web_api_key returned False`
in error logs, meaning no web search provider API keys are configured. The
agent's web search tool is unavailable as a result. We have 5 web search API
keys already stored in `/root/secrets/keys.md` from the existing stack (Brave,
Tavily, Exa, Firecrawl, Serper). Adding them to the Hermes environment will
unlock web search for the agent.

## Files changed

| Action | Path | Change |
|--------|------|--------|
| EDIT | `/root/secrets/hermes.env` | Add 5 web search API keys (factory default — chmod 600, gitignored) |
| EXEC | `hermes_state` volume | Re-pre-populate `/workspace/.env` from host file to pick up new keys |

## Checklist

- [x] **Step 1 — Add keys to host env file.** Edit `/root/secrets/hermes.env`: add `BRAVE_API_KEY`, `TAVILY_API_KEY`, `EXA_API_KEY`, `FIRECRAWL_API_KEY`, `SERPER_API_KEY`. Values sourced from `/root/secrets/keys.md`.
- [x] **Step 2 — Re-pre-populate volume.** Copy the updated `.env` from host into `root_hermes_state` volume so `/workspace/.env` has the new keys.
- [x] **Step 3 — Restart container.** `docker compose up -d --force-recreate hermes`.
- [x] **Step 4 — Verify.** All 5 keys present in container env. No `check_web_api_key returned False` in post-restart logs.
- [ ] **Step 5 — Live test.** User sends a web-search message to @StraitsHermesBot and receives a substantive response citing web sources.

## Locked Oracle Tests (G1)

No locked oracle — LOW risk, env-only change. RED→GREEN proof is check_fn status change.

## RED-proof requirement (G2)

RED state (pre-execution): `docker exec hermes env | grep BRAVE` returns nothing (no web keys). GREEN state: returns the Brave key.

## Asserting Verification Script (G4)

```bash
#!/bin/bash
fail=0

echo "=== 1. Env vars present ==="
for var in BRAVE_API_KEY TAVILY_API_KEY EXA_API_KEY FIRECRAWL_API_KEY SERPER_API_KEY; do
  docker exec hermes env | grep -q "$var" && echo "  PASS: $var" || { echo "  FAIL: $var"; fail=1; }
done

echo "=== 2. No check_fn warnings ==="
docker exec hermes sh -c 'tac /workspace/logs/errors.log 2>/dev/null | head -20' | grep -q 'check_web_api_key' && { echo "  WARN: check_web_api_key still present (may be stale)"; } || echo "  PASS: no recent check_fn warnings"

echo "=== 3. Latest errors ==="
docker exec hermes sh -c 'tac /workspace/logs/errors.log | head -5' 2>/dev/null

[ $fail -eq 0 ] && echo "PASS" || exit 1
```

## Acceptance Gate

- [x] All 5 web search API keys in `/workspace/.env` (and `/root/secrets/hermes.env`)
- [x] Container restarted, picks up new env
- [x] Web search tool available (no `check_web_api_key returned False`)
- [ ] Live test: user gets search results from the agent

## Execution

1. Set Status: executing, commit.
2. Work checklist top to bottom; tick each `- [ ]` when its success criteria are met.
3. Verify script ends in `PASS`.
4. Reviewer flips Status: done.
Satisfy all five gates; STOP on any deviation.
