# Requirements:
# psycopg2-binary>=2.9
# openai>=1.30.0
# pytz>=2024.1

"""
Portfolio Rationalization — Monthly deep-scoring analysis.
Scores ~31 positions across 5 factors and 4 weighting scenarios,
applies absolute red-flag checks, completeness penalty, delta tracking,
and synthesises with two sequential Grok-4.3 calls.
Output: emailed HTML report + /root/research/portfolio/rationalization_YYYY-MM-DD.md
        + portfolio_scores DB upsert.
"""

import json
import os
import smtplib
import requests
from datetime import date, datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import psycopg2
import psycopg2.extras
import pytz
from openai import OpenAI
import logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
log = logging.getLogger(__name__)


REPORT_DIR = "/research/portfolio"

# ── Red-flag absolute thresholds (Finding 1) ──────────────────────────────────
NET_DEBT_EBITDA_MAX = 4.0
CURRENT_RATIO_MIN = 0.8
FWD_PE_MAX = 60.0
REV_CAGR_MIN = 0.0     # below 0 → declining revenue
NI_CAGR_MIN = -0.20    # below -20% → earnings deterioration

# ── Percentile pool size guard (Finding 2) ────────────────────────────────────
MIN_POOL_SIZE = 8

# ADR pairs are loaded from portfolio_positions.consolidation_group at runtime (no hardcoded map).


# ── DB helpers ────────────────────────────────────────────────────────────────

WM_BASE      = "http://windmill_server:8000"
WM_WORKSPACE = "admins"


def _dispatch_formatter(formatter_name: str, md_path: str,
                        telegram_bot_token: str, telegram_owner_id: str,
                        portfolio_db: dict, wm_token: str = "") -> str:
    import os as _os
    token = wm_token or _os.environ.get("WM_TOKEN", "")
    if not token:
        log.warning(f"[Dispatch] No WM_TOKEN — cannot dispatch {formatter_name}")
        return ""
    url = f"{WM_BASE}/api/w/{WM_WORKSPACE}/jobs/run/p/u/admin/{formatter_name}"
    args = {"md_path": md_path, "telegram_bot_token": telegram_bot_token,
            "telegram_owner_id": telegram_owner_id, "portfolio_db": portfolio_db}
    try:
        resp = requests.post(url, headers={"Authorization": f"Bearer {token}",
                                           "Content-Type": "application/json"},
                             json=args, timeout=10)
        job_id = resp.text.strip().strip('"')
        log.info(f"[Dispatch] {formatter_name} dispatched job_id={job_id}")
        return job_id
    except Exception as e:
        log.warning(f"[Dispatch] Failed to dispatch {formatter_name}: {e}")
        return ""


def _conn(portfolio_db: dict):
    return psycopg2.connect(
        host=portfolio_db["host"],
        port=portfolio_db["port"],
        dbname=portfolio_db["dbname"],
        user=portfolio_db["user"],
        password=portfolio_db["password"],
    )


def _fetch_research_reports(tickers: list, portfolio_db: dict) -> dict:
    """Return {ticker: (full_content, date_str)} for the latest stock research per ticker.
    Only called when include_research=True. Empty dict on error or missing DB.
    """
    if not portfolio_db or not tickers:
        return {}
    try:
        conn = _conn(portfolio_db)
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT ON (ticker) ticker, content, created_at::date AS report_date
                FROM research_reports
                WHERE ticker = ANY(%s) AND research_type = 'stock'
                ORDER BY ticker, created_at DESC
            """, (tickers,))
            rows = cur.fetchall()
        conn.close()
        return {row[0]: (row[1], str(row[2])) for row in rows}
    except Exception as e:
        log.warning(f"[Research] _fetch_research_reports error: {e}")
        return {}



def _fetch_positions(cur) -> list[dict]:
    """Return all portfolio positions with latest price in USD, sector, and country."""
    cur.execute("""
        WITH latest_price AS (
            SELECT ticker, close_price
            FROM price_history
            WHERE (ticker, price_date) IN (
                SELECT ticker, MAX(price_date) FROM price_history GROUP BY ticker
            )
        ),
        latest_fx AS (
            SELECT from_currency, rate
            FROM fx_rates
            WHERE (from_currency, rate_date) IN (
                SELECT from_currency, MAX(rate_date) FROM fx_rates GROUP BY from_currency
            )
            AND to_currency = 'USD'
        ),
        latest_profile AS (
            SELECT DISTINCT ON (ticker) ticker, sector, country
            FROM company_profiles
            ORDER BY ticker, updated_at DESC NULLS LAST
        )
        SELECT pp.ticker, pp.company_name,
               COALESCE(cp.sector, '—') AS sector,
               COALESCE(cp.country, '—') AS country,
               pp.shares, pp.currency,
               lp.close_price AS price_local,
               CASE WHEN pp.currency = 'USD' THEN lp.close_price
                    ELSE lp.close_price * COALESCE(fx.rate, 1.0)
               END AS price_usd,
               pp.shares * CASE WHEN pp.currency = 'USD' THEN lp.close_price
                                ELSE lp.close_price * COALESCE(fx.rate, 1.0)
                           END AS position_usd
        FROM portfolio_positions pp
        JOIN latest_price lp ON lp.ticker = pp.ticker
        LEFT JOIN latest_fx fx ON fx.from_currency = pp.currency
        LEFT JOIN latest_profile cp ON cp.ticker = pp.ticker
        ORDER BY position_usd DESC NULLS LAST
    """)
    return [dict(row) for row in cur.fetchall()]


def _cagr(v_new, v_old, years):
    """Compute CAGR; handles sign changes gracefully. Returns negative values for negative growth."""
    if v_old is None or v_new is None or v_old == 0 or years <= 0:
        return None
    try:
        ratio = float(v_new) / float(v_old)
        if ratio <= 0:
            # Return a strongly negative sentinel so negative-CAGR names rank at pool minimum.
            # Magnitude is capped at -1.0 to avoid extreme outlier distortion.
            return max(ratio - 1.0, -1.0)
        return ratio ** (1.0 / years) - 1
    except Exception:
        return None


def _fetch_fundamentals(cur, tickers: list[str], price_map: dict[str, float]) -> dict[str, dict]:
    """Pull quantitative metrics from all relevant tables and normalise to logical field names."""
    result = {t: {} for t in tickers}

    # ── valuation_snapshots (latest row per ticker) ────────────────────────────
    cur.execute("""
        SELECT DISTINCT ON (ticker) ticker,
            forward_pe, trailing_pe, peg, ev_ebitda, ev_revenue, p_fcf, pb,
            analyst_target, analyst_rec_mean, analyst_count,
            short_pct_float, beta, fifty_two_wk_high, fifty_two_wk_low
        FROM valuation_snapshots
        WHERE ticker = ANY(%s)
        ORDER BY ticker, fetched_date DESC
    """, (tickers,))
    for row in cur.fetchall():
        d = dict(row)
        t = d.pop("ticker")
        if t not in result:
            continue
        price = price_map.get(t)
        high = d.get("fifty_two_wk_high")
        low  = d.get("fifty_two_wk_low")
        target = d.get("analyst_target")
        result[t].update({
            "forward_pe":       d.get("forward_pe"),
            "trailing_pe":      d.get("trailing_pe"),
            "peg_ratio":        d.get("peg"),
            "ev_to_ebitda":     d.get("ev_ebitda"),
            "ev_to_revenue":    d.get("ev_revenue"),
            "price_to_fcf":     d.get("p_fcf"),
            "price_to_book":    d.get("pb"),
            "analyst_rec_mean": d.get("analyst_rec_mean"),
            "analyst_count":    d.get("analyst_count"),
            "short_interest_pct": d.get("short_pct_float"),
            "beta":             d.get("beta"),
            # Derived: analyst upside % from target vs current price
            "analyst_upside_pct": (
                (float(target) / float(price) - 1)
                if target and price and float(price) > 0 else None
            ),
            # Derived: momentum = where current price sits in 52wk range
            "momentum_52wk": (
                (float(price) - float(low)) / (float(high) - float(low))
                if price and high and low and float(high) != float(low) else None
            ),
        })

    # ── fundamental_data (quality metrics — latest per ticker) ────────────────
    cur.execute("""
        SELECT DISTINCT ON (ticker) ticker,
            roe, roic, net_margin
        FROM fundamental_data
        WHERE ticker = ANY(%s)
        ORDER BY ticker, as_of_date DESC
    """, (tickers,))
    for row in cur.fetchall():
        d = dict(row)
        t = d.pop("ticker")
        if t not in result:
            continue
        result[t].update({
            "return_on_equity":          d.get("roe"),
            "return_on_invested_capital": d.get("roic"),
            "net_profit_margin":         d.get("net_margin"),
        })

    # ── financial_health_metrics (leverage & liquidity) ───────────────────────
    cur.execute("""
        SELECT DISTINCT ON (ticker) ticker,
            net_debt_ebitda, gearing, current_ratio, roe_dupont
        FROM financial_health_metrics
        WHERE ticker = ANY(%s)
        ORDER BY ticker, fetched_date DESC
    """, (tickers,))
    for row in cur.fetchall():
        d = dict(row)
        t = d.pop("ticker")
        if t not in result:
            continue
        result[t].update({
            "net_debt_to_ebitda": d.get("net_debt_ebitda"),
            "gearing":            d.get("gearing"),
            "current_ratio":      d.get("current_ratio"),
        })
        # Fill ROE from DuPont if not yet set
        if result[t].get("return_on_equity") is None and d.get("roe_dupont") is not None:
            result[t]["return_on_equity"] = d.get("roe_dupont")

    # ── income_statements (3yr for CAGR computation) ──────────────────────────
    cur.execute("""
        SELECT ticker, total_revenue, net_income, basic_eps, fiscal_year_end
        FROM income_statements
        WHERE ticker = ANY(%s)
        ORDER BY ticker, fiscal_year_end DESC
    """, (tickers,))
    is_rows: dict[str, list] = {}
    for row in cur.fetchall():
        t = row["ticker"]
        if t not in is_rows:
            is_rows[t] = []
        is_rows[t].append(row)
    for t, rows in is_rows.items():
        if t not in result:
            continue
        if len(rows) >= 2:
            result[t]["revenue_cagr_1yr"] = _cagr(rows[0]["total_revenue"], rows[1]["total_revenue"], 1)
        if len(rows) >= 4:
            result[t]["revenue_cagr_3yr"]    = _cagr(rows[0]["total_revenue"], rows[3]["total_revenue"], 3)
            result[t]["net_income_cagr_3yr"] = _cagr(rows[0]["net_income"],    rows[3]["net_income"],    3)
            result[t]["eps_cagr"]            = _cagr(rows[0]["basic_eps"],     rows[3]["basic_eps"],     3)
        elif len(rows) >= 3:
            result[t]["revenue_cagr_3yr"]    = _cagr(rows[0]["total_revenue"], rows[2]["total_revenue"], 2)
            result[t]["net_income_cagr_3yr"] = _cagr(rows[0]["net_income"],    rows[2]["net_income"],    2)

    # ── cashflow_statements (FCF quality = operating CF / net income) ──────────
    cur.execute("""
        SELECT DISTINCT ON (ticker) ticker, operating_cf, free_cf
        FROM cashflow_statements
        WHERE ticker = ANY(%s)
        ORDER BY ticker, fetched_date DESC
    """, (tickers,))
    for row in cur.fetchall():
        t = row["ticker"]
        op_cf = row["operating_cf"]
        if t not in result:
            continue
        ni_rows = is_rows.get(t, [])
        net_income = ni_rows[0]["net_income"] if ni_rows else None
        if op_cf and net_income and float(net_income) != 0:
            result[t]["fcf_quality"] = min(float(op_cf) / abs(float(net_income)), 2.0)

    # ── earnings_surprises: avg 4Q EPS beat ───────────────────────────────────
    cur.execute("""
        SELECT ticker, AVG(surprise_pct) AS avg_eps_surprise
        FROM earnings_surprises
        WHERE ticker = ANY(%s)
        GROUP BY ticker
    """, (tickers,))
    for row in cur.fetchall():
        t = row["ticker"]
        if t in result:
            result[t]["avg_eps_surprise"] = row["avg_eps_surprise"]

    # ── ownership_snapshots ────────────────────────────────────────────────────
    cur.execute("""
        SELECT DISTINCT ON (ticker) ticker, insider_pct, institutional_pct
        FROM ownership_snapshots
        WHERE ticker = ANY(%s)
        ORDER BY ticker, fetched_date DESC
    """, (tickers,))
    for row in cur.fetchall():
        t = row["ticker"]
        if t in result:
            result[t]["insider_pct"]       = row["insider_pct"]
            result[t]["institutional_pct"] = row["institutional_pct"]

    # ── insider_transactions: net buy/sell last 90d ────────────────────────────
    cur.execute("""
        SELECT ticker, SUM(value_usd) AS net_insider_90d
        FROM insider_transactions
        WHERE ticker = ANY(%s)
          AND transaction_date >= CURRENT_DATE - INTERVAL '90 days'
        GROUP BY ticker
    """, (tickers,))
    for row in cur.fetchall():
        t = row["ticker"]
        if t in result:
            result[t]["net_insider_90d"] = row["net_insider_90d"]

    return result


def _fetch_thesis(cur, tickers: list[str]) -> dict[str, dict]:
    """Pull thesis data for each ticker."""
    cur.execute("""
        SELECT ticker, conviction, key_catalysts, risks, target_price_usd, updated_at
        FROM portfolio_thesis
        WHERE ticker = ANY(%s)
    """, (tickers,))
    out = {}
    for row in cur.fetchall():
        ticker     = row["ticker"]
        conviction = row["conviction"]
        catalysts  = row["key_catalysts"]
        risks      = row["risks"]
        target_price = row["target_price_usd"]
        updated_at = row["updated_at"]
        cats = catalysts if isinstance(catalysts, list) else (list(catalysts) if catalysts else [])
        rsks = risks if isinstance(risks, list) else (list(risks) if risks else [])
        out[ticker] = {
            "conviction": conviction,
            "catalysts": cats,
            "risks": rsks,
            "target_price": target_price,
            "updated_at": updated_at,
        }
    return out


def _fetch_prior_ranks(cur) -> dict[str, dict]:
    """Return {ticker: {balanced, quality, growth, value}} from most recent prior run (A10)."""
    cur.execute("""
        SELECT ticker, rank_balanced, rank_quality, rank_growth, rank_value
        FROM portfolio_scores
        WHERE score_date = (
            SELECT MAX(score_date) FROM portfolio_scores
            WHERE score_date < CURRENT_DATE
        )
    """)
    rows = cur.fetchall()
    return {
        r[0]: {"balanced": r[1], "quality": r[2], "growth": r[3], "value": r[4]}
        for r in rows
    } if rows else {}


# ── ADR consolidation ─────────────────────────────────────────────────────────

def _load_adr_pairs(cur) -> dict:
    """Load {hk_ticker: usd_primary_ticker} from DB consolidation_group column."""
    cur.execute("""
        SELECT ticker, currency, consolidation_group
        FROM portfolio_positions
        WHERE consolidation_group IS NOT NULL
        ORDER BY consolidation_group, currency
    """)
    rows = cur.fetchall()
    groups: dict = {}
    for row in rows:
        grp = row["consolidation_group"]
        ticker = row["ticker"]
        currency = row["currency"]
        if grp not in groups:
            groups[grp] = {"usd": None, "hkd": None}
        if currency == "USD":
            groups[grp]["usd"] = ticker
        else:
            groups[grp]["hkd"] = ticker
    return {v["hkd"]: v["usd"] for v in groups.values() if v["hkd"] and v["usd"]}


def _consolidate_positions(positions: list[dict], adr_pairs: dict) -> list[dict]:
    """Merge HK ADR duplicates into single consolidated position."""
    consolidated = {}
    for pos in positions:
        ticker = pos["ticker"]
        primary = adr_pairs.get(ticker, ticker)
        if primary not in consolidated:
            consolidated[primary] = dict(pos)
            consolidated[primary]["ticker"] = primary
            consolidated[primary]["hk_ticker"] = ticker if ticker != primary else None
        else:
            # Sum position value; keep primary ticker metadata
            consolidated[primary]["position_usd"] = (
                (consolidated[primary].get("position_usd") or 0) +
                (pos.get("position_usd") or 0)
            )
            if ticker != primary:
                consolidated[primary]["hk_ticker"] = ticker
    return list(consolidated.values())


# ── Red-flag evaluation (Finding 1) ──────────────────────────────────────────

def _evaluate_red_flags(metrics: dict) -> list[str]:
    flags = []
    nd_ebitda = metrics.get("net_debt_to_ebitda")
    if nd_ebitda is not None and nd_ebitda > NET_DEBT_EBITDA_MAX:
        flags.append(f"Leverage: net debt/EBITDA = {nd_ebitda:.1f}x (above {NET_DEBT_EBITDA_MAX}x)")
    rev_cagr = metrics.get("revenue_cagr_3yr")
    if rev_cagr is not None and rev_cagr < REV_CAGR_MIN:
        flags.append(f"Declining revenue: 3yr CAGR = {rev_cagr:.1%}")
    fwd_pe = metrics.get("forward_pe")
    if fwd_pe is None or fwd_pe > FWD_PE_MAX:
        if fwd_pe is None:
            flags.append("Rich/unknown valuation: fwd PE absent")
        else:
            flags.append(f"Rich valuation: fwd PE = {fwd_pe:.1f}x (above {FWD_PE_MAX:.0f}x)")
    ni_cagr = metrics.get("net_income_cagr_3yr")
    if ni_cagr is not None and ni_cagr < NI_CAGR_MIN:
        flags.append(f"Earnings deterioration: 3yr NI CAGR = {ni_cagr:.1%}")
    cr = metrics.get("current_ratio")
    if cr is not None and cr < CURRENT_RATIO_MIN:
        flags.append(f"Liquidity risk: current ratio = {cr:.2f} (below {CURRENT_RATIO_MIN})")
    return flags


# ── Factor scoring ─────────────────────────────────────────────────────────────

def _norm(values: list[Optional[float]], v: Optional[float]) -> Optional[float]:
    """Return 0–1 percentile rank of v within non-null values list."""
    if v is None:
        return None
    non_null = [x for x in values if x is not None]
    if len(non_null) < MIN_POOL_SIZE:
        return None
    rank = sum(1 for x in non_null if x < v) / len(non_null)
    return rank


def _compute_factor_scores(positions: list[dict], fund: dict[str, dict]) -> dict[str, dict]:
    """Compute 5 factor raw scores (0–1) using percentile rank within pool."""
    tickers = [p["ticker"] for p in positions]

    def pool(field: str) -> list[Optional[float]]:
        return [fund.get(t, {}).get(field) for t in tickers]

    scores = {}
    for pos in positions:
        t = pos["ticker"]
        m = fund.get(t, {})

        # Quality: ROE, net_margin, (1-net_debt_ebitda), fcf_quality
        roe_n     = _norm(pool("return_on_equity"),     m.get("return_on_equity"))
        margin_n  = _norm(pool("net_profit_margin"),    m.get("net_profit_margin"))
        nd_pool   = [-(x or 0) for x in pool("net_debt_to_ebitda")]  # invert — lower is better
        nd_raw    = m.get("net_debt_to_ebitda")
        nd_n      = _norm(nd_pool, -nd_raw if nd_raw is not None else None)
        fcf_n     = _norm(pool("fcf_quality"),          m.get("fcf_quality"))
        q_factors = [x for x in [roe_n, margin_n, nd_n, fcf_n] if x is not None]
        if q_factors:
            quality = (0.35 * (roe_n or 0) + 0.25 * (margin_n or 0) +
                       0.25 * (nd_n or 0) + 0.15 * (fcf_n or 0))
            quality_available = sum(1 for x in [roe_n, margin_n, nd_n, fcf_n] if x is not None)
        else:
            quality, quality_available = None, 0

        # Growth: rev_cagr_3yr, ni_cagr_3yr, rev_cagr_1yr
        rc3_n = _norm(pool("revenue_cagr_3yr"),    m.get("revenue_cagr_3yr"))
        nc3_n = _norm(pool("net_income_cagr_3yr"), m.get("net_income_cagr_3yr"))
        rc1_n = _norm(pool("revenue_cagr_1yr"),    m.get("revenue_cagr_1yr"))
        g_factors = [x for x in [rc3_n, nc3_n, rc1_n] if x is not None]
        if g_factors:
            growth = (0.4 * (rc3_n or 0) + 0.4 * (nc3_n or 0) + 0.2 * (rc1_n or 0))
            growth_available = sum(1 for x in [rc3_n, nc3_n, rc1_n] if x is not None)
        else:
            growth, growth_available = None, 0

        # Valuation: analyst_upside, (1-fwd_pe), (1-peg), (1-ev_ebitda)
        up_n  = _norm(pool("analyst_upside_pct"), m.get("analyst_upside_pct"))
        fpe_pool = [-(x or 0) for x in pool("forward_pe")]
        fpe_raw  = m.get("forward_pe")
        fpe_n = _norm(fpe_pool, -fpe_raw if fpe_raw is not None else None)
        peg_pool = [-(x or 0) for x in pool("peg_ratio")]
        peg_raw  = m.get("peg_ratio")
        peg_n = _norm(peg_pool, -peg_raw if peg_raw is not None else None)
        ev_pool = [-(x or 0) for x in pool("ev_to_ebitda")]
        ev_raw  = m.get("ev_to_ebitda")
        ev_n = _norm(ev_pool, -ev_raw if ev_raw is not None else None)
        v_factors = [x for x in [up_n, fpe_n, peg_n, ev_n] if x is not None]
        if v_factors:
            valuation = (0.35 * (up_n or 0) + 0.30 * (fpe_n or 0) +
                         0.20 * (peg_n or 0) + 0.15 * (ev_n or 0))
            valuation_available = sum(1 for x in [up_n, fpe_n, peg_n, ev_n] if x is not None)
        else:
            valuation, valuation_available = None, 0

        # Sentiment: analyst_rec_mean (inverted — 1=Strong Buy is best), eps_surprise, momentum, insider
        rec_pool = [-(x or 0) for x in pool("analyst_rec_mean")]
        rec_raw  = m.get("analyst_rec_mean")
        rec_n = _norm(rec_pool, -rec_raw if rec_raw is not None else None)
        eps_n = _norm(pool("avg_eps_surprise"), m.get("avg_eps_surprise"))
        mom_n = _norm(pool("momentum_52wk"),    m.get("momentum_52wk"))
        # Insider: flow ratio (net_insider_90d / market_cap) for cross-size comparability (A4)
        def _insider_flow(ticker_metrics):
            ins = ticker_metrics.get("net_insider_90d")
            mkt = ticker_metrics.get("market_cap")
            if ins is None or mkt is None or mkt == 0:
                return None
            return ins / mkt
        ins_flow_pool = [_insider_flow(fund.get(tk, {})) for tk in tickers]
        ins_n = _norm(ins_flow_pool, _insider_flow(m))
        s_factors = [x for x in [rec_n, eps_n, mom_n, ins_n] if x is not None]
        if s_factors:
            sentiment = (0.35 * (rec_n or 0) + 0.35 * (eps_n or 0) +
                         0.20 * (mom_n or 0) + 0.10 * (ins_n or 0))
            sentiment_available = sum(1 for x in [rec_n, eps_n, mom_n, ins_n] if x is not None)
        else:
            sentiment, sentiment_available = None, 0

        scores[t] = {
            "quality":  quality,
            "growth":   growth,
            "valuation": valuation,
            "sentiment": sentiment,
            "quality_available": quality_available,
            "growth_available": growth_available,
            "valuation_available": valuation_available,
            "sentiment_available": sentiment_available,
        }

    return scores


def _apply_thesis_scores(positions: list[dict], thesis: dict[str, dict]) -> dict[str, dict]:
    """Thesis score = conviction_raw only (Finding 4 — staleness is display-only, not score input)."""
    CONVICTION = {"High": 1.0, "Medium": 0.6, "Low": 0.2}
    out = {}
    today = date.today()
    for pos in positions:
        t = pos["ticker"]
        th = thesis.get(t, {})
        conviction_str = (th.get("conviction") or "").strip()
        score = CONVICTION.get(conviction_str, 0.0)
        updated_at = th.get("updated_at")
        stale_days = None
        if updated_at:
            ref = updated_at.date() if hasattr(updated_at, "date") else updated_at
            stale_days = (today - ref).days
        out[t] = {
            "thesis_score": score,
            "conviction": conviction_str or "none",
            "catalysts": th.get("catalysts", []),
            "risks": th.get("risks", []),
            "target_price": th.get("target_price"),
            "stale_days": stale_days,
            "stale_flag": stale_days is not None and stale_days > 90,
        }
    return out


def _compute_composites(
    positions: list[dict],
    factor_scores: dict[str, dict],
    thesis_scores: dict[str, dict],
) -> dict[str, dict]:
    """Apply 4 weighting scenarios + completeness penalty (Finding 2)."""
    SCENARIOS = {
        "balanced": {"quality": 0.25, "growth": 0.25, "valuation": 0.20, "sentiment": 0.15, "thesis": 0.15},
        "quality":  {"quality": 0.35, "growth": 0.25, "valuation": 0.20, "sentiment": 0.10, "thesis": 0.10},
        "growth":   {"quality": 0.20, "growth": 0.35, "valuation": 0.25, "sentiment": 0.10, "thesis": 0.10},
        "value":    {"quality": 0.20, "growth": 0.20, "valuation": 0.35, "sentiment": 0.15, "thesis": 0.10},
    }
    out = {}
    for pos in positions:
        t = pos["ticker"]
        fs = factor_scores.get(t, {})
        ts = thesis_scores.get(t, {})

        f = {
            "quality":   fs.get("quality"),
            "growth":    fs.get("growth"),
            "valuation": fs.get("valuation"),
            "sentiment": fs.get("sentiment"),
            "thesis":    ts.get("thesis_score"),
        }
        n_available = sum(1 for v in f.values() if v is not None)
        n_total = 5
        completeness_pct = n_available / n_total * 100

        # Metric coverage: raw sub-components present across all 5 factors (A2)
        # Quality=4 subs, Growth=3, Valuation=4, Sentiment=4, Thesis=1 → 16 total
        metric_subs_present = (
            fs.get("quality_available", 0)
            + fs.get("growth_available", 0)
            + fs.get("valuation_available", 0)
            + fs.get("sentiment_available", 0)
            + (1 if ts.get("thesis_score") is not None else 0)
        )
        metric_coverage_pct = metric_subs_present / 16 * 100

        composites = {}
        for scenario_name, weights in SCENARIOS.items():
            raw = sum(
                weights[factor] * value
                for factor, value in f.items()
                if value is not None
            )
            # Renormalise weights for available factors
            w_sum = sum(weights[factor] for factor, value in f.items() if value is not None)
            raw_norm = raw / w_sum if w_sum > 0 else 0.0
            # Apply completeness penalty (Finding 2)
            penalised = raw_norm * (n_available / n_total)
            composites[scenario_name] = round(penalised * 100, 1)

        out[t] = {
            "composites": composites,
            "data_completeness_pct": round(completeness_pct, 1),
            "metric_coverage_pct": round(metric_coverage_pct, 1),
            "n_available_factors": n_available,
        }
    return out


def _rank_positions(positions: list[dict], composites: dict[str, dict]) -> dict[str, dict]:
    """Rank all positions by each scenario composite (descending)."""
    scenarios = ["balanced", "quality", "growth", "value"]
    ranks = {t: {} for t in [p["ticker"] for p in positions]}
    for sc in scenarios:
        ordered = sorted(
            positions,
            key=lambda p: composites.get(p["ticker"], {}).get("composites", {}).get(sc, 0),
            reverse=True,
        )
        for i, p in enumerate(ordered, 1):
            ranks[p["ticker"]][sc] = i
    return ranks


# ── Grok synthesis ────────────────────────────────────────────────────────────

def _call_grok_with_fallback(messages: list[dict], xai_key: str, deepseek_key: str,
                              max_tokens: int = 8000) -> dict:
    """Call Grok-4.3 with deepseek-chat fallback (Finding 7)."""
    try:
        client = OpenAI(api_key=xai_key, base_url="https://api.x.ai/v1")
        resp = client.chat.completions.create(
            model="grok-4.3", messages=messages,
            max_tokens=max_tokens, temperature=0.3,
            extra_body={"reasoning_effort": "medium"},
        )
        return {
            "text": resp.choices[0].message.content.strip(),
            "model": "grok-4.3",
            "input_tokens": resp.usage.prompt_tokens or 0,
            "output_tokens": resp.usage.completion_tokens or 0,
        }
    except Exception as e:
        log.error(f"[Grok] ERROR: {e} — falling back to deepseek-chat")
    try:
        client = OpenAI(api_key=deepseek_key, base_url="https://api.deepseek.com")
        resp = client.chat.completions.create(
            model="deepseek-chat", messages=messages, max_tokens=max_tokens, temperature=0.3,
        )
        return {
            "text": resp.choices[0].message.content.strip(),
            "model": "deepseek-fallback",
            "input_tokens": resp.usage.prompt_tokens or 0,
            "output_tokens": resp.usage.completion_tokens or 0,
        }
    except Exception as e:
        log.error(f"[Deepseek fallback] ERROR: {e}")
    return {
        "text": "*Synthesis failed — both Grok and Deepseek unavailable.*",
        "model": "error",
        "input_tokens": 0,
        "output_tokens": 0,
    }


# ── JSON output parser (C2 — show-your-work) ─────────────────────────────────

def _parse_call1_json(text: str) -> dict[str, dict]:
    """Parse Grok Call 1 output. Returns {ticker: {verdict, rationale_sentences}} or empty on failure.

    Expected JSON structure per position:
    {"ticker": "...", "verdict": "...", "rationale_sentences": [{"text": "...", "evidence": [...]}]}

    Graceful fallback: returns {} if JSON is absent or malformed, so callers
    can fall back to the plain-text narrative path.
    """
    import re
    positions_data = {}
    # Grok may wrap JSON in ```json ... ``` fences or output it inline
    json_block = re.search(r"```json\s*([\s\S]*?)```", text)
    raw = json_block.group(1) if json_block else text
    try:
        parsed = json.loads(raw)
        items = parsed if isinstance(parsed, list) else parsed.get("positions", [])
        for item in items:
            ticker = item.get("ticker", "").upper().strip()
            if ticker:
                positions_data[ticker] = {
                    "verdict": item.get("verdict", ""),
                    "rationale_sentences": item.get("rationale_sentences", []),
                }
        log.info(f"[Call1 JSON] Parsed {len(positions_data)} positions")
    except (json.JSONDecodeError, AttributeError, TypeError) as e:
        log.warning(f"[Call1 JSON] Parse failed ({e}) — falling back to plain-text narrative")
    return positions_data


# ── Report builder ─────────────────────────────────────────────────────────────

def _fmt_pct(v):
    if v is None:
        return "—"
    return f"{v:.1%}"


def _fmt_val(v, decimals=1):
    if v is None:
        return "—"
    return f"{v:.{decimals}f}"


def _apply_red_flag_override(recommendations: dict, red_flags_map: dict) -> dict:
    """Override any KEEP/TRIM recommendation to EXIT when a position has red flags (A11)."""
    overridden = dict(recommendations)
    for ticker, flags in red_flags_map.items():
        if flags and overridden.get(ticker, "").upper() not in ("EXIT",):
            overridden[ticker] = "EXIT (red-flag override)"
    return overridden


def _build_ranking_table(positions, composites, ranks, prior_ranks, red_flags_map):
    lines = [
        "| Ticker | Bal rank | Qual rank | Grwth rank | Val rank | "
        "Bal score | # top-half | Δ rank | Factor coverage | Metric coverage | Red flags |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    sorted_pos = sorted(positions, key=lambda p: ranks.get(p["ticker"], {}).get("balanced", 99))
    for pos in sorted_pos:
        t = pos["ticker"]
        r = ranks.get(t, {})
        c = composites.get(t, {})
        comp = c.get("composites", {})
        prior_d = prior_ranks.get(t, {})
        prior = prior_d.get("balanced") if isinstance(prior_d, dict) else prior_d
        delta = (r.get("balanced", 0) - prior) if prior is not None else None
        delta_str = f"{delta:+d}" if delta is not None else "–"
        # n_top_half: how many scenarios rank this position in the top half (rank-robustness, not a KEEP verdict)
        n_top_half = sum(1 for sc in ["balanced", "quality", "growth", "value"]
                         if r.get(sc, 99) <= len(positions) // 2)
        factor_coverage = c.get("data_completeness_pct", 0)
        metric_coverage = c.get("metric_coverage_pct", 0)
        flags = len(red_flags_map.get(t, []))
        lines.append(
            f"| {t} | {r.get('balanced','?')} | {r.get('quality','?')} | "
            f"{r.get('growth','?')} | {r.get('value','?')} | "
            f"{comp.get('balanced','?')} | {n_top_half}/4 | {delta_str} | "
            f"{factor_coverage:.0f}% | {metric_coverage:.0f}% | {flags} |"
        )
    return "\n".join(lines)


def _build_per_position_block(pos, metrics, thesis_data, composites_data, ranks_data,
                               red_flags, prior_ranks, position_usd_total):
    t = pos["ticker"]
    m = metrics
    th = thesis_data
    r = ranks_data
    c = composites_data
    comp = c.get("composites", {})
    prior_d = prior_ranks.get(t, {})
    prior = prior_d.get("balanced") if isinstance(prior_d, dict) else prior_d
    delta = (r.get("balanced", 0) - prior) if prior is not None else None
    delta_str = f"{delta:+d}" if delta is not None else "—"
    weight_pct = (pos.get("position_usd") or 0) / position_usd_total * 100 if position_usd_total else 0
    completeness = c.get("data_completeness_pct", 0)

    block = [
        f"[{t} | {pos.get('company_name', t)} | {pos.get('sector','?')} | "
        f"{pos.get('country','?')} | ${pos.get('position_usd',0):,.0f} | "
        f"{weight_pct:.1f}% | Completeness: {completeness:.0f}% | Δ rank: {delta_str}]"
    ]
    if red_flags:
        block.append(f"[RED FLAGS: {'; '.join(red_flags)}]")
    block.append(
        f"Valuation: fwd PE={_fmt_val(m.get('forward_pe'))}, "
        f"PEG={_fmt_val(m.get('peg_ratio'))}, "
        f"EV/EBITDA={_fmt_val(m.get('ev_to_ebitda'))}, "
        f"analyst upside={_fmt_pct(m.get('analyst_upside_pct'))}, "
        f"rec mean={_fmt_val(m.get('analyst_rec_mean'))}, "
        f"analyst count={_fmt_val(m.get('analyst_count'),0)}"
    )
    block.append(
        f"Quality: ROE={_fmt_pct(m.get('return_on_equity'))}, "
        f"ROIC={_fmt_pct(m.get('return_on_invested_capital'))}, "
        f"net margin={_fmt_pct(m.get('net_profit_margin'))}, "
        f"net debt/EBITDA={_fmt_val(m.get('net_debt_to_ebitda'))}, "
        f"current ratio={_fmt_val(m.get('current_ratio'))}"
    )
    block.append(
        f"Growth: rev CAGR 1yr={_fmt_pct(m.get('revenue_cagr_1yr'))}, "
        f"3yr={_fmt_pct(m.get('revenue_cagr_3yr'))}, "
        f"NI CAGR 3yr={_fmt_pct(m.get('net_income_cagr_3yr'))}, "
        f"EPS CAGR={_fmt_pct(m.get('eps_cagr'))}"
    )
    block.append(
        f"Sentiment: avg EPS surprise={_fmt_pct(m.get('avg_eps_surprise'))}, "
        f"short interest={_fmt_pct(m.get('short_interest_pct'))}, "
        f"52wk momentum={_fmt_pct(m.get('momentum_52wk'))}"
    )
    block.append(
        f"Ownership: insider={_fmt_pct(m.get('insider_pct'))}, "
        f"institutional={_fmt_pct(m.get('institutional_pct'))}, "
        f"net insider 90d=${_fmt_val(m.get('net_insider_90d'),0)}"
    )
    conviction = th.get("conviction", "none")
    cats = ", ".join(th.get("catalysts", [])[:3]) or "—"
    risks = ", ".join(th.get("risks", [])[:3]) or "—"
    block.append(f"Thesis: conviction={conviction}, catalysts=[{cats}], risks=[{risks}]")
    if th.get("stale_flag"):
        block.append(f"⚠️ Thesis not reviewed in {th.get('stale_days')} days — consider updating")
    return "\n".join(block)


# ── Email ─────────────────────────────────────────────────────────────────────

def _send_email(gmail_smtp: dict, subject: str, body_md: str, body_html: str, to_email: str):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = gmail_smtp["username"]
    msg["To"] = to_email
    msg.attach(MIMEText(body_md, "plain"))
    msg.attach(MIMEText(body_html, "html"))
    with smtplib.SMTP(gmail_smtp["host"], gmail_smtp["port"]) as s:
        s.starttls()
        s.login(gmail_smtp["username"], gmail_smtp["password"])
        s.sendmail(gmail_smtp["username"], to_email, msg.as_string())
    log.info(f"[Email] Sent to {to_email}")


def _md_to_html(md: str) -> str:
    import re
    h = re.sub(r"^# (.+)$", r"<h1>\1</h1>", md, flags=re.MULTILINE)
    h = re.sub(r"^## (.+)$", r"<h2>\1</h2>", h, flags=re.MULTILINE)
    h = re.sub(r"^### (.+)$", r"<h3>\1</h3>", h, flags=re.MULTILINE)
    h = re.sub(r"^#### (.+)$", r"<h4>\1</h4>", h, flags=re.MULTILINE)
    h = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", h)
    h = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', h)
    h = h.replace("\n", "<br>\n")
    return h


# ── Main ──────────────────────────────────────────────────────────────────────

def main(
    portfolio_db: dict,
    gmail_smtp: dict,
    xai_key: str,
    deepseek_key: str,
    recipient_email: str = "",
    include_research: bool = False,
    telegram_bot_token: str = "",
    telegram_owner_id: str = "",
    wm_token: str = "",
):
    today_str = date.today().strftime("%Y-%m-%d")
    log.info(f"[Rationalization] Starting run for {today_str}")

    conn = _conn(portfolio_db)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur_plain = conn.cursor()

    # ── 1. Positions + ADR consolidation ─────────────────────────────────────
    raw_positions = _fetch_positions(cur)
    adr_pairs = _load_adr_pairs(cur)
    positions = _consolidate_positions([dict(p) for p in raw_positions], adr_pairs)
    log.info(f"[Positions] {len(raw_positions)} raw → {len(positions)} consolidated")

    total_usd = sum(p.get("position_usd") or 0 for p in positions)
    tickers = [p["ticker"] for p in positions]
    # Also fetch HK ticker data for ADR pairs
    hk_tickers = [p.get("hk_ticker") for p in positions if p.get("hk_ticker")]
    all_fetch_tickers = tickers + hk_tickers
    # Price map (USD) for computing analyst upside and momentum
    price_map = {p["ticker"]: p.get("price_usd") for p in positions if p.get("price_usd")}

    # ── 2. Fundamentals from DB ────────────────────────────────────────────────
    fund = _fetch_fundamentals(cur, all_fetch_tickers, price_map)
    # Merge HK ticker fundamentals into primary ADR ticker
    for pos in positions:
        hk = pos.get("hk_ticker")
        if hk and hk in fund:
            t = pos["ticker"]
            for k, v in fund[hk].items():
                if k not in fund.get(t, {}) or fund[t].get(k) is None:
                    fund.setdefault(t, {})[k] = v

    thesis = _fetch_thesis(cur, tickers)
    prior_ranks = _fetch_prior_ranks(cur_plain)
    log.info(f"[Prior ranks] {len(prior_ranks)} tickers from prior run")

    # ── 3. Factor scores ──────────────────────────────────────────────────────
    factor_scores = _compute_factor_scores(positions, fund)
    thesis_scores = _apply_thesis_scores(positions, thesis)

    # ── 4. Red flags ──────────────────────────────────────────────────────────
    red_flags_map = {p["ticker"]: _evaluate_red_flags(fund.get(p["ticker"], {})) for p in positions}
    flagged = sum(1 for v in red_flags_map.values() if v)
    log.info(f"[Red flags] {flagged} positions with at least 1 flag")

    # ── 5. Composites + completeness penalty + ranking ────────────────────────
    composites = _compute_composites(positions, factor_scores, thesis_scores)
    ranks = _rank_positions(positions, composites)

    # ── 6. Delta tracking — all 4 scenarios (A10) ────────────────────────────
    delta_map = {}
    for t in tickers:
        prior = prior_ranks.get(t, {})
        cur_r = ranks.get(t, {})
        delta_map[t] = {}
        for sc in ("balanced", "quality", "growth", "value"):
            p = prior.get(sc)
            c = cur_r.get(sc)
            delta_map[t][sc] = (c - p) if (p is not None and c is not None) else None

    # ── 7. Build ranking table ────────────────────────────────────────────────
    ranking_table = _build_ranking_table(positions, composites, ranks, prior_ranks, red_flags_map)

    # ── 8. Build per-position blocks for Grok Call 1 ─────────────────────────
    per_position_blocks = []
    for pos in sorted(positions, key=lambda p: ranks.get(p["ticker"], {}).get("balanced", 99)):
        t = pos["ticker"]
        block = _build_per_position_block(
            pos=pos,
            metrics=fund.get(t, {}),
            thesis_data=thesis_scores.get(t, {}),
            composites_data=composites.get(t, {}),
            ranks_data=ranks.get(t, {}),
            red_flags=red_flags_map.get(t, []),
            prior_ranks=prior_ranks,
            position_usd_total=total_usd,
        )
        per_position_blocks.append(block)

    n_pos = len(positions)
    CALL1_BATCH_SIZE = 15  # Split Call 1 into 2 batches to avoid truncation at max_tokens=8000 (A7)
    call1_batches = [per_position_blocks[:CALL1_BATCH_SIZE], per_position_blocks[CALL1_BATCH_SIZE:]]

    def _build_call1_prompt(batch_blocks, batch_label):
        return f"""You are a senior portfolio manager conducting a monthly rationalization review of a concentrated equity portfolio.
Evaluate positions {batch_label} of {n_pos} total. Target: approximately 15 final positions across the full portfolio. The reader is a finance professional — be analytical and specific, not educational.

IMPORTANT: Positions marked [RED FLAG] carry absolute concerns independent of their relative rank within this portfolio.
These are hard negatives — do not let a high percentile score override a flagged absolute metric.

Positions with data completeness below 60% carry higher uncertainty — name the missing factors and adjust your confidence accordingly.

== SCORING CONTEXT ==
Quantitative factor scores (0–100 percentile rank, completeness-penalized) computed from financial databases.
Four scenarios: Balanced / Quality-focused / Growth-focused / Value-focused.
Data completeness % and Δ rank vs prior month are shown per position.

{ranking_table}

== PER-POSITION DATA (this batch) ==

{chr(10).join(batch_blocks)}

== YOUR OUTPUT ==
Respond with a JSON array, then a plain-text narrative section. The JSON enables auditability.

JSON format:
```json
[
  {{
    "ticker": "TICKER",
    "verdict": "KEEP | TRIM | EXIT",
    "rationale_sentences": [
      {{"text": "sentence text", "evidence": ["metric_name=value", ...]}}
    ]
  }},
  ...
]
```

After the JSON block, also write a human-readable section for each position in this batch (no skipping, no merging):

**[TICKER] — [Company Name]**
Quantitative: [2 sentences — strongest metric, weakest metric; reference any red flags explicitly]
Qualitative: [2 sentences — thesis strength, key catalyst vs. key risk]
Recommendation: KEEP / TRIM / EXIT
Rationale: [2-3 sentences — opportunity cost relative to other positions; note data uncertainty if completeness < 60%]"""

    # ── 8a. Grok Call 1a — first batch (positions 1–{CALL1_BATCH_SIZE}) ──────────
    call1_model = "grok-4.3"
    call1_total_input = 0
    call1_total_output = 0
    per_position_analysis_parts = []
    call1_structured = {}
    for batch_idx, batch_blocks in enumerate(call1_batches):
        if not batch_blocks:
            continue
        start = batch_idx * CALL1_BATCH_SIZE + 1
        end = start + len(batch_blocks) - 1
        batch_label = f"{start}–{end}"
        prompt = _build_call1_prompt(batch_blocks, batch_label)
        log.info(f"[Grok Call 1 batch {batch_idx+1}] Sending {len(batch_blocks)} blocks ({batch_label})...")
        result = _call_grok_with_fallback(
            messages=[{"role": "user", "content": prompt}],
            xai_key=xai_key,
            deepseek_key=deepseek_key,
            max_tokens=8000,
        )
        call1_model = result["model"]
        call1_total_input  += result["input_tokens"]
        call1_total_output += result["output_tokens"]
        log.info(f"[Grok Call 1 batch {batch_idx+1}] Done — model={call1_model}, "
              f"tokens={result['input_tokens']}in/{result['output_tokens']}out")
        per_position_analysis_parts.append(result["text"])
        batch_structured = _parse_call1_json(result["text"])
        call1_structured.update(batch_structured)

    per_position_analysis = "\n\n".join(per_position_analysis_parts)

    # ── 9. Grok Call 2 — Executive summary ────────────────────────────────────
    if prior_ranks:
        top_movers = sorted(
            [(t, (delta_map.get(t) or {}).get("balanced", 0) or 0) for t in tickers if delta_map.get(t) is not None],
            key=lambda x: abs(x[1]), reverse=True
        )[:5]
        delta_summary = "Top rank movers vs prior month:\n" + "\n".join(
            f"  {t}: {d:+d}" for t, d in top_movers
        )
    else:
        delta_summary = "No prior month — baseline established for next month."

    # ── Optional research synthesis ────────────────────────────────────────────
    research_section = ""
    if include_research:
        research_map = _fetch_research_reports(tickers, portfolio_db)
        if research_map:
            log.info(f"[Research] Including research reports for {len(research_map)} positions in Call 2")
            parts = [
                "== QUALITATIVE RESEARCH ON PORTFOLIO POSITIONS ==",
                "Use these reports to enrich the global narrative — reference management quality, "
                "competitive moats, catalysts, and risks where relevant.\n",
            ]
            for t, (content, rdate) in sorted(research_map.items()):
                parts.append(f"### {t} (report date: {rdate})\n{content}\n")
            research_section = "\n".join(parts) + "\n"
        else:
            log.info("[Research] include_research=True but no stock research reports found in DB")

    call2_prompt = f"""You have just completed per-position analysis of {n_pos} portfolio positions for monthly rationalization.
Below are the position verdicts. Generate the executive summary, portfolio construction assessment, and month-over-month commentary.

== POSITION VERDICTS ==
{per_position_analysis}

== PRIOR MONTH DELTA CONTEXT ==
{delta_summary}

{research_section}== YOUR OUTPUT ==

== EXECUTIVE SUMMARY ==
**Consistent KEEPs** (≥3 of 4 scenarios AND your KEEP verdict): [bulleted, one-line reason each]
**Scenario-Sensitive Positions** (rank shifts >10 places between scenarios): [what drives the sensitivity]
**Trim Candidates**: [list, one-line reason each]
**Exit Candidates**: [list, one-line reason each]
**ADR Pair Decisions**: BABA vs 9988.HK — [which to keep and why]; BIDU vs 9888.HK — [which to keep and why]

== PORTFOLIO CONSTRUCTION (post-rationalization) ==
[4-5 sentences: sector balance, geographic balance, market cap distribution, concentration risk, sizing principle for the 15]

== MONTH-OVER-MONTH ==
[2-3 sentences: most notable rank changes and what they suggest about trajectory; or first-run note]"""

    log.info(f"[Grok Call 2] Sending executive summary generation...")
    call2_result = _call_grok_with_fallback(
        messages=[{"role": "user", "content": call2_prompt}],
        xai_key=xai_key,
        deepseek_key=deepseek_key,
        max_tokens=8000,
    )
    executive_summary = call2_result["text"]
    call2_model = call2_result["model"]
    log.info(f"[Grok Call 2] Done — model={call2_model}, "
          f"tokens={call2_result['input_tokens']}in/{call2_result['output_tokens']}out")

    # ── 10. Assemble full report ──────────────────────────────────────────────
    fallback_warnings = []
    if call1_model == "deepseek-fallback":
        fallback_warnings.append("Call 1 (per-position)")
    if call2_model == "deepseek-fallback":
        fallback_warnings.append("Call 2 (executive summary)")

    scorecards = []
    for pos in sorted(positions, key=lambda p: ranks.get(p["ticker"], {}).get("balanced", 99)):
        t = pos["ticker"]
        r = ranks.get(t, {})
        c = composites.get(t, {})
        th = thesis_scores.get(t, {})
        flags = red_flags_map.get(t, [])
        delta_all = delta_map.get(t, {})
        delta = delta_all.get("balanced") if isinstance(delta_all, dict) else delta_all
        delta_str = f"{delta:+d}" if delta is not None else "–"

        card = [
            f"### {t} — {pos.get('company_name', t)}",
            "",
            f"**C1. Quantitative Metrics** | Completeness: {c.get('data_completeness_pct', 0):.0f}% | Δ rank: {delta_str}",
        ]
        if flags:
            card.append(f"\n⚠️ **RED FLAGS:** {' | '.join(flags)}\n")
        m = fund.get(t, {})
        card.extend([
            f"| Metric | Value |",
            f"|---|---|",
            f"| Fwd PE | {_fmt_val(m.get('forward_pe'))} |",
            f"| PEG | {_fmt_val(m.get('peg_ratio'))} |",
            f"| EV/EBITDA | {_fmt_val(m.get('ev_to_ebitda'))} |",
            f"| Analyst upside | {_fmt_pct(m.get('analyst_upside_pct'))} |",
            f"| Analyst rec (1=SB) | {_fmt_val(m.get('analyst_rec_mean'))} |",
            f"| ROE | {_fmt_pct(m.get('return_on_equity'))} |",
            f"| Net margin | {_fmt_pct(m.get('net_profit_margin'))} |",
            f"| Net debt/EBITDA | {_fmt_val(m.get('net_debt_to_ebitda'))} |",
            f"| Current ratio | {_fmt_val(m.get('current_ratio'))} |",
            f"| Rev CAGR 3yr | {_fmt_pct(m.get('revenue_cagr_3yr'))} |",
            f"| NI CAGR 3yr | {_fmt_pct(m.get('net_income_cagr_3yr'))} |",
            f"| 52wk momentum | {_fmt_pct(m.get('momentum_52wk'))} |",
            "",
            f"**C2. Factor Scores** | Balanced rank: {r.get('balanced','?')} | "
            f"Quality rank: {r.get('quality','?')} | Growth rank: {r.get('growth','?')} | "
            f"Value rank: {r.get('value','?')}",
        ])
        card.append("")
        card.append(f"**C4. Investment Thesis** — Conviction: {th.get('conviction','none')}")
        if th.get("stale_flag"):
            card.append(f"⚠️ Thesis not reviewed in {th.get('stale_days')} days — consider updating")
        card.append(f"Catalysts: {', '.join(th.get('catalysts', [])[:3]) or '—'}")
        card.append(f"Risks: {', '.join(th.get('risks', [])[:3]) or '—'}")

        # C3. Show-your-work evidence (C2) — rendered per-position from JSON if available
        structured = call1_structured.get(t, {})
        if structured.get("rationale_sentences"):
            card.append("")
            verdict_tag = structured.get("verdict", "")
            card.append(f"**C3. Analysis (Grok — {call1_model}){' — Verdict: ' + verdict_tag if verdict_tag else ''}**")
            for rs in structured["rationale_sentences"]:
                evidence_str = " | ".join(rs.get("evidence", []))
                ev_note = f" *[{evidence_str}]*" if evidence_str else ""
                card.append(f"- {rs.get('text','')}{ev_note}")

        scorecards.append("\n".join(card))

    report_md = f"""# Portfolio Rationalization Analysis — {today_str}

{executive_summary}

---

## Section B — Multi-Scenario Ranking Matrix

{ranking_table}

---

## Section C — Per-Position Deep Scorecards

### C3. Qualitative Analysis (Grok-4.3)

{per_position_analysis}

---

### Individual Scorecards

{chr(10).join(scorecards)}

---

*Models: Call 1={call1_model}, Call 2={call2_model}*
*Total input tokens: {call1_total_input + call2_result['input_tokens']:,} | Output tokens: {call1_total_output + call2_result['output_tokens']:,}*
"""
    if fallback_warnings:
        report_md += f"\n⚠️ Grok unavailable for {', '.join(fallback_warnings)} — synthesised with deepseek-chat\n"

    # ── 11. Build front-matter + save canonical .md ──────────────────────────
    # Sort by composite balanced score (descending = best first)
    def _composite_score(t):
        return composites.get(t, {}).get("composites", {}).get("balanced") or 0.0
    sorted_by_score = sorted(tickers, key=_composite_score, reverse=True)
    top3_tickers = sorted_by_score[:3]
    bot3_tickers = sorted_by_score[-3:][::-1]

    def _make_entry(t):
        score = composites.get(t, {}).get("composites", {}).get("balanced")
        verdict = call1_structured.get(t, {}).get("verdict", "KEEP").upper()
        return {"ticker": t, "score": round(score, 1) if score is not None else None, "verdict": verdict}

    import json as _json
    tg_today_str = date.today().strftime("%-d %b")
    front_matter = {
        "today_str":   tg_today_str,
        "n_positions": len(tickers),
        "top3":        [_make_entry(t) for t in top3_tickers],
        "bot3":        [_make_entry(t) for t in bot3_tickers],
    }
    # Canonical md: front-matter JSON + executive_summary as narrative + DETAIL separator + full report
    canonical_md = (
        f"```json\n{_json.dumps(front_matter, indent=2)}\n```\n\n"
        f"{executive_summary}\n\n"
        f"<!-- DETAIL -->\n\n"
        + report_md
    )

    os.makedirs(REPORT_DIR, exist_ok=True)
    file_path = os.path.join(REPORT_DIR, f"rationalization_{today_str}.md")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(canonical_md)
    log.info(f"[File] Saved to {file_path}")

    # ── 12. Email ─────────────────────────────────────────────────────────────
    if gmail_smtp:
        html_body = f"""<html><body style="font-family:Georgia,serif;max-width:900px;margin:0 auto;color:#1a1a1a">
<div style="background:#f5f5f0;padding:16px 20px;border-left:4px solid #2c3e50;margin-bottom:24px">
  <strong style="font-size:16px">Portfolio Rationalization — {today_str}</strong><br>
  <span style="color:#666;font-size:13px">{n_pos} positions scored | Target: 15 | Monthly deep analysis</span>
</div>
{_md_to_html(report_md)}
</body></html>"""
        _send_email(gmail_smtp, f"Portfolio Rationalization — {today_str}", report_md, html_body, recipient_email)
    else:
        log.warning("[Email] No gmail_smtp provided — skipping email delivery")

    # ── 13a. Dispatch Telegram formatter ──────────────────────────────────────
    if telegram_bot_token and telegram_owner_id:
        _dispatch_formatter(
            "portfolio_rationalization_telegram", file_path,
            telegram_bot_token, telegram_owner_id,
            portfolio_db, wm_token,
        )

    # ── 13. Upsert portfolio_scores ────────────────────────────────────────────
    upsert_cur = conn.cursor()
    for pos in positions:
        t = pos["ticker"]
        r = ranks.get(t, {})
        c = composites.get(t, {})
        comp = c.get("composites", {})
        th = thesis_scores.get(t, {})
        d = delta_map.get(t, {})
        verdict = call1_structured.get(t, {}).get("verdict", "KEEP").upper()
        upsert_cur.execute("""
            INSERT INTO portfolio_scores (
                score_date, ticker, consolidated_name,
                quality_score, growth_score, valuation_score, sentiment_score, thesis_score,
                composite_score_balanced, composite_score_quality, composite_score_growth, composite_score_value,
                data_completeness_pct, red_flag_count,
                position_usd, portfolio_pct,
                rank_balanced, rank_quality, rank_growth, rank_value,
                delta_rank_balanced, delta_rank_quality, delta_rank_growth, delta_rank_value,
                recommendation
            ) VALUES (
                CURRENT_DATE, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s,
                %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s
            ) ON CONFLICT (score_date, ticker) DO UPDATE SET
                consolidated_name = EXCLUDED.consolidated_name,
                quality_score = EXCLUDED.quality_score,
                growth_score = EXCLUDED.growth_score,
                valuation_score = EXCLUDED.valuation_score,
                sentiment_score = EXCLUDED.sentiment_score,
                thesis_score = EXCLUDED.thesis_score,
                composite_score_balanced = EXCLUDED.composite_score_balanced,
                composite_score_quality = EXCLUDED.composite_score_quality,
                composite_score_growth = EXCLUDED.composite_score_growth,
                composite_score_value = EXCLUDED.composite_score_value,
                data_completeness_pct = EXCLUDED.data_completeness_pct,
                red_flag_count = EXCLUDED.red_flag_count,
                position_usd = EXCLUDED.position_usd,
                portfolio_pct = EXCLUDED.portfolio_pct,
                rank_balanced = EXCLUDED.rank_balanced,
                rank_quality = EXCLUDED.rank_quality,
                rank_growth = EXCLUDED.rank_growth,
                rank_value = EXCLUDED.rank_value,
                delta_rank_balanced = EXCLUDED.delta_rank_balanced,
                delta_rank_quality = EXCLUDED.delta_rank_quality,
                delta_rank_growth = EXCLUDED.delta_rank_growth,
                delta_rank_value = EXCLUDED.delta_rank_value,
                recommendation = EXCLUDED.recommendation
        """, (
            t, pos.get("company_name", t),
            round(factor_scores.get(t, {}).get("quality") or 0, 1) * 100 or None,
            round(factor_scores.get(t, {}).get("growth") or 0, 1) * 100 or None,
            round(factor_scores.get(t, {}).get("valuation") or 0, 1) * 100 or None,
            round(factor_scores.get(t, {}).get("sentiment") or 0, 1) * 100 or None,
            round(th.get("thesis_score") or 0, 1) * 100,
            comp.get("balanced"),
            comp.get("quality"),
            comp.get("growth"),
            comp.get("value"),
            c.get("data_completeness_pct"),
            len(red_flags_map.get(t, [])),
            pos.get("position_usd"),
            (pos.get("position_usd") or 0) / total_usd * 100 if total_usd else None,
            r.get("balanced"),
            r.get("quality"),
            r.get("growth"),
            r.get("value"),
            d.get("balanced"), d.get("quality"), d.get("growth"), d.get("value"),
            verdict,
        ))
    conn.commit()
    log.info(f"[DB] Upserted {len(positions)} rows into portfolio_scores")
    conn.close()

    return {
        "positions_scored": n_pos,
        "flagged_positions": flagged,
        "call1_model": call1_model,
        "call2_model": call2_model,
        "file_path": file_path,
    }
