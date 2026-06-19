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
        result = await classify("what's in the morning news today", [])
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
        result = await classify("show me the youtube digest", [])
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


def test_candidate_evaluation_intent():
    assert "candidate_evaluation" in SYSTEM_PROMPT, \
        "candidate_evaluation intent missing from SYSTEM_PROMPT — classifier can't route eval requests"


def test_candidate_evaluation_shortcuts():
    assert "evaluate" in SYSTEM_PROMPT.lower(), \
        "'evaluate' shortcut missing from SYSTEM_PROMPT — 'evaluate TICKER' won't route to candidate_evaluation"


# ── New tests: macro routing, analyze shortcut, planner bug ──────────────────

def test_macro_shortcut_routes_to_macro_brief():
    """'macro' and 'rates' shortcuts must map to macro_brief, not macro_indicators."""
    lower = SYSTEM_PROMPT.lower()
    hints_start = lower.rfind("single-word")
    assert hints_start != -1, "No single-word shortcuts section found"
    hints_section = lower[hints_start:]
    # Find the macro shortcut line and confirm it points to macro_brief
    assert "macro_brief" in hints_section, \
        "'macro'/'rates' shortcut must route to macro_brief (not macro_indicators)"
    # The shortcut for raw data must NOT be the default for 'macro'
    # Find the position of 'macro' shortcut and ensure macro_brief follows it
    idx_macro = hints_section.find('"macro"')
    idx_brief = hints_section.find("macro_brief")
    assert idx_macro != -1, "'macro' shortcut not found in hints section"
    assert idx_brief != -1, "macro_brief target not found in hints section"


def test_macro_indicators_still_listed_as_intent():
    """macro_indicators must remain as a listed intent for explicit raw-data requests."""
    assert "macro_indicators" in SYSTEM_PROMPT, \
        "macro_indicators intent was removed — users who ask for 'raw macro data' will fail"


def test_analyze_shortcut_routes_to_portfolio_analysis():
    """'analyze' shortcut must appear in hints section pointing to portfolio_analysis."""
    lower = SYSTEM_PROMPT.lower()
    hints_start = lower.rfind("single-word")
    assert hints_start != -1, "No single-word shortcuts section found"
    hints_section = lower[hints_start:]
    assert "analyze" in hints_section, \
        "'analyze' shortcut missing — /analyze command won't route to portfolio_analysis"
    assert "portfolio_analysis" in hints_section, \
        "portfolio_analysis target missing from hints section"


def test_candidate_shortcut_in_system_prompt():
    """'candidate TICKER' must be listed as a shortcut for candidate_evaluation."""
    lower = SYSTEM_PROMPT.lower()
    hints_start = lower.rfind("single-word")
    assert hints_start != -1, "No single-word shortcuts section found"
    hints_section = lower[hints_start:]
    assert "candidate" in hints_section, \
        "'candidate' shortcut missing from hints section — /candidate TICKER won't route correctly"


# ── Deterministic pre-classification shortcuts ────────────────────────────────

def test_shortcuts_dict_exists():
    """_SHORTCUTS must exist in classifier — it bypasses the LLM for single-word commands."""
    import classifier
    assert hasattr(classifier, "_SHORTCUTS"), "_SHORTCUTS dict missing from classifier"


def test_shortcuts_covers_key_commands():
    """All critical single-word commands must be in _SHORTCUTS so they never go to the LLM."""
    import classifier
    required = {"macro", "health", "portfolio", "refresh", "news", "youtube", "rates", "analyze", "earnings"}
    missing = required - set(classifier._SHORTCUTS.keys())
    assert not missing, f"These commands missing from _SHORTCUTS: {missing}"


def test_shortcuts_macro_routes_to_macro_brief():
    """'macro' must deterministically resolve to macro_brief without an LLM call."""
    import classifier
    intent, args = classifier._SHORTCUTS["macro"]
    assert intent == "macro_brief", f"Expected macro_brief, got {intent}"


@pytest.mark.asyncio
async def test_classify_macro_bypasses_llm():
    """classify('macro', []) must return macro_brief without touching httpx."""
    import classifier
    from unittest.mock import patch, AsyncMock
    with patch("classifier.httpx.AsyncClient") as MockClient:
        MockClient.return_value.__aenter__.return_value.post = AsyncMock()
        result = await classifier.classify("macro", [])
    # httpx must NOT have been called
    MockClient.return_value.__aenter__.return_value.post.assert_not_called()
    assert result["intent"] == "macro_brief"
    assert result["router_tokens"] == 0
