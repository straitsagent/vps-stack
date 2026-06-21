# Requirements:
# requests>=2.31
# psycopg2-binary>=2.9

"""
Portfolio Weekly Review — Telegram Formatter
Reads the canonical markdown report written by portfolio_review and sends
a self-contained ≥500-word Telegram report. No external referrals.
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
    narrative = after_fm[:detail_idx].strip() if detail_idx != -1 else after_fm.strip()
    return front_matter, narrative


# ── Message builder (pure function — unit-testable) ─────────────────────────

def _fmt_pct(v):
    if v is None:
        return "—"
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.1f}%"


def _fmt_k(v):
    if v is None:
        return ""
    k = v / 1000
    sign = "+" if v >= 0 else "-"
    return f" ({sign}${abs(k):.1f}k)"


def _build_message(front_matter: dict, narrative: str) -> str:
    """
    Build the self-contained Telegram weekly review report.
    front_matter must contain: we_str, total_value, week_pnl, week_pct_total,
                                gainers (list of {label, week_pct, week_impact}),
                                losers (same)
    narrative: full Deepseek weekly commentary (≥500 words)
    """
    we_str      = front_matter.get("we_str", "")
    total_val   = front_matter.get("total_value", 0)
    week_pnl    = front_matter.get("week_pnl", 0)
    week_pct    = front_matter.get("week_pct_total", 0)
    gainers     = front_matter.get("gainers", [])
    losers      = front_matter.get("losers", [])

    val_str  = f"${total_val:,.0f}" if total_val else "N/A"
    week_k   = week_pnl / 1000 if week_pnl else 0
    # Dollar sign includes its own +/- so it's unambiguous for both positive and negative
    week_dollar_str = f"+${abs(week_k):.1f}k" if week_pnl >= 0 else f"-${abs(week_k):.1f}k"
    sign_pct = "+" if week_pct >= 0 else ""

    def _mover(p):
        ticker = p.get("label", p.get("ticker", "?"))
        pct = p.get("week_pct", 0)
        impact = p.get("week_impact", 0)
        return f"{ticker} {_fmt_pct(pct)}{_fmt_k(impact)}"

    g_str = "  ".join(_mover(p) for p in gainers[:2]) if gainers else "—"
    l_str = "  ".join(_mover(p) for p in losers[:2]) if losers else "—"

    header = (
        f"*Weekly Review — w/e {we_str}*\n"
        f"{val_str} | Week: {week_dollar_str} ({sign_pct}{week_pct:.2f}%)\n\n"
        f"📈 {g_str}\n"
        f"📉 {l_str}"
    )

    body = narrative.strip() if narrative.strip() else ""
    return f"{header}\n\n{body}"


# ── Entry point ─────────────────────────────────────────────────────────────

def main(
    md_path: str,
    telegram_bot_token: str,
    telegram_owner_id: str,
    portfolio_db: dict = {},
):
    log.info(f"[ReviewTelegram] Reading report: {md_path}")
    front_matter, narrative = _parse_md_report(md_path)
    message = _build_message(front_matter, narrative)
    word_count = len(message.split())
    log.info(f"[ReviewTelegram] Message built: {word_count} words")
    if word_count < 500:
        log.warning(f"[ReviewTelegram] Under 500 words ({word_count})")
    _send_telegram(
        telegram_bot_token, telegram_owner_id, message,
        db=portfolio_db, script_name="portfolio_review",
    )
    return {"status": "sent", "word_count": word_count}
