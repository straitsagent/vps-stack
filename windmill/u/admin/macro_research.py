# Requirements:
# requests>=2.31
# yfinance>=0.2.40
# pytz>=2024.1
# feedparser>=6.0

"""
Macro Research — comprehensive daily macro brief.
Fetches ~25 Yahoo Finance indicators + 13 FRED series + Fed RSS feeds + Google News.
Analyses in 6 sections via Deepseek. Writes canonical .md, sends HTML email,
dispatches macro_daily_push_telegram formatter for Telegram push.
"""

import calendar as _calendar
import json
import logging
import math
import os
import re
import smtplib
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import feedparser
import pytz
import requests
import yfinance as yf

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ── Yahoo Finance symbols ─────────────────────────────────────────────────────

YAHOO_SYMBOLS = {
    # Volatility
    "VIX":    "^VIX",
    # US equities
    "SP500":  "^GSPC",
    "NDX":    "^NDX",
    "RUT":    "^RUT",
    # Global equities
    "Nikkei": "^N225",
    "DAX":    "^GDAXI",
    "FTSE":   "^FTSE",
    "HSI":    "^HSI",
    "CSI300": "000300.SS",
    # US rates (market)
    "UST5Y":  "^FVX",
    "UST10Y": "^TNX",
    "UST30Y": "^TYX",
    # Credit proxies
    "HYG":    "HYG",
    "LQD":    "LQD",
    # Dollar & FX
    "DXY":    "DX-Y.NYB",
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "USDJPY": "JPY=X",
    "USDCNY": "CNY=X",
    "USDSGD": "SGD=X",
    "USDHKD": "HKD=X",
    # Commodities
    "Gold":   "GC=F",
    "Brent":  "BZ=F",
    "Copper": "HG=F",
    "NatGas": "NG=F",
}

# ── FRED series ───────────────────────────────────────────────────────────────

FRED_SERIES = {
    "DFF":          "Effective Fed Funds Rate (%)",
    "SOFR":         "SOFR (%)",
    "DGS2":         "UST 2Y Yield (%)",
    "T10Y2Y":       "10Y-2Y Spread (pp)",
    "T10Y3M":       "10Y-3M Spread (pp)",
    "T5YIE":        "5Y Breakeven Inflation (%)",
    "T10YIE":       "10Y Breakeven Inflation (%)",
    "BAMLH0A0HYM2": "HY OAS Spread (%)",
    "BAMLC0A0CM":   "IG OAS Spread (%)",
    "NFCI":         "Chicago Fed Fin. Conditions",
    "CPIAUCSL":     "CPI YoY %",
    "PCEPI":        "PCE YoY %",
    "UNRATE":       "Unemployment Rate %",
}

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

# Series that should be fetched as percent-change-from-year-ago rather than raw index level
FRED_UNITS_PC1 = {"CPIAUCSL", "PCEPI"}

# ── Fed RSS feeds ─────────────────────────────────────────────────────────────

FED_FEEDS = {
    "speech": "https://www.federalreserve.gov/feeds/speeches.xml",
    "press":  "https://www.federalreserve.gov/feeds/press_all.xml",
}

# ── Google News queries ───────────────────────────────────────────────────────

NEWS_QUERIES = [
    "global macro economy",
    "federal reserve interest rates",
    "china economy markets",
]
GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"

WM_BASE      = "http://windmill_server:8000"
WM_WORKSPACE = "admins"

# ── Section prompts ───────────────────────────────────────────────────────────

_SECTION_TITLES = {
    "equity":      "A. Global Equity Sentiment",
    "rates":       "B. Interest Rates & Yield Curve",
    "fed":         "C. Fed Policy & Inflation",
    "fx_credit":   "D. Dollar, FX & Credit",
    "commodities": "E. Commodities",
    "hk_china":    "F. HK / China",
}

SECTION_PROMPTS = {
    "equity": (
        "You are a macro analyst. Write 200+ words of continuous analytical prose — "
        "no bullets, no headers — interpreting global equity sentiment. "
        "Portfolio context: ~40% HK equities, ~60% US equities. "
        "Cover: what VIX signals about near-term risk appetite, relative performance "
        "across US (SP500/NDX/RUT) and global markets (Nikkei/DAX/FTSE/HSI/CSI300). "
        "Be specific about cross-market divergences and what they imply for the portfolio mix.\n\nData:\n{data}"
    ),
    "rates": (
        "You are a macro analyst. Write 200+ words of continuous analytical prose — "
        "no bullets, no headers — on the US interest rate and yield curve environment. "
        "Cover: the curve shape (UST 2Y/5Y/10Y/30Y), T10Y2Y and T10Y3M spreads as "
        "recession signals, HYG and LQD as credit proxies, Fed Funds vs. SOFR, "
        "and what the rate environment means for equity valuation and portfolio duration risk.\n\nData:\n{data}"
    ),
    "fed": (
        "You are a macro analyst. Write 250+ words of continuous analytical prose — "
        "no bullets, no headers — on Fed policy, inflation, and financial conditions. "
        "Cover: where Fed Funds and SOFR sit vs. inflation breakevens, "
        "what CPI/PCE and unemployment signal about the inflation/jobs balance, "
        "the Chicago Fed Financial Conditions Index, and what any recent Fed speeches "
        "or press releases signal about the policy path. Be concrete about rate-cut or "
        "hike probability implications.\n\nData:\n{data}\n\nFed commentary:\n{fed_news}"
    ),
    "fx_credit": (
        "You are a macro analyst. Write 200+ words of continuous analytical prose — "
        "no bullets, no headers — on the US dollar, FX, and credit spread environment. "
        "Cover: DXY direction and risk-asset implications, key FX pairs (EUR/USD, GBP/USD, "
        "USD/JPY), USD/SGD and USD/HKD for the Singapore/HK portfolio context, "
        "HY OAS and IG OAS spreads as credit health gauges.\n\nData:\n{data}"
    ),
    "commodities": (
        "You are a macro analyst. Write 150+ words of continuous analytical prose — "
        "no bullets, no headers — on commodity markets. "
        "Cover: Gold as a risk-off/inflation hedge signal, Brent as a growth/geopolitical gauge, "
        "Copper as a leading indicator for global industrial demand, "
        "Natural Gas for energy cost context.\n\nData:\n{data}"
    ),
    "hk_china": (
        "You are a macro analyst. Write 200+ words of continuous analytical prose — "
        "no bullets, no headers — on HK and China macro dynamics. "
        "Portfolio context: ~40% HK-listed equities. "
        "Cover: HSI and CSI300 momentum, USD/HKD peg stability, USD/CNY direction "
        "as a proxy for China capital flow pressures, and macro news signals relevant "
        "to the China/HK market outlook.\n\nData:\n{data}\n\nChina/HK news:\n{china_news}"
    ),
}

# ── Yahoo data fetch ──────────────────────────────────────────────────────────

def _fetch_yahoo_macro() -> dict:
    tickers = list(YAHOO_SYMBOLS.values())
    data = yf.download(tickers, period="5d", progress=False, auto_adjust=True)
    filled = data["Close"].ffill()
    close = filled.iloc[-1]
    prev  = filled.iloc[-2] if len(filled) > 1 else filled.iloc[-1]
    results = {}
    for name, sym in YAHOO_SYMBOLS.items():
        val  = float(close[sym]) if sym in close else None
        if val is not None and math.isnan(val):
            val = None
        pval = float(prev[sym])  if sym in prev  else None
        if pval is not None and math.isnan(pval):
            pval = None
        chg = ((val - pval) / pval * 100) if (val is not None and pval and pval != 0) else None
        results[name] = {"value": val, "change_pct": chg}
    return results

# ── FRED fetch ────────────────────────────────────────────────────────────────

def _fetch_fred_data(api_key: str) -> dict:
    results = {}
    for series_id, label in FRED_SERIES.items():
        try:
            params = {
                "series_id":  series_id,
                "api_key":    api_key,
                "file_type":  "json",
                "sort_order": "desc",
                "limit":      10,
            }
            if series_id in FRED_UNITS_PC1:
                params["units"] = "pc1"
            resp = requests.get(FRED_BASE, params=params, timeout=15)
            resp.raise_for_status()
            obs = resp.json().get("observations", [])
            val, obs_date = None, None
            for o in obs:
                raw = o.get("value", ".")
                if raw != ".":
                    try:
                        val = float(raw)
                        obs_date = o.get("date")
                        break
                    except (ValueError, TypeError):
                        continue
            results[series_id] = {"value": val, "date": obs_date, "label": label}
        except Exception as e:
            log.warning(f"[FRED] {series_id} fetch failed: {e}")
            results[series_id] = {"value": None, "date": None, "label": label}
    return results

# ── Fed RSS feeds ─────────────────────────────────────────────────────────────

def _fetch_fed_news(max_age_days: int = 7) -> list:
    items = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    for feed_type, url in FED_FEEDS.items():
        try:
            feed = feedparser.parse(url)
            for entry in (feed.entries or [])[:10]:
                pub = getattr(entry, "published_parsed", None)
                if pub:
                    pub_dt = datetime.fromtimestamp(_calendar.timegm(pub), tz=timezone.utc)
                    if pub_dt < cutoff:
                        continue
                    pub_str = pub_dt.strftime("%-d %b %Y")
                else:
                    pub_str = ""
                title   = getattr(entry, "title", "")
                link    = entry.get("link", "") if hasattr(entry, "get") else ""
                speaker = ""
                if feed_type == "speech":
                    m = re.search(r"^([A-Z][a-z]+)", title)
                    if m:
                        speaker = m.group(1)
                items.append({
                    "title":   title,
                    "date":    pub_str,
                    "type":    feed_type,
                    "speaker": speaker,
                    "url":     link,
                })
        except Exception as e:
            log.warning(f"[FedRSS] {feed_type} fetch failed: {e}")
    return items[:10]

# ── Google News headlines ─────────────────────────────────────────────────────

def _fetch_macro_news() -> list:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
    headlines = []
    seen: set = set()
    for query in NEWS_QUERIES:
        try:
            url  = GOOGLE_NEWS_RSS.format(query=query.replace(" ", "+"))
            feed = feedparser.parse(url)
            count = 0
            for entry in (feed.entries or []):
                if count >= 4:
                    break
                pub = getattr(entry, "published_parsed", None)
                if pub:
                    pub_dt = datetime.fromtimestamp(_calendar.timegm(pub), tz=timezone.utc)
                    if pub_dt < cutoff:
                        continue
                    pub_str = pub_dt.strftime("%-d %b")
                else:
                    pub_str = ""
                title = getattr(entry, "title", "")
                if title in seen:
                    continue
                seen.add(title)
                src = getattr(entry, "source", {})
                src_name = src.get("title", "") if isinstance(src, dict) else str(src)
                headlines.append({
                    "title":  title,
                    "source": src_name,
                    "date":   pub_str,
                    "query":  query,
                })
                count += 1
        except Exception as e:
            log.warning(f"[News] query '{query}' failed: {e}")
    return headlines

# ── Deepseek section synthesis ────────────────────────────────────────────────

def _synthesise_section(section_key: str, data_str: str, deepseek_key: str,
                        extra_str: str = "") -> tuple:
    template = SECTION_PROMPTS[section_key]
    if "{fed_news}" in template:
        prompt = template.format(data=data_str, fed_news=extra_str or "(none)")
    elif "{china_news}" in template:
        prompt = template.format(data=data_str, china_news=extra_str or "(none)")
    else:
        prompt = template.format(data=data_str)
    try:
        r = requests.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {deepseek_key}"},
            json={
                "model":       "deepseek-chat",
                "messages":    [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens":  600,
            },
            timeout=60,
        )
        r.raise_for_status()
        usage = r.json().get("usage", {})
        text  = r.json()["choices"][0]["message"]["content"].strip()
        return text, usage
    except Exception as e:
        log.warning(f"[Deepseek] Section '{section_key}' failed: {e}")
        return "", {}

# ── Formatting helpers ────────────────────────────────────────────────────────

_YAHOO_FMT = {
    "VIX":    lambda v: f"{v:.1f}",
    "SP500":  lambda v: f"{v:,.0f}",
    "NDX":    lambda v: f"{v:,.0f}",
    "RUT":    lambda v: f"{v:,.0f}",
    "Nikkei": lambda v: f"{v:,.0f}",
    "DAX":    lambda v: f"{v:,.0f}",
    "FTSE":   lambda v: f"{v:,.0f}",
    "HSI":    lambda v: f"{v:,.0f}",
    "CSI300": lambda v: f"{v:,.2f}",
    "UST5Y":  lambda v: f"{v:.2f}%",
    "UST10Y": lambda v: f"{v:.2f}%",
    "UST30Y": lambda v: f"{v:.2f}%",
    "HYG":    lambda v: f"{v:.2f}",
    "LQD":    lambda v: f"{v:.2f}",
    "DXY":    lambda v: f"{v:.2f}",
    "EURUSD": lambda v: f"{v:.4f}",
    "GBPUSD": lambda v: f"{v:.4f}",
    "USDJPY": lambda v: f"{v:.2f}",
    "USDCNY": lambda v: f"{v:.4f}",
    "USDSGD": lambda v: f"{v:.4f}",
    "USDHKD": lambda v: f"{v:.4f}",
    "Gold":   lambda v: f"${v:,.0f}",
    "Brent":  lambda v: f"${v:.1f}",
    "Copper": lambda v: f"${v:.3f}",
    "NatGas": lambda v: f"${v:.3f}",
}

_YAHOO_DISPLAY = {
    "EURUSD": "EUR/USD", "GBPUSD": "GBP/USD", "USDJPY": "USD/JPY",
    "USDCNY": "USD/CNY", "USDSGD": "USD/SGD", "USDHKD": "USD/HKD",
    "NatGas": "Nat Gas",
}


def _fmt_yahoo_cell(name: str, val, chg) -> str:
    if val is None:
        return "N/A"
    fmt = _YAHOO_FMT.get(name, lambda v: f"{v:.4g}")
    arrow = " ↑" if (chg or 0) > 0.1 else (" ↓" if (chg or 0) < -0.1 else "")
    chg_str = f" ({chg:+.1f}%)" if chg is not None else ""
    return f"{fmt(val)}{chg_str}{arrow}"


def _fmt_fred_val(series_id: str, val) -> str:
    if val is None:
        return "N/A"
    if series_id == "NFCI":
        return f"{val:.3f}"
    return f"{val:.2f}%"

# ── Section data string builders ──────────────────────────────────────────────

def _yahoo_data_str(yahoo: dict, names: list) -> str:
    lines = []
    for name in names:
        if name not in yahoo:
            continue
        d = yahoo[name]
        v, c = d.get("value"), d.get("change_pct")
        disp = _YAHOO_DISPLAY.get(name, name)
        if v is None:
            lines.append(f"{disp}: N/A")
            continue
        fmt = _YAHOO_FMT.get(name, lambda x: f"{x:.4g}")
        chg_str = f" ({c:+.1f}%)" if c is not None else ""
        lines.append(f"{disp}: {fmt(v)}{chg_str}")
    return "\n".join(lines)


def _fred_data_str(fred: dict, series_ids: list) -> str:
    lines = []
    for sid in series_ids:
        if sid not in fred:
            continue
        d = fred[sid]
        label = d.get("label", sid)
        val   = d.get("value")
        date  = d.get("date") or ""
        val_str = _fmt_fred_val(sid, val)
        suffix  = f" (as of {date})" if date else ""
        lines.append(f"{label}: {val_str}{suffix}")
    return "\n".join(lines)


def _fed_news_str(fed_items: list) -> str:
    lines = []
    for item in fed_items[:6]:
        tag     = item.get("type", "").capitalize()
        speaker = item.get("speaker", "")
        date    = item.get("date", "")
        title   = item.get("title", "")
        prefix  = f"[{tag}]{(' — '+speaker) if speaker else ''} ({date}): " if date else f"[{tag}]: "
        lines.append(prefix + title)
    return "\n".join(lines) if lines else "(no recent Fed commentary)"


def _china_news_str(headlines: list) -> str:
    china = [h for h in headlines if "china" in h.get("query", "").lower()]
    return "\n".join(h["title"] for h in china[:5]) if china else "(no recent China/HK headlines)"

# ── HTML email builder ────────────────────────────────────────────────────────

_YAHOO_GROUPS = [
    ("Volatility & US Equities", ["VIX", "SP500", "NDX", "RUT"]),
    ("Global Equities",          ["Nikkei", "DAX", "FTSE", "HSI", "CSI300"]),
    ("US Rates (Market)",        ["UST5Y", "UST10Y", "UST30Y", "HYG", "LQD"]),
    ("Dollar & FX",              ["DXY", "EURUSD", "GBPUSD", "USDJPY", "USDCNY", "USDSGD", "USDHKD"]),
    ("Commodities",              ["Gold", "Brent", "Copper", "NatGas"]),
]

_FRED_GROUPS = [
    ("Fed Policy",   ["DFF", "SOFR", "DGS2"]),
    ("Yield Curve",  ["T10Y2Y", "T10Y3M"]),
    ("Inflation",    ["T5YIE", "T10YIE", "CPIAUCSL", "PCEPI"]),
    ("Credit",       ["BAMLH0A0HYM2", "BAMLC0A0CM"]),
    ("Conditions",   ["NFCI", "UNRATE"]),
]

_HDR = 'style="background:#eef2f7;font-weight:bold;padding:5px 10px;text-align:left"'
_TD  = 'style="padding:4px 10px;border-bottom:1px solid #f0f0f0"'
_TDG = 'style="padding:4px 10px;border-bottom:1px solid #f0f0f0;color:#1a7a1a"'
_TDR = 'style="padding:4px 10px;border-bottom:1px solid #f0f0f0;color:#b30000"'
_TDS = 'style="padding:4px 10px;border-bottom:1px solid #f0f0f0;color:#999;font-size:11px"'


def _build_email_html(time_label: str, yahoo: dict, fred: dict, sections: dict,
                      fed_items: list, headlines: list, total_cost: float) -> str:
    # Yahoo indicator table
    yahoo_rows = ""
    for group_name, names in _YAHOO_GROUPS:
        yahoo_rows += f'<tr><th colspan="2" {_HDR}>{group_name}</th></tr>\n'
        for name in names:
            if name not in yahoo:
                continue
            d    = yahoo[name]
            v, c = d.get("value"), d.get("change_pct")
            cell = _fmt_yahoo_cell(name, v, c)
            disp = _YAHOO_DISPLAY.get(name, name)
            td   = _TDG if (c or 0) > 0.1 else (_TDR if (c or 0) < -0.1 else _TD)
            yahoo_rows += f'<tr><td {_TD}>{disp}</td><td {td}>{cell}</td></tr>\n'

    # FRED table
    fred_rows = ""
    for group_name, sids in _FRED_GROUPS:
        fred_rows += f'<tr><th colspan="3" {_HDR}>{group_name}</th></tr>\n'
        for sid in sids:
            if sid not in fred:
                continue
            d       = fred[sid]
            label   = d.get("label", sid)
            val_str = _fmt_fred_val(sid, d.get("value"))
            date    = d.get("date") or ""
            fred_rows += f'<tr><td {_TD}>{label}</td><td {_TD}>{val_str}</td><td {_TDS}>{date}</td></tr>\n'

    # Fed commentary
    fed_html = ""
    if fed_items:
        fed_html = '<h2 style="color:#1a1a6b;border-bottom:1px solid #ddd;margin-top:28px">Fed Reserve Commentary</h2>\n<ul style="line-height:1.8">\n'
        for item in fed_items[:8]:
            tag     = "Speech" if item.get("type") == "speech" else "Press Release"
            speaker = item.get("speaker", "")
            date    = f" ({item['date']})" if item.get("date") else ""
            url     = item.get("url", "")
            title   = item.get("title", "")
            link    = f'<a href="{url}">{title}</a>' if url else title
            byline  = f" — <strong>{speaker}</strong>" if speaker else ""
            fed_html += f'  <li><em>[{tag}]{byline}</em>{date}: {link}</li>\n'
        fed_html += "</ul>\n"

    # Analysis sections
    analysis_html = ""
    for key in ("equity", "rates", "fed", "fx_credit", "commodities", "hk_china"):
        text = sections.get(key, "").strip()
        if not text:
            continue
        title = _SECTION_TITLES[key]
        analysis_html += (
            f'<h2 style="color:#1a1a6b;border-bottom:1px solid #ddd;margin-top:28px">'
            f'{title}</h2>\n'
        )
        for para in text.split("\n\n"):
            para = para.strip()
            if para:
                analysis_html += f"<p style='line-height:1.7'>{para}</p>\n"

    # News headlines
    news_html = ""
    if headlines:
        news_html = '<h2 style="color:#1a1a6b;border-bottom:1px solid #ddd;margin-top:28px">Macro Headlines (48h)</h2>\n<ul style="line-height:1.8">\n'
        for h in headlines:
            src  = f" — <em>{h['source']}</em>" if h.get("source") else ""
            date = f" ({h['date']})"             if h.get("date")   else ""
            news_html += f'  <li>{h["title"]}{src}{date}</li>\n'
        news_html += "</ul>\n"

    cost_str = f"${total_cost:.4f}" if total_cost else "—"
    tbl = 'style="border-collapse:collapse;width:100%;margin-bottom:8px"'

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;max-width:840px;margin:0 auto;color:#222;line-height:1.6">

<h1 style="color:#1a1a6b;border-bottom:2px solid #1a1a6b">Macro Research — {time_label}</h1>

<h2 style="color:#1a1a6b;border-bottom:1px solid #ddd;margin-top:28px">Market Indicators</h2>
<table {tbl}>{yahoo_rows}</table>

<h2 style="color:#1a1a6b;border-bottom:1px solid #ddd;margin-top:28px">FRED Economic Data</h2>
<table {tbl}>{fred_rows}</table>

{fed_html}
{analysis_html}
{news_html}

<p style="color:#999;font-size:11px;border-top:1px solid #eee;padding-top:12px;margin-top:24px">
Deepseek cost est.: {cost_str} &nbsp;|&nbsp; Generated {time_label}
</p>
</body>
</html>"""

# ── Email sender ──────────────────────────────────────────────────────────────

def _send_email(smtp_res: dict, recipient: str, subject: str, html_body: str):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = smtp_res.get("username", "")
    msg["To"]      = recipient
    msg.attach(MIMEText(html_body, "html"))
    host     = smtp_res.get("host", "smtp.gmail.com")
    port     = int(smtp_res.get("port", 587))
    username = smtp_res.get("username", "")
    password = smtp_res.get("password", "")
    with smtplib.SMTP(host, port) as server:
        server.ehlo()
        server.starttls()
        server.login(username, password)
        server.sendmail(username, [recipient], msg.as_string())
    log.info(f"[Email] Sent: {subject}")

# ── Telegram formatter dispatch ───────────────────────────────────────────────

def _dispatch_formatter(md_path: str, telegram_bot_token: str,
                        telegram_owner_id: str, portfolio_db: dict,
                        wm_token: str = "") -> str:
    token = wm_token or os.environ.get("WM_TOKEN", "")
    if not token:
        log.warning("[Dispatch] No WM_TOKEN — cannot dispatch macro_daily_push_telegram")
        return ""
    url  = f"{WM_BASE}/api/w/{WM_WORKSPACE}/jobs/run/p/u/admin/macro_daily_push_telegram"
    args = {
        "md_path":            md_path,
        "telegram_bot_token": telegram_bot_token,
        "telegram_owner_id":  telegram_owner_id,
        "portfolio_db":       portfolio_db,
    }
    try:
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type":  "application/json"},
            json=args, timeout=10,
        )
        job_id = resp.text.strip().strip('"')
        log.info(f"[Dispatch] macro_daily_push_telegram job_id={job_id}")
        return job_id
    except Exception as e:
        log.warning(f"[Dispatch] Failed: {e}")
        return ""

# ── Main ──────────────────────────────────────────────────────────────────────

def main(
    fred_api_key: str,
    deepseek_key: str,
    telegram_bot_token: str,
    telegram_owner_id: str,
    smtp_resource: dict,
    recipient_email: str,
    portfolio_db: dict = {},
    wm_token: str = "",
):
    sgt       = pytz.timezone("Asia/Singapore")
    now_sgt   = datetime.now(sgt)
    time_label = now_sgt.strftime("%a %-d %b %Y, %-I:%M %p SGT")

    log.info("[MacroResearch] Fetching Yahoo Finance data...")
    yahoo = _fetch_yahoo_macro()

    log.info("[MacroResearch] Fetching FRED data...")
    fred = _fetch_fred_data(fred_api_key)

    log.info("[MacroResearch] Fetching Fed Reserve RSS feeds...")
    fed_items = _fetch_fed_news()
    log.info(f"[MacroResearch]   {len(fed_items)} Fed items")

    log.info("[MacroResearch] Fetching macro news headlines...")
    headlines = _fetch_macro_news()
    log.info(f"[MacroResearch]   {len(headlines)} headlines")

    # ── Build data strings per section ────────────────────────────────────────
    equity_data = _yahoo_data_str(yahoo, ["VIX","SP500","NDX","RUT","Nikkei","DAX","FTSE","HSI","CSI300"])
    rates_data  = "\n".join([
        _yahoo_data_str(yahoo, ["UST5Y","UST10Y","UST30Y","HYG","LQD"]),
        _fred_data_str(fred, ["DFF","SOFR","DGS2","T10Y2Y","T10Y3M"]),
    ])
    fed_data    = _fred_data_str(fred, ["DFF","T5YIE","T10YIE","CPIAUCSL","PCEPI","UNRATE","NFCI"])
    fx_data     = "\n".join([
        _yahoo_data_str(yahoo, ["DXY","EURUSD","GBPUSD","USDJPY","USDCNY","USDSGD","USDHKD"]),
        _fred_data_str(fred, ["BAMLH0A0HYM2","BAMLC0A0CM"]),
    ])
    comm_data   = _yahoo_data_str(yahoo, ["Gold","Brent","Copper","NatGas"])
    hk_data     = _yahoo_data_str(yahoo, ["HSI","CSI300","USDHKD","USDCNY"])

    section_inputs = {
        "equity":      (equity_data, ""),
        "rates":       (rates_data,  ""),
        "fed":         (fed_data,    _fed_news_str(fed_items)),
        "fx_credit":   (fx_data,     ""),
        "commodities": (comm_data,   ""),
        "hk_china":    (hk_data,     _china_news_str(headlines)),
    }

    # ── 6-section Deepseek analysis ───────────────────────────────────────────
    log.info("[MacroResearch] Running 6-section Deepseek analysis...")
    total_prompt = total_completion = 0
    sections = {}
    for key, (data_str, extra_str) in section_inputs.items():
        text, usage = _synthesise_section(key, data_str, deepseek_key, extra_str)
        sections[key] = text
        total_prompt     += usage.get("prompt_tokens", 0)
        total_completion += usage.get("completion_tokens", 0)
        log.info(f"[MacroResearch]   {key}: {len(text.split())} words")

    total_cost = (total_prompt * 0.27 + total_completion * 1.10) / 1_000_000
    log.info(f"[MacroResearch] Deepseek: {total_prompt}p + {total_completion}c · est. ${total_cost:.4f}")

    # ── Write canonical .md ───────────────────────────────────────────────────
    front_matter = {
        "timestamp": now_sgt.isoformat(),
        "indicators": {
            "yahoo": yahoo,
            "fred":  fred,
        },
        "fed_items":      fed_items,
        "news_headlines": headlines,
    }
    os.makedirs("/research/macro", exist_ok=True)
    md_path   = f"/research/macro/{now_sgt.strftime('%Y-%m-%d_%H%M')}.md"
    narrative = "\n\n".join(
        f"### {_SECTION_TITLES[k]}\n\n{v}"
        for k, v in sections.items() if v
    )
    md_content = (
        f"```json\n{json.dumps(front_matter, indent=2)}\n```\n\n"
        f"{narrative}\n\n"
        "<!-- DETAIL -->\n"
    )
    with open(md_path, "w") as f:
        f.write(md_content)
    log.info(f"[MacroResearch] Written {md_path}")

    # ── HTML email ────────────────────────────────────────────────────────────
    log.info("[MacroResearch] Sending HTML email...")
    html_body = _build_email_html(
        time_label, yahoo, fred, sections, fed_items, headlines, total_cost
    )
    _send_email(smtp_resource, recipient_email,
                f"Macro Research — {time_label}", html_body)

    # ── Dispatch Telegram formatter ───────────────────────────────────────────
    _dispatch_formatter(md_path, telegram_bot_token, telegram_owner_id,
                        portfolio_db, wm_token)

    total_words = sum(len(v.split()) for v in sections.values())
    return {
        "status":       "sent",
        "md_path":      md_path,
        "time":         time_label,
        "total_words":  total_words,
        "est_cost_usd": round(total_cost, 4),
    }
