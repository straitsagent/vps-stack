---
Subject: Affection Bot — Conversational with Perplexity Search via Tool Calling
Date: 2026-06-26
Status: done
Planner model: claude-sonnet-4-6 (Claude Code plan mode)
Executor model: deepseek (opencode) or any
Hard Rules in force: [7, 8, 9, 15, 17]
Files to read before coding: CLAUDE.md, docs/TESTING.md, /opt/n8n/Caddyfile, /root/docker-compose.yml, /root/agent/main.py, /root/agent/telegram.py
---

# Plan: Affection Bot — Conversational with Perplexity Search

## Context

The hourly affection ping now runs on its own bot (`StraitsAffectionBot`) with its own token
(`u/admin/affection_bot_token`). The bot is in the affection group and sends stickers on a cron
schedule. The owner wants it to become conversational: respond to messages when mentioned, with
the ability to search the web to ground its responses.

This is a **clean-slate companion bot** — not a second instance of the main portfolio-advisor
agent. No Windmill dispatch, no DB, no tool registry, no multi-step planner. Just an LLM with a
search tool, warm persona, and short conversation memory.

## Architecture

```
User @StraightsAffectionBot "what's up with Tesla?"
          │
          ▼
   Caddy /webhook/affection → affectionbot:8002 (FastAPI)
          │
          ├─ Add to conversation memory[chat_id]  (deque, max 15)
          │
          ├─ Send to OpenRouter (qwen/qwen3-next-80b-a3b-instruct:free)
          │      system: affectionate persona prompt
          │      messages: last 15-turn window (incl. tool history)
          │      tools: [web_search]
          │
          ├─ LLM decides: just answer, or call web_search?
          │      │
          │      └─ Calls web_search(query) →
          │           POST https://api.perplexity.ai/search
          │           → results[] (title, url, snippet, date)
          │           → feed results back to LLM → final response
          │
          └─ Send response via Telegram (4000-char splits)
```

### Decisions

| Decision | Choice | Why |
|---|---|---|
| LLM | `qwen/qwen3-next-80b-a3b-instruct:free` via OpenRouter | 3B active MoE, no reasoning overhead, fast, tool calling, free |
| Search | Perplexity Search API (`POST /search`) | Raw structured results (not prose), owner already has a key, ~$0.005/search |
| Memory | In-memory deque, 15 messages per chat, volatile | Simple, no DB, acceptable for companionship |
| Deployment | Separate Docker service `affectionbot`, port 8002, `agent_net` | Isolated failures, clean env, no coupling with main agent |
| Group behavior | Respond only when `@StraightsAffectionBot` is in the message | Avoids noise in group chats |
| Tool loop | Single-step: LLM can call search once, then must respond | Simple, no runaway loops. Max 1 search per message. |

### Environment facts the executor needs

- Run from `/root`. Git from `/root` only.
- Caddy config at `/opt/n8n/Caddyfile` — routes through `agent_net`.
- Docker compose at `/root/docker-compose.yml`.
- OpenRouter key: `from /root/shared/keys.md — OpenRouter entry`
- Perplexity key: `from /root/shared/keys.md — Perplexity entry`
- Affection bot token: `from /root/shared/keys.md — Telegram Bot (Affection) entry`
- Affection group ID: `from outbox` — query `SELECT distinct recipient_id FROM affection_outbox;`

---

## Files

| Action | Path | Purpose |
|---|---|---|
| Create | `/root/affection/main.py` | FastAPI app (~200 lines) |
| Create | `/root/affection/requirements.txt` | fastapi, uvicorn, httpx |
| Create | `/root/affection/Dockerfile` | Container build |
| Create | `/root/affection.env` | 5 env vars (token, keys, config) |
| Modify | `/root/docker-compose.yml` | Add `affectionbot` service |
| Modify | `/opt/n8n/Caddyfile` | Add `/webhook/affection*` route |
| Create | `/root/docs/logs/2026-06-26_affection-bot-conversational.md` | Implementation log |

---

## Code design — `main.py` (~200 lines)

### Webhook handler

```
POST /webhook/affection:
  1. Verify X-Telegram-Bot-Api-Secret-Token header == AFFECTION_WEBHOOK_SECRET
  2. Parse payload → extract text, chat_id, display_name, is_group, msg_id
  3. If empty text → ignore (returns {"status": "ignored"})
  4. If is_group AND "@StraightsAffectionBot" NOT in text → ignore
  5. Strip the @mention from the text for the LLM
  6. Add user message to memory[chat_id]
  7. Call chat_with_search(chat_id) → assistant reply
  8. Send reply via Telegram (split at 4000 chars, Markdown, fallback to plain on 400)
  9. Return {"status": "ok"}
```

### Tool-calling loop — `chat_with_search(chat_id)`

```python
async def chat_with_search(chat_id: str) -> str:
    messages = build_messages(chat_id)  # system + history

    # Step 1: call LLM
    resp = await openrouter_chat(messages, tools=[WEB_SEARCH_TOOL])

    # Step 2: handle tool call if present
    if resp contains tool_calls:
        for tc in resp.tool_calls:
            if tc.function.name == "web_search":
                args = json.loads(tc.function.arguments)
                results = await perplexity_search(args["query"])
                remember(chat_id, "assistant", None, tool_calls=resp.tool_calls)
                remember(chat_id, "tool", format_results(results), tool_call_id=tc.id)
        # Step 3: final call with search results
        resp = await openrouter_chat(build_messages(chat_id), tools=[])  # no tools on final

    assistant_text = resp.choices[0].message.content
    remember(chat_id, "assistant", assistant_text)
    return assistant_text
```

### OpenRouter chat helper

```python
async def openrouter_chat(messages, tools=None):
    body = {
        "model": "qwen/qwen3-next-80b-a3b-instruct:free",
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 512,
    }
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    r = await httpx_client.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {OPENROUTER_KEY}"},
        json=body,
        timeout=30,
    )
    return r.json()
```

### Perplexity search helper

```python
async def perplexity_search(query: str) -> dict:
    r = await httpx_client.post(
        "https://api.perplexity.ai/search",
        headers={"Authorization": f"Bearer {PERPLEXITY_KEY}"},
        json={"query": query, "max_results": 5},
        timeout=15,
    )
    return r.json()
```

### Format results for the LLM

```python
def format_results(data: dict) -> str:
    lines = []
    for r in data.get("results", []):
        date = r.get("date", "") or ""
        lines.append(f"- [{r['title']}]({r['url']}) ({date})\n  {r.get('snippet','')[:300]}")
    return "\n".join(lines)
```

### Conversation memory

```python
from collections import deque
memory: dict[str, deque] = {}

def remember(chat_id, role, content=None, tool_call_id=None, tool_calls=None):
    if chat_id not in memory:
        memory[chat_id] = deque(maxlen=15)
    entry = {"role": role}
    if content is not None:
        entry["content"] = content
    if tool_call_id:
        entry["tool_call_id"] = tool_call_id
    if tool_calls:
        entry["tool_calls"] = tool_calls
    memory[chat_id].append(entry)

def build_messages(chat_id):
    return [{"role": "system", "content": SYSTEM_PROMPT}] + list(memory.get(chat_id, []))
```

### System prompt

> You are an affectionate, warm, and playful companion. Respond with genuine warmth — like
> someone who cares about the person's day and feelings. Use light humor, playful teasing where
> appropriate, and always end on a positive or uplifting note. When someone asks a factual or
> current question, use the web_search tool to find current information, then deliver it
> conversationally — not like an encyclopedia. Never be cold, clinical, or robotic. The person
> you're talking to is precious to you. Keep responses under ~200 words unless asked for detail.
> Always respond in plain conversational English — no markdown formatting unless specifically
> needed for readability.

### Web search tool definition (sent to LLM)

```json
{
  "type": "function",
  "function": {
    "name": "web_search",
    "description": "Search the web for current information. Use this when you need facts, news, or data you don't already know. Be specific — include dates for recency, tickers for stocks.",
    "parameters": {
      "type": "object",
      "properties": {
        "query": {
          "type": "string",
          "description": "The search query. Include relevant keywords, dates, or tickers."
        }
      },
      "required": ["query"]
    }
  }
}
```

### Webhook registration (on startup)

```
POST https://api.telegram.org/bot<TOKEN>/setWebhook
  url=https://vmi2933703.contaboserver.net/webhook/affection
  secret_token=<WEBHOOK_SECRET>
```

On failure: log warning, continue (container restarts will retry). The service still starts.

---

## `docker-compose.yml` addition

```yaml
  affectionbot:
    build: ./affection
    restart: unless-stopped
    networks:
      - agent_net
    env_file:
      - affection.env
    logging: *default-logging
```

No DB dependency, no volumes. Isolated. Only needs `agent_net` to reach Caddy.

---

## Caddyfile addition

The existing Caddyfile routes `/webhook/telegram*` → `straitsagent:8001` and everything else →
`n8n:5678`. Add a new `handle` block before the existing telegram one:

```
handle /webhook/affection* {
    reverse_proxy affectionbot:8002
}
handle /webhook/telegram* {
    reverse_proxy straitsagent:8001
}
handle {
    reverse_proxy n8n:5678
}
```

Reload Caddy after: `docker exec n8n-caddy-1 caddy reload --config /etc/caddy/Caddyfile`

---

## Checklist

- [ ] Step 1 — Create `/root/affection/` with main.py, requirements.txt, Dockerfile
- [ ] Step 2 — Create `/root/affection.env` with 5 env vars
- [ ] Step 3 — Add `affectionbot` service to `/root/docker-compose.yml`
- [ ] Step 4 — Add `/webhook/affection*` route to `/opt/n8n/Caddyfile`
- [ ] Step 5 — Reload Caddy
- [ ] Step 6 — Build + start container: `docker compose up -d affectionbot`
- [ ] Step 7 — Confirm webhook registered (check logs)
- [ ] Step 8 — Live test: mention → reply, no mention → silent
- [ ] Step 9 — Live test: factual question → search-grounded answer
- [ ] Step 10 — Live test: memory (reference earlier message)
- [ ] Step 11 — Create `/root/docs/logs/2026-06-26_affection-bot-conversational.md`
- [ ] Step 12 — Commit

---

## Verification

- `docker compose ps affectionbot` shows `Up` and healthy
- `curl -s -o /dev/null -w "%{http_code}" https://vmi2933703.contaboserver.net/webhook/affection` returns 401 (not 404 — proves route active, just missing secret)
- `docker logs affectionbot` shows `setWebhook` succeeded on startup
- `@StraitsAffectionBot hello!` → warm reply within 2-3 seconds
- `@StraitsAffectionBot what happened with NVIDIA stock this week?` → search-grounded answer with current info
- Group message without `@StraightsAffectionBot` → no reply
- `@StraitsAffectionBot what did I just ask you?` → references previous question (proves memory works)
- `git status` clean after commit

## Execution

1. Set front-matter Status: executing, commit.
2. Work the checklist top to bottom; tick each `- [ ]` when its success criteria are met.
3. Run the Verification section.
4. Set Status: done, commit.
Do not redesign. If the plan is ambiguous or wrong, stop and report — do not improvise.
