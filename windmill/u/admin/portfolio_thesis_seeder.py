# Requirements:
# psycopg2-binary>=2.9
# openai>=1.0

"""
portfolio_thesis_seeder — one-shot LLM drafter that reads research_reports per holding,
drafts a thesis via Grok-4.3, and writes it (write-if-absent, never clobbers owner edits).
"""
import json
import re
import traceback
from datetime import date, datetime

import psycopg2
import psycopg2.extras
from openai import OpenAI

# ── Pure helpers (unit-testable — no I/O) ────────────────────────────────────

def _build_thesis_prompt(ticker: str, research_content: str) -> str:
    return (
        "You are drafting a concise investment thesis for a single equity position, using ONLY the research "
        "provided below. Do not invent facts that the research does not support.\n\n"
        "Return STRICT JSON with exactly these keys and nothing else (no markdown, no commentary):\n"
        "{\n"
        '  "investment_thesis": "<2-4 sentences: the core reason to own this stock>",\n'
        '  "conviction": "High" | "Medium" | "Low",\n'
        '  "key_catalysts": ["<short catalyst>", "..."],\n'
        '  "risks": ["<short risk>", "..."],\n'
        '  "target_price_usd": <number or null>\n'
        "}\n\n"
        "Rules:\n"
        "- conviction reflects how strong and well-supported the bull case is in the research:\n"
        "  High = strong, differentiated, well-evidenced; Medium = reasonable but balanced; Low = weak or heavily caveated.\n"
        "- 2 to 4 items each for key_catalysts and risks. Keep every field tight and plain-text.\n"
        "- target_price_usd: a 12-month price target only if the research supports one, else null.\n\n"
        f"Ticker: {ticker}\n"
        f"Research:\n{research_content}"
    )


CONVICTION_MAP = {
    "high": "High", "strong": "Medium", "moderate": "Medium", "neutral": "Medium",
    "low": "Low", "weak": "Low", "very high": "High", "very low": "Low",
}

def _parse_thesis_response(raw: str) -> dict | None:
    raw = raw.strip()
    # strip optional ```json fences
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None

    thesis = (data.get("investment_thesis") or "").strip()
    if not thesis or len(thesis) < 10:
        return None  # never write a blank/trivial thesis

    conviction_raw = (data.get("conviction") or "").strip().lower()
    conviction = CONVICTION_MAP.get(conviction_raw, "Medium")

    catalysts = data.get("key_catalysts")
    if not isinstance(catalysts, list):
        catalysts = []
    catalysts = [str(c).strip() for c in catalysts if isinstance(c, str) and c.strip()]

    risks = data.get("risks")
    if not isinstance(risks, list):
        risks = []
    risks = [str(r).strip() for r in risks if isinstance(r, str) and r.strip()]

    target = data.get("target_price_usd")
    if target is not None:
        try:
            target = float(target)
            if target <= 0:
                target = None
        except (TypeError, ValueError):
            target = None

    return {
        "investment_thesis": thesis,
        "conviction": conviction,
        "key_catalysts": catalysts,
        "risks": risks,
        "target_price_usd": target,
    }


# ── I/O helpers (faked at edges in tests / exercised live) ────────────────────

def _pick_research_content(cur, ticker: str) -> str | None:
    cur.execute("""
        SELECT content FROM research_reports
        WHERE ticker = %s AND content IS NOT NULL
        ORDER BY
            CASE depth WHEN 'deep' THEN 3 WHEN 'standard' THEN 2 ELSE 1 END DESC,
            word_count DESC NULLS LAST,
            created_at DESC
        LIMIT 1
    """, (ticker,))
    row = cur.fetchone()
    return row["content"] if row else None


def _call_llm(xai_key: str, prompt: str, reasoning_effort: str = "medium") -> str:
    client = OpenAI(api_key=xai_key, base_url="https://api.x.ai/v1")
    resp = client.chat.completions.create(
        model="grok-4.3",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=700,
        extra_body={"reasoning_effort": reasoning_effort},
    )
    return resp.choices[0].message.content or ""


def _write_thesis(cur, ticker: str, parsed: dict, overwrite: bool = False) -> str:
    thesis = f"[auto-draft] {parsed['investment_thesis']}"
    if overwrite:
        cur.execute("""
            INSERT INTO portfolio_thesis
                (ticker, thesis_date, investment_thesis, key_catalysts, risks, conviction, target_price_usd, updated_at)
            VALUES (%s, CURRENT_DATE, %s, %s::jsonb, %s::jsonb, %s, %s, NOW())
            ON CONFLICT (ticker) DO UPDATE SET
                investment_thesis = EXCLUDED.investment_thesis,
                key_catalysts = EXCLUDED.key_catalysts,
                risks = EXCLUDED.risks,
                conviction = EXCLUDED.conviction,
                target_price_usd = EXCLUDED.target_price_usd,
                updated_at = NOW()
        """, (ticker, thesis, json.dumps(parsed["key_catalysts"]),
              json.dumps(parsed["risks"]), parsed["conviction"], parsed["target_price_usd"]))
        return "overwritten"
    else:
        cur.execute("""
            INSERT INTO portfolio_thesis
                (ticker, thesis_date, investment_thesis, key_catalysts, risks, conviction, target_price_usd, updated_at)
            VALUES (%s, CURRENT_DATE, %s, %s::jsonb, %s::jsonb, %s, %s, NOW())
            ON CONFLICT (ticker) DO NOTHING
        """, (ticker, thesis, json.dumps(parsed["key_catalysts"]),
              json.dumps(parsed["risks"]), parsed["conviction"], parsed["target_price_usd"]))
        return "skipped_existing" if cur.rowcount == 0 else "seeded"


# ── Main ─────────────────────────────────────────────────────────────────────

def main(portfolio_db: dict = {}, xai_key: str = "", ticker: str = "",
         overwrite: bool = False, reasoning_effort: str = "medium"):
    conn = psycopg2.connect(**portfolio_db)
    conn.autocommit = True
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    if ticker:
        tickers = [ticker.upper()]
    else:
        cur.execute("SELECT DISTINCT ticker FROM portfolio_positions ORDER BY ticker")
        tickers = [r["ticker"] for r in cur.fetchall()]

    seeded = []
    skipped_existing = []
    no_research = []
    errors = {}

    for tk in tickers:
        try:
            content = _pick_research_content(cur, tk)
            if not content:
                no_research.append(tk)
                continue

            prompt = _build_thesis_prompt(tk, content)
            raw = _call_llm(xai_key, prompt, reasoning_effort)
            parsed = _parse_thesis_response(raw)
            if parsed is None:
                errors[tk] = "parse_failed"
                continue

            result = _write_thesis(cur, tk, parsed, overwrite)
            if result == "seeded":
                seeded.append(tk)
            elif result == "skipped_existing":
                skipped_existing.append(tk)
            else:
                seeded.append(tk)  # overwritten
        except Exception as e:
            errors[tk] = f"{type(e).__name__}: {e}"
            traceback.print_exc()

    cur.close()
    conn.close()

    return {
        "ok": len(errors) == 0,
        "seeded": seeded,
        "skipped_existing": skipped_existing,
        "no_research": no_research,
        "errors": errors,
    }
