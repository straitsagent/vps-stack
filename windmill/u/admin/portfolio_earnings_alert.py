# Requirements:
# psycopg2-binary>=2.9
# requests>=2.31

from datetime import date, timedelta
from typing import TypedDict

import psycopg2
import requests


class postgresql(TypedDict):
    host: str
    port: int
    user: str
    password: str
    dbname: str


import os
import logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
log = logging.getLogger(__name__)

WM_BASE_URL = os.environ.get("WM_BASE_URL", "http://windmill_server:8000")
WM_WORKSPACE = "admins"


def _get_tickers(portfolio_db: dict) -> list[str]:
    conn = psycopg2.connect(
        host=portfolio_db["host"],
        port=portfolio_db.get("port", 5432),
        user=portfolio_db["user"],
        password=portfolio_db["password"],
        dbname=portfolio_db["dbname"],
    )
    with conn:
        with conn.cursor() as cur:
            cur.execute("SELECT ticker FROM portfolio_positions ORDER BY ticker")
            rows = cur.fetchall()
    conn.close()
    return [r[0] for r in rows]


def _dispatch_pre_analysis(ticker: str, earnings_date: str, portfolio_db: dict, wm_token: str):
    """Dispatch portfolio_earnings_analysis (pre mode) as async Windmill job."""
    url = f"{WM_BASE_URL}/api/w/{WM_WORKSPACE}/jobs/run/p/u/admin/portfolio_earnings_analysis"
    payload = {
        "ticker": ticker,
        "analysis_type": "pre",
        "portfolio_db": "$res:u/admin/portfolio_db",
        "gmail_smtp": "$res:u/admin/gmail_smtp",
        "xai_key": "$var:u/admin/xai_key",
        "exa_key": "$var:u/admin/exa_key",
        "finnhub_key": "$var:u/admin/finnhub_key",
        "telegram_bot_token": "$var:u/admin/telegram_bot_token",
    }
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {wm_token}", "Content-Type": "application/json"},
        json=payload,
        timeout=15,
    )
    resp.raise_for_status()
    return resp.text.strip().strip('"')


def _send_telegram(bot_token: str, chat_id: str, text: str):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}, timeout=10)


def main(
    portfolio_db: postgresql = {},
    finnhub_key: str = "$var:u/admin/finnhub_key",
    telegram_bot_token: str = "$var:u/admin/telegram_bot_token",
    telegram_owner_id: str = "",
    wm_token: str = "$var:u/admin/wm_token",
):
    tickers = _get_tickers(portfolio_db)
    today = date.today()
    from_date = today.strftime("%Y-%m-%d")
    to_date = (today + timedelta(days=7)).strftime("%Y-%m-%d")

    alerts = []
    upcoming_events = []  # upcoming earnings with no actual results yet
    tickers_checked = 0
    for ticker in tickers:
        tickers_checked += 1
        try:
            url = f"https://finnhub.io/api/v1/calendar/earnings?from={from_date}&to={to_date}&symbol={ticker}&token={finnhub_key}"
            resp = requests.get(url, timeout=10)
            events = resp.json().get("earningsCalendar", [])
            for ev in events:
                d = ev.get("date", "?")
                eps_est = ev.get("epsEstimate")
                eps_actual = ev.get("epsActual")
                eps_str = ""
                if eps_actual is not None and eps_est is not None:
                    surprise_pct = ((eps_actual - eps_est) / abs(eps_est)) * 100 if eps_est != 0 else 0
                    if abs(surprise_pct) > 5:
                        eps_str = f" — EPS surprise: {surprise_pct:+.1f}% ({eps_actual:.2f} vs {eps_est:.2f} est)"
                    else:
                        continue
                else:
                    # Upcoming — no actual results yet
                    upcoming_events.append({"ticker": ticker, "date": d})
                alerts.append(f"• {ticker} earnings: {d}{eps_str}")
        except Exception as e:
            log.info(f"[EarningsAlert] {ticker}: {e}")

    alerts_sent = 0
    if alerts:
        msg = "*Earnings Alert*\n\n" + "\n".join(alerts)
        _send_telegram(telegram_bot_token, telegram_owner_id, msg)
        alerts_sent = len(alerts)
        log.info(f"[EarningsAlert] Sent {alerts_sent} alerts")
    else:
        log.info(f"[EarningsAlert] No upcoming earnings alerts for {tickers_checked} tickers")

    # Dispatch pre-earnings analysis for upcoming (no epsActual yet) events
    pre_dispatched = 0
    for ticker_event in upcoming_events:
        ticker = ticker_event["ticker"]
        earnings_date = ticker_event["date"]
        try:
            _dispatch_pre_analysis(ticker, earnings_date, portfolio_db, wm_token)
            pre_dispatched += 1
            log.info(f"[EarningsAlert] Dispatched pre-analysis for {ticker} ({earnings_date})")
        except Exception as e:
            log.info(f"[EarningsAlert] Pre-analysis dispatch failed for {ticker}: {e}")

    return {"alerts_sent": alerts_sent, "tickers_checked": tickers_checked,
            "pre_analysis_dispatched": pre_dispatched}
