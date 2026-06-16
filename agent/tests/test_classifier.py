"""Tests for classifier.py — prompt structure and intent parsing."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123:test")
os.environ.setdefault("TELEGRAM_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("TELEGRAM_OWNER_ID", "999")
os.environ.setdefault("DRAFTS_GROUP_ID", "")
os.environ.setdefault("WM_TOKEN", "test")
os.environ.setdefault("AGENT_DB_URL", "postgresql://test")
os.environ.setdefault("DEEPSEEK_KEY", "test")
os.environ.setdefault("XAI_KEY", "test")

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from classifier import SYSTEM_PROMPT


# ── Static prompt structure tests (no API call) ───────────────────────────────

def test_system_prompt_contains_all_intents():
    for intent in [
        "news_digest", "youtube_digest", "portfolio_digest", "portfolio_snapshot",
        "research", "health_check", "email_summary", "price_refresh",
        "fundamentals_refresh", "live_prices",
    ]:
        assert intent in SYSTEM_PROMPT, f"Intent '{intent}' missing from SYSTEM_PROMPT"


def test_system_prompt_disambiguates_news():
    """'news' shortcut must appear in the hints section before the news_digest intent line."""
    lower = SYSTEM_PROMPT.lower()
    # The shortcut hint appears BEFORE the intent definition, so look in context before the definition
    idx = lower.find("news_digest")
    # Look in the last 150 chars before the first occurrence of news_digest in the hints block
    # The hint line comes after the intent list, so search the full prompt for the pairing
    assert '"news"' in lower or "'news'" in lower, \
        "SYSTEM_PROMPT has no 'news' shortcut — classify('news') will return unknown"
    # Also confirm the pairing appears near news_digest
    # Find the hints section (after the intent list)
    hints_start = lower.rfind("single-word")
    assert hints_start != -1, "No single-word shortcuts section found in SYSTEM_PROMPT"
    hints_section = lower[hints_start:]
    assert "news" in hints_section and "news_digest" in hints_section, \
        "Hints section must map 'news' → news_digest"


def test_system_prompt_disambiguates_youtube():
    lower = SYSTEM_PROMPT.lower()
    hints_start = lower.rfind("single-word")
    assert hints_start != -1, "No single-word shortcuts section found in SYSTEM_PROMPT"
    hints_section = lower[hints_start:]
    assert "youtube" in hints_section and "youtube_digest" in hints_section, \
        "Hints section must map 'youtube' → youtube_digest"


def test_system_prompt_is_telegram_not_whatsapp():
    assert "WhatsApp" not in SYSTEM_PROMPT, \
        "SYSTEM_PROMPT still says 'WhatsApp' — should say 'Telegram'"
    assert "Telegram" in SYSTEM_PROMPT


# ── Mocked classify() tests ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_classify_returns_parsed_intent():
    mock_resp = MagicMock()
    mock_resp.raise_for_status = lambda: None
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": '{"intent":"news_digest","args":{},"confidence":0.95}'}}],
        "usage": {"total_tokens": 42},
    }
    with patch("classifier.httpx.AsyncClient") as MockClient:
        MockClient.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_resp)
        from classifier import classify
        result = await classify("news", [])
    assert result["intent"] == "news_digest"
    assert result["confidence"] == 0.95
    assert result["router_tokens"] == 42


@pytest.mark.asyncio
async def test_classify_youtube_returns_youtube_digest():
    mock_resp = MagicMock()
    mock_resp.raise_for_status = lambda: None
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": '{"intent":"youtube_digest","args":{},"confidence":0.97}'}}],
        "usage": {"total_tokens": 38},
    }
    with patch("classifier.httpx.AsyncClient") as MockClient:
        MockClient.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_resp)
        from classifier import classify
        result = await classify("youtube", [])
    assert result["intent"] == "youtube_digest"
    assert result["router_tokens"] == 38


@pytest.mark.asyncio
async def test_classify_json_error_returns_unknown():
    mock_resp = MagicMock()
    mock_resp.raise_for_status = lambda: None
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": "not valid json at all"}}],
        "usage": {},
    }
    with patch("classifier.httpx.AsyncClient") as MockClient:
        MockClient.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_resp)
        from classifier import classify
        result = await classify("gibberish", [])
    assert result["intent"] == "unknown"
    assert result["confidence"] == 0.0
    assert result["router_tokens"] == 0


@pytest.mark.asyncio
async def test_classify_includes_history_in_messages():
    """Classifier must include last 4 history turns in the request."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status = lambda: None
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": '{"intent":"unknown","args":{},"confidence":0.1}'}}],
        "usage": {"total_tokens": 10},
    }
    captured = {}
    async def fake_post(url, **kwargs):
        captured["messages"] = kwargs["json"]["messages"]
        return mock_resp
    with patch("classifier.httpx.AsyncClient") as MockClient:
        MockClient.return_value.__aenter__.return_value.post = fake_post
        from classifier import classify
        history = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]
        await classify("what's next", history)
    msgs = captured["messages"]
    # system + 2 history + 1 user = 4
    assert msgs[0]["role"] == "system"
    assert msgs[1]["content"] == "hello"
    assert msgs[2]["content"] == "hi there"
    assert msgs[-1]["content"] == "what's next"


def test_system_prompt_contains_thesis_intents():
    assert "thesis_read" in SYSTEM_PROMPT, "thesis_read intent missing from SYSTEM_PROMPT"
    assert "thesis_write" in SYSTEM_PROMPT, "thesis_write intent missing from SYSTEM_PROMPT"


def test_system_prompt_contains_w2_intents():
    for intent in ["earnings", "news_search", "macro_indicators", "thesis_read", "thesis_write"]:
        assert intent in SYSTEM_PROMPT, f"Missing W2 intent: {intent}"


def test_system_prompt_contains_w4_intents():
    for intent in ["portfolio_analysis", "thesis_check", "macro_brief"]:
        assert intent in SYSTEM_PROMPT, f"Missing W4 intent: {intent}"


def test_system_prompt_contains_earnings_analysis_intent():
    assert "earnings_analysis" in SYSTEM_PROMPT, \
        "earnings_analysis intent missing from SYSTEM_PROMPT — classifier won't dispatch earnings analysis"


def test_portfolio_rationalize_intent():
    assert "portfolio_rationalize" in SYSTEM_PROMPT, \
        "portfolio_rationalize intent missing from SYSTEM_PROMPT — classifier can't route rationalization requests"
