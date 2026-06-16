# Requirements:
# psycopg2-binary>=2.9
# requests>=2.31

import json
from datetime import date
from typing import TypedDict

import psycopg2
import requests
import logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
log = logging.getLogger(__name__)



class postgresql(TypedDict):
    host: str
    port: int
    user: str
    password: str
    dbname: str


RATING_ORDER = {
    "strongBuy": 5, "buy": 4, "hold": 3, "sell": 2, "strongSell": 1,
}


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


def _send_telegram(bot_token: str, chat_id: str, text: str):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}, timeout=10)


def _load_state(portfolio_db: dict) -> dict:
    try:
        conn = psycopg2.connect(
            host=portfolio_db["host"],
            port=portfolio_db.get("port", 5432),
            user=portfolio_db["user"],
            password=portfolio_db["password"],
            dbname=portfolio_db["dbname"],
        )
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT value FROM agent_kv WHERE key = 'analyst_alert_state' LIMIT 1")
                row = cur.fetchone()
                return json.loads(row[0]) if row else {}
        finally:
            conn.close()
    except Exception:
        return {}


def _save_state(portfolio_db: dict, state: dict):
    try:
        conn = psycopg2.connect(
            host=portfolio_db["host"],
            port=portfolio_db.get("port", 5432),
            user=portfolio_db["user"],
            password=portfolio_db["password"],
            dbname=portfolio_db["dbname"],
        )
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO agent_kv (key, value) VALUES ('analyst_alert_state', %s)
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                    """,
                    (json.dumps(state),),
                )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        log.error(f"[AnalystAlert] State save error: {e}")


def main(
    portfolio_db: postgresql = {},
    finnhub_key: str = "$var:u/admin/finnhub_key",
    telegram_bot_token: str = "$var:u/admin/telegram_bot_token",
    telegram_owner_id: str = "",
):
    tickers = _get_tickers(portfolio_db)
    prev_state = _load_state(portfolio_db)
    new_state = dict(prev_state)

    alerts = []
    tickers_checked = 0
    for ticker in tickers:
        tickers_checked += 1
        try:
            url = f"https://finnhub.io/api/v1/stock/recommendation?symbol={ticker}&token={finnhub_key}"
            resp = requests.get(url, timeout=10)
            recs = resp.json()
            if not recs:
                continue
            latest = recs[0]
            period = latest.get("period", "")
            rating = latest.get("strongBuy", 0) and "strongBuy" or latest.get("buy", 0) and "buy" or "hold"
            period_key = f"{ticker}_{period}"
            if period_key not in prev_state:
                new_state[period_key] = rating
            else:
                prev_rating = prev_state.get(period_key, "")
                if prev_rating != rating:
                    direction = "⬆️ Upgrade" if RATING_ORDER.get(rating, 3) > RATING_ORDER.get(prev_rating, 3) else "⬇️ Downgrade"
                    alerts.append(f"• {ticker}: {direction} ({prev_rating} → {rating}) for {period}")
                    new_state[period_key] = rating
        except Exception as e:
            log.info(f"[AnalystAlert] {ticker}: {e}")

    _save_state(portfolio_db, new_state)

    alerts_sent = 0
    if alerts:
        msg = "*Analyst Rating Changes*\n\n" + "\n".join(alerts)
        _send_telegram(telegram_bot_token, telegram_owner_id, msg)
        alerts_sent = len(alerts)
        log.info(f"[AnalystAlert] Sent {alerts_sent} alerts")
    else:
        log.info(f"[AnalystAlert] No rating changes for {tickers_checked} tickers")

    return {"alerts_sent": alerts_sent, "tickers_checked": tickers_checked}
