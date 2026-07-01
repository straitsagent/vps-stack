# Requirements:
# psycopg2-binary>=2.9
# pytz>=2024.1
# yfinance>=0.2.40
# feedparser>=6.0

import feedparser
import json
import smtplib
import time
import urllib.parse
import psycopg2
import pytz
import requests
import yfinance as yf
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional
import logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
log = logging.getLogger(__name__)


WM_BASE      = "http://windmill_server:8000"
WM_WORKSPACE = "admins"

ARTIFACT_MARKERS: dict[str, list[str]] = {
    "Move Monitor": ["triggered", "threshold"],
}



def _send_email(gmail_smtp: dict, recipient_email: str, subject: str, html: str) -> None:
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
    log.info(f"Alert sent to {recipient_email}")


def _write_canonical_md(content: str, path: str) -> None:
    with open(path, "w") as f:
        f.write(content)



# ── News-fetching helpers (each independently try/excepted) ──────────────────

def _fetch_finnhub_news(ticker: str, finnhub_key: str, max_items: int = 5) -> list[dict]:
    try:
        r = requests.get(
            "https://finnhub.io/api/v1/company-news",
            params={"symbol": ticker, "from": (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d"),
                    "to": datetime.now(timezone.utc).strftime("%Y-%m-%d")},
            headers={"X-Finnhub-Token": finnhub_key},
            timeout=10,
        )
        r.raise_for_status()
        items = r.json()[:max_items]
        return [{"source": "finnhub", "title": i.get("headline", ""), "url": i.get("url", ""),
                 "date": i.get("datetime", "")} for i in items if i.get("headline")]
    except Exception as e:
        log.warning(f"[News] Finnhub failed for {ticker}: {e}")
        return []


def _fetch_google_news_for_ticker(query: str, max_items: int = 5) -> list[dict]:
    try:
        url = f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl=en-US&gl=US&ceid=US:en"
        parsed = feedparser.parse(url)
        items = []
        for entry in parsed.entries[:max_items]:
            items.append({"source": "google_news", "title": entry.get("title", ""),
                          "url": entry.get("link", ""), "date": entry.get("published", "")})
        return items
    except Exception as e:
        log.warning(f"[News] Google News RSS failed for {query}: {e}")
        return []


def _fetch_seeking_alpha_news(ticker: str, max_items: int = 5) -> list[dict]:
    try:
        url = f"https://seekingalpha.com/api/sa/combined/{ticker}.xml"
        parsed = feedparser.parse(url)
        items = []
        for entry in parsed.entries[:max_items]:
            items.append({"source": "seeking_alpha", "title": entry.get("title", ""),
                          "url": entry.get("link", ""), "date": entry.get("published", "")})
        return items
    except Exception as e:
        log.warning(f"[News] Seeking Alpha failed for {ticker}: {e}")
        return []


def _fetch_yfinance_news(ticker: str, max_items: int = 5) -> list[dict]:
    try:
        tk = yf.Ticker(ticker)
        news = tk.news[:max_items] if tk.news else []
        return [{"source": "yfinance", "title": i.get("title", ""),
                 "url": i.get("link", ""), "date": i.get("providerPublishTime", "")} for i in news if i.get("title")]
    except Exception as e:
        log.warning(f"[News] yfinance failed for {ticker}: {e}")
        return []


def _fetch_ticker_news(ticker: str, company: str, is_us: bool, finnhub_key: str) -> list[dict]:
    all_items = []
    if is_us:
        all_items.extend(_fetch_finnhub_news(ticker, finnhub_key))
    all_items.extend(_fetch_seeking_alpha_news(ticker))
    all_items.extend(_fetch_yfinance_news(ticker))
    google_query = f"{company} {ticker}" if company else ticker
    all_items.extend(_fetch_google_news_for_ticker(google_query))
    return all_items[:5]


INDEX_SYMBOLS = {
    "HK":  {"HSI": "EWH", "CSI300": "FXI"},
    "US":  {"SP500": "SPY", "NDX": "QQQ"},
}


def _fetch_index_moves(session: str) -> dict:
    try:
        result = {}
        for name, sym in INDEX_SYMBOLS.get(session, {}).items():
            fi = yf.Ticker(sym).fast_info
            live = fi.last_price
            prev = fi.previous_close
            if live and prev and prev != 0:
                result[name] = {"symbol": sym, "pct": round((live - prev) / prev * 100, 2)}
            else:
                result[name] = {"symbol": sym, "pct": None}
        return result
    except Exception as e:
        log.warning(f"[Index] Failed to fetch {session} index moves: {e}")
        return {}


def _build_move_narrative(portfolio_move: float, total_impact: float,
                           pct_threshold: float, position_alerts: list,
                           pos_threshold: float, time_str: str,
                           trigger_desc: str, index_desc: str,
                           total_portfolio_value: float,
                           breadth: dict, deepseek_key: str = "") -> str:
    if deepseek_key:
        pos_desc = "\n".join(
            f"  {p['ticker']} ({p.get('company','')}, {p.get('shares',0):.0f} shares): {p['intraday_pct']:+.2f}% "
            f"($${abs(p.get('dollar_impact',0)):,.0f} impact, {p.get('currency','USD')} "
            f"{p.get('previous_close',0):.2f} -> {p.get('current_price',0):.2f})\n"
            f"    News: " + ("; ".join(f"[{n['source']}] {n['title']}" for n in p.get('news',[])) if p.get('news') else "none found")
            for p in position_alerts
        )
        prompt = (
            f"You are a portfolio risk analyst. A portfolio move alert was triggered at {time_str} "
            f"({INDEX_SYMBOLS.get('session','').keys() or '?'} session).\n\n"
            f"What triggered this alert: {trigger_desc}\n"
            f"Portfolio value: ${total_portfolio_value:,.0f} | Dollar impact of this move: ${abs(total_impact):,.0f}\n"
            f"Market breadth: {breadth.get('up',0)} up / {breadth.get('down',0)} down / "
            f"{breadth.get('flat',0)} flat (of {breadth.get('total',0)} positions)\n"
            f"Index context: {index_desc}\n\n"
            f"All flagged positions ({len(position_alerts)} total):\n{pos_desc}\n\n"
            f"Write a detailed >=500-word analytical report explaining likely causes of this move, "
            f"the risk implications, what to watch next, and any recommended monitoring actions. "
            f"Use the index context to state plainly whether this looks like a market-wide (beta-driven) "
            f"move or a stock-specific move. For each flagged position, use the provided news headlines "
            f"(if any) to ground your explanation of the move in an actual reported catalyst — cite the "
            f"headline briefly. If no news is provided for a position, say so explicitly and describe it "
            f"as an unexplained/technical move rather than inventing a cause. State plainly and accurately "
            f"which threshold(s) were actually breached — do not claim the portfolio-level threshold was "
            f"exceeded unless it genuinely was. Continuous prose, no bullet points or headers. Minimum 500 words."
        )
        try:
            r = requests.post(
                "https://api.deepseek.com/chat/completions",
                headers={"Authorization": f"Bearer {deepseek_key}"},
                json={"model": "deepseek-chat",
                      "messages": [{"role": "user", "content": prompt}],
                      "temperature": 0.4, "max_tokens": 1000},
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
        f"A portfolio move alert was triggered at {time_str}. "
        f"Trigger: {trigger_desc}. "
        f"The portfolio recorded an intraday {direction} move of {abs_pct:.2f}% "
        f"({'' if not portfolio_move or abs(portfolio_move) < pct_threshold else 'exceeding the configured threshold of ' + f'±{pct_threshold:.1f}%'}). "
        f"Total dollar impact: ${abs_impact:,.0f}. "
        f"Market breadth: {breadth.get('up',0)} up / {breadth.get('down',0)} down / {breadth.get('flat',0)} flat positions."
    )
    if position_alerts:
        tickers = ", ".join(p["ticker"] for p in position_alerts)
        paras.append(
            f"Flagged positions ({len(position_alerts)} total): {tickers}."
        )
        for p in position_alerts:
            t = p["ticker"]
            pct = p.get("intraday_pct", 0)
            imp = p.get("dollar_impact", 0)
            sign = "gained" if pct >= 0 else "declined"
            price_info = f"Price: {p.get('previous_close',0):.2f} -> {p.get('current_price',0):.2f}"
            news_bit = ""
            if p.get("news"):
                news_bit = " Recent news: " + "; ".join(n.get("title","") for n in p["news"][:2])
            paras.append(
                f"{t}: {sign} {abs(pct):.2f}% (${abs(imp):,.0f}). "
                f"{price_info}.{news_bit}"
            )
    paras.append(
        f"Recommended monitoring actions: review the news flow for each flagged ticker to "
        f"determine if the move is driven by fundamental news or technical/market-wide factors. "
        f"Check whether any analyst rating changes, earnings releases, or macro data prints "
        f"occurred around the time of the alert. If the move is sustained across multiple "
        f"sessions without a clear fundamental catalyst, flag for review in the next weekly "
        f"portfolio rationalization cycle."
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
    deepseek_key: str = "",
    finnhub_key: str = "",
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

    # ── 6. Send email ──────────────────────────────────────────────────────
    if gmail_smtp:
        subject = f"Portfolio Alert — {move_str} — {time_str}"
        _send_email(gmail_smtp, recipient_email, subject, html)

    # ── 7. Build enriched .md (always — Hermes consumes this) ──────────────
    import os as _os, json as _json
    pct_threshold_pct = PORTFOLIO_ALERT_THRESHOLD * 100
    pos_threshold_pct = POSITION_ALERT_THRESHOLD * 100

    session = "HK" if 9 <= now_sgt.hour <= 16 else "US"
    breadth_up   = sum(1 for p in positions if p["intraday_pct"] > 0.01)
    breadth_down = sum(1 for p in positions if p["intraday_pct"] < -0.01)
    breadth = {"up": breadth_up, "down": breadth_down,
               "flat": len(positions) - breadth_up - breadth_down, "total": len(positions)}
    index_moves = _fetch_index_moves(session)

    portfolio_triggered = portfolio_alert
    position_triggered = len(position_alerts) > 0
    trigger_desc = (
        f"both the portfolio-level threshold (\u00b1{pct_threshold_pct:.1f}%) and "
        f"{len(position_alerts)} position-level threshold(s) (\u00b1{pos_threshold_pct:.1f}%)"
        if portfolio_triggered and position_triggered
        else f"the portfolio-level threshold (\u00b1{pct_threshold_pct:.1f}%)"
        if portfolio_triggered
        else f"{len(position_alerts)} position-level threshold(s) (\u00b1{pos_threshold_pct:.1f}%) only \u2014 "
             f"the portfolio-level move of {portfolio_move:+.2f}% did not itself cross "
             f"\u00b1{pct_threshold_pct:.1f}%"
    )
    index_desc = ", ".join(f"{k} ({v['symbol']}) {v['pct']:+.2f}%" for k, v in index_moves.items()) or "unavailable"

    # Enrich position_alerts with previous_close, current_price, shares, news
    for p in position_alerts:
        p["previous_close"] = p.get("baseline_native")
        p["current_price"]  = p.get("live_native")
        p["shares"]          = p["shares"]
        p["news"] = _fetch_ticker_news(
            p["ticker"], p.get("company", ""), not p["ticker"].endswith(".HK"), finnhub_key
        )

    front_matter = {
        "time_str":        time_str,
        "portfolio_move":  round(portfolio_move, 4),
        "total_impact":    round(total_impact, 2),
        "pct_threshold":   pct_threshold_pct,
        "pos_threshold":   pos_threshold_pct,
        "session":         session,
        "total_portfolio_value_usd": round(total_value, 2),
        "portfolio_triggered": portfolio_triggered,
        "position_triggered": position_triggered,
        "breadth":         breadth,
        "index_moves":     index_moves,
        "position_alerts": [
            {"ticker": p["ticker"], "company": p.get("company", ""),
             "shares": p["shares"], "intraday_pct": round(p.get("intraday_pct", 0), 4),
             "dollar_impact": round(p.get("dollar_impact", 0), 2),
             "previous_close": p.get("previous_close"),
             "current_price": p.get("current_price"),
             "currency": p.get("currency", "USD"),
             "news": p.get("news", [])}
            for p in position_alerts
        ],
    }
    narrative = _build_move_narrative(
        portfolio_move, total_impact, pct_threshold_pct,
        position_alerts, pos_threshold_pct, time_str,
        trigger_desc, index_desc, total_value, breadth, deepseek_key,
    )
    _os.makedirs("/research/portfolio", exist_ok=True)
    md_path = f"/research/portfolio/move_{now_sgt.strftime('%Y-%m-%d_%H%M')}.md"
    md_content = (
        f"```json\n{_json.dumps(front_matter, indent=2)}\n```\n\n"
        f"{narrative}\n\n"
        "<!-- DETAIL -->\n"
    )
    _write_canonical_md(md_content, md_path)
    log.info(f"[md] Written {md_path}")

    return {
        "alerted":          True,
        "portfolio_move_pct": round(portfolio_move, 2),
        "total_impact_usd": round(total_impact, 2),
        "position_alerts":  [p["ticker"] for p in position_alerts],
        "triggers":         triggers,
        "html":             html if not gmail_smtp else None,
    }
