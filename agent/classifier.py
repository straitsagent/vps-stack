import json
from typing import Optional

import httpx
from config import DEEPSEEK_KEY, DEEPSEEK_MODEL

SYSTEM_PROMPT = """You are an intent classifier for a personal assistant Telegram bot.
Classify the user message into exactly one of these intents and extract arguments.

Available intents and required args:
- portfolio_snapshot: {} — live prices and current P&L pulled from the database right now
- portfolio_digest: {} — latest stored portfolio email digest (last 6 AM or 6 PM report)
- ticker_detail: {"ticker": "SYMBOL"}
- live_prices: {}
- health_check: {}
- email_summary: {}
- news_digest: {} — latest stored morning news digest
- youtube_digest: {} — latest stored YouTube channel digest
- research: {"ticker": "SYMBOL or null", "research_type": "stock|strategy|macro|project", "depth": "brief|standard|deep", "question": "optional free-form question", "force": "true if user says 'force' or 'fresh' to bypass cache"}
- price_refresh: {}
- fundamentals_refresh: {}
- draft_send: {"draft_id": int}
- draft_edit: {"draft_id": int, "new_text": "replacement text"}
- draft_ignore: {"draft_id": int}
- add_contact: {"phone": "+E164", "name": "display name", "relationship": "type", "notes": "context"}
- set_autoreplyrule: {"phone": "+E164", "rule_prompt": "rule text"}
- outbound_message: {"contact_name_or_phone": "name or +E164", "message": "text to send"}
- thesis_read: {"ticker": "SYMBOL"} — retrieve stored investment thesis for a position
- thesis_write: {"ticker": "SYMBOL", "thesis": "text", "conviction": "High|Medium|Low", "catalysts": ["..."], "risks": ["..."]} — save or update investment thesis
- earnings: {"ticker": "SYMBOL or null"} — no ticker: upcoming earnings calendar for portfolio; with ticker: retrieve stored earnings analysis for that stock
- news_search: {"query": "search terms"} — ad hoc news search by topic or ticker
- macro_indicators: {} — SGD/USD, HKD/USD, VIX, Brent crude, 10Y UST snapshot
- portfolio_analysis: {} — multi-source portfolio health check (snapshot + news + fundamentals)
- thesis_check: {"ticker": "SYMBOL"} — evaluate thesis against current data (thesis + prices + news)
- macro_brief: {} — macro context mapped to portfolio exposure (macro + news + snapshot)
- earnings_analysis: {"ticker": "SYMBOL", "analysis_type": "pre|post"} — explicitly run a NEW pre-earnings briefing or post-earnings analysis via Windmill (takes ~60s)
- portfolio_rationalize: {"include_research": bool} — weekly portfolio rationalization analysis: score all positions, rank by quality/growth/value/sentiment, recommend which 15 to keep (FAST if recent file ≤30 days; otherwise dispatches Windmill job ~10 min). include_research=true adds full research reports to Grok synthesis (~longer runtime)
- candidate_evaluation: {"ticker": "SYMBOL", "universe_tickers": ["optional"], "thesis_text": "optional", "replacement_ticker": "optional"} — evaluate a stock as a portfolio addition candidate; 3-gate analysis (absolute + portfolio-fit + universe benchmark); produces ADD/WATCH/PASS verdict card with binding constraint (~60s)
- unknown: {}

Single-word shortcuts: "news" or "morning" → news_digest. "youtube" or "yt" → youtube_digest. "health" → health_check. "prices" → live_prices. "refresh" → price_refresh. "thesis" or "my view on" → thesis_read. "earnings" or "earnings TICKER" → earnings intent. "search" or "find news" → news_search. "macro" or "rates" → macro_indicators. "run earnings" or "fresh earnings" or "pre-earnings" or "post-earnings" or "run pre earnings" or "run post earnings" or "trigger earnings" → earnings_analysis. "rationalize" or "rationalise" or "portfolio rationalize" or "rationalization" or "trim portfolio" or "which stocks to keep" → portfolio_rationalize. "rationalize with research" or "full rationalization" or "deep rationalize" or "deep rationalise" → portfolio_rationalize with include_research=true. "evaluate TICKER" or "should I add TICKER" or "candidate TICKER" or "add TICKER" → candidate_evaluation.
Use portfolio_snapshot for "portfoliolive", "portfolio live", "live portfolio", "prices", "what are my prices now", "current portfolio". Use portfolio_digest for "portfoliodigest", "portfolio digest", "portfolio update", "portfolio email", "latest report".
Respond ONLY with valid JSON: {"intent": "...", "args": {...}, "confidence": 0.0-1.0}
No explanation."""


async def classify(text: str, history: list[dict]) -> dict:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for turn in history[-4:]:
        messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": text})

    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {DEEPSEEK_KEY}"},
            json={
                "model": DEEPSEEK_MODEL,
                "messages": messages,
                "temperature": 0.0,
                "max_tokens": 256,
            },
        )
        r.raise_for_status()

    raw = r.json()["choices"][0]["message"]["content"].strip()
    usage = r.json().get("usage", {})
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        result = {"intent": "unknown", "args": {}, "confidence": 0.0}

    result["router_tokens"] = usage.get("total_tokens", 0)
    return result


async def draft_reply(inbound: str, contact: Optional[dict]) -> str:
    """Generate a draft reply to an inbound contact message using Deepseek."""
    context = ""
    if contact:
        context = f"Contact notes: {contact.get('notes', '')}. Relationship: {contact.get('relationship', 'unknown')}."

    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {DEEPSEEK_KEY}"},
            json={
                "model": DEEPSEEK_MODEL,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            f"You are drafting a Telegram reply on behalf of the owner. {context} "
                            "Write a short, natural, friendly reply. No greeting prefix needed. "
                            "Keep it under 3 sentences."
                        ),
                    },
                    {"role": "user", "content": inbound},
                ],
                "temperature": 0.7,
                "max_tokens": 200,
            },
        )
        r.raise_for_status()

    return r.json()["choices"][0]["message"]["content"].strip()
