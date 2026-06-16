"""Integration tests for tools.py — real DB queries, validates SQL against live schema."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123:test")
os.environ.setdefault("TELEGRAM_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("TELEGRAM_OWNER_ID", "999")
os.environ.setdefault("DRAFTS_GROUP_ID", "")
os.environ.setdefault("WM_TOKEN", "test")
_db_pass = os.environ.get("PORTFOLIO_DB_PASSWORD", "changeme")
os.environ.setdefault("AGENT_DB_URL", f"postgresql://portfolio_user:{_db_pass}@portfolio_postgres:5432/portfolio")
os.environ.setdefault("DEEPSEEK_KEY", "test")
os.environ.setdefault("XAI_KEY", "test")

import pytest
import psycopg2
from conftest import TEST_TICKER_THESIS, TEST_TICKER_RESEARCH

import tools
from tools import (
    portfolio_snapshot, ticker_detail, thesis_read, run_thesis_write,
    earnings, _check_research_cache,
)


# ── portfolio_snapshot ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_portfolio_snapshot_executes_without_error():
    r = await portfolio_snapshot({})
    assert isinstance(r["text"], str)
    assert len(r["text"]) > 0


# ── ticker_detail ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ticker_detail_no_ticker_returns_prompt():
    r = await ticker_detail({})
    assert "ticker" in r["text"].lower()


@pytest.mark.asyncio
async def test_ticker_detail_unknown_ticker_returns_not_found():
    r = await ticker_detail({"ticker": "ZZZZZZZ"})
    assert "No price data" in r["text"]


@pytest.mark.asyncio
async def test_ticker_detail_seeded_ticker_no_error(db_conn):
    """Exercises the analyst_target_usd / market_cap_usd fix — no KeyError on real data."""
    with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT ticker FROM portfolio_positions LIMIT 1")
        row = cur.fetchone()
    if row is None:
        pytest.skip("No seeded portfolio positions")
    ticker = row["ticker"]
    r = await ticker_detail({"ticker": ticker})
    assert isinstance(r["text"], str)
    assert ticker in r["text"]


# ── thesis_read / run_thesis_write ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_thesis_write_read_roundtrip(db_conn, clean_test_ticker_thesis):
    write_r = await run_thesis_write({
        "ticker": TEST_TICKER_THESIS,
        "thesis": "Test integration thesis",
        "conviction": "High",
        "catalysts": ["cat1", "cat2"],
        "risks": ["risk1"],
    })
    assert isinstance(write_r["text"], str)

    read_r = await thesis_read({"ticker": TEST_TICKER_THESIS})
    assert "Test integration thesis" in read_r["text"]
    assert TEST_TICKER_THESIS in read_r["text"]


# ── _check_research_cache ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_check_research_cache_no_row_returns_none():
    """Validates the array_length(sources,1) query runs without schema error."""
    import asyncio
    result = await asyncio.to_thread(_check_research_cache, "NONEXISTENT_XYZ_99", "stock")
    assert result is None


@pytest.mark.asyncio
async def test_check_research_cache_with_row_returns_source_count(db_conn, clean_research_reports):
    """Inserts a real row then validates source_count is computed via array_length."""
    import asyncio
    with db_conn.cursor() as cur:
        cur.execute(
            """INSERT INTO research_reports
               (question, research_type, depth, ticker, sources, est_cost_usd, content)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            ("test q", "stock", "deep", TEST_TICKER_RESEARCH,
             ["source_a", "source_b", "source_c"], 0.05, "test content"),
        )
    db_conn.commit()

    result = await asyncio.to_thread(_check_research_cache, TEST_TICKER_RESEARCH, "stock")
    assert result is not None
    assert result["source_count"] == 3
    assert result["depth"] == "deep"
    assert result["content"] == "test content"


# ── earnings (unified) SQL path ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_earnings_portfolio_sql_executes():
    """Validates the portfolio DB query path in the no-ticker calendar mode.
    Does not assert Finnhub live data — only that the DB + result structure are correct."""
    from unittest.mock import patch, AsyncMock, MagicMock
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"earningsCalendar": []}
    with patch("tools.httpx.AsyncClient") as MockClient:
        MockClient.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_resp)
        r = await earnings({})
    assert isinstance(r["text"], str)
