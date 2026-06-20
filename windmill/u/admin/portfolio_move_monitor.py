# Requirements:
# psycopg2-binary>=2.9
# pytz>=2024.1
# yfinance>=0.2.40

import smtplib
import time
import psycopg2
import pytz
import requests
import yfinance as yf
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional
import logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
log = logging.getLogger(__name__)


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


def _build_move_narrative(portfolio_move: float, total_impact: float,
                           pct_threshold: float, position_alerts: list,
                           pos_threshold: float, time_str: str,
                           deepseek_key: str = "") -> str:
    """Generate ≥500-word narrative for the move alert. LLM if key provided, else programmatic."""
    if deepseek_key:
        pos_desc = "\n".join(
            f"  {p['ticker']}: {p['intraday_pct']:+.2f}% (${abs(p.get('dollar_impact',0)):,.0f} impact)"
            for p in position_alerts[:5]
        )
        prompt = (
            f"You are a portfolio risk analyst. A portfolio move alert was triggered at {time_str}.\n"
            f"Portfolio move: {portfolio_move:+.2f}% (threshold ±{pct_threshold:.1f}%)\n"
            f"Dollar impact: ${abs(total_impact):,.0f}\n"
            f"Top position moves:\n{pos_desc}\n\n"
            f"Write a detailed ≥500-word analytical report explaining likely causes of this move, "
            f"the risk implications, what to watch next, and any recommended monitoring actions. "
            f"Continuous prose, no bullet points or headers. Minimum 500 words."
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
            log.warning(f"[Deepseek] Move narrative failed: {e}")
    # Programmatic fallback
    direction = "upward" if portfolio_move >= 0 else "downward"
    abs_pct = abs(portfolio_move)
    abs_impact = abs(total_impact)
    paras = []
    paras.append(
        f"A portfolio move alert was triggered at {time_str}. The portfolio recorded an "
        f"intraday {direction} move of {abs_pct:.2f}%, exceeding the configured threshold of "
        f"±{pct_threshold:.1f}%. The total dollar impact of this move was approximately "
        f"${abs_impact:,.0f}. This alert is triggered automatically when the aggregate "
        f"intraday portfolio move, measured in USD equivalent terms, crosses the threshold in "
        f"either direction. Single-position moves of ±{pos_threshold:.1f}% or more on individual "
        f"holdings are also flagged as supplementary position alerts."
    )
    if position_alerts:
        tickers = ", ".join(p["ticker"] for p in position_alerts[:5])
        paras.append(
            f"The following positions contributed to or amplified the portfolio move: {tickers}. "
            f"Large intraday moves in individual positions can be driven by earnings announcements, "
            f"analyst rating changes, macro data releases, or sector-wide risk-on/risk-off "
            f"sentiment shifts. The move monitor captures these events in real time during market "
            f"hours to ensure timely awareness of significant portfolio risk events."
        )
        for p in position_alerts[:5]:
            t = p["ticker"]
            pct = p.get("intraday_pct", 0)
            imp = p.get("dollar_impact", 0)
            sign = "gained" if pct >= 0 else "declined"
            paras.append(
                f"{t}: The position {sign} {abs(pct):.2f}% intraday, representing a dollar impact "
                f"of approximately ${abs(imp):,.0f} on the portfolio. This move exceeds the per-position "
                f"alert threshold of ±{pos_threshold:.1f}% and warrants monitoring for follow-through "
                f"in subsequent sessions. If this move is driven by company-specific news, consider "
                f"whether the event changes the fundamental thesis for the position."
            )
    paras.append(
        f"Recommended monitoring actions: review the news flow for each flagged ticker to "
        f"determine if the move is driven by fundamental news or technical/market-wide factors. "
        f"Check whether any analyst rating changes, earnings releases, or macro data prints "
        f"occurred around the time of the alert. If the move is sustained across multiple "
        f"sessions without a clear fundamental catalyst, flag for review in the next weekly "
        f"portfolio rationalization cycle. The portfolio move monitor runs hourly during "
        f"market hours and will issue a further alert if the move extends materially beyond "
        f"the current reading."
    )
    return "\n\n".join(paras)


PORTFOLIO_ALERT_THRESHOLD = 0.015   # ±1.5%
POSITION_ALERT_THRESHOLD  = 0.05    # ±5%
GREEN = "#1a7f37"
RED   = "#cf222e"
GRAY  = "#666"


def main(
    portfolio_db: dict,
    gmail_smtp: dict = {},
    recipient_email: str = "",
    telegram_bot_token: str = "",
    telegram_owner_id: str = "",
    deepseek_key: str = "",
    wm_token: str = "",
):
    sgt = pytz.timezone("Asia/Singapore")
    now_sgt = datetime.now(sgt)

    # ── 1. Load DB ────────────────────────────────────────────────────────
    conn = psycopg2.connect(
        host=portfolio_db["host"], port=portfolio_db["port"],
        dbname=portfolio_db["dbname"], user=portfolio_db["user"],
        password=portfolio_db["password"],
    )
    with conn.cursor() as cur:
        cur.execute("SELECT ticker, company_name, shares, currency FROM portfolio_positions ORDER BY ticker")
        pos_rows = cur.fetchall()

        # Most recent close per ticker (baseline for intraday move)
        cur.execute("""
            SELECT DISTINCT ON (ticker) ticker, close_price, price_date, currency
            FROM price_history
            ORDER BY ticker, price_date DESC
        """)
        baseline_rows = cur.fetchall()

        cur.execute("""
            SELECT rate FROM fx_rates
            WHERE from_currency = 'USD' AND to_currency = 'HKD'
            ORDER BY rate_date DESC LIMIT 1
        """)
        row = cur.fetchone()
        usdhkd = float(row[0]) if row else 7.80
    conn.close()

    baseline = {
        ticker: {"close": float(close), "date": price_date, "currency": currency}
        for ticker, close, price_date, currency in baseline_rows
    }

    def to_usd(amount, currency):
        if currency == "USD": return amount
        if currency == "HKD": return amount / usdhkd
        return None

    # ── 2. Fetch live prices via yfinance ─────────────────────────────────
    positions = []
    for ticker, company, shares, currency in pos_rows:
        shares = float(shares)
        base = baseline.get(ticker)
        if not base:
            log.warning(f"SKIP {ticker}: no baseline price")
            continue

        # Get live price
        live_native = None
        try:
            fi = yf.Ticker(ticker).fast_info
            live_native = fi.last_price
            if live_native is None or live_native != live_native:  # NaN check
                raise ValueError("no live price")
        except Exception as e:
            log.warning(f"SKIP {ticker}: live price failed — {e}")
            continue
        time.sleep(0.2)

        baseline_native = base["close"]
        baseline_usd = to_usd(baseline_native, currency)
        live_usd = to_usd(live_native, currency)

        if not baseline_usd or not live_usd or baseline_usd == 0:
            continue

        intraday_pct    = (live_usd - baseline_usd) / baseline_usd * 100
        dollar_impact   = (live_usd - baseline_usd) * shares
        position_value  = baseline_usd * shares

        positions.append({
            "ticker":         ticker,
            "company":        company,
            "shares":         shares,
            "currency":       currency,
            "live_native":    live_native,
            "baseline_native": baseline_native,
            "baseline_date":  base["date"],
            "intraday_pct":   intraday_pct,
            "dollar_impact":  dollar_impact,
            "position_value": position_value,
        })

    if not positions:
        log.info("No positions with live prices — exiting")
        return {"alerted": False, "reason": "no live prices"}

    # ── 3. Calculate portfolio move ────────────────────────────────────────
    total_value    = sum(p["position_value"] for p in positions)
    total_impact   = sum(p["dollar_impact"]  for p in positions)
    portfolio_move = total_impact / total_value * 100 if total_value else 0

    portfolio_alert  = abs(portfolio_move) >= PORTFOLIO_ALERT_THRESHOLD * 100
    position_alerts  = [p for p in positions if abs(p["intraday_pct"]) >= POSITION_ALERT_THRESHOLD * 100]

    log.info(f"Portfolio move: {portfolio_move:+.2f}% | Position alerts: {len(position_alerts)}")

    # ── 4. Exit silently if no threshold breached ──────────────────────────
    if not portfolio_alert and not position_alerts:
        log.info("No thresholds breached — silent exit")
        return {"alerted": False, "portfolio_move_pct": round(portfolio_move, 2)}

    # ── 5. Build alert email ───────────────────────────────────────────────
    def color(val):
        if val is None: return GRAY
        return GREEN if val >= 0 else RED

    def fmt_pct(val):
        if val is None: return "—"
        sign = "+" if val >= 0 else ""
        return f"{sign}{val:.2f}%"

    def fmt_impact(val):
        if val is None: return "—"
        return f"+${val:,.0f}" if val >= 0 else f"-${abs(val):,.0f}"

    def fmt_price(native, currency):
        sym = "HK$" if currency == "HKD" else "$"
        return f"{sym}{native:,.2f}"

    time_str = now_sgt.strftime("%-d %b %H:%M SGT")
    move_str = fmt_pct(portfolio_move)

    # Sorted by abs(intraday_pct) DESC
    sorted_positions = sorted(positions, key=lambda x: abs(x["intraday_pct"]), reverse=True)

    # Alert badges for position_alerts section
    alerts_html = ""
    if position_alerts:
        alerts_sorted = sorted(position_alerts, key=lambda x: abs(x["intraday_pct"]), reverse=True)
        alerts_html = f'<h3 style="margin:20px 0 8px 0;border-bottom:1px solid #ddd;padding-bottom:4px">Positions ≥ ±5%</h3>'
        alerts_html += '<table style="border-collapse:collapse;margin-bottom:4px">'
        for p in alerts_sorted:
            c  = color(p["intraday_pct"])
            arrow = "▲" if p["intraday_pct"] >= 0 else "▼"
            alerts_html += (
                f'<tr>'
                f'<td style="padding:4px 14px 4px 0;font-family:monospace;font-weight:bold;font-size:14px">{arrow} {p["ticker"]}</td>'
                f'<td style="padding:4px 14px;color:{c};font-weight:bold;font-size:14px">{fmt_pct(p["intraday_pct"])}</td>'
                f'<td style="padding:4px 14px;color:{c};font-family:monospace">{fmt_impact(p["dollar_impact"])}</td>'
                f'<td style="padding:4px 0;color:{GRAY};font-size:12px">'
                f'{fmt_price(p["baseline_native"], p["currency"])} → {fmt_price(p["live_native"], p["currency"])}'
                f'&nbsp;&nbsp;{p["company"]}</td>'
                f'</tr>'
            )
        alerts_html += '</table>'

    # All positions table
    pos_rows_html = ""
    for i, p in enumerate(sorted_positions):
        bg = "#fff" if i % 2 == 0 else "#f9f9f9"
        c  = color(p["intraday_pct"])
        arrow = "▲" if p["intraday_pct"] >= 0 else "▼"
        is_alert = abs(p["intraday_pct"]) >= POSITION_ALERT_THRESHOLD * 100
        weight = "font-weight:bold;" if is_alert else ""
        pos_rows_html += (
            f'<tr style="background:{bg}">'
            f'<td style="padding:3px 10px 3px 6px;font-family:monospace;{weight}">{p["ticker"]}</td>'
            f'<td style="padding:3px 10px;color:{c};{weight}">{arrow} {fmt_pct(p["intraday_pct"])}</td>'
            f'<td style="padding:3px 10px;color:{c};font-family:monospace">{fmt_impact(p["dollar_impact"])}</td>'
            f'<td style="padding:3px 10px;font-family:monospace;font-size:12px">'
            f'{fmt_price(p["baseline_native"], p["currency"])} → {fmt_price(p["live_native"], p["currency"])}</td>'
            f'<td style="padding:3px 0;color:{GRAY};font-size:12px">{p["company"]}</td>'
            f'</tr>'
        )

    tc = color(portfolio_move)
    triggers = []
    if portfolio_alert:
        triggers.append(f"Portfolio {fmt_pct(portfolio_move)}")
    if position_alerts:
        names = ", ".join(p["ticker"] for p in sorted(position_alerts, key=lambda x: abs(x["intraday_pct"]), reverse=True))
        triggers.append(f"Positions: {names}")

    html = f"""<html><body style="font-family:Arial,sans-serif;font-size:13px;color:#222;max-width:840px;margin:0 auto;padding:16px">

<h2 style="margin:0 0 4px 0">Portfolio Alert &nbsp;·&nbsp; {time_str}</h2>
<p style="margin:0 0 20px 0;color:{GRAY}">Trigger: {' | '.join(triggers)}</p>

<table style="border-collapse:collapse;margin-bottom:20px">
  <tr>
    <td style="padding:2px 20px 2px 0;color:{GRAY}">Portfolio Move</td>
    <td style="padding:2px 0;font-size:20px;font-weight:bold;color:{tc}">{fmt_pct(portfolio_move)}</td>
    <td style="padding:2px 0 2px 12px;font-size:16px;color:{tc}">{fmt_impact(total_impact)}</td>
  </tr>
  <tr>
    <td style="padding:2px 20px 2px 0;color:{GRAY}">Baseline</td>
    <td colspan="2" style="padding:2px 0;color:{GRAY};font-size:12px">
      vs most recent close in price history</td>
  </tr>
</table>

{alerts_html}

<h3 style="margin:20px 0 8px 0;border-bottom:1px solid #ddd;padding-bottom:4px">All Positions</h3>
<table style="border-collapse:collapse;width:100%;font-size:12px">
  <thead>
    <tr style="background:#f0f0f0;text-align:left">
      <th style="padding:4px 10px 4px 6px">Ticker</th>
      <th style="padding:4px 10px">Move %</th>
      <th style="padding:4px 10px">Impact</th>
      <th style="padding:4px 10px">Price</th>
      <th style="padding:4px 0">Company</th>
    </tr>
  </thead>
  <tbody>{pos_rows_html}</tbody>
</table>

</body></html>"""

    # ── 6. Send ────────────────────────────────────────────────────────────
    if gmail_smtp:
        subject = f"Portfolio Alert — {move_str} — {time_str}"
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = gmail_smtp["username"]
        msg["To"]      = recipient_email
        msg.attach(MIMEText(html, "html"))

        server = smtplib.SMTP(gmail_smtp["host"], gmail_smtp["port"])
        server.ehlo()
        server.starttls()
        server.login(gmail_smtp["username"], gmail_smtp["password"])
        server.sendmail(gmail_smtp["username"], [recipient_email], msg.as_string())
        server.quit()

        log.info(f"Alert sent: {subject}")

    if telegram_bot_token and telegram_owner_id:
        import os as _os, json as _json
        pct_threshold = PORTFOLIO_ALERT_THRESHOLD * 100
        pos_threshold = POSITION_ALERT_THRESHOLD * 100
        front_matter = {
            "time_str":        time_str,
            "portfolio_move":  round(portfolio_move, 4),
            "total_impact":    round(total_impact, 2),
            "pct_threshold":   pct_threshold,
            "position_alerts": [
                {"ticker": p["ticker"],
                 "intraday_pct": round(p.get("intraday_pct", 0), 4),
                 "dollar_impact": round(p.get("dollar_impact", 0), 2)}
                for p in position_alerts
            ],
            "pos_threshold":   pos_threshold,
        }
        narrative = _build_move_narrative(
            portfolio_move, total_impact, pct_threshold,
            position_alerts, pos_threshold, time_str, deepseek_key,
        )
        _os.makedirs("/research/portfolio", exist_ok=True)
        md_path = f"/research/portfolio/move_{now_sgt.strftime('%Y-%m-%d_%H%M')}.md"
        md_content = (
            f"```json\n{_json.dumps(front_matter, indent=2)}\n```\n\n"
            f"{narrative}\n\n"
            "<!-- DETAIL -->\n"
        )
        with open(md_path, "w") as f:
            f.write(md_content)
        log.info(f"[md] Written {md_path}")
        _dispatch_formatter(
            "portfolio_move_monitor_telegram", md_path,
            telegram_bot_token, telegram_owner_id,
            portfolio_db, wm_token,
        )

    return {
        "alerted":          True,
        "portfolio_move_pct": round(portfolio_move, 2),
        "total_impact_usd": round(total_impact, 2),
        "position_alerts":  [p["ticker"] for p in position_alerts],
        "triggers":         triggers,
        "html":             html if not gmail_smtp else None,
    }
