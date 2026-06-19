"""Tests for pure functions in tools.py — no DB or Windmill calls."""
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

import tempfile
import unittest.mock
import pytest
from unittest.mock import patch, AsyncMock

import tools
from tools import (
    _read_latest_research_file, news_digest, youtube_digest, portfolio_digest,
    format_research_result, _SUMMARISE_THRESHOLD,
    TOOL_CLASSES, FAST_EXECUTORS, FIRE_EXECUTORS, GATED_WRITE_EXECUTORS,
)
from config import FAST, FIRE, GATED_WRITE


def test_format_research_result_full():
    result = {
        "preview": "NVDA is a leading GPU maker...",
        "source_count": 58,
        "est_cost_usd": 0.055,
        "file_path": "/research/stocks/2026-06-10_nvda.md",
    }
    text = format_research_result(result)
    assert "58 sources" in text
    assert "$0.055" in text
    assert "NVDA is a leading GPU maker" in text
    assert "/research/stocks/2026-06-10_nvda.md" in text


def test_format_research_result_zero_sources():
    result = {"source_count": 0, "est_cost_usd": 0.0}
    text = format_research_result(result)
    assert "0 sources" in text
    assert "$0.000" in text


def test_format_research_result_no_crash_on_empty():
    text = format_research_result({})
    assert isinstance(text, str)
    assert len(text) > 0


def test_format_research_result_no_file_path():
    result = {"preview": "test", "source_count": 5, "est_cost_usd": 0.01}
    text = format_research_result(result)
    assert "Full report" not in text


def test_format_research_result_uses_preview_over_synthesis():
    result = {
        "preview": "short preview",
        "synthesis": "long synthesis that should not appear",
        "source_count": 1,
        "est_cost_usd": 0.01,
    }
    text = format_research_result(result)
    assert "short preview" in text
    assert "long synthesis that should not appear" not in text


# ── _read_latest_research_file ────────────────────────────────────────────────

def test_read_latest_empty_dir():
    with tempfile.TemporaryDirectory() as d:
        assert _read_latest_research_file(d) is None


def test_read_latest_picks_alpha_last():
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "2026-06-08.md"), "w") as f:
            f.write("old")
        with open(os.path.join(d, "2026-06-10.md"), "w") as f:
            f.write("new")
        assert _read_latest_research_file(d) == "new"


def test_read_latest_timestamped_files():
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "2026-06-10_0600.md"), "w") as f:
            f.write("morning")
        with open(os.path.join(d, "2026-06-10_1200.md"), "w") as f:
            f.write("noon")
        assert _read_latest_research_file(d) == "noon"


def test_read_latest_ignores_non_md():
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "2026-06-10.md"), "w") as f:
            f.write("correct")
        with open(os.path.join(d, "notes.txt"), "w") as f:
            f.write("wrong")
        assert _read_latest_research_file(d) == "correct"


# ── digest tools — no-file fallback ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_news_digest_no_file():
    with patch.object(tools, "_read_latest_research_file", return_value=None):
        r = await news_digest({})
    assert "No news digest" in r["text"]


@pytest.mark.asyncio
async def test_youtube_digest_no_file():
    with patch.object(tools, "_read_latest_research_file", return_value=None):
        r = await youtube_digest({})
    assert "No YouTube digest" in r["text"]


@pytest.mark.asyncio
async def test_portfolio_digest_no_file():
    with patch.object(tools, "_read_latest_research_file", return_value=None):
        r = await portfolio_digest({})
    assert "No portfolio digest" in r["text"]


# ── digest tools — short content passes through ───────────────────────────────

@pytest.mark.asyncio
async def test_news_digest_short_content_passthrough():
    with patch.object(tools, "_read_latest_research_file", return_value="short content"):
        r = await news_digest({})
    assert r["text"] == "short content"


@pytest.mark.asyncio
async def test_youtube_digest_short_content_passthrough():
    with patch.object(tools, "_read_latest_research_file", return_value="short content"):
        r = await youtube_digest({})
    assert r["text"] == "short content"


# ── digest tools — long content triggers summarisation ────────────────────────

@pytest.mark.asyncio
async def test_news_digest_long_content_calls_summarise():
    long_content = "x" * (_SUMMARISE_THRESHOLD + 1)
    calls = []
    async def fake_summarise(content, dtype):
        calls.append(dtype)
        return "summary"
    with patch.object(tools, "_read_latest_research_file", return_value=long_content):
        with patch.object(tools, "_summarise_for_telegram", fake_summarise):
            r = await news_digest({})
    assert calls == ["news"]
    assert r["text"] == "summary"


@pytest.mark.asyncio
async def test_youtube_digest_long_content_calls_summarise():
    long_content = "x" * (_SUMMARISE_THRESHOLD + 1)
    calls = []
    async def fake_summarise(content, dtype):
        calls.append(dtype)
        return "summary"
    with patch.object(tools, "_read_latest_research_file", return_value=long_content):
        with patch.object(tools, "_summarise_for_telegram", fake_summarise):
            r = await youtube_digest({})
    assert calls == ["youtube"]
    assert r["text"] == "summary"


# ── tool registry consistency ─────────────────────────────────────────────────

def test_all_fast_tool_classes_have_executors():
    for intent, cls in TOOL_CLASSES.items():
        if cls == FAST:
            assert intent in FAST_EXECUTORS, f"FAST intent '{intent}' missing from FAST_EXECUTORS"


def test_all_fire_tool_classes_have_executors():
    for intent, cls in TOOL_CLASSES.items():
        if cls == FIRE:
            assert intent in FIRE_EXECUTORS, f"FIRE intent '{intent}' missing from FIRE_EXECUTORS"


def test_all_gated_write_tool_classes_have_executors():
    for intent, cls in TOOL_CLASSES.items():
        if cls == GATED_WRITE:
            assert intent in GATED_WRITE_EXECUTORS, f"GATED_WRITE intent '{intent}' missing from GATED_WRITE_EXECUTORS"


# ── portfolio_thesis tool tests ────────────────────────────────────────────────

from tools import thesis_read


@pytest.mark.asyncio
async def test_thesis_read_no_ticker_returns_error():
    r = await thesis_read({})
    assert "ticker" in r["text"].lower()


@pytest.mark.asyncio
async def test_thesis_read_no_data_returns_not_found():
    with patch.object(tools, "_query", return_value=[]):
        r = await thesis_read({"ticker": "NVDA"})
    assert "no thesis" in r["text"].lower()


@pytest.mark.asyncio
async def test_thesis_read_returns_formatted_thesis():
    from datetime import date
    row = {
        "ticker": "NVDA",
        "investment_thesis": "GPU monopoly in AI era",
        "key_catalysts": ["data centre ramp", "Blackwell launch"],
        "risks": ["AMD competition"],
        "conviction": "High",
        "thesis_date": date(2026, 6, 10),
        "updated_at": date(2026, 6, 10),
    }
    with patch.object(tools, "_query", return_value=[row]):
        r = await thesis_read({"ticker": "NVDA"})
    assert "GPU monopoly" in r["text"]
    assert "NVDA" in r["text"]


def test_thesis_read_is_fast():
    assert TOOL_CLASSES.get("thesis_read") == FAST


def test_thesis_write_is_gated_write():
    assert TOOL_CLASSES.get("thesis_write") == GATED_WRITE


# ── W2 tool tests: earnings (unified), news_search, macro_indicators ─────────

import httpx
from unittest.mock import AsyncMock, MagicMock
from tools import earnings, news_search, macro_indicators


@pytest.mark.asyncio
async def test_earnings_no_ticker_uses_portfolio():
    with patch.object(tools, "_query", return_value=[]):
        with patch("tools.glob.glob", return_value=[]):
            r = await earnings({})
    assert isinstance(r["text"], str)


@pytest.mark.asyncio
async def test_earnings_api_error_returns_fallback():
    with patch("tools.glob.glob", return_value=[]):
        with patch("tools.httpx.AsyncClient") as M:
            M.return_value.__aenter__.return_value.get = AsyncMock(side_effect=Exception("timeout"))
            r = await earnings({"ticker": "AAPL"})
    assert isinstance(r["text"], str)
    assert any(w in r["text"].lower() for w in ("unavailable", "error", "failed", "no earnings", "no analysis"))


@pytest.mark.asyncio
async def test_earnings_formats_upcoming_date():
    mock_data = {"earningsCalendar": [{"date": "2026-07-15", "epsEstimate": 1.25, "symbol": "AAPL"}]}
    mock_resp = MagicMock()
    mock_resp.json.return_value = mock_data
    with patch.object(tools, "_query", return_value=[{"ticker": "AAPL"}]):
        with patch("tools.glob.glob", return_value=[]):
            with patch("tools.httpx.AsyncClient") as M:
                M.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_resp)
                r = await earnings({})
    assert "AAPL" in r["text"]
    assert "2026-07-15" in r["text"]


@pytest.mark.asyncio
async def test_news_search_requires_query():
    r = await news_search({})
    assert any(w in r["text"].lower() for w in ("query", "search", "topic"))


@pytest.mark.asyncio
async def test_news_search_api_error_returns_fallback():
    with patch("tools.httpx.AsyncClient") as M:
        M.return_value.__aenter__.return_value.post = AsyncMock(side_effect=Exception("timeout"))
        r = await news_search({"query": "NVDA earnings"})
    assert isinstance(r["text"], str)


@pytest.mark.asyncio
async def test_news_search_formats_results():
    mock_data = {"results": [{"title": "NVDA beats estimates", "url": "https://example.com", "summary": "strong quarter"}]}
    mock_resp = MagicMock()
    mock_resp.json.return_value = mock_data
    with patch("tools.httpx.AsyncClient") as M:
        M.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_resp)
        r = await news_search({"query": "NVDA"})
    assert "NVDA beats" in r["text"]


@pytest.mark.asyncio
async def test_macro_indicators_api_error_returns_fallback():
    with patch("tools.httpx.AsyncClient") as M:
        M.return_value.__aenter__.return_value.get = AsyncMock(side_effect=Exception("timeout"))
        r = await macro_indicators({})
    assert isinstance(r["text"], str)


@pytest.mark.asyncio
async def test_macro_indicators_returns_expected_symbols():
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "chart": {"result": [{"meta": {"regularMarketPrice": 1.34}, "timestamp": [1000], "indicators": {"quote": [{"close": [1.34, 1.33]}]}}]}
    }
    with patch("tools.httpx.AsyncClient") as M:
        M.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_resp)
        r = await macro_indicators({})
    text = r["text"]
    assert any(sym in text for sym in ["SGD", "HKD", "VIX", "Brent", "UST", "macro"])


def test_macro_indicators_is_fast():
    assert TOOL_CLASSES.get("macro_indicators") == FAST


# ── dispatch_research / _check_research_cache tests ───────────────────────────

from tools import dispatch_research, _check_research_cache
from unittest.mock import call
from datetime import datetime, timezone


def test_check_research_cache_selects_correct_columns():
    """Verify _check_research_cache uses columns that actually exist in research_reports."""
    executed = {}
    mock_cursor = MagicMock()
    mock_cursor.__enter__ = lambda s: s
    mock_cursor.__exit__ = MagicMock(return_value=False)
    mock_cursor.fetchone.return_value = None

    mock_conn = MagicMock()
    mock_conn.__enter__ = lambda s: s
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.cursor.return_value = mock_cursor

    def capture_execute(sql, params):
        executed["sql"] = sql

    mock_cursor.execute.side_effect = capture_execute

    with patch.object(tools, "_pg_conn", return_value=mock_conn):
        _check_research_cache("NVDA", "stock")

    sql = executed["sql"]
    # Must NOT reference source_count as a bare column — it's computed via array_length
    assert "source_count" not in sql or "array_length" in sql, (
        "SQL references source_count column which does not exist — use array_length(sources,1)"
    )
    # Must reference columns that actually exist in research_reports
    assert "content" in sql
    assert "file_path" in sql
    assert "est_cost_usd" in sql
    assert "created_at" in sql
    assert "depth" in sql


@pytest.mark.asyncio
async def test_dispatch_research_no_cache_returns_ack_and_job_id():
    with patch.object(tools, "_check_research_cache", return_value=None):
        with patch("tools.run_job", return_value="job-abc-123") as mock_run:
            result = await dispatch_research({"ticker": "NVDA", "depth": "deep"}, "+1234567890")
    assert "job_id" in result
    assert result["job_id"] == "job-abc-123"
    assert "NVDA" in result["text"]
    assert mock_run.called


@pytest.mark.asyncio
async def test_dispatch_research_recent_cache_returns_directly():
    """Cache <30d → returns immediately with cached content, job_id=None."""
    from datetime import timedelta
    cache_row = {
        "content": "NVDA is a leading GPU maker for AI workloads.",
        "file_path": "/research/stock/2026-06-01_nvda.md",
        "source_count": 42,
        "est_cost_usd": 0.05,
        "created_at": datetime.now(timezone.utc) - timedelta(days=5),
        "depth": "deep",
    }
    with patch.object(tools, "_check_research_cache", return_value=cache_row):
        result = await dispatch_research({"ticker": "NVDA"}, "+1234567890")
    assert result["job_id"] is None
    assert "NVDA is a leading GPU maker" in result["text"]


@pytest.mark.asyncio
async def test_dispatch_research_recent_cache_no_job_dispatched():
    """Cache <30d → run_job must never be called."""
    from datetime import timedelta
    cache_row = {
        "content": "some prior research",
        "file_path": "/research/stock/2026-06-01_nvda.md",
        "source_count": 10,
        "est_cost_usd": 0.03,
        "created_at": datetime.now(timezone.utc) - timedelta(days=10),
        "depth": "standard",
    }
    with patch.object(tools, "_check_research_cache", return_value=cache_row):
        with patch("tools.run_job") as mock_run:
            await dispatch_research({"ticker": "NVDA"}, "+1234567890")
    mock_run.assert_not_called()


@pytest.mark.asyncio
async def test_dispatch_research_no_cache_stock_forces_deep():
    """No cache + research_type=stock → dispatches depth=deep regardless of args."""
    with patch.object(tools, "_check_research_cache", return_value=None):
        with patch("tools.run_job", return_value="job-deep") as mock_run:
            await dispatch_research(
                {"ticker": "NVDA", "research_type": "stock", "depth": "standard"},
                "+1234567890",
            )
    _, wm_args = mock_run.call_args[0]
    assert wm_args["depth"] == "deep"


@pytest.mark.asyncio
async def test_dispatch_research_no_cache_strategy_respects_depth():
    """No cache + research_type=strategy + depth=standard → dispatches standard."""
    with patch.object(tools, "_check_research_cache", return_value=None):
        with patch("tools.run_job", return_value="job-std") as mock_run:
            await dispatch_research(
                {"research_type": "strategy", "depth": "standard", "question": "US rate outlook"},
                "+1234567890",
            )
    _, wm_args = mock_run.call_args[0]
    assert wm_args["depth"] == "standard"


def test_format_research_result_includes_date():
    """format_research_result must include today's date in the header line."""
    from datetime import date
    today = date.today().strftime("%Y-%m-%d")
    result = {"preview": "test content", "source_count": 5, "est_cost_usd": 0.01}
    text = format_research_result(result)
    assert today in text


@pytest.mark.asyncio
async def test_dispatch_research_force_bypasses_cache():
    with patch.object(tools, "_check_research_cache") as mock_cache:
        with patch("tools.run_job", return_value="job-force"):
            result = await dispatch_research({"ticker": "NVDA", "force": True}, "+1234567890")
    mock_cache.assert_not_called()
    assert result["has_synopsis"] is False


# ── Source-inspection regression tests ───────────────────────────────────────

def test_ticker_detail_uses_correct_fundamental_column_names():
    """Catches column name regressions without hitting the DB."""
    import inspect
    src = inspect.getsource(tools.ticker_detail)
    assert "analyst_target_usd" in src, "ticker_detail must use analyst_target_usd"
    assert "market_cap_usd" in src, "ticker_detail must use market_cap_usd"
    assert "price_target" not in src, "price_target column does not exist in fundamental_data"
    assert '"market_cap"' not in src, "bare market_cap column does not exist — use market_cap_usd"


@pytest.mark.asyncio
async def test_portfolio_digest_short_content_passthrough():
    with patch.object(tools, "_read_latest_research_file", return_value="short content"):
        r = await portfolio_digest({})
    assert r["text"] == "short content"


def test_check_research_cache_uses_array_length():
    """Regression: source_count is not a column — array_length(sources,1) required."""
    import inspect
    src = inspect.getsource(tools._check_research_cache)
    assert "array_length" in src, "Must use array_length(sources,1) not bare source_count column"


# ── earnings_analysis ASYNC_NOTIFY tests ─────────────────────────────────────

def test_earnings_analysis_is_async_notify():
    from config import ASYNC_NOTIFY
    assert TOOL_CLASSES.get("earnings_analysis") == ASYNC_NOTIFY, \
        "earnings_analysis must be ASYNC_NOTIFY in TOOL_CLASSES"


def test_earnings_analysis_in_async_notify_executors():
    from tools import ASYNC_NOTIFY_EXECUTORS
    assert "earnings_analysis" in ASYNC_NOTIFY_EXECUTORS, \
        "earnings_analysis missing from ASYNC_NOTIFY_EXECUTORS"


# ── Unified earnings FAST tool tests ─────────────────────────────────────────

def test_earnings_is_fast_tool():
    """earnings must be a FAST tool and earnings_calendar must be gone."""
    assert TOOL_CLASSES.get("earnings") == FAST, \
        "earnings must be FAST in TOOL_CLASSES"
    assert "earnings_calendar" not in TOOL_CLASSES, \
        "earnings_calendar must be removed from TOOL_CLASSES"


def test_earnings_is_in_fast_executors():
    """earnings must be registered in FAST_EXECUTORS."""
    assert "earnings" in FAST_EXECUTORS, \
        "earnings missing from FAST_EXECUTORS"
    assert "earnings_calendar" not in FAST_EXECUTORS, \
        "earnings_calendar must be removed from FAST_EXECUTORS"


@pytest.mark.asyncio
async def test_earnings_reads_file_when_ticker_provided():
    """earnings(ticker=ADBE) must return the content of the latest matching .md file."""
    from tools import earnings
    fake_content = "# ADBE Pre-Earnings Briefing\n**Date written:** 2026-06-11\n..."
    with patch("tools.glob.glob", return_value=["2026-06-11_ADBE_pre.md"]):
        with patch("builtins.open", unittest.mock.mock_open(read_data=fake_content)):
            r = await earnings({"ticker": "ADBE"})
    assert fake_content in r["text"]


@pytest.mark.asyncio
async def test_earnings_shows_calendar_when_no_ticker():
    """earnings({}) with no ticker must call Finnhub (calendar mode)."""
    from tools import earnings
    from unittest.mock import AsyncMock, MagicMock
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"earningsCalendar": [
        {"date": "2026-07-15", "epsEstimate": 1.25, "symbol": "AAPL"}
    ]}
    with patch.object(tools, "_query", return_value=[{"ticker": "AAPL"}]):
        with patch("tools.httpx.AsyncClient") as M:
            M.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_resp)
            r = await earnings({})
    assert "AAPL" in r["text"]


@pytest.mark.asyncio
async def test_earnings_no_file_falls_back_to_finnhub():
    """earnings(ticker=MSFT) when no matching file exists must call Finnhub for that ticker."""
    from tools import earnings
    from unittest.mock import AsyncMock, MagicMock
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"earningsCalendar": [
        {"date": "2026-07-24", "epsEstimate": 3.10, "symbol": "MSFT"}
    ]}
    with patch("tools.glob.glob", return_value=[]):
        with patch("tools.httpx.AsyncClient") as M:
            M.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_resp)
            r = await earnings({"ticker": "MSFT"})
    assert "MSFT" in r["text"] or "no" in r["text"].lower()


# ── serper_key wired into dispatch_research ───────────────────────────────────

@pytest.mark.asyncio
async def test_dispatch_research_includes_serper_key_in_wm_args():
    """dispatch_research must pass serper_key to wm_args so research_tool can call Serper."""
    with patch.object(tools, "_check_research_cache", return_value=None):
        with patch("tools.run_job", return_value="job-serper-test") as mock_run:
            await dispatch_research({"ticker": "NVDA", "depth": "standard"}, "+1234567890")
    _, wm_args = mock_run.call_args[0]
    assert "serper_key" in wm_args, (
        "dispatch_research must include serper_key in wm_args — "
        "research_tool.py now requires it for Serper news at brief/standard depth"
    )


# ── tavily_key, brave_key, fred_key wired into dispatch_research ──────────────

@pytest.mark.asyncio
async def test_dispatch_research_includes_tavily_key():
    """dispatch_research must pass tavily_key to wm_args."""
    with patch.object(tools, "_check_research_cache", return_value=None):
        with patch("tools.run_job", return_value="job-tavily-test") as mock_run:
            await dispatch_research({"ticker": "NVDA", "depth": "standard"}, "+1234567890")
    _, wm_args = mock_run.call_args[0]
    assert "tavily_key" in wm_args, (
        "dispatch_research must include tavily_key in wm_args — "
        "research_tool.py uses it for Tavily search at standard/deep depth"
    )


@pytest.mark.asyncio
async def test_dispatch_research_includes_brave_key():
    """dispatch_research must pass brave_key to wm_args."""
    with patch.object(tools, "_check_research_cache", return_value=None):
        with patch("tools.run_job", return_value="job-brave-test") as mock_run:
            await dispatch_research({"ticker": "NVDA", "depth": "standard"}, "+1234567890")
    _, wm_args = mock_run.call_args[0]
    assert "brave_key" in wm_args, (
        "dispatch_research must include brave_key in wm_args — "
        "research_tool.py uses it for Brave Search at standard/deep depth"
    )


@pytest.mark.asyncio
async def test_dispatch_research_includes_fred_key():
    """dispatch_research must pass fred_key to wm_args."""
    with patch.object(tools, "_check_research_cache", return_value=None):
        with patch("tools.run_job", return_value="job-fred-test") as mock_run:
            await dispatch_research({"ticker": "NVDA", "depth": "standard"}, "+1234567890")
    _, wm_args = mock_run.call_args[0]
    assert "fred_key" in wm_args, (
        "dispatch_research must include fred_key in wm_args — "
        "research_tool.py uses it for FRED macro data at standard/deep depth"
    )


# ── macro_indicators — currency direction + format ───────────────────────────

def test_macro_symbols_use_usd_base_labels():
    """Currency labels must be USD/SGD and USD/HKD (not SGD/USD, HKD/USD)."""
    labels = [v[0] if isinstance(v, tuple) else v for v in tools._MACRO_SYMBOLS.values()]
    assert "USD/SGD" in labels, "USD/SGD label missing from _MACRO_SYMBOLS"
    assert "USD/HKD" in labels, "USD/HKD label missing from _MACRO_SYMBOLS"
    assert "SGD/USD" not in labels, "SGD/USD still in _MACRO_SYMBOLS — should be USD/SGD"
    assert "HKD/USD" not in labels, "HKD/USD still in _MACRO_SYMBOLS — should be USD/HKD"


def test_macro_symbols_fx_marked_for_inversion():
    """SGDUSD=X and HKDUSD=X must be marked invert=True so reciprocal is displayed."""
    for sym in ("SGDUSD=X", "HKDUSD=X"):
        entry = tools._MACRO_SYMBOLS[sym]
        assert isinstance(entry, tuple) and entry[1] is True, \
            f"{sym} must be (label, True) to flag reciprocal display"


@pytest.mark.asyncio
async def test_macro_indicators_output_has_date():
    """macro_indicators output must start with a date-stamped header."""
    mock_result = {
        "chart": {"result": [{
            "indicators": {"quote": [{"close": [0.745, 0.746]}]}
        }]}
    }
    mock_resp = unittest.mock.MagicMock()
    mock_resp.json.return_value = mock_result

    with patch("tools.httpx.AsyncClient") as MockClient:
        MockClient.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_resp)
        result = await tools.macro_indicators({})

    import re
    assert re.search(r"Macro.*(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)", result["text"]), \
        "macro_indicators output must have a date header like '*Macro — 19 Jun 2026*'"


@pytest.mark.asyncio
async def test_macro_indicators_inverts_fx_values():
    """USD/SGD value must be > 1 (reciprocal of ~0.74 Yahoo rate)."""
    def make_resp(close_val):
        m = unittest.mock.MagicMock()
        m.json.return_value = {
            "chart": {"result": [{
                "indicators": {"quote": [{"close": [close_val - 0.001, close_val]}]}
            }]}
        }
        return m

    fx_resp = make_resp(0.745)   # SGDUSD=X — Yahoo gives ~0.745 for SGD in USD
    other_resp = make_resp(18.5) # generic for VIX, Brent, TNX

    call_count = 0
    async def fake_get(url, **kwargs):
        nonlocal call_count
        call_count += 1
        if "SGDUSD" in url or "HKDUSD" in url:
            return make_resp(0.745)
        return other_resp

    with patch("tools.httpx.AsyncClient") as MockClient:
        MockClient.return_value.__aenter__.return_value.get = fake_get
        result = await tools.macro_indicators({})

    text = result["text"]
    assert "USD/SGD" in text
    # Value shown must be reciprocal: 1/0.745 ≈ 1.342, definitely > 1.0
    import re
    m = re.search(r"USD/SGD\s+([\d.]+)", text)
    assert m, "Could not find USD/SGD value in output"
    assert float(m.group(1)) > 1.0, \
        f"USD/SGD value should be ~1.34 (reciprocal of 0.745), got {m.group(1)}"
