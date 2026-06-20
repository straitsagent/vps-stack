# Requirements:
# requests>=2.31
# psycopg2-binary>=2.9

"""
Macro Daily Push — Telegram Formatter
Reads the canonical markdown report written by macro_daily_push and sends
a self-contained ≥500-word Telegram report. Never tells user to refer to email.
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
    """Return (front_matter: dict, narrative: str) from a canonical .md report."""
    with open(md_path) as f:
        content = f.read()
    # Extract json front-matter block
    fm_match = re.search(r"```json\s*\n([\s\S]*?)\n```", content)
    front_matter = {}
    if fm_match:
        try:
            front_matter = json.loads(fm_match.group(1))
        except json.JSONDecodeError as e:
            log.warning(f"[Parser] front-matter JSON parse failed: {e}")
    # Extract narrative: everything between the front-matter block and <!-- DETAIL -->
    after_fm = content[fm_match.end():] if fm_match else content
    detail_idx = after_fm.find("<!-- DETAIL -->")
    narrative = after_fm[:detail_idx].strip() if detail_idx != -1 else after_fm.strip()
    return front_matter, narrative


# ── Message builder (pure function — unit-testable) ─────────────────────────

def _fmt_indicator(name: str, ind: dict) -> str:
    v = ind.get("value")
    c = ind.get("change_pct")
    display = {"USDSGD": "USD/SGD", "USDHKD": "USD/HKD"}.get(name, name)
    if v is None:
        return f"{display}: N/A"
    arrow = " ↑" if (c or 0) > 0.1 else (" ↓" if (c or 0) < -0.1 else "")
    chg_str = f" ({c:+.1f}%)" if c is not None else ""
    # Format by type
    if name == "UST10Y":
        return f"{display}: {v:.2f}%{chg_str}{arrow}"
    elif name in ("Gold",):
        return f"{display}: ${v:,.0f}{chg_str}{arrow}"
    elif name in ("Brent",):
        return f"{display}: ${v:.1f}{chg_str}{arrow}"
    elif name == "SP500":
        return f"{display}: {v:,.0f}{chg_str}{arrow}"
    elif name in ("USDSGD", "USDHKD"):
        return f"{display}: {v:.4f}{chg_str}{arrow}"
    else:
        return f"{display}: {v:.4g}{chg_str}{arrow}"


def _build_message(front_matter: dict, narrative: str) -> str:
    """
    Build the self-contained Telegram macro report.
    front_matter: dict with 'indicators' mapping name→{value, change_pct}, 'timestamp'
    narrative: ≥500-word macro brief from Deepseek
    Returns a self-contained Telegram-ready Markdown string.
    """
    ts = front_matter.get("timestamp", "")
    # Time label from timestamp or fall back to raw
    time_label = ts
    if ts:
        try:
            from datetime import datetime
            import pytz
            dt = datetime.fromisoformat(ts)
            sgt = pytz.timezone("Asia/Singapore")
            dt_sgt = dt.astimezone(sgt)
            time_label = dt_sgt.strftime("%a %-d %b, %-I:%M %p SGT")
        except Exception:
            time_label = ts

    indicators = front_matter.get("indicators", {})
    _ORDER = ["VIX", "UST10Y", "DXY", "Brent", "Gold", "SP500", "USDSGD", "USDHKD"]

    lines = []
    row = []
    for name in _ORDER:
        if name in indicators:
            row.append(_fmt_indicator(name, indicators[name]))
            if len(row) == 3:
                lines.append("  ".join(row))
                row = []
    if row:
        lines.append("  ".join(row))

    header = f"*Macro — {time_label}*\n\n" + "\n".join(lines)
    body = narrative.strip() if narrative.strip() else ""

    return f"{header}\n\n{body}"


# ── Entry point ─────────────────────────────────────────────────────────────

def main(
    md_path: str,
    telegram_bot_token: str,
    telegram_owner_id: str,
    portfolio_db: dict = {},
):
    log.info(f"[MacroTelegram] Reading report: {md_path}")
    front_matter, narrative = _parse_md_report(md_path)
    message = _build_message(front_matter, narrative)
    word_count = len(message.split())
    log.info(f"[MacroTelegram] Message built: {word_count} words")
    if word_count < 500:
        log.warning(f"[MacroTelegram] Message under 500 words ({word_count}) — narrative may be too short")
    _send_telegram(
        telegram_bot_token, telegram_owner_id, message,
        db=portfolio_db, script_name="macro_daily_push",
    )
    return {"status": "sent", "word_count": word_count}
