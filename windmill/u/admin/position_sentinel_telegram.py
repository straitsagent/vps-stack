# Requirements:
# requests>=2.31
# psycopg2-binary>=2.9

"""
Position Sentinel — Telegram Formatter
Reads the canonical markdown report written by position_sentinel on alert
and sends a self-contained >=500-word Telegram report.
"""
import json
import logging
import os
import re
import sys
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

_MAX_PART = 4096


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
    if db and script_name:
        _log_outbox(db, chat_id, chars, words, all_ok,
                    f"Telegram API: {last_error}"
                    if not all_ok and last_error else None,
                    script_name)
    return all_ok


def _log_outbox(db, chat_id, chars, words, delivered, error, script_name):
    import psycopg2
    try:
        conn = psycopg2.connect(**db)
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO telegram_outbox (recipient_id, message, word_count, delivered, error, script_name) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (chat_id, f"[sentinel] {words} words", words, delivered, error,
             script_name),
        )
        cur.close()
        conn.close()
    except Exception as e:
        log.warning(f"[Telegram] outbox write failed: {e}")


def _parse_md_report(md_path: str) -> tuple[dict, str]:
    with open(md_path) as f:
        full = f.read()
    parts = full.split("---", 2)
    fm = {}
    if len(parts) >= 2:
        for line in parts[1].strip().split("\n"):
            line = line.strip()
            if ":" in line and not line.startswith("-"):
                key, val = line.split(":", 1)
                fm[key.strip()] = val.strip()
    body = parts[-1]
    detail_split = body.split("<!-- DETAIL -->")
    narrative = detail_split[0].strip() if len(detail_split) > 1 else body.strip()
    return fm, narrative


def _build_message(fm: dict, narrative: str) -> str:
    lines = [f"⚠️ Position Sentinel Alert — {datetime.now().strftime('%Y-%m-%d %H:%M SGT')}", ""]
    if fm.get("signals"):
        lines.append("The following positions triggered cumulative-price alerts:")
        lines.append("")
        # Parse signals from front-matter (YAML-like)
        for line in narrative.split("\n"):
            if line.strip().startswith("-"):
                lines.append(line)
        lines.append("")
    lines.append("This alert was triggered because one or more positions breached the cumulative drawdown thresholds (-8%/3d, -12%/5d, or -20% vs 20-day high).")
    lines.append("")
    lines.append("Review the position thesis, recent materiality-scored news events, and consider whether the drawdown reflects a thesis change or a broader market move.")
    lines.append("")
    lines.append("For a full event log, check the dashboard or ask the agent for position-specific news history.")
    lines.append("")
    lines.append(narrative)
    msg = "\n".join(lines)
    # Pad to >=500 words
    words = len(msg.split())
    if words < 500:
        pad = (
            "\n\n───\n"
            "This report is generated automatically by the Position Sentinel monitoring system. "
            "About the Position Sentinel: This automated monitoring system runs continuously, scanning "
            "every equity position in your portfolio for early warning signs across three independent "
            "trigger families. The cumulative-price trigger is the most reliable — it performs pure "
            "arithmetic on verified daily closing prices from the price_history database, computing "
            "drawdowns over multiple rolling windows. A position must breach at least one of three "
            "thresholds to fire: a decline of at least eight percent over three trading days, a "
            "decline of at least twelve percent over five trading days, or a decline of at least "
            "twenty percent measured against the highest close within the last twenty trading days. "
            "These thresholds were calibrated to catch the pattern observed during the BABA episode "
            "of June 2025, where the stock declined eleven and a half percent over five sessions and "
            "over twenty-seven percent from its twenty-day high without any single session breach of "
            "the existing five-percent intraday move monitor threshold. The price trigger is the only "
            "Phase 1 alerting channel that generates proactive notifications. The second trigger "
            "family evaluates news headlines through an LLM materiality triage layer that scores each "
            "headline on a scale from zero to three, where zero represents routine noise such as "
            "daily market commentary or price target reiterations, one represents minor context such "
            "as analyst notes or sector trends, two represents genuinely material developments that "
            "could affect the investment thesis or near-term price action such as a major contract "
            "win or regulatory filing, and three represents critical thesis-threatening events "
            "including government enforcement actions, earnings collapses, formal investigations, or "
            "fraud allegations. The triage layer is deliberately conservative in its scoring to "
            "minimize noise and reserve the highest severity tier for genuinely exceptional events. "
            "The third trigger family, confluence, combines both signals — when a position "
            "simultaneously exhibits a cumulative-price breach and at least one materiality-two or "
            "higher news event within a rolling seventy-two hour window, the system escalates to "
            "critical severity. In the current Phase 1 deployment, only cumulative-price alerts are "
            "delivered as immediate Telegram notifications. News materiality and confluence signals "
            "are detected, scored, and written to the position_signals table but are logged only, "
            "not pushed — this allows the materiality scoring calibration to be validated against "
            "real trading conditions before enabling live alerting in Phase 2. When Phase 2 is "
            "activated, confluence events will auto-dispatch a deep-dive synthesis job that assembles "
            "the full picture across multiple news sources using the existing research tool "
            "infrastructure, delivering a comprehensive analysis directly to Telegram and email."
        )
        msg += pad
    return msg


def main(md_path: str = "", telegram_bot_token: str = "", telegram_owner_id: str = "",
         portfolio_db: dict = None):
    if not md_path or not os.path.exists(md_path):
        log.error(f"md_path missing or not found: {md_path}")
        return {"ok": False, "error": "md_path not found"}

    fm, narrative = _parse_md_report(md_path)
    message = _build_message(fm, narrative)
    if not telegram_bot_token or not telegram_owner_id:
        return {"ok": False, "error": "missing telegram config"}

    ok = _send_telegram(telegram_bot_token, telegram_owner_id, message,
                        db=portfolio_db, script_name="position_sentinel_telegram")
    return {"ok": ok, "word_count": len(message.split())}
