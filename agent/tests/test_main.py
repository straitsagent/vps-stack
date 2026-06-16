"""
Unit tests for handle_owner dispatch logic in agent/main.py.

Covers:
  B6 — FIRE branch silent-failure bugs: missing executor and executor exception
  B8 — Basic dispatch path coverage per tool class
"""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from unittest.mock import DEFAULT


OWNER_PHONE = "100000"
T0 = 0.0


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _db_patches():
    """Patch all async db functions used inside handle_owner.

    Uses DEFAULT so patch.multiple returns the auto-created AsyncMock objects
    in the context-manager dict.
    """
    return patch.multiple(
        "db",
        expire_stale_confirmations=DEFAULT,
        get_pending_confirmation=DEFAULT,
        load_history=DEFAULT,
        append_history=DEFAULT,
        write_audit=DEFAULT,
        create_confirmation=DEFAULT,
        create_pending_job=DEFAULT,
    )


def _configure_db_defaults(db_mocks):
    """Set sensible default return values on auto-created db mocks."""
    db_mocks["get_pending_confirmation"].return_value = None
    db_mocks["load_history"].return_value = []


# ── FIRE branch: missing executor (H7 bug #1) ────────────────────────────────

class TestFireMissingExecutor:
    def test_sends_error_message(self):
        """FIRE intent with no executor must send a reply — not silently return."""
        import main
        from config import FIRE

        with _db_patches() as db_mocks, \
             patch("telegram.send_message", new_callable=AsyncMock) as send_mock, \
             patch("classifier.classify", new_callable=AsyncMock) as clf_mock, \
             patch.dict("main.TOOL_CLASSES", {"_missing_fire": FIRE}):

            _configure_db_defaults(db_mocks)
            clf_mock.return_value = {
                "intent": "_missing_fire", "args": {}, "router_tokens": 0,
            }
            run(main.handle_owner(OWNER_PHONE, "test", T0))

        assert send_mock.called, (
            "send_message was never called — silent failure for unregistered FIRE intent"
        )

    def test_writes_unregistered_audit(self):
        """FIRE intent with no executor must write db.write_audit(status='unregistered')."""
        import main
        from config import FIRE

        with _db_patches() as db_mocks, \
             patch("telegram.send_message", new_callable=AsyncMock), \
             patch("classifier.classify", new_callable=AsyncMock) as clf_mock, \
             patch.dict("main.TOOL_CLASSES", {"_missing_fire": FIRE}):

            _configure_db_defaults(db_mocks)
            clf_mock.return_value = {
                "intent": "_missing_fire", "args": {}, "router_tokens": 0,
            }
            run(main.handle_owner(OWNER_PHONE, "test", T0))

        wa = db_mocks["write_audit"]
        assert wa.called, "db.write_audit was never called for unregistered FIRE intent"
        status = wa.call_args.kwargs.get("status")
        assert status == "unregistered", (
            f"Expected status='unregistered', got {status!r}"
        )


# ── FIRE branch: executor exception (H7 bug #2) ──────────────────────────────

class TestFireExecutorException:
    def test_writes_failed_audit(self):
        """FIRE executor that raises must write db.write_audit(status='failed')."""
        import main
        from config import FIRE

        async def exploding(args):
            raise RuntimeError("executor exploded")

        with _db_patches() as db_mocks, \
             patch("telegram.send_message", new_callable=AsyncMock), \
             patch("classifier.classify", new_callable=AsyncMock) as clf_mock, \
             patch.dict("main.TOOL_CLASSES", {"_boom_fire": FIRE}), \
             patch.dict("main.FIRE_EXECUTORS", {"_boom_fire": exploding}):

            _configure_db_defaults(db_mocks)
            clf_mock.return_value = {
                "intent": "_boom_fire", "args": {}, "router_tokens": 0,
            }
            run(main.handle_owner(OWNER_PHONE, "test", T0))

        wa = db_mocks["write_audit"]
        assert wa.called, "db.write_audit was never called after executor exception"
        status = wa.call_args.kwargs.get("status")
        assert status == "failed", f"Expected status='failed', got {status!r}"


# ── Basic dispatch coverage per tool class (B8) ──────────────────────────────

class TestFastDispatch:
    def test_executor_called_and_audits_success(self):
        """FAST intent: executor called, reply sent, audit written with status='success'."""
        import main
        from config import FAST

        async def fast_exec(args):
            return {"text": "here is your data"}

        with _db_patches() as db_mocks, \
             patch("telegram.send_message", new_callable=AsyncMock) as send_mock, \
             patch("classifier.classify", new_callable=AsyncMock) as clf_mock, \
             patch.dict("main.TOOL_CLASSES", {"_fast_test": FAST}), \
             patch.dict("main.FAST_EXECUTORS", {"_fast_test": fast_exec}):

            _configure_db_defaults(db_mocks)
            clf_mock.return_value = {
                "intent": "_fast_test", "args": {}, "router_tokens": 0,
            }
            run(main.handle_owner(OWNER_PHONE, "test", T0))

        assert send_mock.called
        status = db_mocks["write_audit"].call_args.kwargs.get("status")
        assert status == "success"


class TestGatedWriteDispatch:
    def test_creates_confirmation_and_audits_pending(self):
        """GATED_WRITE intent: creates confirmation, audits as 'pending_confirmation'."""
        import main
        from config import GATED_WRITE

        with _db_patches() as db_mocks, \
             patch("telegram.send_message", new_callable=AsyncMock), \
             patch("classifier.classify", new_callable=AsyncMock) as clf_mock, \
             patch.dict("main.TOOL_CLASSES", {"_gated_test": GATED_WRITE}):

            _configure_db_defaults(db_mocks)
            clf_mock.return_value = {
                "intent": "_gated_test", "args": {}, "router_tokens": 0,
            }
            run(main.handle_owner(OWNER_PHONE, "test", T0))

        assert db_mocks["create_confirmation"].called
        status = db_mocks["write_audit"].call_args.kwargs.get("status")
        assert status == "pending_confirmation"


class TestAsyncNotifyDispatch:
    def test_dispatches_and_audits(self):
        """ASYNC_NOTIFY intent: executor dispatched, ack sent, audit status 'dispatched'."""
        import main
        from config import ASYNC_NOTIFY

        async def notify_exec(args, phone):
            return {"text": "dispatched job abc123", "job_id": "abc123"}

        with _db_patches() as db_mocks, \
             patch("telegram.send_message", new_callable=AsyncMock) as send_mock, \
             patch("classifier.classify", new_callable=AsyncMock) as clf_mock, \
             patch.dict("main.TOOL_CLASSES", {"_notify_test": ASYNC_NOTIFY}), \
             patch.dict("main.ASYNC_NOTIFY_EXECUTORS", {"_notify_test": notify_exec}):

            _configure_db_defaults(db_mocks)
            clf_mock.return_value = {
                "intent": "_notify_test", "args": {}, "router_tokens": 0,
            }
            run(main.handle_owner(OWNER_PHONE, "test", T0))

        assert send_mock.called
        status = db_mocks["write_audit"].call_args.kwargs.get("status")
        assert status in ("dispatched", "cached")
