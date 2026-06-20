# Requirements:
# psycopg2-binary>=2.9
# pytz>=2024.1
# requests>=2.31
# yfinance>=0.2.40
# openai>=1.0.0

import smtplib
import time
import requests
import psycopg2
import pytz
import yfinance as yf
from datetime import date, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional
from openai import OpenAI
import logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
log = logging.getLogger(__name__)


GREEN = "#1a7f37"
RED   = "#cf222e"
GRAY  = "#666"
ETF_TICKERS = {"XLV", "SPY", "QQQ", "IWM", "VTI"}


def _send_telegram(bot_token: str, chat_id: str, text: str):
    try:
        requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception as e:
        log.warning(f"[Telegram] Failed to send: {e}")


def main(portfolio_db: dict, finnhub_key: str, deepseek_key: str, gmail_smtp: dict, recipient_email: str = "", telegram_bot_token: str = "", telegram_owner_id: str = ""):
    today = date.today()

    # ── 1. Load DB ────────────────────────────────────────────────────────
    conn = psycopg2.connect(
        host=portfolio_db["host"], port=portfolio_db["port"],
        dbname=portfolio_db["dbname"], user=portfolio_db["user"],
        password=portfolio_db["password"],
    )
    with conn.cursor() as cur:
        cur.execute("SELECT ticker, company_name, shares, currency FROM portfolio_positions ORDER BY ticker")
        pos_rows = cur.fetchall()

        cur.execute("""
            WITH ranked AS (
                SELECT ticker, price_date, close_price,
                       ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY price_date DESC) AS rn
                FROM price_history
            )
            SELECT ticker, price_date, close_price, rn FROM ranked WHERE rn <= 2
        """)
        price_rows = cur.fetchall()

        cur.execute("""
            SELECT DISTINCT ON (ticker) ticker, pe_ratio, analyst_target_usd, sector, country
            FROM fundamental_data ORDER BY ticker, as_of_date DESC
        """)
        fund_rows = cur.fetchall()

        cur.execute("""
            SELECT rate FROM fx_rates
            WHERE from_currency = 'USD' AND to_currency = 'HKD'
            ORDER BY rate_date DESC LIMIT 1
        """)
        row = cur.fetchone()
        usdhkd = float(row[0]) if row else 7.80
    conn.close()

    # index prices: ticker -> {1: (date, price), 2: (date, price)}
    price_idx = {}
    for ticker, price_date, close_price, rn in price_rows:
        price_idx.setdefault(ticker, {})[rn] = (price_date, float(close_price))

    fund_idx = {
        ticker: {
            "pe_ratio":          float(pe) if pe else None,
            "analyst_target_usd": float(t) if t else None,
            "sector":            sector,
            "country":           country,
        }
        for ticker, pe, t, sector, country in fund_rows
    }

    def to_usd(amount, currency):
        if currency == "USD": return amount
        if currency == "HKD": return amount / usdhkd
        return None

    # ── 2. Compute per-position metrics ───────────────────────────────────
    positions = []
    for ticker, company, shares, currency in pos_rows:
        shares = float(shares)
        prices = price_idx.get(ticker, {})
        curr = prices.get(1)
        prev = prices.get(2)

        if curr is None:
            log.warning(f"SKIP {ticker}: no price data")
            continue

        curr_date, curr_native = curr
        curr_usd = to_usd(curr_native, currency)
        if curr_usd is None:
            log.warning(f"SKIP {ticker}: cannot convert {currency} to USD")
            continue

        curr_value = curr_usd * shares
        week_pct = week_impact = prev_native = None

        if prev is not None:
            _, prev_native = prev
            prev_usd = to_usd(prev_native, currency)
            if prev_usd and prev_usd > 0:
                week_pct    = (curr_usd - prev_usd) / prev_usd * 100
                week_impact = (curr_usd - prev_usd) * shares

        fund = fund_idx.get(ticker, {})
        target_usd = fund.get("analyst_target_usd")
        vs_target  = (curr_usd - target_usd) / target_usd * 100 if target_usd else None

        positions.append({
            "ticker":        ticker,
            "company":       company,
            "shares":        shares,
            "currency":      currency,
            "curr_native":   curr_native,
            "prev_native":   prev_native,
            "curr_usd":      curr_usd,
            "curr_value":    curr_value,
            "week_pct":      week_pct,
            "week_impact":   week_impact,
            "pe_ratio":      fund.get("pe_ratio"),
            "target_usd":    target_usd,
            "vs_target":     vs_target,
            "sector":        fund.get("sector"),
            "country":       fund.get("country"),
        })

    if not positions:
        raise RuntimeError("portfolio_review: no positions with price data — aborting")

    # ── 3. Portfolio summary ───────────────────────────────────────────────
    total_value = sum(p["curr_value"] for p in positions)
    movers      = [p for p in positions if p["week_impact"] is not None]
    week_pnl    = sum(p["week_impact"] for p in movers)
    prev_total  = total_value - week_pnl
    week_pct_total = week_pnl / prev_total * 100 if prev_total > 0 else 0

    sector_totals = {}
    for p in positions:
        s = p["sector"] or "Other"
        sector_totals[s] = sector_totals.get(s, 0) + p["curr_value"]
    sector_weights = sorted(sector_totals.items(), key=lambda x: -x[1])

    hk_value = sum(p["curr_value"] for p in positions if p["ticker"].endswith(".HK"))
    us_value = total_value - hk_value

    # ── 4. Rank movers ─────────────────────────────────────────────────────
    top10_impact = sorted(movers, key=lambda x: abs(x["week_impact"]), reverse=True)[:10]
    top10_pct    = sorted(movers, key=lambda x: abs(x["week_pct"]),    reverse=True)[:10]
    news_tickers = list({p["ticker"] for p in top10_impact + top10_pct})

    # ── 5. Fetch news ──────────────────────────────────────────────────────
    today_str    = today.strftime("%Y-%m-%d")
    week_ago_str = (today - timedelta(days=7)).strftime("%Y-%m-%d")
    news_by_ticker = {}

    for ticker in [t for t in news_tickers if not t.endswith(".HK")]:
        try:
            resp = requests.get(
                "https://finnhub.io/api/v1/company-news",
                params={"symbol": ticker, "from": week_ago_str, "to": today_str},
                headers={"X-Finnhub-Token": finnhub_key},
                timeout=10,
            )
            resp.raise_for_status()
            articles = resp.json()[:5]
            news_by_ticker[ticker] = [
                {"headline": a.get("headline", ""), "summary": a.get("summary", "")[:200], "url": a.get("url", "")}
                for a in articles if a.get("headline")
            ]
            log.info(f"[News] {ticker}: {len(news_by_ticker[ticker])} articles")
        except Exception as e:
            log.warning(f"[News] WARNING: {ticker} failed — {e}")
            news_by_ticker[ticker] = []
        time.sleep(0.3)

    for ticker in [t for t in news_tickers if t.endswith(".HK")]:
        try:
            raw = yf.Ticker(ticker).news or []
            items = []
            for n in raw[:5]:
                # handle both old and new yfinance news formats
                headline = (n.get("title") or n.get("content", {}).get("title") or "")
                url      = (n.get("link") or n.get("content", {}).get("canonicalUrl", {}).get("url") or "")
                if headline:
                    items.append({"headline": headline, "summary": "", "url": url})
            news_by_ticker[ticker] = items
            log.info(f"[News-HK] {ticker}: {len(items)} articles")
        except Exception as e:
            log.warning(f"[News-HK] WARNING: {ticker} failed — {e}")
            news_by_ticker[ticker] = []
        time.sleep(0.5)

    # ── 6. Deepseek commentary ─────────────────────────────────────────────
    days_since_friday = (today.weekday() - 4) % 7
    last_friday = today - timedelta(days=days_since_friday)

    ctx = [
        f"Week ending: {last_friday.strftime('%d %b %Y')}",
        f"Portfolio total value: ${total_value:,.0f}",
        f"Week P&L: ${week_pnl:+,.0f} ({week_pct_total:+.2f}%)",
        f"Sector weights: {', '.join(f'{s} {v/total_value*100:.0f}%' for s, v in sector_weights[:6])}",
        f"Geography: US {us_value/total_value*100:.0f}%, HK {hk_value/total_value*100:.0f}%",
        "",
        "TOP 10 BY PORTFOLIO IMPACT:",
    ]
    for p in top10_impact:
        ctx.append(f"  {p['ticker']} ({p['company']}): {p['week_pct']:+.1f}%, impact ${p['week_impact']:+,.0f}")

    ctx.append("\nTOP 10 BY % CHANGE:")
    for p in top10_pct:
        ctx.append(f"  {p['ticker']} ({p['company']}): {p['week_pct']:+.1f}%, impact ${p['week_impact']:+,.0f}")

    ctx.append("\nRECENT NEWS HEADLINES BY TICKER:")
    for ticker in news_tickers:
        articles = news_by_ticker.get(ticker, [])
        if articles:
            ctx.append(f"\n{ticker}:")
            for a in articles:
                line = f"  - {a['headline']}"
                if a.get("summary"):
                    line += f" — {a['summary']}"
                ctx.append(line)

    prompt = "\n".join(ctx) + f"""

You are reviewing a personal investment portfolio for the week ending {last_friday.strftime('%d %b %Y')}.
Above is the week's price performance and recent news headlines for the top movers.
Write a 2-3 paragraph portfolio commentary covering:
1. What drove the notable movers this week (tie to news where possible)
2. Any valuation observations (e.g. large discount to analyst target, elevated P/E)
3. Key themes or risks across the portfolio (concentration, China exposure, sector trends)
Be factual and concise. Do not give buy/sell recommendations."""

    commentary = None
    try:
        ds = OpenAI(api_key=deepseek_key, base_url="https://api.deepseek.com")
        resp = ds.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=600,
            temperature=0.3,
        )
        commentary = resp.choices[0].message.content.strip()
        log.info(f"[Deepseek] {len(commentary)} chars")
    except Exception as e:
        log.warning(f"[Deepseek] WARNING: failed — {e}")

    # ── 7. Build HTML ──────────────────────────────────────────────────────
    def color(val):
        if val is None: return GRAY
        return GREEN if val >= 0 else RED

    def fmt_pct(val, plus=True):
        if val is None: return "—"
        sign = "+" if val >= 0 and plus else ""
        return f"{sign}{val:.1f}%"

    def fmt_usd(val):
        if val is None: return "—"
        return f"${val:,.0f}"

    def fmt_impact(val):
        if val is None: return "—"
        return f"+${val:,.0f}" if val >= 0 else f"-${abs(val):,.0f}"

    def fmt_price(native, currency):
        sym = "HK$" if currency == "HKD" else "$"
        return f"{sym}{native:,.2f}"

    def fmt_vs_target(val):
        if val is None: return "—"
        if val <= -0.01: return f'<span style="color:{GREEN}">{abs(val):.0f}% disc</span>'
        if val >= 0.01:  return f'<span style="color:{RED}">{val:.0f}% prem</span>'
        return "≈ target"

    def fmt_pe(val, ticker):
        if ticker in ETF_TICKERS: return "ETF"
        if val is None: return "—"
        return f"{val:.0f}x"

    # Snapshot section
    sector_rows = "".join(
        f'<tr><td style="padding:2px 20px 2px 0;color:{GRAY}">{s}</td>'
        f'<td style="padding:2px 0">{v/total_value*100:.1f}%</td></tr>'
        for s, v in sector_weights
    )

    # Top movers tables
    def movers_rows(lst):
        rows = ""
        for p in lst:
            c = color(p["week_impact"])
            arrow = "▲" if (p["week_pct"] or 0) >= 0 else "▼"
            rows += (
                f'<tr>'
                f'<td style="padding:4px 14px 4px 0;font-family:monospace;font-weight:bold">{arrow} {p["ticker"]}</td>'
                f'<td style="padding:4px 14px;color:{c};font-weight:bold">{fmt_pct(p["week_pct"])}</td>'
                f'<td style="padding:4px 14px;color:{c};font-family:monospace">{fmt_impact(p["week_impact"])}</td>'
                f'<td style="padding:4px 0;color:{GRAY};font-size:12px">{p["company"]}</td>'
                f'</tr>'
            )
        return rows

    # News section — ordered: top10_impact first, then pct-only additions
    seen = set()
    news_order = []
    for p in top10_impact + top10_pct:
        if p["ticker"] not in seen:
            news_order.append(p)
            seen.add(p["ticker"])

    news_html = ""
    for p in news_order:
        articles = news_by_ticker.get(p["ticker"], [])
        c = color(p["week_pct"])
        arrow = "▲" if (p["week_pct"] or 0) >= 0 else "▼"
        news_html += (
            f'<div style="margin-bottom:18px">'
            f'<p style="margin:0 0 5px 0">'
            f'<strong style="font-family:monospace">{arrow} {p["ticker"]}</strong>'
            f'<span style="color:{c};font-weight:bold;margin-left:8px">{fmt_pct(p["week_pct"])}</span>'
            f'<span style="color:{GRAY};margin-left:8px;font-size:12px">{fmt_price(p["curr_native"], p["currency"])}'
        )
        if p["prev_native"]:
            news_html += f' (prev {fmt_price(p["prev_native"], p["currency"])})'
        news_html += f'</span><span style="color:{GRAY};margin-left:10px;font-size:12px">{p["company"]}</span></p>'

        if articles:
            news_html += '<ul style="margin:2px 0 0 0;padding-left:18px;line-height:1.7">'
            for a in articles:
                if a.get("url"):
                    news_html += f'<li><a href="{a["url"]}" style="color:#0366d6;text-decoration:none">{a["headline"]}</a></li>'
                else:
                    news_html += f'<li>{a["headline"]}</li>'
            news_html += '</ul>'
        else:
            news_html += f'<p style="margin:2px 0 0 18px;color:{GRAY};font-size:12px">No recent news found</p>'
        news_html += '</div>'

    # All positions table — sorted by abs(week_pct) DESC
    all_sorted = sorted(positions, key=lambda x: abs(x["week_pct"] or 0), reverse=True)
    pos_rows_html = ""
    for i, p in enumerate(all_sorted):
        bg = "#fff" if i % 2 == 0 else "#f9f9f9"
        c  = color(p["week_pct"])
        arrow = "▲" if (p["week_pct"] or 0) >= 0 else "▼"
        price_str = fmt_price(p["curr_native"], p["currency"])
        if p["prev_native"]:
            price_str = fmt_price(p["prev_native"], p["currency"]) + " → " + price_str
        pos_rows_html += (
            f'<tr style="background:{bg}">'
            f'<td style="padding:4px 10px 4px 6px;font-family:monospace;font-weight:bold">{p["ticker"]}</td>'
            f'<td style="padding:4px 10px;font-size:12px;color:{GRAY}">{p["company"]}</td>'
            f'<td style="padding:4px 10px;text-align:right;color:{c};font-weight:bold">{arrow} {fmt_pct(p["week_pct"])}</td>'
            f'<td style="padding:4px 10px;text-align:right;font-family:monospace;font-size:12px">{price_str}</td>'
            f'<td style="padding:4px 10px;text-align:right;font-size:12px">{fmt_vs_target(p["vs_target"])}</td>'
            f'<td style="padding:4px 10px;text-align:right;font-size:12px;color:{GRAY}">{fmt_pe(p["pe_ratio"], p["ticker"])}</td>'
            f'</tr>'
        )

    # Commentary block
    if commentary:
        commentary_html = "<p>" + commentary.replace("\n\n", "</p><p>").replace("\n", " ") + "</p>"
    else:
        commentary_html = f'<p style="color:{GRAY}"><em>Commentary unavailable for this week.</em></p>'

    tc = color(week_pnl)
    subject = (
        f"Portfolio Review — Week ending {last_friday.strftime('%-d %b %Y')} | "
        f"{fmt_usd(total_value)} | Week: {fmt_impact(week_pnl)} ({fmt_pct(week_pct_total)})"
    )

    html = f"""<html><body style="font-family:Arial,sans-serif;font-size:13px;color:#222;max-width:960px;margin:0 auto;padding:16px">

<h2 style="margin:0 0 4px 0">Portfolio Review — Week ending {last_friday.strftime('%-d %b %Y')}</h2>
<p style="margin:0 0 20px 0;color:{GRAY}">{len(positions)} positions &nbsp;·&nbsp; USDHKD {usdhkd:.4f}</p>

<h3 style="margin:0 0 10px 0;border-bottom:1px solid #ddd;padding-bottom:4px">Portfolio Snapshot</h3>
<table style="border-collapse:collapse;margin-bottom:6px">
  <tr>
    <td style="padding:2px 20px 2px 0;color:{GRAY}">Total Value</td>
    <td style="padding:2px 0;font-size:20px;font-weight:bold">{fmt_usd(total_value)}</td>
  </tr>
  <tr>
    <td style="padding:2px 20px 2px 0;color:{GRAY}">Week P&amp;L</td>
    <td style="padding:2px 0;font-size:16px;font-weight:bold;color:{tc}">{fmt_impact(week_pnl)} ({fmt_pct(week_pct_total)})</td>
  </tr>
</table>
<table style="border-collapse:collapse;margin-bottom:4px;font-size:12px">
  <tr><td style="padding:6px 20px 2px 0;font-weight:bold;color:{GRAY};vertical-align:top">Sectors</td>
    <td><table style="border-collapse:collapse">{sector_rows}</table></td>
  </tr>
  <tr>
    <td style="padding:4px 20px 2px 0;font-weight:bold;color:{GRAY}">Geography</td>
    <td style="padding:4px 0">US {us_value/total_value*100:.0f}% &nbsp;·&nbsp; HK {hk_value/total_value*100:.0f}%</td>
  </tr>
</table>

<h3 style="margin:24px 0 8px 0;border-bottom:1px solid #ddd;padding-bottom:4px">Top 10 — Portfolio Impact</h3>
<table style="border-collapse:collapse;margin-bottom:4px">{movers_rows(top10_impact)}</table>

<h3 style="margin:24px 0 8px 0;border-bottom:1px solid #ddd;padding-bottom:4px">Top 10 — Price Movers (%)</h3>
<table style="border-collapse:collapse;margin-bottom:4px">{movers_rows(top10_pct)}</table>

<h3 style="margin:24px 0 8px 0;border-bottom:1px solid #ddd;padding-bottom:4px">News — Top Movers</h3>
{news_html}

<h3 style="margin:24px 0 8px 0;border-bottom:1px solid #ddd;padding-bottom:4px">All Positions</h3>
<table style="border-collapse:collapse;width:100%;font-size:12px">
  <thead>
    <tr style="background:#f0f0f0;text-align:left">
      <th style="padding:5px 10px 5px 6px">Ticker</th>
      <th style="padding:5px 10px">Company</th>
      <th style="padding:5px 10px;text-align:right">Week %</th>
      <th style="padding:5px 10px;text-align:right">Price (prev → curr)</th>
      <th style="padding:5px 10px;text-align:right">vs Target</th>
      <th style="padding:5px 10px;text-align:right">P/E</th>
    </tr>
  </thead>
  <tbody>{pos_rows_html}</tbody>
  <tfoot>
    <tr style="font-weight:bold;border-top:2px solid #ccc;background:#f0f0f0">
      <td colspan="2" style="padding:5px 10px 5px 6px">PORTFOLIO TOTAL</td>
      <td style="padding:5px 10px;text-align:right;color:{tc}">{fmt_pct(week_pct_total)}</td>
      <td colspan="3" style="padding:5px 10px;color:{tc}">{fmt_impact(week_pnl)} week P&amp;L</td>
    </tr>
  </tfoot>
</table>

<h3 style="margin:24px 0 8px 0;border-bottom:1px solid #ddd;padding-bottom:4px">Weekly Commentary</h3>
<div style="line-height:1.7;max-width:820px">{commentary_html}</div>

</body></html>"""

    # ── 8. Send ────────────────────────────────────────────────────────────
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

    log.info(f"Sent: {subject}")

    if telegram_bot_token and telegram_owner_id:
        we_str = last_friday.strftime("%-d %b")
        sign_pnl = "+" if week_pnl >= 0 else ""
        sign_pct = "+" if week_pct_total >= 0 else ""
        week_k = week_pnl / 1000
        gainers = sorted([p for p in top10_impact if (p.get("week_impact") or 0) > 0],
                         key=lambda x: x["week_impact"], reverse=True)[:2]
        losers  = sorted([p for p in top10_impact if (p.get("week_impact") or 0) < 0],
                         key=lambda x: x["week_impact"])[:2]
        def _mover_str(p):
            pct = f"{'+' if (p.get('week_pct') or 0) >= 0 else ''}{p.get('week_pct') or 0:.1f}%"
            wi = p.get("week_impact") or 0
            k = wi / 1000
            impact = f" (+${k:.1f}k)" if wi >= 0 else f" (-${abs(k):.1f}k)"
            return f"{p['ticker']} {pct}{impact}"
        g_str = "  ".join(_mover_str(p) for p in gainers) or "—"
        l_str = "  ".join(_mover_str(p) for p in losers) or "—"
        tg_text = (
            f"*Weekly Review — w/e {we_str}*\n"
            f"{fmt_usd(total_value)} | Week: {sign_pnl}${abs(week_k):.1f}k ({sign_pct}{week_pct_total:.2f}%)\n\n"
            f"📈 {g_str}\n"
            f"📉 {l_str}\n\n"
            f"_Full review → email_"
        )
        _send_telegram(telegram_bot_token, telegram_owner_id, tg_text)

    return {
        "positions": len(positions),
        "total_value_usd": round(total_value, 2),
        "week_pnl_usd": round(week_pnl, 2),
        "week_pct": round(week_pct_total, 2),
        "news_tickers": len(news_tickers),
        "commentary_chars": len(commentary) if commentary else 0,
    }
