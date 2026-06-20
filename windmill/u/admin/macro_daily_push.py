# Requirements:
# requests>=2.31
# yfinance>=0.2.40
# pytz>=2024.1

"""
Macro Daily Push — fetches 8 macro data points from Yahoo Finance,
synthesises 2-3 sentences via Deepseek, and sends a Telegram message.
No email, no DB write. Push is the only output.
"""

import math
import requests
import yfinance as yf
import pytz
from datetime import datetime
import logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
log = logging.getLogger(__name__)


SYMBOLS = {
    "VIX":      "^VIX",
    "UST10Y":   "^TNX",
    "DXY":      "DX-Y.NYB",
    "Gold":     "GC=F",
    "Brent":    "BZ=F",
    "SP500":    "^GSPC",
    "USDSGD":   "SGD=X",   # Yahoo returns SGD-per-USD (USD/SGD conventional quote) — no inversion needed
    "USDHKD":   "HKD=X",   # Yahoo returns HKD-per-USD (USD/HKD conventional quote) — no inversion needed
}
# Yahoo FX tickers already return the conventional USD/FX rate — nothing to invert
_INVERT_SYMBOLS: set = set()

SYNTHESIS_PROMPT = (
    "You are a macro analyst. Given these 8 market data points, write a detailed macro brief of at least "
    "500 words interpreting the current macro environment for a portfolio that is ~40% HK equities and "
    "~60% US equities. Cover: (1) equity risk sentiment and what VIX signals, (2) interest rates and "
    "yield context, (3) dollar strength and FX implications for the portfolio, (4) energy and commodity "
    "context from Brent, (5) gold as a risk/hedge indicator, (6) implications for the specific HK and "
    "US equity mix. Be specific about what the data means for portfolio positioning — not generic. "
    "No preamble, no bullet points, no headers — continuous analytical prose only.\n\n"
    "Data:\n{data}"
)

WM_BASE      = "http://windmill_server:8000"
WM_WORKSPACE = "admins"


def _dispatch_formatter(formatter_name: str, md_path: str,
                        telegram_bot_token: str, telegram_owner_id: str,
                        portfolio_db: dict, wm_token: str = "") -> str:
    """Dispatch a Telegram formatter script fire-and-forget. Returns job_id or ''."""
    import os as _os
    token = wm_token or _os.environ.get("WM_TOKEN", "")
    if not token:
        log.warning(f"[Dispatch] No WM_TOKEN — cannot dispatch {formatter_name}")
        return ""
    url = f"{WM_BASE}/api/w/{WM_WORKSPACE}/jobs/run/p/u/admin/{formatter_name}"
    args = {
        "md_path": md_path,
        "telegram_bot_token": telegram_bot_token,
        "telegram_owner_id": telegram_owner_id,
        "portfolio_db": portfolio_db,
    }
    try:
        resp = requests.post(
            url, headers={"Authorization": f"Bearer {token}",
                          "Content-Type": "application/json"},
            json=args, timeout=10,
        )
        job_id = resp.text.strip().strip('"')
        log.info(f"[Dispatch] {formatter_name} dispatched job_id={job_id}")
        return job_id
    except Exception as e:
        log.warning(f"[Dispatch] Failed to dispatch {formatter_name}: {e}")
        return ""


def _fetch_macro() -> dict:
    tickers = list(SYMBOLS.values())
    data = yf.download(tickers, period="5d", progress=False, auto_adjust=True)
    filled = data["Close"].ffill()  # carry last valid price forward across weekend gaps
    close = filled.iloc[-1]
    prev  = filled.iloc[-2] if len(filled) > 1 else filled.iloc[-1]
    results = {}
    for name, sym in SYMBOLS.items():
        val  = float(close[sym]) if sym in close else None
        if val is not None and math.isnan(val):
            val = None
        pval = float(prev[sym]) if sym in prev else None
        if pval is not None and math.isnan(pval):
            pval = None
        chg  = ((val - pval) / pval * 100) if (val is not None and pval and pval != 0) else None
        if name in _INVERT_SYMBOLS and val is not None:
            val = 1.0 / val
            chg = -chg if chg is not None else None
        results[name] = {"value": val, "change_pct": chg}
    return results


def _fmt_arrow(chg):
    if chg is None: return ""
    return " ↑" if chg > 0.1 else (" ↓" if chg < -0.1 else "")


_DISPLAY_NAMES = {"USDSGD": "USD/SGD", "USDHKD": "USD/HKD"}


def _synthesise(macro: dict, deepseek_key: str) -> str:
    lines = []
    for name, d in macro.items():
        v = d["value"]
        c = d["change_pct"]
        if v is None:
            continue
        chg_str = f" ({c:+.1f}%)" if c is not None else ""
        display = _DISPLAY_NAMES.get(name, name)
        lines.append(f"{display}: {v:.4g}{chg_str}")
    data_str = "\n".join(lines)
    prompt = SYNTHESIS_PROMPT.format(data=data_str)
    try:
        r = requests.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {deepseek_key}"},
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens": 900,
            },
            timeout=20,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        log.warning(f"[Deepseek] Synthesis failed: {e}")
        return ""


def main(
    telegram_bot_token: str,
    telegram_owner_id: str,
    deepseek_key: str,
    portfolio_db: dict = {},
    wm_token: str = "",
):
    import json as _json, os as _os
    sgt = pytz.timezone("Asia/Singapore")
    now_sgt = datetime.now(sgt)
    time_label = now_sgt.strftime("%a %-d %b, %-I:%M %p SGT")

    log.info("[MacroPush] Fetching Yahoo Finance data...")
    macro = _fetch_macro()

    log.info("[MacroPush] Running Deepseek synthesis...")
    narrative = _synthesise(macro, deepseek_key)

    # ── Write canonical .md ──────────────────────────────────────────────────
    front_matter = {
        "timestamp": now_sgt.isoformat(),
        "indicators": macro,
    }
    _os.makedirs("/research/macro", exist_ok=True)
    md_path = f"/research/macro/{now_sgt.strftime('%Y-%m-%d_%H%M')}.md"
    md_content = (
        f"```json\n{_json.dumps(front_matter, indent=2)}\n```\n\n"
        f"{narrative}\n\n"
        "<!-- DETAIL -->\n"
    )
    with open(md_path, "w") as f:
        f.write(md_content)
    log.info(f"[md] Written {md_path}")

    # ── Dispatch Telegram formatter ──────────────────────────────────────────
    _dispatch_formatter(
        "macro_daily_push_telegram", md_path,
        telegram_bot_token, telegram_owner_id,
        portfolio_db, wm_token,
    )

    return {"status": "dispatched", "md_path": md_path, "time": time_label}
