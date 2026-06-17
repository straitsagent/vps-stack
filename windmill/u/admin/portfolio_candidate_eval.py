# Requirements:
# psycopg2-binary>=2.9
# openai>=1.30.0
# numpy>=1.24.0
# yfinance>=0.2.40
# pytz>=2024.1

"""
Portfolio Candidate Evaluation — On-demand 3-gate ADD/WATCH/PASS verdict.
Gate 1: Absolute red-flag check (same thresholds as portfolio_rationalization).
Gate 2: Portfolio fit — price correlation, fundamental similarity, sector/geo/
        currency overlap, factor gap-fill.
Gate 3: Universe benchmark — peer percentile ranks.
Output: emailed verdict card + portfolio_candidate_evals DB row.
"""

import json
import logging
import smtplib
from datetime import date, datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import numpy as np
import psycopg2
import psycopg2.extras
import pytz
import yfinance as yf
from openai import OpenAI

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ── Thresholds (mirrors portfolio_rationalization.py) ────────────────────────
NET_DEBT_EBITDA_MAX = 4.0
CURRENT_RATIO_MIN   = 0.8
FWD_PE_MAX          = 60.0
REV_CAGR_MIN        = 0.0
NI_CAGR_MIN         = -0.20

min_pool = 5          # Gate 3: minimum peer pool for meaningful percentile ranks (B4)
EVAL_TTL_DAYS = 30    # B11
CURRENCY_SOFT_LIMIT = 0.30   # B8: 30% soft cap for any single non-USD currency


# ── DB helpers ────────────────────────────────────────────────────────────────

def _conn(portfolio_db: dict):
    return psycopg2.connect(
        host=portfolio_db["host"],
        port=portfolio_db["port"],
        dbname=portfolio_db["dbname"],
        user=portfolio_db["user"],
        password=portfolio_db["password"],
    )


def _cagr(v_new, v_old, years):
    """CAGR; handles sign changes. Returns negative for negative growth."""
    if v_old is None or v_new is None or v_old == 0 or years <= 0:
        return None
    try:
        ratio = float(v_new) / float(v_old)
        if ratio <= 0:
            return max(ratio - 1.0, -1.0)
        return ratio ** (1.0 / years) - 1
    except Exception:
        return None


def _norm(values: list, v) -> Optional[float]:
    """0–1 percentile rank of v within non-null values list. Returns None if pool < min_pool."""
    if v is None:
        return None
    non_null = [x for x in values if x is not None]
    if len(non_null) < min_pool:
        return None
    return sum(1 for x in non_null if x < v) / len(non_null)


# ── Red-flag evaluation ───────────────────────────────────────────────────────

def _evaluate_red_flags(metrics: dict) -> list[str]:
    """Same thresholds as portfolio_rationalization._evaluate_red_flags."""
    flags = []
    nd_ebitda = metrics.get("net_debt_to_ebitda")
    if nd_ebitda is not None and nd_ebitda > NET_DEBT_EBITDA_MAX:
        flags.append(f"Leverage: net debt/EBITDA = {nd_ebitda:.1f}x (above {NET_DEBT_EBITDA_MAX}x)")
    rev_cagr = metrics.get("revenue_cagr_3yr")
    if rev_cagr is not None and rev_cagr < REV_CAGR_MIN:
        flags.append(f"Declining revenue: 3yr CAGR = {rev_cagr:.1%}")
    fwd_pe = metrics.get("forward_pe")
    if fwd_pe is None or fwd_pe > FWD_PE_MAX:
        flags.append(
            "Rich/unknown valuation: fwd PE absent" if fwd_pe is None
            else f"Rich valuation: fwd PE = {fwd_pe:.1f}x (above {FWD_PE_MAX:.0f}x)"
        )
    ni_cagr = metrics.get("net_income_cagr_3yr")
    if ni_cagr is not None and ni_cagr < NI_CAGR_MIN:
        flags.append(f"Earnings deterioration: 3yr NI CAGR = {ni_cagr:.1%}")
    cr = metrics.get("current_ratio")
    if cr is not None and cr < CURRENT_RATIO_MIN:
        flags.append(f"Liquidity risk: current ratio = {cr:.2f} (below {CURRENT_RATIO_MIN})")
    return flags


# ── Portfolio freshness check (B10) ──────────────────────────────────────────

def _check_portfolio_baseline_freshness(cur) -> Optional[int]:
    """Return age in days of the most recent portfolio_scores run, or None if table is empty."""
    cur.execute("SELECT MAX(score_date) AS latest FROM portfolio_scores")
    row = cur.fetchone()
    if not row or row["latest"] is None:
        return None
    latest = row["latest"]
    if isinstance(latest, str):
        latest = datetime.strptime(latest, "%Y-%m-%d").date()
    return (date.today() - latest).days


# ── Fundamentals fetcher (single-ticker) ─────────────────────────────────────

def _fetch_fundamentals_for_ticker(cur, ticker: str, price_usd: Optional[float]) -> dict:
    """Pull quantitative metrics for one ticker from all relevant tables."""
    m: dict = {}

    # valuation_snapshots
    cur.execute("""
        SELECT forward_pe, trailing_pe, peg, ev_ebitda, ev_revenue, p_fcf, pb,
               analyst_target, analyst_rec_mean, analyst_count,
               short_pct_float, beta, fifty_two_wk_high, fifty_two_wk_low
        FROM valuation_snapshots WHERE ticker = %s
        ORDER BY fetched_date DESC LIMIT 1
    """, (ticker,))
    row = cur.fetchone()
    if row:
        d = dict(row)
        high, low, target = d.get("fifty_two_wk_high"), d.get("fifty_two_wk_low"), d.get("analyst_target")
        m.update({
            "forward_pe":         d.get("forward_pe"),
            "trailing_pe":        d.get("trailing_pe"),
            "peg_ratio":          d.get("peg"),
            "ev_to_ebitda":       d.get("ev_ebitda"),
            "ev_to_revenue":      d.get("ev_revenue"),
            "price_to_fcf":       d.get("p_fcf"),
            "price_to_book":      d.get("pb"),
            "analyst_rec_mean":   d.get("analyst_rec_mean"),
            "analyst_count":      d.get("analyst_count"),
            "analyst_upside_pct": (
                (float(target) / float(price_usd) - 1)
                if target and price_usd and float(price_usd) > 0 else None
            ),
            "momentum_52wk": (
                (float(price_usd) - float(low)) / (float(high) - float(low))
                if price_usd and high and low and float(high) != float(low) else None
            ),
        })

    # fundamental_data (ROE, ROIC, net_margin)
    cur.execute("""
        SELECT roe, roic, net_margin FROM fundamental_data
        WHERE ticker = %s ORDER BY as_of_date DESC LIMIT 1
    """, (ticker,))
    row = cur.fetchone()
    if row:
        m.update({
            "return_on_equity":          row["roe"],
            "return_on_invested_capital": row["roic"],
            "net_profit_margin":         row["net_margin"],
        })

    # financial_health_metrics
    cur.execute("""
        SELECT net_debt_ebitda, gearing, current_ratio, roe_dupont
        FROM financial_health_metrics WHERE ticker = %s
        ORDER BY fetched_date DESC LIMIT 1
    """, (ticker,))
    row = cur.fetchone()
    if row:
        m.update({
            "net_debt_to_ebitda": row["net_debt_ebitda"],
            "gearing":            row["gearing"],
            "current_ratio":      row["current_ratio"],
        })
        if m.get("return_on_equity") is None and row["roe_dupont"] is not None:
            m["return_on_equity"] = row["roe_dupont"]

    # income_statements (3yr CAGR)
    cur.execute("""
        SELECT total_revenue, net_income, basic_eps, fiscal_year_end
        FROM income_statements WHERE ticker = %s
        ORDER BY fiscal_year_end DESC LIMIT 4
    """, (ticker,))
    rows = cur.fetchall()
    if len(rows) >= 2:
        m["revenue_cagr_1yr"] = _cagr(rows[0]["total_revenue"], rows[1]["total_revenue"], 1)
    if len(rows) >= 4:
        m["revenue_cagr_3yr"]    = _cagr(rows[0]["total_revenue"], rows[3]["total_revenue"], 3)
        m["net_income_cagr_3yr"] = _cagr(rows[0]["net_income"],    rows[3]["net_income"],    3)
    elif len(rows) >= 3:
        m["revenue_cagr_3yr"]    = _cagr(rows[0]["total_revenue"], rows[2]["total_revenue"], 2)
        m["net_income_cagr_3yr"] = _cagr(rows[0]["net_income"],    rows[2]["net_income"],    2)

    # cashflow_statements (FCF quality)
    cur.execute("""
        SELECT operating_cf, free_cf FROM cashflow_statements
        WHERE ticker = %s ORDER BY fetched_date DESC LIMIT 1
    """, (ticker,))
    row = cur.fetchone()
    if row and rows:
        op_cf = row["operating_cf"]
        net_income = rows[0]["net_income"] if rows else None
        if op_cf and net_income and float(net_income) != 0:
            m["fcf_quality"] = min(float(op_cf) / abs(float(net_income)), 2.0)

    # earnings_surprises (avg 4Q beat)
    cur.execute("""
        SELECT AVG(surprise_pct) AS avg_eps_surprise FROM earnings_surprises
        WHERE ticker = %s
    """, (ticker,))
    row = cur.fetchone()
    if row and row["avg_eps_surprise"] is not None:
        m["avg_eps_surprise"] = row["avg_eps_surprise"]

    # ownership + insider flow
    cur.execute("""
        SELECT insider_pct, institutional_pct FROM ownership_snapshots
        WHERE ticker = %s ORDER BY fetched_date DESC LIMIT 1
    """, (ticker,))
    row = cur.fetchone()
    if row:
        m["insider_pct"] = row["insider_pct"]
        m["institutional_pct"] = row["institutional_pct"]

    cur.execute("""
        SELECT SUM(value_usd) AS net_insider_90d FROM insider_transactions
        WHERE ticker = %s AND transaction_date >= CURRENT_DATE - INTERVAL '90 days'
    """, (ticker,))
    row = cur.fetchone()
    if row and row["net_insider_90d"] is not None:
        m["net_insider_90d"] = row["net_insider_90d"]

    # company profile
    cur.execute("""
        SELECT sector, industry, country, exchange FROM company_profiles
        WHERE ticker = %s LIMIT 1
    """, (ticker,))
    row = cur.fetchone()
    if row:
        m["sector"]   = row["sector"]
        m["industry"] = row["industry"]
        m["country"]  = row["country"]
        m["exchange"] = row["exchange"]

    return m


# ── Compute factor scores (single ticker vs a pool) ───────────────────────────

def _compute_factor_scores_single(candidate_metrics: dict, pool_metrics: list[dict]) -> dict:
    """Compute 4 factor 0–1 percentile ranks for a candidate against pool_metrics list."""
    all_metrics = pool_metrics + [candidate_metrics]

    def pool(field): return [m.get(field) for m in all_metrics]

    m = candidate_metrics

    roe_n    = _norm(pool("return_on_equity"),  m.get("return_on_equity"))
    margin_n = _norm(pool("net_profit_margin"), m.get("net_profit_margin"))
    nd_pool  = [-(x or 0) for x in pool("net_debt_to_ebitda")]
    nd_raw   = m.get("net_debt_to_ebitda")
    nd_n     = _norm(nd_pool, -nd_raw if nd_raw is not None else None)
    fcf_n    = _norm(pool("fcf_quality"), m.get("fcf_quality"))
    q_facts  = [x for x in [roe_n, margin_n, nd_n, fcf_n] if x is not None]
    quality  = (0.35*(roe_n or 0) + 0.25*(margin_n or 0) +
                0.25*(nd_n or 0) + 0.15*(fcf_n or 0)) if q_facts else None

    rc3_n = _norm(pool("revenue_cagr_3yr"),    m.get("revenue_cagr_3yr"))
    nc3_n = _norm(pool("net_income_cagr_3yr"), m.get("net_income_cagr_3yr"))
    rc1_n = _norm(pool("revenue_cagr_1yr"),    m.get("revenue_cagr_1yr"))
    g_facts = [x for x in [rc3_n, nc3_n, rc1_n] if x is not None]
    growth  = (0.4*(rc3_n or 0) + 0.4*(nc3_n or 0) + 0.2*(rc1_n or 0)) if g_facts else None

    up_n   = _norm(pool("analyst_upside_pct"), m.get("analyst_upside_pct"))
    fpe_pool = [-(x or 0) for x in pool("forward_pe")]
    fpe_n  = _norm(fpe_pool, -(m.get("forward_pe") or 0) if m.get("forward_pe") is not None else None)
    peg_pool = [-(x or 0) for x in pool("peg_ratio")]
    peg_n  = _norm(peg_pool, -(m.get("peg_ratio") or 0) if m.get("peg_ratio") is not None else None)
    ev_pool  = [-(x or 0) for x in pool("ev_to_ebitda")]
    ev_n   = _norm(ev_pool, -(m.get("ev_to_ebitda") or 0) if m.get("ev_to_ebitda") is not None else None)
    v_facts = [x for x in [up_n, fpe_n, peg_n, ev_n] if x is not None]
    valuation = (0.35*(up_n or 0) + 0.30*(fpe_n or 0) +
                 0.20*(peg_n or 0) + 0.15*(ev_n or 0)) if v_facts else None

    rec_pool = [-(x or 0) for x in pool("analyst_rec_mean")]
    rec_n  = _norm(rec_pool, -(m.get("analyst_rec_mean") or 0) if m.get("analyst_rec_mean") is not None else None)
    eps_n  = _norm(pool("avg_eps_surprise"), m.get("avg_eps_surprise"))
    mom_n  = _norm(pool("momentum_52wk"),    m.get("momentum_52wk"))
    ins_flow_pool = [
        (x.get("net_insider_90d") or 0) / max(x.get("market_cap") or 1, 1)
        for x in all_metrics
    ]
    ins_flow_cand = (
        (m.get("net_insider_90d") or 0) / max(m.get("market_cap") or 1, 1)
        if m.get("net_insider_90d") is not None else None
    )
    ins_n  = _norm(ins_flow_pool, ins_flow_cand)
    s_facts = [x for x in [rec_n, eps_n, mom_n, ins_n] if x is not None]
    sentiment = (0.35*(rec_n or 0) + 0.35*(eps_n or 0) +
                 0.20*(mom_n or 0) + 0.10*(ins_n or 0)) if s_facts else None

    return {
        "quality": round(quality * 100, 1) if quality is not None else None,
        "growth":  round(growth  * 100, 1) if growth  is not None else None,
        "valuation": round(valuation * 100, 1) if valuation is not None else None,
        "sentiment": round(sentiment * 100, 1) if sentiment is not None else None,
    }


# ── Gate 2: price correlation (B1) ───────────────────────────────────────────

def _compute_correlation(ticker: str, cur) -> dict:
    """Compute max Pearson correlation between candidate 90d returns and existing positions.
    B1: guard on date range — fallback to yfinance if <60d available; gate2_warn if <30d candidate data.
    """
    gate2_warn = None

    # Fetch existing positions' price history
    cur.execute("""
        SELECT ticker, price_date, close_price FROM price_history
        WHERE price_date >= CURRENT_DATE - INTERVAL '95 days'
        ORDER BY ticker, price_date
    """)
    rows = cur.fetchall()

    existing_prices: dict[str, dict] = {}
    for r in rows:
        existing_prices.setdefault(r["ticker"], {})[r["price_date"]] = float(r["close_price"])

    # Check data coverage for any existing ticker
    max_existing_days = max((len(v) for v in existing_prices.values()), default=0)
    if max_existing_days < 60:
        log.warning("[Correlation] Existing price history <60d — fetching via yfinance")
        existing_prices = {}  # trigger yfinance fallback below

    # Fetch candidate prices
    try:
        df = yf.download(ticker, period="3mo", progress=False, auto_adjust=True)
        candidate_prices = {
            d.date() if hasattr(d, "date") else d: float(p)
            for d, p in zip(df.index, df["Close"].squeeze())
            if p is not None
        }
    except Exception as e:
        log.error(f"[Correlation] yfinance failed for {ticker}: {e}")
        candidate_prices = {}

    n_cand = len(candidate_prices)
    if n_cand < 30:
        gate2_warn = "insufficient_history"
        log.warning(f"[Correlation] Only {n_cand} days of candidate data — insufficient_history")
    if n_cand < 60 or not existing_prices:
        # Fallback: use yfinance for both sides
        existing_prices = {}
        cur.execute("SELECT DISTINCT ticker FROM portfolio_positions")
        ex_tickers = [r["ticker"] for r in cur.fetchall()]
        for t in ex_tickers[:10]:  # limit yfinance calls
            try:
                df_ex = yf.download(t, period="3mo", progress=False, auto_adjust=True)
                existing_prices[t] = {
                    d.date() if hasattr(d, "date") else d: float(p)
                    for d, p in zip(df_ex.index, df_ex["Close"].squeeze())
                    if p is not None
                }
            except Exception:
                pass

    # Compute returns and Pearson correlation
    max_corr = 0.0
    closest_existing = None
    cand_dates = sorted(candidate_prices.keys())
    if len(cand_dates) < 2:
        return {"max_corr": None, "closest_existing": None, "gate2_warn": gate2_warn}

    cand_rets = [
        (candidate_prices[cand_dates[i]] / candidate_prices[cand_dates[i-1]] - 1)
        for i in range(1, len(cand_dates))
    ]
    for ex_ticker, ex_prices in existing_prices.items():
        ex_dates = sorted(ex_prices.keys())
        common = sorted(set(cand_dates) & set(ex_dates))
        if len(common) < 20:
            continue
        c_rets = [
            (candidate_prices[common[i]] / candidate_prices[common[i-1]] - 1)
            for i in range(1, len(common))
        ]
        e_rets = [
            (ex_prices[common[i]] / ex_prices[common[i-1]] - 1)
            for i in range(1, len(common))
        ]
        if len(c_rets) < 10 or len(e_rets) < 10:
            continue
        try:
            corr = float(np.corrcoef(c_rets, e_rets)[0, 1])
            if not np.isnan(corr) and abs(corr) > abs(max_corr):
                max_corr = corr
                closest_existing = ex_ticker
        except Exception:
            pass

    return {
        "max_corr": round(max_corr, 3) if closest_existing else None,
        "closest_existing": closest_existing,
        "gate2_warn": gate2_warn,
    }


# ── Gate 2: fundamental cosine similarity (B2) ───────────────────────────────

def _compute_fundamental_similarity(candidate_metrics: dict, cur) -> dict:
    """Cosine similarity of (sector, country, factor-triplet vector) vs existing positions.
    Returns {max_fundamental_sim, closest_fundamental}.
    """
    cur.execute("""
        SELECT DISTINCT ON (pp.ticker) pp.ticker, cp.sector, cp.country,
               ps.quality_score, ps.growth_score, ps.valuation_score, ps.sentiment_score
        FROM portfolio_positions pp
        LEFT JOIN company_profiles cp ON cp.ticker = pp.ticker
        LEFT JOIN portfolio_scores ps ON ps.ticker = pp.ticker
            AND ps.score_date = (SELECT MAX(score_date) FROM portfolio_scores)
        ORDER BY pp.ticker
    """)
    rows = cur.fetchall()
    if not rows:
        return {"max_fundamental_sim": None, "closest_fundamental": None}

    # Build sector/country sets for one-hot encoding
    all_sectors  = list({r["sector"] or "" for r in rows} | {candidate_metrics.get("sector", "")})
    all_countries = list({r["country"] or "" for r in rows} | {candidate_metrics.get("country", "")})

    def _vec(sector, country, q, g, v, s):
        sec_oh  = [1.0 if sector  == x else 0.0 for x in all_sectors]
        cty_oh  = [1.0 if country == x else 0.0 for x in all_countries]
        factors = [float(q or 50)/100, float(g or 50)/100,
                   float(v or 50)/100, float(s or 50)/100]
        return np.array(sec_oh + cty_oh + factors, dtype=float)

    def _cosine(a, b):
        denom = np.linalg.norm(a) * np.linalg.norm(b)
        return float(np.dot(a, b) / denom) if denom > 0 else 0.0

    cand_vec = _vec(
        candidate_metrics.get("sector", ""), candidate_metrics.get("country", ""),
        candidate_metrics.get("quality_score"), candidate_metrics.get("growth_score"),
        candidate_metrics.get("valuation_score"), candidate_metrics.get("sentiment_score"),
    )

    max_sim = 0.0
    closest = None
    for row in rows:
        ex_vec = _vec(
            row["sector"] or "", row["country"] or "",
            row["quality_score"], row["growth_score"],
            row["valuation_score"], row["sentiment_score"],
        )
        sim = _cosine(cand_vec, ex_vec)
        if sim > max_sim:
            max_sim = sim
            closest = row["ticker"]

    return {
        "max_fundamental_sim": round(max_sim, 3),
        "closest_fundamental": closest,
    }


# ── Gate 2: sector/geo overlap ────────────────────────────────────────────────

def _compute_sector_geo_overlap(ticker: str, candidate_metrics: dict, cur,
                                 exclude_ticker: Optional[str] = None) -> dict:
    """Count existing positions in same sector and country."""
    query = """
        SELECT cp.sector, cp.country FROM portfolio_positions pp
        LEFT JOIN company_profiles cp ON cp.ticker = pp.ticker
        WHERE pp.ticker != %s
    """
    params = [ticker]
    if exclude_ticker:
        query += " AND pp.ticker != %s"
        params.append(exclude_ticker)
    cur.execute(query, params)
    rows = cur.fetchall()

    cand_sector  = (candidate_metrics.get("sector")  or "").lower()
    cand_country = (candidate_metrics.get("country") or "").lower()
    sector_count  = sum(1 for r in rows if (r["sector"]  or "").lower() == cand_sector  and cand_sector)
    country_count = sum(1 for r in rows if (r["country"] or "").lower() == cand_country and cand_country)
    return {"sector_match_count": sector_count, "country_match_count": country_count}


# ── Gate 2: currency exposure (B8) ───────────────────────────────────────────

def _compute_currency_exposure(ticker: str, candidate_currency: str, cur,
                                exclude_ticker: Optional[str] = None) -> dict:
    """Compute current and post-addition currency exposure % for candidate's currency."""
    # Fetch current portfolio USD values by currency
    query = """
        SELECT pp.currency,
               pp.shares * CASE WHEN pp.currency = 'USD' THEN lp.close_price
                                ELSE lp.close_price * COALESCE(fx.rate, 1.0) END AS position_usd
        FROM portfolio_positions pp
        JOIN (
            SELECT ticker, close_price FROM price_history
            WHERE (ticker, price_date) IN (
                SELECT ticker, MAX(price_date) FROM price_history GROUP BY ticker
            )
        ) lp ON lp.ticker = pp.ticker
        LEFT JOIN (
            SELECT from_currency, rate FROM fx_rates
            WHERE (from_currency, rate_date) IN (
                SELECT from_currency, MAX(rate_date) FROM fx_rates GROUP BY from_currency
            )
            AND to_currency = 'USD'
        ) fx ON fx.from_currency = pp.currency
        WHERE pp.ticker != %s
    """
    params = [ticker]
    if exclude_ticker:
        query += " AND pp.ticker != %s"
        params.append(exclude_ticker)
    cur.execute(query, params)
    rows = cur.fetchall()

    total_usd = sum(float(r["position_usd"] or 0) for r in rows)
    currency_usd = sum(
        float(r["position_usd"] or 0) for r in rows
        if (r["currency"] or "USD") == candidate_currency and candidate_currency != "USD"
    )

    # Post-addition exposure (assume 1% of total portfolio for the new position as a conservative proxy)
    # Use median existing position value to estimate the added weight
    if rows:
        median_pos = sorted([float(r["position_usd"] or 0) for r in rows])[len(rows)//2]
    else:
        median_pos = 0.0
    total_post = total_usd + median_pos
    currency_post_usd = currency_usd + (median_pos if candidate_currency != "USD" else 0)
    currency_post_pct = (currency_post_usd / total_post * 100) if total_post > 0 and candidate_currency != "USD" else 0.0
    currency_breach = currency_post_pct > (CURRENCY_SOFT_LIMIT * 100)

    return {
        "currency_post_pct": round(currency_post_pct, 1),
        "currency_breach": currency_breach,
    }


# ── Gate 2: factor gap fill (B3) ─────────────────────────────────────────────

def _compute_factor_gap(candidate_scores: dict, cur) -> dict:
    """Identify factors the candidate fills that the existing portfolio lacks.
    Condition: pool_median_F < 50 AND candidate_F > pool_p60_F.
    """
    cur.execute("""
        SELECT quality_score, growth_score, valuation_score, sentiment_score
        FROM portfolio_scores
        WHERE score_date = (SELECT MAX(score_date) FROM portfolio_scores)
    """)
    rows = cur.fetchall()
    if not rows:
        return {"gap_factors": [], "fill_factors": []}

    factors = ["quality", "growth", "valuation", "sentiment"]
    field_map = {
        "quality":   "quality_score",
        "growth":    "growth_score",
        "valuation": "valuation_score",
        "sentiment": "sentiment_score",
    }

    gap_factors = []
    fill_factors = []
    for f in factors:
        vals = [float(r[field_map[f]] or 0) for r in rows if r[field_map[f]] is not None]
        if not vals:
            continue
        vals_sorted = sorted(vals)
        pool_median_F = float(np.median(vals_sorted))
        n = len(vals_sorted)
        pool_p60_F = float(vals_sorted[min(int(n * 0.6), n-1)])
        cand_f = candidate_scores.get(f)
        if pool_median_F < 50:
            gap_factors.append(f)
        if pool_median_F < 50 and cand_f is not None and cand_f > pool_p60_F:
            fill_factors.append(f)

    return {"gap_factors": gap_factors, "fill_factors": fill_factors}


# ── Gate 2: sizing headroom ───────────────────────────────────────────────────

def _compute_sizing_headroom(cur) -> dict:
    cur.execute("""
        SELECT portfolio_pct FROM portfolio_scores
        WHERE score_date = (SELECT MAX(score_date) FROM portfolio_scores)
        AND portfolio_pct IS NOT NULL
    """)
    rows = cur.fetchall()
    if not rows:
        return {"smallest_pct": None, "median_pct": None, "largest_pct": None}
    vals = sorted([float(r["portfolio_pct"]) for r in rows])
    n = len(vals)
    return {
        "smallest_pct": vals[0],
        "median_pct": vals[n // 2],
        "largest_pct": vals[-1],
    }


# ── Gate 3: universe fetcher ──────────────────────────────────────────────────

def _fetch_universe(ticker: str, universe_tickers: list, cur) -> dict:
    """Fetch peer metrics from peer_comparisons, or use user-supplied universe_tickers."""
    if universe_tickers:
        peers = universe_tickers
    else:
        cur.execute("""
            SELECT DISTINCT peer_ticker FROM peer_comparisons
            WHERE ticker = %s
            ORDER BY peer_ticker
        """, (ticker,))
        peers = [r["peer_ticker"] for r in cur.fetchall()]

    universe_size = len(peers)
    thin_universe = universe_size < min_pool
    below_min_universe = universe_size < 3

    # Fetch peer fundamentals from DB
    peer_metrics = []
    for p in peers:
        pm = _fetch_fundamentals_for_ticker(cur, p, price_usd=None)
        peer_metrics.append(pm)

    return {
        "universe_tickers": peers,
        "universe_size": universe_size,
        "thin_universe": thin_universe,
        "below_min_universe": below_min_universe,
        "peer_metrics": peer_metrics,
    }


# ── B9: Universe heterogeneity validator ─────────────────────────────────────

def _validate_universe(universe_tickers: list, cur) -> bool:
    """Return True (heterogeneity warning) if user-supplied universe is heterogeneous:
    market-cap CoV>2, >3 distinct sectors, or >2 distinct countries.
    """
    if not universe_tickers:
        return False
    cur.execute("""
        SELECT cp.sector, cp.country, ps.quality_score
        FROM company_profiles cp
        LEFT JOIN (
            SELECT DISTINCT ON (ticker) ticker, quality_score
            FROM portfolio_scores ORDER BY ticker, score_date DESC
        ) ps ON ps.ticker = cp.ticker
        WHERE cp.ticker = ANY(%s)
    """, (universe_tickers,))
    rows = cur.fetchall()
    sectors   = {r["sector"] for r in rows if r["sector"]}
    countries = {r["country"] for r in rows if r["country"]}
    if len(sectors) > 3 or len(countries) > 2:
        return True
    return False


# ── Grok call with fallback ───────────────────────────────────────────────────

def _call_grok_with_fallback(messages: list, xai_key: str, deepseek_key: str,
                              max_tokens: int = 3000) -> dict:
    try:
        client = OpenAI(api_key=xai_key, base_url="https://api.x.ai/v1")
        resp = client.chat.completions.create(
            model="grok-4.3", messages=messages, max_tokens=max_tokens, temperature=0.3,
            extra_body={"reasoning_effort": "medium"},
        )
        return {
            "text": resp.choices[0].message.content.strip(),
            "model": "grok-4.3",
            "input_tokens": resp.usage.prompt_tokens or 0,
            "output_tokens": resp.usage.completion_tokens or 0,
        }
    except Exception as e:
        log.error(f"[Grok] {e} — falling back to deepseek-chat")
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
        log.error(f"[Deepseek fallback] {e}")
    return {
        "text": "*Synthesis failed — both Grok and Deepseek unavailable.*",
        "model": "error",
        "input_tokens": 0,
        "output_tokens": 0,
    }


# ── Grok prompt assembly ──────────────────────────────────────────────────────

def _assemble_prompt(
    ticker: str, company_name: str, metrics: dict, red_flags: list,
    gate1_status: str, corr_result: dict, fund_sim: dict, overlap: dict,
    currency_result: dict, gap_result: dict, sizing: dict,
    universe_info: dict, portfolio_scores: dict, thesis_text: str,
    replacement_ticker: Optional[str],
) -> str:
    universe_size = universe_info["universe_size"]
    thin_flag = " — THIN UNIVERSE, treat with lower confidence" if universe_info["thin_universe"] else ""
    u_tickers = ", ".join(universe_info["universe_tickers"][:10]) or "none found"

    q_pct = portfolio_scores.get("quality")
    g_pct = portfolio_scores.get("growth")
    v_pct = portfolio_scores.get("valuation")
    s_pct = portfolio_scores.get("sentiment")
    q_uni = universe_info.get("universe_q")
    g_uni = universe_info.get("universe_g")
    v_uni = universe_info.get("universe_v")
    s_uni = universe_info.get("universe_s")

    thesis_block = (
        thesis_text.strip() if thesis_text.strip()
        else "[NO USER-SUPPLIED THESIS — analysis limited to quantitative factors; "
             "qualitative context is LLM-derived and not user-validated]"
    )

    replacement_note = (
        f"\nNOTE: Evaluate also assuming {replacement_ticker} is exited simultaneously. "
        f"Gate 2 sector/country/currency counts have been recomputed net of {replacement_ticker}. "
        f"Show both outcomes: 'ADD if {replacement_ticker} also exited / WATCH if portfolio held intact'."
        if replacement_ticker else ""
    )

    def fmt(v): return f"{v:.1f}" if v is not None else "N/A"
    def fmtpct(v): return f"{v:.1%}" if v is not None else "N/A"

    return f"""SYSTEM: You are a quantitative portfolio analyst producing a structured verdict card for a stock being evaluated for portfolio addition. Be analytical and specific. Finance-professional tone — no educational framing.

USER:
== CANDIDATE EVALUATION =={replacement_note}
Candidate: {ticker} ({company_name}) | Sector: {metrics.get("sector", "N/A")} | Country: {metrics.get("country", "N/A")}
Date: {date.today().isoformat()}

== GATE 1 — ABSOLUTE CHECK ==
Red flags: {"; ".join(red_flags) if red_flags else "None"}
Gate 1 status: {gate1_status.upper()}

== GATE 2 — PORTFOLIO FIT ==
Price correlation: {fmt(corr_result.get("max_corr"))} (closest match: {corr_result.get("closest_existing", "N/A")}){(" ⚠️ " + corr_result["gate2_warn"]) if corr_result.get("gate2_warn") else ""}
Fundamental similarity: {fmt(fund_sim.get("max_fundamental_sim"))} (closest match: {fund_sim.get("closest_fundamental", "N/A")})
Sector overlap: {overlap.get("sector_match_count", 0)} existing positions in same sector
Country overlap: {overlap.get("country_match_count", 0)} existing positions in same country
Currency exposure post-addition ({metrics.get("currency", "USD")}): {fmt(currency_result.get("currency_post_pct"))}%{" ⚠️ above 30% soft limit" if currency_result.get("currency_breach") else ""}
Portfolio factor gaps (below pool median): {", ".join(gap_result.get("gap_factors", [])) or "none"}
Candidate fills gap in: {", ".join(gap_result.get("fill_factors", [])) or "none"} (pool_median_F<50 AND candidate_F>pool_p60_F)
Sizing headroom: Smallest existing position {fmt(sizing.get("smallest_pct"))}%, median {fmt(sizing.get("median_pct"))}%

== GATE 3 — UNIVERSE BENCHMARK ==
Universe: {u_tickers} ({universe_size} peers{thin_flag})
Candidate vs universe — Quality: {fmt(q_uni)}th pct | Growth: {fmt(g_uni)}th pct | Valuation: {fmt(v_uni)}th pct

== PER-FACTOR TRIPLETS ==
Quality:   absolute={gate1_status}, vs portfolio={fmt(q_pct)}th pct, vs universe={fmt(q_uni)}th pct
Growth:    absolute={gate1_status}, vs portfolio={fmt(g_pct)}th pct, vs universe={fmt(g_uni)}th pct
Valuation: absolute={gate1_status}, vs portfolio={fmt(v_pct)}th pct, vs universe={fmt(v_uni)}th pct
Sentiment: absolute={gate1_status}, vs portfolio={fmt(s_pct)}th pct, vs universe={fmt(s_uni)}th pct

== KEY METRICS ==
fwd_pe={fmt(metrics.get("forward_pe"))} | ev_ebitda={fmt(metrics.get("ev_to_ebitda"))} | rev_cagr_3yr={fmtpct(metrics.get("revenue_cagr_3yr"))} | ni_cagr_3yr={fmtpct(metrics.get("net_income_cagr_3yr"))} | roe={fmtpct(metrics.get("return_on_equity"))} | net_margin={fmtpct(metrics.get("net_profit_margin"))} | current_ratio={fmt(metrics.get("current_ratio"))} | net_debt_ebitda={fmt(metrics.get("net_debt_to_ebitda"))}

== THESIS ==
{thesis_block}

== OUTPUT FORMAT (exact — structured JSON then verdict card) ==

Respond with a JSON object, then the human-readable verdict card.

```json
{{
  "verdict": "ADD | WATCH | PASS",
  "binding_constraint": "one sentence: the single factor that, if changed, would flip this verdict",
  "rationale_sentences": [
    {{
      "text": "sentence text",
      "evidence": ["metric_name=value", "metric_name=value"]
    }}
  ],
  "thesis_source": "user-supplied | llm-derived"
}}
```

After the JSON block, render the human-readable verdict card:

**VERDICT: [ADD | WATCH | PASS]**
**Binding constraint:** [One sentence]

**Gate summary:**
- Gate 1 (Absolute): [one sentence]
- Gate 2 (Portfolio fit): [one sentence on price correlation + fundamental similarity + concentration + gap fill + currency]
- Gate 3 (Universe): [one sentence on peer ranking]

**Sizing recommendation (ADD/WATCH only):** [Suggested weight %; skip for PASS]

**Watch items:** [2–3 bullet points]

{("⚠️ No user-supplied thesis — qualitative context is LLM-derived and not user-validated." if not thesis_text.strip() else "")}"""


# ── Grok output parser ────────────────────────────────────────────────────────

def _parse_grok_json(text: str) -> dict:
    """Parse structured JSON from Grok output. Returns {} on failure."""
    import re
    json_block = re.search(r"```json\s*([\s\S]*?)```", text)
    raw = json_block.group(1) if json_block else text
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict) and "verdict" in parsed:
            return parsed
        # Handle list wrapper
        if isinstance(parsed, list) and parsed:
            return parsed[0]
    except (json.JSONDecodeError, AttributeError, TypeError) as e:
        log.warning(f"[GrokJSON] Parse failed ({e}) — plain-text fallback")
    return {}


# ── Deterministic verdict ─────────────────────────────────────────────────────

def _determine_verdict(gate1_status: str, universe_composite: Optional[float],
                        overlap: dict, currency_result: dict) -> str:
    """Deterministic ADD/WATCH/PASS classification (B6). Grok narrates; this classifies."""
    if gate1_status == "breach" or universe_composite is None or universe_composite < 40:
        return "PASS"
    blocking_constraints = []
    if overlap.get("sector_match_count", 0) >= 4:
        blocking_constraints.append("sector_concentration")
    if overlap.get("country_match_count", 0) >= 5:
        blocking_constraints.append("country_concentration")
    if currency_result.get("currency_breach"):
        blocking_constraints.append("currency_exposure")
    if universe_composite >= 60 and not blocking_constraints:
        return "ADD"
    if universe_composite >= 40:
        return "WATCH"
    return "PASS"


# ── Email ─────────────────────────────────────────────────────────────────────

def _send_email(gmail_smtp: dict, subject: str, body_md: str, to_email: str):
    body_html = f"<pre style='font-family:monospace'>{body_md}</pre>"
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = gmail_smtp["username"]
    msg["To"]      = to_email
    msg.attach(MIMEText(body_md, "plain"))
    msg.attach(MIMEText(body_html, "html"))
    with smtplib.SMTP(gmail_smtp["host"], gmail_smtp["port"]) as s:
        s.ehlo()
        s.starttls()
        s.login(gmail_smtp["username"], gmail_smtp["password"])
        s.sendmail(gmail_smtp["username"], to_email, msg.as_string())


# ── Main ──────────────────────────────────────────────────────────────────────

def main(
    ticker: str,
    portfolio_db: dict,
    gmail_smtp: dict,
    xai_key: str,
    deepseek_key: str,
    universe_tickers: list = [],
    thesis_text: str = "",
    replacement_ticker: str = "",
    recipient_email: str = "straitsagent@gmail.com",
):
    ticker = ticker.strip().upper()
    replacement_ticker = (replacement_ticker or "").strip().upper() or None
    today = date.today()
    sgt = pytz.timezone("Asia/Singapore")
    log.info(f"[CandidateEval] Starting evaluation for {ticker}")

    conn = _conn(portfolio_db)
    conn.autocommit = True
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # ── B10: Portfolio baseline freshness ─────────────────────────────────────
    baseline_age = _check_portfolio_baseline_freshness(cur)
    baseline_warning = ""
    if baseline_age is None:
        baseline_warning = "⚠️ No portfolio baseline found — run portfolio rationalization first.\n\n"
    elif baseline_age > 35:
        baseline_warning = (
            f"⚠️ Portfolio baseline is {baseline_age} days old — "
            f"consider running rationalization before this eval.\n\n"
        )

    # ── B11: Check for fresh cached eval ─────────────────────────────────────
    cur.execute("""
        SELECT eval_date, verdict, binding_constraint, eval_expires_date
        FROM portfolio_candidate_evals
        WHERE ticker = %s
        ORDER BY eval_date DESC LIMIT 1
    """, (ticker,))
    cached = cur.fetchone()
    if cached:
        expires = cached["eval_expires_date"]
        age_days = (today - cached["eval_date"]).days
        if age_days <= EVAL_TTL_DAYS:
            log.info(f"[CandidateEval] Serving cached eval ({age_days}d old, expires {expires})")
            return {
                "ticker": ticker,
                "verdict": cached["verdict"],
                "binding_constraint": cached["binding_constraint"],
                "cached": True,
                "eval_date": str(cached["eval_date"]),
                "eval_expires_date": str(expires),
                "note": f"Cached eval ({age_days}d old). Valid until {expires}.",
            }

    # ── Fetch company name ────────────────────────────────────────────────────
    cur.execute("SELECT company_name FROM portfolio_positions WHERE ticker = %s LIMIT 1", (ticker,))
    row = cur.fetchone()
    if row:
        company_name = row["company_name"]
    else:
        cur.execute("SELECT description FROM company_profiles WHERE ticker = %s LIMIT 1", (ticker,))
        row = cur.fetchone()
        company_name = ticker  # fallback

    # Fetch latest price via yfinance
    try:
        info = yf.Ticker(ticker).fast_info
        price_usd = float(info.last_price or 0) or None
        candidate_currency = info.currency or "USD"
    except Exception:
        price_usd = None
        candidate_currency = "USD"

    # ── Fundamentals ─────────────────────────────────────────────────────────
    metrics = _fetch_fundamentals_for_ticker(cur, ticker, price_usd)
    metrics["currency"] = candidate_currency

    # ── Gate 1 ────────────────────────────────────────────────────────────────
    red_flags = _evaluate_red_flags(metrics)
    gate1_status = "breach" if red_flags else "ok"
    log.info(f"[Gate1] {gate1_status} | {len(red_flags)} flags")

    # ── Gate 2 ────────────────────────────────────────────────────────────────
    corr_result  = _compute_correlation(ticker, cur)
    fund_sim     = _compute_fundamental_similarity(metrics, cur)
    overlap      = _compute_sector_geo_overlap(ticker, metrics, cur, exclude_ticker=replacement_ticker)
    currency_result = _compute_currency_exposure(ticker, candidate_currency, cur, exclude_ticker=replacement_ticker)
    sizing       = _compute_sizing_headroom(cur)
    log.info(f"[Gate2] corr={corr_result.get('max_corr')} | fun_sim={fund_sim.get('max_fundamental_sim')} | "
             f"sector={overlap.get('sector_match_count')} | country={overlap.get('country_match_count')}")

    # ── Portfolio-relative factor scores ─────────────────────────────────────
    cur.execute("""
        SELECT quality_score, growth_score, valuation_score, sentiment_score
        FROM portfolio_scores
        WHERE score_date = (SELECT MAX(score_date) FROM portfolio_scores)
    """)
    portfolio_rows = cur.fetchall()
    portfolio_metrics = [
        {
            "quality_score":    r["quality_score"],
            "growth_score":     r["growth_score"],
            "valuation_score":  r["valuation_score"],
            "sentiment_score":  r["sentiment_score"],
        }
        for r in portfolio_rows
    ]
    portfolio_scores_relative = _compute_factor_scores_single(metrics, portfolio_metrics)

    gap_result = _compute_factor_gap(portfolio_scores_relative, cur)

    # ── Gate 3: Universe ──────────────────────────────────────────────────────
    # B9: validate user-supplied universe
    universe_heterogeneity = False
    if universe_tickers:
        universe_heterogeneity = _validate_universe(universe_tickers, cur)
        if universe_heterogeneity:
            log.warning("[Gate3] User-supplied universe is heterogeneous (B9)")

    universe_info = _fetch_universe(ticker, universe_tickers, cur)
    peer_metrics  = universe_info.pop("peer_metrics")

    universe_factor_scores = _compute_factor_scores_single(metrics, peer_metrics) if peer_metrics else {}
    universe_info["universe_q"] = universe_factor_scores.get("quality")
    universe_info["universe_g"] = universe_factor_scores.get("growth")
    universe_info["universe_v"] = universe_factor_scores.get("valuation")
    universe_info["universe_s"] = universe_factor_scores.get("sentiment")

    # universe_composite = mean of available universe percentiles
    u_vals = [v for v in [
        universe_info["universe_q"], universe_info["universe_g"],
        universe_info["universe_v"], universe_info["universe_s"]
    ] if v is not None]
    universe_composite = round(float(np.mean(u_vals)), 1) if u_vals else None
    portfolio_composite = round(float(np.mean([
        v for v in portfolio_scores_relative.values() if v is not None
    ])), 1) if any(v is not None for v in portfolio_scores_relative.values()) else None

    log.info(f"[Gate3] universe_composite={universe_composite} | thin={universe_info['thin_universe']}")

    # ── Deterministic verdict (B6) ────────────────────────────────────────────
    verdict = _determine_verdict(gate1_status, universe_composite, overlap, currency_result)
    log.info(f"[Verdict] Deterministic: {verdict}")

    # ── Grok synthesis ────────────────────────────────────────────────────────
    thesis_source = "user-supplied" if thesis_text.strip() else "llm-derived"
    prompt = _assemble_prompt(
        ticker, company_name, metrics, red_flags, gate1_status,
        corr_result, fund_sim, overlap, currency_result, gap_result, sizing,
        universe_info, portfolio_scores_relative, thesis_text, replacement_ticker,
    )
    grok_result = _call_grok_with_fallback(
        messages=[{"role": "user", "content": prompt}],
        xai_key=xai_key, deepseek_key=deepseek_key, max_tokens=3000,
    )
    synthesiser_model = grok_result["model"]
    grok_text = grok_result["text"]
    grok_json = _parse_grok_json(grok_text)

    # Use Grok's verdict if deterministic verdict is ADD/WATCH but Grok says PASS (trust Grok's nuance)
    grok_verdict = (grok_json.get("verdict") or "").upper().strip(".")
    if grok_verdict in ("ADD", "WATCH", "PASS") and verdict == "ADD" and grok_verdict == "PASS":
        verdict = "PASS"
    binding_constraint = grok_json.get("binding_constraint", "")
    log.info(f"[Grok] model={synthesiser_model} | verdict={grok_verdict} | final={verdict}")

    # ── Build per-factor triplets ─────────────────────────────────────────────
    def triplet(factor, abs_status):
        return {
            "absolute": abs_status,
            "portfolio_pct": portfolio_scores_relative.get(factor),
            "universe_pct":  universe_factor_scores.get(factor),
        }
    abs_status = "breach" if red_flags else "ok"
    quality_triplet   = triplet("quality",   abs_status)
    growth_triplet    = triplet("growth",    abs_status)
    valuation_triplet = triplet("valuation", abs_status)
    sentiment_triplet = triplet("sentiment", abs_status)

    # ── DB write ──────────────────────────────────────────────────────────────
    eval_expires_date = today + timedelta(days=EVAL_TTL_DAYS)
    cur.execute("""
        INSERT INTO portfolio_candidate_evals (
            eval_date, eval_expires_date, ticker, company_name, replacement_ticker,
            red_flag_count, red_flags, gate1_status,
            max_correlation, closest_existing, gate2_warn,
            max_fundamental_sim, closest_fundamental,
            sector_match_count, country_match_count,
            currency_post_pct, currency_breach,
            factor_gap_fills,
            universe_tickers, universe_size, thin_universe, below_min_universe,
            universe_heterogeneity,
            quality_triplet, growth_triplet, valuation_triplet, sentiment_triplet,
            portfolio_composite, universe_composite,
            verdict, binding_constraint,
            grok_json_output, thesis_source, portfolio_baseline_age,
            synthesiser_model, input_tokens, output_tokens
        ) VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s,
            %s, %s,
            %s, %s,
            %s, %s,
            %s,
            %s, %s, %s, %s,
            %s,
            %s, %s, %s, %s,
            %s, %s,
            %s, %s,
            %s, %s, %s,
            %s, %s, %s
        )
        ON CONFLICT (eval_date, ticker) DO UPDATE SET
            verdict=EXCLUDED.verdict, binding_constraint=EXCLUDED.binding_constraint,
            grok_json_output=EXCLUDED.grok_json_output,
            universe_composite=EXCLUDED.universe_composite,
            eval_expires_date=EXCLUDED.eval_expires_date,
            synthesiser_model=EXCLUDED.synthesiser_model,
            input_tokens=EXCLUDED.input_tokens, output_tokens=EXCLUDED.output_tokens
    """, (
        today, eval_expires_date, ticker, company_name, replacement_ticker,
        len(red_flags), json.dumps(red_flags), gate1_status,
        corr_result.get("max_corr"), corr_result.get("closest_existing"), corr_result.get("gate2_warn"),
        fund_sim.get("max_fundamental_sim"), fund_sim.get("closest_fundamental"),
        overlap.get("sector_match_count"), overlap.get("country_match_count"),
        currency_result.get("currency_post_pct"), currency_result.get("currency_breach"),
        json.dumps(gap_result.get("fill_factors", [])),
        json.dumps(universe_info["universe_tickers"]), universe_info["universe_size"],
        universe_info["thin_universe"], universe_info["below_min_universe"],
        universe_heterogeneity,
        json.dumps(quality_triplet), json.dumps(growth_triplet),
        json.dumps(valuation_triplet), json.dumps(sentiment_triplet),
        portfolio_composite, universe_composite,
        verdict, binding_constraint,
        json.dumps(grok_json) if grok_json else None,
        thesis_source, baseline_age,
        synthesiser_model, grok_result["input_tokens"], grok_result["output_tokens"],
    ))

    # ── Email ─────────────────────────────────────────────────────────────────
    subject = f"[{verdict}] Candidate Eval: {ticker} — {today.isoformat()}"
    body = f"""{baseline_warning}# Candidate Evaluation: {ticker} ({company_name})
Eval date: {today.isoformat()} | Valid until: {eval_expires_date.isoformat()}
Model: {synthesiser_model}

{grok_text}

---
*Deterministic verdict: {verdict} | universe_composite={universe_composite} | gate1={gate1_status}*
*Gap factors: {gap_result.get("gap_factors")} | Fill factors: {gap_result.get("fill_factors")}*
*Currency post-addition: {currency_result.get("currency_post_pct")}%{" (⚠️ breach)" if currency_result.get("currency_breach") else ""}*
*Thesis source: {thesis_source}*
"""
    _send_email(gmail_smtp, subject, body, recipient_email)
    log.info(f"[CandidateEval] Email sent — {subject}")

    cur.close()
    conn.close()

    return {
        "ticker": ticker,
        "verdict": verdict,
        "binding_constraint": binding_constraint,
        "gate1_status": gate1_status,
        "red_flags": red_flags,
        "universe_composite": universe_composite,
        "portfolio_composite": portfolio_composite,
        "eval_date": str(today),
        "eval_expires_date": str(eval_expires_date),
        "thesis_source": thesis_source,
        "synthesiser_model": synthesiser_model,
    }
