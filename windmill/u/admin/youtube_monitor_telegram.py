# Requirements:
# requests>=2.31
# psycopg2-binary>=2.9

"""
YouTube Monitor — Telegram Formatter
Reads the canonical markdown report written by youtube_monitor and sends
a self-contained ≥500-word Telegram report including per-video AI summaries.
No external referrals.
"""

import json
import logging
import re

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

_MAX_PART = 4096


# ── Shared Telegram sender ──────────────────────────────────────────────────

def _split_telegram_message(text: str, max_chars: int = _MAX_PART) -> list:
    if len(text) <= max_chars:
        return [text]
    parts = []
    remaining = text
    while remaining:
        if len(remaining) <= max_chars:
            parts.append(remaining)
            break
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
                   db: dict = None, script_name: str = "") -> bool:
    import requests as _req
    words = len(text.split())
    chars = len(text)
    log.info(f"[Telegram] Sending ({chars} chars, {words} words):\n{text}")
    parts = _split_telegram_message(text)
    all_ok = True
    last_error = None
    for part in parts:
        delivered = False
        error = None
        for parse_mode in ("Markdown", None):
            try:
                payload = {"chat_id": chat_id, "text": part}
                if parse_mode:
                    payload["parse_mode"] = parse_mode
                r = _req.post(
                    f"https://api.telegram.org/bot{bot_token}/sendMessage",
                    json=payload, timeout=15,
                )
                body = r.json()
                if body.get("ok"):
                    delivered = True
                    error = None
                    break
                else:
                    desc = body.get("description", "unknown")
                    log.warning(f"[Telegram] API rejected (mode={parse_mode}): {desc}")
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
    if db:
        try:
            import psycopg2
            conn = psycopg2.connect(**{k: v for k, v in db.items()
                                       if k in ("host", "port", "dbname", "user", "password")})
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO telegram_outbox (script_name,message_text,char_count,word_count,delivered,error)"
                " VALUES (%s,%s,%s,%s,%s,%s)",
                (script_name, text, chars, words, all_ok, last_error),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            log.warning(f"[Telegram] Outbox write failed (non-fatal): {e}")
    return all_ok


# ── Markdown report parser ──────────────────────────────────────────────────

def _parse_md_report(md_path: str) -> tuple:
    with open(md_path) as f:
        content = f.read()
    fm_match = re.search(r"```json\s*\n([\s\S]*?)\n```", content)
    front_matter = {}
    if fm_match:
        try:
            front_matter = json.loads(fm_match.group(1))
        except json.JSONDecodeError as e:
            log.warning(f"[Parser] front-matter JSON parse failed: {e}")
    after_fm = content[fm_match.end():] if fm_match else content
    detail_idx = after_fm.find("<!-- DETAIL -->")
    # Per-video summaries live BELOW the <!-- DETAIL --> marker (24h synthesis removed 2026-06-30).
    if detail_idx != -1:
        body = after_fm[detail_idx + len("<!-- DETAIL -->"):].strip()
    else:
        body = after_fm.strip()
    return front_matter, body


# ── Message builder (pure function — unit-testable) ─────────────────────────

def _build_message(front_matter: dict, body: str) -> str:
    """
    Build the self-contained Telegram YouTube digest.
    front_matter must contain:
      date_str, n_summarised,
      videos: [{title, watch_url, channel_name}]
    body: the per-video summaries from the report's DETAIL section
    (the 24h synthesis was removed 2026-06-30).
    """
    date_str     = front_matter.get("date_str", "")
    n_summarised = front_matter.get("n_summarised", 0)
    videos       = front_matter.get("videos", [])

    header = f"*YouTube — {date_str} | {n_summarised} new*"

    link_lines = []
    for v in videos:
        title   = v.get("title", "Untitled")
        url     = v.get("watch_url", "")
        channel = v.get("channel_name", "")
        if url:
            link_lines.append(f"[{title}]({url}) — _{channel}_")
        else:
            link_lines.append(f"*{title}* — _{channel}_")

    links_block = "\n".join(link_lines) if link_lines else ""
    body = body.strip() if body.strip() else "(no summaries available)"
    parts = [header]
    if links_block:
        parts.append(links_block)
    parts.append(body)
    return "\n\n".join(parts)


# ── Entry point ─────────────────────────────────────────────────────────────

def main(
    md_path: str,
    telegram_bot_token: str,
    telegram_owner_id: str,
    portfolio_db: dict = {},
):
    log.info(f"[YouTubeTelegram] Reading report: {md_path}")
    front_matter, body = _parse_md_report(md_path)
    message = _build_message(front_matter, body)
    word_count = len(message.split())
    log.info(f"[YouTubeTelegram] Message built: {word_count} words")
    below_min = word_count < 500
    if below_min:
        log.warning(
            f"[YouTubeTelegram] Under 500 words ({word_count}) — short per-video summaries; "
            "sending anyway and flagging BELOW_MIN_WORDS in outbox"
        )

    # Send telegram. Skip auto-outbox write (db=None) so we can control the error field.
    delivered = _send_telegram(
        telegram_bot_token, telegram_owner_id, message,
        db=None,  # outbox handled manually below to allow BELOW_MIN_WORDS flag
        script_name="youtube_monitor",
    )

    # Write outbox row — include BELOW_MIN_WORDS flag when the summaries are short
    if portfolio_db:
        try:
            import psycopg2 as _pg
            conn = _pg.connect(**{k: v for k, v in portfolio_db.items()
                                   if k in ("host", "port", "dbname", "user", "password")})
            cur = conn.cursor()
            chars = len(message)
            outbox_error = f"BELOW_MIN_WORDS:{word_count}" if below_min else None
            cur.execute(
                "INSERT INTO telegram_outbox "
                "(script_name,message_text,char_count,word_count,delivered,error)"
                " VALUES (%s,%s,%s,%s,%s,%s)",
                ("youtube_monitor", message, chars, word_count, delivered, outbox_error),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            log.warning(f"[YouTubeTelegram] Outbox write failed (non-fatal): {e}")

    return {"status": "sent", "word_count": word_count}
