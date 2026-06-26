# factor_scorer.py — shared scoring functions extracted from portfolio_rationalization.py
# Used by both portfolio_rationalization (Step 0 refactor) and candidate_prescreener (Plan A).
# All functions operate purely on passed-in arguments — no DB reads, no I/O.

from datetime import date
from typing import Optional

# ── Red-flag absolute thresholds ───────────────────────────────────────────────
NET_DEBT_EBITDA_MAX = 4.0
CURRENT_RATIO_MIN = 0.8
FWD_PE_MAX = 60.0
REV_CAGR_MIN = 0.0     # below 0 → declining revenue
NI_CAGR_MIN = -0.20    # below -20% → earnings deterioration

# ── Percentile pool size guard ─────────────────────────────────────────────────
MIN_POOL_SIZE = 8


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
