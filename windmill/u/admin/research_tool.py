# Requirements:
# psycopg2-binary>=2.9
# feedparser>=6.0
# requests>=2.31
# yfinance>=0.2.40
# openai>=1.0.0
# beautifulsoup4>=4.12

import re
import json
import time
import smtplib
import urllib.parse
from datetime import date, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import TypedDict

import feedparser
import requests
import yfinance as yf
import psycopg2
from bs4 import BeautifulSoup
from openai import OpenAI


class postgresql(TypedDict):
    host: str
    port: int
    user: str
    password: str
    dbname: str


SYSTEM_PROMPTS = {
    "stock": (
        "You are a professional equity research analyst. Analyse the question using the sources "
        "provided. Structure your response as:\n"
        "1. Business Overview — what the company does, key revenue drivers, business model\n"
        "2. Financial Position — use DB metrics and financial statements (P/E, P/B, ROE, revenue trend, margins, debt)\n"
        "3. Competitive Position — moat, market share, key competitors\n"
        "4. Catalysts — near-term upside drivers (product launches, contract wins, macro tailwinds)\n"
        "5. Risks — execution risk, competitive threats, macro headwinds, valuation risk\n"
        "Use inline citations [N] referencing source numbers. Be factual and direct."
    ),
    "strategy": (
        "You are a strategy consultant and industry analyst. Analyse the question using the sources "
        "provided. Structure your response as:\n"
        "1. Market Structure — size, growth, key players, concentration\n"
        "2. Competitive Dynamics — basis of competition, switching costs, barriers to entry\n"
        "3. Moat Analysis — which players have durable advantage and why\n"
        "4. Strategic Positioning — winners and losers in the current competitive landscape\n"
        "5. Outlook — how the dynamics are likely to shift over 3-5 years\n"
        "Use inline citations [N] referencing source numbers. Be factual and direct."
    ),
    "macro": (
        "You are a macroeconomist and sovereign analyst. Analyse the question using the sources "
        "provided. Structure your response as:\n"
        "1. Proximate Drivers — immediate causes of the trend or event\n"
        "2. Structural Factors — underlying economic or political dynamics\n"
        "3. Policy Response — central bank, fiscal, or regulatory actions taken or expected\n"
        "4. Asset Transmission — how this affects equities, rates, FX, commodities\n"
        "5. Outlook — base case trajectory and key downside risks\n"
        "Use inline citations [N] referencing source numbers. Be factual and direct."
    ),
    "project": (
        "You are a project finance banker and credit analyst. Analyse the question using the sources "
        "provided. Structure your response as:\n"
        "1. Project Overview — technology, capacity, location, sponsor, stage\n"
        "2. Revenue & Offtake — contract structure, counterparty quality, price exposure\n"
        "3. Construction Risk — contractor, EPC structure, completion risk mitigants\n"
        "4. Credit Considerations — leverage, DSCR expectations, lender requirements\n"
        "5. Key Risks — permitting, grid connection, fuel supply, force majeure, political risk\n"
        "Use inline citations [N] referencing source numbers. Be factual and direct."
    ),
}

TYPE_DIRS = {"stock": "stocks", "strategy": "strategy", "macro": "macro", "project": "projects"}

EDGAR_HEADERS = {"User-Agent": "research-tool/1.0 straitsagent@gmail.com"}


def _slugify(text, max_len=50):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:max_len].rstrip("-")


def _strip_html(text):
    return re.sub(r"<[^>]+>", "", text or "").strip()


def _format_fin_table(df):
    """Format a yfinance financial DataFrame as a markdown table with scaled numbers."""
    try:
        lines = []
        col_headers = [str(c)[:10] for c in df.columns]
        lines.append("| Metric | " + " | ".join(col_headers) + " |")
        lines.append("|" + "---|" * (len(col_headers) + 1))
        for idx, row in df.iterrows():
            vals = []
            for v in row:
                try:
                    fv = float(v)
                    if fv != fv:  # NaN
                        vals.append("N/A")
                    elif abs(fv) >= 1e9:
                        vals.append(f"${fv/1e9:.2f}B")
                    elif abs(fv) >= 1e6:
                        vals.append(f"${fv/1e6:.0f}M")
                    else:
                        vals.append(f"${fv:,.0f}")
                except (TypeError, ValueError):
                    vals.append("N/A")
            lines.append(f"| {idx} | " + " | ".join(vals) + " |")
        return "\n".join(lines)
    except Exception as e:
        return f"(table formatting error: {e})"


def _fetch_yfinance_financials(ticker):
    """Annual 3-year income statement, balance sheet, cash flow + financial health metrics."""
    try:
        t = yf.Ticker(ticker)
        blocks = []
        data = {}

        # Annual income statement
        try:
            ais = t.income_stmt
            if ais is not None and not ais.empty:
                key_rows = ["Total Revenue", "Gross Profit", "Operating Income", "EBITDA",
                            "Net Income", "Basic EPS"]
                rows = [r for r in key_rows if r in ais.index]
                if rows:
                    blocks.append("### Income Statement (Annual, 3yr)\n"
                                  + _format_fin_table(ais.loc[rows, ais.columns[:3]]))
        except Exception as e:
            print(f"[yfinance-fin] income stmt: {e}")

        # Annual balance sheet
        try:
            bs = t.balance_sheet
            if bs is not None and not bs.empty:
                key_rows = [
                    "Total Assets", "Total Liabilities Net Minority Interest",
                    "Stockholders Equity", "Total Debt", "Cash And Cash Equivalents",
                    "Current Assets", "Current Liabilities",
                ]
                rows = [r for r in key_rows if r in bs.index]
                if rows:
                    blocks.append("### Balance Sheet (Annual, 3yr)\n"
                                  + _format_fin_table(bs.loc[rows, bs.columns[:3]]))
        except Exception as e:
            print(f"[yfinance-fin] balance sheet: {e}")

        # Annual cash flow
        try:
            cf = t.cashflow
            if cf is not None and not cf.empty:
                key_rows = ["Operating Cash Flow", "Free Cash Flow", "Capital Expenditure"]
                rows = [r for r in key_rows if r in cf.index]
                if rows:
                    blocks.append("### Cash Flow (Annual, 3yr)\n"
                                  + _format_fin_table(cf.loc[rows, cf.columns[:3]]))
        except Exception as e:
            print(f"[yfinance-fin] cash flow: {e}")

        # Financial Health Metrics (computed from annual data)
        try:
            inc = t.income_stmt
            bs  = t.balance_sheet
            n   = min(
                3,
                len(bs.columns)  if bs  is not None and not bs.empty  else 0,
                len(inc.columns) if inc is not None and not inc.empty else 0,
            )
            if n > 0:
                yr_hdrs = [str(c)[:10] for c in bs.columns[:n]]

                def _g(df, row, i):
                    try:
                        if df is not None and row in df.index and len(df.columns) > i:
                            v = df.iloc[df.index.get_loc(row), i]
                            f = float(v)
                            return None if f != f else f
                    except Exception:
                        pass
                    return None

                def _fh(v, pct=False, x=False):
                    if v is None:
                        return "N/A"
                    if pct:
                        return f"{v:.1f}%"
                    if x:
                        return f"{v:.2f}x"
                    av = abs(v)
                    if av >= 1e9:
                        return f"${v/1e9:.2f}B"
                    if av >= 1e6:
                        return f"${v/1e6:.0f}M"
                    return f"${v:.0f}"

                hdr  = "| Metric | " + " | ".join(yr_hdrs) + " |"
                sep  = "|" + "---|" * (n + 1)
                hrows = ["### Financial Health Metrics", "", hdr, sep]

                def _hr(label, vals, **kw):
                    hrows.append("| " + label + " | "
                                 + " | ".join(_fh(v, **kw) for v in vals) + " |")

                debt  = [_g(bs,  "Total Debt",                  i) for i in range(n)]
                cash  = [_g(bs,  "Cash And Cash Equivalents",   i) for i in range(n)]
                equity= [_g(bs,  "Stockholders Equity",         i) for i in range(n)]
                ca    = [_g(bs,  "Current Assets",              i) for i in range(n)]
                cl    = [_g(bs,  "Current Liabilities",         i) for i in range(n)]
                ta    = [_g(bs,  "Total Assets",                i) for i in range(n)]
                rev   = [_g(inc, "Total Revenue",               i) for i in range(n)]
                ni    = [_g(inc, "Net Income",                  i) for i in range(n)]
                eb    = [_g(inc, "EBITDA",                      i) for i in range(n)]

                nd   = [d - c       if d is not None and c is not None else None
                        for d, c in zip(debt, cash)]
                nd_e = [x / y       if x is not None and y else None
                        for x, y in zip(nd, eb)]
                gear = [d / (d + e) if d is not None and e is not None and (d + e) else None
                        for d, e in zip(debt, equity)]
                crr  = [a / l       if a is not None and l else None
                        for a, l in zip(ca, cl)]
                nm   = [n_i / r     if n_i is not None and r else None
                        for n_i, r in zip(ni, rev)]
                ato  = [r / t_a     if r is not None and t_a else None
                        for r, t_a in zip(rev, ta)]
                em   = [t_a / e     if t_a is not None and e else None
                        for t_a, e in zip(ta, equity)]
                roe  = [a * b * c   if a is not None and b is not None and c is not None else None
                        for a, b, c in zip(nm, ato, em)]

                # ── Raw data dict for DB persistence ─────────────────────────
                gp  = [_g(inc, "Gross Profit",     i) for i in range(n)]
                oi  = [_g(inc, "Operating Income",  i) for i in range(n)]
                eps = [_g(inc, "Basic EPS",         i) for i in range(n)]
                tl  = [_g(bs,  "Total Liabilities Net Minority Interest", i) for i in range(n)]
                try:
                    _cf2  = t.cashflow
                    n2    = min(n, len(_cf2.columns) if _cf2 is not None and not _cf2.empty else 0)
                    op_cf = [_g(_cf2, "Operating Cash Flow", i) for i in range(n2)]
                    fcf   = [_g(_cf2, "Free Cash Flow",      i) for i in range(n2)]
                    capex = [_g(_cf2, "Capital Expenditure", i) for i in range(n2)]
                except Exception:
                    op_cf = fcf = capex = []
                _ii = lambda v: int(v) if v is not None else None
                data.update({
                    "fiscal_years": yr_hdrs,
                    "income": {
                        "total_revenue":    [_ii(v) for v in rev],
                        "gross_profit":     [_ii(v) for v in gp],
                        "operating_income": [_ii(v) for v in oi],
                        "ebitda":           [_ii(v) for v in eb],
                        "net_income":       [_ii(v) for v in ni],
                        "basic_eps":        eps,
                    },
                    "balance_sheet": {
                        "total_assets":        [_ii(v) for v in ta],
                        "total_liabilities":   [_ii(v) for v in tl],
                        "stockholders_equity": [_ii(v) for v in equity],
                        "total_debt":          [_ii(v) for v in debt],
                        "cash":                [_ii(v) for v in cash],
                        "current_assets":      [_ii(v) for v in ca],
                        "current_liabilities": [_ii(v) for v in cl],
                    },
                    "cashflow": {
                        "operating_cf": [_ii(v) for v in op_cf],
                        "free_cf":      [_ii(v) for v in fcf],
                        "capex":        [_ii(v) for v in capex],
                    },
                    "health": {
                        "net_debt":          [_ii(v) for v in nd],
                        "net_debt_ebitda":   nd_e,
                        "gearing":           gear,
                        "current_ratio":     crr,
                        "net_margin":        nm,
                        "asset_turnover":    ato,
                        "equity_multiplier": em,
                        "roe_dupont":        roe,
                    },
                })

                _hr("Net Debt",                nd)
                _hr("Net Debt / EBITDA",       nd_e,                                        x=True)
                _hr("Gearing D/(D+E)",         gear,                                        x=True)
                _hr("Current Ratio",           crr,                                         x=True)
                _hr("Net Margin (DuPont)",     [v * 100 if v is not None else None for v in nm],  pct=True)
                _hr("Asset Turnover (DuPont)", ato,                                         x=True)
                _hr("Equity Mult. (DuPont)",   em,                                          x=True)
                _hr("DuPont ROE",              [v * 100 if v is not None else None for v in roe], pct=True)

                blocks.append("\n".join(hrows))
        except Exception as e:
            print(f"[yfinance-fin] health metrics: {e}")

        if blocks:
            print(f"[yfinance-fin] {len(blocks)} block(s) for {ticker}")
            return f"## Financial Statements: {ticker}\n\n" + "\n\n".join(blocks), data
        print(f"[yfinance-fin] no data for {ticker}")
        return "", {}
    except Exception as e:
        print(f"[yfinance-fin] WARNING: {e}")
        return "", {}


def _fetch_company_overview(ticker):
    """Company profile: sector, industry, employees, website, description."""
    try:
        info = yf.Ticker(ticker).info
        lines = [f"## Company Profile: {ticker}", ""]
        meta = []
        for label, key in [("Sector", "sector"), ("Industry", "industry"),
                            ("Country", "country"), ("Exchange", "exchange")]:
            v = info.get(key)
            if v:
                meta.append(f"**{label}:** {v}")
        emp = info.get("fullTimeEmployees")
        if emp:
            meta.append(f"**Employees:** {int(emp):,}")
        web = info.get("website")
        if web:
            meta.append(f"**Website:** {web}")
        if meta:
            lines.append(" | ".join(meta))
        full_desc = info.get("longBusinessSummary") or ""
        if full_desc:
            desc = full_desc[:400]
            lines.append(f"\n{desc}{'...' if len(full_desc) > 400 else ''}")
        if len(lines) <= 2:
            return "", {}
        data = {
            "sector":      info.get("sector"),
            "industry":    info.get("industry"),
            "country":     info.get("country"),
            "exchange":    info.get("exchange"),
            "employees":   int(emp) if emp else None,
            "website":     web,
            "description": full_desc[:1000] if full_desc else None,
        }
        print(f"[overview] profile fetched for {ticker}")
        return "\n".join(lines), data
    except Exception as e:
        print(f"[overview] WARNING: {e}")
        return "", {}


def _fetch_yfinance_valuation(ticker):
    """Comprehensive valuation multiples, short interest, and analyst consensus."""
    try:
        info = yf.Ticker(ticker).info
        lines = [f"## Valuation: {ticker}", ""]

        price = info.get("currentPrice")
        fcf   = info.get("freeCashflow")
        shrs  = info.get("sharesOutstanding")
        p_fcf_val = None
        p_fcf = "N/A"
        if price and fcf and shrs and shrs > 0 and fcf > 0:
            p_fcf_val = float(price) / (float(fcf) / float(shrs))
            p_fcf = f"{p_fcf_val:.1f}x"

        def _fx(v, d=1):
            return f"{float(v):.{d}f}x" if v is not None else "N/A"
        def _f(v, d=2):
            return f"${float(v):.{d}f}" if v is not None else "N/A"
        def _fv(v):
            return float(v) if v is not None else None

        multiples = [
            ("Trailing P/E",    _fx(info.get("trailingPE"))),
            ("Forward P/E",     _fx(info.get("forwardPE"))),
            ("P/B",             _fx(info.get("priceToBook"))),
            ("P/S (TTM)",       _fx(info.get("priceToSalesTrailing12Months"))),
            ("EV/EBITDA",       _fx(info.get("enterpriseToEbitda"))),
            ("EV/Revenue",      _fx(info.get("enterpriseToRevenue"))),
            ("P/FCF",           p_fcf),
            ("PEG Ratio",       _fx(info.get("pegRatio"), 2)),
            ("Beta",            _fx(info.get("beta"), 2)),
            ("Trailing EPS",    _f(info.get("trailingEps"))),
            ("Forward EPS",     _f(info.get("forwardEps"))),
        ]
        lines.append("| Metric | Value |")
        lines.append("|---|---|")
        for label, val in multiples:
            lines.append(f"| {label} | {val} |")

        hi = info.get("fiftyTwoWeekHigh")
        lo = info.get("fiftyTwoWeekLow")
        if hi and lo:
            lines.append(f"| 52-wk Range | ${float(lo):.2f} – ${float(hi):.2f} |")

        tgt = info.get("targetMeanPrice")
        n_a = info.get("numberOfAnalystOpinions")
        rec = info.get("recommendationMean")
        if tgt:
            lines.append(f"| Analyst Target | ${float(tgt):.2f} ({n_a or '?'} analysts) |")
        if rec:
            lines.append(f"| Rec. Score | {float(rec):.1f}/5 |")

        short_pct   = info.get("shortPercentOfFloat")
        short_ratio = info.get("shortRatio")
        if short_pct is not None:
            lines.append(f"\n**Short Interest:** {float(short_pct)*100:.1f}% of float")
            if short_ratio:
                lines.append(f" | **Days to Cover:** {float(short_ratio):.1f}")

        data = {
            "trailing_pe":      _fv(info.get("trailingPE")),
            "forward_pe":       _fv(info.get("forwardPE")),
            "pb":               _fv(info.get("priceToBook")),
            "ps_ttm":           _fv(info.get("priceToSalesTrailing12Months")),
            "ev_ebitda":        _fv(info.get("enterpriseToEbitda")),
            "ev_revenue":       _fv(info.get("enterpriseToRevenue")),
            "p_fcf":            p_fcf_val,
            "peg":              _fv(info.get("pegRatio")),
            "beta":             _fv(info.get("beta")),
            "trailing_eps":     _fv(info.get("trailingEps")),
            "forward_eps":      _fv(info.get("forwardEps")),
            "fifty_two_wk_high": _fv(hi),
            "fifty_two_wk_low":  _fv(lo),
            "short_pct_float":  _fv(short_pct) * 100 if short_pct is not None else None,
            "short_ratio":      _fv(short_ratio),
            "analyst_target":   _fv(tgt),
            "analyst_rec_mean": _fv(rec),
            "analyst_count":    int(n_a) if n_a else None,
        }
        print(f"[valuation] fetched for {ticker}")
        return "\n".join(lines), data
    except Exception as e:
        print(f"[valuation] WARNING: {e}")
        return "", {}


def _fetch_ownership(ticker):
    """Institutional ownership summary and top holders."""
    try:
        t = yf.Ticker(ticker)
        lines = [f"## Ownership: {ticker}", ""]
        insider_pct = None
        institutional_pct = None
        holders = []

        try:
            mh = t.major_holders
            if mh is not None and not mh.empty:
                for _, row in mh.iterrows():
                    pct_val = row.iloc[0]
                    label   = str(row.iloc[1]).lower()
                    try:
                        pct_f = float(pct_val) * 100
                        lines.append(f"**{row.iloc[1]}:** {pct_f:.1f}%")
                        if "insider" in label:
                            insider_pct = pct_f
                        elif "institution" in label:
                            institutional_pct = pct_f
                    except (TypeError, ValueError):
                        lines.append(f"**{row.iloc[1]}:** {pct_val}")
        except Exception:
            pass

        try:
            ih = t.institutional_holders
            if ih is not None and not ih.empty:
                lines.append("\n### Top Institutional Holders")
                lines.append("| Holder | Shares | % Held | Reported |")
                lines.append("|---|---|---|---|")
                for _, row in ih.head(10).iterrows():
                    holder    = str(row.get("Holder",        row.iloc[0] if len(row) > 0 else ""))
                    shares    = row.get("Shares",            row.iloc[1] if len(row) > 1 else None)
                    pct       = row.get("% Out",             row.iloc[2] if len(row) > 2 else None)
                    reported  = row.get("Date Reported",     row.iloc[3] if len(row) > 3 else "")
                    s_fmt     = f"{int(shares):,}"      if shares  is not None else "N/A"
                    p_fmt     = f"{float(pct)*100:.2f}%" if pct    is not None else "N/A"
                    d_fmt     = str(reported)[:10]      if reported else "N/A"
                    lines.append(f"| {holder} | {s_fmt} | {p_fmt} | {d_fmt} |")
                    holders.append({
                        "name":          holder,
                        "shares":        int(shares) if shares is not None else None,
                        "pct_held":      float(pct) * 100 if pct is not None else None,
                        "reported_date": str(reported)[:10] if reported else None,
                    })
        except Exception as e:
            print(f"[ownership] institutional holders: {e}")

        if len(lines) <= 2:
            return "", {}
        data = {
            "insider_pct":       insider_pct,
            "institutional_pct": institutional_pct,
            "holders":           holders,
        }
        print(f"[ownership] fetched for {ticker}")
        return "\n".join(lines), data
    except Exception as e:
        print(f"[ownership] WARNING: {e}")
        return "", {}


def _fetch_insider_transactions(ticker):
    """Recent insider buy/sell transactions."""
    try:
        t = yf.Ticker(ticker)
        insiders = t.insider_transactions
        if insiders is None or insiders.empty:
            return "", {}
        lines = [f"## Insider Transactions: {ticker} (Last 6 months)", ""]
        lines.append("| Date | Insider | Title | Transaction | Shares | Value (USD) |")
        lines.append("|---|---|---|---|---|---|")
        transactions = []
        for _, row in insiders.head(10).iterrows():
            date_s = str(row.get("Start Date", row.iloc[0] if len(row) > 0 else ""))[:10]
            name   = str(row.get("Insider",    row.iloc[1] if len(row) > 1 else ""))
            title  = str(row.get("Position", ""))
            txn    = str(row.get("Transaction", ""))
            shares = row.get("Shares", None)
            value  = row.get("Value",  None)
            s_ok   = shares is not None and str(shares) != "nan"
            v_ok   = value  is not None and str(value)  != "nan"
            s_fmt  = f"{int(shares):,}"          if s_ok else "N/A"
            v_fmt  = f"${float(value)/1e6:.2f}M" if v_ok else "N/A"
            lines.append(f"| {date_s} | {name} | {title} | {txn} | {s_fmt} | {v_fmt} |")
            transactions.append({
                "insider_name":     name,
                "title":            title,
                "transaction_date": date_s if date_s else None,
                "txn_type":         txn,
                "shares":           int(shares) if s_ok else None,
                "value_usd":        int(float(value)) if v_ok else None,
            })
        data = {"transactions": transactions}
        print(f"[insiders] fetched for {ticker}")
        return "\n".join(lines), data
    except Exception as e:
        print(f"[insiders] WARNING: {e}")
        return "", {}


def _fetch_earnings_calendar(ticker):
    """Next earnings date + EPS/revenue consensus + recent EPS surprises."""
    try:
        t = yf.Ticker(ticker)
        lines = [f"## Earnings Calendar: {ticker}", ""]
        earn_date = eps_est = rev_lo = rev_hi = None
        surprises = []

        # Next earnings
        try:
            cal = t.calendar
            if cal is not None:
                parts = []
                if isinstance(cal, dict):
                    ed = cal.get("Earnings Date")
                    earn_date = ed[0] if isinstance(ed, list) and ed else ed
                    eps_est   = cal.get("EPS Estimate")
                    rev_lo    = cal.get("Revenue Low")
                    rev_hi    = cal.get("Revenue High")
                else:
                    earn_date = cal.iloc[0, 0] if not cal.empty else None
                    eps_est = rev_lo = rev_hi = None
                if earn_date:
                    parts.append(f"**Next earnings:** {str(earn_date)[:10]}")
                if eps_est:
                    parts.append(f"**EPS estimate:** ${float(eps_est):.2f}")
                if rev_lo and rev_hi:
                    parts.append(f"**Revenue range:** ${float(rev_lo)/1e9:.1f}B – ${float(rev_hi)/1e9:.1f}B")
                if parts:
                    lines.append(" | ".join(parts))
        except Exception as e:
            print(f"[calendar] next earnings: {e}")

        # Recent EPS surprises
        try:
            ed_df = t.earnings_dates
            if ed_df is not None and not ed_df.empty:
                actual_col = next((c for c in ed_df.columns if "actual" in str(c).lower()), None)
                est_col    = next((c for c in ed_df.columns if "estimate" in str(c).lower()), None)
                if actual_col:
                    recent = ed_df[ed_df[actual_col].notna()].head(4)
                    if not recent.empty:
                        lines.append("\n### Recent EPS Surprises")
                        lines.append("| Period | EPS Estimate | EPS Actual | Surprise |")
                        lines.append("|---|---|---|---|")
                        for idx, row in recent.iterrows():
                            period   = str(idx)[:10]
                            est      = row.get(est_col)    if est_col    else None
                            act      = row.get(actual_col)
                            surp_pct = None
                            surprise = ""
                            if est is not None and act is not None:
                                try:
                                    e_f, a_f = float(est), float(act)
                                    if e_f != 0:
                                        surp_pct = (a_f - e_f) / abs(e_f) * 100
                                        surprise = f"{surp_pct:+.1f}%"
                                except Exception:
                                    pass
                            e_fmt = f"${float(est):.2f}" if est is not None else "N/A"
                            a_fmt = f"${float(act):.2f}" if act is not None else "N/A"
                            lines.append(f"| {period} | {e_fmt} | {a_fmt} | {surprise} |")
                            surprises.append({
                                "period_date":  period,
                                "eps_estimate": float(est) if est is not None else None,
                                "eps_actual":   float(act) if act is not None else None,
                                "surprise_pct": surp_pct,
                            })
        except Exception as e:
            print(f"[calendar] earnings dates: {e}")

        if len(lines) <= 2:
            return "", {}
        data = {
            "earnings_date": str(earn_date)[:10] if earn_date else None,
            "eps_estimate":  float(eps_est) if eps_est is not None else None,
            "revenue_low":   int(float(rev_lo)) if rev_lo else None,
            "revenue_high":  int(float(rev_hi)) if rev_hi else None,
            "surprises":     surprises,
        }
        print(f"[calendar] fetched for {ticker}")
        return "\n".join(lines), data
    except Exception as e:
        print(f"[calendar] WARNING: {e}")
        return "", {}


def _fetch_mdna_synopsis(ticker, deepseek_key):
    """150-200 word MD&A synopsis from EDGAR 10-Q/10-K. US tickers only."""
    try:
        if not ticker or ticker.endswith(".HK"):
            return "", {}

        # CIK lookup
        tickers_resp = requests.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers=EDGAR_HEADERS, timeout=15,
        )
        tickers_resp.raise_for_status()
        ticker_map = {v["ticker"]: str(v["cik_str"]) for v in tickers_resp.json().values()}
        cik = ticker_map.get(ticker.upper())
        if not cik:
            return "", {}

        cik_padded = cik.zfill(10)
        subs = requests.get(
            f"https://data.sec.gov/submissions/CIK{cik_padded}.json",
            headers=EDGAR_HEADERS, timeout=15,
        ).json()
        filings     = subs.get("filings", {}).get("recent", {})
        forms_list  = filings.get("form", [])
        accessions  = filings.get("accessionNumber", [])
        primary_docs = filings.get("primaryDocument", [])
        filing_dates = filings.get("filingDate", [])

        extract      = ""
        source_label = ""
        for target in ("10-Q", "10-K"):
            for i, form in enumerate(forms_list):
                if form != target:
                    continue
                acc_clean = accessions[i].replace("-", "")
                doc_url   = (f"https://www.sec.gov/Archives/edgar/data/{cik}/"
                             f"{acc_clean}/{primary_docs[i]}")
                try:
                    r = requests.get(doc_url, headers=EDGAR_HEADERS, timeout=30)
                    if r.status_code != 200:
                        break
                    soup = BeautifulSoup(r.text, "html.parser")
                    for tag in soup(["script", "style", "table"]):
                        tag.decompose()
                    text = re.sub(r"\n{3,}", "\n\n",
                                  soup.get_text(separator="\n", strip=True))
                    mda  = re.search(
                        r"(management.{0,10}s\s+discussion|item\s+2[\s\.:\-]+management)",
                        text, re.IGNORECASE,
                    )
                    extract      = text[mda.start():mda.start() + 5000] if mda else text[:3000]
                    source_label = f"{form} ({filing_dates[i]})"
                    time.sleep(0.3)
                except Exception as e:
                    print(f"[mdna] fetch {form}: {e}")
                break
            if extract:
                break

        if not extract:
            return "", {}

        client = OpenAI(api_key=deepseek_key, base_url="https://api.deepseek.com")
        resp   = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "You are a financial analyst summarising SEC filings."},
                {"role": "user", "content": (
                    "Summarise the following MD&A section in 150–200 words, "
                    "focusing on revenue drivers, margin trends, and forward guidance."
                    f"\n\n{extract}"
                )},
            ],
            max_tokens=300,
            temperature=0.3,
        )
        synopsis = resp.choices[0].message.content.strip()
        print(f"[mdna] synopsis generated for {ticker} from {source_label}")
        return f"## MD&A Synopsis ({source_label})\n\n{synopsis}", {}
    except Exception as e:
        print(f"[mdna] WARNING: {e}")
        return "", {}


def _fetch_management(ticker):
    """Key executives from yfinance companyOfficers."""
    try:
        info     = yf.Ticker(ticker).info
        officers = info.get("companyOfficers", [])
        if not officers:
            return "", {}
        lines = [f"## Key Management: {ticker}", ""]
        lines.append("| Name | Title | Age | Pay (USD) |")
        lines.append("|---|---|---|---|")
        officers_data = []
        for o in officers[:10]:
            name  = o.get("name", "N/A")
            title = o.get("title", "N/A")
            age   = o.get("age")
            pay   = o.get("totalPay")
            p_fmt = f"${pay/1e6:.1f}M" if pay else "N/A"
            lines.append(f"| {name} | {title} | {age or 'N/A'} | {p_fmt} |")
            officers_data.append({
                "name":          name,
                "title":         title,
                "age":           int(age) if age else None,
                "total_pay_usd": int(pay) if pay else None,
            })
        data = {"officers": officers_data}
        print(f"[management] {len(officers)} officers for {ticker}")
        return "\n".join(lines), data
    except Exception as e:
        print(f"[management] WARNING: {e}")
        return "", {}


def _fetch_board_of_directors(ticker):
    """Board of directors from SEC EDGAR DEF 14A proxy statement. US tickers only."""
    if not ticker or ticker.endswith(".HK"):
        return "", {}
    try:
        tickers_resp = requests.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers=EDGAR_HEADERS, timeout=15,
        )
        tickers_resp.raise_for_status()
        ticker_map = {v["ticker"]: str(v["cik_str"]) for v in tickers_resp.json().values()}
        cik = ticker_map.get(ticker.upper())
        if not cik:
            print(f"[board] CIK not found for {ticker}")
            return "", {}

        cik_padded = cik.zfill(10)
        subs = requests.get(
            f"https://data.sec.gov/submissions/CIK{cik_padded}.json",
            headers=EDGAR_HEADERS, timeout=15,
        ).json()
        filings      = subs.get("filings", {}).get("recent", {})
        forms_list   = filings.get("form", [])
        accessions   = filings.get("accessionNumber", [])
        primary_docs = filings.get("primaryDocument", [])
        filing_dates = filings.get("filingDate", [])

        for i, form in enumerate(forms_list):
            if form != "DEF 14A":
                continue
            acc_clean = accessions[i].replace("-", "")
            doc_url   = (f"https://www.sec.gov/Archives/edgar/data/{cik}/"
                         f"{acc_clean}/{primary_docs[i]}")
            try:
                r = requests.get(doc_url, headers=EDGAR_HEADERS, timeout=30)
                if r.status_code != 200:
                    break
                soup = BeautifulSoup(r.text, "html.parser")

                lines = [f"## Board of Directors: {ticker} (DEF 14A, {filing_dates[i]})", ""]
                lines.append("| Name | Role | Independence |")
                lines.append("|---|---|---|")

                directors_found = 0
                directors_data = []
                for table in soup.find_all("table"):
                    t_text = table.get_text(separator="|", strip=True).lower()
                    if not ("director" in t_text or "independent" in t_text):
                        continue
                    for row in table.find_all("tr"):
                        cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
                        if len(cells) < 2 or not cells[0] or len(cells[0]) < 4:
                            continue
                        name = cells[0]
                        role = cells[1] if len(cells) > 1 else ""
                        indep = next((c for c in cells if "independent" in c.lower()), "")
                        if any(kw in role.lower() or kw in t_text
                               for kw in ("director", "chair", "president", "ceo", "cfo")):
                            lines.append(f"| {name} | {role} | {indep} |")
                            directors_data.append({"name": name, "role": role, "independence": indep})
                            directors_found += 1
                            if directors_found >= 15:
                                break
                    if directors_found > 0:
                        break

                # Fallback: regex on plain text
                if directors_found == 0:
                    text = soup.get_text(separator="\n", strip=True)
                    brd  = re.search(r"(board\s+of\s+directors|director\s+nominees)",
                                     text, re.IGNORECASE)
                    section = text[brd.start():brd.start() + 3000] if brd else text[:3000]
                    for name in re.findall(
                        r"([A-Z][a-z]+(?: [A-Z][a-z.]+){1,3})\s*(?:\n|,|–|-)\s*(?:Independent\s+)?Director",
                        section,
                    )[:12]:
                        lines.append(f"| {name} | Director | |")
                        directors_data.append({"name": name, "role": "Director", "independence": ""})
                        directors_found += 1

                if directors_found == 0:
                    print(f"[board] no directors parsed for {ticker}")
                    return "", {}
                time.sleep(0.3)
                print(f"[board] {directors_found} directors for {ticker}")
                return "\n".join(lines), {"directors": directors_data}
            except Exception as e:
                print(f"[board] parse error: {e}")
                return "", {}

        print(f"[board] no DEF 14A found for {ticker}")
        return "", {}
    except Exception as e:
        print(f"[board] WARNING: {e}")
        return "", {}


def _fetch_competitors(ticker, finnhub_key):
    """Peer comparison table via Finnhub /stock/peers + yfinance. US tickers only."""
    if not ticker or ticker.endswith(".HK") or not finnhub_key:
        return "", {}
    try:
        resp = requests.get(
            f"https://finnhub.io/api/v1/stock/peers?symbol={ticker}&token={finnhub_key}",
            timeout=10,
        )
        if resp.status_code != 200:
            return "", {}
        peers = [p for p in resp.json() if p and p.upper() != ticker.upper()][:5]
        if not peers:
            return "", {}

        def _sc(v):
            if v is None:
                return "N/A"
            f = float(v)
            if f >= 1e12: return f"${f/1e12:.1f}T"
            if f >= 1e9:  return f"${f/1e9:.1f}B"
            if f >= 1e6:  return f"${f/1e6:.0f}M"
            return f"${f:,.0f}"

        lines = [f"## Competitive Landscape: {ticker}", ""]
        lines.append("| Company | Ticker | Mkt Cap | Revenue (TTM) | EBITDA | P/E | P/B |")
        lines.append("|---|---|---|---|---|---|---|")
        peers_data = []
        for peer in peers:
            try:
                pi   = yf.Ticker(peer).info
                name = pi.get("shortName") or pi.get("longName") or peer
                mc_v = pi.get("marketCap")
                rv_v = pi.get("totalRevenue")
                eb_v = pi.get("ebitda")
                pe_v = pi.get("trailingPE")
                pb_v = pi.get("priceToBook")
                mc   = _sc(mc_v)
                rev  = _sc(rv_v)
                eb   = _sc(eb_v)
                pe   = f"{float(pe_v):.1f}x" if pe_v else "N/A"
                pb   = f"{float(pb_v):.1f}x" if pb_v else "N/A"
                lines.append(f"| {name} | {peer} | {mc} | {rev} | {eb} | {pe} | {pb} |")
                peers_data.append({
                    "peer_ticker":   peer,
                    "peer_name":     name,
                    "market_cap_usd": int(float(mc_v)) if mc_v else None,
                    "revenue_ttm":   int(float(rv_v)) if rv_v else None,
                    "ebitda":        int(float(eb_v)) if eb_v else None,
                    "trailing_pe":   float(pe_v) if pe_v else None,
                    "pb":            float(pb_v) if pb_v else None,
                })
                time.sleep(0.2)
            except Exception as ep:
                print(f"[competitors] peer {peer}: {ep}")

        data = {"peers": peers_data}
        print(f"[competitors] {len(peers)} peers for {ticker}")
        return "\n".join(lines), data
    except Exception as e:
        print(f"[competitors] WARNING: {e}")
        return "", {}


def _fetch_article_text(url, max_chars=2000):
    """Attempt full article text retrieval via requests + BeautifulSoup. Returns text or None."""
    if not url:
        return None
    skip_domains = ("youtube.com", "seekingalpha.com", "bloomberg.com", "ft.com",
                    "wsj.com", "barrons.com", "reuters.com/plus", "perplexity.ai")
    if any(d in url for d in skip_domains):
        return None
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        }
        resp = requests.get(url, headers=headers, timeout=10, allow_redirects=True)
        if resp.status_code != 200:
            return None
        if "text/html" not in resp.headers.get("content-type", ""):
            return None
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "iframe"]):
            tag.decompose()
        article = soup.find("article")
        if article:
            text = article.get_text(separator=" ", strip=True)
        else:
            paras = soup.find_all("p")
            text = " ".join(p.get_text(strip=True) for p in paras)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:max_chars] if len(text) >= 150 else None
    except Exception:
        return None


def _fetch_edgar_filings(ticker, forms=None):
    """Fetch recent SEC EDGAR filings for US tickers. forms=None → all (10-K, 10-Q, 8-K); forms=['8-K'] → 8-K only."""
    if not ticker or ticker.endswith(".HK"):
        print(f"[EDGAR] Skipped — {'HK ticker' if ticker else 'no ticker'}")
        return []
    try:
        # Resolve ticker → CIK
        tickers_resp = requests.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers=EDGAR_HEADERS, timeout=15,
        )
        tickers_resp.raise_for_status()
        ticker_map = {v["ticker"]: str(v["cik_str"]) for v in tickers_resp.json().values()}
        cik = ticker_map.get(ticker.upper())
        if not cik:
            print(f"[EDGAR] Ticker {ticker} not found in EDGAR ticker map")
            return []

        cik_padded = cik.zfill(10)
        subs_resp = requests.get(
            f"https://data.sec.gov/submissions/CIK{cik_padded}.json",
            headers=EDGAR_HEADERS, timeout=15,
        )
        subs_resp.raise_for_status()
        subs = subs_resp.json()
        company_name = subs.get("name", ticker)
        filings = subs.get("filings", {}).get("recent", {})

        forms = filings.get("form", [])
        accessions = filings.get("accessionNumber", [])
        primary_docs = filings.get("primaryDocument", [])
        filing_dates = filings.get("filingDate", [])

        # Targets: 1x 10-K, 1x 10-Q, 3x 8-K (restricted by forms arg)
        all_targets = {"10-K": 1, "10-Q": 1, "8-K": 3}
        targets = {f: n for f, n in all_targets.items() if forms is None or f in forms}
        counts = {}
        results = []

        for i, form in enumerate(forms):
            if form not in targets:
                continue
            if counts.get(form, 0) >= targets[form]:
                continue
            # Stop early once all targets met
            if all(counts.get(f, 0) >= n for f, n in targets.items()):
                break

            accession_clean = accessions[i].replace("-", "")
            primary_doc = primary_docs[i]
            filing_date = filing_dates[i]
            doc_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_clean}/{primary_doc}"

            try:
                doc_resp = requests.get(doc_url, headers=EDGAR_HEADERS, timeout=30)
                if doc_resp.status_code != 200:
                    continue
                soup = BeautifulSoup(doc_resp.text, "html.parser")
                for tag in soup(["script", "style", "table"]):
                    tag.decompose()
                text = soup.get_text(separator="\n", strip=True)
                text = re.sub(r"\n{3,}", "\n\n", text)

                if form in ("10-K", "10-Q"):
                    mda_match = re.search(
                        r"(management.{0,10}s\s+discussion|item\s+2[\s\.:\-]+management)",
                        text, re.IGNORECASE,
                    )
                    if mda_match:
                        extract = text[mda_match.start():mda_match.start() + 5000]
                    else:
                        extract = text[:5000]
                else:  # 8-K
                    extract = text[:3000]

                src_key = f"edgar_{form.lower().replace('-', '')}"
                results.append({
                    "source": src_key,
                    "title": f"{company_name} {form} ({filing_date})",
                    "url": doc_url,
                    "snippet": extract,
                    "date": filing_date,
                    "content_level": "full_text",
                })
                counts[form] = counts.get(form, 0) + 1
                print(f"[EDGAR] {form} ({filing_date}) — {len(extract)} chars")
                time.sleep(0.5)  # Respect SEC rate limits
            except Exception as e:
                print(f"[EDGAR] WARNING: failed to fetch {form} ({filing_dates[i]}) — {e}")

        print(f"[EDGAR] {len(results)} filing(s) retrieved for {ticker} (CIK {cik})")
        return results
    except Exception as e:
        print(f"[EDGAR] WARNING: {e}")
        return []


def _fetch_google_news(query, max_items=5):
    url = ("https://news.google.com/rss/search?q="
           + urllib.parse.quote(query)
           + "&hl=en-US&gl=US&ceid=US:en")
    try:
        feed = feedparser.parse(url)
        items = []
        for e in feed.entries[:max_items]:
            snippet = _strip_html(getattr(e, "summary", "") or "")[:300]
            items.append({
                "source": "google_news",
                "title": e.get("title", ""),
                "url": e.get("link", ""),
                "snippet": snippet,
                "date": e.get("published", ""),
            })
        return items
    except Exception as ex:
        print(f"[GoogleNews] WARNING: '{query[:40]}' — {ex}")
        return []


def _fetch_perplexity_batch(queries_batch, perplexity_key, max_results=5):
    headers = {
        "Authorization": f"Bearer {perplexity_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "query": queries_batch,
        "max_results": max_results,
        "search_context_size": "high",
        "search_recency_filter": "month",
    }
    try:
        resp = requests.post(
            "https://api.perplexity.ai/search",
            json=payload,
            headers=headers,
            timeout=45,
        )
        resp.raise_for_status()
        data = resp.json()
        items = []
        raw = data.get("results", [])
        if isinstance(raw, list):
            for r in raw:
                items.append({
                    "source": "perplexity",
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "snippet": r.get("snippet", ""),
                    "date": r.get("date") or r.get("last_updated", ""),
                })
        elif isinstance(raw, dict):
            for v in raw.values():
                for r in (v if isinstance(v, list) else []):
                    items.append({
                        "source": "perplexity",
                        "title": r.get("title", ""),
                        "url": r.get("url", ""),
                        "snippet": r.get("snippet", ""),
                        "date": r.get("date") or r.get("last_updated", ""),
                    })
        print(f"[Perplexity] {len(items)} results for {len(queries_batch)} queries")
        return items
    except Exception as e:
        print(f"[Perplexity] WARNING: {e}")
        return []


def _fetch_exa_query(query, exa_key, max_results=5):
    start_date = (date.today() - timedelta(days=30)).strftime("%Y-%m-%dT00:00:00.000Z")
    try:
        resp = requests.post(
            "https://api.exa.ai/search",
            headers={"x-api-key": exa_key, "Content-Type": "application/json"},
            json={
                "query": query,
                "numResults": max_results,
                "useAutoprompt": True,
                "type": "auto",
                "startPublishedDate": start_date,
                "contents": {"text": {"maxCharacters": 400}},
            },
            timeout=30,
        )
        resp.raise_for_status()
        items = []
        for r in resp.json().get("results", []):
            items.append({
                "source": "exa",
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": (r.get("text") or "")[:400],
                "date": r.get("publishedDate", ""),
            })
        return items
    except Exception as e:
        print(f"[Exa] WARNING: '{query[:40]}' — {e}")
        return []


def _fetch_serper_news(queries, serper_key, max_results=10):
    """Fetch news from Serper.dev /news endpoint. Returns normalised list."""
    items = []
    query_str = " ".join(queries) if isinstance(queries, list) else queries
    try:
        resp = requests.post(
            "https://google.serper.dev/news",
            headers={"X-API-KEY": serper_key, "Content-Type": "application/json"},
            json={"q": query_str, "num": max_results},
            timeout=15,
        )
        resp.raise_for_status()
        for r in resp.json().get("news", []):
            items.append({
                "source": "serper",
                "title": r.get("title", ""),
                "url": r.get("link", ""),
                "snippet": r.get("snippet", ""),
                "date": r.get("date", ""),
            })
        print(f"[Serper] {len(items)} news results")
    except Exception as e:
        print(f"[Serper] WARNING: {e}")
    return items


def _parse_brave_relative_date(rel_str: str) -> str:
    """Convert Brave relative date strings to ISO format. '1d'→yesterday, '3w'→3 weeks ago, '2mo'→60 days ago."""
    try:
        m = re.match(r'^(\d+)(d|w|mo)$', rel_str.strip())
        if not m:
            return ""
        n, unit = int(m.group(1)), m.group(2)
        if unit == 'd':
            return (date.today() - timedelta(days=n)).isoformat()
        elif unit == 'w':
            return (date.today() - timedelta(weeks=n)).isoformat()
        elif unit == 'mo':
            return (date.today() - timedelta(days=n * 30)).isoformat()
    except Exception:
        pass
    return ""


def _fetch_brave_news(queries, brave_key, max_results=10):
    """Fetch news from Brave Search API with freshness=pm (past month). Returns normalised list."""
    items = []
    query_str = " ".join(queries) if isinstance(queries, list) else queries
    try:
        resp = requests.get(
            "https://api.search.brave.com/res/v1/news/search",
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "X-Subscription-Token": brave_key,
            },
            params={"q": query_str, "count": max_results, "freshness": "pm",
                    "extra_snippets": "true"},
            timeout=15,
        )
        resp.raise_for_status()
        for r in resp.json().get("results", []):
            age = r.get("age", "")
            pub_date = _parse_brave_relative_date(age) if age else r.get("published", "")
            extra = r.get("extra_snippets", [])
            snippet = r.get("description", "") or (extra[0] if extra else "")
            items.append({
                "source": "brave",
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": snippet,
                "date": pub_date,
            })
        print(f"[Brave] {len(items)} news results")
    except Exception as e:
        print(f"[Brave] WARNING: {e}")
    return items


def _fetch_tavily(queries, tavily_key, max_results=10):
    """Fetch from Tavily finance search. time_range=month enforces freshness (Hard Rule 14 workaround — Tavily has no pub dates)."""
    items = []
    query_str = " ".join(queries) if isinstance(queries, list) else queries
    try:
        resp = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": tavily_key,
                "query": query_str,
                "topic": "finance",
                "time_range": "month",
                "max_results": max_results,
                "include_raw_content": "markdown",
            },
            timeout=30,
        )
        resp.raise_for_status()
        for r in resp.json().get("results", []):
            content = r.get("content", "") or r.get("raw_content", "")
            items.append({
                "source": "tavily",
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": content[:400] if content else "",
                "date": "freshness:month",  # Tavily returns no dates — sentinel per plan
            })
        print(f"[Tavily] {len(items)} results")
    except Exception as e:
        print(f"[Tavily] WARNING: {e}")
    return items


def _fetch_fred_data(fred_key):
    """Fetch key macro series from FRED API. Returns normalised list."""
    SERIES = {
        "CPIAUCSL": "CPI (Urban Consumers, SA)",
        "GDP": "US GDP",
        "UNRATE": "US Unemployment Rate",
        "DGS10": "10-Year Treasury Rate",
        "FEDFUNDS": "Federal Funds Rate",
        "DEXSIUS": "SGD/USD Exchange Rate",
        "DEXUSEU": "USD/EUR Exchange Rate",
    }
    items = []
    for series_id, label in SERIES.items():
        try:
            resp = requests.get(
                "https://api.stlouisfed.org/fred/series/observations",
                params={
                    "series_id": series_id,
                    "api_key": fred_key,
                    "file_type": "json",
                    "sort_order": "desc",
                    "limit": 3,
                },
                timeout=15,
            )
            resp.raise_for_status()
            obs = resp.json().get("observations", [])
            if obs:
                latest = obs[0]
                val = latest.get("value", ".")
                date_val = latest.get("date", "")
                items.append({
                    "source": "fred",
                    "title": f"FRED: {label} ({series_id})",
                    "url": f"https://fred.stlouisfed.org/series/{series_id}",
                    "snippet": f"{label}: {val} (as of {date_val})",
                    "date": date_val,
                    "content_level": "full_text",
                })
                print(f"[FRED] {series_id}: {val} ({date_val})")
        except Exception as e:
            print(f"[FRED] WARNING: {series_id} — {e}")
    print(f"[FRED] {len(items)} series retrieved")
    return items


def _iterative_gap_analysis(sources, question, research_type, deepseek_key):
    """Analyse Round 1 sources with Deepseek to identify up to 3 coverage gaps.
    Returns list of {description, query, source_type} dicts.
    source_type is one of: 'news', 'sec', 'analyst', 'market_data'.
    """
    if not deepseek_key or not sources:
        return []
    try:
        source_summary = "\n".join(
            f"- [{i+1}] {s.get('source','?')} | {s.get('title','?')}"
            for i, s in enumerate(sources[:30])
        )
        prompt = (
            f"You found {len(sources)} sources about '{question}' (research_type={research_type}).\n"
            f"Review their titles and sources. Identify up to 3 specific coverage gaps.\n"
            f"For each gap, specify the single best query AND the best source type to address it.\n"
            f"Return JSON only: {{\"gaps\": [{{\"description\": str, \"query\": str, "
            f"\"source_type\": \"news|sec|analyst|market_data\"}}]}}\n"
            f"If coverage is sufficient, return {{\"gaps\": []}}.\n\n"
            f"Sources:\n{source_summary}"
        )
        resp = requests.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {deepseek_key}", "Content-Type": "application/json"},
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 400,
                "temperature": 0.2,
            },
            timeout=30,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"].strip()
        m = re.search(r'\{.*\}', content, re.DOTALL)
        if m:
            data = json.loads(m.group())
            gaps = data.get("gaps", [])
            print(f"[gap analysis] Found {len(gaps)} gaps: {[g.get('description','?') for g in gaps]}")
            return gaps[:3]
    except Exception as e:
        print(f"[gap analysis] WARNING: {e}")
    return []


def _read_structured_stock_data(ticker, portfolio_db):
    """Read all 14 structured DB tables for ticker; return (sections_dict, staleness).

    staleness: 'absent' if no valuation row exists, 'stale' if >3 days old, 'fresh' otherwise.
    sections_dict keys: overview, fin, val, own, ins, earn, mgmt, comp.
    Returns ({}, 'absent') on any DB error or missing inputs.
    """
    if not portfolio_db or not ticker:
        return {}, "absent"
    try:
        conn = psycopg2.connect(
            host=portfolio_db["host"], port=portfolio_db["port"],
            dbname=portfolio_db["dbname"], user=portfolio_db["user"],
            password=portfolio_db["password"],
        )
        sections = {}
        with conn.cursor() as cur:
            cur.execute(
                "SELECT fetched_date FROM valuation_snapshots WHERE ticker = %s "
                "ORDER BY fetched_date DESC LIMIT 1",
                (ticker,)
            )
            row = cur.fetchone()
            if row is None:
                conn.close()
                return {}, "absent"
            age = (date.today() - row[0]).days
            staleness = "stale" if age > 3 else "fresh"
            stale_note = f"> Data as of {row[0]}\n\n" if staleness == "stale" else ""

            # company_profiles → overview
            cur.execute(
                "SELECT sector, industry, country, exchange, employees, website, description "
                "FROM company_profiles WHERE ticker = %s",
                (ticker,)
            )
            cp = cur.fetchone()
            if cp:
                sector, industry, country, exchange, employees, website, description = cp
                meta = []
                for label, val in [("Sector", sector), ("Industry", industry),
                                   ("Country", country), ("Exchange", exchange)]:
                    if val:
                        meta.append(f"**{label}:** {val}")
                if employees:
                    meta.append(f"**Employees:** {int(employees):,}")
                if website:
                    meta.append(f"**Website:** {website}")
                lines = [f"## Company Profile: {ticker}", ""]
                if meta:
                    lines.append(" | ".join(meta))
                if description:
                    lines.append(f"\n{description[:400]}{'...' if len(description) > 400 else ''}")
                sections["overview"] = stale_note + "\n".join(lines)

            # income + balance + cashflow + health → fin
            cur.execute(
                "SELECT fiscal_year_end, total_revenue, gross_profit, operating_income, "
                "ebitda, net_income, basic_eps FROM income_statements "
                "WHERE ticker = %s ORDER BY fiscal_year_end DESC LIMIT 3",
                (ticker,)
            )
            inc_rows = cur.fetchall()
            cur.execute(
                "SELECT fiscal_year_end, total_assets, total_liabilities, stockholders_equity, "
                "total_debt, cash FROM balance_sheets "
                "WHERE ticker = %s ORDER BY fiscal_year_end DESC LIMIT 3",
                (ticker,)
            )
            bs_rows = cur.fetchall()
            cur.execute(
                "SELECT fiscal_year_end, operating_cf, free_cf, capex FROM cashflow_statements "
                "WHERE ticker = %s ORDER BY fiscal_year_end DESC LIMIT 3",
                (ticker,)
            )
            cf_rows = cur.fetchall()
            cur.execute(
                "SELECT fiscal_year_end, net_debt, net_debt_ebitda, gearing, current_ratio, "
                "net_margin, roe_dupont FROM financial_health_metrics "
                "WHERE ticker = %s ORDER BY fiscal_year_end DESC LIMIT 3",
                (ticker,)
            )
            hlth_rows = cur.fetchall()
            if inc_rows:
                def _fmb(v):
                    return f"${float(v)/1e9:.2f}B" if v is not None else "N/A"
                def _fv2(v, d=2):
                    return f"{float(v):.{d}f}" if v is not None else "N/A"
                fin_lines = [f"## Financials: {ticker}", ""]
                fin_lines.append("### Income Statement (USD, last 3 FY)")
                fin_lines.append("| Metric | " + " | ".join(str(r[0])[:10] for r in inc_rows) + " |")
                fin_lines.append("|" + "---|" * (len(inc_rows) + 1))
                for label, idx, use_bil in [("Revenue", 1, True), ("Gross Profit", 2, True),
                                             ("Op. Income", 3, True), ("EBITDA", 4, True),
                                             ("Net Income", 5, True), ("EPS", 6, False)]:
                    vals = " | ".join(_fmb(r[idx]) if use_bil else _fv2(r[idx]) for r in inc_rows)
                    fin_lines.append(f"| {label} | {vals} |")
                if bs_rows:
                    fin_lines.append("\n### Balance Sheet")
                    fin_lines.append("| Metric | " + " | ".join(str(r[0])[:10] for r in bs_rows) + " |")
                    fin_lines.append("|" + "---|" * (len(bs_rows) + 1))
                    for label, idx in [("Total Assets", 1), ("Total Liabilities", 2),
                                        ("Equity", 3), ("Total Debt", 4), ("Cash", 5)]:
                        fin_lines.append(f"| {label} | " + " | ".join(_fmb(r[idx]) for r in bs_rows) + " |")
                if cf_rows:
                    fin_lines.append("\n### Cash Flow")
                    fin_lines.append("| Metric | " + " | ".join(str(r[0])[:10] for r in cf_rows) + " |")
                    fin_lines.append("|" + "---|" * (len(cf_rows) + 1))
                    for label, idx in [("Operating CF", 1), ("Free CF", 2), ("CapEx", 3)]:
                        fin_lines.append(f"| {label} | " + " | ".join(_fmb(r[idx]) for r in cf_rows) + " |")
                if hlth_rows:
                    fin_lines.append("\n### Financial Health")
                    fin_lines.append("| Metric | " + " | ".join(str(r[0])[:10] for r in hlth_rows) + " |")
                    fin_lines.append("|" + "---|" * (len(hlth_rows) + 1))
                    for label, idx, use_bil in [("Net Debt", 1, True), ("Net Debt/EBITDA", 2, False),
                                                 ("Gearing", 3, False), ("Current Ratio", 4, False),
                                                 ("Net Margin %", 5, False), ("ROE (DuPont)", 6, False)]:
                        vals = " | ".join(_fmb(r[idx]) if use_bil else _fv2(r[idx]) for r in hlth_rows)
                        fin_lines.append(f"| {label} | {vals} |")
                sections["fin"] = stale_note + "\n".join(fin_lines)

            # valuation_snapshots → val
            cur.execute(
                "SELECT trailing_pe, forward_pe, pb, ps_ttm, ev_ebitda, ev_revenue, p_fcf, "
                "peg, beta, trailing_eps, forward_eps, fifty_two_wk_high, fifty_two_wk_low, "
                "short_pct_float, short_ratio, analyst_target, analyst_rec_mean, analyst_count "
                "FROM valuation_snapshots WHERE ticker = %s ORDER BY fetched_date DESC LIMIT 1",
                (ticker,)
            )
            vrow = cur.fetchone()
            if vrow:
                def _vfx(v, d=1):
                    return f"{float(v):.{d}f}x" if v is not None else "N/A"
                def _vfd(v, d=2):
                    return f"${float(v):.{d}f}" if v is not None else "N/A"
                (t_pe, f_pe, pb, ps, ev_eb, ev_rev, p_fcf, peg, beta,
                 t_eps, f_eps, hi, lo, s_pct, s_ratio, tgt, rec, n_a) = vrow
                val_lines = [f"## Valuation: {ticker}", "",
                             "| Metric | Value |", "|---|---|"]
                for label, val in [
                    ("Trailing P/E", _vfx(t_pe)), ("Forward P/E", _vfx(f_pe)),
                    ("P/B", _vfx(pb)), ("P/S (TTM)", _vfx(ps)),
                    ("EV/EBITDA", _vfx(ev_eb)), ("EV/Revenue", _vfx(ev_rev)),
                    ("P/FCF", _vfx(p_fcf)), ("PEG Ratio", _vfx(peg, 2)),
                    ("Beta", _vfx(beta, 2)), ("Trailing EPS", _vfd(t_eps)),
                    ("Forward EPS", _vfd(f_eps)),
                ]:
                    val_lines.append(f"| {label} | {val} |")
                if hi and lo:
                    val_lines.append(f"| 52-wk Range | ${float(lo):.2f} – ${float(hi):.2f} |")
                if tgt:
                    val_lines.append(f"| Analyst Target | ${float(tgt):.2f} ({n_a or '?'} analysts) |")
                if rec:
                    val_lines.append(f"| Rec. Score | {float(rec):.1f}/5 |")
                if s_pct is not None:
                    val_lines.append(f"\n**Short Interest:** {float(s_pct):.1f}% of float")
                    if s_ratio:
                        val_lines.append(f" | **Days to Cover:** {float(s_ratio):.1f}")
                sections["val"] = stale_note + "\n".join(val_lines)

            # ownership_snapshots + institutional_holders → own
            cur.execute(
                "SELECT insider_pct, institutional_pct FROM ownership_snapshots "
                "WHERE ticker = %s ORDER BY fetched_date DESC LIMIT 1",
                (ticker,)
            )
            os_row = cur.fetchone()
            cur.execute(
                "SELECT holder_name, shares, pct_held FROM institutional_holders "
                "WHERE ticker = %s ORDER BY fetched_date DESC, shares DESC NULLS LAST LIMIT 10",
                (ticker,)
            )
            ih_rows = cur.fetchall()
            if os_row or ih_rows:
                own_lines = [f"## Ownership: {ticker}", ""]
                if os_row:
                    ins_p, inst_p = os_row
                    if ins_p is not None:
                        own_lines.append(f"**Insider Ownership:** {float(ins_p):.1f}%")
                    if inst_p is not None:
                        own_lines.append(f"**Institutional Ownership:** {float(inst_p):.1f}%")
                if ih_rows:
                    own_lines += ["\n### Top Institutional Holders",
                                  "| Holder | Shares | % Held |", "|---|---|---|"]
                    for name, shares, pct in ih_rows:
                        own_lines.append(
                            f"| {name or 'N/A'} | "
                            f"{int(shares):,}" if shares else "N/A" +
                            f" | {float(pct):.2f}% |" if pct else " | N/A |"
                        )
                sections["own"] = stale_note + "\n".join(own_lines)

            # insider_transactions → ins
            cur.execute(
                "SELECT insider_name, title, transaction_date, txn_type, shares, value_usd "
                "FROM insider_transactions WHERE ticker = %s "
                "ORDER BY transaction_date DESC LIMIT 15",
                (ticker,)
            )
            ins_rows = cur.fetchall()
            if ins_rows:
                ins_lines = [f"## Insider Transactions: {ticker}", "",
                             "| Name | Title | Date | Type | Shares | Value |", "|---|---|---|---|---|---|"]
                for name, title, txn_date, txn_type, shares, value in ins_rows:
                    ins_lines.append(
                        f"| {name or 'N/A'} | {title or 'N/A'} | {txn_date} | {txn_type or 'N/A'} "
                        f"| {int(shares):,}" if shares else "| N/A" +
                        f" | ${float(value):,.0f} |" if value else " | N/A |"
                    )
                sections["ins"] = stale_note + "\n".join(ins_lines)

            # next_earnings + earnings_surprises → earn
            cur.execute(
                "SELECT earnings_date, eps_estimate, revenue_low, revenue_high FROM next_earnings "
                "WHERE ticker = %s",
                (ticker,)
            )
            ne_row = cur.fetchone()
            cur.execute(
                "SELECT period_date, eps_estimate, eps_actual, surprise_pct FROM earnings_surprises "
                "WHERE ticker = %s ORDER BY period_date DESC LIMIT 4",
                (ticker,)
            )
            es_rows = cur.fetchall()
            if ne_row or es_rows:
                earn_lines = [f"## Earnings Calendar: {ticker}", ""]
                if ne_row:
                    e_date, e_eps, rev_lo, rev_hi = ne_row
                    if e_date:
                        earn_lines.append(f"**Next Earnings:** {e_date}")
                        if e_eps is not None:
                            earn_lines.append(f" | EPS Estimate: ${float(e_eps):.2f}")
                        if rev_lo and rev_hi:
                            earn_lines.append(
                                f" | Revenue Guide: ${float(rev_lo)/1e9:.2f}B–${float(rev_hi)/1e9:.2f}B"
                            )
                if es_rows:
                    earn_lines += ["\n### Historical Surprises",
                                   "| Quarter | EPS Est | EPS Actual | Surprise |", "|---|---|---|---|"]
                    for period, est, actual, surp in es_rows:
                        earn_lines.append(
                            f"| {period} "
                            f"| {'$'+f'{float(est):.2f}' if est is not None else 'N/A'} "
                            f"| {'$'+f'{float(actual):.2f}' if actual is not None else 'N/A'} "
                            f"| {f'{float(surp):+.1f}%' if surp is not None else 'N/A'} |"
                        )
                sections["earn"] = stale_note + "\n".join(earn_lines)

            # key_management → mgmt
            cur.execute(
                "SELECT name, title, age, total_pay_usd FROM key_management "
                "WHERE ticker = %s ORDER BY name",
                (ticker,)
            )
            km_rows = cur.fetchall()
            if km_rows:
                mgmt_lines = [f"## Key Management: {ticker}", "",
                              "| Name | Title | Age | Total Pay |", "|---|---|---|---|"]
                for name, title, age, pay in km_rows:
                    mgmt_lines.append(
                        f"| {name or 'N/A'} | {title or 'N/A'} "
                        f"| {age if age else 'N/A'} "
                        f"| {'$'+f'{int(pay):,}' if pay else 'N/A'} |"
                    )
                sections["mgmt"] = stale_note + "\n".join(mgmt_lines)

            # peer_comparisons → comp
            cur.execute(
                "SELECT peer_ticker, peer_name, market_cap_usd, revenue_ttm, ebitda, trailing_pe, pb "
                "FROM peer_comparisons WHERE ticker = %s "
                "ORDER BY fetched_date DESC, market_cap_usd DESC NULLS LAST LIMIT 10",
                (ticker,)
            )
            comp_rows = cur.fetchall()
            if comp_rows:
                def _cfmb(v):
                    return f"${float(v)/1e9:.1f}B" if v is not None else "N/A"
                def _cfx(v):
                    return f"{float(v):.1f}x" if v is not None else "N/A"
                comp_lines = [f"## Peer Comparison: {ticker}", "",
                              "| Ticker | Name | Mkt Cap | Revenue TTM | EBITDA | P/E | P/B |",
                              "|---|---|---|---|---|---|---|"]
                for p_tick, p_name, mktcap, rev, ebitda, pe, pb_v in comp_rows:
                    comp_lines.append(
                        f"| {p_tick or 'N/A'} | {p_name or 'N/A'} | {_cfmb(mktcap)} "
                        f"| {_cfmb(rev)} | {_cfmb(ebitda)} | {_cfx(pe)} | {_cfx(pb_v)} |"
                    )
                sections["comp"] = stale_note + "\n".join(comp_lines)

        conn.close()
        print(f"[read_structured] {ticker}: staleness={staleness}, sections={list(sections.keys())}")
        return sections, staleness
    except Exception as e:
        print(f"[read_structured] WARNING: {e}")
        return {}, "absent"


def _dispatch_stock_fetcher(ticker, portfolio_db, finnhub_key, wm_token, timeout_s=60):
    """Dispatch stock_data_fetcher as a Windmill sub-job and poll until complete.
    Returns True on success, False on timeout or error. Never raises.
    """
    WM_BASE = "http://windmill_server:8000"
    WM_WORKSPACE = "admins"
    url = f"{WM_BASE}/api/w/{WM_WORKSPACE}/jobs/run/p/u/admin/stock_data_fetcher"
    headers = {"Authorization": f"Bearer {wm_token}", "Content-Type": "application/json"}
    payload = {"ticker": ticker, "portfolio_db": portfolio_db, "finnhub_key": finnhub_key}
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=15)
        resp.raise_for_status()
        job_id = resp.text.strip().strip('"')
        print(f"[fetcher] dispatched job_id={job_id} for {ticker}")
        poll_url = f"{WM_BASE}/api/w/{WM_WORKSPACE}/jobs/completed/get/{job_id}"
        for _ in range(timeout_s // 5):
            time.sleep(5)
            try:
                check = requests.get(poll_url, headers=headers, timeout=10)
                if check.status_code == 200:
                    job = check.json()
                    if job.get("type") == "CompletedJob":
                        success = bool(job.get("success", False))
                        print(f"[fetcher] job {job_id} completed, success={success}")
                        return success
            except Exception:
                pass
        print(f"[fetcher] timeout waiting for job {job_id}")
        return False
    except Exception as e:
        print(f"[fetcher] dispatch error: {e}")
        return False


def _build_db_context(ticker, portfolio_db):
    if not portfolio_db or not ticker:
        return ""
    try:
        conn = psycopg2.connect(
            host=portfolio_db["host"], port=portfolio_db["port"],
            dbname=portfolio_db["dbname"], user=portfolio_db["user"],
            password=portfolio_db["password"],
        )
        with conn.cursor() as cur:
            cur.execute("""
                SELECT price_date, close_price
                FROM price_history
                WHERE ticker = %s
                ORDER BY price_date DESC
                LIMIT 30
            """, (ticker,))
            price_rows = cur.fetchall()

            cur.execute("""
                SELECT pe_ratio, pb_ratio, ev_ebitda, analyst_target_usd,
                       roe, roic, revenue_growth_yoy, debt_equity,
                       market_cap_usd, sector, country
                FROM fundamental_data
                WHERE ticker = %s
                ORDER BY as_of_date DESC
                LIMIT 1
            """, (ticker,))
            fund_row = cur.fetchone()
        conn.close()

        def fv(v, fmt=".1f"):
            return f"{float(v):{fmt}}" if v is not None else "N/A"

        lines = [f"## DB Context: {ticker}", ""]

        if price_rows:
            lines.append("### Recent Prices")
            lines.append("| Date | Close |")
            lines.append("|---|---|")
            for d, p in price_rows[:15]:
                lines.append(f"| {d} | {float(p):.2f} |")

        if fund_row:
            pe, pb, ev_eb, target, roe, roic, rev_g, d_eq, mktcap, sector, country = fund_row
            lines.append("\n### Fundamentals (latest)")
            lines.append(f"- P/E: {fv(pe)}x | P/B: {fv(pb)}x | EV/EBITDA: {fv(ev_eb)}x")
            lines.append(f"- Analyst target (USD): ${fv(target, '.2f')}")
            lines.append(f"- ROE: {fv(roe)}% | ROIC: {fv(roic)}%")
            lines.append(f"- Revenue growth YoY: {fv(rev_g)}% | Debt/Equity: {fv(d_eq)}")
            if mktcap:
                lines.append(f"- Market cap: ${float(mktcap)/1e9:.1f}B")
            lines.append(f"- Sector: {sector or 'N/A'} | Country: {country or 'N/A'}")

        print(f"[DB] {len(price_rows)} price rows, fundamentals {'found' if fund_row else 'not found'}")
        return "\n".join(lines)
    except Exception as e:
        print(f"[DB] WARNING: context fetch failed — {e}")
        return ""


def _md_to_html(md):
    html = re.sub(r"^# (.+)$", r"<h1>\1</h1>", md, flags=re.MULTILINE)
    html = re.sub(r"^## (.+)$", r"<h2>\1</h2>", html, flags=re.MULTILINE)
    html = re.sub(r"^### (.+)$", r"<h3>\1</h3>", html, flags=re.MULTILINE)
    html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html)
    html = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', html)
    html = re.sub(r"^---$", r"<hr>", html, flags=re.MULTILINE)
    html = re.sub(r"^- (.+)$", r"<li>\1</li>", html, flags=re.MULTILINE)
    paragraphs = []
    for block in re.split(r"\n\n+", html):
        block = block.strip()
        if not block:
            continue
        if block.startswith(("<h", "<hr", "<li")):
            paragraphs.append(block)
        else:
            paragraphs.append(f"<p>{block.replace(chr(10), '<br>')}</p>")
    return "\n".join(paragraphs)


def _send_research_email(question, research_type, depth, ticker, full_markdown,
                         source_count, est_cost, gmail_smtp, recipient_email=""):
    subject_ticker = f" [{ticker}]" if ticker else ""
    subject = f"Research{subject_ticker}: {question} — {research_type}/{depth}"

    html_body = f"""
<html><body style="font-family:Georgia,serif;max-width:800px;margin:0 auto;color:#1a1a1a">
<div style="background:#f5f5f0;padding:16px 20px;border-left:4px solid #2c3e50;margin-bottom:24px">
  <strong style="font-size:16px">{question}</strong><br>
  <span style="color:#666;font-size:13px">
    {research_type} &nbsp;|&nbsp; {depth} &nbsp;|&nbsp; {source_count} sources &nbsp;|&nbsp; est. ${est_cost:.4f}
    {"&nbsp;|&nbsp; " + ticker if ticker else ""}
  </span>
</div>
{_md_to_html(full_markdown)}
</body></html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = gmail_smtp.get("username", "straitsagent@gmail.com")
    msg["To"] = recipient_email
    msg.attach(MIMEText(full_markdown, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP(gmail_smtp["host"], gmail_smtp["port"]) as s:
        s.starttls()
        s.login(gmail_smtp["username"], gmail_smtp["password"])
        s.sendmail(gmail_smtp["username"], recipient_email, msg.as_string())
    print(f"[Email] Sent to {recipient_email}")


def _synthesise_with_fallback(messages, xai_key, deepseek_key, reasoning_effort, max_tokens):
    """Call Grok; fall back to Deepseek on failure. Returns {"text", "synthesiser_model", "input_tokens", "output_tokens"}."""
    try:
        grok = OpenAI(api_key=xai_key, base_url="https://api.x.ai/v1")
        resp = grok.chat.completions.create(
            model="grok-4.3", messages=messages,
            max_tokens=max_tokens, temperature=0.3,
            extra_body={"reasoning_effort": reasoning_effort},
        )
        return {
            "text": resp.choices[0].message.content.strip(),
            "synthesiser_model": "grok-4.3",
            "input_tokens": resp.usage.prompt_tokens or 0,
            "output_tokens": resp.usage.completion_tokens or 0,
        }
    except Exception as e:
        print(f"[Grok] ERROR: {e} — falling back to Deepseek")
    try:
        ds = OpenAI(api_key=deepseek_key, base_url="https://api.deepseek.com")
        resp = ds.chat.completions.create(
            model="deepseek-chat", messages=messages, max_tokens=max_tokens, temperature=0.3,
        )
        return {
            "text": resp.choices[0].message.content.strip(),
            "synthesiser_model": "deepseek-fallback",
            "input_tokens": resp.usage.prompt_tokens or 0,
            "output_tokens": resp.usage.completion_tokens or 0,
        }
    except Exception as e:
        print(f"[Deepseek fallback] ERROR: {e}")
    return {
        "text": "*Synthesis failed — both Grok and Deepseek unavailable.*",
        "synthesiser_model": "error",
        "input_tokens": 0,
        "output_tokens": 0,
    }


def main(
    question: str = "",
    research_type: str = "stock",
    depth: str = "standard",
    ticker: str = "",
    portfolio_db: dict = {},
    gmail_smtp: dict = {},
    perplexity_key: str = "",
    xai_key: str = "",
    exa_key: str = "",
    deepseek_key: str = "",
    finnhub_key: str = "",
    serper_key: str = "",
    tavily_key: str = "",
    brave_key: str = "",
    fred_key: str = "",
    wm_token: str = "",
    recipient_email: str = "",
):
    ticker = ticker.strip().upper()
    research_type = research_type.lower().strip()
    depth = depth.lower().strip()
    n_queries = {"brief": 3, "standard": 5, "deep": 10}.get(depth, 5)
    is_stock = (research_type == "stock" and ticker)
    is_us_ticker = is_stock and not ticker.endswith(".HK")

    print(f"[Start] question='{question[:60]}', type={research_type}, depth={depth}, ticker={ticker or 'none'}")

    # ── Step 1: Query decomposition (Deepseek) ────────────────────────────────
    queries = [question]
    ds_input_tokens = ds_output_tokens = 0
    if deepseek_key:
        try:
            ds = OpenAI(api_key=deepseek_key, base_url="https://api.deepseek.com")
            ds_resp = ds.chat.completions.create(
                model="deepseek-chat",
                messages=[{
                    "role": "user",
                    "content": (
                        f"Generate {n_queries} targeted search queries to research the following.\n"
                        f"research_type: {research_type}\n"
                        f"question: {question}\n"
                        + (f"ticker: {ticker}\n" if ticker else "")
                        + "\nReturn ONLY a JSON array of strings. No explanation, no markdown. "
                        "Example: [\"query 1\", \"query 2\"]"
                    ),
                }],
                max_tokens=400,
                temperature=0.3,
            )
            raw = ds_resp.choices[0].message.content.strip()
            ds_input_tokens = ds_resp.usage.prompt_tokens or 0
            ds_output_tokens = ds_resp.usage.completion_tokens or 0
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list) and parsed:
                    queries = [str(q) for q in parsed[:n_queries]]
            except Exception:
                m = re.search(r"\[.*\]", raw, re.DOTALL)
                if m:
                    try:
                        parsed = json.loads(m.group())
                        if isinstance(parsed, list) and parsed:
                            queries = [str(q) for q in parsed[:n_queries]]
                    except Exception:
                        pass
            print(f"[Decomposition] {len(queries)} queries generated")
        except Exception as e:
            print(f"[Decomposition] WARNING: Deepseek failed — {e}. Using question as query.")
    else:
        print("[Decomposition] No deepseek_key — using question directly")

    # ── Step 2: Multi-source search ───────────────────────────────────────────
    all_results = []
    source_priority = {
        "edgar_10k": 0, "edgar_10q": 1, "edgar_8k": 2, "fred": 3,
        "finnhub": 4, "seeking_alpha": 5, "yfinance": 6,
        "google_news": 7, "perplexity": 8,
        "tavily": 9, "brave": 10, "exa": 11, "serper": 12,
    }

    # 2b: Stock-specific sources
    if is_stock:
        today_str = date.today().strftime("%Y-%m-%d")
        week_ago_str = (date.today() - timedelta(days=7)).strftime("%Y-%m-%d")

        # Finnhub (US tickers only)
        if finnhub_key and is_us_ticker:
            try:
                resp = requests.get(
                    "https://finnhub.io/api/v1/company-news",
                    params={"symbol": ticker, "from": week_ago_str, "to": today_str},
                    headers={"X-Finnhub-Token": finnhub_key},
                    timeout=10,
                )
                resp.raise_for_status()
                for a in resp.json()[:10]:
                    if a.get("headline"):
                        all_results.append({
                            "source": "finnhub",
                            "title": a["headline"],
                            "url": a.get("url", ""),
                            "snippet": a.get("summary", "")[:300],
                            "date": str(a.get("datetime", "")),
                        })
                print(f"[Finnhub] {sum(1 for r in all_results if r['source']=='finnhub')} articles")
            except Exception as e:
                print(f"[Finnhub] WARNING: {e}")

        # Seeking Alpha RSS
        try:
            sa_feed = feedparser.parse(f"https://seekingalpha.com/api/sa/combined/{ticker}.xml")
            for e in sa_feed.entries[:5]:
                snippet = _strip_html(getattr(e, "summary", "") or "")[:300]
                all_results.append({
                    "source": "seeking_alpha",
                    "title": e.get("title", ""),
                    "url": e.get("link", ""),
                    "snippet": snippet,
                    "date": e.get("published", ""),
                })
            print(f"[SeekingAlpha] {sum(1 for r in all_results if r['source']=='seeking_alpha')} articles")
        except Exception as e:
            print(f"[SeekingAlpha] WARNING: {e}")

        # yfinance news
        try:
            raw_news = yf.Ticker(ticker).news or []
            for n in raw_news[:5]:
                headline = n.get("title") or n.get("content", {}).get("title") or ""
                url = (n.get("link")
                       or n.get("content", {}).get("canonicalUrl", {}).get("url") or "")
                if headline:
                    all_results.append({
                        "source": "yfinance",
                        "title": headline,
                        "url": url,
                        "snippet": "",
                        "date": "",
                    })
            print(f"[yfinance-news] {sum(1 for r in all_results if r['source']=='yfinance')} articles")
        except Exception as e:
            print(f"[yfinance-news] WARNING: {e}")
        time.sleep(0.3)

    # 2a: Google News RSS
    for q in queries:
        all_results.extend(_fetch_google_news(q, max_items=5))
        time.sleep(0.2)
    print(f"[GoogleNews] {sum(1 for r in all_results if r['source']=='google_news')} articles total")

    # 2c: Perplexity Search API
    perplexity_calls_n = 0
    if perplexity_key:
        batch_size = 5
        for i in range(0, len(queries), batch_size):
            batch = queries[i:i + batch_size]
            all_results.extend(_fetch_perplexity_batch(batch, perplexity_key, max_results=5))
            perplexity_calls_n += 1
            time.sleep(0.5)

    # 2d: Serper news — all depths when key present
    if serper_key:
        all_results.extend(_fetch_serper_news(queries, serper_key, max_results=10))

    # 2d2: Tavily finance search — standard + deep
    if tavily_key and depth in ("standard", "deep"):
        all_results.extend(_fetch_tavily(queries, tavily_key, max_results=10))

    # 2d3: Brave news — standard + deep
    if brave_key and depth in ("standard", "deep"):
        all_results.extend(_fetch_brave_news(queries, brave_key, max_results=10))

    # 2d4: FRED macro data — standard + deep, macro research type only
    if fred_key and depth in ("standard", "deep") and research_type == "macro":
        all_results.extend(_fetch_fred_data(fred_key))

    # 2e: Exa — standard + deep, but skip for stock research at standard
    exa_queries_n = 0
    use_exa = exa_key and depth in ("standard", "deep") and not (
        depth == "standard" and research_type == "stock"
    )
    if use_exa:
        for q in queries[:3]:
            all_results.extend(_fetch_exa_query(q, exa_key, max_results=5))
            exa_queries_n += 1
            time.sleep(0.3)
        print(f"[Exa] {sum(1 for r in all_results if r['source']=='exa')} articles total")

    # 2f: SEC EDGAR — standard (8-K only) + deep (all) for US tickers
    edgar_results = []
    if is_us_ticker and depth in ("standard", "deep"):
        edgar_forms = None if depth == "deep" else ["8-K"]
        edgar_results = _fetch_edgar_filings(ticker, forms=edgar_forms)
        all_results.extend(edgar_results)

    # ── Step 3: Aggregate + deduplicate ───────────────────────────────────────
    seen_urls = set()
    deduped = []
    for item in all_results:
        url = item.get("url", "").strip()
        if url and url in seen_urls:
            continue
        if url:
            seen_urls.add(url)
        if item.get("title"):
            deduped.append(item)
    deduped.sort(key=lambda x: source_priority.get(x["source"], 99))
    print(f"[Aggregate] {len(all_results)} raw → {len(deduped)} deduped results")

    # ── Step 3b: Full article text fetch — standard + deep ────────────────────
    full_text_count = snippet_count = skip_count = 0
    if depth in ("standard", "deep"):
        for item in deduped:
            # Skip: Perplexity (own domain), EDGAR (already full text), Seeking Alpha (paywall)
            if item["source"] in ("perplexity", "seeking_alpha") or item["source"].startswith("edgar"):
                item.setdefault("content_level", item.get("content_level", "snippet"))
                skip_count += 1
                continue
            text = _fetch_article_text(item.get("url", ""))
            if text:
                item["snippet"] = text
                item["content_level"] = "full_text"
                full_text_count += 1
            else:
                item.setdefault("content_level", "snippet")
                snippet_count += 1
            time.sleep(0.15)
        print(f"[ArticleFetch] {full_text_count} full text, {snippet_count} snippet, {skip_count} skipped")
    else:
        for item in deduped:
            item.setdefault("content_level", "snippet")

    # ── Step 3c: Agentic gap analysis — deep only ─────────────────────────────
    gap_round2_count = 0
    if depth == "deep":
        gaps = _iterative_gap_analysis(deduped, question, research_type, deepseek_key)
        for gap in gaps:
            source_type = gap.get("source_type", "news")
            gap_query = gap.get("query", "")
            print(f"[Round 2] fetching for gap: '{gap.get('description','?')}' — source_type={source_type}")
            round2_batch = []
            if source_type == "news":
                if perplexity_key:
                    round2_batch.extend(_fetch_perplexity_batch([gap_query], perplexity_key, max_results=3))
                if brave_key:
                    round2_batch.extend(_fetch_brave_news([gap_query], brave_key, max_results=5))
            elif source_type == "sec":
                if is_us_ticker:
                    round2_batch.extend(_fetch_edgar_filings(ticker, forms=["8-K"]))
            elif source_type == "analyst":
                if exa_key:
                    round2_batch.extend(_fetch_exa_query(gap_query, exa_key, max_results=3))
            elif source_type == "market_data":
                if finnhub_key and is_us_ticker:
                    try:
                        today_s = date.today().strftime("%Y-%m-%d")
                        week_ago_s = (date.today() - timedelta(days=7)).strftime("%Y-%m-%d")
                        resp = requests.get(
                            "https://finnhub.io/api/v1/company-news",
                            params={"symbol": ticker, "from": week_ago_s, "to": today_s},
                            headers={"X-Finnhub-Token": finnhub_key},
                            timeout=10,
                        )
                        for a in resp.json()[:5]:
                            if a.get("headline"):
                                round2_batch.append({
                                    "source": "finnhub",
                                    "title": a["headline"],
                                    "url": a.get("url", ""),
                                    "snippet": a.get("summary", "")[:300],
                                    "date": str(a.get("datetime", "")),
                                })
                    except Exception as e:
                        print(f"[Round 2 market_data] WARNING: {e}")
                elif is_stock:
                    try:
                        raw_news = yf.Ticker(ticker).news or []
                        for n in raw_news[:3]:
                            headline = n.get("title") or n.get("content", {}).get("title") or ""
                            url = (n.get("link") or n.get("content", {}).get("canonicalUrl", {}).get("url") or "")
                            if headline:
                                round2_batch.append({"source": "yfinance", "title": headline, "url": url, "snippet": "", "date": ""})
                    except Exception as e:
                        print(f"[Round 2 yfinance] WARNING: {e}")
            # Deduplicate Round 2 against seen_urls and append
            for item in round2_batch:
                url = item.get("url", "").strip()
                if url and url in seen_urls:
                    continue
                if url:
                    seen_urls.add(url)
                if item.get("title"):
                    item.setdefault("content_level", "snippet")
                    if item["source"] not in ("perplexity", "seeking_alpha") and not item["source"].startswith("edgar"):
                        text = _fetch_article_text(item.get("url", ""))
                        if text:
                            item["snippet"] = text
                            item["content_level"] = "full_text"
                            full_text_count += 1
                    deduped.append(item)
                    gap_round2_count += 1
        if gap_round2_count > 0:
            print(f"[Round 2] {gap_round2_count} new sources added from gap analysis")
            deduped.sort(key=lambda x: source_priority.get(x["source"], 99))

    # ── Step 4: DB context + comprehensive stock fundamentals (stock type only) ─
    db_context = _build_db_context(ticker, portfolio_db) if ticker else ""
    overview_context = fin_context = val_context = own_context = ""
    ins_context = earn_context = mgmt_context = comp_context = mdna_context = ""
    sections = {}

    if is_stock and portfolio_db:
        sections, staleness = _read_structured_stock_data(ticker, portfolio_db)
        if staleness in ("absent", "stale") and wm_token:
            print(f"[Step 4] Data {staleness} for {ticker} — dispatching stock_data_fetcher")
            ok = _dispatch_stock_fetcher(ticker, portfolio_db, finnhub_key, wm_token)
            if ok:
                sections, staleness = _read_structured_stock_data(ticker, portfolio_db)
                print(f"[Step 4] Fetcher completed — re-read: staleness={staleness}")
            else:
                print(f"[Step 4] Fetcher failed — falling back to live fetch")

    if is_stock and sections:
        # DB data available (fresh read, or fetcher succeeded)
        overview_context = sections.get("overview", "")
        fin_context      = sections.get("fin", "")
        val_context      = sections.get("val", "")
        own_context      = sections.get("own", "")
        ins_context      = sections.get("ins", "")
        earn_context     = sections.get("earn", "")
        mgmt_context     = sections.get("mgmt", "")
        comp_context     = sections.get("comp", "")
    elif is_stock:
        # Live-fetch fallback: no portfolio_db, OR fetcher timed out with empty sections
        print(f"[Step 4] Live-fetching all 8 data functions for {ticker}")
        overview_context, _ = _fetch_company_overview(ticker)
        fin_context,      _ = _fetch_yfinance_financials(ticker)
        val_context,      _ = _fetch_yfinance_valuation(ticker)
        own_context,      _ = _fetch_ownership(ticker)
        ins_context,      _ = _fetch_insider_transactions(ticker)
        earn_context,     _ = _fetch_earnings_calendar(ticker)
        _exec_ctx,        _ = _fetch_management(ticker)
        mgmt_context        = _exec_ctx
        comp_context,     _ = _fetch_competitors(ticker, finnhub_key)

    # Always live-fetched (DeepSeek cost + EDGAR parser bug — not in stock_data_fetcher):
    if is_stock:
        mdna_context, _ = _fetch_mdna_synopsis(ticker, deepseek_key)
        _board_ctx, _   = _fetch_board_of_directors(ticker)
        if _board_ctx:
            mgmt_context = "\n\n".join(x for x in [mgmt_context, _board_ctx] if x)

    # ── Step 5: Synthesis (Grok via xAI) ─────────────────────────────────────
    # Snippet length passed to Grok depends on content level and source type.
    # EDGAR and full-text articles get their full content — truncating defeats the fetch.
    SNIPPET_CAPS = {
        "edgar_10k": 5000, "edgar_10q": 5000, "edgar_8k": 3000,
        "full_text": 2000,
        "snippet": 500,
    }
    source_lines = []
    for i, item in enumerate(deduped, 1):
        src = item.get("source", "")
        content_level = item.get("content_level", "snippet")
        if src.startswith("edgar"):
            cap = SNIPPET_CAPS.get(src, 3000)
        else:
            cap = SNIPPET_CAPS.get(content_level, 500)
        snippet = (item.get("snippet") or "")[:cap]
        snippet_text = f"\n{snippet}" if snippet else ""
        source_lines.append(
            f"[{i}] {item['source']} | {item['title']} | {item.get('date', 'n/d')}"
            + snippet_text
        )

    depth_instruction = {
        "brief": (
            "Depth=brief: provide a concise, structured summary. "
            "2–3 sentences per section. Total target: 300–400 words."
        ),
        "standard": (
            "Depth=standard: provide a thorough analysis. "
            "2–4 paragraphs per section with specific numbers and evidence from the sources. "
            "Total target: 700–1,000 words."
        ),
        "deep": (
            "Depth=deep: produce a comprehensive, investment-grade analysis. "
            "Each section should be 4–6 paragraphs. Go beyond summarising — analyse the "
            "implications, compare competing evidence across sources, and quantify wherever "
            "possible. Reference specific figures from financial statements and SEC filings "
            "where available. Call out uncertainties or conflicting signals between sources. "
            + (f"Note: {gap_round2_count} additional sources were added from targeted gap analysis (Round 2); "
               "acknowledge where follow-up sources confirmed, extended, or contradicted Round 1 findings. "
               if gap_round2_count > 0 else "")
            + "Total target: 1,800–2,500 words."
        ),
    }.get(depth, "")

    user_message = f"Question: {question}\n"
    if ticker:
        user_message += f"Ticker: {ticker}\n"
    user_message += f"Research type: {research_type}\nDepth: {depth}\n"
    if depth_instruction:
        user_message += f"\nINSTRUCTION: {depth_instruction}\n"
    if db_context:
        user_message += f"\n{db_context}\n"
    if overview_context:
        user_message += f"\n{overview_context}\n"
    if fin_context:
        user_message += f"\n{fin_context}\n"
    if val_context:
        user_message += f"\n{val_context}\n"
    if own_context:
        user_message += f"\n{own_context}\n"
    if ins_context:
        user_message += f"\n{ins_context}\n"
    if earn_context:
        user_message += f"\n{earn_context}\n"
    if mdna_context:
        user_message += f"\n{mdna_context}\n"
    if mgmt_context:
        user_message += f"\n{mgmt_context}\n"
    if comp_context:
        user_message += f"\n{comp_context}\n"
    user_message += f"\nSOURCES ({len(deduped)} results):\n\n" + "\n\n".join(source_lines)

    system_prompt = SYSTEM_PROMPTS.get(research_type, SYSTEM_PROMPTS["strategy"])

    reasoning_effort = {"brief": "low", "standard": "medium", "deep": "high"}.get(depth, "medium")
    max_output_tokens = {"brief": 1500, "standard": 3000, "deep": 8000}.get(depth, 3000)
    _synth = _synthesise_with_fallback(
        messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_message}],
        xai_key=xai_key, deepseek_key=deepseek_key,
        reasoning_effort=reasoning_effort, max_tokens=max_output_tokens,
    )
    synthesis = _synth["text"]
    synthesiser_model = _synth["synthesiser_model"]
    grok_input_tokens = _synth["input_tokens"]
    grok_output_tokens = _synth["output_tokens"]
    print(f"[Synthesis] model={synthesiser_model}, {grok_input_tokens} in + {grok_output_tokens} out tokens, {len(synthesis)} chars")

    # ── Cost estimation ────────────────────────────────────────────────────────
    ds_cost = (ds_input_tokens * 0.27 + ds_output_tokens * 1.10) / 1_000_000
    pplx_cost = perplexity_calls_n * 0.010
    exa_cost = exa_queries_n * 0.010
    serper_count = sum(1 for r in deduped if r["source"] == "serper")
    serper_cost = 0.0003 * (1 if serper_count > 0 else 0)
    tavily_count = sum(1 for r in deduped if r["source"] == "tavily")
    brave_count = sum(1 for r in deduped if r["source"] == "brave")
    fred_count = sum(1 for r in deduped if r["source"] == "fred")
    grok_cost = (grok_input_tokens * 1.25 + grok_output_tokens * 2.50) / 1_000_000
    est_cost = ds_cost + pplx_cost + exa_cost + serper_cost + grok_cost
    total_tokens = (ds_input_tokens + ds_output_tokens
                    + grok_input_tokens + grok_output_tokens)

    # ── Step 6: Store ──────────────────────────────────────────────────────────
    today_str = date.today().strftime("%Y-%m-%d")
    slug = _slugify(question) if question else ticker.lower()
    type_dir = TYPE_DIRS.get(research_type, "strategy")
    file_path = f"/research/{type_dir}/{today_str}_{depth}_{slug}.md"

    ref_lines = []
    for i, item in enumerate(deduped, 1):
        if item.get("url"):
            ref_lines.append(f"[{i}] [{item['title']}]({item['url']}) — {item['source']}")

    # Cost breakdown
    cost_rows = [
        f"| Deepseek (query decomp{' + gap analysis' if depth=='deep' else ''}) | {ds_input_tokens} in + {ds_output_tokens} out | ${ds_cost:.4f} |",
        f"| Perplexity Search API | {perplexity_calls_n} call(s), {len(queries)} queries | ${pplx_cost:.4f} |",
        f"| Serper news | {serper_count} results{' (1 call, $0.0003)' if serper_count > 0 else ' (skipped — no key)'} | ${serper_cost:.4f} |",
        f"| Tavily finance search | {tavily_count} results (free tier, time_range=month) | $0.0000 |",
        f"| Brave Search | {brave_count} results (free tier, freshness=pm) | $0.0000 |",
        f"| FRED macro data | {fred_count} series (free) | $0.0000 |",
        f"| Exa neural search | {exa_queries_n} queries{' (skipped — brief depth)' if exa_queries_n == 0 and depth == 'brief' else ''} | ${exa_cost:.4f} |",
        f"| Grok-4.3 synthesis (reasoning_effort={reasoning_effort}) | {grok_input_tokens} in + {grok_output_tokens} out | ${grok_cost:.4f} |",
        f"| **Total** | {total_tokens} tokens | **${est_cost:.4f}** |",
    ]
    cost_table = (
        "### Cost Breakdown\n"
        "| API | Usage | Est. Cost |\n"
        "|---|---|---|\n"
        + "\n".join(cost_rows)
    )

    # Source retrieval quality — dynamic content level tracking
    source_quality = {}
    for item in deduped:
        src = item["source"]
        level = item.get("content_level", "snippet")
        if src not in source_quality:
            source_quality[src] = {"full_text": 0, "snippet": 0}
        source_quality[src][level] = source_quality[src].get(level, 0) + 1

    quality_rows = []
    source_order = [
        "edgar_10k", "edgar_10q", "edgar_8k", "fred",
        "finnhub", "seeking_alpha", "yfinance",
        "google_news", "perplexity", "tavily", "brave", "exa", "serper",
    ]
    for src in source_order:
        if src not in source_quality:
            continue
        ft = source_quality[src].get("full_text", 0)
        sn = source_quality[src].get("snippet", 0)
        total = ft + sn
        level_str = f"{ft} full text, {sn} snippet" if ft > 0 else f"{sn} snippet only"
        quality_rows.append(f"| {src} | {total} | {level_str} |")

    # Add notes for sources that were eligible but returned 0
    if depth == "brief":
        quality_rows.append("| exa | 0 | Skipped — brief depth |")
        quality_rows.append("| edgar_* | 0 | Skipped — brief depth |")
    elif not is_us_ticker and is_stock:
        quality_rows.append("| edgar_* | 0 | Skipped — HK ticker (not in SEC EDGAR) |")
    elif depth in ("standard", "deep") and not any(s.startswith("edgar") for s in source_quality):
        if depth == "standard":
            quality_rows.append("| edgar_* | 0 | Skipped — standard depth (deep only) |")

    total_full_text = sum(v.get("full_text", 0) for v in source_quality.values())
    total_sources = len(deduped)
    if depth == "brief":
        retrieval_label = "⚠️ **Headline/snippet-level analysis.** No article text retrieval at brief depth."
    elif total_full_text == 0:
        retrieval_label = "⚠️ **Snippet-level analysis only.** Article fetch attempted but all sources returned paywalled/blocked content."
    elif total_full_text < total_sources // 2:
        retrieval_label = f"⚠️ **Partial full-text retrieval.** {total_full_text}/{total_sources} sources retrieved as full article text; remainder are headlines/snippets."
    else:
        retrieval_label = f"✅ **Full-text analysis.** {total_full_text}/{total_sources} sources retrieved as full article text."

    fin_label = ""
    if is_stock:
        fin_label = "\n\n**Financial statements:** yfinance quarterly income statement, balance sheet, and cash flow included in synthesis context."
    if depth == "deep" and is_us_ticker:
        fin_label += "\n**SEC filings:** EDGAR 10-K (MD&A), 10-Q (MD&A), and recent 8-K(s) retrieved and included."
    elif depth == "deep" and is_stock and not is_us_ticker:
        fin_label += "\n**SEC filings:** Not available — HK-listed tickers are not in SEC EDGAR."
    if depth == "deep" and gap_round2_count > 0:
        fin_label += f"\n**Agentic gap analysis:** Round 2 added {gap_round2_count} targeted sources."
    if tavily_count > 0:
        fin_label += "\n**Tavily:** time_range=month enforced — exact publish dates unavailable but all results within 30 days."

    quality_table = (
        "### Source Retrieval Quality\n"
        "| Source | Count | Content Level |\n"
        "|---|---|---|\n"
        + "\n".join(quality_rows)
        + f"\n\n{retrieval_label}{fin_label}"
    )

    header = (
        f"# {question}\n\n"
        f"**Type:** {research_type} | **Depth:** {depth} | **Date:** {today_str}"
    )
    if ticker:
        header += f" | **Ticker:** {ticker}"
    header += f" | **Sources:** {len(deduped)} | **Queries:** {len(queries)}"
    header += f"\n\n{cost_table}\n\n{quality_table}\n\n---\n\n"

    full_markdown = header + synthesis
    if is_stock:
        _data_sections = [s for s in [
            overview_context, fin_context, val_context, own_context,
            ins_context, earn_context, mdna_context, mgmt_context, comp_context,
        ] if s]
        if _data_sections:
            full_markdown += "\n\n---\n\n## Supporting Data\n\n" + "\n\n".join(_data_sections)
    if ref_lines:
        full_markdown += "\n\n---\n\n## References\n\n" + "\n".join(ref_lines)

    written_path = None
    try:
        with open(file_path, "w") as f:
            f.write(full_markdown)
        written_path = file_path
        print(f"[Store] Written: {file_path}")
    except Exception as e:
        print(f"[Store] WARNING: file write failed — {e}")

    report_id = None
    if portfolio_db:
        try:
            conn = psycopg2.connect(
                host=portfolio_db["host"], port=portfolio_db["port"],
                dbname=portfolio_db["dbname"], user=portfolio_db["user"],
                password=portfolio_db["password"],
            )
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO research_reports
                        (question, research_type, depth, ticker, file_path, word_count,
                         sources, search_queries, total_tokens, est_cost_usd, content)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    question, research_type, depth, ticker or None,
                    written_path, len(synthesis.split()),
                    [item["source"] for item in deduped],
                    queries,
                    total_tokens,
                    round(est_cost, 4),
                    full_markdown,
                ))
                report_id = cur.fetchone()[0]
            conn.commit()
            conn.close()
            print(f"[DB] Saved research_reports id={report_id}")
        except Exception as e:
            print(f"[DB] WARNING: save failed — {e}")

    try:
        index_path = "/research/index.json"
        with open(index_path) as f:
            index = json.load(f)
        index.append({
            "id": f"{today_str}_{slug}",
            "date": today_str,
            "question": question,
            "research_type": research_type,
            "depth": depth,
            "ticker": ticker or None,
            "file_path": written_path,
            "word_count": len(synthesis.split()),
            "source_count": len(deduped),
            "est_cost_usd": round(est_cost, 4),
        })
        with open(index_path, "w") as f:
            json.dump(index, f, indent=2, default=str)
        print(f"[Index] Updated — {len(index)} entries total")
    except Exception as e:
        print(f"[Index] WARNING: {e}")

    # ── Step 7: Email delivery ─────────────────────────────────────────────────
    if gmail_smtp:
        try:
            _send_research_email(
                question, research_type, depth, ticker,
                full_markdown, len(deduped), est_cost, gmail_smtp, recipient_email,
            )
        except Exception as e:
            print(f"[Email] WARNING: send failed — {e}")
    else:
        print("[Email] No gmail_smtp provided — skipping email delivery")

    return {
        "file_path": written_path,
        "word_count": len(synthesis.split()),
        "source_count": len(deduped),
        "queries": queries,
        "total_tokens": total_tokens,
        "est_cost_usd": round(est_cost, 4),
        "db_id": report_id,
        "synthesiser_model": synthesiser_model,
        "preview": synthesis[:2000] + ("…" if len(synthesis) > 2000 else ""),
    }
