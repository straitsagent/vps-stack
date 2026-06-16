# Requirements:
# psycopg2-binary>=2.9
# requests>=2.31

"""
Post-earnings detector — runs at 7 AM SGT daily.

Checks each portfolio ticker against Finnhub for earnings released in the last 3 days.
US after-hours earnings hit Finnhub by ~5–6 AM SGT; 7 AM provides a safe buffer.
If epsActual is populated AND no post-analysis exists in earnings_analyses for that
ticker+date, dispatches portfolio_earnings_analysis (analysis_type=post) as a new
Windmill job.
"""

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
        host=portfolio_db["host"], port=portfolio_db.get("port", 5432),
        user=portfolio_db["user"], password=portfolio_db["password"],
        dbname=portfolio_db["dbname"],
    )
    with conn:
        with conn.cursor() as cur:
            cur.execute("SELECT ticker FROM portfolio_positions ORDER BY ticker")
            rows = cur.fetchall()
    conn.close()
    return [r[0] for r in rows]


def _post_analysis_exists(portfolio_db: dict, ticker: str, earnings_date: str) -> bool:
    conn = psycopg2.connect(
        host=portfolio_db["host"], port=portfolio_db.get("port", 5432),
        user=portfolio_db["user"], password=portfolio_db["password"],
        dbname=portfolio_db["dbname"],
    )
    with conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM earnings_analyses WHERE ticker=%s AND analysis_type='post' AND earnings_date=%s",
                (ticker, earnings_date),
            )
            return cur.fetchone() is not None


def _dispatch_post_analysis(ticker: str, earnings_date: str, portfolio_db: dict, wm_token: str):
    url = f"{WM_BASE_URL}/api/w/{WM_WORKSPACE}/jobs/run/p/u/admin/portfolio_earnings_analysis"
    payload = {
        "ticker": ticker,
        "analysis_type": "post",
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


def main(
    portfolio_db: postgresql = {},
    finnhub_key: str = "$var:u/admin/finnhub_key",
    wm_token: str = "$var:u/admin/wm_token",
) -> dict:
    tickers = _get_tickers(portfolio_db)
    from_date = (date.today() - timedelta(days=3)).strftime("%Y-%m-%d")
    to_date = date.today().strftime("%Y-%m-%d")

    dispatched = []
    tickers_checked = 0
    for ticker in tickers:
        tickers_checked += 1
        try:
            url = (f"https://finnhub.io/api/v1/calendar/earnings"
                   f"?from={from_date}&to={to_date}&symbol={ticker}&token={finnhub_key}")
            resp = requests.get(url, timeout=10)
            events = resp.json().get("earningsCalendar", [])
            for ev in events:
                if ev.get("epsActual") is None:
                    continue
                earnings_date = ev.get("date", to_date)
                if _post_analysis_exists(portfolio_db, ticker, earnings_date):
                    log.warning(f"[PostCheck] {ticker} {earnings_date}: post-analysis already exists, skipping")
                    continue
                log.info(f"[PostCheck] Dispatching post-analysis for {ticker} ({earnings_date})")
                try:
                    _dispatch_post_analysis(ticker, earnings_date, portfolio_db, wm_token)
                    dispatched.append(f"{ticker}:{earnings_date}")
                except Exception as e:
                    log.info(f"[PostCheck] Dispatch failed for {ticker}: {e}")
        except Exception as e:
            log.info(f"[PostCheck] {ticker}: {e}")

    return {
        "tickers_checked": tickers_checked,
        "dispatched": len(dispatched),
        "dispatched_tickers": dispatched,
    }
