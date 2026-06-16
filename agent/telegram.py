"""
Telegram Bot API adapter.
Provides send_message, parse_inbound, verify_signature, mark_read.
"""
import httpx
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_WEBHOOK_SECRET

BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def verify_signature(raw_body: bytes, secret_header: str) -> bool:
    return secret_header == TELEGRAM_WEBHOOK_SECRET


def parse_inbound(payload: dict) -> dict | None:
    try:
        msg = payload.get("message") or payload.get("edited_message")
        if not msg:
            return None
        chat = msg["chat"]
        sender = msg.get("from", {})
        return {
            "phone": str(chat["id"]),
            "display_name": sender.get("first_name", ""),
            "msg_id": str(msg["message_id"]),
            "type": "text",
            "text": msg.get("text", ""),
            "timestamp": msg.get("date"),
            "is_group": chat["type"] in ("group", "supergroup", "channel"),
        }
    except (KeyError, TypeError):
        return None


_MAX_CHARS = 4000


def _split_text(text: str) -> list[str]:
    """Split text into chunks ≤ _MAX_CHARS, breaking at newlines where possible."""
    if len(text) <= _MAX_CHARS:
        return [text]
    chunks = []
    while text:
        if len(text) <= _MAX_CHARS:
            chunks.append(text)
            break
        # Find last newline within the limit
        cut = text.rfind("\n", 0, _MAX_CHARS)
        if cut <= 0:
            cut = _MAX_CHARS
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    return chunks


async def _send_single(client: httpx.AsyncClient, chat_id: int, text: str) -> bool:
    r = await client.post(
        f"{BASE_URL}/sendMessage",
        json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
    )
    if r.status_code == 200:
        return True
    if r.status_code == 400:
        r2 = await client.post(
            f"{BASE_URL}/sendMessage",
            json={"chat_id": chat_id, "text": text},
        )
        return r2.status_code == 200
    print(f"[telegram] send failed {r.status_code}: {r.text[:200]}")
    return False


async def send_message(to_chat_id: str, text: str) -> bool:
    chunks = _split_text(text)
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            ok = True
            for chunk in chunks:
                ok = await _send_single(client, int(to_chat_id), chunk) and ok
            return ok
    except Exception as e:
        print(f"[telegram] send error: {type(e).__name__}: {e!r}")
        return False


async def mark_read(msg_id: str, phone: str = "") -> None:
    pass  # Telegram has no read receipts


async def set_my_commands(commands: list[dict]) -> bool:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(f"{BASE_URL}/setMyCommands",
                                  json={"commands": commands})
            return r.status_code == 200
    except Exception as e:
        print(f"[telegram] setMyCommands failed: {e}")
        return False
