# Requirements:
# requests>=2.31
# pytz>=2024.1
# feedparser>=6.0

"""
Macro Research — comprehensive daily macro brief.
Fetches 11 Finnhub ETF proxies + 30 FRED series + Fed RSS feeds + Google News.
Analyses in 6 sections via Deepseek. Writes canonical .md, sends HTML email.
Telegram dispatch retired 2026-06-29 (formatter retained on disk).
"""

import calendar as _calendar
import json
import logging
import os
import re
import smtplib
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import feedparser
import pytz
import requests

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ── Finnhub symbols (ETF proxies — direct index symbols not available on free tier) ──

FINNHUB_SYMBOLS = {
    # US equities — ETF proxies (SPY/QQQ/IWM track the indices)
    "SP500":  "SPY",
    "NDX":    "QQQ",
    "RUT":    "IWM",
    # Global equities — ETF proxies
    "Nikkei": "EWJ",
    "DAX":    "EWG",
    "FTSE":   "EWU",
    "HSI":    "EWH",
    "CSI300": "FXI",
    # Credit ETFs
    "HYG":    "HYG",
    "LQD":    "LQD",
    # Commodities ETF proxies
    "Copper": "CPER",
    "Gold":   "GLD",
}

# ── FRED series ───────────────────────────────────────────────────────────────

FRED_SERIES = {
    # Policy & rates
    "DFF":          "Effective Fed Funds Rate (%)",
    "SOFR":         "SOFR (%)",
    "DGS2":         "UST 2Y Yield (%)",
    "DGS5":         "UST 5Y Yield (%)",
    "DGS10":        "UST 10Y Yield (%)",
    "DGS30":        "UST 30Y Yield (%)",
    "T10Y2Y":       "10Y-2Y Spread (pp)",
    "T10Y3M":       "10Y-3M Spread (pp)",
    # Inflation & conditions
    "T5YIE":        "5Y Breakeven Inflation (%)",
    "T10YIE":       "10Y Breakeven Inflation (%)",
    "CPIAUCSL":     "CPI YoY %",
    "PCEPI":        "PCE YoY %",
    "UNRATE":       "Unemployment Rate %",
    "NFCI":         "Chicago Fed Fin. Conditions",
    # Credit spreads
    "BAMLH0A0HYM2": "HY OAS Spread (bp)",
    "BAMLC0A0CM":   "IG OAS Spread (bp)",
    # Volatility (replaces Yahoo ^VIX)
    "VIXCLS":            "VIX",
    # Dollar & FX (replaces Yahoo FX tickers)
    "DTWEXBGS":          "USD Index (Broad)",
    "DEXUSEU":           "EUR/USD",
    "DEXUSUK":           "GBP/USD",
    "DEXJPUS":           "USD/JPY",
    "DEXCHUS":           "USD/CNY",
    "DEXSIUS":           "USD/SGD",
    "DEXHKUS":           "USD/HKD",
    # Commodities (replaces Yahoo BZ=F, NG=F)
    "DCOILBRENTEU":      "Brent Crude (USD/bbl)",
    "DHHNGSP":           "Nat Gas (USD/MMBtu)",
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
        "Cover: USD Index (Broad) direction and risk-asset implications, key FX pairs (EUR/USD, GBP/USD, "
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

ARTIFACT_MARKERS: dict[str, list[str]] = {
    "Macro Research": ["VIX", "10Y"],
}

# ── Finnhub market data fetch ─────────────────────────────────────────────────

def _fetch_finnhub_data(api_key: str) -> dict:
    results = {}
    for name, sym in FINNHUB_SYMBOLS.items():
        try:
            resp = requests.get(
                "https://finnhub.io/api/v1/quote",
                params={"symbol": sym, "token": api_key},
                timeout=10,
            )
            resp.raise_for_status()
            d   = resp.json()
            val = d.get("c") or None
            pc  = d.get("pc") or None
            if val == 0:
                val = None
            if pc == 0:
                pc = None
            chg = ((val - pc) / pc * 100) if (val is not None and pc) else None
            results[name] = {"value": val, "change_pct": chg}
        except Exception as e:
            log.warning(f"[Finnhub] {name} ({sym}): {e}")
            results[name] = {"value": None, "change_pct": None}
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

_MARKET_FMT = {
    "SP500":  lambda v: f"{v:.2f}",
    "NDX":    lambda v: f"{v:.2f}",
    "RUT":    lambda v: f"{v:.2f}",
    "Nikkei": lambda v: f"{v:.2f}",
    "DAX":    lambda v: f"{v:.2f}",
    "FTSE":   lambda v: f"{v:.2f}",
    "HSI":    lambda v: f"{v:.2f}",
    "CSI300": lambda v: f"{v:.2f}",
    "HYG":    lambda v: f"{v:.2f}",
    "LQD":    lambda v: f"{v:.2f}",
    "Copper": lambda v: f"{v:.2f}",
    "Gold":   lambda v: f"${v:.2f} (GLD)",
}

_MARKET_DISPLAY = {
    "SP500":  "SP500 (SPY)",
    "NDX":    "NDX (QQQ)",
    "RUT":    "RUT (IWM)",
    "Nikkei": "Nikkei (EWJ)",
    "DAX":    "DAX (EWG)",
    "FTSE":   "FTSE (EWU)",
    "HSI":    "HSI (EWH)",
    "CSI300": "CSI300 (FXI)",
    "Copper": "Copper (CPER)",
    "Gold":   "Gold (GLD ETF)",
}


def _fmt_market_cell(name: str, val, chg) -> str:
    if val is None:
        return "N/A"
    fmt = _MARKET_FMT.get(name, lambda v: f"{v:.4g}")
    arrow = " ↑" if (chg or 0) > 0.1 else (" ↓" if (chg or 0) < -0.1 else "")
    chg_str = f" ({chg:+.1f}%)" if chg is not None else ""
    return f"{fmt(val)}{chg_str}{arrow}"


_FRED_FMT: dict = {
    "NFCI":             lambda v: f"{v:.3f}",
    "VIXCLS":           lambda v: f"{v:.1f}",
    "DTWEXBGS":         lambda v: f"{v:.2f}",
    "DEXUSEU":          lambda v: f"{v:.4f}",
    "DEXUSUK":          lambda v: f"{v:.4f}",
    "DEXJPUS":          lambda v: f"{v:.2f}",
    "DEXCHUS":          lambda v: f"{v:.4f}",
    "DEXSIUS":          lambda v: f"{v:.4f}",
    "DEXHKUS":          lambda v: f"{v:.4f}",
    "DCOILBRENTEU":     lambda v: f"${v:.1f}",
    "DHHNGSP":          lambda v: f"${v:.3f}",
}


def _fmt_fred_val(series_id: str, val) -> str:
    if val is None:
        return "N/A"
    fmt = _FRED_FMT.get(series_id)
    if fmt:
        return fmt(val)
    return f"{val:.2f}%"

# ── Section data string builders ──────────────────────────────────────────────

def _market_data_str(market: dict, names: list) -> str:
    lines = []
    for name in names:
        if name not in market:
            continue
        d = market[name]
        v, c = d.get("value"), d.get("change_pct")
        disp = _MARKET_DISPLAY.get(name, name)
        if v is None:
            lines.append(f"{disp}: N/A")
            continue
        fmt = _MARKET_FMT.get(name, lambda x: f"{x:.4g}")
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

_MARKET_GROUPS = [
    ("US Equities (ETF proxy)",     ["SP500", "NDX", "RUT"]),
    ("Global Equities (ETF proxy)", ["Nikkei", "DAX", "FTSE", "HSI", "CSI300"]),
    ("Credit ETFs",                 ["HYG", "LQD"]),
    ("Commodities (ETF proxy)",     ["Copper", "Gold"]),
]

_FRED_GROUPS = [
    ("Volatility",   ["VIXCLS"]),
    ("US Rates",     ["DGS5", "DGS10", "DGS30", "DFF", "SOFR", "DGS2"]),
    ("Yield Curve",  ["T10Y2Y", "T10Y3M"]),
    ("Inflation",    ["T5YIE", "T10YIE", "CPIAUCSL", "PCEPI"]),
    ("Credit",       ["BAMLH0A0HYM2", "BAMLC0A0CM"]),
    ("Conditions",   ["NFCI", "UNRATE"]),
    ("Dollar & FX",  ["DTWEXBGS", "DEXUSEU", "DEXUSUK", "DEXJPUS", "DEXCHUS", "DEXSIUS", "DEXHKUS"]),
    ("Commodities",  ["DCOILBRENTEU", "DHHNGSP"]),
]

_HDR = 'style="background:#eef2f7;font-weight:bold;padding:5px 10px;text-align:left"'
_TD  = 'style="padding:4px 10px;border-bottom:1px solid #f0f0f0"'
_TDG = 'style="padding:4px 10px;border-bottom:1px solid #f0f0f0;color:#1a7a1a"'
_TDR = 'style="padding:4px 10px;border-bottom:1px solid #f0f0f0;color:#b30000"'
_TDS = 'style="padding:4px 10px;border-bottom:1px solid #f0f0f0;color:#999;font-size:11px"'


def _build_email_html(time_label: str, market: dict, fred: dict, sections: dict,
                      fed_items: list, headlines: list, total_cost: float) -> str:
    # Market indicator table (Finnhub ETF proxies)
    market_rows = ""
    for group_name, names in _MARKET_GROUPS:
        market_rows += f'<tr><th colspan="2" {_HDR}>{group_name}</th></tr>\n'
        for name in names:
            if name not in market:
                continue
            d    = market[name]
            v, c = d.get("value"), d.get("change_pct")
            cell = _fmt_market_cell(name, v, c)
            disp = _MARKET_DISPLAY.get(name, name)
            td   = _TDG if (c or 0) > 0.1 else (_TDR if (c or 0) < -0.1 else _TD)
            market_rows += f'<tr><td {_TD}>{disp}</td><td {td}>{cell}</td></tr>\n'

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

<h2 style="color:#1a1a6b;border-bottom:1px solid #ddd;margin-top:28px">Market Indicators (Finnhub ETF proxies)</h2>
<table {tbl}>{market_rows}</table>

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

# ── Canonical .md writer (seam for tests) ─────────────────────────────────────

def _write_canonical_md(content: str, path: str) -> None:
    with open(path, "w") as f:
        f.write(content)


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

# ── Main ──────────────────────────────────────────────────────────────────────

def main(
    fred_api_key: str,
    finnhub_key: str,
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

    log.info("[MacroResearch] Fetching Finnhub market data...")
    market = _fetch_finnhub_data(finnhub_key)

    log.info("[MacroResearch] Fetching FRED data...")
    fred = _fetch_fred_data(fred_api_key)

    log.info("[MacroResearch] Fetching Fed Reserve RSS feeds...")
    fed_items = _fetch_fed_news()
    log.info(f"[MacroResearch]   {len(fed_items)} Fed items")

    log.info("[MacroResearch] Fetching macro news headlines...")
    headlines = _fetch_macro_news()
    log.info(f"[MacroResearch]   {len(headlines)} headlines")

    # ── Build data strings per section ────────────────────────────────────────
    equity_data = "\n".join([
        _market_data_str(market, ["SP500", "NDX", "RUT", "Nikkei", "DAX", "FTSE", "HSI", "CSI300"]),
        _fred_data_str(fred, ["VIXCLS"]),
    ])
    rates_data  = "\n".join([
        _market_data_str(market, ["HYG", "LQD"]),
        _fred_data_str(fred, ["DFF", "SOFR", "DGS2", "DGS5", "DGS10", "DGS30", "T10Y2Y", "T10Y3M"]),
    ])
    fed_data    = _fred_data_str(fred, ["DFF", "T5YIE", "T10YIE", "CPIAUCSL", "PCEPI", "UNRATE", "NFCI"])
    fx_data     = "\n".join([
        _fred_data_str(fred, ["DTWEXBGS", "DEXUSEU", "DEXUSUK", "DEXJPUS", "DEXCHUS", "DEXSIUS", "DEXHKUS"]),
        _fred_data_str(fred, ["BAMLH0A0HYM2", "BAMLC0A0CM"]),
    ])
    comm_data   = "\n".join([
        _market_data_str(market, ["Copper", "Gold"]),
        _fred_data_str(fred, ["DCOILBRENTEU", "DHHNGSP"]),
    ])
    hk_data     = "\n".join([
        _market_data_str(market, ["HSI", "CSI300"]),
        _fred_data_str(fred, ["DEXHKUS", "DEXCHUS"]),
    ])

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
            "market": market,
            "fred":   fred,
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
    _write_canonical_md(md_content, md_path)
    log.info(f"[MacroResearch] Written {md_path}")

    # ── HTML email ────────────────────────────────────────────────────────────
    log.info("[MacroResearch] Sending HTML email...")
    html_body = _build_email_html(
        time_label, market, fred, sections, fed_items, headlines, total_cost
    )
    _send_email(smtp_resource, recipient_email,
                f"Macro Research — {time_label}", html_body)

    total_words = sum(len(v.split()) for v in sections.values())
    return {
        "status":       "sent",
        "md_path":      md_path,
        "time":         time_label,
        "total_words":  total_words,
        "est_cost_usd": round(total_cost, 4),
    }
