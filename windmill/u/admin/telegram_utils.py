# Requirements:
# requests>=2.31
# psycopg2-binary>=2.9

"""
Shared Telegram utilities — included verbatim in each formatter script.
NOT deployed as a standalone Windmill script; copy this block into each formatter.
"""

import logging
import math

log = logging.getLogger(__name__)

_MAX_PART = 4096


def _split_telegram_message(text: str, max_chars: int = _MAX_PART) -> list:
    """
    Split a long message into parts each <= max_chars, breaking on paragraph
    or line boundaries.  Appends " (n/N)" suffix when N > 1.
    """
    if len(text) <= max_chars:
        return [text]

    parts = []
    remaining = text
    while remaining:
        if len(remaining) <= max_chars:
            parts.append(remaining)
            break
        # Find a clean break point: paragraph first, then newline, then space
        chunk = remaining[:max_chars]
        cut = chunk.rfind("\n\n")
        if cut == -1 or cut < max_chars // 2:
            cut = chunk.rfind("\n")
        if cut == -1 or cut < max_chars // 2:
            cut = chunk.rfind(" ")
        if cut == -1:
            cut = max_chars
        parts.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()

    if len(parts) == 1:
        return parts

    n = len(parts)
    return [f"{p}\n\n({i}/{n})" for i, p in enumerate(parts, 1)]


def _send_telegram(bot_token: str, chat_id: str, text: str,
                   db=None, script_name: str = "") -> bool:
    """
    Send a (potentially long) Telegram message.
    - Logs the full text + word count to job logs (always).
    - Splits into parts <= 4096 chars.
    - Checks the API 'ok' field; retries as plain text on parse failure.
    - Best-effort inserts into telegram_outbox if db provided.
    Returns True if all parts delivered.
    """
    import requests

    words = len(text.split())
    chars = len(text)
    log.info(f"[Telegram] Sending ({chars} chars, {words} words):\n{text}")

    parts = _split_telegram_message(text)
    all_ok = True
    last_error = None

    for part in parts:
        delivered = False
        error = None
        for parse_mode in ("Markdown", None):  # retry as plain text if Markdown rejected
            try:
                payload = {"chat_id": chat_id, "text": part}
                if parse_mode:
                    payload["parse_mode"] = parse_mode
                r = requests.post(
                    f"https://api.telegram.org/bot{bot_token}/sendMessage",
                    json=payload,
                    timeout=15,
                )
                body = r.json()
                if body.get("ok"):
                    delivered = True
                    error = None
                    break
                else:
                    desc = body.get("description", "unknown error")
                    log.warning(f"[Telegram] API rejected (parse_mode={parse_mode}): {desc}")
                    error = desc
            except Exception as e:
                log.warning(f"[Telegram] Send failed: {e}")
                error = str(e)

        if not delivered:
            all_ok = False
            last_error = error

    if all_ok:
        log.info("[Telegram] Delivered OK")
    else:
        log.warning(f"[Telegram] Delivery failed: {last_error}")

    # Best-effort outbox write
    if db:
        try:
            import psycopg2
            conn = psycopg2.connect(**{k: v for k, v in db.items()
                                       if k in ("host", "port", "dbname", "user", "password")})
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO telegram_outbox
                   (script_name, message_text, char_count, word_count, delivered, error)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (script_name, text, chars, words, all_ok, last_error),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            log.warning(f"[Telegram] Outbox write failed (non-fatal): {e}")

    return all_ok
