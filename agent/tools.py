"""
Tool registry — maps intents to execution logic.
Each tool returns a dict with at minimum {"text": "reply text"}.
"""
import asyncio
import glob
import json
import os
import time
from datetime import datetime, date, timezone, timedelta
from typing import Any, Optional

import httpx
import psycopg2
import psycopg2.extras
from config import (
    AGENT_DB_URL, ASYNC_NOTIFY, DEEPSEEK_KEY, DEEPSEEK_MODEL,
    EXA_KEY, FAST, FINNHUB_KEY, FIRE, GATED_WRITE, MULTI_STEP, WM_WORKSPACE,
)
from windmill_client import run_job, run_sync

# ── Windmill script paths ─────────────────────────────────────────────────────
SCRIPT_HEALTH_CHECK     = "u/admin/health_check"
SCRIPT_MOVE_MONITOR     = "u/admin/portfolio_move_monitor"
SCRIPT_EMAIL_SUMMARY    = "u/admin/email_summary"
SCRIPT_NEWS_DIGEST      = "u/admin/morning_news_digest"
SCRIPT_YOUTUBE          = "u/admin/youtube_monitor"
SCRIPT_RESEARCH         = "u/admin/research_tool"
SCRIPT_PRICE_FETCHER      = "u/admin/portfolio_price_fetcher"
SCRIPT_FUNDAMENTALS       = "u/admin/fundamentals_fetcher"
SCRIPT_EARNINGS_ANALYSIS    = "u/admin/portfolio_earnings_analysis"
SCRIPT_RATIONALIZATION      = "u/admin/portfolio_rationalization"
SCRIPT_CANDIDATE_EVAL       = "u/admin/portfolio_candidate_eval"

# Resource/variable string refs
RES_PORTFOLIO_DB   = "$res:u/admin/portfolio_db"
RES_GMAIL_SMTP     = "$res:u/admin/gmail_smtp"
VAR_DEEPSEEK_KEY   = "$var:u/admin/deepseek_key"
VAR_RAPIDAPI_KEY   = "$var:u/admin/rapidapi_key"
VAR_PERPLEXITY_KEY = "$var:u/admin/perplexity_key"
VAR_XAI_KEY        = "$var:u/admin/xai_key"
VAR_FINNHUB_KEY    = "$var:u/admin/finnhub_key"
VAR_EXA_KEY        = "$var:u/admin/exa_key"
VAR_SERPER_KEY     = "$var:u/admin/serper_key"
VAR_TAVILY_KEY     = "$var:u/admin/tavily_key"
VAR_BRAVE_KEY      = "$var:u/admin/brave_key"
VAR_FRED_KEY       = "$var:u/admin/fred_key"
VAR_YT_FEEDS       = "$var:u/admin/youtube_feeds"
VAR_YT_STATE       = "$var:u/admin/youtube_processed_state"

TOOL_CLASSES = {
    "portfolio_snapshot":   FAST,
    "portfolio_digest":     FAST,
    "ticker_detail":        FAST,
    "live_prices":          FAST,
    "health_check":         FAST,
    "email_summary":        FIRE,
    "news_digest":          FAST,
    "youtube_digest":       FAST,
    "research":             ASYNC_NOTIFY,
    "price_refresh":        GATED_WRITE,
    "fundamentals_refresh": GATED_WRITE,
    "thesis_read":          FAST,
    "thesis_write":         GATED_WRITE,
    "earnings":             FAST,
    "news_search":          FAST,
    "macro_indicators":     FAST,
    "portfolio_analysis":   MULTI_STEP,
    "thesis_check":         MULTI_STEP,
    "macro_brief":          MULTI_STEP,
    "earnings_analysis":     ASYNC_NOTIFY,
    "portfolio_rationalize": ASYNC_NOTIFY,
    "candidate_evaluation":  ASYNC_NOTIFY,
}

GATED_WRITE_PROMPTS = {
    "price_refresh": "This will write new price data to the database. Reply *confirm* to proceed or *cancel* to abort.",
    "fundamentals_refresh": "This will overwrite fundamental data for all 33 tickers. Reply *confirm* to proceed or *cancel* to abort.",
    "thesis_write": "This will save/update the investment thesis for {ticker}. Reply *confirm* to proceed or *cancel* to abort.",
}


def _pg_conn():
    return psycopg2.connect(AGENT_DB_URL)


def _query(sql: str, params=()) -> list[dict]:
    with _pg_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]


def _execute(sql: str, params=()) -> None:
    """Run a non-SELECT statement (INSERT/UPDATE/DELETE) and commit."""
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
        conn.commit()


# ── FAST tools ────────────────────────────────────────────────────────────────

async def portfolio_snapshot(_args: dict) -> dict:
    rows = await asyncio.to_thread(
        _query,
        """
        SELECT pp.ticker, pp.company_name, pp.currency,
               ph.close_price, ph.price_date,
               pp.shares,
               pp.shares * ph.close_price AS position_native,
               COALESCE(fx.rate, 1) AS fx_to_usd
        FROM portfolio_positions pp
        LEFT JOIN LATERAL (
            SELECT close_price, price_date FROM price_history
            WHERE ticker = pp.ticker ORDER BY price_date DESC LIMIT 1
        ) ph ON TRUE
        LEFT JOIN LATERAL (
            SELECT
                CASE
                    WHEN from_currency = pp.currency AND to_currency = 'USD' THEN rate
                    WHEN from_currency = 'USD' AND to_currency = pp.currency THEN 1.0 / NULLIF(rate, 0)
                END AS rate
            FROM fx_rates
            WHERE (from_currency = pp.currency AND to_currency = 'USD')
               OR (from_currency = 'USD' AND to_currency = pp.currency)
            ORDER BY rate_date DESC LIMIT 1
        ) fx ON TRUE
        ORDER BY (pp.shares * ph.close_price * COALESCE(fx.rate, 1)) DESC NULLS LAST
        """,
    )
    if not rows:
        return {"text": "No portfolio data available."}

    total_usd = sum(
        (r["position_native"] or 0) * (r["fx_to_usd"] or 1) for r in rows
    )
    # Show most recent price date per currency so user knows data freshness
    dates_by_ccy = {}
    for r in rows:
        if r.get("price_date") and r.get("currency"):
            ccy = r["currency"]
            d = str(r["price_date"])[:10]
            if ccy not in dates_by_ccy or d > dates_by_ccy[ccy]:
                dates_by_ccy[ccy] = d
    date_str = "  ·  ".join(f"{ccy}: {d}" for ccy, d in sorted(dates_by_ccy.items()))
    lines = [
        f"*Portfolio Live* — ${total_usd:,.0f} USD",
        f"_{date_str}_\n",
    ]
    for r in rows:
        val_usd = (r["position_native"] or 0) * (r["fx_to_usd"] or 1)
        pct = val_usd / total_usd * 100 if total_usd else 0
        lines.append(
            f"{r['ticker']:8} {str(r['close_price'] or '—'):>10}  {r['currency']}  "
            f"${val_usd:>9,.0f}  ({pct:.1f}%)"
        )
    return {"text": "\n".join(lines)}


async def ticker_detail(args: dict) -> dict:
    ticker = args.get("ticker", "").upper()
    if not ticker:
        return {"text": "Please specify a ticker symbol."}

    price_rows = await asyncio.to_thread(
        _query,
        """SELECT close_price, price_date FROM price_history
           WHERE ticker = %s ORDER BY price_date DESC LIMIT 5""",
        (ticker,),
    )
    fund_rows = await asyncio.to_thread(
        _query,
        """SELECT * FROM fundamental_data WHERE ticker = %s
           ORDER BY as_of_date DESC LIMIT 1""",
        (ticker,),
    )

    if not price_rows:
        return {"text": f"No price data found for {ticker}."}

    latest = price_rows[0]
    lines = [f"*{ticker}* — {latest['price_date']}"]
    lines.append(f"Price: {latest['close_price']}")

    if len(price_rows) > 1:
        prev = price_rows[1]["close_price"]
        if prev and latest["close_price"]:
            chg = (latest["close_price"] - prev) / prev * 100
            lines.append(f"1-day change: {chg:+.2f}%")

    if fund_rows:
        f = fund_rows[0]
        if f.get("pe_ratio"):
            lines.append(f"P/E: {f['pe_ratio']:.1f}")
        if f.get("analyst_target_usd"):
            lines.append(f"Price target: ${f['analyst_target_usd']:,.2f}")
        if f.get("market_cap_usd"):
            mc = float(f["market_cap_usd"])
            lines.append(f"Mkt cap: {'${:,.0f}B'.format(mc/1e9) if mc > 1e9 else '${:,.0f}M'.format(mc/1e6)}")

    return {"text": "\n".join(lines)}


async def live_prices(_args: dict) -> dict:
    result = await run_sync(
        SCRIPT_MOVE_MONITOR,
        {"portfolio_db": RES_PORTFOLIO_DB},
        timeout=45,
    )
    if not result.get("alerted"):
        pct = result.get("portfolio_move_pct", 0)
        return {"text": f"No threshold breaches. Portfolio move: {pct:+.2f}%"}

    pct = result.get("portfolio_move_pct", 0)
    alerts = result.get("position_alerts", [])
    lines = [f"*Move Alert* — Portfolio: {pct:+.2f}%"]
    if alerts:
        lines.append("Position movers: " + ", ".join(alerts))
    return {"text": "\n".join(lines)}


async def health_check(_args: dict) -> dict:
    result = await run_sync(
        SCRIPT_HEALTH_CHECK,
        {},
        timeout=60,
    )
    ok = result.get("ok_count", 0)
    total = result.get("total", 0)
    cost = result.get("total_cost", 0)
    status_emoji = "✅" if ok == total else "⚠️"
    lines = [f"{status_emoji} *Health Check* — {ok}/{total} OK | Est. cost today: ${cost:.4f}"]
    for row in result.get("rows", []):
        icon = "✅" if row.get("status") == "OK" else "❌"
        lines.append(f"{icon} {row.get('label', '?')}")
    return {"text": "\n".join(lines)}


# ── FIRE tools — dispatch with gmail_smtp, return immediate ACK ───────────────

async def email_summary(_args: dict) -> dict:
    await run_job(SCRIPT_EMAIL_SUMMARY, {
        "smtp_resource": RES_GMAIL_SMTP,
        "deepseek_key":  VAR_DEEPSEEK_KEY,
    })
    return {"text": "📧 Email summary triggered — check your inbox in ~30s."}


def _read_latest_research_file(directory: str) -> Optional[str]:
    """Return contents of the most recently dated .md file in directory, or None."""
    files = sorted(glob.glob(f"{directory}/*.md"))
    if not files:
        return None
    with open(files[-1]) as f:
        return f.read()


_SUMMARISE_THRESHOLD = 3500  # chars; above this, call Deepseek to condense

_SUMMARISE_PROMPTS = {
    "news": (
        "Summarise the following morning news digest for a finance professional. "
        "List the 8-10 most important stories as bullet points. "
        "Each bullet: source, headline, one sentence on why it matters. "
        "Group loosely by theme (markets, geopolitics, energy, tech). "
        "No markdown headers — plain bullet list only."
    ),
    "youtube": (
        "Summarise this YouTube channel digest for a finance professional. "
        "For each video that has a real summary (skip entries marked 'No transcript available'), "
        "give: channel name, video title as a short label, one-sentence key takeaway. "
        "Format each as: '• Channel — Title: takeaway.' "
        "Keep the whole response under 600 words."
    ),
}


async def _summarise_for_telegram(content: str, digest_type: str) -> str:
    prompt = _SUMMARISE_PROMPTS.get(
        digest_type, "Summarise the following into key bullet points under 400 words."
    )
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                "https://api.deepseek.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {DEEPSEEK_KEY}"},
                json={
                    "model": DEEPSEEK_MODEL,
                    "messages": [
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": content},
                    ],
                    "max_tokens": 900,
                },
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"[summarise] {digest_type} failed: {e} — truncating instead")
        return content[:_SUMMARISE_THRESHOLD] + "\n\n_(summarisation unavailable — truncated)_"


async def news_digest(_args: dict) -> dict:
    content = _read_latest_research_file("/research/news")
    if not content:
        return {"text": "No news digest on file yet. The digest runs at 6:30 AM SGT daily."}
    if len(content) > _SUMMARISE_THRESHOLD:
        content = await _summarise_for_telegram(content, "news")
    return {"text": content}


async def youtube_digest(_args: dict) -> dict:
    content = _read_latest_research_file("/research/youtube")
    if not content:
        return {"text": "No YouTube digest on file yet. The digest runs every 6 hours."}
    if len(content) > _SUMMARISE_THRESHOLD:
        content = await _summarise_for_telegram(content, "youtube")
    return {"text": content}


async def portfolio_digest(_args: dict) -> dict:
    content = _read_latest_research_file("/research/portfolio")
    if not content:
        return {"text": "No portfolio digest on file yet. The email runs at 6 AM and 6 PM SGT."}
    return {"text": content}


# ── ASYNC_NOTIFY tool — dispatch research, caller handles polling ─────────────

def _check_research_cache(ticker: str, research_type: str) -> Optional[dict]:
    """Returns the most recent deep/standard report within 90 days, or None."""
    with _pg_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT content, file_path, array_length(sources, 1) AS source_count, est_cost_usd, created_at, depth
                   FROM research_reports
                   WHERE ticker = %s AND research_type = %s
                     AND depth IN ('deep', 'standard')
                     AND created_at > NOW() - INTERVAL '90 days'
                   ORDER BY created_at DESC LIMIT 1""",
                (ticker, research_type),
            )
            row = cur.fetchone()
            return dict(row) if row else None


async def dispatch_research(args: dict, phone: str) -> dict:
    """
    Tiered cache: checks for prior deep/standard research within 90 days.
    - Prior research <30 days: dispatch brief update, prepend synopsis
    - Prior research 30–90 days: dispatch standard focused on new developments
    - No prior research: dispatch at requested depth (default: deep)
    Returns {"text": ack, "job_id": job_id} — job_id may be None if fully cached.
    """
    ticker = (args.get("ticker") or "").strip().upper()
    question = (args.get("question") or "").strip()
    if not ticker and not question:
        return {"text": "Please specify a ticker or topic — e.g. */research NVDA* or *research inflation outlook*.", "job_id": None}
    research_type = args.get("research_type", "stock") if ticker else args.get("research_type", "macro")
    depth = args.get("depth", "deep")
    force = args.get("force", False)

    wm_args = {
        "portfolio_db":   RES_PORTFOLIO_DB,
        "gmail_smtp":     RES_GMAIL_SMTP,
        "deepseek_key":   VAR_DEEPSEEK_KEY,
        "perplexity_key": VAR_PERPLEXITY_KEY,
        "xai_key":        VAR_XAI_KEY,
        "finnhub_key":    VAR_FINNHUB_KEY,
        "exa_key":        VAR_EXA_KEY,
        "serper_key":     VAR_SERPER_KEY,
        "tavily_key":     VAR_TAVILY_KEY,
        "brave_key":      VAR_BRAVE_KEY,
        "fred_key":       VAR_FRED_KEY,
        "wm_token":       "$var:u/admin/wm_token",
        "research_type":  research_type,
    }
    if ticker:
        wm_args["ticker"] = ticker

    label = ticker if ticker else question[:40] if question else research_type
    cache = None
    if ticker and not force:
        cache = await asyncio.to_thread(_check_research_cache, ticker, research_type)

    if cache:
        created_at = cache["created_at"]
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - created_at).days
        date_str = created_at.strftime("%Y-%m-%d")
        if age_days <= 30:
            content = (cache.get("content") or "")[:2000]
            src = cache.get("source_count") or 0
            cost = cache.get("est_cost_usd") or 0
            return {
                "text": (
                    f"📋 *{label} — {cache['depth']} research ({date_str})*"
                    f" | {src} sources | ${cost:.3f}\n\n{content}"
                ),
                "job_id": None,
            }
        else:
            wm_args["depth"] = "standard"
            if question:
                wm_args["question"] = question
            ack = (f"🔍 Running standard research on *{label}*"
                   f" (prior: {date_str}) — ~60s. I'll message you when done.")
    else:
        dispatch_depth = "deep" if research_type == "stock" else depth
        wm_args["depth"] = dispatch_depth
        if question:
            wm_args["question"] = question
        eta = {"standard": "~60s", "deep": "~2 min"}.get(dispatch_depth, "~60s")
        ack = (f"🔍 Starting research on *{label}*"
               f" ({dispatch_depth} depth) — {eta}. I'll message you when done.")

    job_id = await run_job(SCRIPT_RESEARCH, wm_args)
    return {"text": ack, "job_id": job_id, "has_synopsis": False}


async def dispatch_earnings_analysis(args: dict, phone: str) -> dict:
    ticker = (args.get("ticker") or "").strip().upper()
    analysis_type = (args.get("analysis_type") or "pre").lower()
    if not ticker:
        return {"text": "Please specify a ticker, e.g. 'pre earnings NVDA' or 'post earnings analysis AAPL'"}
    if analysis_type not in ("pre", "post"):
        analysis_type = "pre"
    label = "Pre-earnings briefing" if analysis_type == "pre" else "Post-earnings analysis"
    job_id = await run_job(SCRIPT_EARNINGS_ANALYSIS, {
        "ticker": ticker,
        "analysis_type": analysis_type,
        "portfolio_db": RES_PORTFOLIO_DB,
        "gmail_smtp": RES_GMAIL_SMTP,
        "xai_key": VAR_XAI_KEY,
        "exa_key": VAR_EXA_KEY,
        "finnhub_key": VAR_FINNHUB_KEY,
        "wm_token": "$var:u/admin/wm_token",
        "telegram_bot_token": "$var:u/admin/telegram_bot_token",
    })
    return {
        "text": f"📊 *{label}* for *{ticker}* dispatched — ~60s. I'll message you when done.",
        "job_id": job_id,
    }


async def dispatch_candidate_eval(args: dict, phone: str) -> dict:
    ticker = (args.get("ticker") or "").strip().upper()
    if not ticker:
        return {"text": "Please specify a ticker, e.g. 'evaluate NVDA' or 'should I add MSFT'"}
    universe_tickers = args.get("universe_tickers") or []
    thesis_text      = args.get("thesis_text") or ""
    replacement_ticker = args.get("replacement_ticker") or ""
    job_id = await run_job(SCRIPT_CANDIDATE_EVAL, {
        "ticker":              ticker,
        "portfolio_db":        RES_PORTFOLIO_DB,
        "gmail_smtp":          RES_GMAIL_SMTP,
        "xai_key":             VAR_XAI_KEY,
        "deepseek_key":        VAR_DEEPSEEK_KEY,
        "universe_tickers":    universe_tickers,
        "thesis_text":         thesis_text,
        "replacement_ticker":  replacement_ticker,
    })
    return {
        "text": f"🔍 *Candidate eval* for *{ticker}* dispatched — ~60s. I'll message you when done.",
        "job_id": job_id,
    }


RATIONALIZATION_MAX_AGE_DAYS = 30
RATIONALIZATION_DIR = "/research/portfolio"


def _read_latest_rationalization() -> Optional[dict]:
    """Return {content, date_str} for the most recent rationalization file ≤30 days, or None."""
    files = sorted(glob.glob(f"{RATIONALIZATION_DIR}/rationalization_*.md"), reverse=True)
    if not files:
        return None
    latest = files[0]
    basename = os.path.basename(latest)
    try:
        date_str = basename.replace("rationalization_", "").replace(".md", "")
        file_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - file_date).days
        if age_days > RATIONALIZATION_MAX_AGE_DAYS:
            return None
        with open(latest) as f:
            content = f.read()
        return {"content": content, "date_str": date_str, "age_days": age_days}
    except Exception:
        return None


async def dispatch_rationalization(args: dict, phone: str) -> dict:
    """FAST path: return compact ranked table from recent file. ASYNC path: dispatch Windmill job."""
    cached = await asyncio.to_thread(_read_latest_rationalization)
    if cached:
        preview = cached["content"][:2000]
        return {
            "text": (
                f"📊 *Portfolio Rationalization ({cached['date_str']})*"
                f" — {cached['age_days']}d ago\n\n{preview}\n\n"
                f"_Full report emailed. Run `/rationalize force` for a fresh analysis._"
            ),
            "job_id": None,
        }
    job_id = await run_job(SCRIPT_RATIONALIZATION, {
        "portfolio_db": RES_PORTFOLIO_DB,
        "gmail_smtp": RES_GMAIL_SMTP,
        "xai_key": VAR_XAI_KEY,
        "deepseek_key": VAR_DEEPSEEK_KEY,
    })
    return {
        "text": (
            "📊 *Portfolio Rationalization* analysis dispatched — ~10 min. "
            "Full report will be emailed to you when complete."
        ),
        "job_id": job_id,
    }


def format_research_result(result: dict) -> str:
    today = date.today().strftime("%Y-%m-%d")
    preview = result.get("preview") or result.get("synthesis", "")[:2000]
    source_count = result.get("source_count", 0)
    cost = result.get("est_cost_usd", 0)
    lines = [
        f"✅ *Research complete* ({today}) | {source_count} sources | ${cost:.3f}",
        "",
        preview,
    ]
    if result.get("file_path"):
        lines.append(f"\n📄 Full report: {result['file_path']}")
    return "\n".join(lines)


# ── W2 FAST tools: earnings, news_search, macro_indicators ────────────────────

def _read_latest_earnings_file(ticker: str) -> Optional[str]:
    """Return content of the most recent /research/earnings/ file matching ticker."""
    files = sorted(glob.glob("/research/earnings/*.md"), reverse=True)
    matches = [f for f in files if ticker.upper() in os.path.basename(f).upper()]
    if not matches:
        return None
    with open(matches[0]) as fh:
        return fh.read()


async def _finnhub_calendar(tickers: list[str]) -> dict:
    """Fetch Finnhub earnings calendar for given tickers, return {text}."""
    today = date.today()
    from_date = today.strftime("%Y-%m-%d")
    to_date = (today + timedelta(days=14)).strftime("%Y-%m-%d")
    all_events = []
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            for t in tickers[:10]:
                url = (f"https://finnhub.io/api/v1/calendar/earnings"
                       f"?from={from_date}&to={to_date}&symbol={t}&token={FINNHUB_KEY}")
                r = await client.get(url)
                data = r.json().get("earningsCalendar", [])
                all_events.extend(data)
    except Exception as e:
        return {"text": f"Earnings data unavailable: {e}"}
    if not all_events:
        return {"text": f"No upcoming earnings in the next 14 days for {', '.join(tickers[:5])}."}
    all_events.sort(key=lambda x: x.get("date", ""))
    lines = ["*Upcoming Earnings (next 14 days)*\n"]
    for ev in all_events[:20]:
        sym = ev.get("symbol", "?")
        d = ev.get("date", "?")
        est = ev.get("epsEstimate")
        est_str = f"  EPS est: {est:.2f}" if est is not None else ""
        lines.append(f"• {sym}  {d}{est_str}")
    return {"text": "\n".join(lines)}


async def earnings(args: dict) -> dict:
    ticker = (args.get("ticker") or "").strip().upper()

    if not ticker:
        # No ticker — portfolio-wide calendar
        rows = await asyncio.to_thread(_query, "SELECT ticker FROM portfolio_positions")
        tickers = [r["ticker"] for r in rows]
        if not tickers:
            return {"text": "No tickers found."}
        return await _finnhub_calendar(tickers)

    # Ticker provided — serve stored analysis file
    content = _read_latest_earnings_file(ticker)
    if content:
        return {"text": content}

    # No file on disk — fall back to Finnhub date for this ticker
    result = await _finnhub_calendar([ticker])
    if "No upcoming" in result["text"] or "unavailable" in result["text"].lower():
        return {"text": f"No earnings analysis on file for {ticker}. "
                        f"Run *'pre earnings {ticker}'* to generate one.\n\n{result['text']}"}
    return {"text": f"No earnings analysis on file for {ticker}. "
                    f"Run *'pre earnings {ticker}'* to generate one.\n\n{result['text']}"}


async def news_search(args: dict) -> dict:
    query = (args.get("query") or "").strip()
    if not query:
        return {"text": "Please provide a search query, e.g. 'search NVDA earnings'."}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                "https://api.exa.ai/search",
                headers={"x-api-key": EXA_KEY, "Content-Type": "application/json"},
                json={
                    "query": query,
                    "numResults": 5,
                    "useAutoprompt": True,
                    "contents": {"summary": {"query": query}},
                },
            )
            data = r.json()
    except Exception as e:
        return {"text": f"News search failed: {e}"}
    results = data.get("results", [])
    if not results:
        return {"text": f"No results found for: {query}"}
    lines = [f"*News Search: {query}*\n"]
    for item in results:
        title = item.get("title", "Untitled")
        url = item.get("url", "")
        summary = item.get("summary", "").strip()
        lines.append(f"• [{title}]({url})")
        if summary:
            lines.append(f"  _{summary[:120]}_")
    return {"text": "\n".join(lines)}


_MACRO_SYMBOLS = {
    "SGDUSD=X": "SGD/USD",
    "HKDUSD=X": "HKD/USD",
    "^VIX":     "VIX",
    "BZ=F":     "Brent",
    "^TNX":     "UST 10Y",
}


async def macro_indicators(_args: dict) -> dict:
    lines = ["*Macro Indicators*\n"]
    errors = 0
    async with httpx.AsyncClient(timeout=10) as client:
        for symbol, label in _MACRO_SYMBOLS.items():
            try:
                r = await client.get(
                    f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
                    params={"interval": "1d", "range": "5d"},
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                result = r.json()["chart"]["result"][0]
                closes = result["indicators"]["quote"][0]["close"]
                closes = [c for c in closes if c is not None]
                if len(closes) < 1:
                    raise ValueError("no data")
                latest = closes[-1]
                chg = ((closes[-1] / closes[0]) - 1) * 100 if len(closes) >= 2 else 0
                arrow = "▲" if chg >= 0 else "▼"
                lines.append(f"{label:10}  {latest:>10.4f}  {arrow}{abs(chg):.2f}% (5d)")
            except Exception:
                errors += 1
                lines.append(f"{label:10}  —")
    if errors == len(_MACRO_SYMBOLS):
        return {"text": "Macro data unavailable — Yahoo Finance unreachable."}
    return {"text": "\n".join(lines)}


# ── portfolio_thesis tools ─────────────────────────────────────────────────────

async def thesis_read(args: dict) -> dict:
    ticker = (args.get("ticker") or "").strip().upper()
    if not ticker:
        return {"text": "Please specify a ticker, e.g. 'thesis NVDA'."}
    rows = await asyncio.to_thread(
        _query,
        "SELECT * FROM portfolio_thesis WHERE ticker = %s",
        (ticker,),
    )
    if not rows:
        return {"text": f"No thesis found for {ticker}. Use 'save thesis {ticker} ...' to add one."}
    r = rows[0]
    catalysts = r.get("key_catalysts") or []
    risks = r.get("risks") or []
    lines = [
        f"*Investment Thesis — {ticker}*",
        f"Conviction: {r.get('conviction', '—')}  |  Date: {r.get('thesis_date', '—')}",
        "",
        r.get("investment_thesis", ""),
    ]
    if catalysts:
        lines += ["", "*Key Catalysts:*"] + [f"• {c}" for c in catalysts]
    if risks:
        lines += ["", "*Risks:*"] + [f"• c" for c in risks]
    if r.get("target_price_usd"):
        lines.append(f"\nTarget: ${r['target_price_usd']:.2f}")
    return {"text": "\n".join(lines)}


async def run_thesis_write(args: dict) -> dict:
    ticker = (args.get("ticker") or "").strip().upper()
    thesis = (args.get("thesis") or "").strip()
    conviction = (args.get("conviction") or "Medium").strip()
    catalysts = args.get("catalysts", [])
    risks = args.get("risks", [])
    if not ticker or not thesis:
        return {"text": "Need both ticker and thesis text to save."}
    await asyncio.to_thread(
        _execute,
        """
        INSERT INTO portfolio_thesis (ticker, investment_thesis, key_catalysts, risks, conviction, updated_at)
        VALUES (%s, %s, %s::jsonb, %s::jsonb, %s, NOW())
        ON CONFLICT (ticker) DO UPDATE SET
            investment_thesis = EXCLUDED.investment_thesis,
            key_catalysts     = EXCLUDED.key_catalysts,
            risks             = EXCLUDED.risks,
            conviction        = EXCLUDED.conviction,
            updated_at        = NOW()
        """,
        (ticker, thesis, json.dumps(catalysts), json.dumps(risks), conviction),
    )
    return {"text": f"Thesis for {ticker} saved (conviction: {conviction})."}


# ── GATED_WRITE tools — dispatch after confirmation ───────────────────────────

async def run_price_refresh(_args: dict) -> dict:
    job_id = await run_job(SCRIPT_PRICE_FETCHER, {
        "portfolio_db": RES_PORTFOLIO_DB,
    })
    return {"text": f"✅ Price refresh dispatched (job {job_id[:8]}…). Will complete in ~30s."}


async def run_fundamentals_refresh(_args: dict) -> dict:
    job_id = await run_job(SCRIPT_FUNDAMENTALS, {
        "portfolio_db": RES_PORTFOLIO_DB,
        "finnhub_key":  VAR_FINNHUB_KEY,
    })
    return {"text": f"✅ Fundamentals refresh dispatched (job {job_id[:8]}…). Will complete in ~2 min."}


GATED_WRITE_EXECUTORS = {
    "price_refresh":       run_price_refresh,
    "fundamentals_refresh": run_fundamentals_refresh,
    "thesis_write":        run_thesis_write,
}

FAST_EXECUTORS = {
    "portfolio_snapshot": portfolio_snapshot,
    "portfolio_digest":   portfolio_digest,
    "ticker_detail":      ticker_detail,
    "live_prices":        live_prices,
    "health_check":       health_check,
    "news_digest":        news_digest,
    "youtube_digest":     youtube_digest,
    "thesis_read":        thesis_read,
    "earnings":           earnings,
    "news_search":        news_search,
    "macro_indicators":   macro_indicators,
}

FIRE_EXECUTORS = {
    "email_summary": email_summary,
}

ASYNC_NOTIFY_EXECUTORS = {
    "research":              dispatch_research,
    "earnings_analysis":     dispatch_earnings_analysis,
    "portfolio_rationalize": dispatch_rationalization,
    "candidate_evaluation":  dispatch_candidate_eval,
}
