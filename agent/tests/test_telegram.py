"""Tests for telegram.py adapter — pure parsing, no network calls."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Patch config imports before importing telegram
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123:test")
os.environ.setdefault("TELEGRAM_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("TELEGRAM_OWNER_ID", "999")
os.environ.setdefault("DRAFTS_GROUP_ID", "")
os.environ.setdefault("WM_TOKEN", "test")
os.environ.setdefault("AGENT_DB_URL", "postgresql://test")
os.environ.setdefault("DEEPSEEK_KEY", "test")
os.environ.setdefault("XAI_KEY", "test")

import telegram
from telegram import _split_text, _MAX_CHARS


def _make_update(chat_id, chat_type, text, msg_id=1, from_id=None):
    return {
        "update_id": 1,
        "message": {
            "message_id": msg_id,
            "from": {"id": from_id or chat_id, "first_name": "Owner"},
            "chat": {"id": chat_id, "type": chat_type},
            "text": text,
            "date": 1234567890,
        },
    }


def test_parse_private_message():
    msg = telegram.parse_inbound(_make_update(123456, "private", "hello"))
    assert msg is not None
    assert msg["phone"] == "123456"
    assert msg["text"] == "hello"
    assert msg["msg_id"] == "1"
    assert msg["is_group"] is False
    assert msg["display_name"] == "Owner"


def test_parse_group_message():
    msg = telegram.parse_inbound(_make_update(-1001234567890, "supergroup", "hi", from_id=999))
    assert msg is not None
    assert msg["phone"] == "-1001234567890"
    assert msg["is_group"] is True


def test_parse_missing_message_returns_none():
    assert telegram.parse_inbound({}) is None
    assert telegram.parse_inbound({"update_id": 1}) is None


def test_parse_missing_text_returns_empty():
    update = _make_update(123, "private", "hello")
    del update["message"]["text"]
    msg = telegram.parse_inbound(update)
    assert msg is not None
    assert msg["text"] == ""


def test_verify_signature_correct():
    from config import TELEGRAM_WEBHOOK_SECRET
    secret = TELEGRAM_WEBHOOK_SECRET or "test-secret"
    assert telegram.verify_signature(b"", secret) is True


def test_verify_signature_wrong():
    assert telegram.verify_signature(b"", "wrong-secret") is False


def test_verify_signature_empty():
    assert telegram.verify_signature(b"", "") is False


# ── _split_text tests ─────────────────────────────────────────────────────────

def test_split_short_text_is_single_chunk():
    assert _split_text("hello world") == ["hello world"]


def test_split_empty_string():
    assert _split_text("") == [""]


def test_split_exactly_at_limit_is_single_chunk():
    text = "x" * _MAX_CHARS
    assert _split_text(text) == [text]


def test_split_one_char_over_limit_gives_two_chunks():
    text = "x" * (_MAX_CHARS + 1)
    chunks = _split_text(text)
    assert len(chunks) == 2
    assert all(len(c) <= _MAX_CHARS for c in chunks)


def test_split_prefers_newline_boundary():
    line = "a" * 100
    text = "\n".join([line] * 60)  # 6059 chars, clean newlines throughout
    chunks = _split_text(text)
    assert all(len(c) <= _MAX_CHARS for c in chunks)
    for chunk in chunks[:-1]:
        assert chunk.endswith(line), "Chunk not cut at line boundary"


def test_split_no_newlines_hard_cuts():
    text = "x" * (_MAX_CHARS * 3)
    chunks = _split_text(text)
    assert len(chunks) == 3
    assert all(len(c) <= _MAX_CHARS for c in chunks)
