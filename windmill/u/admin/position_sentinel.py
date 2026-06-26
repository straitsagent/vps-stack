# Requirements:
# requests>=2.31
# feedparser>=6
# psycopg2-binary>=2.9
# openai>=1.0

"""
Position Sentinel — Phase 1: Signal spine + cumulative-price alert.
Hourly monitor: per-holding price drawdowns + news materiality triage.
Phase 1 alerting: cumulative-price signals only. News/confluence logged.
"""
import hashlib
import json
import os
import traceback
from datetime import datetime, timezone, timedelta
from typing import Any

import feedparser
import psycopg2
import psycopg2.extras
import requests
from openai import OpenAI

SGT = timezone(timedelta(hours=8))

# ── Threshold constants (configurable) ────────────────────────────────────────
PRICE_THRESHOLDS = {
    "chg_3d": -8.0,        # position ≤ -8% over 3 trading days
    "chg_5d": -12.0,       # position ≤ -12% over 5 trading days
    "vs_20d_high": -20.0,  # position ≤ -20% vs 20-day high
}

NEWS_COOLDOWN_MINUTES = 60    # per-ticker signal cooldown

# ── Pure helpers ──────────────────────────────────────────────────────────────

def _cumulative_drawdowns(closes: list[float]) -> dict:
    """Compute chg_3d, chg_5d, vs_20d_high from an ordered close series (oldest first)."""
    n = len(closes)
    latest = closes[-1] if n > 0 else None
    if latest is None or latest == 0:
        return {"chg_3d": None, "chg_5d": None, "vs_20d_high": None}

    def pct_chg(days):
        if n >= days + 1 and closes[-days-1] != 0:
            return round((latest - closes[-days-1]) / closes[-days-1] * 100, 1)
        return None

    window = closes[-20:] if n >= 20 else closes
    high20 = max(window) if window else latest
    vs20 = round((latest - high20) / high20 * 100, 1) if high20 != 0 else None

    return {"chg_3d": pct_chg(3), "chg_5d": pct_chg(5), "vs_20d_high": vs20}


def _price_signal(dd: dict, cfg: dict) -> str | None:
    for key, threshold in cfg.items():
        val = dd.get(key)
        if val is not None and val <= threshold:
            return "price_cumulative"
    return None


def _url_hash(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()


def _parse_materiality(raw: str) -> dict | None:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[0] if raw.count("```") == 1 else raw.split("```")[1]
        raw = raw.replace("json", "").strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None

    try:
        m = int(data.get("materiality", -1))
    except (ValueError, TypeError):
        return None
    if m < 0 or m > 3:
        return None

    cat = str(data.get("category", "")).lower().strip()
    valid_cats = {"earnings","regulatory","legal","geopolitical","competitive","analyst","m&a","guidance","other"}
    if cat not in valid_cats:
        cat = "other"

    direction = str(data.get("direction", "")).lower().strip()
    if direction not in ("neg", "neutral", "pos"):
        direction = "neutral"

    impact = str(data.get("impact", "")).strip() or "routine"

    return {
        "materiality": m,
        "category": cat,
        "direction": direction,
        "impact": impact,
    }


def _aggregate_materiality(events: list[dict], window_h: int = 72) -> int:
    cutoff = datetime.now(SGT) - timedelta(hours=window_h)
    total = 0
    for ev in events:
        ts = ev.get("fetched_at")
        if ts and ts >= cutoff:
            total += ev.get("materiality", 0) or 0
    return total


def _confluence(price_signal_type: str | None, events: list[dict], window_h: int = 72) -> bool:
    if not price_signal_type:
        return False
    cutoff = datetime.now(SGT) - timedelta(hours=window_h)
    for ev in events:
        ts = ev.get("fetched_at")
        mat = ev.get("materiality", 0) or 0
        if ts and ts >= cutoff and mat >= 2:
            return True
    return False


# ── I/O helpers ───────────────────────────────────────────────────────────────

def _load_closes(cur, ticker: str, days: int = 25) -> list[float]:
    cur.execute(
        "SELECT close FROM price_history WHERE ticker=%s ORDER BY price_date ASC",
        (ticker,)
    )
    rows = cur.fetchall()
    closes = [float(r["close"]) for r in rows if r.get("close") is not None]
    return closes[-days:] if len(closes) > days else closes


def _load_recent_events(cur, ticker: str, hours: int = 72) -> list[dict]:
    cutoff = datetime.now(SGT) - timedelta(hours=hours)
    cur.execute(
        "SELECT * FROM position_events WHERE ticker=%s AND fetched_at>=%s ORDER BY fetched_at DESC",
        (ticker, cutoff)
    )
    return cur.fetchall()


def _fetch_news(query: str) -> list[dict]:
    url = f"https://news.google.com/rss/search?q={requests.utils.quote(query)}&hl=en-US&gl=US&ceid=US:en"
    try:
        feed = feedparser.parse(url)
    except Exception:
        return []
    items = []
    for entry in feed.entries[:10]:
        items.append({
            "headline": entry.get("title", ""),
            "url": entry.get("link", ""),
            "snippet": entry.get("summary", "")[:500],
            "published": entry.get("published", ""),
        })
    return items


TRIAGE_PROMPT = (
    "You are triaging a single news headline about a company a portfolio holds. Using ONLY the "
    "headline/snippet provided, return STRICT JSON and nothing else:\n"
    '{"materiality": 0|1|2|3, "category": "earnings|regulatory|legal|geopolitical|competitive|analyst|m&a|guidance|other",'
    ' "direction": "neg|neutral|pos", "impact": "<one short clause: why it matters or \'routine\'>"}\n'
    "materiality: 0=routine/noise, 1=minor/context, 2=material (could move the thesis or price), "
    "3=critical/thesis-threatening (regulatory or legal action, earnings collapse, guidance cut, "
    "government designation, fraud). Be conservative: reserve 3 for genuinely thesis-changing news.\n"
    "Ticker: {ticker}\n"
    "Headline: {headline}\n"
    "Snippet: {snippet}"
)


def _triage_news(deepseek_key: str, ticker: str, items: list[dict]) -> list[dict]:
    client = OpenAI(api_key=deepseek_key, base_url="https://api.deepseek.com")
    triaged = []
    for item in items:
        try:
            prompt = TRIAGE_PROMPT.format(
                ticker=ticker,
                headline=item["headline"][:300],
                snippet=item.get("snippet", "")[:400],
            )
            resp = client.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=150,
            )
            raw = resp.choices[0].message.content or ""
            parsed = _parse_materiality(raw)
            if parsed:
                triaged.append({
                    "headline": item["headline"],
                    "url": item.get("url", ""),
                    "published_at": item.get("published", ""),
                    "source": "google_news",
                    **parsed,
                })
        except Exception:
            continue
    return triaged


# ── Formatter dispatch ────────────────────────────────────────────────────────

def _build_md_front_matter(signals: list[dict], drawdowns: dict[str, dict]) -> str:
    lines = ["---"]
    lines.append(f"generated_at: {datetime.now(SGT).isoformat()}")
    lines.append("signals:")
    for s in signals:
        dd = drawdowns.get(s["ticker"], {})
        lines.append(f"  - ticker: {s['ticker']}")
        lines.append(f"    type: {s['type']}")
        lines.append(f"    severity: {s['severity']}")
        lines.append(f"    chg_3d: {dd.get('chg_3d', 'N/A')}")
        lines.append(f"    chg_5d: {dd.get('chg_5d', 'N/A')}")
        lines.append(f"    vs_20d_high: {dd.get('vs_20d_high', 'N/A')}")
    lines.append("---")
    return "\n".join(lines)


def _dispatch_formatter(wm_token: str, formatter_path: str, md_path: str, wm_base: str = "http://localhost:8080"):
    try:
        resp = requests.post(
            f"{wm_base}/api/w/admins/jobs/run/p/u%2Fadmin%2F{formatter_path}",
            headers={
                "Authorization": f"Bearer {wm_token}",
                "Content-Type": "application/json",
            },
            json={"md_path": md_path},
            timeout=30,
        )
        return resp.status_code == 200
    except Exception:
        return False


# ── Main ─────────────────────────────────────────────────────────────────────

def main(portfolio_db: dict = {}, deepseek_key: str = "", finnhub_key: str = "",
         telegram_bot_token: str = "", telegram_owner_id: str = "", wm_token: str = ""):
    conn = psycopg2.connect(**portfolio_db)
    conn.autocommit = True
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("SELECT DISTINCT ticker FROM portfolio_positions ORDER BY ticker")
    tickers = [r["ticker"] for r in cur.fetchall()]

    all_signals = []
    all_drawdowns = {}
    now = datetime.now(SGT)

    for tk in tickers:
        try:
            closes = _load_closes(cur, tk)
            if len(closes) < 4:
                continue

            dd = _cumulative_drawdowns(closes)
            all_drawdowns[tk] = dd
            ps = _price_signal(dd, PRICE_THRESHOLDS)

            events: list[dict] = []
            news_items = _fetch_news(f"{tk} stock")
            existing_urls = set()
            cur.execute("SELECT url_hash FROM position_events WHERE ticker=%s", (tk,))
            for er in cur.fetchall():
                existing_urls.add(er["url_hash"])

            triaged = _triage_news(deepseek_key, tk, news_items)
            for t in triaged:
                uh = _url_hash(t.get("url", f"{tk}_{t['headline']}"))
                if uh in existing_urls:
                    continue
                existing_urls.add(uh)
                pub = t.get("published_at", "")
                try:
                    pub_dt = datetime.strptime(pub, "%a, %d %b %Y %H:%M:%S %Z") if pub else None
                except ValueError:
                    pub_dt = None
                cur.execute("""
                    INSERT INTO position_events (ticker, published_at, source, headline, url, url_hash, materiality, category, direction, impact)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (ticker, url_hash) DO NOTHING
                """, (tk, pub_dt, t.get("source"), t["headline"], t.get("url"), uh,
                      t["materiality"], t.get("category"), t.get("direction"), t.get("impact")))
                events.append({
                    "fetched_at": now,
                    "materiality": t["materiality"],
                })

            sig_type = None
            severity = "HIGH"

            if ps:  # Phase 1: cumulative-price only
                sig_type = "price_cumulative"
                all_signals.append({"ticker": tk, "type": sig_type, "severity": severity,
                                    "chg_3d": dd.get("chg_3d"), "chg_5d": dd.get("chg_5d"),
                                    "vs_20d_high": dd.get("vs_20d_high")})

                # Check cooldown
                cur.execute(
                    "SELECT 1 FROM position_signals WHERE ticker=%s AND signal_type=%s AND created_at > NOW() - INTERVAL '%s minutes'",
                    (tk, sig_type, NEWS_COOLDOWN_MINUTES))
                if cur.fetchone():
                    continue  # cooldown active

                cur.execute("""
                    INSERT INTO position_signals (ticker, signal_type, severity, detail, alerted)
                    VALUES (%s,%s,%s,%s::jsonb, TRUE)
                """, (tk, sig_type, severity, json.dumps(dd)))

                # Write canonical .md
                research_dir = "/research/portfolio"
                os.makedirs(research_dir, exist_ok=True)
                md_path = f"{research_dir}/sentinel_{now.strftime('%Y-%m-%d_%H%M')}.md"
                fm = _build_md_front_matter(all_signals, all_drawdowns)
                narrative = (
                    f"# Position Sentinel — {now.strftime('%Y-%m-%d %H:%M SGT')}\n\n"
                    f"The following positions triggered cumulative-price alerts:\n\n"
                )
                for s in all_signals:
                    dd_tk = all_drawdowns.get(s["ticker"], {})
                    narrative += (
                        f"- **{s['ticker']}**: 3d {dd_tk.get('chg_3d','N/A')}%, "
                        f"5d {dd_tk.get('chg_5d','N/A')}%, "
                        f"vs 20d high {dd_tk.get('vs_20d_high','N/A')}%\n"
                    )
                narrative += "\n<!-- DETAIL -->\n"
                with open(md_path, "w") as f:
                    f.write(fm + "\n" + narrative)
                _dispatch_formatter(wm_token, "position_sentinel_telegram", md_path)

            # Log-only: news_materiality and confluence
            agg = _aggregate_materiality(events)
            if ps and _confluence(ps, events):
                cur.execute("""
                    INSERT INTO position_signals (ticker, signal_type, severity, detail, alerted)
                    VALUES (%s,%s,%s,%s::jsonb, FALSE)
                """, (tk, "confluence", "CRITICAL", json.dumps({"chg_dd": dd, "cum_materiality": agg})))
            elif agg >= 4:
                cur.execute("""
                    INSERT INTO position_signals (ticker, signal_type, severity, detail, alerted)
                    VALUES (%s,%s,%s,%s::jsonb, FALSE)
                """, (tk, "news_materiality", "MED", json.dumps({"cum_materiality": agg})))

        except Exception:
            traceback.print_exc()

    cur.close()
    conn.close()
    return {"ok": True, "signals": len(all_signals), "tickers_scanned": len(tickers)}
