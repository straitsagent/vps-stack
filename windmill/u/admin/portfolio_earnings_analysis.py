# Requirements:
# psycopg2-binary>=2.9
# requests>=2.31
# yfinance>=0.2.40
# openai>=1.0.0

"""
Earnings analysis tool — pre-earnings briefing or post-earnings analysis with recommendation.

Pre-earnings: fetches earnings date/estimates, historical quarterly financials, prior 8-K
press release (EDGAR), and earnings call transcripts (Exa → SeekingAlpha/Motley Fool).
Synthesises a structured briefing: what to watch, trends, valuation context.

Post-earnings: fetches actual results, current 8-K press release (EDGAR), earnings call
transcript (Exa), analyst reactions (Exa), price reaction. Synthesises full analysis with
Buy/Accumulate/Hold/Reduce/Sell recommendation.
"""

import json
import os
import re
import time
from datetime import date, datetime, timedelta
from typing import Optional, TypedDict

import psycopg2
import requests

# openai imported inline — keeps Windmill happy if package is slow to load
from openai import OpenAI


class postgresql(TypedDict):
    host: str
    port: int
    user: str
    password: str
    dbname: str


class smtp(TypedDict):
    host: str
    port: int
    username: str
    password: str
    tls_implicit: bool


RESEARCH_DIR = "/research/earnings"
WM_BASE = "http://windmill_server:8000"
WM_WORKSPACE = "admins"


# ── DB helpers ─────────────────────────────────────────────────────────────────

def _get_portfolio_context(portfolio_db: dict, ticker: str) -> dict:
    """Return context dict: fundamentals, position sizing, thesis, prior analysis, research synopsis."""
    conn = psycopg2.connect(
        host=portfolio_db["host"], port=portfolio_db.get("port", 5432),
        user=portfolio_db["user"], password=portfolio_db["password"],
        dbname=portfolio_db["dbname"],
    )
    ctx = {"ticker": ticker, "company_name": ticker, "currency": "USD"}
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT company_name, currency FROM portfolio_positions WHERE ticker = %s",
                (ticker,),
            )
            row = cur.fetchone()
            if row:
                ctx["company_name"] = row[0]
                ctx["currency"] = row[1]

            cur.execute(
                """SELECT pe_ratio, pb_ratio, market_cap_usd, analyst_target_usd,
                          net_margin, revenue_growth_yoy, sector, roe, roic
                   FROM fundamental_data WHERE ticker = %s
                   ORDER BY updated_at DESC LIMIT 1""",
                (ticker,),
            )
            row = cur.fetchone()
            if row:
                cols = ["pe_ratio", "pb_ratio", "market_cap_usd", "analyst_target_usd",
                        "net_margin", "revenue_growth_yoy", "sector", "roe", "roic"]
                for k, v in zip(cols, row):
                    ctx[k] = v

            cur.execute(
                "SELECT investment_thesis, conviction FROM portfolio_thesis WHERE ticker = %s",
                (ticker,),
            )
            row = cur.fetchone()
            if row:
                ctx["thesis"] = row[0]
                ctx["conviction"] = row[1]

            cur.execute(
                """SELECT analysis_type, earnings_date, content
                   FROM earnings_analyses WHERE ticker = %s AND analysis_type = 'pre'
                   ORDER BY created_at DESC LIMIT 1""",
                (ticker,),
            )
            row = cur.fetchone()
            if row:
                ctx["prior_pre_analysis"] = {"earnings_date": str(row[1]), "content": row[2]}

            # Portfolio position sizing
            cur.execute(
                """SELECT pp.shares, ph.close_price,
                          pp.shares * ph.close_price * COALESCE(fx.rate, 1) AS position_usd
                   FROM portfolio_positions pp
                   LEFT JOIN LATERAL (
                       SELECT close_price FROM price_history
                       WHERE ticker = pp.ticker ORDER BY price_date DESC LIMIT 1
                   ) ph ON TRUE
                   LEFT JOIN LATERAL (
                       SELECT CASE
                           WHEN from_currency = pp.currency AND to_currency = 'USD' THEN rate
                           WHEN from_currency = 'USD' AND to_currency = pp.currency THEN 1.0/NULLIF(rate,0)
                       END AS rate
                       FROM fx_rates
                       WHERE (from_currency = pp.currency AND to_currency = 'USD')
                          OR (from_currency = 'USD' AND to_currency = pp.currency)
                       ORDER BY rate_date DESC LIMIT 1
                   ) fx ON TRUE
                   WHERE pp.ticker = %s""",
                (ticker,),
            )
            row = cur.fetchone()
            if row:
                ctx["shares"] = float(row[0]) if row[0] else None
                ctx["latest_price"] = float(row[1]) if row[1] else None
                ctx["position_usd"] = float(row[2]) if row[2] else None

            # Total portfolio value for % weight
            cur.execute(
                """SELECT SUM(pp.shares * ph.close_price * COALESCE(fx.rate, 1))
                   FROM portfolio_positions pp
                   LEFT JOIN LATERAL (
                       SELECT close_price FROM price_history
                       WHERE ticker = pp.ticker ORDER BY price_date DESC LIMIT 1
                   ) ph ON TRUE
                   LEFT JOIN LATERAL (
                       SELECT CASE
                           WHEN from_currency = pp.currency AND to_currency = 'USD' THEN rate
                           WHEN from_currency = 'USD' AND to_currency = pp.currency THEN 1.0/NULLIF(rate,0)
                       END AS rate
                       FROM fx_rates
                       WHERE (from_currency = pp.currency AND to_currency = 'USD')
                          OR (from_currency = 'USD' AND to_currency = pp.currency)
                       ORDER BY rate_date DESC LIMIT 1
                   ) fx ON TRUE"""
            )
            row = cur.fetchone()
            ctx["total_portfolio_usd"] = float(row[0]) if row and row[0] else None

            # Most recent research report synopsis
            cur.execute(
                """SELECT content, created_at, depth, source_count
                   FROM (
                       SELECT content, created_at, depth,
                              array_length(sources, 1) AS source_count
                       FROM research_reports
                       WHERE ticker = %s AND research_type = 'stock'
                       ORDER BY created_at DESC LIMIT 1
                   ) r""",
                (ticker,),
            )
            row = cur.fetchone()
            if row:
                ctx["research_content"] = row[0]
                ctx["research_date"] = str(row[1])[:10]
                ctx["research_depth"] = row[2]
                ctx["research_source_count"] = row[3]
    finally:
        conn.close()
    return ctx


def _save_analysis(portfolio_db: dict, ticker: str, analysis_type: str,
                   earnings_date: Optional[str], eps_estimate: Optional[float],
                   eps_actual: Optional[float], revenue_estimate: Optional[float],
                   revenue_actual: Optional[float], surprise_pct: Optional[float],
                   recommendation: Optional[str], content: str, file_path: str):
    conn = psycopg2.connect(
        host=portfolio_db["host"], port=portfolio_db.get("port", 5432),
        user=portfolio_db["user"], password=portfolio_db["password"],
        dbname=portfolio_db["dbname"],
    )
    with conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO earnings_analyses
                   (ticker, analysis_type, earnings_date, eps_estimate, eps_actual,
                    revenue_estimate, revenue_actual, surprise_pct, recommendation,
                    content, file_path)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (ticker, analysis_type,
                 earnings_date, eps_estimate, eps_actual,
                 revenue_estimate, revenue_actual, surprise_pct, recommendation,
                 content, file_path),
            )
    conn.close()


# ── Finnhub helpers ────────────────────────────────────────────────────────────

def _finnhub_earnings(ticker: str, finnhub_key: str, from_date: str, to_date: str) -> list[dict]:
    try:
        url = (f"https://finnhub.io/api/v1/calendar/earnings"
               f"?from={from_date}&to={to_date}&symbol={ticker}&token={finnhub_key}")
        resp = requests.get(url, timeout=10)
        return resp.json().get("earningsCalendar", [])
    except Exception as e:
        print(f"[Finnhub] earnings fetch error: {e}")
        return []


# ── yfinance quarterly financials ─────────────────────────────────────────────

def _yfinance_quarterly(ticker: str) -> str:
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        qf = t.quarterly_financials
        if qf is None or qf.empty:
            return ""
        rows = []
        for col in qf.columns[:4]:
            quarter = str(col)[:10]
            rev = qf.loc["Total Revenue", col] if "Total Revenue" in qf.index else None
            gp = qf.loc["Gross Profit", col] if "Gross Profit" in qf.index else None
            ni = qf.loc["Net Income", col] if "Net Income" in qf.index else None
            def fmt(v):
                if v is None:
                    return "n/a"
                try:
                    return f"${float(v)/1e9:.2f}B"
                except Exception:
                    return "n/a"
            rows.append(f"| {quarter} | {fmt(rev)} | {fmt(gp)} | {fmt(ni)} |")
        header = "| Quarter | Revenue | Gross Profit | Net Income |\n|---|---|---|---|"
        return header + "\n" + "\n".join(rows)
    except Exception as e:
        print(f"[yfinance] quarterly financials error: {e}")
        return ""


# ── EDGAR 8-K helpers ─────────────────────────────────────────────────────────


def _edgar_fetch_text(url: str) -> Optional[str]:
    """Fetch and strip HTML from a URL, return plain text up to 8000 chars."""
    try:
        resp = requests.get(url, headers={"User-Agent": "straitsagent@gmail.com"}, timeout=15)
        text = re.sub(r"<[^>]+>", " ", resp.text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:8000] if len(text) > 100 else None
    except Exception as e:
        print(f"[EDGAR] fetch error: {e}")
        return None


def _edgar_latest_8k(ticker: str, days_back: int = 7) -> Optional[str]:
    """Fetch Exhibit 99.1 text from the most recent 8-K press release via EDGAR EFTS search.
    The _id field in EFTS results encodes accession:exhibit_path directly."""
    try:
        from_dt = (date.today() - timedelta(days=days_back)).strftime("%Y-%m-%d")
        to_dt = date.today().strftime("%Y-%m-%d")
        url = (f"https://efts.sec.gov/LATEST/search-index?q=%22{ticker}%22&forms=8-K"
               f"&dateRange=custom&startdt={from_dt}&enddt={to_dt}")
        resp = requests.get(url, headers={"User-Agent": "straitsagent@gmail.com"}, timeout=15)
        hits = resp.json().get("hits", {}).get("hits", [])
        if not hits:
            print(f"[EDGAR] No 8-K for {ticker} in last {days_back} days")
            return None

        for hit in hits:
            src = hit.get("_source", {})
            # Prefer EX-99.1 (actual press release) over the 8-K wrapper
            file_type = src.get("file_type", "")
            hit_id = hit.get("_id", "")
            if ":" not in hit_id:
                continue
            accession_with_dashes, exhibit_filename = hit_id.split(":", 1)
            ciks = src.get("ciks", [])
            if not ciks:
                continue
            cik_int = int(ciks[0])
            accession_nodash = accession_with_dashes.replace("-", "")
            exhibit_url = (f"https://www.sec.gov/Archives/edgar/data/{cik_int}/"
                           f"{accession_nodash}/{exhibit_filename}")
            print(f"[EDGAR] Fetching {file_type} for {ticker} from {src.get('file_date','?')}: {exhibit_url}")
            text = _edgar_fetch_text(exhibit_url)
            if text:
                return text

        print(f"[EDGAR] Could not extract text from any 8-K hit for {ticker}")
        return None
    except Exception as e:
        print(f"[EDGAR] 8-K fetch error: {e}")
        return None


def _edgar_prior_8k(ticker: str) -> Optional[str]:
    """Fetch 8-K press release from ~90 days ago (prior quarter)."""
    return _edgar_latest_8k(ticker, days_back=120)


# ── Exa search helpers ────────────────────────────────────────────────────────

def _exa_search(query: str, exa_key: str, num_results: int = 3, max_chars: int = 3000) -> str:
    try:
        resp = requests.post(
            "https://api.exa.ai/search",
            headers={"x-api-key": exa_key, "Content-Type": "application/json"},
            json={"query": query, "numResults": num_results, "contents": {"text": {"maxCharacters": max_chars}}},
            timeout=20,
        )
        results = resp.json().get("results", [])
        parts = []
        for r in results:
            title = r.get("title", "")
            url = r.get("url", "")
            text = r.get("text", r.get("summary", ""))[:max_chars]
            parts.append(f"[{title}]({url})\n{text}")
        return "\n\n---\n\n".join(parts)
    except Exception as e:
        print(f"[Exa] search error: {e}")
        return ""


# ── Research dispatch ────────────────────────────────────────────────────────

def _dispatch_and_wait_research(ticker: str, wm_token: str, timeout_s: int = 240) -> bool:
    """Dispatch research_tool (standard depth) for ticker and poll until done.
    Returns True on success, False on timeout or error."""
    try:
        url = f"{WM_BASE}/api/w/{WM_WORKSPACE}/jobs/run/p/u/admin/research_tool"
        payload = {
            "ticker": ticker,
            "research_type": "stock",
            "depth": "standard",
            "portfolio_db": "$res:u/admin/portfolio_db",
            "gmail_smtp": "$res:u/admin/gmail_smtp",
            "xai_key": "$var:u/admin/xai_key",
            "exa_key": "$var:u/admin/exa_key",
            "finnhub_key": "$var:u/admin/finnhub_key",
            "perplexity_key": "$var:u/admin/perplexity_key",
            "telegram_bot_token": "$var:u/admin/telegram_bot_token",
        }
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {wm_token}", "Content-Type": "application/json"},
            json=payload,
            timeout=15,
        )
        resp.raise_for_status()
        job_id = resp.text.strip().strip('"')
        print(f"[Research] Dispatched research_tool for {ticker}, job {job_id} — polling...")
        for _ in range(timeout_s // 5):
            time.sleep(5)
            check = requests.get(
                f"{WM_BASE}/api/w/{WM_WORKSPACE}/jobs/completed/get/{job_id}",
                headers={"Authorization": f"Bearer {wm_token}"},
                timeout=10,
            )
            if check.status_code == 200:
                result = check.json()
                if result.get("type") == "CompletedJob":
                    success = result.get("success", False)
                    print(f"[Research] Job {job_id} complete — success={success}")
                    return bool(success)
        print(f"[Research] Timed out waiting for job {job_id}")
        return False
    except Exception as e:
        print(f"[Research] Dispatch/poll error: {e}")
        return False


# ── Research synopsis extraction ─────────────────────────────────────────────

def _extract_research_synopsis(content: str, max_chars: int = 600) -> str:
    """Strip metadata preamble (cost/source tables) from research_reports content.
    Returns first max_chars of narrative, stopping before the sources/tokens footer."""
    if not content:
        return ""
    # Metadata preamble ends at the first horizontal rule on its own line
    m = re.search(r'\n-{3,}\n', content)
    if m:
        narrative = content[m.end():].lstrip()
        # Stop before the next horizontal rule (sources/tokens footer)
        m2 = re.search(r'\n-{3,}\n', narrative)
        if m2:
            narrative = narrative[:m2.start()].rstrip()
        if narrative:
            suffix = "…" if len(narrative) > max_chars else ""
            return narrative[:max_chars].rstrip() + suffix
    # Fallback: skip table rows, metadata lines, and known section headings
    lines = content.split("\n")
    narrative_lines = []
    skipping = True
    for line in lines:
        stripped = line.strip()
        if skipping:
            if (stripped.startswith("|") or stripped.startswith("###") or
                    stripped.startswith("**Type:") or stripped == "---" or
                    stripped.startswith("✅") or
                    (stripped.startswith("#") and not stripped.startswith("##")) or
                    not stripped):
                continue
            skipping = False
        narrative_lines.append(line)
    narrative = "\n".join(narrative_lines).strip()
    if not narrative:
        return content[:max_chars].rstrip() + "…"
    suffix = "…" if len(narrative) > max_chars else ""
    return narrative[:max_chars].rstrip() + suffix


# ── Research seeding ─────────────────────────────────────────────────────────

def _get_seeded_overview(company: str, ticker: str, exa_key: str, xai_key: str) -> str:
    """When no research_reports entry exists, fetch a lightweight company overview via Exa + Grok.
    Returns a 150-word brief suitable for inclusion as context in the earnings analysis."""
    print(f"[Seed] No prior research for {ticker} — generating overview via Exa+Grok")
    text = _exa_search(
        f"{ticker} {company} business overview revenue model competitive position",
        exa_key, num_results=2, max_chars=2000,
    )
    if not text:
        return f"{company} ({ticker}) — no research on file and no overview sources retrieved."
    brief = _grok_brief(
        f"In 150 words, summarise the business of {company} ({ticker}): what it does, "
        f"its main revenue streams, key competitive position, and the main investment risks. "
        f"Be factual and concise — no preamble.\n\nSources:\n{text}",
        xai_key,
    )
    return brief or f"{company} ({ticker}) — overview not available."


# ── Grok synthesis ─────────────────────────────────────────────────────────────

GROK_INPUT_COST_PER_M = 1.25   # USD per 1M input tokens
GROK_OUTPUT_COST_PER_M = 2.50  # USD per 1M output tokens


def _grok_synthesise(system_prompt: str, user_prompt: str, xai_key: str,
                     max_tokens: int = 2500) -> dict:
    """Returns {"text": str, "input_tokens": int, "output_tokens": int}."""
    try:
        client = OpenAI(api_key=xai_key, base_url="https://api.x.ai/v1")
        resp = client.chat.completions.create(
            model="grok-4.3",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            reasoning_effort="high",
            max_tokens=max_tokens,
        )
        return {
            "text": resp.choices[0].message.content or "",
            "input_tokens": resp.usage.prompt_tokens if resp.usage else 0,
            "output_tokens": resp.usage.completion_tokens if resp.usage else 0,
            "model": "grok-4.3",
        }
    except Exception as e:
        print(f"[Grok] synthesis error: {e}")
        return {"text": f"[Synthesis unavailable: {e}]", "input_tokens": 0, "output_tokens": 0, "model": "grok-4.3"}


def _grok_brief(prompt: str, xai_key: str) -> str:
    """Lightweight single-prompt Grok call — returns bare text string."""
    result = _grok_synthesise("You are a concise equity research assistant.", prompt, xai_key, max_tokens=400)
    return result["text"]


# ── Telegram helper ────────────────────────────────────────────────────────────

def _send_telegram(bot_token: str, text: str, telegram_owner_id: str = ""):
    if not bot_token or bot_token.startswith("$"):
        print("[Telegram] no valid bot token — skipping")
        return
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    for chunk in [text[i:i+4000] for i in range(0, len(text), 4000)]:
        try:
            requests.post(url, json={"chat_id": telegram_owner_id, "text": chunk, "parse_mode": "Markdown"}, timeout=10)
        except Exception as e:
            print(f"[Telegram] send error: {e}")


# ── Email helper ───────────────────────────────────────────────────────────────

def _send_email(smtp_cfg: dict, subject: str, body: str, recipient_email: str = ""):
    if not smtp_cfg or not smtp_cfg.get("host"):
        return
    try:
        import smtplib
        from email.mime.text import MIMEText
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = smtp_cfg["username"]
        msg["To"] = recipient_email
        with smtplib.SMTP(smtp_cfg["host"], smtp_cfg["port"]) as s:
            s.starttls()
            s.login(smtp_cfg["username"], smtp_cfg["password"])
            s.send_message(msg)
    except Exception as e:
        print(f"[Email] send error: {e}")


# ── Pre-earnings flow ─────────────────────────────────────────────────────────

PRE_SYSTEM_PROMPT = """You are an equity analyst preparing a pre-earnings briefing for a portfolio manager who already holds this position.
Your job is to set expectations and define what to watch — not to repeat general business context.
Be specific about numbers. Be concise. Use bullet points, not paragraphs.
Never write general business background — focus entirely on the upcoming earnings event."""


def _run_pre_earnings(ticker: str, portfolio_db: dict, finnhub_key: str,
                      exa_key: str, xai_key: str, wm_token: str = "") -> dict:
    if not ticker:
        return {"error": "No ticker provided"}

    ctx = _get_portfolio_context(portfolio_db, ticker)
    company = ctx.get("company_name", ticker)
    print(f"[PreEarnings] {ticker} ({company})")

    sources_used = []

    # Research synopsis — use existing research_reports; if absent dispatch research_tool first
    research_synopsis = ""
    if not ctx.get("research_content") and wm_token:
        print(f"[PreEarnings] No research found for {ticker} — dispatching standard research job...")
        success = _dispatch_and_wait_research(ticker, wm_token)
        if success:
            ctx = _get_portfolio_context(portfolio_db, ticker)  # re-fetch after research completes

    if ctx.get("research_content"):
        research_synopsis = _extract_research_synopsis(ctx["research_content"])
        sources_used.append(f"Research report ({ctx.get('research_date', '?')}, {ctx.get('research_depth', '?')} depth)")
    else:
        print(f"[PreEarnings] Research dispatch failed or no token — using seeded overview")
        research_synopsis = _get_seeded_overview(company, ticker, exa_key, xai_key)
        sources_used.append("Seeded overview (research dispatch failed)")

    # Earnings date + estimates from Finnhub
    today_str = date.today().strftime("%Y-%m-%d")
    future_str = (date.today() + timedelta(days=30)).strftime("%Y-%m-%d")
    events = _finnhub_earnings(ticker, finnhub_key, today_str, future_str)
    earnings_date = None
    eps_estimate = None
    for ev in events:
        if ev.get("epsEstimate") is not None or ev.get("date"):
            earnings_date = ev.get("date")
            eps_estimate = ev.get("epsEstimate")
            break
    if events:
        sources_used.append("Finnhub earnings calendar")

    # Quarterly financial trend (yfinance)
    quarterly_table = _yfinance_quarterly(ticker)
    if quarterly_table:
        sources_used.append("yfinance quarterly financials")

    # Prior quarter 8-K from EDGAR (gives verbatim guidance from last earnings)
    print(f"[PreEarnings] Fetching prior 8-K from EDGAR...")
    prior_8k = _edgar_prior_8k(ticker)
    if prior_8k:
        sources_used.append("SEC EDGAR 8-K (prior quarter press release)")
    else:
        print(f"[PreEarnings] No prior 8-K found (may be HK/non-US ticker)")

    # Prior earnings call transcript via Exa
    q_label = f"Q earnings {date.today().year}"
    transcript_query = f"{company} earnings call transcript {q_label} site:seekingalpha.com OR site:fool.com"
    transcript_text = _exa_search(transcript_query, exa_key, num_results=1, max_chars=4000)
    if transcript_text:
        sources_used.append("Earnings call transcript (SeekingAlpha/Fool via Exa)")

    # Analyst preview articles via Exa
    preview_query = f"{ticker} {company} earnings preview expectations consensus {date.today().year}"
    preview_text = _exa_search(preview_query, exa_key, num_results=2, max_chars=2000)
    if preview_text:
        sources_used.append("Analyst preview articles (Exa)")

    # Build source text block
    source_parts = []
    if prior_8k:
        source_parts.append(f"=== PRIOR QUARTER EARNINGS PRESS RELEASE (EDGAR 8-K) ===\n{prior_8k[:3000]}")
    if transcript_text:
        source_parts.append(f"=== PRIOR EARNINGS CALL TRANSCRIPT ===\n{transcript_text}")
    if preview_text:
        source_parts.append(f"=== ANALYST PREVIEWS ===\n{preview_text}")
    source_block = "\n\n".join(source_parts) if source_parts else "No primary sources retrieved."

    # Build fundamentals context
    pe = ctx.get("pe_ratio")
    pb = ctx.get("pb_ratio")
    mc = ctx.get("market_cap_usd")
    target = ctx.get("analyst_target_usd")
    net_margin = ctx.get("net_margin")
    rev_growth = ctx.get("revenue_growth_yoy")
    fund_lines = []
    if pe:
        fund_lines.append(f"PE: {float(pe):.1f}x")
    if pb:
        fund_lines.append(f"PB: {float(pb):.1f}x")
    if mc:
        fund_lines.append(f"Mkt cap: ${float(mc)/1e9:.1f}B")
    if target:
        fund_lines.append(f"Analyst target: ${float(target):.2f}")
    if net_margin:
        fund_lines.append(f"Net margin: {float(net_margin)*100:.1f}%")
    if rev_growth:
        fund_lines.append(f"Rev growth YoY: {float(rev_growth)*100:.1f}%")
    fund_str = " | ".join(fund_lines) if fund_lines else "Fundamentals not available"

    user_prompt = f"""Ticker: {ticker} | Company: {company}
Upcoming earnings: {earnings_date or 'date TBC'}
Consensus: EPS est. {eps_estimate if eps_estimate is not None else 'n/a'}
Fundamentals: {fund_str}

Company overview (for context only — do not repeat in briefing):
{research_synopsis}

Quarterly financial trend (last 4Q):
{quarterly_table if quarterly_table else 'Not available'}

--- PRIMARY SOURCES ---
{source_block}

Write a pre-earnings briefing:
1. What analysts expect (EPS, revenue, key segments) — be specific about numbers
2. Historical financial trend: revenue/margin trajectory over last 4Q
3. Key guidance and commitments from last quarter's call/press release
4. What would constitute a positive surprise vs. a negative surprise
5. Valuation context: current multiples vs. historical norms for this sector
6. Top 3 specific items to watch when results are released"""

    print(f"[PreEarnings] Synthesising with Grok-4.3...")
    grok_result = _grok_synthesise(PRE_SYSTEM_PROMPT, user_prompt, xai_key)

    return {
        "ticker": ticker,
        "company": company,
        "analysis_type": "pre",
        "earnings_date": earnings_date,
        "eps_estimate": eps_estimate,
        "content": grok_result["text"],
        "input_tokens": grok_result["input_tokens"],
        "output_tokens": grok_result["output_tokens"],
        "synthesiser_model": grok_result.get("model", "grok-4.3"),
        "sources": sources_used,
        "research_synopsis": research_synopsis,
        "ctx": ctx,
    }


# ── Post-earnings flow ────────────────────────────────────────────────────────

POST_SYSTEM_PROMPT = """You are an equity analyst reviewing earnings for a portfolio manager who holds this position.
Focus on earnings quality, guidance changes, and what the results mean for the investment thesis.
End with a clear, justified recommendation: Buy / Accumulate / Hold / Reduce / Sell.
Be specific and direct. Do not hedge or waffle."""


def _parse_recommendation(text: str) -> Optional[str]:
    """Extract Buy/Accumulate/Hold/Reduce/Sell from synthesis text."""
    for word in ("Buy", "Accumulate", "Hold", "Reduce", "Sell"):
        if re.search(rf"\b{word}\b", text):
            return word
    return None


def _run_post_earnings(ticker: str, portfolio_db: dict, finnhub_key: str,
                       exa_key: str, xai_key: str, wm_token: str = "") -> dict:
    if not ticker:
        return {"error": "No ticker provided"}

    ctx = _get_portfolio_context(portfolio_db, ticker)
    company = ctx.get("company_name", ticker)
    print(f"[PostEarnings] {ticker} ({company})")

    sources_used = []

    # Research synopsis — use existing research_reports; if absent dispatch research_tool first
    research_synopsis = ""
    if not ctx.get("research_content") and wm_token:
        print(f"[PostEarnings] No research found for {ticker} — dispatching standard research job...")
        success = _dispatch_and_wait_research(ticker, wm_token)
        if success:
            ctx = _get_portfolio_context(portfolio_db, ticker)

    if ctx.get("research_content"):
        research_synopsis = _extract_research_synopsis(ctx["research_content"])
        sources_used.append(f"Research report ({ctx.get('research_date', '?')}, {ctx.get('research_depth', '?')} depth)")
    else:
        print(f"[PostEarnings] Research dispatch failed or no token — using seeded overview")
        research_synopsis = _get_seeded_overview(company, ticker, exa_key, xai_key)
        sources_used.append("Seeded overview (research dispatch failed)")

    # Actual results from Finnhub (last 3 days window)
    yesterday = (date.today() - timedelta(days=3)).strftime("%Y-%m-%d")
    today_str = date.today().strftime("%Y-%m-%d")
    events = _finnhub_earnings(ticker, finnhub_key, yesterday, today_str)
    eps_actual = None
    eps_estimate = None
    earnings_date = None
    for ev in events:
        if ev.get("epsActual") is not None:
            eps_actual = ev.get("epsActual")
            eps_estimate = ev.get("epsEstimate")
            earnings_date = ev.get("date")
            break
    if events:
        sources_used.append("Finnhub earnings calendar (actual results)")

    surprise_pct = None
    if eps_actual is not None and eps_estimate and eps_estimate != 0:
        surprise_pct = ((eps_actual - eps_estimate) / abs(eps_estimate)) * 100

    # Current 8-K press release from EDGAR (within last 5 days)
    print(f"[PostEarnings] Fetching latest 8-K from EDGAR...")
    press_release = _edgar_latest_8k(ticker, days_back=5)
    if press_release:
        sources_used.append("SEC EDGAR 8-K (earnings press release)")
    else:
        print(f"[PostEarnings] No recent 8-K — may be HK/non-US ticker, trying Exa fallback")
        pr_query = f"{company} earnings results press release {date.today().year} \"results announcement\""
        press_release = _exa_search(pr_query, exa_key, num_results=1, max_chars=5000)
        if press_release:
            sources_used.append("Earnings press release (IR/newswire via Exa)")

    # Current earnings call transcript via Exa
    transcript_query = (f"{company} Q earnings call transcript {date.today().year} "
                        f"site:seekingalpha.com OR site:fool.com OR site:rev.com")
    transcript_text = _exa_search(transcript_query, exa_key, num_results=1, max_chars=5000)
    if transcript_text:
        sources_used.append("Earnings call transcript (SeekingAlpha/Fool/Rev via Exa)")

    # Analyst reactions via Exa
    reaction_query = f"{ticker} {company} earnings reaction analyst price target upgrade downgrade {date.today().year}"
    reaction_text = _exa_search(reaction_query, exa_key, num_results=3, max_chars=2000)
    if reaction_text:
        sources_used.append("Analyst reactions / price target changes (Exa)")

    # Quarterly trend
    quarterly_table = _yfinance_quarterly(ticker)
    if quarterly_table:
        sources_used.append("yfinance quarterly financials")

    # Prior pre-earnings analysis for context
    prior_pre = ctx.get("prior_pre_analysis", {})
    pre_summary = prior_pre.get("content", "")[:1000] if prior_pre else ""

    # Thesis
    thesis_text = ctx.get("thesis", "No thesis on file.")

    # Build source block
    source_parts = []
    if press_release:
        source_parts.append(f"=== EARNINGS PRESS RELEASE (EDGAR 8-K / IR) ===\n{press_release[:4000]}")
    if transcript_text:
        source_parts.append(f"=== EARNINGS CALL TRANSCRIPT ===\n{transcript_text}")
    if reaction_text:
        source_parts.append(f"=== ANALYST REACTIONS ===\n{reaction_text}")
    source_block = "\n\n".join(source_parts) if source_parts else "No primary sources retrieved."

    eps_str = f"{eps_actual:.2f}" if eps_actual is not None else "n/a"
    est_str = f"{eps_estimate:.2f}" if eps_estimate is not None else "n/a"
    surprise_str = f"{surprise_pct:+.1f}%" if surprise_pct is not None else "n/a"

    user_prompt = f"""Ticker: {ticker} | Company: {company} | Report date: {earnings_date or today_str}
Results: EPS {eps_str} vs. est. {est_str} (surprise: {surprise_str})

Company overview (for context only — do not repeat in analysis):
{research_synopsis}

Quarterly financial trend (last 4Q):
{quarterly_table if quarterly_table else 'Not available'}

Portfolio thesis: {thesis_text}

Pre-earnings expectations (summary): {pre_summary if pre_summary else 'Not available'}

--- PRIMARY SOURCES ---
{source_block}

Provide:
1. Results summary: EPS beat/miss, revenue beat/miss, key segment performance
2. Guidance analysis: next quarter/year vs. prior guidance (raised/lowered/maintained)
3. Earnings quality: non-GAAP adjustments, one-time items, cash flow vs. net income
4. Management tone and key transcript highlights from Q&A
5. Thesis impact: does this reinforce or challenge the investment thesis?
6. Recommendation: [Buy / Accumulate / Hold / Reduce / Sell] + 2-3 sentence rationale"""

    print(f"[PostEarnings] Synthesising with Grok-4.3...")
    grok_result = _grok_synthesise(POST_SYSTEM_PROMPT, user_prompt, xai_key)
    recommendation = _parse_recommendation(grok_result["text"])

    return {
        "ticker": ticker,
        "company": company,
        "analysis_type": "post",
        "earnings_date": earnings_date,
        "eps_estimate": eps_estimate,
        "eps_actual": eps_actual,
        "surprise_pct": surprise_pct,
        "recommendation": recommendation,
        "content": grok_result["text"],
        "input_tokens": grok_result["input_tokens"],
        "output_tokens": grok_result["output_tokens"],
        "synthesiser_model": grok_result.get("model", "grok-4.3"),
        "sources": sources_used,
        "research_synopsis": research_synopsis,
        "ctx": ctx,
    }


# ── Main entry point ──────────────────────────────────────────────────────────

def main(
    ticker: str = "",
    analysis_type: str = "pre",
    portfolio_db: postgresql = {},
    gmail_smtp: smtp = {},
    xai_key: str = "$var:u/admin/xai_key",
    exa_key: str = "$var:u/admin/exa_key",
    finnhub_key: str = "$var:u/admin/finnhub_key",
    telegram_bot_token: str = "$var:u/admin/telegram_bot_token",
    wm_token: str = "$var:u/admin/wm_token",
    telegram_owner_id: str = "",
    recipient_email: str = "",
) -> dict:
    ticker = ticker.strip().upper()
    if not ticker:
        return {"error": "ticker is required"}

    t0 = time.time()
    if analysis_type == "pre":
        result = _run_pre_earnings(ticker, portfolio_db, finnhub_key, exa_key, xai_key, wm_token)
    else:
        result = _run_post_earnings(ticker, portfolio_db, finnhub_key, exa_key, xai_key, wm_token)

    if "error" in result:
        return result

    content = result["content"]
    label = "Pre-Earnings Briefing" if analysis_type == "pre" else "Post-Earnings Analysis"
    today = date.today().strftime("%Y-%m-%d")
    earnings_date = result.get("earnings_date") or "TBC"
    company = result.get("company", ticker)

    # ── Portfolio position section ──────────────────────────────────────────────
    ctx = result.get("ctx", {})
    shares = ctx.get("shares")
    latest_price = ctx.get("latest_price")
    position_usd = ctx.get("position_usd")
    total_usd = ctx.get("total_portfolio_usd")
    currency = ctx.get("currency", "USD")

    portfolio_lines = []
    if shares is not None and latest_price is not None:
        portfolio_lines.append(f"Shares: {shares:,.0f} @ {currency} {latest_price:,.2f}")
    if position_usd is not None:
        portfolio_lines.append(f"Position value: USD {position_usd:,.0f}")
    if position_usd is not None and total_usd:
        pct = (position_usd / total_usd) * 100
        portfolio_lines.append(f"Portfolio weight: {pct:.1f}% of USD {total_usd:,.0f} total")
    portfolio_section = "\n".join(portfolio_lines) if portfolio_lines else "Position data not available"

    # ── Research synopsis section ───────────────────────────────────────────────
    synopsis = result.get("research_synopsis", "")
    research_section = synopsis if synopsis else "No research on file."

    # ── Cost calculation ────────────────────────────────────────────────────────
    in_tok = result.get("input_tokens", 0)
    out_tok = result.get("output_tokens", 0)
    synthesiser_model = result.get("synthesiser_model", "grok-4.3")
    # Deepseek fallback rates (~$0.27/1M in, ~$1.10/1M out) differ from Grok
    DEEPSEEK_INPUT_COST_PER_M = 0.27
    DEEPSEEK_OUTPUT_COST_PER_M = 1.10
    if "deepseek" in synthesiser_model.lower():
        cost_usd = (in_tok / 1_000_000 * DEEPSEEK_INPUT_COST_PER_M) + (out_tok / 1_000_000 * DEEPSEEK_OUTPUT_COST_PER_M)
    else:
        cost_usd = (in_tok / 1_000_000 * GROK_INPUT_COST_PER_M) + (out_tok / 1_000_000 * GROK_OUTPUT_COST_PER_M)

    # ── Sources footer ──────────────────────────────────────────────────────────
    sources = result.get("sources", [])
    sources_str = "\n".join(f"  - {s}" for s in sources) if sources else "  - (none recorded)"

    # ── Assemble full document ──────────────────────────────────────────────────
    date_line = f"**Date written:** {today}"
    if analysis_type == "pre":
        date_line += f" | **Expected earnings:** {earnings_date}"
    else:
        date_line += f" | **Earnings date:** {earnings_date}"

    rec_str = f"\n\n**Recommendation: {result['recommendation']}**" if result.get("recommendation") else ""

    full_doc = f"""# {ticker} {label}
{date_line}

## Portfolio Position — {company}
{portfolio_section}

## Company Overview
{research_section}

---

{content}{rec_str}

---

**Sources used ({len(sources)}):**
{sources_str}
**Model:** {synthesiser_model} | **Tokens:** {in_tok:,} in / {out_tok:,} out | **Est. cost:** USD {cost_usd:.4f}
"""

    # Write to file
    os.makedirs(RESEARCH_DIR, exist_ok=True)
    filename = f"{today}_{ticker}_{analysis_type}.md"
    file_path = os.path.join(RESEARCH_DIR, filename)
    with open(file_path, "w") as f:
        f.write(full_doc)
    print(f"[EarningsAnalysis] Written to {file_path}")

    # Save to DB (store full_doc so the file and DB are in sync)
    _save_analysis(
        portfolio_db=portfolio_db,
        ticker=ticker,
        analysis_type=analysis_type,
        earnings_date=result.get("earnings_date"),
        eps_estimate=result.get("eps_estimate"),
        eps_actual=result.get("eps_actual"),
        revenue_estimate=None,
        revenue_actual=None,
        surprise_pct=result.get("surprise_pct"),
        recommendation=result.get("recommendation"),
        content=full_doc,
        file_path=file_path,
    )

    # Telegram notification
    tg_header = f"📊 *{ticker} {label}*\n_{date_line}_"
    if result.get("recommendation"):
        tg_header += f"\n\n*Recommendation: {result['recommendation']}*"
    tg_footer = f"\n\n_Sources: {len(sources)} | Tokens: {in_tok+out_tok:,} | Cost: USD {cost_usd:.4f}_"
    tg_body = content[:3200]
    tg_msg = f"{tg_header}\n\n{tg_body}{tg_footer}"
    _send_telegram(telegram_bot_token, tg_msg, telegram_owner_id)

    # Email — full document
    _send_email(gmail_smtp, f"{ticker} {label} — {today}", full_doc, recipient_email)

    elapsed = time.time() - t0
    print(f"[EarningsAnalysis] Done in {elapsed:.1f}s — {in_tok+out_tok:,} tokens, USD {cost_usd:.4f}")
    return {
        "ticker": ticker,
        "analysis_type": analysis_type,
        "earnings_date": earnings_date,
        "file_path": file_path,
        "recommendation": result.get("recommendation"),
        "content_length": len(full_doc),
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "cost_usd": round(cost_usd, 4),
        "sources_count": len(sources),
        "elapsed_s": round(elapsed, 1),
    }
