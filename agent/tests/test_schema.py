"""Schema validation — every column name used in tools.py and db.py must exist in the live DB.
These tests catch code-schema mismatches (like the source_count bug) before deployment.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123:test")
os.environ.setdefault("TELEGRAM_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("TELEGRAM_OWNER_ID", "999")
os.environ.setdefault("DRAFTS_GROUP_ID", "")
os.environ.setdefault("WM_TOKEN", "test")
_db_pass = os.environ.get("PORTFOLIO_DB_PASSWORD", "changeme")
os.environ.setdefault("AGENT_DB_URL", f"postgresql://portfolio_user:{_db_pass}@portfolio_postgres:5432/portfolio")
os.environ.setdefault("DEEPSEEK_KEY", "test")
os.environ.setdefault("XAI_KEY", "test")

import psycopg2
import pytest


def _get_columns(db_conn, table_name: str) -> set:
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
            (table_name,),
        )
        return {r[0] for r in cur.fetchall()}


def test_fundamental_data_columns(db_conn):
    cols = _get_columns(db_conn, "fundamental_data")
    assert "analyst_target_usd" in cols, "fundamental_data.analyst_target_usd missing"
    assert "market_cap_usd" in cols, "fundamental_data.market_cap_usd missing"
    assert "pe_ratio" in cols
    assert "pb_ratio" in cols
    assert "roe" in cols
    assert "roic" in cols
    # Regression: old wrong column names used in ticker_detail before fix
    assert "price_target" not in cols, "price_target does not exist — use analyst_target_usd"
    assert "market_cap" not in cols, "market_cap does not exist — use market_cap_usd"


def test_research_reports_columns(db_conn):
    cols = _get_columns(db_conn, "research_reports")
    assert cols, "research_reports table does not exist or has no columns"
    for col in ["question", "research_type", "depth", "ticker", "file_path",
                "sources", "search_queries", "est_cost_usd", "content", "created_at"]:
        assert col in cols, f"research_reports.{col} missing"


def test_portfolio_positions_columns(db_conn):
    cols = _get_columns(db_conn, "portfolio_positions")
    for col in ["ticker", "company_name", "shares", "currency", "consolidation_group"]:
        assert col in cols, f"portfolio_positions.{col} missing"


def test_price_history_columns(db_conn):
    cols = _get_columns(db_conn, "price_history")
    for col in ["ticker", "price_date", "close_price", "currency"]:
        assert col in cols, f"price_history.{col} missing"


def test_fx_rates_columns(db_conn):
    cols = _get_columns(db_conn, "fx_rates")
    for col in ["rate_date", "from_currency", "to_currency", "rate"]:
        assert col in cols, f"fx_rates.{col} missing"


def test_agent_conversation_history_columns(db_conn):
    cols = _get_columns(db_conn, "agent_conversation_history")
    for col in ["wa_phone", "role", "content", "tool_called", "tool_args", "created_at"]:
        assert col in cols, f"agent_conversation_history.{col} missing"


def test_agent_pending_jobs_columns(db_conn):
    cols = _get_columns(db_conn, "agent_pending_jobs")
    for col in ["job_id", "wa_phone", "tool_name", "tool_args", "status",
                "dispatched_at", "completed_at", "result_preview", "error_message"]:
        assert col in cols, f"agent_pending_jobs.{col} missing"


def test_agent_pending_confirmations_columns(db_conn):
    cols = _get_columns(db_conn, "agent_pending_confirmations")
    for col in ["wa_phone", "tool_name", "tool_args", "status", "created_at", "expires_at"]:
        assert col in cols, f"agent_pending_confirmations.{col} missing"


def test_agent_draft_queue_columns(db_conn):
    cols = _get_columns(db_conn, "agent_draft_queue")
    for col in ["wa_phone", "inbound_text", "draft_reply", "status", "notified_at", "resolved_at"]:
        assert col in cols, f"agent_draft_queue.{col} missing"


def test_agent_contact_rules_columns(db_conn):
    cols = _get_columns(db_conn, "agent_contact_rules")
    for col in ["wa_phone", "display_name", "relationship", "auto_reply", "rule_prompt", "notes"]:
        assert col in cols, f"agent_contact_rules.{col} missing"


def test_portfolio_thesis_columns(db_conn):
    cols = _get_columns(db_conn, "portfolio_thesis")
    for col in ["ticker", "investment_thesis", "key_catalysts", "risks", "conviction",
                "target_price_usd", "thesis_date", "updated_at"]:
        assert col in cols, f"portfolio_thesis.{col} missing"


def test_earnings_analyses_columns(db_conn):
    cols = _get_columns(db_conn, "earnings_analyses")
    assert cols, "earnings_analyses table does not exist or has no columns"
    for col in ["ticker", "analysis_type", "earnings_date", "eps_estimate",
                "eps_actual", "recommendation", "content", "file_path", "created_at"]:
        assert col in cols, f"earnings_analyses.{col} missing"


# ── Stock Research Structured Data Store — new tables ────────────────────────

def test_income_statements_table_exists_in_db(db_conn):
    cols = _get_columns(db_conn, "income_statements")
    assert cols, "income_statements table missing from DB"
    for col in ["ticker", "fiscal_year_end", "total_revenue", "gross_profit",
                "operating_income", "ebitda", "net_income", "basic_eps", "fetched_date"]:
        assert col in cols, f"income_statements.{col} missing"


def test_valuation_snapshots_table_exists_in_db(db_conn):
    cols = _get_columns(db_conn, "valuation_snapshots")
    assert cols, "valuation_snapshots table missing from DB"
    for col in ["ticker", "fetched_date", "trailing_pe", "forward_pe", "pb",
                "ps_ttm", "ev_ebitda", "short_pct_float", "analyst_target"]:
        assert col in cols, f"valuation_snapshots.{col} missing"


def test_company_profiles_table_exists_in_db(db_conn):
    cols = _get_columns(db_conn, "company_profiles")
    assert cols, "company_profiles table missing from DB"
    for col in ["ticker", "sector", "industry", "country", "employees", "updated_at"]:
        assert col in cols, f"company_profiles.{col} missing"
