import asyncio
import json
from datetime import datetime, timezone
from typing import Optional

import psycopg2
import psycopg2.extras
from config import AGENT_DB_URL


def _get_conn():
    return psycopg2.connect(AGENT_DB_URL)


async def db_exec(fn, *args):
    return await asyncio.to_thread(fn, *args)


# ── Conversation history ──────────────────────────────────────────────────────

def _load_history(phone: str, n: int = 10) -> list[dict]:
    with _get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT role, content, tool_called, tool_args
                   FROM agent_conversation_history
                   WHERE wa_phone = %s
                   ORDER BY created_at DESC LIMIT %s""",
                (phone, n),
            )
            rows = list(reversed(cur.fetchall()))
    return [dict(r) for r in rows]


async def load_history(phone: str, n: int = 10) -> list[dict]:
    return await db_exec(_load_history, phone, n)


def _append_history(phone: str, role: str, content: str,
                    tool_called: Optional[str] = None, tool_args: Optional[dict] = None):
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO agent_conversation_history
                   (wa_phone, role, content, tool_called, tool_args)
                   VALUES (%s, %s, %s, %s, %s)""",
                (phone, role, content, tool_called,
                 json.dumps(tool_args) if tool_args else None),
            )
        conn.commit()


async def append_history(phone: str, role: str, content: str,
                          tool_called: Optional[str] = None, tool_args: Optional[dict] = None):
    await db_exec(_append_history, phone, role, content, tool_called, tool_args)


# ── Pending jobs ──────────────────────────────────────────────────────────────

def _create_pending_job(job_id: str, phone: str, tool_name: str, tool_args: dict):
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO agent_pending_jobs (job_id, wa_phone, tool_name, tool_args)
                   VALUES (%s, %s, %s, %s)""",
                (job_id, phone, tool_name, json.dumps(tool_args)),
            )
        conn.commit()


async def create_pending_job(job_id: str, phone: str, tool_name: str, tool_args: dict):
    await db_exec(_create_pending_job, job_id, phone, tool_name, tool_args)


def _get_running_jobs() -> list[dict]:
    with _get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM agent_pending_jobs WHERE status = 'running'"
            )
            return [dict(r) for r in cur.fetchall()]


async def get_running_jobs() -> list[dict]:
    return await db_exec(_get_running_jobs)


def _update_job_status(job_id: str, status: str,
                        result_preview: Optional[str] = None,
                        error_message: Optional[str] = None):
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE agent_pending_jobs
                   SET status = %s, completed_at = NOW(),
                       result_preview = %s, error_message = %s
                   WHERE job_id = %s""",
                (status, result_preview, error_message, job_id),
            )
        conn.commit()


async def update_job_status(job_id: str, status: str,
                             result_preview: Optional[str] = None,
                             error_message: Optional[str] = None):
    await db_exec(_update_job_status, job_id, status, result_preview, error_message)


# ── Pending confirmations ─────────────────────────────────────────────────────

def _create_confirmation(phone: str, tool_name: str, tool_args: dict) -> int:
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO agent_pending_confirmations (wa_phone, tool_name, tool_args)
                   VALUES (%s, %s, %s) RETURNING id""",
                (phone, tool_name, json.dumps(tool_args)),
            )
            row_id = cur.fetchone()[0]
        conn.commit()
    return row_id


async def create_confirmation(phone: str, tool_name: str, tool_args: dict) -> int:
    return await db_exec(_create_confirmation, phone, tool_name, tool_args)


def _get_pending_confirmation(phone: str) -> Optional[dict]:
    with _get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT * FROM agent_pending_confirmations
                   WHERE wa_phone = %s AND status = 'pending' AND expires_at > NOW()
                   ORDER BY created_at DESC LIMIT 1""",
                (phone,),
            )
            row = cur.fetchone()
    return dict(row) if row else None


async def get_pending_confirmation(phone: str) -> Optional[dict]:
    return await db_exec(_get_pending_confirmation, phone)


def _resolve_confirmation(conf_id: int, status: str):
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE agent_pending_confirmations SET status = %s WHERE id = %s",
                (status, conf_id),
            )
        conn.commit()


async def resolve_confirmation(conf_id: int, status: str):
    await db_exec(_resolve_confirmation, conf_id, status)


def _expire_stale_confirmations(phone: str):
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE agent_pending_confirmations
                   SET status = 'expired'
                   WHERE wa_phone = %s AND status = 'pending' AND expires_at <= NOW()""",
                (phone,),
            )
        conn.commit()


async def expire_stale_confirmations(phone: str):
    await db_exec(_expire_stale_confirmations, phone)


# ── Draft queue ───────────────────────────────────────────────────────────────

def _create_draft(phone: str, inbound_text: str, draft_reply: str) -> int:
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO agent_draft_queue (wa_phone, inbound_text, draft_reply, notified_at)
                   VALUES (%s, %s, %s, NOW()) RETURNING id""",
                (phone, inbound_text, draft_reply),
            )
            row_id = cur.fetchone()[0]
        conn.commit()
    return row_id


async def create_draft(phone: str, inbound_text: str, draft_reply: str) -> int:
    return await db_exec(_create_draft, phone, inbound_text, draft_reply)


def _get_pending_draft(draft_id: int) -> Optional[dict]:
    with _get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM agent_draft_queue WHERE id = %s AND status = 'pending'",
                (draft_id,),
            )
            row = cur.fetchone()
    return dict(row) if row else None


async def get_pending_draft(draft_id: int) -> Optional[dict]:
    return await db_exec(_get_pending_draft, draft_id)


def _resolve_draft(draft_id: int, status: str):
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE agent_draft_queue SET status = %s, resolved_at = NOW() WHERE id = %s",
                (status, draft_id),
            )
        conn.commit()


async def resolve_draft(draft_id: int, status: str):
    await db_exec(_resolve_draft, draft_id, status)


# ── Contact rules ─────────────────────────────────────────────────────────────

def _get_contact(phone: str) -> Optional[dict]:
    with _get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM agent_contact_rules WHERE wa_phone = %s",
                (phone,),
            )
            row = cur.fetchone()
    return dict(row) if row else None


async def get_contact(phone: str) -> Optional[dict]:
    return await db_exec(_get_contact, phone)


def _upsert_contact(phone: str, display_name: str, relationship: Optional[str],
                     auto_reply: bool, rule_prompt: Optional[str], notes: Optional[str]):
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO agent_contact_rules
                   (wa_phone, display_name, relationship, auto_reply, rule_prompt, notes)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   ON CONFLICT (wa_phone) DO UPDATE SET
                       display_name = EXCLUDED.display_name,
                       relationship = EXCLUDED.relationship,
                       auto_reply   = EXCLUDED.auto_reply,
                       rule_prompt  = EXCLUDED.rule_prompt,
                       notes        = EXCLUDED.notes""",
                (phone, display_name, relationship, auto_reply, rule_prompt, notes),
            )
        conn.commit()


async def upsert_contact(phone: str, display_name: str, relationship: Optional[str],
                          auto_reply: bool, rule_prompt: Optional[str], notes: Optional[str]):
    await db_exec(_upsert_contact, phone, display_name, relationship,
                  auto_reply, rule_prompt, notes)


def _search_contacts_by_name(name_fragment: str) -> list[dict]:
    with _get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM agent_contact_rules WHERE lower(display_name) LIKE lower(%s) LIMIT 1",
                (f"%{name_fragment}%",),
            )
            return [dict(r) for r in cur.fetchall()]


async def search_contacts_by_name(name_fragment: str) -> list[dict]:
    return await db_exec(_search_contacts_by_name, name_fragment)


# ── Audit log ─────────────────────────────────────────────────────────────────

def _write_audit(
    phone: str, inbound_text: str, intent: Optional[str], tool: Optional[str],
    tool_args: Optional[dict], latency_ms: Optional[int], router_tokens: Optional[int],
    synth_tokens: Optional[int], cost_usd: Optional[float], wm_job_id: Optional[str],
    response_text: Optional[str], status: str, error: Optional[str],
):
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO agent_audit_log (
                       wa_phone, inbound_text, intent_detected, tool_called, tool_args,
                       tool_latency_ms, router_tokens, synth_tokens, estimated_cost_usd,
                       windmill_job_id, response_text, status, error_detail
                   ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    phone, inbound_text, intent, tool,
                    json.dumps(tool_args) if tool_args else None,
                    latency_ms, router_tokens, synth_tokens, cost_usd,
                    wm_job_id, response_text, status, error,
                ),
            )
        conn.commit()


async def write_audit(**kwargs):
    await asyncio.to_thread(_write_audit, **kwargs)
