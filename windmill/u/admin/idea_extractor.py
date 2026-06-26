# Requirements:
# psycopg2-binary>=2.9
# openai>=1.30.0

"""
Idea Extractor — reads a research .md file, calls Deepseek to extract
(ticker, reason) pairs for investment ideas, and writes them to
watchlist_ideas (status: pending). Deduplicates via ON CONFLICT (ticker, source).
"""

import json
import logging
import re

import psycopg2
from openai import OpenAI

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ── Extraction prompt (owner-approved 2026-06-26) ─────────────────────────────
EXTRACTION_SYSTEM_PROMPT = (
    "You are reading a research digest. Identify any publicly-traded companies "
    "or ETFs mentioned as investment ideas, themes, catalysts, or risks. For each, "
    "return STRICT JSON with exactly these keys and nothing else:\n"
    '[\n  {"ticker": "SYMBOL", "reason": "<one sentence: why it was mentioned in this digest>"}\n]\n'
    "Rules:\n"
    "- ONLY include tickers that are mentioned in the context of an investment idea, "
    "theme, catalyst, or significant risk.\n"
    '- Do NOT include tickers mentioned only in passing (e.g., "the S&P 500 fell" '
    "→ SPY is NOT an idea).\n"
    "- If no tickers qualify, return an empty array: []\n"
    '- Use the primary exchange ticker (e.g., "BABA" not "9988.HK").'
)


def _conn(portfolio_db: dict):
    return psycopg2.connect(
        host=portfolio_db["host"],
        port=portfolio_db["port"],
        dbname=portfolio_db["dbname"],
        user=portfolio_db["user"],
        password=portfolio_db["password"],
    )


def _read_md(md_path: str) -> str:
    """Read the .md file content. Returns empty string on error."""
    try:
        with open(md_path, "r") as f:
            return f.read()
    except Exception as e:
        log.error(f"Failed to read {md_path}: {e}")
        return ""


def _call_deepseek_extraction(content: str, deepseek_key: str) -> str | None:
    """Call Deepseek with the extraction prompt. Returns raw JSON string or None."""
    if not content.strip():
        return None
    client = OpenAI(
        base_url="https://api.deepseek.com/v1",
        api_key=deepseek_key,
    )
    try:
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ],
            temperature=0.0,
            max_tokens=512,
        )
        raw = resp.choices[0].message.content.strip()
        log.info(f"Deepseek extraction response: {raw[:200]}...")
        return raw
    except Exception as e:
        log.error(f"Deepseek extraction call failed: {e}")
        return None


def _parse_extraction_response(raw: str) -> list[dict] | None:
    """Parse the Deepseek JSON response. Returns list of {ticker, reason} dicts or None.
    Pure helper — no I/O, no DB, testable in isolation."""
    if not raw or not raw.strip():
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        log.warning(f"Extraction response is not valid JSON: {raw[:200]}")
        return None
    if not isinstance(parsed, list):
        return None
    out = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        ticker = (item.get("ticker") or "").strip().upper()
        reason = (item.get("reason") or "").strip()
        if not ticker or not reason:
            continue
        # Sanitise: skip obvious non-tickers
        if not _is_valid_ticker(ticker):
            log.info(f"Skipping non-ticker: {ticker}")
            continue
        out.append({"ticker": ticker, "reason": reason})
    return out if out else []


# ── Ticker sanitisation ───────────────────────────────────────────────────────
# Strings that are clearly NOT tickers are silently skipped.

_NON_TICKER_PATTERNS = [
    re.compile(r"^[A-Z]$"),                     # single letter
    re.compile(r"^[A-Z]{2,3}:\s"),              # starts with prefix like "US:"
    re.compile(r"^[A-Z]{3}\s[A-Z]"),            # "S&P 500" pattern
    re.compile(r"\d{4}"),                       # contains 4-digit year
    re.compile(r"S&P|NASDAQ|NYSE|DOW|ETF\b"),   # index/ETF generic names
    re.compile(r"SECTOR|INDEX|BOND|TREASURY|FUND\b"),
    re.compile(r"^\d"),                         # starts with digit
    re.compile(r" "),                           # contains space (tickers don't)
    re.compile(r"^.{6,}$"),                     # longer than 5 chars (tickers are 1-5)
]


def _is_valid_ticker(ticker: str) -> bool:
    """Return True if the string looks like a valid ticker symbol."""
    if not ticker or len(ticker) < 1 or len(ticker) > 5:
        return False
    if not re.match(r"^[A-Z0-9.]+$", ticker):
        return False
    for pat in _NON_TICKER_PATTERNS:
        if pat.search(ticker):
            return False
    return True


def _insert_candidates(cur, rows: list[dict], source: str, source_ref: str = ""):
    """Insert extracted tickers into watchlist_ideas. ON CONFLICT for dedup."""
    for r in rows:
        try:
            cur.execute(
                """
                INSERT INTO watchlist_ideas (ticker, source, source_ref, reason, status)
                VALUES (%s, %s, %s, %s, 'pending')
                ON CONFLICT (ticker, source) DO NOTHING
                """,
                (r["ticker"], source, source_ref, r["reason"]),
            )
        except Exception as e:
            log.warning(f"Failed to insert {r['ticker']}: {e}")
    log.info(f"Inserted/upserted {len(rows)} candidates from source={source}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main(md_path: str, source: str, portfolio_db: dict, deepseek_key: str):
    content = _read_md(md_path)
    if not content:
        log.warning(f"No content read from {md_path} — exiting")
        return

    raw = _call_deepseek_extraction(content, deepseek_key)
    if raw is None:
        log.warning("Deepseek extraction returned no content")
        return

    rows = _parse_extraction_response(raw)
    if rows is None:
        log.warning("Extraction parsing returned None (malformed response)")
        return
    if not rows:
        log.info("No tickers extracted — nothing to insert")
        return

    conn = _conn(portfolio_db)
    try:
        with conn.cursor() as cur:
            _insert_candidates(cur, rows, source, md_path)
        conn.commit()
        log.info(f"Committed {len(rows)} candidates")
    except Exception as e:
        conn.rollback()
        log.error(f"DB transaction failed: {e}")
        raise
    finally:
        conn.close()
