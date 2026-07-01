"""
Affection Bot — conversational companion with Perplexity web search grounding.
Receives Telegram webhook, responds when @mentioned, tool-calls web_search as needed.
"""
import json
import os
import re
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from threading import Lock

import httpx
import psycopg2
import psycopg2.extras
from fastapi import FastAPI, Request

# ── Config ────────────────────────────────────────────────────────────────────
BOT_TOKEN      = os.environ["AFFECTION_BOT_TOKEN"]
WEBHOOK_SECRET = os.environ["AFFECTION_WEBHOOK_SECRET"]
GROUP_ID       = os.environ.get("AFFECTION_GROUP_ID", "")
DEEPSEEK_KEY   = os.environ["DEEPSEEK_KEY"]
PERPLEXITY_KEY = os.environ["PERPLEXITY_KEY"]
DEEPSEEK_URL   = "https://api.deepseek.com/v1/chat/completions"
PERPLEXITY_URL = "https://api.perplexity.ai/search"
TELEGRAM_URL   = f"https://api.telegram.org/bot{BOT_TOKEN}"
MODEL          = "deepseek-chat"
MAX_HISTORY    = 15
MAX_RESP_TOKENS = 512
MAX_TOOL_DEPTH = 3
DB_URL         = os.environ.get("DB_URL", "")

_db_conn = None
_db_lock = Lock()

def _get_db():
    global _db_conn
    if _db_conn is None or _db_conn.closed:
        _db_conn = psycopg2.connect(DB_URL)
        _db_conn.autocommit = True
    return _db_conn

SGT = timezone(timedelta(hours=8))

SYSTEM_PROMPT_BASE = (
    "You are an affectionate, warm, and playful companion. Respond with genuine warmth — like "
    "someone who cares about the person's day and feelings. Use light humor, playful teasing where "
    "appropriate, and always end on a positive or uplifting note. When someone asks a factual or "
    "current question, use the web_search tool to find current information, then deliver it "
    "conversationally — not like an encyclopedia. Never be cold, clinical, or robotic. The person "
    "you're talking to is precious to you. Keep responses under ~200 words unless asked for detail. "
    "Always respond in plain conversational English — no markdown formatting unless specifically "
    "needed for readability.\n\n"
    "CRITICAL — When you use web_search results, you MUST cite sources inline with [1], [2], etc. "
    "and append a numbered Sources section at the very end of your message, like:\n"
    "Sources:\n[1] https://...\n[2] https://...\n\n"
    "You are in a Telegram group and can see all messages (prefixed with the sender's name, "
    "e.g. 'Kev: ...' or 'lissy: ...'). Only respond when someone mentions @StraitsAffectionBot "
    "directly. You observe ambient conversation passively — it helps you understand the group's "
    "context and personalities.\n\n"
    "Use the search_memory tool to recall past conversations, including group discussions you've "
    "observed. When asked to summarize recent topics or recall something from days/weeks ago, "
    "search by keywords and/or date range. The current date/time in your system prompt tells you "
    "what 'last month' or '2 weeks ago' maps to in YYYY-MM-DD format. When asked for a broad "
    "summary, leave the query empty and set the date range — this returns all messages in that window."
)

def _load_memory_blocks(chat_id: str) -> str:
    """Read short-term and long-term memory for chat_id, render as frozen blocks."""
    if not DB_URL:
        return ""
    blocks = []
    try:
        with _db_lock:
            cur = _get_db().cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(
                "SELECT content, synth_at, n_msgs FROM affection_long_term_memory WHERE chat_id = %s",
                (chat_id,),
            )
            lt = cur.fetchone()
            cur.execute(
                "SELECT content, synth_at, n_msgs, window_start, window_end "
                "FROM affection_short_term_memory WHERE chat_id = %s",
                (chat_id,),
            )
            st = cur.fetchone()
            cur.close()
        if lt:
            ts = lt["synth_at"].strftime("%Y-%m-%d %H:%M SGT") if lt.get("synth_at") else "?"
            blocks.append(
                f"══════════════════════════════════════════════\n"
                f"LONG-TERM MEMORY (synthesised {ts} from {lt['n_msgs']} messages)\n"
                f"══════════════════════════════════════════════\n"
                f"{lt['content']}"
            )
        if st:
            ts = st["synth_at"].strftime("%Y-%m-%d %H:%M SGT") if st.get("synth_at") else "?"
            window = ""
            if st.get("window_start") and st.get("window_end"):
                window = f"Window: {st['window_start'].strftime('%Y-%m-%d')} → {st['window_end'].strftime('%Y-%m-%d')}"
            blocks.append(
                f"══════════════════════════════════════════════\n"
                f"SHORT-TERM MEMORY (synthesised {ts} from {st['n_msgs']} messages)\n"
                f"{window}\n"
                f"══════════════════════════════════════════════\n"
                f"{st['content']}"
            )
    except Exception as e:
        print(f"[affection] memory block load error: {e!r}")
    return "\n\n".join(blocks)


def build_system_prompt(chat_id: str = "") -> str:
    now = datetime.now(SGT)
    ts = now.strftime("%A, %d %B %Y, %I:%M %p SGT")
    memory_section = ""
    if chat_id:
        mem = _load_memory_blocks(chat_id)
        if mem:
            memory_section = f"\n\n{mem}"
    return (
        f"{SYSTEM_PROMPT_BASE}{memory_section}\n\n"
        f"Current time: {ts}. You are in Singapore and the user is in Singapore. "
        f"Use this date/time for recency in search queries — never guess the year or month."
    )

WEB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Search the web for current information. Use this when you need facts, news, or data "
            "you don't already know. Be specific — include dates for recency, tickers for stocks."
        ),
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

SEARCH_MEMORY_TOOL = {
    "type": "function",
    "function": {
        "name": "search_memory",
        "description": (
            "Search our past conversation history, including group discussions I've observed. "
            "Use this when the user asks about something discussed before, wants a summary of "
            "recent topics, or references a past conversation. Search by keywords, date range, or both."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keywords to search for (1-5 words). Leave empty to match ALL messages — use for date-range summaries like 'what have we talked about this week?'."
                },
                "from_date": {
                    "type": "string",
                    "description": "Start date in YYYY-MM-DD format. Use when the user asks about a period like 'last month', 'since Monday', or 'in May'. Omit for no lower bound."
                },
                "to_date": {
                    "type": "string",
                    "description": "End date in YYYY-MM-DD format. Use with from_date for bounded searches. Omit for no upper bound."
                }
            },
            "required": ["query"]
        }
    }
}

ALL_TOOLS = [WEB_SEARCH_TOOL, SEARCH_MEMORY_TOOL]

# ── Conversation memory (in-memory cache + Postgres persistence) ──────────────
memory: dict[str, deque] = {}
_loaded: set[str] = set()

def _load_memory(chat_id: str):
    """Load last MAX_HISTORY messages from DB into the in-memory deque."""
    if not DB_URL:
        return
    try:
        with _db_lock:
            cur = _get_db().cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(
                "SELECT role, content, tool_calls, tool_call_id "
                "FROM affection_conversation WHERE chat_id = %s "
                "ORDER BY created_at DESC LIMIT %s",
                (chat_id, MAX_HISTORY),
            )
            rows = cur.fetchall()
            cur.close()
        entries = []
        for row in reversed(rows):
            entry = {"role": row["role"]}
            if row["content"] is not None:
                entry["content"] = row["content"]
            if row["tool_call_id"] is not None:
                entry["tool_call_id"] = row["tool_call_id"]
            if row["tool_calls"] is not None:
                entry["tool_calls"] = row["tool_calls"]
            entries.append(entry)
        memory[chat_id] = deque(entries, maxlen=MAX_HISTORY)
    except Exception as e:
        print(f"[affection] db load error for {chat_id}: {e!r}")

def _persist_message(chat_id: str, role: str, content=None, tool_call_id=None, tool_calls=None):
    """Insert a message into the DB for long-term persistence."""
    if not DB_URL:
        return
    try:
        tc_json = json.dumps(tool_calls) if tool_calls else None
        with _db_lock:
            cur = _get_db().cursor()
            cur.execute(
                "INSERT INTO affection_conversation (chat_id, role, content, tool_calls, tool_call_id) "
                "VALUES (%s, %s, %s, %s, %s)",
                (chat_id, role, content, tc_json, tool_call_id),
            )
            cur.close()
    except Exception as e:
        print(f"[affection] db persist error for {chat_id}: {e!r}")

def remember(chat_id: str, role: str, content=None, tool_call_id=None, tool_calls=None):
    if chat_id not in memory:
        if chat_id not in _loaded and DB_URL:
            _load_memory(chat_id)
            _loaded.add(chat_id)
        if chat_id not in memory:
            memory[chat_id] = deque(maxlen=MAX_HISTORY)
    entry = {"role": role}
    if content is not None:
        entry["content"] = content
    if tool_call_id:
        entry["tool_call_id"] = tool_call_id
    if tool_calls:
        entry["tool_calls"] = tool_calls
    memory[chat_id].append(entry)
    _persist_message(chat_id, role, content, tool_call_id, tool_calls)

def build_messages(chat_id: str) -> list[dict]:
    return [{"role": "system", "content": build_system_prompt(chat_id)}] + list(memory.get(chat_id, []))

# ── API helpers ───────────────────────────────────────────────────────────────
_limits = httpx.Limits(max_keepalive_connections=4, max_connections=8)
_client = httpx.AsyncClient(timeout=30, limits=_limits)

async def deepseek_chat(messages: list[dict], tools=None) -> dict:
    body = {
        "model": MODEL,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": MAX_RESP_TOKENS,
    }
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    r = await _client.post(
        DEEPSEEK_URL,
        headers={
            "Authorization": f"Bearer {DEEPSEEK_KEY}",
            "Content-Type": "application/json",
        },
        json=body,
    )
    if r.status_code != 200:
        print(f"[affection] Deepseek error {r.status_code}: {r.text[:300]}")
        return {}
    return r.json()

async def perplexity_search(query: str) -> dict:
    r = await _client.post(
        PERPLEXITY_URL,
        headers={
            "Authorization": f"Bearer {PERPLEXITY_KEY}",
            "Content-Type": "application/json",
        },
        json={"query": query, "max_results": 10},
    )
    if r.status_code != 200:
        print(f"[affection] Perplexity error {r.status_code}: {r.text[:300]}")
        return {"results": []}
    return r.json()

def format_search_results(data: dict) -> str:
    results = data.get("results", [])
    if not results:
        return "No search results found."
    lines = []
    for i, r in enumerate(results[:10], 1):
        date = r.get("date", "") or ""
        title = r.get("title", "Untitled")
        url   = r.get("url", "")
        snippet = (r.get("snippet", "") or "")[:300]
        lines.append(f"[{i}] {title}\n    URL: {url}\n    Date: {date}\n    {snippet}")
    return "\n\n".join(lines)

def search_conversation(chat_id: str, query: str, from_date: str, to_date: str) -> list[dict]:
    """Search affection_conversation by keywords and/or date range."""
    if not DB_URL:
        return []
    try:
        with _db_lock:
            cur = _get_db().cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            sql = (
                "SELECT role, content, created_at AT TIME ZONE 'Asia/Singapore' AS sgt "
                "FROM affection_conversation "
                "WHERE chat_id = %s "
                "  AND role IN ('user', 'assistant') "
                "  AND (%s = '' OR content ILIKE '%%' || %s || '%%') "
                "  AND (%s = '' OR created_at >= %s::timestamptz) "
                "  AND (%s = '' OR created_at < (%s::date + interval '1 day')::timestamptz) "
                "ORDER BY created_at DESC LIMIT 10"
            )
            cur.execute(sql, (chat_id, query, query, from_date, from_date, to_date, to_date))
            rows = cur.fetchall()
            cur.close()
        return rows
    except Exception as e:
        print(f"[affection] memory search error: {e!r}")
        return []

def format_memory_results(rows: list[dict]) -> str:
    if not rows:
        return "No matching messages found in our conversation history."
    lines = []
    for row in rows:
        ts = row["sgt"].strftime("%Y-%m-%d %H:%M") if row.get("sgt") else "unknown"
        role = row["role"]
        content = (row.get("content") or "")[:400]
        lines.append(f"[{ts} SGT] {role}: {content}")
    return "\n".join(lines)

async def send_telegram(chat_id: str, text: str) -> bool:
    chunks = []
    remaining = text
    while remaining:
        if len(remaining) <= 4000:
            chunks.append(remaining)
            break
        cut = remaining.rfind("\n", 0, 4000)
        if cut <= 0:
            cut = 4000
        chunks.append(remaining[:cut])
        remaining = remaining[cut:].lstrip("\n")

    ok = True
    for chunk in chunks:
        try:
            r = await _client.post(
                f"{TELEGRAM_URL}/sendMessage",
                json={"chat_id": int(chat_id), "text": chunk, "parse_mode": "Markdown"},
            )
            if r.status_code != 200:
                if r.status_code == 400:
                    r2 = await _client.post(
                        f"{TELEGRAM_URL}/sendMessage",
                        json={"chat_id": int(chat_id), "text": chunk},
                    )
                    ok = r2.status_code == 200 and ok
                else:
                    print(f"[affection] sendMessage failed {r.status_code}: {r.text[:200]}")
                    ok = False
        except Exception as e:
            print(f"[affection] sendMessage error: {type(e).__name__}: {e!r}")
            ok = False
    return ok

# ── Content sanitization ─────────────────────────────────────────────────────────
_DSML_RE = re.compile(r"<｜[^>]+｜>[^<]*<｜[^>]+｜>")


def _sanitize_content(text: str) -> str:
    """Remove DSML XML tool-call markers from outgoing text."""
    return _DSML_RE.sub("", text).strip()


# ── Core logic ────────────────────────────────────────────────────────────────
async def chat_with_search(chat_id: str, depth: int = 0) -> str:
    messages = build_messages(chat_id)

    resp = await deepseek_chat(messages, tools=ALL_TOOLS)
    if not resp:
        return "Sorry, I'm having a moment — try me again in a bit?"

    choice = resp.get("choices", [{}])[0]
    msg = choice.get("message", {})
    search_urls = []  # [(num, title, url), ...]

    if msg.get("tool_calls"):
        tool_calls = msg["tool_calls"]
        remember(chat_id, "assistant", None, tool_calls=tool_calls)

        for tc in tool_calls:
            fn = tc.get("function", {})
            name = fn.get("name", "")
            try:
                args = json.loads(fn.get("arguments", "{}"))
            except json.JSONDecodeError:
                args = {}

            if name == "web_search":
                query = args.get("query", "")
                if not query:
                    continue
                print(f"[affection] searching: {query[:80]}")
                results = await perplexity_search(query)
                tool_content = format_search_results(results)
                remember(chat_id, "tool", tool_content, tool_call_id=tc.get("id", ""))
                for i, r in enumerate(results.get("results", [])[:10], 1):
                    url = r.get("url", "")
                    if url:
                        search_urls.append((i, r.get("title", ""), url))

            elif name == "search_memory":
                q = args.get("query", "")
                fd = args.get("from_date", "")
                td = args.get("to_date", "")
                print(f"[affection] memory: q='{q[:60]}' {fd}→{td}")
                rows = search_conversation(chat_id, q, fd, td)
                tool_content = format_memory_results(rows)
                remember(chat_id, "tool", tool_content, tool_call_id=tc.get("id", ""))

        if depth >= MAX_TOOL_DEPTH:
            return "Sorry, I kept looking but couldn't find a clear answer — could you rephrase?"

        messages = build_messages(chat_id)
        resp = await deepseek_chat(messages, tools=ALL_TOOLS)
        if not resp:
            return "Sorry, I couldn't look that up — try again?"

        choice = resp.get("choices", [{}])[0]
        msg = choice.get("message", {})

        if msg.get("tool_calls"):
            tool_calls = msg["tool_calls"]
            remember(chat_id, "assistant", None, tool_calls=tool_calls)
            for tc in tool_calls:
                fn = tc.get("function", {})
                name = fn.get("name", "")
                try:
                    args = json.loads(fn.get("arguments", "{}"))
                except json.JSONDecodeError:
                    args = {}
                if name == "web_search":
                    query = args.get("query", "")
                    if query:
                        results = await perplexity_search(query)
                        tc_content = format_search_results(results)
                        remember(chat_id, "tool", tc_content, tool_call_id=tc.get("id", ""))
                        for i, r in enumerate(results.get("results", [])[:10], 1):
                            url = r.get("url", "")
                            if url:
                                search_urls.append((i, r.get("title", ""), url))
                elif name == "search_memory":
                    q = args.get("query", "")
                    fd = args.get("from_date", "")
                    td = args.get("to_date", "")
                    rows = search_conversation(chat_id, q, fd, td)
                    tc_content = format_memory_results(rows)
                    remember(chat_id, "tool", tc_content, tool_call_id=tc.get("id", ""))
            return await chat_with_search(chat_id, depth + 1)

    reply = msg.get("content", "")
    reply = _sanitize_content(reply)
    if not reply or not reply.strip():
        return "..."

    if search_urls:
        reply += "\n\nSources:"
        for num, title, url in search_urls:
            reply += f"\n[{num}] [{title}]({url})"

    remember(chat_id, "assistant", reply)
    return reply

# ── Telegram webhook ──────────────────────────────────────────────────────────
def parse_inbound(payload: dict) -> dict | None:
    try:
        m = payload.get("message") or payload.get("edited_message")
        if not m:
            return None
        chat = m["chat"]
        sender = m.get("from", {})
        return {
            "chat_id": str(chat["id"]),
            "display_name": sender.get("first_name", ""),
            "text": m.get("text", ""),
            "is_group": chat["type"] in ("group", "supergroup", "channel"),
        }
    except (KeyError, TypeError):
        return None

# ── FastAPI app ───────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        async with httpx.AsyncClient(timeout=15) as cl:
            r = await cl.post(
                f"{TELEGRAM_URL}/setWebhook",
                json={
                    "url": "https://vmi2933703.contaboserver.net/webhook/affection",
                    "secret_token": WEBHOOK_SECRET,
                    "allowed_updates": ["message"],
                },
            )
            if r.status_code == 200 and r.json().get("ok"):
                print("[affection] webhook registered successfully")
            else:
                print(f"[affection] setWebhook failed: {r.status_code} {r.text[:200]}")
    except Exception as e:
        print(f"[affection] setWebhook error: {e!r}")
    yield

app = FastAPI(lifespan=lifespan)

@app.post("/webhook/affection")
async def handle_affection(request: Request):
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if secret != WEBHOOK_SECRET:
        return {"status": "unauthorized"}

    payload = await request.json()
    msg = parse_inbound(payload)
    if not msg or not msg.get("text", "").strip():
        return {"status": "ignored"}

    text = msg["text"]
    chat_id = msg["chat_id"]
    mentioned = "@straitsaffectionbot" in text.lower()

    if msg["is_group"]:
        display = msg["display_name"] or "someone"
        clean = text.replace("@StraitsAffectionBot", "").replace("@straitsaffectionbot", "").strip()
        if clean:
            remember(chat_id, "user", f"{display}: {clean}")

    if not mentioned:
        return {"status": "lurking"}

    print(f"[affection] {chat_id} ({msg['display_name']}): {text[:80]}")
    reply = await chat_with_search(chat_id)
    await send_telegram(chat_id, reply)
    return {"status": "ok"}
