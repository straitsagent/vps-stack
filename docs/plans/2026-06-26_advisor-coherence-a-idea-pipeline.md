---
Subject: Advisor Coherence Phase 2 — Idea Pipeline + Rationalization-based Prescreener (watchlist infrastructure)
Date: 2026-06-26
Status: draft
Planner model: claude-sonnet-4-6 (Claude Code plan mode)
Executor model: deepseek (opencode) or any
Hard Rules in force: [1, 4, 6, 7, 9, 10, 11, 15, 17, 19, 20, 22]
Risk tier: HIGH (planner-locked oracle)
Complies with: docs/EXECUTOR_CONTRACT.md
Sign-off items:
  - Extraction model: deepseek-chat via $var:u/admin/deepseek_key  (owner confirmed 2026-06-26)
  - Extraction prompt: approved text in §Sign-offs section  (Hard Rule 10)
  - Neutral thesis score: 0.5  (owner confirmed 2026-06-26)
  - Refactoring approach: extract factor_scorer.py as Step 0  (owner confirmed 2026-06-26)
  - Rationalization schedule: Monday 9PM SGT → Saturday 6AM SGT  (owner confirmed 2026-06-26)
Files to read before coding: CLAUDE.md, docs/TESTING.md, windmill/u/admin/portfolio_rationalization.py (full scoring functions), windmill/u/admin/youtube_monitor.py (dispatch pattern at ~line 475), windmill/u/admin/morning_news_digest.py (md write at ~line 541, main signature), windmill/u/admin/portfolio_candidate_eval.py (main signature at ~line 1364, auto-dispatch at 1426-1450)
---

# Plan: Advisor Coherence Phase 2 — Idea Pipeline + Prescreener

## Context — why this matters

Two of the daily intelligence workflows in your stack — the YouTube monitor (every 6 hours, 37
finance channels) and the morning news digest (daily at 6:30 AM SGT) — read and summarize content
that frequently mentions specific tickers and investment ideas ("Microsoft's Azure growth is
accelerating," "CoreWeave is the leading neocloud play," "BABA faces regulatory headwinds"). Today,
those mentions are written into `.md` research files and pushed to Telegram, then **evaporate**.
Nothing extracts them, stores them, or feeds them into the portfolio evaluation pipeline.

Meanwhile, the rationalization algorithm already runs a battle-tested 5-factor scoring system on all
33 held positions every Saturday, producing a ranked KEEP / TRIM / EXIT report. The algorithm's
scoring functions (`_score_valuation`, `_score_quality`, `_score_growth`, `_score_sentiment`,
`_score_thesis`, and the `_compute_composite` scenario-weighted blend) are pure arithmetic from DB
tables (`price_history`, `fundamental_data`, `financial_statements`, `valuation_data`). Any ticker
with quant data can be scored through the same formulas.

**The core insight:** rather than invent a new quantitative filter to decide which watchlist
candidates are worth full evaluation, we run each candidate through the **same rationalization
scoring formulas** that already govern the KEEP / TRIM / EXIT decision. With a neutral 0.5
placeholder on the Thesis factor (no thesis yet — neither penalized nor credited), we compute each
candidate's composite score, insert it into the 33 holdings' ranking, and shortlist only those that
would crack the top 15. This reuses the rationalization's proven methodology rather than reinventing
a new scoring system.

Further down the pipeline, the `portfolio_candidate_eval` script — which already auto-dispatches
`stock_data_fetcher` (yfinance, free) and `research_tool` (Perplexity + multiple search APIS) and
runs the 3-gate Grok-4.3 evaluation — gains a pull-mode parameter that reads shortlisted candidates
from the watchlist table and evaluates them in batch. This turns passive ticker mentions into active
ADD / WATCH / PASS verdicts with no manual intervention.

## Architecture overview

```
[YouTube scan / News digest]
          │  (every 6h / daily)
          │
    ┌─────▼─────────────────────────────────────────────┐
    │  idea_extractor.py                                 │
    │  - Reads latest .md from /research/youtube/ and    │
    │    /research/news/                                 │
    │  - Calls Deepseek (deepseek-chat, your key) to      │
    │    extract (ticker, reason) pairs from the text    │
    │  - Writes each to watchlist_ideas (status: pending) │
    └────────────────────────────────────────────────────┘
                          │
                      (accumulate all week)
                          │
              Saturday 6:00 AM SGT
                          │
    ┌─────▼─────────────────────────────────────────────┐
    │  portfolio_rationalization.swift                    │
    │  Scores 33 holdings, writes portfolio_scores        │
    │  (now running Saturday AM, not Monday PM)           │
    └────────────────────────────────────────────────────┘
                          │
              Saturday ~6:05 AM SGT (dispatched by rationalization)
                          │
    ┌─────▼─────────────────────────────────────────────┐
    │  candidate_prescreener.py                           │
    │  - Reads pending candidates from watchlist_ideas     │
    │  - Dispatches stock_data_fetcher for each           │
    │    (yfinance + Finnhub, both free)                  │
    │  - Imports factor_scorer.py and runs the same        │
    │    5-factor scoring formulas as rationalization     │
    │    (Thesis factor: neutral 0.5 placeholder)         │
    │  - Inserts candidates into holdings rankings         │
    │  - Rank ≤ 15 → status: shortlisted                  │
    │  - Rank > 15 → status: archived                     │
    │  - Reads portfolio_candidate_evals for PASS verdicts │
    │    within 30 days → auto-archive (already rejected) │
    └────────────────────────────────────────────────────┘
                          │
              Saturday ~6:30 AM SGT (dispatched by prescreener)
                          │
    ┌─────▼─────────────────────────────────────────────┐
    │  portfolio_candidate_eval.py  (pull mode)           │
    │  - watchlist_pull=True                              │
    │  - Reads shortlisted candidates from watchlist_ideas │
    │  - For each: dispatches stock_data_fetcher +         │
    │    research_tool → 3-gate evaluation →               │
    │    ADD / WATCH / PASS verdict                        │
    │  - Writes verdict to portfolio_candidate_evals      │
    │  - Updates watchlist_ideas:                          │
    │    status → evaluated (then watchlist if ADD/WATCH) │
    └────────────────────────────────────────────────────┘
                          │
              Next Saturday: Section D shows the candidates in the report (from Plan 1)
```

## Step 0 — Refactor scoring into a shared module

The currently embedded scoring functions in `portfolio_rationalization.py` —
`_score_valuation`, `_score_quality`, `_score_growth`, `_score_sentiment`, `_score_thesis`,
and the `_compute_composite` / scenario-weighting logic — must be available to both rationalization
AND the new prescreener.

**Before any new code is written:** extract these functions into a new file
`windmill/u/admin/factor_scorer.py`. The extraction is mechanical:
1. Cut the scoring functions and their helper queries from `portfolio_rationalization.py`.
2. Paste into `factor_scorer.py`.
3. Add `from factor_scorer import _score_valuation, _score_quality, ...` to the rationalization
   script at the top, replacing the now-removed local definitions.
4. Push rationalization. Run the full test suite. Confirm all existing tests pass with zero
   behavioral change.

This step must be complete and GREEN before any new Plan 2 code is written.

## New schema — `watchlist_ideas` table

```sql
CREATE TABLE IF NOT EXISTS watchlist_ideas (
    id            SERIAL PRIMARY KEY,
    ticker        TEXT NOT NULL,
    source        TEXT NOT NULL,       -- 'youtube' | 'news' | 'rationalization_exit'
    source_ref    TEXT,                -- the .md filename or eval_date that produced it
    reason        TEXT,                -- one-sentence reason from extraction or prescreen
    added_at      TIMESTAMPTZ DEFAULT NOW(),
    status        TEXT NOT NULL DEFAULT 'pending',
      -- pending → shortlisted → evaluated → watchlist | archived
    eval_date     DATE,                -- when candidate_eval processed it
    prescreen_rank   INTEGER,          -- rank from rationalization-based prescreen
    prescreen_score  NUMERIC(6,4),     -- composite score from factor_scorer
    UNIQUE (ticker, source)
);
```

**Status values and their meaning:**

| Status | Meaning |
|--------|---------|
| `pending` | Just extracted from a scan. Not yet filtered or evaluated. |
| `shortlisted` | Passed the rationalization-based prescreen (ranked ≤15). Ready for full candidate_eval. |
| `evaluated` | candidate_eval has run and produced a verdict (verdict stored in `portfolio_candidate_evals`). |
| `watchlist` | candidate_eval returned WATCH or ADD. Actively monitoring — appears in Section D of the rationalization report. |
| `archived` | Rejected — either failed the prescreen (rank >15), failed candidate_eval (PASS within 30 days), or owner manually archived. |

## New script — `idea_extractor.py`

A new Windmill script that runs after every YouTube monitor and morning news digest run (dispatched
by those scripts — see hooks below). It reads the just-written `.md` file's content and sends it to
Deepseek with a narrow, structured extraction prompt. The Deepseek call is cheap (~2000 tokens input,
~200 tokens output, ~$0.001 per scan. At 4 YouTube scans + 1 news scan per day = ~$0.005/day).

The script must:
1. Accept parameters: `md_path: str`, `source: str` ('youtube' or 'news'), `portfolio_db: dict`,
   `deepseek_key: str`.
2. Read the `.md` file content from `md_path`.
3. Call Deepseek with the approved extraction prompt.
4. Parse the JSON response using a **pure helper** (`_parse_extraction_response(raw: str) -> list[dict] | None`).
5. For each extracted ticker, INSERT into `watchlist_ideas` with `ON CONFLICT (ticker, source) DO NOTHING`
   (deduplication — if MSFT was extracted from a YouTube scan yesterday, it will not be re-added).

**The extraction helper must sanitise tickers —**
strings that are clearly NOT tickers (e.g. "S&P 500", "tech sector", single letters) should be
silently skipped rather than polluting the watchlist.

## New script — `candidate_prescreener.py`

Runs every Saturday after rationalization completes (dispatched by rationalization's post-run hook).

1. **Reads the just-produced `portfolio_scores`** for all 33 holdings — gets their composite scores
   across all 4 scenarios and their ranks.
2. **Reads all `pending` candidates** from `watchlist_ideas WHERE status='pending'`.
3. **Applies automatic exclusions:**
   - Checks `portfolio_candidate_evals` for any PASS verdict within the last 30 days for each
     candidate ticker. Auto-archives those candidates (already rejected by candidate_eval).
   - Checks whether the candidate ticker is already a held position in `portfolio_positions`.
     Auto-archives those (we already own them — they are not "candidates").
4. **For each remaining candidate, dispatches `stock_data_fetcher`** to pull fresh quant data
   (yfinance + Finnhub, both free). Uses the same dispatch + DB-poll pattern as
   `portfolio_candidate_eval.py:1426-1450`. Processes in batches of 5 to stay under yfinance limits.
5. **Scores each candidate** using `factor_scorer`:
   - Valuation score, Quality score, Growth score, Sentiment score — same formulas as rationalization.
   - Thesis score = 0.5 (neutral placeholder — candidate has no thesis yet).
   - Blended through the same 4 scenarios (Balanced, Quality-tilted, Growth-tilted, Value-tilted).
   - Produces 4 composite scores per candidate.
6. **Inserts candidates into the holding rankings:** takes the 33 holdings' composites from
   `portfolio_scores` + all candidate composites → sorts by balanced-weighted composite → produces
   ranks 1–38 or so.
7. **Writes results to `watchlist_ideas`:**
   - Candidates ranking ≤15: `status → 'shortlisted'`, `prescreen_rank`, `prescreen_score` set.
   - Candidates ranking >15: `status → 'archived'`, rejection reason logged (e.g., "would rank #22").
   - Candidates auto-excluded: `status → 'archived'`, rejection reason logged.
8. **Dispatches `portfolio_candidate_eval`** with `watchlist_pull=True` and `ticker=''`
   (or a list of the shortlisted tickers).

## Hooks into existing scan scripts

### `youtube_monitor.py` (ready to hook — has params and dispatch helper)

The YouTube monitor already has `portfolio_db` and `wm_token` params, and already uses the
`_dispatch_formatter` helper at line ~476 to dispatch `youtube_monitor_telegram`. Add ONE line at
line ~475 (after `_write_canonical_md`, before the Telegram formatter dispatch):

```python
_dispatch_formatter("idea_extractor", md_path, telegram_bot_token,
                     telegram_owner_id, portfolio_db, wm_token)
```

The `_dispatch_formatter` helper at `youtube_monitor.py:304-330` constructs the correct Windmill
job-dispatch URL using `WM_BASE_DISPATCH` (line 31). The `idea_extractor` script must accept
`md_path` as a parameter, matching this dispatch signature.

### `morning_news_digest.py` (needs params added)

The morning news digest lacks both `portfolio_db` and `wm_token` params, and has no formatter-dispatch
pattern. The dispatch helper from youtube_monitor must be imported. Add to `main()` signature:
`portfolio_db: dict = {}`, `wm_token: str = ""`. After the `.md` write at ~line 541, add:

```python
if portfolio_db and wm_token:
    _dispatch_formatter("idea_extractor", md_path, telegram_bot_token,
                         telegram_owner_id, portfolio_db, wm_token)
```

The dispatch helper code (from `youtube_monitor.py:304-330`) should be copied into the news digest
script, or extracted to a shared utility. Either approach is acceptable; the plan recommends copying
to avoid a third import refactor.

## `candidate_eval` pull mode

The `portfolio_candidate_eval.py` script gains a new parameter: `watchlist_pull: bool = False`
at line ~1364. When `True`, at the top of `main()` (before the normal single-ticker evaluation
branch), the script:
1. Reads `shortlisted` rows from `watchlist_ideas ORDER BY prescreen_rank ASC`.
2. For each row, runs the existing evaluation loop (dispatch stock_data_fetcher → poll for data →
   dispatch research_tool → poll for research → Grok-4.3 evaluation → INSERT into
   `portfolio_candidate_evals`).
3. After each evaluation, updates the `watchlist_ideas` row: `status → 'evaluated'`; after
   evaluation completes, if verdict is ADD or WATCH, `status → 'watchlist'`.
4. The existing `replacement_ticker` parameter is passed through (unused in pull mode — candidates
   do not have a replacement_ticker unless set explicitly).

## Schedule amendment — rationalization moves from Monday to Saturday

The `portfolio_rationalization.schedule.yaml` on disk currently has `schedule: '0 0 21 * * 1'`
(Monday 9 PM SGT). Change to `schedule: '0 0 6 * * 6'` (Saturday 6 AM SGT). Push the new cron
to the live schedule via curl API (Hard Rule 9 — never sync push):

```bash
WM_TOKEN=$(grep "WM_TOKEN" /root/agent.env | cut -d= -f2 | tr -d ' ')
curl -s -X POST "http://localhost:8080/api/w/admins/schedules/update/u%2Fadmin%2Fportfolio_rationalization" \
  -H "Authorization: Bearer $WM_TOKEN" -H "Content-Type: application/json" \
  -d '{"schedule":"0 0 6 * * 6","timezone":"Asia/Singapore","no_flow_overlap":true,"args":{...same args...}}'
```

The ROADMAP.md must also be updated to reflect Saturday 6 AM SGT.

## Files changed

| Action | Path | Change |
|---|---|---|
| Create | `portfolio/migrations/2026-06-26_watchlist_ideas.sql` | `watchlist_ideas` table DDL |
| Edit | `portfolio/schema.sql` | Append `watchlist_ideas` definition |
| Create | `windmill/u/admin/factor_scorer.py` | Extracted scoring functions from rationalization into shared module |
| Edit | `windmill/u/admin/portfolio_rationalization.py` | Import from factor_scorer; add post-run dispatch of candidate_prescreener; add Saturday 6 AM schedule |
| Create | `windmill/u/admin/idea_extractor.py` | Reads `.md`, Deepseek extraction → `watchlist_ideas` (status: pending) |
| Create | `windmill/u/admin/idea_extractor.script.yaml` | Script metadata |
| Edit | `windmill/u/admin/youtube_monitor.py` | Add one-line dispatch of `idea_extractor` after md write (~line 475) |
| Edit | `windmill/u/admin/morning_news_digest.py` | Add `portfolio_db` and `wm_token` params; add dispatch of `idea_extractor` after md write (~line 541) |
| Create | `windmill/u/admin/candidate_prescreener.py` | Pulls quant data via stock_data_fetcher, scores candidates using factor_scorer, inserts into rankings, shortlists ≤15 |
| Create | `windmill/u/admin/candidate_prescreener.script.yaml` | Script metadata |
| Edit | `windmill/u/admin/portfolio_candidate_eval.py` | Add `watchlist_pull: bool = False` param + iteration branch |
| Edit | `windmill/u/admin/portfolio_rationalization.schedule.yaml` | Change cron from Monday 9 PM → Saturday 6 AM SGT |
| Edit | `agent/tests/test_windmill_scripts.py` | Pure-logic tests: extraction parser, composite score insertion into rankings, prescreener rank computation |
| Create | `docs/logs/2026-06-26_advisor-coherence-a-idea-pipeline.md` | Implementation log |
| Edit | `/root/docs/ROADMAP.md` | Mark Initiative A done; update rationalization schedule from Monday 9 PM → Saturday 6 AM SGT |
| Edit | `docs/WORKFLOW_ARCHITECTURE.md` | Add specs for idea_extractor, candidate_prescreener, factor_scorer |

## Checklist

- [ ] **Step 0 — Refactor scoring into shared module.** Create `windmill/u/admin/factor_scorer.py`.
  Move `_score_valuation`, `_score_quality`, `_score_growth`, `_score_sentiment`, `_score_thesis`,
  `_compute_composite`, `_apply_scenario_weights` from `portfolio_rationalization.py` into the shared
  module. Add `from factor_scorer import ...` to rationalization. Push rationalization. Run full test
  suite — all green (same tests, same behavior). **This must be green before any new code is written.**

- [ ] **Step 1 — Schema: `watchlist_ideas` table.** Apply the migration SQL to the live DB.
  Append the `CREATE TABLE` statement to `portfolio/schema.sql`.

- [ ] **Step 2 — Write `idea_extractor.py`.** Create the script with a pure `_parse_extraction_response`
  helper and I/O edges for reading `.md` files, calling Deepseek, and writing to `watchlist_ideas`.
  Deploy to Windmill.

- [ ] **Step 3 — Hook `idea_extractor` into existing scans.** In `youtube_monitor.py`: add one-line
  dispatch. In `morning_news_digest.py`: add `portfolio_db` and `wm_token` params, add dispatch.
  Deploy both.

- [ ] **Step 4 — Write RED tests.** Add to `test_windmill_scripts.py`: (a) extraction parser valid /
  empty / malformed, (b) prescreener rank insertion (candidate with score 0.85 ranks ≤15; candidate
  with score 0.20 ranks >15). Rebuild agent container. Confirm RED.

- [ ] **Step 5 — Implement `candidate_prescreener.py` to GREEN.** Build the script: dispatches
  `stock_data_fetcher` in batches of 5, scores each candidate via `factor_scorer`, inserts into
  holdings rankings, writes results. Confirm tests pass. Full suite green.

- [ ] **Step 6 — Add `watchlist_pull` to `candidate_eval`.** New param `watchlist_pull`. When set,
  reads `shortlisted` rows from `watchlist_ideas` and iterates them. Deploy.

- [ ] **Step 7 — Wire the dispatch chain.** In `portfolio_rationalization.py`: after the report is
  written and the formatter dispatched, dispatch `candidate_prescreener`. In `candidate_prescreener.py`:
  after scoring, dispatch `candidate_eval` with `watchlist_pull=True`. In `candidate_eval`: the pull
  mode dispatches `stock_data_fetcher` and `research_tool` per candidate (existing dispatch helpers).

- [ ] **Step 8 — Update rationalization schedule.** Edit `portfolio_rationalization.schedule.yaml`:
  cron `'0 0 21 * * 1'` (Monday 9 PM) → `'0 0 6 * * 6'` (Saturday 6 AM). Push to server via curl API.
  Update ROADMAP.md to reflect the new schedule.

- [ ] **Step 9 — Live-verify the full pipeline.** Run each step manually on-demand (no need to wait
  for Saturday): (a) Run YouTube monitor → confirm `idea_extractor` dispatches and `watchlist_ideas`
  has `pending` rows. (b) Run rationalization → confirm `candidate_prescreener` dispatches and
  `shortlisted` candidates appear. (c) Confirm `candidate_eval` evaluates them and `watchlist_ideas`
  rows update. Verify `portfolio_candidate_evals` has new verdicts. Verify `position_signals` has
  no regressions (sentinel should still work).

- [ ] **Step 10 — Docs.** Update ROADMAP (mark Initiative A done, update rationalization schedule to
  Saturday 6 AM), update WORKFLOW_ARCHITECTURE (add specs for the three new scripts + factor_scorer),
  create implementation log. Commit.

## Sign-offs (Hard Rules 6 + 10)

The following must be confirmed before any code is written:

1. **Extraction model:** Deepseek `deepseek-chat` via `$var:u/admin/deepseek_key` — *confirmed.*
2. **Extraction prompt** — the exact prompt text below. Approve as-is or modify before coding:
   ```
   You are reading a research digest. Identify any publicly-traded companies or ETFs mentioned as
   investment ideas, themes, catalysts, or risks. For each, return STRICT JSON with exactly these
   keys and nothing else:
   [
     {"ticker": "SYMBOL", "reason": "<one sentence: why it was mentioned in this digest>"}
   ]
   Rules:
   - ONLY include tickers that are mentioned in the context of an investment idea, theme, catalyst,
     or significant risk.
   - Do NOT include tickers mentioned only in passing (e.g., "the S&P 500 fell" → SPY is NOT an idea).
   - If no tickers qualify, return an empty array: []
   - Use the primary exchange ticker (e.g., "BABA" not "9988.HK").
   ```
   *Approved 2026-06-26 by owner.*
3. **Neutral thesis score:** 0.5 — *confirmed.*
4. **Refactoring approach:** Extract factor_scorer.py as Step 0 — *confirmed.*
5. **Schedule timing:** Saturday 6 AM SGT — *confirmed.*
6. **Pull-mode evaluation runs immediately after prescreener** — *confirmed.*

## Locked Oracle Tests (G1)

> Planner-authored. The assertions below are frozen. Executor reproduces them VERBATIM.

```python
# LOCKED ORACLE — copy verbatim, do not modify assertions

def test_parse_extraction_response_valid():
    """Parses valid JSON with ticker + reason pairs."""
    raw = '[{"ticker":"NVDA","reason":"Dominant AI chip provider"},{"ticker":"CRWV","reason":"Leading neocloud"}]'
    out = parse_extraction_response(raw)
    assert len(out) == 2
    assert out[0]["ticker"] == "NVDA" and out[0]["reason"] == "Dominant AI chip provider"

def test_parse_extraction_response_empty():
    """Empty array returns empty list — no crash, no false data."""
    assert parse_extraction_response("[]") == []

def test_parse_extraction_response_malformed():
    """Garbage input returns None — never write garbage to DB."""
    assert parse_extraction_response("not json") is None

def test_prescreener_rank_insertion():
    """Candidate with composite=0.85 ranks ≤15 in a 33-holding ranking;
    candidate with composite=0.20 ranks >15."""
    from unittest.mock import MagicMock
    # Simulate 33 holding composites (top 10 shown, rest inferred)
    holdings = [0.92, 0.88, 0.75, 0.70, 0.65, 0.60, 0.55, 0.50, 0.45, 0.40]
    # Pad to 33
    holdings.extend([0.35] * 23)
    candidates = {"NVDA": 0.85, "CRWV": 0.20}
    result = compute_candidate_ranks(holdings, candidates)
    assert result["NVDA"]["rank"] <= 15
    assert result["CRWV"]["rank"] > 15
```

## RED-proof requirement (G2)

```
BEFORE implementing factor_scorer extraction (Step 0 baseline):
docker exec root-straitsagent-1 python -m pytest tests/test_windmill_scripts.py \
  -k "rationalization" -q
→ current green (existing rationalization tests still pass)

BEFORE implementing new prescreener + extraction (Step 4 — RED):
docker exec root-straitsagent-1 python -m pytest tests/test_windmill_scripts.py \
  -k "parse_extraction_response or prescreener_rank_insertion" -q
→ FAILS (helpers absent)

AFTER implementation (GREEN):
docker exec root-straitsagent-1 python -m pytest tests/test_windmill_scripts.py \
  -k "parse_extraction_response or prescreener_rank_insertion" -q
→ 4 passed

Full suite:
docker exec root-straitsagent-1 python -m pytest tests/test_windmill_scripts.py -q
→ all green (no regressions)
```

## Asserting Verification Script (G4)

```bash
fail=0

# 1. watchlist_ideas table exists
docker exec root-portfolio_postgres-1 psql -U portfolio_user -d portfolio -tAc \
  "SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name='watchlist_ideas')" \
| { read n; [ "$n" = "t" ] && echo "table_exists=$n" || { echo "FAIL: watchlist_ideas missing"; fail=1; }; }

# 2. factor_scorer module is importable
python3 -c "
import sys; sys.path.insert(0, '/root/windmill/u/admin')
from factor_scorer import _compute_composite
print('PASS factor_scorer_importable')
" || { echo "FAIL: factor_scorer import failed"; fail=1; }

# 3. idea_extractor ran recently (run youtube_monitor first, then check)
docker exec root-portfolio_postgres-1 psql -U portfolio_user -d portfolio -tAc \
  "SELECT count(*) FROM watchlist_ideas WHERE status='pending' AND added_at > NOW() - INTERVAL '2 hours'" \
| { read n; echo "pending_after_scan=$n (>=0 is expected)"; }

# 4. prescreener produces shortlisted rows (run rationalization + prescreener, then check)
docker exec root-portfolio_postgres-1 psql -U portfolio_user -d portfolio -tAc \
  "SELECT count(*) FROM watchlist_ideas WHERE status='shortlisted'" \
| { read n; echo "shortlisted=$n (>=0 is expected)"; }

# 5. rationalization schedule is Saturday AM
grep -q "0 0 6 \* \* 6" windmill/u/admin/portfolio_rationalization.schedule.yaml \
  && echo "PASS schedule_saturday" || { echo "FAIL: schedule not Saturday AM"; fail=1; }

[ "$fail" -eq 0 ] && echo "PASS" || exit 1
```

## Acceptance Gate (G2/G3/G5 + review)

- [ ] Locked tests diff-clean vs. oracle block above (G1)
- [ ] RED + GREEN runs pasted for BOTH refactor baseline + new helpers (G2)
- [ ] Asserting verify script output pasted, ends in `PASS` (G4)
- [ ] `watchlist_ideas` has `pending` rows after YouTube monitor runs (G3)
- [ ] `shortlisted` rows appear after prescreener runs with `prescreen_rank` ≤ 15 (G3)
- [ ] `candidate_eval` pull mode evaluates shortlisted candidates into `portfolio_candidate_evals` (G3)
- [ ] Rationalization schedule verified as Saturday 6 AM SGT on both disk and server (G3)
- [ ] All 6 sign-off items confirmed before coding (Hard Rules 6 + 10)
- [ ] Step 0 (factor_scorer refactor) is GREEN with no behavioral change before any new code is written

## Execution

1. Confirm all 6 sign-off items in §Sign-offs are approved.
2. Set front-matter `Status: executing`, commit.
3. Work the checklist top to bottom. Step 0 must be green before anything else. Step 4 must be RED before Step 5.
4. Run the Asserting Verification Script. Paste the output.
5. Confirm every item in the Acceptance Gate above is satisfied.
6. Set `Status: done`, commit.
Do not redesign. If the plan is ambiguous or wrong, stop and report — do not improvise.
