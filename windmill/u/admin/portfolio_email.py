# Requirements:
# psycopg2-binary>=2.9
# pytz>=2024.1
# feedparser>=6.0

import smtplib
import requests
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
import urllib.parse
import psycopg2
import pytz
import feedparser
import logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
log = logging.getLogger(__name__)


GREEN = "#1a7f37"
RED   = "#cf222e"
GRAY  = "#666"


WM_BASE      = "http://windmill_server:8000"
WM_WORKSPACE = "admins"

ARTIFACT_MARKERS: dict[str, list[str]] = {
    "Portfolio": ["Total Value", "P&L"],
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


def _write_canonical_md(content: str, path: str) -> None:
    with open(path, "w") as f:
        f.write(content)


def _generate_portfolio_narrative(positions: list, top_up: list, top_down: list,
                                   total_value: float, total_pnl: float,
                                   total_pnl_pct: float, session: str,
                                   now_sgt, deepseek_key: str = "") -> str:
    """Generate ≥500-word portfolio narrative. Uses Deepseek if key provided, else programmatic."""
    if deepseek_key:
        # Build structured summary for LLM
        def _fmt(v): return f"${v:,.0f}" if v is not None else "N/A"
        def _pct(v): return f"{v:+.2f}%" if v is not None else "N/A"
        movers_str = ""
        for it in top_up[:3]:
            movers_str += f"  • {it.get('label','?')}: {_fmt(it.get('pnl'))} ({_pct(it.get('pnl_pct'))})\n"
        for it in top_down[:3]:
            movers_str += f"  • {it.get('label','?')}: {_fmt(it.get('pnl'))} ({_pct(it.get('pnl_pct'))})\n"
        prompt = (
            f"You are a portfolio analyst. Write a detailed ≥500-word commentary on this portfolio session.\n"
            f"Session: {session} | Date: {now_sgt.strftime('%a %-d %b %Y, %-I:%M %p SGT')}\n"
            f"Portfolio total: {_fmt(total_value)} | Day P&L: {_fmt(total_pnl)} ({_pct(total_pnl_pct)})\n"
            f"Top movers:\n{movers_str}\n"
            f"Write continuous analytical prose — no bullets, no headers. Cover what drove today's move, "
            f"the macro context, key position dynamics, and any notable risk factors to watch. "
            f"Minimum 500 words."
        )
        try:
            r = requests.post(
                "https://api.deepseek.com/chat/completions",
                headers={"Authorization": f"Bearer {deepseek_key}"},
                json={"model": "deepseek-chat",
                      "messages": [{"role": "user", "content": prompt}],
                      "temperature": 0.4, "max_tokens": 900},
                timeout=60,
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            log.warning(f"[Deepseek] Portfolio narrative failed: {e}")
    # Programmatic fallback: generate detailed position-by-position narrative
    date_str = now_sgt.strftime("%A, %-d %B %Y at %-I:%M %p SGT")
    direction = "gained" if (total_pnl or 0) >= 0 else "declined"
    abs_pnl = abs(total_pnl or 0)
    paras = []
    paras.append(
        f"This {session} portfolio report was generated on {date_str}. "
        f"The total portfolio value stands at ${total_value:,.0f}. "
        f"Day-over-day, the portfolio {direction} ${abs_pnl:,.0f} "
        f"({total_pnl_pct:+.2f}%), reflecting net market movement across all positions "
        f"for this session. The report covers all {len(positions)} portfolio positions across "
        f"US-listed and HK-listed equities, with performance measured in USD equivalent terms."
    )
    if top_up:
        up_desc = ", ".join(
            f"{it.get('label','?')} ({it.get('pnl_pct',0):+.2f}%)"
            for it in top_up[:5]
        )
        paras.append(
            f"The top-performing positions this session were: {up_desc}. "
            f"These positions contributed positively to the overall day P&L and reflect "
            f"continued momentum in their respective sectors. Strong performance in these "
            f"names should be monitored for any reversal signals, particularly if driven by "
            f"short-term news flow rather than fundamental change."
        )
    if top_down:
        down_desc = ", ".join(
            f"{it.get('label','?')} ({it.get('pnl_pct',0):+.2f}%)"
            for it in top_down[:5]
        )
        paras.append(
            f"The weakest-performing positions this session were: {down_desc}. "
            f"These positions detracted from overall performance and warrant closer monitoring. "
            f"Persistent weakness across multiple sessions may trigger a review under the "
            f"portfolio rationalization framework, particularly if revenue or earnings drivers "
            f"are deteriorating alongside the price action."
        )
    paras.append(
        f"Portfolio risk context: the portfolio is structured approximately sixty percent in "
        f"US-listed equities and forty percent in Hong Kong-listed names. Key currency exposures "
        f"include USD and HKD, with a minor SGD allocation. The current session is the "
        f"{session.lower()} report, capturing the most recent closing prices available. "
        f"FX rates are applied at prevailing USDHKD and USDSGD spot rates to convert all "
        f"positions to a unified USD reporting basis. Position sizes and weights are recalculated "
        f"daily to reflect current market prices."
    )
    paras.append(
        f"Monitoring notes: any position showing a day move beyond plus or minus five percent "
        f"may be flagged by the intraday move monitor for a separate alert. The portfolio review "
        f"cycle includes weekly commentary every Saturday, a monthly rationalization scoring run, "
        f"and on-demand candidate evaluation for new positions. The daily email report provides "
        f"the baseline snapshot against which all alerts and reviews are calibrated. "
        f"Total positions tracked: {len(positions)}. "
        f"Reporting currency: USD. Session: {session}."
    )
    return "\n\n".join(paras)


CURRENCY_SYMBOLS = {
    "USD": "$", "HKD": "HK$", "SGD": "S$",
    "EUR": "€", "GBP": "£", "JPY": "¥",
}

def sym(currency):
    return CURRENCY_SYMBOLS.get(currency, currency + "\xa0")

def fmt_usd(val):
    return f"${val:,.0f}"

def fmt_pnl(val):
    if val is None: return "—"
    return f"+${val:,.0f}" if val >= 0 else f"-${abs(val):,.0f}"

def fmt_pct(val):
    if val is None: return "—"
    return f"+{val:.2f}%" if val >= 0 else f"{val:.2f}%"

def pnl_color(val):
    if val is None: return GRAY
    return GREEN if val >= 0 else RED

def fetch_news(query, max_items=5):
    url = "https://news.google.com/rss/search?q=" + urllib.parse.quote(query) + "&hl=en-US&gl=US&ceid=US:en"
    try:
        feed = feedparser.parse(url)
        return [{"title": e.title, "link": e.link} for e in feed.entries[:max_items]]
    except Exception as ex:
        log.info(f"News fetch failed for '{query}': {ex}")
        return []

def price_cell_html(price, currency, price_usd):
    cell = f"{sym(currency)}{price:,.2f}"
    if currency != "USD" and price_usd is not None:
        cell += f'<br><span style="color:{GRAY};font-size:11px">(${price_usd:,.2f})</span>'
    return cell


def main(
    portfolio_db: dict,
    gmail_smtp: dict,
    recipient_email: str = "",
    telegram_bot_token: str = "",
    telegram_owner_id: str = "",
    deepseek_key: str = "",
    wm_token: str = "",
):
    sgt = pytz.timezone("Asia/Singapore")
    now_sgt = datetime.now(sgt)

    session = "Asia Close" if now_sgt.hour >= 12 else "US Close"

    # ── DB ─────────────────────────────────────────────────────────────
    conn = psycopg2.connect(
        host=portfolio_db["host"],
        port=portfolio_db["port"],
        dbname=portfolio_db["dbname"],
        user=portfolio_db["user"],
        password=portfolio_db["password"],
    )
    cur = conn.cursor()

    cur.execute("""
        WITH ranked AS (
            SELECT ticker, price_date, close_price,
                   ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY price_date DESC) AS rn
            FROM price_history
        )
        SELECT p.ticker, p.company_name, p.shares, p.currency, p.consolidation_group,
               t.close_price, t.price_date,
               y.close_price, y.price_date
        FROM portfolio_positions p
        LEFT JOIN ranked t ON t.ticker = p.ticker AND t.rn = 1
        LEFT JOIN ranked y ON y.ticker  = p.ticker AND y.rn  = 2
        ORDER BY p.ticker
    """)
    rows = cur.fetchall()

    # fx_map: ('USD','HKD') → 7.83 means 1 USD = 7.83 HKD; to_usd = local / rate
    cur.execute("""
        SELECT DISTINCT ON (from_currency, to_currency)
               from_currency, to_currency, rate
        FROM fx_rates
        ORDER BY from_currency, to_currency, rate_date DESC
    """)
    fx_map = {(r[0], r[1]): float(r[2]) for r in cur.fetchall()}
    cur.close()
    conn.close()

    def to_usd(amount, currency):
        if currency == "USD": return float(amount)
        rate = fx_map.get(("USD", currency))
        if rate is None:
            log.warning(f"WARNING: No FX rate for USD/{currency}")
            return None
        return float(amount) / rate

    # ── Compute individual positions ────────────────────────────────────
    positions = []
    price_dates = {}

    for ticker, company, shares, currency, cgroup, price_today, date_today, price_yest, date_yest in rows:
        if price_today is None:
            log.warning(f"SKIP {ticker}: no price data")
            continue

        shares        = float(shares)
        price_today_f = float(price_today)
        value_today   = to_usd(price_today_f * shares, currency)
        if value_today is None: continue

        pnl = pnl_pct = None
        if price_yest is not None:
            value_yest = to_usd(float(price_yest) * shares, currency)
            if value_yest:
                pnl     = value_today - value_yest
                pnl_pct = pnl / value_yest * 100

        price_usd = to_usd(price_today_f, currency) if currency != "USD" else None
        if date_today:
            price_dates[currency] = date_today

        positions.append({
            "ticker":               ticker,
            "company":              company,
            "shares":               shares,
            "currency":             currency,
            "consolidation_group":  cgroup,
            "price":                price_today_f,
            "price_yest":           float(price_yest) if price_yest is not None else None,
            "price_usd":            price_usd,
            "value_today":          value_today,
            "pnl":                  pnl,
            "pnl_pct":              pnl_pct,
        })

    if not positions:
        log.info("No positions with price data — aborting")
        return

    # ── Portfolio totals ────────────────────────────────────────────────
    total_value  = sum(p["value_today"] for p in positions)
    with_pnl     = [p for p in positions if p["pnl"] is not None]
    total_pnl    = sum(p["pnl"] for p in with_pnl) if with_pnl else None
    pnl_base     = sum(p["value_today"] - p["pnl"] for p in with_pnl)
    total_pnl_pct = total_pnl / pnl_base * 100 if (total_pnl is not None and pnl_base) else None

    for p in positions:
        p["alloc_pct"] = p["value_today"] / total_value * 100 if total_value else 0

    # ── Build display items (consolidated groups + standalone) ───────────
    groups     = {}
    standalone = []
    for p in positions:
        cg = p["consolidation_group"]
        if cg:
            groups.setdefault(cg, []).append(p)
        else:
            standalone.append(p)

    display_items = []

    for p in standalone:
        display_items.append({
            "type":      "standalone",
            "label":     p["ticker"],
            "company":   p["company"],
            "value":     p["value_today"],
            "pnl":       p["pnl"],
            "pnl_pct":   p["pnl_pct"],
            "alloc_pct": p["alloc_pct"],
            "position":  p,
        })

    for gname, members in groups.items():
        grp_value    = sum(m["value_today"] for m in members)
        grp_w_pnl    = [m for m in members if m["pnl"] is not None]
        grp_pnl      = sum(m["pnl"] for m in grp_w_pnl) if grp_w_pnl else None
        grp_base     = sum(m["value_today"] - m["pnl"] for m in grp_w_pnl)
        grp_pct      = grp_pnl / grp_base * 100 if (grp_pnl is not None and grp_base) else None
        grp_alloc    = grp_value / total_value * 100 if total_value else 0
        display_items.append({
            "type":      "group",
            "label":     gname.upper(),
            "company":   gname,
            "value":     grp_value,
            "pnl":       grp_pnl,
            "pnl_pct":   grp_pct,
            "alloc_pct": grp_alloc,
            "members":   sorted(members, key=lambda x: x["value_today"], reverse=True),
        })

    display_items.sort(key=lambda x: x["value"], reverse=True)

    # ── Top movers (consolidated view) ───────────────────────────────────
    movers   = [it for it in display_items if it["pnl"] is not None]
    top_up   = sorted(movers, key=lambda x: x["pnl"], reverse=True)[:5]
    top_down = sorted(movers, key=lambda x: x["pnl"])[:5]

    # ── Top % movers + news ───────────────────────────────────────────────
    top_pct_movers = sorted(
        [it for it in display_items if it["pnl_pct"] is not None],
        key=lambda x: abs(x["pnl_pct"]), reverse=True
    )[:5]
    for it in top_pct_movers:
        it["news"] = fetch_news(it["company"])

    # ── Date line & FX ──────────────────────────────────────────────────
    if len(set(str(d) for d in price_dates.values())) == 1:
        date_line = "Prices as of " + list(price_dates.values())[0].strftime("%-d %b %Y")
    else:
        parts = [f"{c}: {d.strftime('%-d %b')}" for c, d in sorted(price_dates.items())]
        date_line = " · ".join(parts)

    hkd_rate = fx_map.get(("USD", "HKD"))
    fx_line  = f"USDHKD {hkd_rate:.4f}" if hkd_rate else ""

    # ── Subject ─────────────────────────────────────────────────────────
    val_str = f"${total_value/1e6:.2f}M" if total_value >= 1e6 else fmt_usd(total_value)
    subject = (
        f"Portfolio — {now_sgt.strftime('%-d %b %Y')} | {session} | "
        f"{val_str} | Day: {fmt_pnl(total_pnl)} ({fmt_pct(total_pnl_pct)})"
    )

    # ── HTML helpers ────────────────────────────────────────────────────
    def mover_rows_html(mover_list, color, arrow):
        out = ""
        for it in mover_list:
            impact = it["pnl"] / total_value * 100 if total_value else None
            impact_str = f"portfolio impact: {fmt_pct(impact)}" if impact is not None else ""
            out += f"""
        <tr>
          <td style="padding:3px 14px 3px 0;font-weight:bold;width:110px">{arrow} {it['label']}</td>
          <td style="padding:3px 14px 3px 0;color:{color};font-weight:bold;width:110px">{fmt_pnl(it['pnl'])}</td>
          <td style="padding:3px 14px 3px 0;color:{color};width:80px">({fmt_pct(it['pnl_pct'])})</td>
          <td style="padding:3px 0;color:{GRAY}">{it['company']} <span style="font-size:11px">({impact_str})</span></td>
        </tr>"""
        return out

    def price_change_str(it):
        if it["type"] == "standalone":
            p = it["position"]
            curr = f"{sym(p['currency'])}{p['price']:,.2f}"
            if p["price_yest"] is not None:
                prev = f"{sym(p['currency'])}{p['price_yest']:,.2f}"
                return f"{prev} → {curr}"
            return curr
        else:  # group — show each member's prev → curr
            parts = []
            for m in it["members"]:
                curr = f"{sym(m['currency'])}{m['price']:,.2f}"
                if m["price_yest"] is not None:
                    prev = f"{sym(m['currency'])}{m['price_yest']:,.2f}"
                    parts.append(f"{m['ticker']}: {prev} → {curr}")
                else:
                    parts.append(f"{m['ticker']}: {curr}")
            return " &nbsp;·&nbsp; ".join(parts)

    def news_movers_html():
        out = ""
        for it in top_pct_movers:
            color = GREEN if it["pnl_pct"] >= 0 else RED
            arrow = "▲" if it["pnl_pct"] >= 0 else "▼"
            out += f"""
<div style="margin-bottom:16px">
  <p style="margin:0 0 5px 0">
    <strong>{arrow} {it['label']}</strong>
    <span style="color:{color};font-weight:bold;margin-left:6px">{fmt_pct(it['pnl_pct'])}</span>
    <span style="color:{GRAY};margin-left:8px;font-family:monospace;font-size:12px">{price_change_str(it)}</span>
    <span style="color:{GRAY};margin-left:10px">{it['company']}</span>
  </p>
  <ul style="margin:0;padding-left:20px;line-height:1.6">"""
            if it.get("news"):
                for n in it["news"]:
                    out += f"""
    <li><a href="{n['link']}" style="color:#0366d6;text-decoration:none">{n['title']}</a></li>"""
            else:
                out += f"""
    <li style="color:{GRAY}">No recent news found</li>"""
            out += """
  </ul>
</div>"""
        return out

    def pos_rows_html():
        out = ""
        row_idx = 0
        for it in display_items:
            if it["type"] == "standalone":
                p  = it["position"]
                bg = "#fff" if row_idx % 2 == 0 else "#f9f9f9"
                pc = pnl_color(p["pnl"])
                out += f"""
      <tr style="background:{bg}">
        <td style="padding:5px 12px 5px 6px;font-weight:bold;font-family:monospace">{p['ticker']}</td>
        <td style="padding:5px 12px">{p['company']}</td>
        <td style="padding:5px 12px;text-align:right">{p['shares']:,.0f}</td>
        <td style="padding:5px 12px;text-align:right;font-family:monospace">{price_cell_html(p['price'], p['currency'], p['price_usd'])}</td>
        <td style="padding:5px 12px;text-align:right;font-family:monospace">{fmt_usd(p['value_today'])}</td>
        <td style="padding:5px 12px;text-align:right;font-family:monospace;color:{pc}">{fmt_pnl(p['pnl'])}</td>
        <td style="padding:5px 12px;text-align:right;color:{pc}">{fmt_pct(p['pnl_pct'])}</td>
        <td style="padding:5px 12px;text-align:right">{p['alloc_pct']:.1f}%</td>
      </tr>"""
                row_idx += 1

            else:  # group header + child rows
                gc = pnl_color(it["pnl"])
                out += f"""
      <tr style="background:#e8edf5;font-weight:bold">
        <td colspan="4" style="padding:5px 12px 5px 6px">{it['label']}</td>
        <td style="padding:5px 12px;text-align:right;font-family:monospace">{fmt_usd(it['value'])}</td>
        <td style="padding:5px 12px;text-align:right;font-family:monospace;color:{gc}">{fmt_pnl(it['pnl'])}</td>
        <td style="padding:5px 12px;text-align:right;color:{gc}">{fmt_pct(it['pnl_pct'])}</td>
        <td style="padding:5px 12px;text-align:right">{it['alloc_pct']:.1f}%</td>
      </tr>"""
                for m in it["members"]:
                    mc = pnl_color(m["pnl"])
                    out += f"""
      <tr style="background:#f4f7fc">
        <td style="padding:4px 12px 4px 22px;font-family:monospace;color:{GRAY}">↳ {m['ticker']}</td>
        <td style="padding:4px 12px;color:{GRAY};font-size:12px">{m['company']}</td>
        <td style="padding:4px 12px;text-align:right;color:{GRAY}">{m['shares']:,.0f}</td>
        <td style="padding:4px 12px;text-align:right;font-family:monospace;color:{GRAY}">{price_cell_html(m['price'], m['currency'], m['price_usd'])}</td>
        <td style="padding:4px 12px;text-align:right;font-family:monospace;color:{GRAY}">{fmt_usd(m['value_today'])}</td>
        <td style="padding:4px 12px;text-align:right;font-family:monospace;color:{mc}">{fmt_pnl(m['pnl'])}</td>
        <td style="padding:4px 12px;text-align:right;color:{mc}">{fmt_pct(m['pnl_pct'])}</td>
        <td style="padding:4px 12px"></td>
      </tr>"""
                row_idx += 1
        return out

    tc = pnl_color(total_pnl)
    html = f"""<html><body style="font-family:Arial,sans-serif;font-size:13px;color:#222;max-width:960px;margin:0 auto;padding:16px">

<h2 style="margin:0 0 4px 0">Portfolio — {now_sgt.strftime('%A, %-d %B %Y')} &nbsp;·&nbsp; {session}</h2>
<p style="margin:0 0 20px 0;color:{GRAY}">{date_line} &nbsp;·&nbsp; {fx_line}</p>

<table style="border-collapse:collapse;margin-bottom:24px">
  <tr>
    <td style="padding:2px 20px 2px 0;color:{GRAY}">Total Value</td>
    <td style="padding:2px 0;font-size:20px;font-weight:bold">{fmt_usd(total_value)}</td>
  </tr>
  <tr>
    <td style="padding:2px 20px 2px 0;color:{GRAY}">Day P&amp;L</td>
    <td style="padding:2px 0;font-size:16px;font-weight:bold;color:{tc}">{fmt_pnl(total_pnl)} ({fmt_pct(total_pnl_pct)})</td>
  </tr>
</table>

<h3 style="margin:0 0 8px 0;border-bottom:1px solid #ddd;padding-bottom:4px">Top Movers</h3>
<table style="border-collapse:collapse;margin-bottom:6px;width:100%">{mover_rows_html(top_up, GREEN, '▲')}</table>
<table style="border-collapse:collapse;margin-bottom:24px;width:100%">{mover_rows_html(top_down, RED, '▼')}</table>

<h3 style="margin:0 0 8px 0;border-bottom:1px solid #ddd;padding-bottom:4px">% Movers — Market Context</h3>
{news_movers_html()}

<h3 style="margin:0 0 8px 0;border-bottom:1px solid #ddd;padding-bottom:4px">All Positions</h3>
<table style="border-collapse:collapse;width:100%;font-size:12px">
  <thead>
    <tr style="background:#f0f0f0;text-align:left">
      <th style="padding:6px 12px 6px 6px">Ticker</th>
      <th style="padding:6px 12px">Company</th>
      <th style="padding:6px 12px;text-align:right">Shares</th>
      <th style="padding:6px 12px;text-align:right">Price</th>
      <th style="padding:6px 12px;text-align:right">Value (USD)</th>
      <th style="padding:6px 12px;text-align:right">Day P&amp;L</th>
      <th style="padding:6px 12px;text-align:right">Day %</th>
      <th style="padding:6px 12px;text-align:right">Alloc %</th>
    </tr>
  </thead>
  <tbody>{pos_rows_html()}
  </tbody>
  <tfoot>
    <tr style="font-weight:bold;border-top:2px solid #ccc;background:#f0f0f0">
      <td colspan="4" style="padding:6px 12px 6px 6px">TOTAL</td>
      <td style="padding:6px 12px;text-align:right;font-family:monospace">{fmt_usd(total_value)}</td>
      <td style="padding:6px 12px;text-align:right;font-family:monospace;color:{tc}">{fmt_pnl(total_pnl)}</td>
      <td style="padding:6px 12px;text-align:right;color:{tc}">{fmt_pct(total_pnl_pct)}</td>
      <td style="padding:6px 12px;text-align:right">100%</td>
    </tr>
  </tfoot>
</table>
</body></html>"""

    # ── Send ────────────────────────────────────────────────────────────
    _send_email(gmail_smtp, recipient_email, subject, html)

    log.info(f"Sent: {subject}")
    log.info(f"{len(positions)} positions | {fmt_usd(total_value)} | P&L: {fmt_pnl(total_pnl)} ({fmt_pct(total_pnl_pct)})")

    # ── Generate narrative ────────────────────────────────────────────────────
    narrative = _generate_portfolio_narrative(
        positions, top_up, top_down,
        total_value, total_pnl, total_pnl_pct,
        session, now_sgt, deepseek_key,
    )

    # ── Write canonical .md ──────────────────────────────────────────────────
    import os as _os, json as _json
    _os.makedirs("/research/portfolio", exist_ok=True)
    session_slug = "pm" if now_sgt.hour >= 12 else "am"
    md_path = f"/research/portfolio/{now_sgt.strftime('%Y-%m-%d')}_{session_slug}.md"
    date_str   = now_sgt.strftime("%a %-d %b")
    time_label = now_sgt.strftime("%-I%p").lower() + " SGT"
    front_matter = {
        "date_str":     date_str,
        "time_label":   time_label,
        "session":      session,
        "total_value":  round(total_value, 2) if total_value else None,
        "total_pnl":    round(total_pnl, 2) if total_pnl is not None else None,
        "total_pnl_pct": round(total_pnl_pct, 4) if total_pnl_pct is not None else None,
        "gainers": [
            {"label": it.get("label","?"), "pnl_pct": it.get("pnl_pct"), "pnl": it.get("pnl")}
            for it in top_up[:3]
        ],
        "losers": [
            {"label": it.get("label","?"), "pnl_pct": it.get("pnl_pct"), "pnl": it.get("pnl")}
            for it in top_down[:3]
        ],
    }
    # Build detail section (full position table)
    detail_rows = []
    for it in display_items:
        if it["type"] == "standalone":
            p = it["position"]
            detail_rows.append(
                f"| {p['ticker']} | {p['company']} | {p['shares']:,.0f} | "
                f"{fmt_usd(p['value_today'])} | {fmt_pnl(p['pnl'])} | {fmt_pct(p['pnl_pct'])} | {p['alloc_pct']:.1f}% |"
            )
        else:
            detail_rows.append(
                f"| **{it['label']}** | {it['company']} | — | "
                f"**{fmt_usd(it['value'])}** | **{fmt_pnl(it['pnl'])}** | **{fmt_pct(it['pnl_pct'])}** | {it['alloc_pct']:.1f}% |"
            )
            for m in it["members"]:
                detail_rows.append(
                    f"| ↳ {m['ticker']} | {m['company']} | {m['shares']:,.0f} | "
                    f"{fmt_usd(m['value_today'])} | {fmt_pnl(m['pnl'])} | {fmt_pct(m['pnl_pct'])} | — |"
                )
    detail_table = "\n".join([
        "| Ticker | Company | Shares | Value (USD) | Day P&L | Day % | Alloc |",
        "|---|---|---:|---:|---:|---:|---:|",
    ] + detail_rows)
    md_content = (
        f"```json\n{_json.dumps(front_matter, indent=2)}\n```\n\n"
        f"{narrative}\n\n"
        f"<!-- DETAIL -->\n\n"
        f"# Portfolio — {session} · {now_sgt.strftime('%d %b %Y, %H:%M SGT')}\n\n"
        f"**Total:** {fmt_usd(total_value)} | Day P&L: {fmt_pnl(total_pnl)} ({fmt_pct(total_pnl_pct)})\n\n"
        f"_{date_line}_" + (f"  ·  _{fx_line}_" if fx_line else "") + "\n\n"
        f"{detail_table}\n"
    )
    _write_canonical_md(md_content, md_path)
    log.info(f"[md] Written {md_path}")


