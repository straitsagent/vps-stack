# Requirements:
# requests>=2.31
# psycopg2-binary>=2.9

"""
Portfolio Rationalization — Telegram Formatter
Reads the canonical markdown report written by portfolio_rationalization and sends
a self-contained ≥500-word Telegram report with verdict tags + composite scores.
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
    narrative = after_fm[:detail_idx].strip() if detail_idx != -1 else after_fm.strip()
    return front_matter, narrative


# ── Message builder (pure function — unit-testable) ─────────────────────────

_VERDICT_LABELS = {"KEEP": "", "TRIM": " TRIM", "EXIT": " EXIT"}


def _ticker_line(item: dict) -> str:
    ticker  = item.get("ticker", "?")
    score   = item.get("score")        # composite balanced score (e.g. 55.5)
    verdict = item.get("verdict", "").upper()
    score_str   = f" {score:.1f}" if score is not None else ""
    verdict_str = _VERDICT_LABELS.get(verdict, f" {verdict}" if verdict else "")
    return f"{ticker}{score_str}{verdict_str}"


def _build_message(front_matter: dict, narrative: str) -> str:
    """
    Build the self-contained Telegram rationalization report.
    front_matter must contain:
      today_str, n_positions,
      top3: [{ticker, score, verdict}, ...],
      bot3: [{ticker, score, verdict}, ...]   ← score is composite (not rank), verdict is EXIT/TRIM
      monitored_candidates: [{ticker, verdict, eval_date, binding_constraint}, ...]   ← optional
    narrative: full Grok executive summary (≥500 words)
    """
    today_str   = front_matter.get("today_str", "")
    n_positions = front_matter.get("n_positions", 0)
    top3        = front_matter.get("top3", [])
    bot3        = front_matter.get("bot3", [])
    monitored   = front_matter.get("monitored_candidates", []) or []

    top_str = "  ".join(_ticker_line(t) for t in top3)
    bot_str = "  ".join(_ticker_line(t) for t in bot3)

    header = (
        f"*Portfolio Rationalization — {today_str}*  ·  _{n_positions} positions scored_\n\n"
        f"🏆 {top_str}\n"
        f"⚠️  {bot_str}"
    )

    monitored_block = ""
    if monitored:
        lines = [
            "",
            "*Watchlist (recently evaluated — Section D)*",
            "",
            "Ticker | Verdict | Evaluated | Note",
            "--- | --- | --- | ---",
        ]
        for m in monitored:
            ticker = m.get("ticker", "?")
            verdict = m.get("verdict", "")
            eval_date = m.get("eval_date", "")
            note = m.get("binding_constraint") or "—"
            lines.append(f"{ticker} | {verdict} | {eval_date} | {note}")
        monitored_block = "\n".join(lines)

    body = narrative.strip() if narrative.strip() else ""
    return f"{header}\n\n{body}{monitored_block}"


# ── Entry point ─────────────────────────────────────────────────────────────

def main(
    md_path: str,
    telegram_bot_token: str,
    telegram_owner_id: str,
    portfolio_db: dict = {},
):
    log.info(f"[RationalizationTelegram] Reading report: {md_path}")
    front_matter, narrative = _parse_md_report(md_path)
    message = _build_message(front_matter, narrative)
    word_count = len(message.split())
    log.info(f"[RationalizationTelegram] Message built: {word_count} words")
    if word_count < 500:
        log.warning(f"[RationalizationTelegram] Under 500 words ({word_count})")
    _send_telegram(
        telegram_bot_token, telegram_owner_id, message,
        db=portfolio_db, script_name="portfolio_rationalization",
    )
    return {"status": "sent", "word_count": word_count}
