# Affection Bot — Conversational Implementation Log

**Date:** 2026-06-26
**Scope:** Build a conversational companion bot for `StraitsAffectionBot` with Perplexity web search grounding via tool calling. Deploy as a separate Docker service alongside the main agent.

## Architecture

New Docker service `affectionbot` — separate FastAPI app (port 8002, `agent_net`):
- Receives Telegram webhook at `/webhook/affection` via Caddy proxy
- Responds only when `@StraitsAffectionBot` is mentioned in the group
- Uses Deepseek `deepseek-chat` as the LLM with function calling
- Calls Perplexity Search API as a tool when factual/current info is needed
- In-memory conversation memory: 15-turn sliding window per chat (volatile)
- Warm/playful/affectionate persona in all replies
- Singapore date/time/location injected into every system prompt for recency
- Sources and links appended to search-grounded responses

## Why Deepseek, not OpenRouter free models

Original plan used `qwen/qwen3-next-80b-a3b-instruct:free` via OpenRouter. All free models were 429 rate-limited during deployment. Switched to the existing Deepseek API key — same OpenAI-compatible tool-calling format, cost ~$0.0002-0.0005 per conversation.

## Group privacy fix

Initial messages didn't reach the bot. The Telegram group privacy setting in BotFather (`/mybots → StraitsAffectionBot → Bot Settings → Group Privacy`) needed to be switched to OFF so the bot could receive group messages. Changed the setting and messages started flowing.

## Files created

| File | Purpose |
|---|---|
| `/root/affection/main.py` | FastAPI app (290 lines) — webhook handler, tool-calling loop, Perplexity search, Telegram send, memory |
| `/root/affection/requirements.txt` | fastapi, uvicorn, httpx |
| `/root/affection/Dockerfile` | python:3.12-slim, uvicorn on port 8002 |
| `/root/affection.env` | Bot token, webhook secret, Deepseek key, Perplexity key, group ID |

## Files modified

| File | Change |
|---|---|
| `/root/docker-compose.yml` | Added `affectionbot` service (build ./affection, agent_net, env_file affection.env) |
| `/opt/n8n/Caddyfile` | Added `/webhook/affection* → affectionbot:8002` handle block |
| `/root/docs/plans/2026-06-26_affection-bot-conversational.md` | Plan file (draft → executing → done) |
| `/root/shared/keys.md` | Added StraitsAffectionBot token |

## Live verification

- Affection ping sticker pack updated: +`peachlovesgoma` (12 packs total)
- Test ping from peachlovesgoma pack confirmed delivered (job `019f021e`)
- Bot replies to `@StraitsAffectionBot` mentions with warm conversational tone
- Web search working — Perplexity → Deepseek synthesis → cited response with Sources links
- Date/location awareness confirmed — Singapore time injected into prompts, no more 2025 hallucinations
- Group silence respected — messages without @mention are ignored
- Conversation memory working — follow-up questions reference prior context

## Notes

- Container is zero-dependency: no Windmill, no Postgres, no volumes. Just the LLM and search API.
- Conversation memory resets on container restart (acceptable for a companion bot).
- Orphaned `root-baileys_bridge-1` container removed from the stack.
