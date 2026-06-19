"""Multi-step reasoning: planner LLM call → sequential FAST tool execution → synthesis."""
import asyncio
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
- macro_indicators: {} — 24 indicators across 6 groups: equity indices (S&P 500, Nasdaq, Hang Seng, STI, Shanghai), rates (UST 5Y/10Y/30Y), volatility (VIX), commodities (Brent, WTI, Gold, Copper), FX (USD/SGD, USD/HKD, USD/CNY, DXY, EUR/USD, USD/JPY), and FRED economic data (Fed Funds, CPI YoY, Core PCE YoY, Unemployment)
- thesis_read: {"ticker": "SYMBOL"} — stored investment thesis

Choose 2-4 tools that best answer the question. Output ONLY valid JSON array. No explanation."""

SYNTHESISER_SYSTEM_PROMPT = """You are a concise personal finance assistant. You receive tool outputs and synthesise them into a clear, direct answer for the user. Write in plain text with markdown formatting. Be brief — aim for 200-400 words unless the question demands more detail."""

_NEWS_SECTIONS = {
    "Indices & Vol":  "stock markets equities S&P Nasdaq Hang Seng volatility VIX",
    "Rates":          "US treasury yields interest rates Federal Reserve bonds",
    "Commodities":    "oil Brent gold copper commodities prices",
    "FX":             "dollar USD currency CNY JPY SGD exchange rates",
    "Economics":      "Fed inflation CPI PCE unemployment US economy",
}

MACRO_SYNTHESISER_SYSTEM_PROMPT = """You are a macro analyst for a personal finance assistant.

You receive: macro indicators data (grouped by section) and news results labelled by section.

For EACH section in the data, output:
1. A divider: ━━━━━━━━━━━━━━━━━━━━
2. The section header and ALL data rows EXACTLY as given (preserve spacing and values)
3. 2-4 sentences of in-depth commentary interpreting what the indicators signal for a portfolio ~40% HK equities / ~60% US equities. Be specific about portfolio implications.
4. Relevant news sources with hyperlinks: • [Title](url) — Publication

Output sections in this order: Indices, Rates, Vol, Commodities, FX, Economics (FRED).
Use Markdown. No preamble or conclusion text outside the sections."""


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


async def synthesise_macro(question: str, tool_results: dict[str, str]) -> str:
    """Macro-specific synthesiser: preserves data verbatim, adds commentary + sources."""
    context_parts = [f"**{tool}**:\n{output}" for tool, output in tool_results.items()]
    context = "\n\n".join(context_parts)
    messages = [
        {"role": "system", "content": MACRO_SYNTHESISER_SYSTEM_PROMPT},
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
        print(f"[MacroSynthesiser] ERROR: {e}")
        return f"Macro analysis failed: {e}"


async def run_macro_brief(question: str) -> str:
    """Fetch macro data + 5 targeted news searches in parallel, then synthesise per-section."""
    from tools import macro_indicators, news_search

    queries = list(_NEWS_SECTIONS.values())
    section_names = list(_NEWS_SECTIONS.keys())

    tasks = [macro_indicators({})] + [news_search({"query": q}) for q in queries]
    all_results = await asyncio.gather(*tasks, return_exceptions=True)

    macro_result = all_results[0]
    macro_data = macro_result.get("text", "Macro data unavailable.") if not isinstance(macro_result, Exception) else "Macro data unavailable."

    news_parts = []
    for i, name in enumerate(section_names):
        r = all_results[i + 1]
        news_text = r.get("text", "") if not isinstance(r, Exception) else ""
        news_parts.append(f"[News — {name}]\n{news_text}")

    combined = f"[Macro Data]\n{macro_data}\n\n" + "\n\n".join(news_parts)

    messages = [
        {"role": "system", "content": MACRO_SYNTHESISER_SYSTEM_PROMPT},
        {"role": "user", "content": f"{combined}\n\nUser question: {question}"},
    ]
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                "https://api.deepseek.com/chat/completions",
                headers={"Authorization": f"Bearer {DEEPSEEK_KEY}"},
                json={
                    "model": DEEPSEEK_MODEL,
                    "messages": messages,
                    "temperature": 0.3,
                    "max_tokens": 2500,
                },
            )
            r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"[run_macro_brief] ERROR: {e}")
        return f"Macro brief failed: {e}"
