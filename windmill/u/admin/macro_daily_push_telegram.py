# Requirements:
# requests>=2.31
# psycopg2-binary>=2.9
# pytz>=2024.1

"""
Macro Daily Push — Telegram Formatter
Reads the canonical markdown written by macro_research, synthesises a 500-600 word
Telegram summary via Deepseek, then sends it. Never tells user to refer to email.
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


# ── Deepseek synthesis ──────────────────────────────────────────────────────

def _synthesise_telegram(narrative: str, deepseek_key: str) -> str:
    """Return a 500-600 word synthesis via Deepseek, or truncated narrative as fallback."""
    import requests as _req
    if not deepseek_key:
        return " ".join(narrative.split()[:600])
    prompt = (
        "You are a macro research analyst. The text below is a detailed daily macro research "
        "report covering global equities, interest rates, Fed policy, FX/credit, commodities, "
        "and HK/China markets. Write a coherent 500-600 word executive synthesis that captures "
        "the key themes and what they mean together for markets. Write in flowing analytical "
        "prose — no bullet points, no section headers, no preamble. Be direct and specific.\n\n"
        f"{narrative}"
    )
    try:
        r = _req.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {deepseek_key}",
                     "Content-Type": "application/json"},
            json={"model": "deepseek-chat",
                  "messages": [{"role": "user", "content": prompt}],
                  "temperature": 0.3,
                  "max_tokens": 1000},
            timeout=60,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        log.warning(f"[MacroTelegram] Synthesis failed ({e}) — using narrative truncation")
        return " ".join(narrative.split()[:600])


# ── Yahoo indicator formatting ──────────────────────────────────────────────

_YAHOO_ORDER = [
    "SP500", "NDX", "HSI",
    "CSI300", "VIX", "UST10Y",
    "DXY", "EURUSD", "USDJPY",
    "USDSGD", "USDHKD", "Gold",
    "Brent",
]

_YAHOO_DISPLAY = {
    "SP500": "S&P", "NDX": "NDX", "HSI": "HSI", "CSI300": "CSI300",
    "RUT": "RUT", "Nikkei": "Nikkei", "DAX": "DAX", "FTSE": "FTSE",
    "VIX": "VIX",
    "UST5Y": "5Y", "UST10Y": "10Y", "UST30Y": "30Y",
    "HYG": "HYG", "LQD": "LQD",
    "DXY": "DXY", "EURUSD": "EUR/USD", "GBPUSD": "GBP/USD",
    "USDJPY": "USD/JPY", "USDCNY": "USD/CNY",
    "USDSGD": "USD/SGD", "USDHKD": "USD/HKD",
    "Gold": "Gold", "Brent": "Brent", "Copper": "Copper",
    "NatGas": "Nat Gas", "BTC-USD": "BTC",
}


def _fmt_indicator(name: str, ind: dict) -> str:
    v = ind.get("value")
    c = ind.get("change_pct")
    display = _YAHOO_DISPLAY.get(name, name)
    if v is None:
        return f"{display}: N/A"
    arrow = " ↑" if (c or 0) > 0.1 else (" ↓" if (c or 0) < -0.1 else "")
    chg_str = f" ({c:+.1f}%)" if c is not None else ""
    if name in ("SP500", "NDX", "HSI", "CSI300", "RUT", "Nikkei", "DAX", "FTSE"):
        return f"{display}: {v:,.0f}{chg_str}{arrow}"
    elif name in ("UST5Y", "UST10Y", "UST30Y"):
        return f"{display}: {v:.2f}%{chg_str}{arrow}"
    elif name == "Gold":
        return f"{display}: ${v:,.0f}{chg_str}{arrow}"
    elif name in ("Brent", "NatGas"):
        return f"{display}: ${v:.1f}{chg_str}{arrow}"
    elif name == "Copper":
        return f"{display}: ${v:.2f}{chg_str}{arrow}"
    elif name == "BTC-USD":
        return f"{display}: ${v:,.0f}{chg_str}{arrow}"
    elif name in ("EURUSD", "GBPUSD"):
        return f"{display}: {v:.4f}{chg_str}{arrow}"
    elif name in ("USDJPY", "USDCNY"):
        return f"{display}: {v:.2f}{chg_str}{arrow}"
    elif name in ("USDSGD", "USDHKD"):
        return f"{display}: {v:.4f}{chg_str}{arrow}"
    elif name == "DXY":
        return f"{display}: {v:.2f}{chg_str}{arrow}"
    elif name == "VIX":
        return f"{display}: {v:.1f}{chg_str}{arrow}"
    elif name in ("HYG", "LQD"):
        return f"{display}: {v:.2f}{chg_str}{arrow}"
    else:
        return f"{display}: {v:.4g}{chg_str}{arrow}"


# ── FRED block formatting ───────────────────────────────────────────────────

_FRED_GROUPS = [
    ("Rates",     ["DFF", "SOFR", "DGS2", "T10Y2Y", "T10Y3M"]),
    ("Inflation", ["CPIAUCSL", "PCEPI", "T5YIE", "T10YIE"]),
    ("Credit",    ["BAMLH0A0HYM2", "BAMLC0A0CM", "NFCI"]),
    ("Labour",    ["UNRATE"]),
]

_FRED_SHORT = {
    "DFF":          "Fed Funds",
    "SOFR":         "SOFR",
    "DGS2":         "2Y",
    "T10Y2Y":       "10Y-2Y",
    "T10Y3M":       "10Y-3M",
    "CPIAUCSL":     "CPI",
    "PCEPI":        "PCE",
    "T5YIE":        "5Y BE",
    "T10YIE":       "10Y BE",
    "BAMLH0A0HYM2": "HY OAS",
    "BAMLC0A0CM":   "IG OAS",
    "NFCI":         "FCI",
    "UNRATE":       "Unemp",
}

_FRED_SPREADS = {"T10Y2Y", "T10Y3M"}
_FRED_SIGNED  = {"NFCI"}


def _fmt_fred_val(sid: str, v: float) -> str:
    if sid in _FRED_SPREADS:
        return f"{v:+.2f}pp"
    elif sid in _FRED_SIGNED:
        return f"{v:+.3f}"
    elif v > 100:
        return f"{v:.1f}"
    else:
        return f"{v:.2f}%"


def _build_fred_block(fred_indicators: dict) -> str:
    lines = []
    for group_name, sids in _FRED_GROUPS:
        parts = []
        for sid in sids:
            d = fred_indicators.get(sid, {})
            v = d.get("value") if isinstance(d, dict) else None
            if v is not None:
                label = _FRED_SHORT.get(sid, sid)
                parts.append(f"{label} {_fmt_fred_val(sid, v)}")
        if parts:
            lines.append(f"{group_name}: " + "  ".join(parts))
    return "\n".join(lines)


# ── Message builder (pure function — unit-testable) ─────────────────────────

def _build_message(front_matter: dict, narrative: str) -> str:
    """
    Build the Telegram macro summary.
    `narrative` is expected to be a ~500-600 word Deepseek synthesis (or fallback text).
    Handles both schemas:
      - New (macro_research): indicators.yahoo + indicators.fred + fed_items + news_headlines
      - Old (macro_daily_push): flat indicators dict (backward compat)
    """
    # ── Timestamp ──────────────────────────────────────────────────────────────
    ts = front_matter.get("timestamp", "")
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

    # ── Schema detection: new nested vs. old flat ──────────────────────────────
    raw_indicators = front_matter.get("indicators", {})
    if "yahoo" in raw_indicators:
        yahoo_indicators = raw_indicators.get("yahoo", {})
        fred_indicators  = raw_indicators.get("fred", {})
    else:
        yahoo_indicators = raw_indicators
        fred_indicators  = {}

    # ── Weekend / holiday detection ────────────────────────────────────────────
    all_changes = [
        yahoo_indicators[n].get("change_pct") or 0
        for n in _YAHOO_ORDER if n in yahoo_indicators
    ]
    markets_closed = bool(all_changes) and all(abs(c) < 0.01 for c in all_changes)

    # ── Yahoo numbers block (3 per row) ────────────────────────────────────────
    items = [
        _fmt_indicator(name, yahoo_indicators[name])
        for name in _YAHOO_ORDER if name in yahoo_indicators
    ]
    yahoo_block = "\n".join(
        "  ".join(items[i:i+3]) for i in range(0, len(items), 3)
    )

    # ── FRED block ─────────────────────────────────────────────────────────────
    fred_block = _build_fred_block(fred_indicators) if fred_indicators else ""

    # ── Fed Watch line ─────────────────────────────────────────────────────────
    fed_watch = ""
    fed_items = front_matter.get("fed_items", [])
    if fed_items:
        latest  = fed_items[0]
        speaker = latest.get("speaker", "")
        title   = latest.get("title", "")[:80]
        date    = latest.get("date", "")
        by      = f"{speaker}: " if speaker else ""
        fed_watch = f"_Fed Watch: {by}{title}{(' — ' + date) if date else ''}_"

    # ── News headlines (top 4) ─────────────────────────────────────────────────
    headlines = front_matter.get("news_headlines", [])
    news_block = ""
    if headlines:
        hl_lines = []
        for h in headlines[:4]:
            title  = h.get("title", "").split(" - ")[0].strip()[:70]
            source = h.get("source", "").split(" - ")[0].strip()[:25]
            date   = h.get("date", "")
            suffix = f" ({date})" if date else ""
            hl_lines.append(f"• {title} — {source}{suffix}")
        news_block = "_In focus:_\n" + "\n".join(hl_lines)

    # ── Assemble ───────────────────────────────────────────────────────────────
    header = f"*Macro — {time_label}*"
    if markets_closed:
        header += "\n\n_Markets closed — values shown are as of the last trading session._"

    parts = [f"{header}\n\n{yahoo_block}"]

    fred_section = fred_block
    if fed_watch:
        fred_section = (fred_block + "\n" + fed_watch) if fred_block else fed_watch
    if fred_section:
        parts.append(fred_section)

    if narrative:
        parts.append(narrative)

    if news_block:
        parts.append(news_block)

    return "\n\n".join(parts)


# ── Entry point ─────────────────────────────────────────────────────────────

def main(
    md_path: str,
    telegram_bot_token: str,
    telegram_owner_id: str,
    portfolio_db: dict = {},
    deepseek_key: str = "",
):
    log.info(f"[MacroTelegram] Reading report: {md_path}")
    front_matter, narrative = _parse_md_report(md_path)

    log.info("[MacroTelegram] Synthesising narrative...")
    summary = _synthesise_telegram(narrative, deepseek_key)

    message = _build_message(front_matter, summary)
    word_count = len(message.split())
    log.info(f"[MacroTelegram] Message built: {word_count} words")
    if word_count < 400:
        log.warning(f"[MacroTelegram] Message under 400 words ({word_count}) — synthesis may have degraded")

    _send_telegram(
        telegram_bot_token, telegram_owner_id, message,
        db=portfolio_db, script_name="macro_daily_push",
    )
    return {"status": "sent", "word_count": word_count}
