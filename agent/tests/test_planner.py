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
