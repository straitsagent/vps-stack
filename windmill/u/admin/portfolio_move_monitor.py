# Requirements:
# psycopg2-binary>=2.9
# pytz>=2024.1
# yfinance>=0.2.40

import smtplib
import time
import psycopg2
import pytz
import yfinance as yf
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional
import logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
log = logging.getLogger(__name__)


PORTFOLIO_ALERT_THRESHOLD = 0.015   # ±1.5%
POSITION_ALERT_THRESHOLD  = 0.05    # ±5%
GREEN = "#1a7f37"
RED   = "#cf222e"
GRAY  = "#666"


def main(portfolio_db: dict, gmail_smtp: dict = {}, recipient_email: str = ""):
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

    return {
        "alerted":          True,
        "portfolio_move_pct": round(portfolio_move, 2),
        "total_impact_usd": round(total_impact, 2),
        "position_alerts":  [p["ticker"] for p in position_alerts],
        "triggers":         triggers,
        "html":             html if not gmail_smtp else None,
    }
