"""Integration tests for db.py — all 16 operations against the real portfolio DB."""
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
from conftest import TEST_PHONE
import db


# ── Conversation history ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_load_history_empty_returns_empty_list():
    result = await db.load_history("+0000000000", n=10)
    assert result == []


@pytest.mark.asyncio
async def test_append_and_load_history(db_conn, clean_test_phone):
    await db.append_history(TEST_PHONE, "user", "hello world")
    await db.append_history(TEST_PHONE, "assistant", "hi there")
    history = await db.load_history(TEST_PHONE, n=10)
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[0]["content"] == "hello world"
    assert history[1]["role"] == "assistant"
    assert history[1]["content"] == "hi there"


@pytest.mark.asyncio
async def test_append_history_with_tool_args(db_conn, clean_test_phone):
    await db.append_history(
        TEST_PHONE, "assistant", "fetching thesis",
        tool_called="thesis_read", tool_args={"ticker": "NVDA"}
    )
    history = await db.load_history(TEST_PHONE, n=5)
    assert len(history) == 1
    row = history[0]
    assert row["tool_called"] == "thesis_read"
    assert row["tool_args"] == {"ticker": "NVDA"}


# ── Pending jobs ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_and_get_running_jobs(db_conn, clean_test_phone):
    await db.create_pending_job("job-inttest-1", TEST_PHONE, "research", {"ticker": "NVDA"})
    running = await db.get_running_jobs()
    job_ids = [j["job_id"] for j in running]
    assert "job-inttest-1" in job_ids


@pytest.mark.asyncio
async def test_update_job_status_to_completed(db_conn, clean_test_phone):
    await db.create_pending_job("job-inttest-2", TEST_PHONE, "research", {})
    await db.update_job_status("job-inttest-2", "completed", result_preview="done")
    running = await db.get_running_jobs()
    job_ids = [j["job_id"] for j in running]
    assert "job-inttest-2" not in job_ids


@pytest.mark.asyncio
async def test_update_job_status_to_failed(db_conn, clean_test_phone):
    await db.create_pending_job("job-inttest-3", TEST_PHONE, "research", {})
    await db.update_job_status("job-inttest-3", "failed", error_message="timed out")
    with db_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT error_message, status FROM agent_pending_jobs WHERE job_id = %s",
                    ("job-inttest-3",))
        row = cur.fetchone()
    assert row["status"] == "failed"
    assert row["error_message"] == "timed out"


# ── Pending confirmations ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_and_get_pending_confirmation(db_conn, clean_test_phone):
    conf_id = await db.create_confirmation(TEST_PHONE, "thesis_write", {"ticker": "NVDA"})
    assert isinstance(conf_id, int) and conf_id > 0
    pending = await db.get_pending_confirmation(TEST_PHONE)
    assert pending is not None
    assert pending["tool_name"] == "thesis_write"


@pytest.mark.asyncio
async def test_resolve_confirmation(db_conn, clean_test_phone):
    conf_id = await db.create_confirmation(TEST_PHONE, "thesis_write", {"ticker": "NVDA"})
    await db.resolve_confirmation(conf_id, "confirmed")
    pending = await db.get_pending_confirmation(TEST_PHONE)
    assert pending is None


@pytest.mark.asyncio
async def test_expire_stale_confirmations_marks_expired(db_conn, clean_test_phone):
    # Insert a row with expires_at already in the past
    with db_conn.cursor() as cur:
        cur.execute(
            """INSERT INTO agent_pending_confirmations
               (wa_phone, tool_name, tool_args, expires_at)
               VALUES (%s, 'price_refresh', '{}', NOW() - INTERVAL '1 second')""",
            (TEST_PHONE,),
        )
    db_conn.commit()
    await db.expire_stale_confirmations(TEST_PHONE)
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT status FROM agent_pending_confirmations WHERE wa_phone = %s",
            (TEST_PHONE,),
        )
        row = cur.fetchone()
    assert row[0] == "expired"


# ── Draft queue ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_draft_id_returned_on_create(db_conn, clean_test_phone):
    draft_id = await db.create_draft(TEST_PHONE, "incoming msg", "draft reply")
    assert isinstance(draft_id, int) and draft_id > 0


@pytest.mark.asyncio
async def test_create_and_get_pending_draft(db_conn, clean_test_phone):
    draft_id = await db.create_draft(TEST_PHONE, "hello", "world")
    row = await db.get_pending_draft(draft_id)
    assert row is not None
    assert row["inbound_text"] == "hello"
    assert row["draft_reply"] == "world"
    assert row["status"] == "pending"


@pytest.mark.asyncio
async def test_resolve_draft(db_conn, clean_test_phone):
    draft_id = await db.create_draft(TEST_PHONE, "msg", "reply")
    await db.resolve_draft(draft_id, "sent")
    row = await db.get_pending_draft(draft_id)
    assert row is None  # status != 'pending' so not returned


# ── Contact rules ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_upsert_and_get_contact(db_conn):
    try:
        await db.upsert_contact(TEST_PHONE, "Test User", "colleague", False, None, None)
        contact = await db.get_contact(TEST_PHONE)
        assert contact is not None
        assert contact["display_name"] == "Test User"

        # Update via upsert
        await db.upsert_contact(TEST_PHONE, "Test User Updated", "friend", True, "be polite", "note")
        contact2 = await db.get_contact(TEST_PHONE)
        assert contact2["display_name"] == "Test User Updated"
        assert contact2["auto_reply"] is True
    finally:
        with db_conn.cursor() as cur:
            cur.execute("DELETE FROM agent_contact_rules WHERE wa_phone = %s", (TEST_PHONE,))
        db_conn.commit()


@pytest.mark.asyncio
async def test_search_contacts_by_name(db_conn):
    try:
        await db.upsert_contact(TEST_PHONE, "Testy McTestface", None, False, None, None)
        results = await db.search_contacts_by_name("Testy")
        assert len(results) > 0
        assert any("Testy" in r["display_name"] for r in results)
    finally:
        with db_conn.cursor() as cur:
            cur.execute("DELETE FROM agent_contact_rules WHERE wa_phone = %s", (TEST_PHONE,))
        db_conn.commit()


# ── Audit log ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_write_audit_does_not_raise(db_conn, clean_test_phone):
    await db.write_audit(
        phone=TEST_PHONE,
        inbound_text="test message",
        intent="portfolio_snapshot",
        tool="portfolio_snapshot",
        tool_args={"ticker": "NVDA"},
        latency_ms=42,
        router_tokens=100,
        synth_tokens=200,
        cost_usd=0.0012,
        wm_job_id="job-audit-test",
        response_text="Portfolio: $1M",
        status="success",
        error=None,
    )


@pytest.mark.asyncio
async def test_write_audit_minimal_fields(db_conn, clean_test_phone):
    await db.write_audit(
        phone=TEST_PHONE,
        inbound_text="minimal test",
        intent=None,
        tool=None,
        tool_args=None,
        latency_ms=None,
        router_tokens=None,
        synth_tokens=None,
        cost_usd=None,
        wm_job_id=None,
        response_text=None,
        status="error",
        error="unknown error",
    )
