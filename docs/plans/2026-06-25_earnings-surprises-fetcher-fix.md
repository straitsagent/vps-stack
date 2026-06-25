---
Subject: earnings_surprises Fetcher Fix — repair the yfinance column-detection bug that kept the table empty
Date: 2026-06-25
Status: draft
Planner model: claude-opus-4 (Claude Code)
Executor model: deepseek (opencode) or any
Hard Rules in force: [7, 9, 11, 15, 17, 19, 20, 21]
Files to read before coding: CLAUDE.md, docs/TESTING.md, docs/OPERATIONS.md, windmill/u/admin/stock_data_fetcher.py
---

# Plan: earnings_surprises Fetcher Fix (Hygiene Initiative 3 of 5)

## Context

`earnings_surprises` has **0 rows** despite being load-bearing — read by three live consumers:
- `portfolio_rationalization.py:300-303` — "avg 4Q EPS beat" scoring factor (feeds the weekly Mon 9PM rationalization email/Telegram).
- `portfolio_candidate_eval.py:356-358` — `AVG(surprise_pct) AS avg_eps_surprise` in candidate gating.
- `research_tool.py:1563-1571` — earnings section of research reports.

**Root cause (confirmed live, not assumed):** `stock_data_fetcher.py._fetch_earnings_calendar` (the
only writer of the table) extracts EPS surprises from yfinance's `Ticker.earnings_dates` DataFrame.
At line 519 it looks for the actual-EPS column with `"actual" in str(c).lower()`. But yfinance names
that column **`Reported EPS`** — which contains no "actual" substring. So `actual_col` is always
`None`, the `if actual_col:` block (lines 521-549) is skipped entirely, `surprises` stays `[]`, and
`earnings_surprises` never receives a row. This has been broken since the code was written.

**Proof it's the extraction, not a never-run fetcher:** `next_earnings` is written in the *same*
`if earn:` block (stock_data_fetcher.py:838-849) and has **33 rows / 33 tickers** — so the fetcher
has run across the whole portfolio; only the surprises sub-block produced nothing.

**Live probe (yfinance 1.4.1, AAPL & MSFT):**
```
columns: ['EPS Estimate', 'Reported EPS', 'Surprise(%)']
code's actual_col -> None          # the bug
                           EPS Estimate  Reported EPS  Surprise(%)
2026-07-30 (future)              1.89           NaN          NaN     # must be excluded
2026-04-30                       1.94          2.01         3.46
2026-01-29                       2.67          2.84         6.25
...
```
Note yfinance even provides a ready-made `Surprise(%)` column the current code ignores.

### Decisions (resolved with owner this session)
- **Scope: fix + backfill all 33 portfolio positions** (owner choice). After the fix is test-green and
  one-ticker live-verified, re-run `stock_data_fetcher` for every position so the table fills
  immediately and the rationalization EPS-beat factor works at the next Monday 9PM run.
- **surprise_pct source:** recompute from estimate/actual (matches the existing logic; readers
  `AVG(surprise_pct)`), with yfinance's native `Surprise(%)` as fallback when recompute isn't possible.

### Why a small refactor (not a one-line patch)
Hard Rule 15 requires an artifact-driven test. The agent test container has **no pandas/yfinance**, so a
test cannot build a real `earnings_dates` DataFrame. The fix therefore **factors the pure extraction
logic out of the pandas/yfinance I/O** into two helpers that take plain Python data — directly testable
with stubbed imports (the established `sys.modules.setdefault(...)` pattern, e.g. test_windmill_scripts.py:3303).
This is the "seams factored" approach in docs/TESTING.md.

### Environment facts the executor needs
- Run from `/root`. Git from `/root` only. Script: `/root/windmill/u/admin/stock_data_fetcher.py`.
- Tests live in `/root/agent/tests/test_windmill_scripts.py` and **run inside the agent container**
  (Hard Rule 15): `docker exec root-straitsagent-1 python -m pytest tests/test_windmill_scripts.py -q`.
  Inside the container the script is at `/windmill/u/admin/stock_data_fetcher.py`; the test already
  resolves it via `STOCK_DATA_FETCHER` (a `__file__`-relative path) — reuse that constant.
- Windmill API base: `http://localhost:8080`, workspace `admins`.
  Token: `WM_TOKEN=$(grep "WM_TOKEN" /root/agent.env | cut -d= -f2 | tr -d ' ')`.
- Postgres: `docker exec root-portfolio_postgres-1 psql -U portfolio_user -d portfolio -c "<SQL>"`.
- Deploy: **`wmill script push u/admin/stock_data_fetcher.py`** from `/root/windmill` (Hard Rule 9 —
  never `wmill sync push`). The PostToolUse hook may also auto-push on edit; run the explicit push
  regardless to be sure.

---

## Files changed

| Action | Path | Change |
|--------|------|--------|
| Edit | `windmill/u/admin/stock_data_fetcher.py` | Add 2 pure helpers (`_pick_col`, `_extract_surprises`); rewrite the surprises sub-block of `_fetch_earnings_calendar` to use them + broadened column detection |
| Edit | `agent/tests/test_windmill_scripts.py` | Add `_load_sdf_stubbed()` + 3 regression tests (RED→GREEN) |
| Edit | `/root/docs/ROADMAP.md` | Mark Part 5 empty-table item: `earnings_surprises` resolved; update the `(0 rows)` annotations |
| Create | `/root/docs/logs/2026-06-25_earnings-surprises-fetcher-fix.md` | Implementation log |

No reader scripts change — they already query the table correctly.

---

## Checklist

### Step 1 — Write the failing tests first (RED) — Hard Rule 15
Add to `agent/tests/test_windmill_scripts.py`, in the "Stock Data Fetcher" section (after the existing
`test_stock_data_fetcher_*` tests, ~line 1648). Use the existing module-level `STOCK_DATA_FETCHER` constant.

```python
# ── earnings_surprises extraction (regression: yfinance 'Reported EPS' column) ──
# stock_data_fetcher is a data collector, not a sending script, so the email/Telegram
# artifact harness does not apply. The "artifact" here is the DB rows written to
# earnings_surprises; the fixture below mirrors REAL yfinance Ticker.earnings_dates output
# captured live for AAPL (columns: 'EPS Estimate', 'Reported EPS', 'Surprise(%)').
_EARNINGS_DATES_COLUMNS = ["EPS Estimate", "Reported EPS", "Surprise(%)"]


def _load_sdf_stubbed():
    """Load stock_data_fetcher with heavy imports stubbed so pure helpers are importable
    in the agent container (no pandas/yfinance installed there)."""
    from unittest.mock import MagicMock
    for _m in ("requests", "psycopg2", "yfinance", "bs4", "pandas", "numpy"):
        sys.modules.setdefault(_m, MagicMock())
    sys.modules.setdefault("windmill_http_client", MagicMock())
    spec = importlib.util.spec_from_file_location("_sdf_stub", STOCK_DATA_FETCHER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_pick_col_detects_reported_eps_actual_column():
    """REGRESSION: yfinance names the actual column 'Reported EPS' (no 'actual' substring).
    The old code searched only for 'actual' and silently matched nothing -> empty table."""
    sdf = _load_sdf_stubbed()
    assert sdf._pick_col(_EARNINGS_DATES_COLUMNS, ["reported", "actual"]) == "Reported EPS"
    assert sdf._pick_col(_EARNINGS_DATES_COLUMNS, ["estimate"]) == "EPS Estimate"
    # documents the exact defect: the old predicate finds nothing
    assert sdf._pick_col(_EARNINGS_DATES_COLUMNS, ["actual"]) is None


def test_extract_surprises_from_real_yfinance_records():
    """AAPL-shaped records incl. a future row with NaN actual: 4 past surprises extracted,
    future row excluded, surprise_pct RECOMPUTED from est/actual (not echoed from fixture)."""
    sdf = _load_sdf_stubbed()
    nan = float("nan")
    records = [
        {"period_date": "2026-07-30", "eps_estimate": 1.89, "eps_actual": nan,  "native_surprise_pct": nan},   # future
        {"period_date": "2026-04-30", "eps_estimate": 1.94, "eps_actual": 2.01, "native_surprise_pct": 3.46},
        {"period_date": "2026-01-29", "eps_estimate": 2.67, "eps_actual": 2.84, "native_surprise_pct": 6.25},
        {"period_date": "2025-10-30", "eps_estimate": 1.77, "eps_actual": 1.85, "native_surprise_pct": 4.52},
        {"period_date": "2025-07-31", "eps_estimate": 1.43, "eps_actual": 1.57, "native_surprise_pct": 9.48},
    ]
    out = sdf._extract_surprises(records)
    assert len(out) == 4, f"expected 4 past surprises, got {len(out)}"
    periods = [s["period_date"] for s in out]
    assert "2026-07-30" not in periods, "future (NaN-actual) row must be excluded"
    first = out[0]
    assert first["period_date"] == "2026-04-30"
    assert first["eps_estimate"] == 1.94 and first["eps_actual"] == 2.01
    # recomputed: (2.01 - 1.94) / 1.94 * 100 = 3.608...  (distinct from fixture native 3.46 -> not a tautology)
    assert abs(first["surprise_pct"] - 3.608) < 0.01, first["surprise_pct"]


def test_extract_surprises_empty_when_no_actuals():
    """Empty-artifact guard (Testing Critic #1): all-future records -> no surprises, not a false pass."""
    sdf = _load_sdf_stubbed()
    nan = float("nan")
    records = [{"period_date": "2026-07-30", "eps_estimate": 1.89, "eps_actual": nan, "native_surprise_pct": nan}]
    assert sdf._extract_surprises(records) == []
```

**Run and confirm RED:**
```bash
docker exec root-straitsagent-1 python -m pytest tests/test_windmill_scripts.py -k "pick_col or extract_surprises" -q
```
**Expected:** the 3 new tests FAIL with `AttributeError: module '_sdf_stub' has no attribute '_pick_col'`
(helpers don't exist yet). If they ERROR for any other reason (e.g. module won't load) STOP and report.

**Testing Critic sign-off (Hard Rule 20):** ① empty-artifact guarded by `test_extract_surprises_empty_when_no_actuals`;
② no template strings — asserts on computed numerics; ③ not a tautology — asserts the *recomputed*
3.608, not the fixture's native 3.46; ④ no ASD (collector, not sender) — documented in comment;
⑤ completeness — extraction test covers all 4 output fields.

### Step 2 — Implement the fix (GREEN)
In `windmill/u/admin/stock_data_fetcher.py`, add the two pure helpers **above** `_fetch_earnings_calendar`
(i.e. before line 485):

```python
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
            continue  # future / unreported period
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
```

Then **replace** the surprises sub-block — current lines 516-551, the
`try: ed_df = t.earnings_dates ... except Exception as e: log.info(f"[calendar] earnings dates: {e}")`
block — with:

```python
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
```

Leave the rest of `_fetch_earnings_calendar` (the `t.calendar` next-earnings block, lines 492-514, and
the final `data = {...}` assembly that already reads the local `surprises` list) **unchanged** — the
`surprises` variable is still populated, now correctly. The write path (lines 850-864) is unchanged.

**Run and confirm GREEN:**
```bash
docker exec root-straitsagent-1 python -m pytest tests/test_windmill_scripts.py -k "pick_col or extract_surprises" -q
docker exec root-straitsagent-1 python -m pytest tests/test_windmill_scripts.py -q   # full file, no regressions
```
**Expected:** 3 new tests pass; full file still green (was 479 passed before).

### Step 3 — Deploy (Hard Rule 9)
```bash
cd /root/windmill && wmill script push u/admin/stock_data_fetcher.py && cd /root
```
**Expected:** push succeeds. Hard Rule 19 — confirm the regenerated `stock_data_fetcher.script.lock`
resolves real packages (the live AAPL run in Step 4 is the real proof deps resolve).

### Step 4 — Live-verify ONE ticker (Hard Rule 17 — verify rows, not success:True)
Per the "one ticker at a time" rule, prove AAPL writes real rows before backfilling.
```bash
WM_TOKEN=$(grep "WM_TOKEN" /root/agent.env | cut -d= -f2 | tr -d ' ')
docker exec root-portfolio_postgres-1 psql -U portfolio_user -d portfolio -t -c "SELECT count(*) FROM earnings_surprises WHERE ticker='AAPL';"   # expect 0
curl -s -X POST "http://localhost:8080/api/w/admins/jobs/run_wait_result/p/u%2Fadmin%2Fstock_data_fetcher" \
  -H "Authorization: Bearer $WM_TOKEN" -H "Content-Type: application/json" \
  -d '{"ticker":"AAPL","portfolio_db":"$res:u/admin/portfolio_db","finnhub_key":"$var:u/admin/finnhub_key"}' \
  | python3 -c "import sys,json;d=json.load(sys.stdin);print('ok:',d.get('ok'),'| tables:',d.get('tables_written'))"
docker exec root-portfolio_postgres-1 psql -U portfolio_user -d portfolio -c \
  "SELECT period_date, eps_estimate, eps_actual, surprise_pct FROM earnings_surprises WHERE ticker='AAPL' ORDER BY period_date DESC;"
```
**Success — ALL must hold:**
1. Result `ok: True` and `tables_written` includes `earnings_surprises`.
2. The `psql` SELECT returns **≥1 row** with a non-null `surprise_pct` (this is the artifact — not `ok:True`).
**If 0 rows or `surprise_pct` all null:** STOP and report (the recompute or column detection is still off).

### Step 5 — Backfill all 33 positions (owner-approved)
One ticker at a time, sequential, with a small delay for yfinance rate limits.
```bash
WM_TOKEN=$(grep "WM_TOKEN" /root/agent.env | cut -d= -f2 | tr -d ' ')
TICKERS=$(docker exec root-portfolio_postgres-1 psql -U portfolio_user -d portfolio -t -A \
  -c "SELECT DISTINCT ticker FROM portfolio_positions ORDER BY ticker;")
for TK in $TICKERS; do
  RES=$(curl -s -X POST "http://localhost:8080/api/w/admins/jobs/run_wait_result/p/u%2Fadmin%2Fstock_data_fetcher" \
    -H "Authorization: Bearer $WM_TOKEN" -H "Content-Type: application/json" \
    -d "{\"ticker\":\"$TK\",\"portfolio_db\":\"\$res:u/admin/portfolio_db\",\"finnhub_key\":\"\$var:u/admin/finnhub_key\"}")
  echo "$TK -> $(echo "$RES" | python3 -c "import sys,json;d=json.load(sys.stdin);print('ok',d.get('ok'),'earnings_surprises' in (d.get('tables_written') or []))" 2>/dev/null || echo "PARSE_ERR")"
  sleep 4
done
```
Then confirm coverage:
```bash
docker exec root-portfolio_postgres-1 psql -U portfolio_user -d portfolio -c \
  "SELECT count(*) AS rows, count(DISTINCT ticker) AS tickers FROM earnings_surprises;"
```
**Expected:** rows > 0 across most tickers. **Partial coverage is acceptable and not a failure** —
yfinance `earnings_dates` is frequently empty for `.HK` listings and some ADRs; those tickers simply
won't have surprise rows. Note any ticker that returned `ok False` in the log.

### Step 6 — Docs + commit
1. Edit `/root/docs/ROADMAP.md`:
   - Part 5 "Empty Table Decisions" table — change the `earnings_surprises` row's action to:
     `✅ Resolved 2026-06-25 — column-detection bug fixed; backfilled. See log.`
   - Reference "Database Tables" section — remove `*(0 rows — see Part 5)*` after `earnings_surprises`
     (line ~397). Leave the `portfolio_thesis` `(0 rows)` annotation (separate initiative).
2. Create `/root/docs/logs/2026-06-25_earnings-surprises-fetcher-fix.md` (template below).
3. Commit from `/root`:
   ```bash
   cd /root
   git add windmill/u/admin/stock_data_fetcher.py windmill/u/admin/stock_data_fetcher.script.lock \
           agent/tests/test_windmill_scripts.py docs/ROADMAP.md \
           docs/logs/2026-06-25_earnings-surprises-fetcher-fix.md
   git commit -m "$(printf 'fix(stock_data_fetcher): populate earnings_surprises (yfinance column-detection bug)\n\n_fetch_earnings_calendar searched for an EPS column named \"actual\"; yfinance\nnames it \"Reported EPS\", so actual_col was always None and the surprises block\nnever ran, leaving earnings_surprises empty (read by rationalization,\ncandidate_eval, research_tool). Factored pure _pick_col + _extract_surprises\nhelpers (pandas-free, unit-tested), broadened column detection, kept recompute\nwith native Surprise%% fallback. Backfilled all 33 positions.\n\nCo-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>')"
   git push
   ```
**Success:** full pytest green; `git status` clean; push succeeded.

#### Log template — `/root/docs/logs/2026-06-25_earnings-surprises-fetcher-fix.md`
```markdown
# earnings_surprises Fetcher Fix — Implementation Log

**Date:** 2026-06-25
**Scope:** Repair the yfinance column-detection bug in stock_data_fetcher that left the
load-bearing earnings_surprises table empty; backfill all 33 portfolio positions.

## Root cause
_fetch_earnings_calendar detected the actual-EPS column with `"actual" in name`, but yfinance
names it `Reported EPS`. actual_col was always None -> surprises block skipped -> 0 rows.
Confirmed isolated: next_earnings (same write block) had 33 rows. Live probe (AAPL/MSFT)
showed columns ['EPS Estimate','Reported EPS','Surprise(%)'].

## Fix
- Added pure helpers `_pick_col` and `_extract_surprises` (+`_is_blank`) — pandas-free, unit-tested.
- Broadened actual-column detection to ["reported","actual"]; recompute surprise_pct from
  est/actual with native Surprise(%) fallback; future (NaN-actual) rows excluded.
- 3 regression tests added (RED->GREEN); full suite green.

## Live verification (Hard Rule 17)
- AAPL one-off run: ok=True, tables_written included earnings_surprises; psql showed N rows
  with non-null surprise_pct.
- Backfill: 33 positions re-run sequentially. Final coverage: <rows> rows / <tickers> tickers.
  Partial coverage expected — yfinance earnings_dates empty for some .HK/ADR listings.

## Downstream effect
- portfolio_rationalization EPS-beat factor now has data at the next Monday 9PM run.
- No reader code changed.

## Follow-up (out of scope)
- research_tool.py:585 has the IDENTICAL column-detection bug in its OWN _fetch_earnings_calendar
  (affects research-report earnings markdown only; it does not write the table). One-line fix —
  fold into a later hygiene pass.
- Hygiene initiative 3 of 5. Remaining: portfolio_thesis seeding; macro_daily_push disposition.
```

---

## Verification (run after the checklist)
- `docker exec root-straitsagent-1 python -m pytest tests/test_windmill_scripts.py -q` — all green,
  including the 3 new tests.
- `SELECT count(*) FROM earnings_surprises;` > 0 with non-null `surprise_pct` values.
- AAPL has ≥1 row; backfill log shows per-ticker outcomes.
- `git status` clean after commit + push.

## Out of scope (subsequent hygiene plans)
`portfolio_thesis` seeding, `macro_daily_push` disposition, optional API health monitor, and the
parallel `research_tool.py:585` column bug (report markdown only). Each handled separately.

## Execution
1. Set front-matter `Status: executing`, commit.
2. Work the checklist top to bottom; tick each `- [ ]` only when its success criteria are met.
   Step 1 must be RED before Step 2; Step 4 must pass before Step 5.
3. Run the Verification section.
4. Set `Status: done`, commit.
Do not redesign. If any command errors or output differs from "Expected", STOP and report — do not improvise or retry blindly.
