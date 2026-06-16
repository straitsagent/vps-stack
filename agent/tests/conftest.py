"""Shared fixtures for integration tests — real DB connection using AGENT_DB_URL."""
import os
import pytest
import psycopg2
import psycopg2.extras

TEST_PHONE = "+9999000001"
TEST_TICKER_THESIS = "TESTONLY"
TEST_TICKER_RESEARCH = "RESEARCHTEST"


@pytest.fixture(scope="session")
def db_conn():
    """Session-scoped real DB connection — reused across all integration tests."""
    conn = psycopg2.connect(os.environ["AGENT_DB_URL"])
    conn.autocommit = False
    yield conn
    conn.close()


@pytest.fixture(autouse=False)
def clean_test_phone(db_conn):
    """Delete all test-phone rows after each test."""
    yield
    with db_conn.cursor() as cur:
        for table in [
            "agent_conversation_history",
            "agent_pending_jobs",
            "agent_pending_confirmations",
            "agent_draft_queue",
        ]:
            cur.execute(f"DELETE FROM {table} WHERE wa_phone = %s", (TEST_PHONE,))
    db_conn.commit()


@pytest.fixture(autouse=False)
def clean_test_ticker_thesis(db_conn):
    """Remove test thesis row after each test."""
    yield
    with db_conn.cursor() as cur:
        cur.execute(
            "DELETE FROM portfolio_thesis WHERE ticker = %s", (TEST_TICKER_THESIS,)
        )
    db_conn.commit()


@pytest.fixture(autouse=False)
def clean_research_reports(db_conn):
    """Remove test research_reports rows after each test."""
    yield
    with db_conn.cursor() as cur:
        cur.execute(
            "DELETE FROM research_reports WHERE ticker = %s", (TEST_TICKER_RESEARCH,)
        )
    db_conn.commit()
