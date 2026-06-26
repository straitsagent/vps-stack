# Requirements:
# psycopg2-binary>=2.9

"""
Replacement Screener — selects top-3 shortlisted candidates as replacements
for EXIT / TRIM positions and identifies overweight candidates among held
positions. Runs after candidate_prescreener completes (Plan A).
"""

import json
import logging
import os
import re

import psycopg2
import psycopg2.extras
import requests

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

WM_BASE = "http://windmill_server:8000"
WM_WORKSPACE = "admins"


# ── Pure helper ───────────────────────────────────────────────────────────────

def _select_top_replacements(
    exit_tickers: list[str],
    shortlisted: list[dict],
    held_tickers: set[str],
    top_n: int = 3,
) -> dict[str, list[dict]]:
    """Return {exit_ticker: [top_n candidates sorted by prescreen_rank]}.
    Held positions are excluded. Sector-agnostic (any sector qualifies).
    If fewer than top_n candidates exist, returns all available."""
    # Sort shortlisted by prescreen_rank ascending
    ranked = sorted(shortlisted, key=lambda s: s.get("prescreen_rank", 999))
    # Exclude held positions
    available = [s for s in ranked if s.get("ticker") not in held_tickers]
    result = {}
    for et in exit_tickers:
        # Each exit ticker gets the same top-N pool
        result[et] = available[:top_n]
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


def _query_exit_trim_positions(cur) -> list[dict]:
    """Return positions with EXIT or TRIM recommendation from portfolio_scores."""
    cur.execute("""
        SELECT DISTINCT ON (ticker)
            ticker, recommendation, composite_score_balanced,
            rank_balanced, sector
        FROM portfolio_scores
        WHERE recommendation IN ('EXIT', 'TRIM')
        ORDER BY ticker, score_date DESC
    """)
    return [dict(row) for row in cur.fetchall()]


def _query_shortlisted_candidates(cur) -> list[dict]:
    """Return shortlisted watchlist candidates with their prescreen data."""
    cur.execute("""
        SELECT ticker, prescreen_rank, prescreen_score,
               reason
        FROM watchlist_ideas
        WHERE status = 'shortlisted'
          AND prescreen_rank IS NOT NULL
        ORDER BY prescreen_rank ASC
    """)
    rows = [dict(row) for row in cur.fetchall()]
    # Enrich with sector if available (from company_profiles)
    tickers = [r["ticker"] for r in rows]
    if tickers:
        try:
            cur.execute("""
                SELECT ticker, sector FROM company_profiles
                WHERE ticker = ANY(%s)
            """, (tickers,))
            sector_map = {row["ticker"]: row.get("sector", "—") for row in cur.fetchall()}
        except Exception:
            sector_map = {}
        for r in rows:
            r["sector"] = sector_map.get(r["ticker"], "—")
    return rows


def _query_held_tickers(cur) -> set[str]:
    """Return set of currently held tickers."""
    cur.execute("SELECT ticker FROM portfolio_positions")
    return {row[0] for row in cur.fetchall()}


def _query_held_sector_data(cur, held_tickers: set[str]) -> dict[str, dict]:
    """Return {ticker: {sector, rank_balanced, composite_score_balanced}} for held positions."""
    result = {}
    if not held_tickers:
        return result
    cur.execute("""
        SELECT DISTINCT ON (ticker)
            ticker, sector, rank_balanced, composite_score_balanced
        FROM portfolio_scores
        WHERE ticker = ANY(%s)
        ORDER BY ticker, score_date DESC
    """, (list(held_tickers),))
    for row in cur.fetchall():
        rd = dict(row)
        if rd.get("rank_balanced") and rd["rank_balanced"] <= 15:
            result[rd["ticker"]] = rd
    return result


def _write_replacement_rows(cur, replacements: dict[str, list[dict]]):
    """Write replacement suggestions to watchlist_ideas for traceability."""
    for exit_ticker, candidates in replacements.items():
        for c in candidates:
            reason = f"Ranked #{c.get('prescreen_rank', '?')} replacement for {exit_ticker} after rationalization-based prescreen"
            cur.execute("""
                INSERT INTO watchlist_ideas (ticker, source, source_ref, reason, status,
                                             prescreen_rank, prescreen_score)
                VALUES (%s, 'rationalization_exit', %s, %s, 'shortlisted', %s, %s)
                ON CONFLICT (ticker, source) DO NOTHING
            """, (
                c["ticker"],
                exit_ticker,
                reason,
                c.get("prescreen_rank"),
                c.get("prescreen_score"),
            ))


# ── Report rendering ─────────────────────────────────────────────────────────

def _render_section_e(
    exit_positions: list[dict],
    replacements: dict[str, list[dict]],
    overweight: list[str],
    held_data: dict[str, dict],
) -> str:
    """Render Section E — Replacement Candidates as markdown."""
    if not exit_positions:
        return """## Section E — Replacement Candidates

No positions flagged for EXIT or TRIM this week.
"""

    lines = [
        "## Section E — Replacement Candidates",
        "",
        "### EXIT / TRIM Replacements",
        "",
        "The rationalization recommends exiting or trimming the following positions.",
        "Below are the top-3 shortlisted candidates for each, ranked by composite score",
        "from the rationalization-based prescreener.",
        "",
    ]

    for ep in exit_positions:
        t = ep["ticker"]
        rec = ep.get("recommendation", "?")
        rank = ep.get("rank_balanced", "?")
        lines.append(f"**{t}** → recommendation: {rec} (rank #{rank})")
        cands = replacements.get(t, [])
        if not cands:
            lines.append("*No shortlisted candidates available.*")
            lines.append("")
            continue
        lines.append("| Rank | Candidate | Prescreen Score | Rationale |")
        lines.append("|------|-----------|-----------------|-----------|")
        for c in cands:
            pr = c.get("prescreen_rank", "?")
            ps = f"{c.get('prescreen_score', 0):.2f}" if c.get("prescreen_score") is not None else "—"
            reason = c.get("reason") or "—"
            lines.append(f"| {pr} | {c['ticker']} | {ps} | {reason} |")
        lines.append("")

    # Overweight suggestions
    if overweight:
        lines.append("### Overweight Candidates")
        lines.append("")
        lines.append(
            "The following currently-held positions are strong candidates for overweighting. "
            "They ranked in the top 15 and are in a different sector than the position being exited, "
            "providing natural diversification."
        )
        lines.append("")
        for ow in overweight:
            hd = held_data.get(ow, {})
            rank = hd.get("rank_balanced", "?")
            sector = hd.get("sector", "—")
            lines.append(
                f"- **{ow}** — ranked #{rank} (sector: {sector}). "
                f"Consider increasing weight from freed capital."
            )
        lines.append("")

    return "\n".join(lines)


def _build_overweight_list(
    exit_positions: list[dict],
    held_data: dict[str, dict],
) -> list[str]:
    """Identify held positions in top 15 that are in a different sector from any EXIT position."""
    if not exit_positions:
        return []
    exit_sectors = {ep.get("sector", "") for ep in exit_positions if ep.get("sector")}
    overweight = []
    for ticker, hd in held_data.items():
        hs = hd.get("sector", "")
        if hs not in exit_sectors or not exit_sectors:
            overweight.append(ticker)
    # Sort by rank ascending
    overweight.sort(key=lambda t: held_data.get(t, {}).get("rank_balanced", 999))
    return overweight


# ── Dispatch ──────────────────────────────────────────────────────────────────

def _dispatch_formatter(md_path: str, telegram_bot_token: str,
                        telegram_owner_id: str, portfolio_db: dict,
                        wm_token: str = "") -> str:
    """Re-dispatch the rationalization formatter with updated .md."""
    token = wm_token or os.environ.get("WM_TOKEN", "")
    if not token:
        log.warning("[Dispatch] No WM_TOKEN — cannot re-dispatch formatter")
        return ""
    url = f"{WM_BASE}/api/w/{WM_WORKSPACE}/jobs/run/p/u/admin/portfolio_rationalization_telegram"
    args = {
        "md_path": md_path,
        "telegram_bot_token": telegram_bot_token,
        "telegram_owner_id": telegram_owner_id,
        "portfolio_db": portfolio_db,
    }
    try:
        resp = requests.post(
            url, headers={"Authorization": f"Bearer {token}",
                          "Content-Type": "application/json"},
            json=args, timeout=10,
        )
        job_id = resp.text.strip().strip('"')
        log.info(f"[Dispatch] formatter re-dispatched job_id={job_id}")
        return job_id
    except Exception as e:
        log.warning(f"[Dispatch] Failed to re-dispatch formatter: {e}")
        return ""


# ── Main ──────────────────────────────────────────────────────────────────────

def main(md_path: str, portfolio_db: dict,
         telegram_bot_token: str = "",
         telegram_owner_id: str = "",
         wm_token: str = ""):
    conn = _conn(portfolio_db)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # 1. Read EXIT / TRIM positions
            exit_positions = _query_exit_trim_positions(cur)
            if not exit_positions:
                log.info("No EXIT or TRIM positions — nothing to do")
                # Still write empty Section E for completeness
                section_e = _render_section_e([], {}, [], {})
                _append_section_e(md_path, section_e)
                return {"exit_positions": 0, "replacements": 0}

            log.info(f"Found {len(exit_positions)} EXIT/TRIM positions: "
                     f"{[e['ticker'] for e in exit_positions]}")

            # 2. Read shortlisted candidates from prescreener
            shortlisted = _query_shortlisted_candidates(cur)
            log.info(f"  {len(shortlisted)} shortlisted candidates available")

            # 3. Read held tickers
            held = _query_held_tickers(cur)

            # 4. Select top-3 replacements (pure helper)
            exit_tickers = [e["ticker"] for e in exit_positions]
            replacements = _select_top_replacements(exit_tickers, shortlisted, held, top_n=3)
            total = sum(len(v) for v in replacements.values())
            log.info(f"  Selected {total} replacements across {len(exit_positions)} exit positions")

            # 5. Write replacement rows to watchlist_ideas for traceability
            _write_replacement_rows(cur, replacements)

            # 6. Build overweight list
            held_data = _query_held_sector_data(cur, held)
            overweight = _build_overweight_list(exit_positions, held_data)

            # 7. Render Section E
            section_e = _render_section_e(exit_positions, replacements, overweight, held_data)

            # Build replacement data for front-matter
            replacement_data = {
                "exit_positions": [
                    {
                        "ticker": ep["ticker"],
                        "recommendation": ep.get("recommendation"),
                        "rank": ep.get("rank_balanced"),
                        "candidates": [
                            {"ticker": c["ticker"], "prescreen_rank": c.get("prescreen_rank"),
                             "prescreen_score": c.get("prescreen_score")}
                            for c in replacements.get(ep["ticker"], [])
                        ],
                    }
                    for ep in exit_positions
                ],
                "overweight": overweight,
            }

            conn.commit()
            log.info(f"Committed {total} replacement row(s) to watchlist_ideas")

        # 8. Append Section E to the rationalization .md file
        _append_section_e(md_path, section_e, replacement_data)

        # 9. Re-dispatch the Telegram formatter so owner sees Section E
        if telegram_bot_token and telegram_owner_id and wm_token:
            _dispatch_formatter(md_path, telegram_bot_token, telegram_owner_id,
                                portfolio_db, wm_token)

        return {
            "exit_positions": len(exit_positions),
            "replacements": total,
            "overweight": len(overweight),
        }

    except Exception as e:
        conn.rollback()
        log.error(f"Replacement screener failed: {e}")
        raise
    finally:
        conn.close()


def _append_section_e(md_path: str, section_e: str, replacement_data: dict = None):
    """Append Section E to the rationalization .md file and update front-matter."""
    try:
        with open(md_path, "r") as f:
            content = f.read()
        # Patch front-matter JSON if replacement_data provided
        if replacement_data:
            content = _patch_front_matter(content, replacement_data)
        # Insert Section E before the final --- footer
        if "---" in content:
            parts = content.rsplit("---", 1)
            updated = parts[0].rstrip() + "\n\n" + section_e + "\n\n---" + parts[1]
        else:
            updated = content + "\n\n" + section_e + "\n"
        with open(md_path, "w") as f:
            f.write(updated)
        log.info(f"[File] Appended Section E to {md_path}")
    except Exception as e:
        log.error(f"[File] Failed to append Section E to {md_path}: {e}")


def _patch_front_matter(content: str, replacement_data: dict) -> str:
    """Insert replacement_candidates key into the JSON front-matter block."""
    match = re.match(r'^(```json\s*\n)(.*?)(\n```)', content, re.DOTALL)
    if not match:
        return content
    prefix, json_str, suffix = match.groups()
    try:
        fm = json.loads(json_str)
    except json.JSONDecodeError:
        return content
    fm["replacement_candidates"] = replacement_data
    new_json = json.dumps(fm, indent=2, default=str)
    return prefix + new_json + suffix + content[match.end():]
