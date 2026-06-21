# Requirements:
# requests>=2.31
# psycopg2-binary>=2.9

"""
Health Check — Telegram Formatter
Reads the canonical markdown report written by health_check and sends
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

def _build_message(front_matter: dict, narrative: str) -> str:
    """
    Build the self-contained Telegram health check report.
    front_matter must contain:
      tg_date, ok_count, total,
      rows: [{label, status, age_str, error}],
      token_usage: [{job, model, tokens, cost_usd}]  (may be empty)
      outbox_rows: [{script_name, delivered, word_count, error, sent_at}]  (may be absent/empty)
    narrative: additional system notes or templated commentary (≥500 words when combined)
    """
    tg_date     = front_matter.get("tg_date", "")
    ok_count    = front_matter.get("ok_count", 0)
    total       = front_matter.get("total", 0)
    rows        = front_matter.get("rows", [])
    token_usage = front_matter.get("token_usage", [])
    outbox_rows = front_matter.get("outbox_rows", [])

    icon = "✅" if ok_count == total else "⚠️"
    header = f"*Health Check — {tg_date} | {ok_count}/{total} OK {icon}*"

    # Per-schedule status lines — detailed
    status_lines = []
    for row in rows:
        label     = row.get("label", "Unknown")
        status    = row.get("status", "?")
        age_str   = row.get("age_str", "")
        error     = row.get("error", "")
        st_icon   = "✅" if status == "OK" else "❌"
        detail    = f" — {error}" if error else (f" — {age_str}" if age_str else "")
        status_lines.append(f"{st_icon} *{label}*{detail}")

    # Token usage section
    token_lines = []
    if token_usage:
        token_lines.append("\n*24h Token Usage:*")
        total_cost = 0.0
        for entry in token_usage:
            job   = entry.get("job", "?")
            model = entry.get("model", "?")
            toks  = entry.get("tokens", 0)
            cost  = entry.get("cost_usd", 0.0)
            total_cost += cost
            token_lines.append(f"• {job} ({model}): {toks:,} tokens — ${cost:.4f}")
        token_lines.append(f"Total estimated cost: ${total_cost:.4f}")

    # Telegram formatter outbox audit — surfaces delivery failures and BELOW_MIN_WORDS violations
    outbox_lines = []
    if outbox_rows:
        outbox_lines.append("\n*Telegram Formatter Audit (24h):*")
        for row in outbox_rows:
            name      = row.get("script_name", "?")
            words     = row.get("word_count", 0)
            delivered = row.get("delivered", False)
            error     = row.get("error") or ""
            ot_icon   = "✅" if delivered and not error else "❌"
            detail    = f" — {error}" if error else f" — {words}w"
            outbox_lines.append(f"{ot_icon} {name}{detail}")
    else:
        outbox_lines.append("\n*Telegram Formatter Audit:* No sends recorded in last 24h")

    # System observations — explain what OK/FAIL means in context
    observations = []
    failed_schedules = [r for r in rows if r.get("status") != "OK"]
    if failed_schedules:
        observations.append(
            f"\n*Attention required:* {len(failed_schedules)} schedule(s) are in FAIL state. "
            "A FAIL typically means the last job ran more than the expected interval ago, "
            "the job returned an error result, or no completed job was found within the lookback window. "
            "Check the Windmill job logs for the affected schedules to diagnose root cause."
        )
        for row in failed_schedules:
            label = row.get("label", "?")
            error = row.get("error", "unknown")
            age   = row.get("age_str", "unknown age")
            observations.append(
                f"• *{label}*: {error} (last seen: {age}). "
                "Recommended action: open Windmill, navigate to this schedule, inspect the most "
                "recent completed and failed jobs for stack traces or dependency errors."
            )
    else:
        observations.append(
            "\n*All systems nominal.* All scheduled jobs completed within their expected intervals "
            "and returned successful results. No manual intervention required."
        )

    # Combine all sections into a single cohesive report
    all_sections = (
        [header, ""]
        + status_lines
        + token_lines
        + outbox_lines
        + observations
    )

    body = narrative.strip() if narrative.strip() else ""
    base = "\n".join(all_sections)
    return f"{base}\n\n{body}" if body else base


# ── Entry point ─────────────────────────────────────────────────────────────

def main(
    md_path: str,
    telegram_bot_token: str,
    telegram_owner_id: str,
    portfolio_db: dict = {},
):
    log.info(f"[HealthCheckTelegram] Reading report: {md_path}")
    front_matter, narrative = _parse_md_report(md_path)
    message = _build_message(front_matter, narrative)
    word_count = len(message.split())
    log.info(f"[HealthCheckTelegram] Message built: {word_count} words")
    if word_count < 500:
        log.warning(f"[HealthCheckTelegram] Under 500 words ({word_count})")
    _send_telegram(
        telegram_bot_token, telegram_owner_id, message,
        db=portfolio_db, script_name="health_check",
    )
    return {"status": "sent", "word_count": word_count}
