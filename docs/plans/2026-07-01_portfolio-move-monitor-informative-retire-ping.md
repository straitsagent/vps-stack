---
Subject: Portfolio Move Monitor — prices/shares/news/index context in .md + retire StraitsAgent Telegram ping
Date: 2026-07-01
Status: approved
Planner model: claude-sonnet-4-6
Executor model: opencode
Risk tier: HIGH (planner-locked oracle — different executor model, live market-hours production script, 4 new external data sources)
Hard Rules in force: [1, 4, 6, 7, 10, 12, 15, 16, 17, 18, 19, 20, 22]
Complies with: docs/EXECUTOR_CONTRACT.md
Files to read before coding: CLAUDE.md, docs/EXECUTOR_CONTRACT.md, docs/TESTING.md, windmill/u/admin/portfolio_move_monitor.py, windmill/u/admin/portfolio_move_monitor_telegram.py, windmill/u/admin/research_tool.py (news-source implementations to reuse verbatim — Step 2b block + `_fetch_google_news`), windmill/u/admin/position_sentinel.py (hourly per-ticker news pattern), windmill/u/admin/macro_research.py (index ETF-proxy symbol convention), agent/tests/test_windmill_scripts.py (pmmm harness + youtube-retirement precedent)
---

# Plan: Portfolio Move Monitor — richer content, retire the Telegram ping

## Context

`portfolio_move_monitor` runs hourly during market hours (HK schedule 9am–4pm SGT, US schedule 9am–4pm
ET) and, on a threshold breach (portfolio ±1.5% or any position ±5%), writes a canonical `.md` to
`/research/portfolio/move_*.md` and (currently) pushes a Telegram alert via a dispatched formatter using
StraitsAgent's bot token.

Two things are changing at once, in one commit boundary (they touch the same file pair):

**1. The `.md` content has real bugs and real gaps, found by inspecting live output:**
- The narrative always claims the move "exceeded the configured threshold of ±1.5%" even when only a
  *position*-level threshold fired and the portfolio-level move never crossed 1.5% (verified live: a
  real event with portfolio_move=1.40% — under the 1.5% threshold — still says "exceeding ±1.5%").
- Both the `.md` narrative and the Telegram formatter hard-slice `position_alerts[:5]` — a live 9-alert
  event only narrates the first 5; the other 4 are in the JSON but invisible in the readable text.
- `deepseek_key` is never passed via the schedule args, so the LLM narrative path has never actually run.
- No price levels, no share counts, no news, no market-wide context — a reader can't tell *why* a stock
  moved or whether this is a broad market move vs. stock-specific.

**2. Hermes now consumes `move_*.md` directly via its own hourly cron (owner confirmed, already set up).**
This makes StraitsAgent's Telegram push redundant — real-time delivery is Hermes' job now, not
StraitsAgent's. **Precedent already exists for this exact pattern**: `youtube_monitor_telegram` was
retired the same way on 2026-06-29 ("Hermes will consume `.md`" — see `docs/ROADMAP.md` line 479,
`CLAUDE.md`'s formatter list). Follow it exactly: **retain the formatter file on disk, frozen** (do not
edit or delete `portfolio_move_monitor_telegram.py`); remove only the dispatch call + its schedule args
from the producer.

**New in this revision — owner requested (2026-07-01), after reviewing a preview:**
- Previous-close price, current (live) price, and portfolio share count for every alerted ticker.
- News search per alerted ticker across **4 sources**: Finnhub `company-news`, Google News RSS, Yahoo
  Finance news (`yfinance` `.news`), Seeking Alpha RSS — to ground the narrative in an actual reported
  catalyst instead of speculative boilerplate.
- Index-move context (2 major index ETF proxies matching the session) so the narrative can state whether
  a move looks market-wide (beta-driven) or stock-specific.

**Do not build new news-fetching code from scratch — reuse what's already proven in this repo:**
- `windmill/u/admin/research_tool.py`, `main()` Step 2b (~line 1900–1971): working Finnhub
  `company-news`, Seeking Alpha RSS (`feedparser.parse(f"https://seekingalpha.com/api/sa/combined/{ticker}.xml")`),
  and `yfinance` `.news` calls, each independently try/excepted so one source failing doesn't kill the
  others. `is_us_ticker = is_stock and not ticker.endswith(".HK")` is the exact pattern for gating
  Finnhub to US tickers (our portfolio's HK tickers all end `.HK`).
- `research_tool.py`, `_fetch_google_news(query, max_items=5)` (~line 1043): Google News RSS via
  `feedparser` + `urllib.parse.quote`. Copy this function's logic directly.
- `windmill/u/admin/position_sentinel.py`: already does hourly per-holding news triage — same operating
  cadence and news-fetch-only-on-signal pattern this plan follows.
- `windmill/u/admin/macro_research.py`, `FINNHUB_SYMBOLS` dict (~line 32): the ETF-proxy convention for
  index data — `SP500→SPY`, `NDX→QQQ`, `HSI→EWH`, `CSI300→FXI`. Reuse the **same symbols** here (via
  `yfinance`, which this script already depends on) so index figures are comparable across reports.
- `finnhub_key` is an **existing** Windmill variable (`$var:u/admin/finnhub_key`), already used by 5+
  other schedules (`portfolio_review`, `portfolio_analyst_alert`, `macro_research_daily`, etc.) — no new
  credential needed.

## Files changed

| Action | Path | Change |
|--------|------|--------|
| Edit | `windmill/u/admin/portfolio_move_monitor.py` | See "Code changes" below — this is the bulk of the work |
| Edit | `windmill/u/admin/portfolio_move_monitor.schedule.yaml` | Remove `telegram_bot_token`/`telegram_owner_id`; add `deepseek_key: $var:u/admin/deepseek_key` and `finnhub_key: $var:u/admin/finnhub_key` |
| Edit | `windmill/u/admin/portfolio_move_monitor_us.schedule.yaml` | Same as above |
| No change | `windmill/u/admin/portfolio_move_monitor_telegram.py` | **Frozen, retained on disk** — matches youtube/health-check/macro retirement precedent. Do not touch. |
| Edit | `agent/tests/test_windmill_scripts.py` | See "Test changes" below |
| Edit | `CLAUDE.md` | Move `portfolio_move_monitor_telegram` from "Currently-pushing" to "Retired (formatters retained, no longer dispatched as of 2026-07-01)" |
| Edit | `docs/ROADMAP.md` | Move Monitor row (~line 67): note Telegram retired, Hermes consumes `.md`, news+index context added. Formatter table row (~line 476): `⚠️ Retained on disk — dispatch removed 2026-07-01 (Hermes consumes .md hourly)`, matching the `youtube_monitor_telegram` row exactly |

## Code changes — `portfolio_move_monitor.py`

### New imports
Add `import feedparser` and `import urllib.parse`. Add `# feedparser>=6.0` to the `# Requirements:`
header comment block at the top of the file (alongside the existing `psycopg2-binary`, `pytz`,
`yfinance` lines).

### New pure functions (each independently try/excepted, empty list/dict on any failure — never raise)

```python
def _fetch_finnhub_news(ticker: str, finnhub_key: str, max_items: int = 5) -> list[dict]:
    """Finnhub company-news, last 7 days. Reuse research_tool.py's Step 2b Finnhub block verbatim
    (same endpoint, same params, same 10s timeout). Returns [{"source":"finnhub","title","url","date"}]."""

def _fetch_google_news_for_ticker(query: str, max_items: int = 5) -> list[dict]:
    """Copy research_tool.py's _fetch_google_news(query, max_items) verbatim.
    Returns [{"source":"google_news","title","url","date"}]."""

def _fetch_seeking_alpha_news(ticker: str, max_items: int = 5) -> list[dict]:
    """Reuse research_tool.py's Step 2b Seeking Alpha RSS block verbatim
    (feedparser.parse(f"https://seekingalpha.com/api/sa/combined/{ticker}.xml")).
    Returns [{"source":"seeking_alpha","title","url","date"}]."""

def _fetch_yfinance_news(ticker: str, max_items: int = 5) -> list[dict]:
    """Reuse research_tool.py's Step 2b yfinance-news block verbatim (yf.Ticker(ticker).news).
    Returns [{"source":"yfinance","title","url","date"}]."""

def _fetch_ticker_news(ticker: str, company: str, is_us: bool, finnhub_key: str) -> list[dict]:
    """Aggregate all 4 sources for one ticker. Skip Finnhub if not is_us (ticker.endswith('.HK')).
    Priority order when capping: finnhub > seeking_alpha > yfinance > google_news (matches
    research_tool.py's source_priority ordering). Cap at 5 items TOTAL per ticker (not per source) —
    keeps the LLM prompt bounded for events with many alerted tickers. Google News query = company name
    if available else ticker."""

def _fetch_index_moves(session: str) -> dict:
    """session == "HK" -> {"HSI": {"symbol":"EWH","pct":...}, "CSI300": {"symbol":"FXI","pct":...}}
    session == "US" -> {"SP500": {"symbol":"SPY","pct":...}, "NDX": {"symbol":"QQQ","pct":...}}
    Uses yf.Ticker(symbol).fast_info.last_price and .previous_close (same yfinance dependency
    already used for position prices — no new library). Empty dict on any failure."""
```

These are **seams** — each must be a standalone module-level function (not inlined in `main()`) so
tests can `patch.object(mod, "_fetch_ticker_news", ...)` / `patch.object(mod, "_fetch_index_moves", ...)`
exactly like the existing `_send_email`/`_write_canonical_md` seams already are in this file.

### `main()` control-flow — critical correctness point, read carefully

The current code nests the **entire** `.md`-writing block inside `if telegram_bot_token and
telegram_owner_id:` (lines ~385–419 of the current file). Once `telegram_bot_token`/`telegram_owner_id`
are deleted as params, **this block must be un-nested to run whenever `portfolio_alert or
position_alerts` is true** (the same condition that currently guards against silent-exit). If this isn't
done, the `.md` file — the *only* remaining output artifact, the thing Hermes' hourly cron reads — would
silently stop being written entirely. This is the single most important thing to get right in this plan.

Sequence inside `main()`, after the existing silent-exit check (`if not portfolio_alert and not
position_alerts: return`) and before narrative construction:

```python
session = "HK" if 9 <= now_sgt.hour <= 16 else "US"
total_portfolio_value = sum(p["position_value"] for p in positions)  # all positions, not just alerted
up   = sum(1 for p in positions if p["intraday_pct"] > 0.01)
down = sum(1 for p in positions if p["intraday_pct"] < -0.01)
breadth = {"up": up, "down": down, "flat": len(positions) - up - down, "total": len(positions)}
index_moves = _fetch_index_moves(session)

for p in position_alerts:
    p["previous_close"] = p["baseline_native"]   # already computed above in the positions loop
    p["current_price"]  = p["live_native"]        # already computed above
    p["shares"]          = p["shares"]             # already present, just carried through to front-matter
    p["news"] = _fetch_ticker_news(
        p["ticker"], p["company"], not p["ticker"].endswith(".HK"), finnhub_key
    )
```

(`position_value`, `baseline_native`, `live_native`, `shares`, `company` are all already computed in the
existing positions-loop — nothing new to fetch there, just carry them through to `position_alerts` and
the front-matter dict, which today drops most of this.)

### Front-matter — additive only, old keys byte-identical

```json
{
  "time_str": "...", "portfolio_move": 1.4, "total_impact": 14371.77,
  "pct_threshold": 1.5, "pos_threshold": 5.0,
  "session": "US",
  "total_portfolio_value_usd": 1024878.0,
  "portfolio_triggered": false,
  "position_triggered": true,
  "breadth": {"up": 19, "down": 9, "flat": 4, "total": 32},
  "index_moves": {"SP500": {"symbol": "SPY", "pct": 0.31}, "NDX": {"symbol": "QQQ", "pct": 0.48}},
  "position_alerts": [
    {"ticker": "AMAT", "company": "Applied Materials Inc", "shares": 50,
     "intraday_pct": -7.8852, "dollar_impact": -2850.5,
     "previous_close": 723.00, "current_price": 666.9, "currency": "USD",
     "news": [{"source": "finnhub", "title": "...", "url": "...", "date": "2026-07-01"}]}
  ]
}
```

### Exact LLM prompt (Hard Rule 10 — approved, copy verbatim into `_build_move_narrative`)

```
You are a portfolio risk analyst. A portfolio move alert was triggered at {time_str} ({session} session).

What triggered this alert: {trigger_desc}
Portfolio value: ${total_portfolio_value:,.0f} | Dollar impact of this move: ${abs(total_impact):,.0f}
Market breadth: {breadth_up} up / {breadth_down} down / {breadth_flat} flat (of {breadth_total} positions)
Index context: {index_desc}

All flagged positions ({n_alerts} total):
{pos_desc}

Write a detailed ≥500-word analytical report explaining likely causes of this move, the risk
implications, what to watch next, and any recommended monitoring actions. Use the index context to
state plainly whether this looks like a market-wide (beta-driven) move or a stock-specific move. For
each flagged position, use the provided news headlines (if any) to ground your explanation of the move
in an actual reported catalyst — cite the headline briefly. If no news is provided for a position, say
so explicitly and describe it as an unexplained/technical move rather than inventing a cause. State
plainly and accurately which threshold(s) were actually breached — do not claim the portfolio-level
threshold was exceeded unless it genuinely was. Continuous prose, no bullet points or headers. Minimum
500 words.
```

Where (computed in code, never left to the model to phrase):
```python
trigger_desc = (
    f"both the portfolio-level threshold (±{pct_threshold:.1f}%) and {len(position_alerts)} "
    f"position-level threshold(s) (±{pos_threshold:.1f}%)" if portfolio_triggered and position_triggered
    else f"the portfolio-level threshold (±{pct_threshold:.1f}%)" if portfolio_triggered
    else f"{len(position_alerts)} position-level threshold(s) (±{pos_threshold:.1f}%) only — the "
         f"portfolio-level move of {portfolio_move:+.2f}% did not itself cross ±{pct_threshold:.1f}%"
)
index_desc = ", ".join(f"{k} ({v['symbol']}) {v['pct']:+.2f}%" for k, v in index_moves.items()) or "unavailable"
pos_desc = "\n".join(
    f"  {p['ticker']} ({p['company']}, {p['shares']:.0f} shares): {p['intraday_pct']:+.2f}% "
    f"(${abs(p['dollar_impact']):,.0f} impact, {p['currency']} {p['previous_close']:.2f} -> {p['current_price']:.2f})\n"
    f"    News: " + ("; ".join(f\"[{n['source']}] {n['title']}\" for n in p['news']) if p['news'] else "none found")
    for p in position_alerts
)
```

The **programmatic fallback** (no `deepseek_key` / API failure) must use the same `trigger_desc` and
loop over ALL `position_alerts` (no `[:5]`), and should mention the top news headline per ticker if
present (one sentence), matching the existing fallback's per-ticker paragraph style — but is not
required to synthesize the beta-vs-idiosyncratic framing (that's the LLM path's job; the fallback stays
mechanical/templated as it is today, just de-bugged and de-truncated).

### Deletions
- `_dispatch_formatter` function and its call site
- `telegram_bot_token`/`telegram_owner_id` params from `main()`'s signature
- The `if telegram_bot_token and telegram_owner_id:` gate itself (superseded by the always-run block above)

## Test changes — `agent/tests/test_windmill_scripts.py`

- Replace `test_move_monitor_has_telegram_params`, `test_move_monitor_sends_telegram_on_breach`,
  `test_move_monitor_telegram_guarded_by_token_check` with one `test_move_monitor_no_longer_dispatches_telegram`
  (mirrors `test_youtube_no_longer_dispatches_telegram` exactly — `assert "portfolio_move_monitor_telegram"
  not in src` and `assert "_dispatch_formatter" not in src`).
- `_render_portfolio_move_monitor_artifacts`: remove the `patch.object(mod, "_dispatch_formatter", ...)`
  line and the `telegram_bot_token`/`telegram_owner_id` kwargs from the `mod.main(...)` call. **Add**
  `patch.object(mod, "_fetch_ticker_news", return_value=[...fixture...])` and `patch.object(mod,
  "_fetch_index_moves", return_value={...fixture...})` so the harness stays fully offline/deterministic
  (no real network calls in the test suite — this is required, not optional).
- `portfolio_move_monitor_telegram.py`'s own tests (`test_move_monitor_formatter_*`,
  `test_contract_move_monitor_alert_details_survive`) — **no changes**; frozen formatter, old schema
  keys unchanged, still passes as-is.
- New tests required: trigger-description accuracy for all 3 cases (portfolio-only / position-only /
  both); full (>5) position-alert narration with no truncation; all 5 new front-matter top-level keys
  present with correct types (`session` ∈ {"HK","US"}, `breadth` dict shape, `index_moves` dict shape);
  each `position_alerts[]` item has `previous_close`/`current_price`/`shares`/`news` keys; `_fetch_*`
  news functions each return `[]` (not raise) when given a mocked failing `requests`/`feedparser` call;
  `_fetch_ticker_news` skips Finnhub for a `.HK` ticker; `_fetch_ticker_news` caps at 5 total items even
  when all 4 sources return results.

## Locked Oracle Tests (G1)

```python
# LOCKED ORACLE — copy verbatim, do not modify assertions
import subprocess
def run(c):
    r = subprocess.run(c, shell=True, capture_output=True, text=True, cwd="/root")
    return r.returncode, r.stdout + r.stderr

PMM = "/root/windmill/u/admin/portfolio_move_monitor.py"
# O1 — telegram dispatch fully removed from the producer
rc, o = run(f"grep -c '_dispatch_formatter\\|telegram_bot_token\\|telegram_owner_id' {PMM}")
assert o.strip() == "0", f"O1 FAIL: telegram refs remain: {o}"
print("O1 PASS")
# O2 — deepseek_key + finnhub_key wired into both schedules
for sched in ("portfolio_move_monitor.schedule.yaml", "portfolio_move_monitor_us.schedule.yaml"):
    rc, _ = run(f"grep -q 'deepseek_key' /root/windmill/u/admin/{sched}")
    assert rc == 0, f"O2 FAIL: deepseek_key missing from {sched}"
    rc, _ = run(f"grep -q 'finnhub_key' /root/windmill/u/admin/{sched}")
    assert rc == 0, f"O2 FAIL: finnhub_key missing from {sched}"
print("O2 PASS")
# O3 — narrative no longer truncates to top 5
rc, o = run(f"grep -n 'position_alerts\\[:5\\]' {PMM}")
assert o.strip() == "", f"O3 FAIL: still slicing to [:5]: {o}"
print("O3 PASS")
# O4 — trigger-type flags wired into front-matter construction
rc, o = run(f"grep -c 'portfolio_triggered' {PMM}")
assert int(o.strip()) >= 2, f"O4 FAIL: portfolio_triggered not wired (found {o.strip()} refs)"
print("O4 PASS")
# O5 — all new context keys present in the script
for key in ("total_portfolio_value_usd", "\"session\"", "breadth", "position_triggered", "index_moves"):
    rc, _ = run(f"grep -q '{key}' {PMM}")
    assert rc == 0, f"O5 FAIL missing: {key}"
print("O5 PASS")
# O6 — CLAUDE.md formatter list updated, old formatter file still present (frozen, not deleted)
rc, o = run("grep 'Retired (formatters retained' /root/CLAUDE.md")
assert "portfolio_move_monitor_telegram" in o, "O6 FAIL: CLAUDE.md retired-list not updated"
rc, _ = run("test -f /root/windmill/u/admin/portfolio_move_monitor_telegram.py")
assert rc == 0, "O6 FAIL: formatter file must remain on disk (frozen, not deleted)"
print("O6 PASS")
# O7 — new fetch functions exist as standalone seams (patchable), feedparser added to Requirements
for fn in ("_fetch_finnhub_news", "_fetch_google_news_for_ticker", "_fetch_seeking_alpha_news",
           "_fetch_yfinance_news", "_fetch_ticker_news", "_fetch_index_moves"):
    rc, _ = run(f"grep -q 'def {fn}' {PMM}")
    assert rc == 0, f"O7 FAIL missing function: {fn}"
rc, _ = run(f"grep -q 'feedparser' {PMM}")
assert rc == 0, "O7 FAIL: feedparser not imported/required"
print("O7 PASS")
# O8 — position_alerts enriched with prices/shares/news
for key in ("previous_close", "current_price", '"shares"', '"news"'):
    rc, _ = run(f"grep -q '{key}' {PMM}")
    assert rc == 0, f"O8 FAIL missing position_alerts key: {key}"
print("O8 PASS")
# O9 — full agent test suite green
rc, o = run("cd /root/agent && python3 -m pytest tests/test_windmill_scripts.py -q 2>&1 | tail -3")
assert rc == 0, f"O9 FAIL: {o}"
print("O9 PASS")
print("\nLOCKED ORACLE: PASS")
```

## RED-proof requirement (G2)

Before editing, `test_move_monitor_no_longer_dispatches_telegram` does not exist → RED. Paste
`cd /root/agent && python3 -m pytest tests/test_windmill_scripts.py -k move_monitor_no_longer_dispatches -q`
failing (collection error) before the edit, then paste it passing after.

## Asserting Verification Script (G4)

Must run fully offline (mock `requests`/`feedparser`/`yfinance` for the news+index seams — do NOT hit
real Finnhub/Seeking Alpha/Google News/yfinance APIs in this script; use `patch.object` on the module
exactly as the DB/price mocks already do). Exercises: a 9-position trigger with mixed news coverage
(some tickers with headlines, at least one with none), and confirms the `.md` is written with the new
`main()` signature (no telegram args) — the critical un-nesting check from "Code changes" above.

```bash
cd /root/agent
fail=0
chk(){ [ "$1" -eq 0 ] && echo "PASS: $2" || { echo "FAIL: $2"; fail=1; }; }

python3 - <<'PYEOF'
import sys, os
sys.path.insert(0, "tests")
os.chdir("/root/agent")
from test_windmill_scripts import _load_portfolio_move_monitor_module
import re, json, datetime as dt
from unittest.mock import MagicMock, patch

mod = _load_portfolio_move_monitor_module()
now_sgt = dt.datetime(2026, 7, 1, 23, 0, 0, tzinfo=dt.timezone(dt.timedelta(hours=8)))  # US session

class _Stub:
    @classmethod
    def now(cls, tz=None): return now_sgt

pos_rows = [("AMAT","Applied Materials",50,"USD"), ("AMD","AMD",50,"USD"),
            ("CRM","Salesforce",100,"USD"), ("CRWV","CoreWeave",150,"USD"),
            ("META","Meta",200,"USD"), ("PINS","Pinterest",550,"USD"),
            ("RDDT","Reddit",100,"USD"), ("TSM","TSMC",100,"USD"), ("WIX","Wix",400,"USD"),
            ("MSFT","Microsoft",5,"USD")]
baseline_rows = [(t, 100.0, dt.date(2026,6,30), "USD") for t,_,_,_ in pos_rows]
live_prices = {"AMAT":92.0,"AMD":94.9,"CRM":105.0,"CRWV":86.0,"META":110.5,
               "PINS":106.0,"RDDT":109.9,"TSM":94.3,"WIX":109.3,"MSFT":100.3}

mock_cursor = MagicMock()
mock_cursor.fetchall.side_effect = [pos_rows, baseline_rows]
mock_cursor.fetchone.return_value = (7.80,)
mock_conn = MagicMock()
mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
mock_psycopg2 = MagicMock(); mock_psycopg2.connect.return_value = mock_conn

def _mk_fi(t):
    fi = MagicMock(); fi.last_price = live_prices[t]; return fi
mock_yf = MagicMock()
mock_yf.Ticker.side_effect = lambda t: MagicMock(fast_info=_mk_fi(t))

captured = {}
def _fake_write_md(content, path): captured["md"] = content

def _fake_news(ticker, company, is_us, finnhub_key):
    if ticker == "AMAT":
        return [{"source": "finnhub", "title": "AMAT guides below Street on export curbs",
                  "url": "https://x", "date": "2026-07-01"}]
    return []  # every other ticker: no news found — must not be fabricated in narrative

def _fake_index(session):
    assert session == "US", f"expected US session at 23:00 SGT, got {session}"
    return {"SP500": {"symbol": "SPY", "pct": 0.31}, "NDX": {"symbol": "QQQ", "pct": 0.48}}

with patch.object(mod, "psycopg2", mock_psycopg2), \
     patch.object(mod, "yf", mock_yf), \
     patch.object(mod, "datetime", _Stub), \
     patch.object(mod, "_write_canonical_md", side_effect=_fake_write_md), \
     patch.object(mod, "_fetch_ticker_news", side_effect=_fake_news), \
     patch.object(mod, "_fetch_index_moves", side_effect=_fake_index), \
     patch("os.makedirs"), patch("time.sleep"):
    mod.main(portfolio_db={"host":"x","port":5432,"dbname":"x","user":"x","password":"x"},
             deepseek_key="", finnhub_key="")

md = captured.get("md", "")
assert md, ".md must be written even with the new (telegram-free) main() signature — check " \
           "_write_canonical_md isn't still nested inside a deleted telegram conditional"
fm_match = re.search(r"```json\s*\n([\s\S]*?)\n```", md)
fm = json.loads(fm_match.group(1))
narrative = md[fm_match.end():].split("<!-- DETAIL -->")[0]

assert fm.get("session") == "US"
assert "total_portfolio_value_usd" in fm and "breadth" in fm
assert fm.get("index_moves", {}).get("SP500", {}).get("symbol") == "SPY"
assert len(fm["position_alerts"]) == 9, f"expected 9 alerted positions, got {len(fm['position_alerts'])}"
for p in fm["position_alerts"]:
    assert p["ticker"] in narrative, f"{p['ticker']} missing from narrative — truncation bug not fixed"
    assert "previous_close" in p and "current_price" in p and "shares" in p and "news" in p, \
        f"{p['ticker']} missing enriched fields"
amat = next(p for p in fm["position_alerts"] if p["ticker"] == "AMAT")
assert len(amat["news"]) == 1 and "export curbs" in amat["news"][0]["title"]
no_news_tickers = [p["ticker"] for p in fm["position_alerts"] if p["ticker"] != "AMAT"]
assert all(len(p["news"]) == 0 for p in fm["position_alerts"] if p["ticker"] != "AMAT")
print(f"PASS: session=US, 9/9 positions narrated, AMAT has 1 news item, "
      f"{len(no_news_tickers)} tickers correctly show no news")
PYEOF
chk $? "live artifact scenario (9-position trigger, mixed news coverage, US session)"

grep -q '_dispatch_formatter' /root/windmill/u/admin/portfolio_move_monitor.py; [ $? -ne 0 ]; chk $? "no telegram dispatch in producer"
python3 -m pytest tests/test_windmill_scripts.py -q 2>&1 | tail -3; chk ${PIPESTATUS[0]} "full suite green"
[ $fail -eq 0 ] && echo "PASS" || exit 1
```

## Acceptance Gate

- [ ] `trigger_desc` correctly distinguishes portfolio-only / position-only / both cases
- [ ] All alerted positions appear in the narrative — no `[:5]` truncation anywhere (producer or formatter's caller)
- [ ] `deepseek_key` + `finnhub_key` reach the script via both schedules
- [ ] Front-matter has `session`, `total_portfolio_value_usd`, `portfolio_triggered`, `position_triggered`,
  `breadth`, `index_moves`; each `position_alerts[]` item has `previous_close`, `current_price`, `shares`, `news`
- [ ] `.md` is written whenever alerted, **not gated by any telegram-related conditional** (verify: G4's
  live scenario calls `main()` with the new signature and confirms the artifact is captured)
- [ ] All 4 news sources implemented as independent try/excepted seams; Finnhub skipped for `.HK` tickers;
  `_fetch_ticker_news` caps at 5 items total per ticker
- [ ] Index moves use the same ETF-proxy symbols as `macro_research.py` (SPY/QQQ/EWH/FXI)
- [ ] `main()` no longer accepts `telegram_bot_token`/`telegram_owner_id`; `_dispatch_formatter` deleted
- [ ] `portfolio_move_monitor_telegram.py` untouched, still on disk, its own tests still pass unmodified
- [ ] Test suite mocks all news/index network calls — no live API calls in `agent/tests/`
- [ ] `CLAUDE.md` + `docs/ROADMAP.md` reflect the retirement + new capability
- [ ] LOCKED ORACLE O1–O9 pass verbatim; RED→GREEN pasted; G4 script ends in `PASS`
- [ ] `wmill script push` succeeded for `portfolio_move_monitor.py`; both schedules updated via API (never `wmill sync push`)

## Execution

1. On approval: copy this file to `docs/plans/2026-07-01_portfolio-move-monitor-informative-retire-ping.md`
   with `Status: approved`, commit. Then set `Status: executing`.
2. Work top to bottom: code changes → test changes → docs.
3. Paste RED run, then GREEN run. Run the LOCKED ORACLE verbatim + the G4 script (ends `PASS`).
4. Leave `Status: executing` for reviewer (per this repo's `/verify-implementations` convention — the
   reviewer independently re-runs the oracle and flips to `done`).
Satisfy all five `docs/EXECUTOR_CONTRACT.md` gates; do not modify the `# LOCKED ORACLE` block; never
`wmill sync push`. Do not touch `portfolio_move_monitor_telegram.py` — retirement means "stop
dispatching," not "delete." Do not invent new API integrations — the 4 news sources and the index-proxy
symbols must be copied from the existing, working implementations named above, not reimplemented from
scratch. Do not redesign; if the plan is ambiguous or wrong, stop and report — do not improvise.
