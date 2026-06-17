# Implementation Log — Telegram Agent (W1 Core Service)
**Date:** 2026-06-10 (extended single session)
**Commits:** reconstructed from session transcripts
**Files changed:** `agent/main.py`, `agent/telegram.py`, `agent/intent_classifier.py`, `agent/tool_registry.py`, `agent/windmill_dispatch.py`, `agent/db.py`, `agent/Dockerfile`, `agent/requirements.txt`, `agent/tests/`, `/opt/n8n/Caddyfile`, `docker-compose.yml`, `CLAUDE.md`, `docs/ROADMAP.md`, `docs/WORKFLOW_ARCHITECTURE.md`

---

## Plan Completed

Built a personal automation agent accessible via messaging, ending up on Telegram after two failed transport attempts (Meta Cloud API, then Baileys/WhatsApp Web). The agent is a FastAPI service running in Docker, receives inbound messages via webhook through Caddy, classifies intent with Deepseek, and dispatches to a tool registry. Async/long-running tools (research, portfolio queries) are dispatched as Windmill jobs and results returned via follow-up message. The service was renamed from `whatsapp_agent` to `straitsagent` after the transport settled on Telegram.

---

## All Tasks Performed

1. Documented W1 (Personal Agent) and W2 (Business Agent) architecture in ROADMAP.md; W1 marked architecture-approved
2. Designed initial agent around Meta Cloud API — webhook-based, no Node.js sidecar, uses a spare phone number
3. Built full WhatsApp/Meta Cloud API FastAPI service: state machine, Deepseek intent classifier, tool registry with latency classes (FAST/FIRE/GATED_WRITE/ASYNC_NOTIFY/MULTI_STEP), Windmill async job dispatcher, psycopg2 DB layer, asyncio background tasks
4. Added Caddy route for `/webhook/whatsapp` → agent service in `/opt/n8n/Caddyfile`
5. Added `straitsagent` Docker service to `docker-compose.yml` on `agent_net` + `default` networks
6. Updated CLAUDE.md with W1 code-complete status and pending Meta setup note
7. Wrote full W1 pseudocode spec in WORKFLOW_ARCHITECTURE.md; updated ROADMAP with W2–W6 sophistication roadmap
8. Added design rationale doc: FastAPI chosen over polling loop; LangGraph considered and rejected (overkill for single-owner bot)
9. Documented W2–W6 expansion roadmap: W2 tool expansion, W3 compound answers, W4 ReAct loop, W5 personalization, W6 proactive agent
10. Pivoted transport to Baileys — Node.js sidecar with QR-code WhatsApp Web session, spare number <YOUR_SPARE_NUMBER> linked, session persisted in `baileys_auth` Docker volume
11. Pivoted transport to Telegram Bot API — removed Baileys sidecar entirely, added `agent/telegram.py` adapter with `send_message`, `parse_inbound`, `verify_signature`; registered `/webhook/telegram` Caddy route
12. Added slash commands: `/help`, `/portfolio`, `/research`, `/youtube`, `/digest`
13. Fixed `research_tool.py` function signature crash (see Bug 3)
14. Fixed first live research test issues: truncation, slug bug, cache fix, email dispatch, TDD framework
15. Renamed Docker service from `whatsapp_agent` to `straitsagent`; removed all Baileys bridge code and unused WhatsApp adapters
16. Updated all docs to reflect final Telegram-based architecture

---

## Bugs Encountered

**Bug 1 — Meta Cloud API: business verification required, weeks-long approval gate**
**Symptom:** Meta Cloud API integration was fully coded and the Docker service deployed, but the webhook could not be activated. Meta's console rejected the phone number registration and prompted for Facebook Business Manager verification.
**Root cause:** Meta's free tier for the Cloud API (even for user-initiated conversations under the Nov 2024 policy change) still requires a verified Facebook Business account before a number can be registered. Verification takes 1–2 weeks and requires a business entity, not a personal account. This was not apparent from the API docs until reaching the number registration step in the console.
**Fix:** Pivoted to Baileys — a Node.js library that connects via WhatsApp Web (QR scan) using a spare personal number, bypassing Meta's business verification entirely.

**Bug 2 — Baileys WhatsApp number banned within 24 hours**
**Symptom:** The spare number (<YOUR_SPARE_NUMBER>) connected successfully via QR scan and the bridge handled several test messages. Approximately 24 hours later the number was banned by WhatsApp and could no longer send or receive messages.
**Root cause:** WhatsApp actively detects third-party API usage by monitoring for non-official client behavior (Baileys mimics WhatsApp Web but is not an officially sanctioned client). Ban is automated and typically happens within hours to days of first use. There is no appeal path for a personal number.
**Fix:** Pivoted to Telegram Bot API permanently. Telegram explicitly supports and documents bots via the Bot API; bot tokens are first-class and cannot be banned for normal usage.

**Bug 3 — `depth` non-default argument after default crash in research_tool**
**Symptom:** Every agent-triggered research job failed immediately. Windmill logs showed `SyntaxError: non-default argument follows default argument` before any research logic ran.
**Root cause:** `research_tool.py` had the function signature `main(question, research_type="stock", depth, ...)`. The parameter `depth` had no default value but appeared after `research_type`, which did. Python requires all non-default parameters to precede all default parameters in a function signature — this is a syntax error caught at import/compile time, not at runtime, so the script never executed at all.
**Fix:** Added `depth: str = "standard"` as the default, matching the depth that most agent queries should use anyway. This was a pure oversight — a simple import test in the TDD suite would have caught it before deployment.

---

## Lessons Learned

1. **Validate platform requirements before coding the integration.** Meta Cloud API requires business verification that is not prominently documented until you reach the number registration step. A 15-minute read of the full setup guide — including the developer console steps — would have revealed this before a full implementation was written.
2. **Unofficial WhatsApp libraries carry a real ban risk.** Baileys and similar WhatsApp Web reverse-engineering libraries have no official standing. WhatsApp bans numbers using them, often within 24 hours. Any architecture depending on them is inherently fragile. Telegram Bot API is the correct choice for a personal bot: officially supported, no approval needed, free, and instant setup.
3. **A function signature with a missing default is a deploy-time bomb.** The `depth` bug meant the research tool was broken from the moment it was deployed — but this only became visible on the first live test. An `import research_tool` test in the TDD suite (which compiles the module) would have caught this at the red-phase before any deployment.
4. **Name services for what they do, not the transport they use.** Renaming from `whatsapp_agent` to `straitsagent` after the transport changed was the right move — a transport-agnostic name makes future transport swaps easier and avoids stale references in docs and configs.
5. **Keep the Caddy config in sync with service renames.** When the agent service was renamed and the webhook path changed from `/webhook/whatsapp` to `/webhook/telegram`, the Caddyfile needed a corresponding update. Forgetting this would have silently dropped all inbound messages with no error on the agent side.
