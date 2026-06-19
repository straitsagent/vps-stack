"""Tests for planner.py — plan generation, tool execution, synthesis, fallback."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123:test")
os.environ.setdefault("TELEGRAM_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("TELEGRAM_OWNER_ID", "999")
os.environ.setdefault("DRAFTS_GROUP_ID", "")
os.environ.setdefault("WM_TOKEN", "test")
os.environ.setdefault("AGENT_DB_URL", "postgresql://test")
os.environ.setdefault("DEEPSEEK_KEY", "test")
os.environ.setdefault("XAI_KEY", "test")
os.environ.setdefault("FINNHUB_KEY", "test")
os.environ.setdefault("EXA_KEY", "test")

import pytest
import json
from unittest.mock import patch, AsyncMock, MagicMock

import planner


def test_parse_plan_valid_json():
    raw = '[{"tool":"portfolio_snapshot","args":{}},{"tool":"news_search","args":{"query":"NVDA"}}]'
    steps = planner._parse_plan(raw)
    assert len(steps) == 2
    assert steps[0]["tool"] == "portfolio_snapshot"


def test_parse_plan_invalid_json_returns_empty():
    steps = planner._parse_plan("not json at all")
    assert steps == []


def test_parse_plan_rejects_unknown_tools():
    raw = '[{"tool":"nonexistent_tool","args":{}}]'
    steps = planner._parse_plan(raw)
    assert steps == []


@pytest.mark.asyncio
async def test_plan_returns_steps_on_success():
    mock_resp = MagicMock()
    mock_resp.raise_for_status = lambda: None
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": '[{"tool":"portfolio_snapshot","args":{}}]'}}],
        "usage": {"total_tokens": 20},
    }
    with patch("planner.httpx.AsyncClient") as MockClient:
        MockClient.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_resp)
        steps = await planner.plan("portfolio_analysis", {}, "how is my portfolio doing?")
    assert len(steps) == 1
    assert steps[0]["tool"] == "portfolio_snapshot"


@pytest.mark.asyncio
async def test_plan_returns_empty_on_api_error():
    with patch("planner.httpx.AsyncClient") as MockClient:
        MockClient.return_value.__aenter__.return_value.post = AsyncMock(side_effect=Exception("timeout"))
        steps = await planner.plan("portfolio_analysis", {}, "test")
    assert steps == []


@pytest.mark.asyncio
async def test_synthesise_includes_tool_outputs_in_prompt():
    captured = {}
    mock_resp = MagicMock()
    mock_resp.raise_for_status = lambda: None
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": "unified answer"}}],
        "usage": {"total_tokens": 30},
    }

    async def fake_post(url, **kwargs):
        captured["messages"] = kwargs["json"]["messages"]
        return mock_resp

    with patch("planner.httpx.AsyncClient") as MockClient:
        MockClient.return_value.__aenter__.return_value.post = fake_post
        result = await planner.synthesise(
            "how is my portfolio?",
            {"portfolio_snapshot": "Portfolio: $1M total", "news_digest": "Markets up"},
        )
    user_content = captured["messages"][-1]["content"]
    assert "Portfolio: $1M total" in user_content
    assert "Markets up" in user_content
    assert result == "unified answer"


# ── Planner bug fix: earnings_calendar → earnings ─────────────────────────────

import planner


def test_planner_allowed_tools_has_earnings_not_earnings_calendar():
    """earnings_calendar was removed; the unified 'earnings' tool replaced it."""
    assert "earnings" in planner._ALLOWED_TOOLS, \
        "'earnings' not in _ALLOWED_TOOLS — MULTI_STEP flows can't call the earnings tool"
    assert "earnings_calendar" not in planner._ALLOWED_TOOLS, \
        "'earnings_calendar' still in _ALLOWED_TOOLS — this tool no longer exists"


def test_planner_system_prompt_no_earnings_calendar():
    """PLANNER_SYSTEM_PROMPT must not reference earnings_calendar (removed intent)."""
    assert "earnings_calendar" not in planner.PLANNER_SYSTEM_PROMPT, \
        "PLANNER_SYSTEM_PROMPT still describes 'earnings_calendar' — causes planner to emit dead tool calls"


def test_planner_system_prompt_has_earnings():
    """PLANNER_SYSTEM_PROMPT must describe the current 'earnings' tool."""
    assert "earnings" in planner.PLANNER_SYSTEM_PROMPT, \
        "PLANNER_SYSTEM_PROMPT missing 'earnings' tool description — planner can't select it"


# ── macro_brief synthesiser ───────────────────────────────────────────────────

def test_synthesise_macro_function_exists():
    """synthesise_macro must be exported from planner for macro_brief MULTI_STEP path."""
    assert hasattr(planner, "synthesise_macro"), \
        "planner.synthesise_macro missing — macro_brief MULTI_STEP path will fall back to generic synthesiser"


def test_macro_synthesiser_prompt_exists():
    """MACRO_SYNTHESISER_SYSTEM_PROMPT must be defined in planner."""
    assert hasattr(planner, "MACRO_SYNTHESISER_SYSTEM_PROMPT"), \
        "MACRO_SYNTHESISER_SYSTEM_PROMPT missing from planner"


def test_macro_synthesiser_prompt_has_sources_section():
    """MACRO_SYNTHESISER_SYSTEM_PROMPT must instruct model to list news sources."""
    assert "sources" in planner.MACRO_SYNTHESISER_SYSTEM_PROMPT.lower(), \
        "MACRO_SYNTHESISER_SYSTEM_PROMPT must mention 'sources' so the model lists news origins"


def test_macro_synthesiser_prompt_instructs_data_first():
    """MACRO_SYNTHESISER_SYSTEM_PROMPT must tell model to show data before commentary."""
    prompt = planner.MACRO_SYNTHESISER_SYSTEM_PROMPT.lower()
    assert "data" in prompt or "indicators" in prompt, \
        "MACRO_SYNTHESISER_SYSTEM_PROMPT must instruct model to output the data section"


@pytest.mark.asyncio
async def test_synthesise_macro_calls_deepseek():
    """synthesise_macro must call Deepseek and return its response."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status = lambda: None
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": "macro analysis"}}],
        "usage": {"total_tokens": 40},
    }
    with patch("planner.httpx.AsyncClient") as MockClient:
        MockClient.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_resp)
        result = await planner.synthesise_macro(
            "what is the macro picture?",
            {"macro_indicators": "*Macro — 19 Jun*\nVIX 18.4", "news_search": "• Fed holds rates"},
        )
    assert result == "macro analysis"
