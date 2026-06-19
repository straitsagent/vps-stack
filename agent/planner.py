"""Multi-step reasoning: planner LLM call → sequential FAST tool execution → synthesis."""
import json

import httpx
from config import DEEPSEEK_KEY, DEEPSEEK_MODEL

_ALLOWED_TOOLS = {
    "portfolio_snapshot", "portfolio_digest", "ticker_detail", "live_prices",
    "health_check", "news_digest", "youtube_digest", "thesis_read",
    "earnings", "news_search", "macro_indicators",
}

PLANNER_SYSTEM_PROMPT = """You are a research planner for a personal finance assistant.
Given a user intent and question, output a JSON array of tool steps to execute (in order).
Each step: {"tool": "<name>", "args": {<args>}}.

Available tools:
- portfolio_snapshot: {} — current portfolio values and P&L
- news_digest: {} — latest morning news digest
- ticker_detail: {"ticker": "SYMBOL"} — detailed price and fundamentals for one stock
- earnings: {"ticker": "SYMBOL or null"} — upcoming earnings calendar or latest stored earnings analysis
- news_search: {"query": "search terms"} — search for specific news
- macro_indicators: {} — SGD/USD, HKD/USD, VIX, Brent, 10Y UST
- thesis_read: {"ticker": "SYMBOL"} — stored investment thesis

Choose 2-4 tools that best answer the question. Output ONLY valid JSON array. No explanation."""

SYNTHESISER_SYSTEM_PROMPT = """You are a concise personal finance assistant. You receive tool outputs and synthesise them into a clear, direct answer for the user. Write in plain text with markdown formatting. Be brief — aim for 200-400 words unless the question demands more detail."""


def _parse_plan(raw: str) -> list[dict]:
    try:
        steps = json.loads(raw)
        if not isinstance(steps, list):
            return []
        return [s for s in steps if isinstance(s, dict) and s.get("tool") in _ALLOWED_TOOLS]
    except (json.JSONDecodeError, TypeError):
        return []


async def plan(intent: str, args: dict, text: str) -> list[dict]:
    """Call Deepseek to generate an ordered list of tool steps. Returns [] on any error."""
    messages = [
        {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
        {"role": "user", "content": f"Intent: {intent}\nQuestion: {text}"},
    ]
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                "https://api.deepseek.com/chat/completions",
                headers={"Authorization": f"Bearer {DEEPSEEK_KEY}"},
                json={
                    "model": DEEPSEEK_MODEL,
                    "messages": messages,
                    "temperature": 0.0,
                    "max_tokens": 512,
                },
            )
            r.raise_for_status()
        raw = r.json()["choices"][0]["message"]["content"].strip()
        steps = _parse_plan(raw)
        print(f"[Planner] {len(steps)} steps planned for intent={intent}")
        return steps
    except Exception as e:
        print(f"[Planner] ERROR: {e}")
        return []


async def synthesise(question: str, tool_results: dict[str, str]) -> str:
    """Synthesise tool outputs into a unified answer. Returns error string on failure."""
    context_parts = [f"**{tool}**:\n{output}" for tool, output in tool_results.items()]
    context = "\n\n".join(context_parts)
    messages = [
        {"role": "system", "content": SYNTHESISER_SYSTEM_PROMPT},
        {"role": "user", "content": f"Question: {question}\n\nTool outputs:\n{context}"},
    ]
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                "https://api.deepseek.com/chat/completions",
                headers={"Authorization": f"Bearer {DEEPSEEK_KEY}"},
                json={
                    "model": DEEPSEEK_MODEL,
                    "messages": messages,
                    "temperature": 0.3,
                    "max_tokens": 1500,
                },
            )
            r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"[Synthesiser] ERROR: {e}")
        return f"Analysis failed: {e}"
