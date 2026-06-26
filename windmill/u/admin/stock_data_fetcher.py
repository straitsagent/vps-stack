# Requirements:
# psycopg2-binary>=2.9
# requests>=2.31
# yfinance>=0.2.40
# beautifulsoup4>=4.12
# lxml>=5.0

"""
Stock Data Fetcher — fetch structured data for a single ticker and persist to DB.

Fetches: company profile, financials (3yr income/BS/CF/health), valuation multiples,
ownership, insider transactions, earnings calendar, key management, peer comparisons.

Does NOT fetch: MD&A synopsis (costly LLM generation) or board of directors
(EDGAR parsing has a known bug — both kept as live fetches in research_tool).

Designed to be called for any ticker — portfolio, watchlist, S&P 500, or ad-hoc.
Batching across multiple tickers is the caller's responsibility.
"""

import time
from datetime import date
from typing import TypedDict

import psycopg2
import requests
import yfinance as yf
import logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
log = logging.getLogger(__name__)



class postgresql(TypedDict):
    host: str
    port: int
    user: str
    password: str
    dbname: str


EDGAR_HEADERS = {"User-Agent": "research-tool/1.0 straitsagent@gmail.com"}


def _format_fin_table(df):
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
                    if fv != fv:
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
    try:
        t = yf.Ticker(ticker)
        blocks = []
        data = {}

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
            log.info(f"[yfinance-fin] income stmt: {e}")

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
            log.info(f"[yfinance-fin] balance sheet: {e}")

        try:
            cf = t.cashflow
            if cf is not None and not cf.empty:
                key_rows = ["Operating Cash Flow", "Free Cash Flow", "Capital Expenditure"]
                rows = [r for r in key_rows if r in cf.index]
                if rows:
                    blocks.append("### Cash Flow (Annual, 3yr)\n"
                                  + _format_fin_table(cf.loc[rows, cf.columns[:3]]))
        except Exception as e:
            log.info(f"[yfinance-fin] cash flow: {e}")

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
                    except Exception as _exc:
                        log.warning("Suppressed: %s", _exc)
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
            log.info(f"[yfinance-fin] health metrics: {e}")

        if blocks:
            log.info(f"[yfinance-fin] {len(blocks)} block(s) for {ticker}")
            return f"## Financial Statements: {ticker}\n\n" + "\n\n".join(blocks), data
        log.info(f"[yfinance-fin] no data for {ticker}")
        return "", {}
    except Exception as e:
        log.warning(f"[yfinance-fin] WARNING: {e}")
        return "", {}


def _fetch_company_overview(ticker):
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
        log.info(f"[overview] profile fetched for {ticker}")
        return "\n".join(lines), data
    except Exception as e:
        log.warning(f"[overview] WARNING: {e}")
        return "", {}


def _fetch_yfinance_valuation(ticker):
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

        tgt = info.get("targetMeanPrice")  # consensus mean across all analyst opinions (A5 verified)
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
            "trailing_pe":       _fv(info.get("trailingPE")),
            "forward_pe":        _fv(info.get("forwardPE")),
            "pb":                _fv(info.get("priceToBook")),
            "ps_ttm":            _fv(info.get("priceToSalesTrailing12Months")),
            "ev_ebitda":         _fv(info.get("enterpriseToEbitda")),
            "ev_revenue":        _fv(info.get("enterpriseToRevenue")),
            "p_fcf":             p_fcf_val,
            "peg":               _fv(info.get("pegRatio")),
            "beta":              _fv(info.get("beta")),
            "trailing_eps":      _fv(info.get("trailingEps")),
            "forward_eps":       _fv(info.get("forwardEps")),
            "fifty_two_wk_high": _fv(hi),
            "fifty_two_wk_low":  _fv(lo),
            "short_pct_float":   _fv(short_pct) * 100 if short_pct is not None else None,
            "short_ratio":       _fv(short_ratio),
            "analyst_target":    _fv(tgt),
            "analyst_rec_mean":  _fv(rec),
            "analyst_count":     int(n_a) if n_a else None,
        }
        log.info(f"[valuation] fetched for {ticker}")
        return "\n".join(lines), data
    except Exception as e:
        log.warning(f"[valuation] WARNING: {e}")
        return "", {}


def _fetch_ownership(ticker):
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
        except Exception as _exc:
            log.warning("Suppressed: %s", _exc)

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
            log.info(f"[ownership] institutional holders: {e}")

        if len(lines) <= 2:
            return "", {}
        data = {
            "insider_pct":       insider_pct,
            "institutional_pct": institutional_pct,
            "holders":           holders,
        }
        log.info(f"[ownership] fetched for {ticker}")
        return "\n".join(lines), data
    except Exception as e:
        log.warning(f"[ownership] WARNING: {e}")
        return "", {}


def _fetch_insider_transactions(ticker):
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
        log.info(f"[insiders] fetched for {ticker}")
        return "\n".join(lines), data
    except Exception as e:
        log.warning(f"[insiders] WARNING: {e}")
        return "", {}


def _pick_col(columns, keywords):
    """First column whose lowercased name contains any of `keywords`, else None."""
    for c in columns:
        name = str(c).lower()
        if any(k in name for k in keywords):
            return c
    return None


def _is_blank(v):
    """True for None or NaN (NaN != NaN) — lets pure logic stay pandas-free."""
    return v is None or (isinstance(v, float) and v != v)


def _extract_surprises(records, limit=4):
    """records: list of dicts {period_date, eps_estimate, eps_actual, native_surprise_pct}.
    Returns up to `limit` PAST-earnings surprises (eps_actual present), in input order,
    surprise_pct recomputed from est/actual, falling back to native_surprise_pct."""
    out = []
    for r in records:
        act = r.get("eps_actual")
        if _is_blank(act):
            continue
        est = r.get("eps_estimate")
        surp = None
        if not _is_blank(est) and not _is_blank(act):
            try:
                e_f, a_f = float(est), float(act)
                if e_f != 0:
                    surp = (a_f - e_f) / abs(e_f) * 100.0
            except Exception:
                surp = None
        if surp is None and not _is_blank(r.get("native_surprise_pct")):
            surp = float(r.get("native_surprise_pct"))
        out.append({
            "period_date":  r.get("period_date"),
            "eps_estimate": float(est) if not _is_blank(est) else None,
            "eps_actual":   float(act),
            "surprise_pct": surp,
        })
        if len(out) >= limit:
            break
    return out


def _fetch_earnings_calendar(ticker):
    try:
        t = yf.Ticker(ticker)
        lines = [f"## Earnings Calendar: {ticker}", ""]
        earn_date = eps_est = rev_lo = rev_hi = None
        surprises = []

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
            log.info(f"[calendar] next earnings: {e}")

        try:
            ed_df = t.earnings_dates
            if ed_df is not None and not ed_df.empty:
                est_col = _pick_col(ed_df.columns, ["estimate"])
                act_col = _pick_col(ed_df.columns, ["reported", "actual"])
                sur_col = _pick_col(ed_df.columns, ["surprise"])
                records = []
                for idx, row in ed_df.iterrows():
                    records.append({
                        "period_date":         str(idx)[:10],
                        "eps_estimate":        row.get(est_col) if est_col else None,
                        "eps_actual":          row.get(act_col) if act_col else None,
                        "native_surprise_pct": row.get(sur_col) if sur_col else None,
                    })
                surprises = _extract_surprises(records)
                if surprises:
                    lines.append("\n### Recent EPS Surprises")
                    lines.append("| Period | EPS Estimate | EPS Actual | Surprise |")
                    lines.append("|---|---|---|---|")
                    for s in surprises:
                        e_fmt = f"${s['eps_estimate']:.2f}" if s['eps_estimate'] is not None else "N/A"
                        a_fmt = f"${s['eps_actual']:.2f}"   if s['eps_actual']   is not None else "N/A"
                        sp    = f"{s['surprise_pct']:+.1f}%" if s['surprise_pct'] is not None else ""
                        lines.append(f"| {s['period_date']} | {e_fmt} | {a_fmt} | {sp} |")
        except Exception as e:
            log.info(f"[calendar] earnings dates: {e}")

        if len(lines) <= 2:
            return "", {}
        data = {
            "earnings_date": str(earn_date)[:10] if earn_date else None,
            "eps_estimate":  float(eps_est) if eps_est is not None else None,
            "revenue_low":   int(float(rev_lo)) if rev_lo else None,
            "revenue_high":  int(float(rev_hi)) if rev_hi else None,
            "surprises":     surprises,
        }
        log.info(f"[calendar] fetched for {ticker}")
        return "\n".join(lines), data
    except Exception as e:
        log.warning(f"[calendar] WARNING: {e}")
        return "", {}


def _fetch_management(ticker):
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
        log.info(f"[management] {len(officers)} officers for {ticker}")
        return "\n".join(lines), data
    except Exception as e:
        log.warning(f"[management] WARNING: {e}")
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
                    "peer_ticker":    peer,
                    "peer_name":      name,
                    "market_cap_usd": int(float(mc_v)) if mc_v else None,
                    "revenue_ttm":    int(float(rv_v)) if rv_v else None,
                    "ebitda":         int(float(eb_v)) if eb_v else None,
                    "trailing_pe":    float(pe_v) if pe_v else None,
                    "pb":             float(pb_v) if pb_v else None,
                })
                time.sleep(0.2)
            except Exception as ep:
                log.info(f"[competitors] peer {peer}: {ep}")

        data = {"peers": peers_data}
        log.info(f"[competitors] {len(peers)} peers for {ticker}")
        return "\n".join(lines), data
    except Exception as e:
        log.warning(f"[competitors] WARNING: {e}")
        return "", {}


def _store_stock_snapshot(ticker, portfolio_db, data):
    """Persist structured stock data to all 14 research DB tables. Graceful on failure."""
    try:
        conn = psycopg2.connect(
            host=portfolio_db["host"], port=portfolio_db.get("port", 5432),
            dbname=portfolio_db["dbname"], user=portfolio_db["user"],
            password=portfolio_db["password"],
        )
        tables_written = []
        with conn.cursor() as cur:
            # company_profiles
            ov = data.get("overview", {})
            if ov:
                cur.execute("""
                    INSERT INTO company_profiles
                        (ticker, sector, industry, country, exchange, employees, website, description, updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                    ON CONFLICT (ticker) DO UPDATE SET
                        sector=EXCLUDED.sector, industry=EXCLUDED.industry,
                        country=EXCLUDED.country, exchange=EXCLUDED.exchange,
                        employees=EXCLUDED.employees, website=EXCLUDED.website,
                        description=EXCLUDED.description, updated_at=NOW()
                """, (ticker, ov.get("sector"), ov.get("industry"), ov.get("country"),
                      ov.get("exchange"), ov.get("employees"), ov.get("website"),
                      ov.get("description")))
                tables_written.append("company_profiles")

            # financial statements + health metrics
            fin = data.get("fin", {})
            if fin and fin.get("fiscal_years"):
                fys  = fin["fiscal_years"]
                inc  = fin.get("income", {})
                bs   = fin.get("balance_sheet", {})
                cf   = fin.get("cashflow", {})
                hlth = fin.get("health", {})
                for idx, fy in enumerate(fys):
                    def _v(d, k): return d.get(k, [None] * 3)[idx] if d.get(k) else None
                    cur.execute("""
                        INSERT INTO income_statements
                            (ticker, fiscal_year_end, total_revenue, gross_profit, operating_income,
                             ebitda, net_income, basic_eps, fetched_date)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,CURRENT_DATE)
                        ON CONFLICT (ticker, fiscal_year_end) DO UPDATE SET
                            total_revenue=EXCLUDED.total_revenue, gross_profit=EXCLUDED.gross_profit,
                            operating_income=EXCLUDED.operating_income, ebitda=EXCLUDED.ebitda,
                            net_income=EXCLUDED.net_income, basic_eps=EXCLUDED.basic_eps,
                            fetched_date=CURRENT_DATE
                    """, (ticker, fy, _v(inc,"total_revenue"), _v(inc,"gross_profit"),
                          _v(inc,"operating_income"), _v(inc,"ebitda"),
                          _v(inc,"net_income"), _v(inc,"basic_eps")))
                    cur.execute("""
                        INSERT INTO balance_sheets
                            (ticker, fiscal_year_end, total_assets, total_liabilities,
                             stockholders_equity, total_debt, cash, current_assets,
                             current_liabilities, fetched_date)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,CURRENT_DATE)
                        ON CONFLICT (ticker, fiscal_year_end) DO UPDATE SET
                            total_assets=EXCLUDED.total_assets,
                            total_liabilities=EXCLUDED.total_liabilities,
                            stockholders_equity=EXCLUDED.stockholders_equity,
                            total_debt=EXCLUDED.total_debt, cash=EXCLUDED.cash,
                            current_assets=EXCLUDED.current_assets,
                            current_liabilities=EXCLUDED.current_liabilities,
                            fetched_date=CURRENT_DATE
                    """, (ticker, fy, _v(bs,"total_assets"), _v(bs,"total_liabilities"),
                          _v(bs,"stockholders_equity"), _v(bs,"total_debt"), _v(bs,"cash"),
                          _v(bs,"current_assets"), _v(bs,"current_liabilities")))
                    cur.execute("""
                        INSERT INTO cashflow_statements
                            (ticker, fiscal_year_end, operating_cf, free_cf, capex, fetched_date)
                        VALUES (%s,%s,%s,%s,%s,CURRENT_DATE)
                        ON CONFLICT (ticker, fiscal_year_end) DO UPDATE SET
                            operating_cf=EXCLUDED.operating_cf, free_cf=EXCLUDED.free_cf,
                            capex=EXCLUDED.capex, fetched_date=CURRENT_DATE
                    """, (ticker, fy, _v(cf,"operating_cf"), _v(cf,"free_cf"), _v(cf,"capex")))
                    cur.execute("""
                        INSERT INTO financial_health_metrics
                            (ticker, fiscal_year_end, net_debt, net_debt_ebitda, gearing,
                             current_ratio, net_margin, asset_turnover, equity_multiplier,
                             roe_dupont, fetched_date)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,CURRENT_DATE)
                        ON CONFLICT (ticker, fiscal_year_end) DO UPDATE SET
                            net_debt=EXCLUDED.net_debt, net_debt_ebitda=EXCLUDED.net_debt_ebitda,
                            gearing=EXCLUDED.gearing, current_ratio=EXCLUDED.current_ratio,
                            net_margin=EXCLUDED.net_margin, asset_turnover=EXCLUDED.asset_turnover,
                            equity_multiplier=EXCLUDED.equity_multiplier,
                            roe_dupont=EXCLUDED.roe_dupont, fetched_date=CURRENT_DATE
                    """, (ticker, fy, _v(hlth,"net_debt"), _v(hlth,"net_debt_ebitda"),
                          _v(hlth,"gearing"), _v(hlth,"current_ratio"), _v(hlth,"net_margin"),
                          _v(hlth,"asset_turnover"), _v(hlth,"equity_multiplier"),
                          _v(hlth,"roe_dupont")))
                tables_written.extend(["income_statements", "balance_sheets",
                                       "cashflow_statements", "financial_health_metrics"])

            # valuation_snapshots
            val = data.get("val", {})
            if val:
                cur.execute("""
                    INSERT INTO valuation_snapshots
                        (ticker, fetched_date, trailing_pe, forward_pe, pb, ps_ttm, ev_ebitda,
                         ev_revenue, p_fcf, peg, beta, trailing_eps, forward_eps,
                         fifty_two_wk_high, fifty_two_wk_low, short_pct_float, short_ratio,
                         analyst_target, analyst_rec_mean, analyst_count)
                    VALUES (%s,CURRENT_DATE,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (ticker, fetched_date) DO UPDATE SET
                        trailing_pe=EXCLUDED.trailing_pe, forward_pe=EXCLUDED.forward_pe,
                        pb=EXCLUDED.pb, ps_ttm=EXCLUDED.ps_ttm, ev_ebitda=EXCLUDED.ev_ebitda,
                        ev_revenue=EXCLUDED.ev_revenue, p_fcf=EXCLUDED.p_fcf,
                        peg=EXCLUDED.peg, beta=EXCLUDED.beta,
                        trailing_eps=EXCLUDED.trailing_eps, forward_eps=EXCLUDED.forward_eps,
                        fifty_two_wk_high=EXCLUDED.fifty_two_wk_high,
                        fifty_two_wk_low=EXCLUDED.fifty_two_wk_low,
                        short_pct_float=EXCLUDED.short_pct_float,
                        short_ratio=EXCLUDED.short_ratio,
                        analyst_target=EXCLUDED.analyst_target,
                        analyst_rec_mean=EXCLUDED.analyst_rec_mean,
                        analyst_count=EXCLUDED.analyst_count
                """, (ticker, val.get("trailing_pe"), val.get("forward_pe"), val.get("pb"),
                      val.get("ps_ttm"), val.get("ev_ebitda"), val.get("ev_revenue"),
                      val.get("p_fcf"), val.get("peg"), val.get("beta"),
                      val.get("trailing_eps"), val.get("forward_eps"),
                      val.get("fifty_two_wk_high"), val.get("fifty_two_wk_low"),
                      val.get("short_pct_float"), val.get("short_ratio"),
                      val.get("analyst_target"), val.get("analyst_rec_mean"),
                      val.get("analyst_count")))
                tables_written.append("valuation_snapshots")

            # ownership_snapshots + institutional_holders
            own = data.get("own", {})
            if own:
                cur.execute("""
                    INSERT INTO ownership_snapshots
                        (ticker, fetched_date, insider_pct, institutional_pct)
                    VALUES (%s,CURRENT_DATE,%s,%s)
                    ON CONFLICT (ticker, fetched_date) DO UPDATE SET
                        insider_pct=EXCLUDED.insider_pct,
                        institutional_pct=EXCLUDED.institutional_pct
                """, (ticker, own.get("insider_pct"), own.get("institutional_pct")))
                for h in own.get("holders", []):
                    try:
                        cur.execute("""
                            INSERT INTO institutional_holders
                                (ticker, fetched_date, holder_name, shares, pct_held, reported_date)
                            VALUES (%s,CURRENT_DATE,%s,%s,%s,%s)
                            ON CONFLICT (ticker, holder_name, fetched_date) DO UPDATE SET
                                shares=EXCLUDED.shares, pct_held=EXCLUDED.pct_held,
                                reported_date=EXCLUDED.reported_date
                        """, (ticker, h.get("name"), h.get("shares"), h.get("pct_held"),
                              h.get("reported_date")))
                    except Exception as _exc:
                        log.warning("Suppressed: %s", _exc)
                tables_written.extend(["ownership_snapshots", "institutional_holders"])

            # insider_transactions (append-only)
            for txn in data.get("ins", {}).get("transactions", []):
                try:
                    cur.execute("""
                        INSERT INTO insider_transactions
                            (ticker, insider_name, title, transaction_date, txn_type, shares,
                             value_usd, fetched_date)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,CURRENT_DATE)
                        ON CONFLICT (ticker, insider_name, transaction_date, txn_type, shares)
                        DO NOTHING
                    """, (ticker, txn.get("insider_name"), txn.get("title"),
                          txn.get("transaction_date"), txn.get("txn_type"),
                          txn.get("shares"), txn.get("value_usd")))
                except Exception as _exc:
                    log.warning("Suppressed: %s", _exc)
            if data.get("ins", {}).get("transactions"):
                tables_written.append("insider_transactions")

            # next_earnings + earnings_surprises
            earn = data.get("earn", {})
            if earn:
                cur.execute("""
                    INSERT INTO next_earnings
                        (ticker, earnings_date, eps_estimate, revenue_low, revenue_high, updated_at)
                    VALUES (%s,%s,%s,%s,%s,NOW())
                    ON CONFLICT (ticker) DO UPDATE SET
                        earnings_date=EXCLUDED.earnings_date,
                        eps_estimate=EXCLUDED.eps_estimate,
                        revenue_low=EXCLUDED.revenue_low,
                        revenue_high=EXCLUDED.revenue_high,
                        updated_at=NOW()
                """, (ticker, earn.get("earnings_date"), earn.get("eps_estimate"),
                      earn.get("revenue_low"), earn.get("revenue_high")))
                for s in earn.get("surprises", []):
                    try:
                        cur.execute("""
                            INSERT INTO earnings_surprises
                                (ticker, period_date, eps_estimate, eps_actual, surprise_pct)
                            VALUES (%s,%s,%s,%s,%s)
                            ON CONFLICT (ticker, period_date) DO UPDATE SET
                                eps_estimate=EXCLUDED.eps_estimate,
                                eps_actual=EXCLUDED.eps_actual,
                                surprise_pct=EXCLUDED.surprise_pct
                        """, (ticker, s.get("period_date"), s.get("eps_estimate"),
                              s.get("eps_actual"), s.get("surprise_pct")))
                    except Exception as _exc:
                        log.warning("Suppressed: %s", _exc)
                tables_written.extend(["next_earnings", "earnings_surprises"])

            # key_management
            for o in data.get("mgmt", {}).get("officers", []):
                try:
                    cur.execute("""
                        INSERT INTO key_management
                            (ticker, name, title, age, total_pay_usd, updated_at)
                        VALUES (%s,%s,%s,%s,%s,NOW())
                        ON CONFLICT (ticker, name) DO UPDATE SET
                            title=EXCLUDED.title, age=EXCLUDED.age,
                            total_pay_usd=EXCLUDED.total_pay_usd, updated_at=NOW()
                    """, (ticker, o.get("name"), o.get("title"),
                          o.get("age"), o.get("total_pay_usd")))
                except Exception as _exc:
                    log.warning("Suppressed: %s", _exc)
            if data.get("mgmt", {}).get("officers"):
                tables_written.append("key_management")

            # peer_comparisons
            for p in data.get("comp", {}).get("peers", []):
                try:
                    cur.execute("""
                        INSERT INTO peer_comparisons
                            (ticker, peer_ticker, fetched_date, peer_name, market_cap_usd,
                             revenue_ttm, ebitda, trailing_pe, pb)
                        VALUES (%s,%s,CURRENT_DATE,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (ticker, peer_ticker, fetched_date) DO UPDATE SET
                            peer_name=EXCLUDED.peer_name,
                            market_cap_usd=EXCLUDED.market_cap_usd,
                            revenue_ttm=EXCLUDED.revenue_ttm,
                            ebitda=EXCLUDED.ebitda,
                            trailing_pe=EXCLUDED.trailing_pe,
                            pb=EXCLUDED.pb
                    """, (ticker, p.get("peer_ticker"), p.get("peer_name"),
                          p.get("market_cap_usd"), p.get("revenue_ttm"),
                          p.get("ebitda"), p.get("trailing_pe"), p.get("pb")))
                except Exception as _exc:
                    log.warning("Suppressed: %s", _exc)
            if data.get("comp", {}).get("peers"):
                tables_written.append("peer_comparisons")

        conn.commit()
        conn.close()
        log.info(f"[store] snapshot persisted for {ticker}: {tables_written}")
        return tables_written
    except Exception as e:
        log.warning(f"[store] WARNING for {ticker}: {e}")
        return []


def main(
    ticker: str,
    portfolio_db: postgresql = {},
    finnhub_key: str = "",
) -> dict:
    """
    Fetch all structured stock data for a single ticker and persist to DB.
    Returns a result dict: {"ticker": ticker, "ok": bool, "tables_written": [...], "error": str|None}
    """
    ticker = ticker.strip().upper()
    t0 = time.time()

    try:
        log.info(f"[fetcher] Starting for {ticker}")

        _, overview_data = _fetch_company_overview(ticker)
        _, fin_data      = _fetch_yfinance_financials(ticker)
        _, val_data      = _fetch_yfinance_valuation(ticker)
        _, own_data      = _fetch_ownership(ticker)
        _, ins_data      = _fetch_insider_transactions(ticker)
        _, earn_data     = _fetch_earnings_calendar(ticker)
        _, mgmt_data     = _fetch_management(ticker)
        _, comp_data     = _fetch_competitors(ticker, finnhub_key)

        tables_written = _store_stock_snapshot(ticker, portfolio_db, {
            "overview": overview_data,
            "fin":      fin_data,
            "val":      val_data,
            "own":      own_data,
            "ins":      ins_data,
            "earn":     earn_data,
            "mgmt":     mgmt_data,
            "comp":     comp_data,
        })

        elapsed = round(time.time() - t0, 1)
        log.info(f"[fetcher] Done for {ticker} in {elapsed}s — tables: {tables_written}")
        return {
            "ticker":         ticker,
            "ok":             True,
            "tables_written": tables_written,
            "error":          None,
        }

    except Exception as e:
        elapsed = round(time.time() - t0, 1)
        msg = str(e)
        log.error(f"[fetcher] ERROR for {ticker} after {elapsed}s: {msg}")
        return {
            "ticker":         ticker,
            "ok":             False,
            "tables_written": [],
            "error":          msg,
        }
