# Requirements:
# requests>=2.31
# yfinance>=0.2.40
# pytz>=2024.1

"""
Macro Daily Push — fetches 8 macro data points from Yahoo Finance,
synthesises 2-3 sentences via Deepseek, and sends a Telegram message.
No email, no DB write. Push is the only output.
"""

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
    "SGDUSD":   "SGD=X",
    "HKDUSD":   "HKD=X",
}

SYNTHESIS_PROMPT = (
    "You are a macro analyst. Given these 8 market data points, write exactly 2-3 concise sentences "
    "interpreting the current macro environment for a portfolio that is ~40% HK equities and ~60% US equities. "
    "Focus on what matters most right now. No preamble, no bullet points — plain prose only.\n\n"
    "Data:\n{data}"
)


def _send_telegram(bot_token: str, chat_id: str, text: str):
    try:
        requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception as e:
        log.warning(f"[Telegram] Failed to send: {e}")


def _fetch_macro() -> dict:
    tickers = list(SYMBOLS.values())
    data = yf.download(tickers, period="2d", progress=False, auto_adjust=True)
    close = data["Close"].iloc[-1]
    prev  = data["Close"].iloc[-2] if len(data) > 1 else data["Close"].iloc[-1]
    results = {}
    for name, sym in SYMBOLS.items():
        val  = float(close[sym]) if sym in close else None
        pval = float(prev[sym])  if sym in prev  else None
        chg  = ((val - pval) / pval * 100) if (val and pval and pval != 0) else None
        results[name] = {"value": val, "change_pct": chg}
    return results


def _fmt_arrow(chg):
    if chg is None: return ""
    return " ↑" if chg > 0.1 else (" ↓" if chg < -0.1 else "")


def _synthesise(macro: dict, deepseek_key: str) -> str:
    lines = []
    for name, d in macro.items():
        v = d["value"]
        c = d["change_pct"]
        if v is None:
            continue
        chg_str = f" ({c:+.1f}%)" if c is not None else ""
        lines.append(f"{name}: {v:.4g}{chg_str}")
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
                "max_tokens": 200,
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
):
    sgt = pytz.timezone("Asia/Singapore")
    now_sgt = datetime.now(sgt)
    time_label = now_sgt.strftime("%a %-d %b, %-I:%M %p SGT")

    log.info("[MacroPush] Fetching Yahoo Finance data...")
    macro = _fetch_macro()

    def fv(name, fmt=".4g"):
        v = macro.get(name, {}).get("value")
        return f"{v:{fmt}}" if v is not None else "N/A"

    def fa(name):
        return _fmt_arrow(macro.get(name, {}).get("change_pct"))

    vix_str      = f"VIX {fv('VIX', '.3g')}{fa('VIX')}"
    ust_str      = f"UST10Y {float(macro['UST10Y']['value']):.2f}%{fa('UST10Y')}" if macro.get("UST10Y", {}).get("value") else "UST10Y N/A"
    dxy_str      = f"DXY {fv('DXY', '.4g')}{fa('DXY')}"
    brent_str    = f"Brent ${fv('Brent', '.4g')}{fa('Brent')}"
    gold_str     = f"Gold ${fv('Gold', ',.0f')}{fa('Gold')}"
    sp500_val    = macro.get("SP500", {}).get("value")
    sp500_chg    = macro.get("SP500", {}).get("change_pct")
    sp500_str    = (f"S&P 500 {sp500_val:,.0f} {sp500_chg:+.1f}%" if sp500_val and sp500_chg is not None else "S&P 500 N/A")
    sgd_str      = f"SGD/USD {fv('SGDUSD', '.4f')}"
    hkd_str      = f"HKD/USD {fv('HKDUSD', '.4f')}"

    log.info("[MacroPush] Running Deepseek synthesis...")
    synthesis = _synthesise(macro, deepseek_key)

    tg_text = (
        f"*Macro — {time_label}*\n\n"
        f"{vix_str}  {ust_str}  {dxy_str}\n"
        f"{brent_str}  {gold_str}\n"
        f"{sgd_str}  {hkd_str}\n"
        f"{sp500_str}\n"
    )
    if synthesis:
        tg_text += f"\n_{synthesis}_"

    _send_telegram(telegram_bot_token, telegram_owner_id, tg_text)
    log.info("[MacroPush] Sent.")

    return {"status": "sent", "time": time_label}
