# Requirements:
# psycopg2-binary>=2.9
# openai>=1.30.0
# requests

"""
Candidate Prescreener — runs after rationalization every Saturday.
Scores pending watchlist_ideas candidates using the rationalization's
5-factor union-pool scoring (via factor_scorer), ranks them against the
33 holdings, and shortlists candidates ranking ≤15 for full evaluation.
"""

import json
import logging
import os
import time

import psycopg2
import psycopg2.extras
import requests

from factor_scorer import (
    _compute_factor_scores,
    _apply_thesis_scores,
    _compute_composites,
    _rank_positions,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

WM_BASE = "http://windmill_server:8000"
WM_WORKSPACE = "admins"

# ── Final-sort helper (locked oracle) ─────────────────────────────────────────

def compute_candidate_ranks(
    holding_composites: list[float],
    candidate_composites: dict[str, float],
) -> dict[str, dict]:
    """Given 33-holding balanced composites and a dict of {ticker: composite},
    return {ticker: {rank: int, composite: float}} sorted by composite desc."""
    merged = []
    for hc in holding_composites:
        merged.append(("_holding_", hc))
    for ticker, comp in candidate_composites.items():
        merged.append((ticker, comp))
    merged.sort(key=lambda x: x[1], reverse=True)
    # Assign ranks (1-indexed)
    result = {}
    for rank, (ticker, comp) in enumerate(merged, 1):
        if ticker != "_holding_":
            result[ticker] = {"rank": rank, "composite": comp}
    return result


# ── DB helpers ────────────────────────────────────────────────────────────────

def _conn(portfolio_db: dict):
    return psycopg2.connect(
        host=portfolio_db["host"],
        port=portfolio_db["port"],
        dbname=portfolio_db["dbname"],
        user=portfolio_db["user"],
        password=portfolio_db["password"],
    )


def _query_pending_candidates(cur) -> list[dict]:
    """Return all pending candidates from watchlist_ideas."""
    cur.execute("""
        SELECT id, ticker, source, reason
        FROM watchlist_ideas
        WHERE status = 'pending'
        ORDER BY added_at ASC
    """)
    return [dict(row) for row in cur.fetchall()]


def _query_held_tickers(cur) -> set[str]:
    """Return set of tickers currently held in portfolio_positions."""
    cur.execute("SELECT ticker FROM portfolio_positions")
    return {row[0] for row in cur.fetchall()}


def _query_recent_pass_verdicts(cur, tickers: list[str], days: int = 30) -> set[str]:
    """Return tickers with PASS verdicts in last `days` days."""
    if not tickers:
        return set()
    cur.execute("""
        SELECT DISTINCT ticker
        FROM portfolio_candidate_evals
        WHERE verdict = 'PASS'
          AND ticker = ANY(%s)
          AND eval_date >= CURRENT_DATE - INTERVAL '30 days'
    """, (tickers,))
    return {row[0] for row in cur.fetchall()}


def _query_holding_composites(cur) -> list[float]:
    """Return balanced composite scores for current holdings from portfolio_scores."""
    cur.execute("""
        SELECT composite_score_balanced
        FROM portfolio_scores
        WHERE composite_score_balanced IS NOT NULL
        ORDER BY composite_score_balanced DESC
    """)
    return [row[0] for row in cur.fetchall()]


def _query_fundamentals(cur, tickers: list[str]) -> dict[str, dict]:
    """Pull quantitative metrics for given tickers from fundamental_data and related tables."""
    if not tickers:
        return {}
    rows_dict = {}
    # Try fundamental_data first (the primary source used by rationalization)
    try:
        cur.execute("""
            SELECT ticker, data FROM fundamental_data
            WHERE ticker = ANY(%s)
        """, (tickers,))
        for row in cur.fetchall():
            data = row[1] if isinstance(row[1], dict) else json.loads(row[1])
            rows_dict[row[0]] = data
    except Exception:
        pass
    # Fall back: query individual quant tables for tickers not covered
    missing = [t for t in tickers if t not in rows_dict]
    if missing:
        # Build metrics from available tables
        metric_cols = [
            "return_on_equity", "net_profit_margin", "net_debt_to_ebitda",
            "fcf_quality", "revenue_cagr_3yr", "net_income_cagr_3yr",
            "revenue_cagr_1yr", "analyst_upside_pct", "forward_pe",
            "peg_ratio", "ev_to_ebitda", "analyst_rec_mean",
            "avg_eps_surprise", "momentum_52wk", "net_insider_90d", "market_cap",
        ]
        for t in missing:
            row = {}
            try:
                cur.execute("""
                    SELECT data FROM stock_snapshots WHERE ticker = %s
                """, (t,))
                snap = cur.fetchone()
                if snap:
                    sd = snap[0] if isinstance(snap[0], dict) else json.loads(snap[0])
                    for col in metric_cols:
                        if col in sd:
                            row[col] = sd[col]
            except Exception:
                pass
            rows_dict[t] = row
    return rows_dict


def _query_holdings_fund(cur, held_tickers: set[str]) -> dict[str, dict]:
    """Get fundamental data for held positions (for union pool scoring)."""
    fund = {}
    try:
        cur.execute("""
            SELECT ticker, data FROM fundamental_data
            WHERE ticker = ANY(%s)
        """, (list(held_tickers),))
        for row in cur.fetchall():
            data = row[1] if isinstance(row[1], dict) else json.loads(row[1])
            fund[row[0]] = data
    except Exception:
        pass
    return fund


def _update_candidate_status(cur, cand_id: int, status: str,
                              prescreen_rank: int = None,
                              prescreen_score: float = None):
    """Update a watchlist_ideas row."""
    cur.execute("""
        UPDATE watchlist_ideas
        SET status = %s,
            prescreen_rank = %s,
            prescreen_score = %s
        WHERE id = %s
    """, (status, prescreen_rank, prescreen_score, cand_id))


# ── Windmill dispatch ─────────────────────────────────────────────────────────

def _dispatch_stock_fetcher(ticker: str, portfolio_db: dict, wm_token: str) -> bool:
    """Dispatch stock_data_fetcher for a single ticker. Polls for completion."""
    token = wm_token or os.environ.get("WM_TOKEN", "")
    if not token:
        log.warning("[Dispatch] No WM_TOKEN")
        return False
    url = f"{WM_BASE}/api/w/{WM_WORKSPACE}/jobs/run/p/u/admin/stock_data_fetcher"
    args = {"ticker": ticker, "portfolio_db": portfolio_db}
    try:
        resp = requests.post(
            url, headers={"Authorization": f"Bearer {token}",
                          "Content-Type": "application/json"},
            json=args, timeout=10,
        )
        job_id = resp.text.strip().strip('"')
        log.info(f"[Dispatch] stock_data_fetcher for {ticker} job_id={job_id}")
        # Poll for completion
        for _ in range(48):  # up to 4 min
            time.sleep(5)
            try:
                poll = requests.get(
                    f"{WM_BASE}/api/w/{WM_WORKSPACE}/jobs/get/{job_id}",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=10,
                )
                poll_data = poll.json()
                if poll_data.get("success") and not poll_data.get("running"):
                    return True
            except Exception:
                pass
        log.warning(f"[Dispatch] stock_data_fetcher for {ticker} timed out")
        return False
    except Exception as e:
        log.warning(f"[Dispatch] Failed to dispatch stock_data_fetcher for {ticker}: {e}")
        return False


def _dispatch_candidate_eval(wm_token: str, portfolio_db: dict) -> str:
    """Dispatch candidate_eval in pull mode. Returns job_id or ''."""
    token = wm_token or os.environ.get("WM_TOKEN", "")
    if not token:
        log.warning("[Dispatch] No WM_TOKEN")
        return ""
    url = f"{WM_BASE}/api/w/{WM_WORKSPACE}/jobs/run/p/u/admin/portfolio_candidate_eval"
    args = {
        "ticker": "",
        "watchlist_pull": True,
        "portfolio_db": portfolio_db,
    }
    try:
        resp = requests.post(
            url, headers={"Authorization": f"Bearer {token}",
                          "Content-Type": "application/json"},
            json=args, timeout=10,
        )
        job_id = resp.text.strip().strip('"')
        log.info(f"[Dispatch] candidate_eval (pull mode) dispatched job_id={job_id}")
        return job_id
    except Exception as e:
        log.warning(f"[Dispatch] Failed to dispatch candidate_eval: {e}")
        return ""


# ── Neutral thesis ────────────────────────────────────────────────────────────

def _neutral_thesis(ticker: str) -> dict:
    """Return a neutral thesis row (conviction score 0.5, no catalysts/risks)."""
    return {
        "conviction": "Medium",
        "catalysts": [],
        "risks": [],
        "target_price": None,
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main(portfolio_db: dict, wm_token: str = ""):
    conn = _conn(portfolio_db)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # 1. Get pending candidates
            candidates = _query_pending_candidates(cur)
            if not candidates:
                log.info("No pending candidates — nothing to do")
                return {"prescreened": 0, "shortlisted": 0, "archived": 0}

            log.info(f"Found {len(candidates)} pending candidates")

            # 2. Get held tickers
            held = _query_held_tickers(cur)
            log.info(f"  {len(held)} held positions")

            # 3. Auto-exclude: held positions + recent PASS verdicts
            cand_tickers = [c["ticker"] for c in candidates]
            recent_passes = _query_recent_pass_verdicts(cur, cand_tickers)

            active = []
            excluded = []
            for c in candidates:
                t = c["ticker"]
                if t in held:
                    log.info(f"  Excluding {t}: already held")
                    _update_candidate_status(cur, c["id"], "archived")
                    excluded.append(t)
                elif t in recent_passes:
                    log.info(f"  Excluding {t}: PASS verdict within 30 days")
                    _update_candidate_status(cur, c["id"], "archived")
                    excluded.append(t)
                else:
                    active.append(c)

            if not active:
                conn.commit()
                log.info("All candidates excluded — nothing to score")
                return {"prescreened": 0, "shortlisted": 0, "archived": len(excluded)}

            log.info(f"  {len(active)} candidates to score, {len(excluded)} excluded")

            # 4. Dispatch stock_data_fetcher for each active candidate (batches of 5)
            active_tickers = [c["ticker"] for c in active]
            for i in range(0, len(active_tickers), 5):
                batch = active_tickers[i : i + 5]
                for ticker in batch:
                    if wm_token:
                        _dispatch_stock_fetcher(ticker, portfolio_db, wm_token)
                if i + 5 < len(active_tickers):
                    time.sleep(5)

            # 5. Get fundamentals for held positions (union pool)
            holdings_fund = _query_holdings_fund(cur, held)
            # Get fundamentals for candidates
            cand_fund = _query_fundamentals(cur, active_tickers)

            # Build positions list for held positions
            held_positions = [{"ticker": t} for t in held if t in holdings_fund]

            # 6. Score each candidate via union-pool approach
            candidate_composites = {}
            for c in active:
                t = c["ticker"]
                cf = cand_fund.get(t, {})
                if not cf:
                    log.info(f"  Skipping {t}: no fundamental data")
                    _update_candidate_status(cur, c["id"], "archived")
                    continue

                # Build union pool: held positions + candidate
                union_positions = held_positions + [{"ticker": t}]
                union_fund = {**holdings_fund, t: cf}

                # Score factors
                factor_scores = _compute_factor_scores(union_positions, union_fund)

                # Thesis: neutral for candidate, real for holdings
                thesis_data = {}
                for ht in held:
                    thesis_data[ht] = _neutral_thesis(ht)
                thesis_data[t] = _neutral_thesis(t)
                thesis_scores = _apply_thesis_scores(union_positions, thesis_data)

                # Compute composites
                composites = _compute_composites(union_positions, factor_scores, thesis_scores)
                balanced = composites.get(t, {}).get("composites", {}).get("balanced", 0)
                candidate_composites[t] = balanced
                log.info(f"  {t}: balanced composite = {balanced}")

            if not candidate_composites:
                conn.commit()
                return {"prescreened": 0, "shortlisted": 0, "archived": len(excluded) + len(active)}

            # 7. Get holding composites and rank
            holding_composites = _query_holding_composites(cur)
            ranks = compute_candidate_ranks(holding_composites, candidate_composites)

            # 8. Write results
            shortlisted = 0
            archived_by_rank = 0
            for c in active:
                t = c["ticker"]
                r = ranks.get(t, {})
                rank = r.get("rank", 999)
                composite = r.get("composite", 0)
                if rank <= 15 and composite > 0:
                    _update_candidate_status(cur, c["id"], "shortlisted", rank, composite)
                    shortlisted += 1
                    log.info(f"  {t}: shortlisted (rank {rank}, composite {composite})")
                else:
                    _update_candidate_status(cur, c["id"], "archived", rank, composite)
                    archived_by_rank += 1
                    log.info(f"  {t}: archived (rank {rank}, composite {composite})")

            conn.commit()
            log.info(f"Prescreen complete: {shortlisted} shortlisted, "
                     f"{archived_by_rank} archived by rank, {len(excluded)} auto-excluded")

            # 9. Dispatch candidate_eval in pull mode
            if shortlisted > 0 and wm_token:
                _dispatch_candidate_eval(wm_token, portfolio_db)

            return {
                "prescreened": len(active),
                "shortlisted": shortlisted,
                "archived": archived_by_rank + len(excluded),
            }

    except Exception as e:
        conn.rollback()
        log.error(f"Prescreener failed: {e}")
        raise
    finally:
        conn.close()
