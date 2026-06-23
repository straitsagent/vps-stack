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


WM_BASE      = "http://windmill_server:8000"
WM_WORKSPACE = "admins"


def _dispatch_formatter(formatter_name: str, md_path: str,
                        telegram_bot_token: str, telegram_owner_id: str,
                        portfolio_db: dict, wm_token: str = "") -> str:
    import os as _os
    token = wm_token or _os.environ.get("WM_TOKEN", "")
    if not token:
        log.warning(f"[Dispatch] No WM_TOKEN — cannot dispatch {formatter_name}")
        return ""
    url = f"{WM_BASE}/api/w/{WM_WORKSPACE}/jobs/run/p/u/admin/{formatter_name}"
    args = {"md_path": md_path, "telegram_bot_token": telegram_bot_token,
            "telegram_owner_id": telegram_owner_id, "portfolio_db": portfolio_db}
    try:
        resp = requests.post(url, headers={"Authorization": f"Bearer {token}",
                                           "Content-Type": "application/json"},
                             json=args, timeout=10)
        job_id = resp.text.strip().strip('"')
        log.info(f"[Dispatch] {formatter_name} dispatched job_id={job_id}")
        return job_id
    except Exception as e:
        log.warning(f"[Dispatch] Failed to dispatch {formatter_name}: {e}")
        return ""


def _write_canonical_md(content: str, path: str) -> None:
    with open(path, "w") as f:
        f.write(content)


def _build_analyst_narrative(alerts_structured: list, today_str: str,
                              deepseek_key: str = "") -> str:
    """Generate ≥500-word narrative for analyst rating changes."""
    if deepseek_key and alerts_structured:
        changes = "\n".join(
            f"  {a['ticker']}: {a['action']} from {a['old_rating']} to {a['new_rating']} ({a.get('period','')})"
            for a in alerts_structured
        )
        prompt = (
            f"You are an equity analyst. The following analyst rating changes were detected on {today_str}:\n"
            f"{changes}\n\n"
            f"Write a detailed ≥500-word analytical report covering: why each rating change matters, "
            f"the typical market reaction to such changes, what the new consensus implies for each position, "
            f"and what an investor should monitor in the coming days. "
            f"Continuous prose, no bullet points. Minimum 500 words."
        )
        try:
            r = requests.post(
                "https://api.deepseek.com/chat/completions",
                headers={"Authorization": f"Bearer {deepseek_key}"},
                json={"model": "deepseek-chat",
                      "messages": [{"role": "user", "content": prompt}],
                      "temperature": 0.4, "max_tokens": 900},
                timeout=30,
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            log.warning(f"[Deepseek] Analyst narrative failed: {e}")
    # Programmatic fallback
    if not alerts_structured:
        return ""
    paras = []
    paras.append(
        f"This analyst rating change alert was generated on {today_str}. "
        f"The portfolio monitoring system checks Finnhub analyst consensus data for all holdings "
        f"on a scheduled basis and issues an alert whenever a rating change is detected for any "
        f"position in the portfolio. Rating changes are tracked across multiple analyst periods and "
        f"compared against the previously recorded consensus to identify upgrades and downgrades. "
        f"An upgrade indicates that the analyst community has revised its collective view of the "
        f"stock upward, while a downgrade reflects deteriorating consensus sentiment."
    )
    for a in alerts_structured:
        ticker = a["ticker"]
        action = a["action"]
        old_r  = a["old_rating"]
        new_r  = a["new_rating"]
        period = a.get("period", "")
        direction_word = "positively" if "Upgrade" in action else "negatively"
        paras.append(
            f"{ticker} — {action}: The analyst consensus for {ticker} has moved from {old_r} "
            f"to {new_r}" + (f" for the {period} period" if period else "") + ". "
            f"This rating change is typically interpreted {direction_word} by the market. "
            f"A shift in analyst consensus often precedes institutional re-rating of the position "
            f"and may be accompanied by revised price targets. Investors holding this position "
            f"should monitor whether the change reflects a single-analyst revision or a broad "
            f"consensus shift, as the latter carries significantly higher signal value. "
            f"Review recent company announcements, earnings guidance, and sector-level trends "
            f"to assess whether the rating change is consistent with the fundamental outlook."
        )
    paras.append(
        f"Context and monitoring: analyst rating changes are one input into the portfolio "
        f"rationalization framework, which scores each position across five dimensions including "
        f"fundamentals, momentum, valuation, coverage quality, and portfolio fit. A rating "
        f"downgrade to sell or strong-sell typically increases a position's exit score in the "
        f"next rationalization cycle. An upgrade to buy or strong-buy may improve retention "
        f"probability if other factors are also supportive. Positions with persistent negative "
        f"rating trends across multiple periods warrant priority review regardless of current "
        f"price performance, as deteriorating analyst sentiment often leads price weakness "
        f"by several weeks in the HK-listed space."
    )
    paras.append(
        f"Recommended actions: review the affected tickers in the Windmill portfolio dashboard "
        f"and cross-reference the rating changes against recent price performance and news flow. "
        f"If the rating change is from a top-tier sell-side firm, apply additional weight to "
        f"the signal. Consider whether any pending earnings announcements or guidance updates "
        f"may have informed the change. Update position notes in the tracking system to record "
        f"the rating change date and new consensus level for future reference."
    )
    return "\n\n".join(paras)


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
    deepseek_key: str = "",
    wm_token: str = "",
):
    tickers = _get_tickers(portfolio_db)
    prev_state = _load_state(portfolio_db)
    new_state = dict(prev_state)

    alerts = []
    alerts_structured = []
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
                    action = "Upgrade" if RATING_ORDER.get(rating, 3) > RATING_ORDER.get(prev_rating, 3) else "Downgrade"
                    alerts.append(f"• {ticker}: {action} ({prev_rating} → {rating}) for {period}")
                    alerts_structured.append({
                        "ticker":      ticker,
                        "action":      action,
                        "old_rating":  prev_rating,
                        "new_rating":  rating,
                        "period":      period,
                    })
                    new_state[period_key] = rating
        except Exception as e:
            log.info(f"[AnalystAlert] {ticker}: {e}")

    _save_state(portfolio_db, new_state)

    alerts_sent = 0
    if alerts_structured:
        import os as _os, json as _json
        today_str = date.today().strftime("%-d %b")
        narrative = _build_analyst_narrative(alerts_structured, today_str, deepseek_key)
        front_matter = {
            "today_str": today_str,
            "alerts": alerts_structured,
        }
        _os.makedirs("/research/portfolio", exist_ok=True)
        md_path = f"/research/portfolio/analyst_{date.today().strftime('%Y-%m-%d')}.md"
        md_content = (
            f"```json\n{_json.dumps(front_matter, indent=2)}\n```\n\n"
            f"{narrative}\n\n"
            "<!-- DETAIL -->\n"
        )
        _write_canonical_md(md_content, md_path)
        log.info(f"[md] Written {md_path}")
        if telegram_bot_token and telegram_owner_id:
            _dispatch_formatter(
                "portfolio_analyst_alert_telegram", md_path,
                telegram_bot_token, telegram_owner_id,
                portfolio_db, wm_token,
            )
        alerts_sent = len(alerts_structured)
        log.info(f"[AnalystAlert] Sent {alerts_sent} alerts")
    else:
        log.info(f"[AnalystAlert] No rating changes for {tickers_checked} tickers")

    return {"alerts_sent": alerts_sent, "tickers_checked": tickers_checked}
