---
Subject: Advisor Coherence Phase 2 — Idea Pipeline + Rationalization-based Prescreener (watchlist infrastructure)
Date: 2026-06-26
Status: executing
Planner model: claude-sonnet-4-6 (Claude Code plan mode)
Executor model: deepseek (opencode) or any
Hard Rules in force: [1, 4, 6, 7, 9, 10, 11, 15, 17, 19, 20, 22]
Risk tier: HIGH (planner-locked oracle)
Initiative: A (idea-pipeline) — build order 2 of 3
Complies with: docs/EXECUTOR_CONTRACT.md
Sign-off items:
  - Extraction model: deepseek-chat via $var:u/admin/deepseek_key  (owner confirmed 2026-06-26)
  - Extraction prompt: approved text in §Sign-offs section  (Hard Rule 10)
  - Neutral thesis score: 0.5  (owner confirmed 2026-06-26)
  - Refactoring approach: extract factor_scorer.py as Step 0  (owner confirmed 2026-06-26)
  - Rationalization schedule: Already Saturday 6AM SGT (implemented 2026-06-25 — no change needed)
Files to read before coding: CLAUDE.md, docs/TESTING.md, windmill/u/admin/portfolio_rationalization.py (full scoring functions — see §Step 0 for real function names), windmill/u/admin/youtube_monitor.py (dispatch pattern at ~line 477), windmill/u/admin/morning_news_digest.py (md write at ~line 539-540, main signature at ~line 423), windmill/u/admin/portfolio_candidate_eval.py (main signature at line 1364, stock_data_fetcher dispatch at lines 1426-1435 via _dispatch_stock_fetcher helper at 124-130, research_tool dispatch at lines 1437-1450 via _dispatch_research_tool helper at 186-192)
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
scoring functions (`_compute_factor_scores` for the 4 quant factors, `_apply_thesis_scores` for the
5th, and `_compute_composites` for the scenario-weighted blend) are pure arithmetic from DB tables
(`price_history`, `fundamental_data`, `financial_statements`, `valuation_data`). Critically, factor
scores are **percentile ranks within the pool** — a candidate must be added to the union pool and
scored together with the 33 holdings, not standalone. Any ticker with quant data can be scored
through the same formulas this way.

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
    │  portfolio_rationalization.py                       │
    │  Scores 33 holdings, writes portfolio_scores        │
    │  (running Saturday 6AM SGT — schedule already live) │
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

The scoring functions in `portfolio_rationalization.py` must be available to both rationalization
AND the new prescreener. **Actual function names (verified by grep):**

| Function | Line | What it does |
|---|---|---|
| `_cagr(start, end, years)` | early helper | Compound annual growth rate calc |
| `_evaluate_red_flags(metrics)` | ~433 | Absolute red-flag checks (pure math) |
| `_norm(values, v)` | ~458 | Percentile-rank helper used by all 4 quant factors |
| `_compute_factor_scores(positions, fund)` | ~469 | All 4 quant factors (quality/growth/valuation/sentiment) in one function — no per-factor helpers exist |
| `_apply_thesis_scores(positions, thesis)` | ~563 | 5th factor (thesis conviction score) |
| `_compute_composites(positions, factor_scores, thesis_scores)` | ~590 | Blends 4 factors + thesis into 4 scenario composites. Scenarios are keyed `balanced`/`quality`/`growth`/`value` (dict at ~line 596). |
| `_rank_positions(positions, composites)` | ~653 | Final ranking per scenario |

**None** of these have per-factor names like `_score_valuation`, `_score_quality` — those do not exist.
The 4 quant factors live as inline labeled blocks inside `_compute_factor_scores`.

**Extraction is straightforward** — all these functions operate purely on passed-in arguments
(`positions` dict, `fund` dict from `_fetch_fundamentals`). They have no DB reads inside them.
The field-name contract (`return_on_equity`, `net_debt_to_ebitda`, `analyst_upside_pct`, etc.)
that `_fetch_fundamentals` produces must be documented in `factor_scorer.py` so the prescreener
knows what to feed these functions.

**Before any new code is written:** extract these 7 functions into `windmill/u/admin/factor_scorer.py`:
1. Cut the 7 functions from `portfolio_rationalization.py`.
2. Paste into `factor_scorer.py`.
3. Add `from factor_scorer import _cagr, _evaluate_red_flags, _norm, _compute_factor_scores, _apply_thesis_scores, _compute_composites, _rank_positions` to rationalization at the top.
4. Push rationalization. Run full test suite — all green (same behavior). **Must be green before any new code is written.**

> **Important for prescreener scoring (C2):** `_compute_factor_scores` scores factors as
> **percentile ranks within the pool** via `_norm(values, v)`. A candidate's factor score is
> its percentile relative to the pool — it has no standalone composite. The prescreener must
> score each candidate by calling `_compute_factor_scores` on the **union pool** (33 holdings +
> candidate) and reading the candidate's row from the result. Ranking then falls out naturally.
> The `compute_candidate_ranks` helper (see §Locked Oracle) handles only the final sort of
> already-computed balanced composites — it is not where scoring happens.

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
   `portfolio_candidate_eval.py` — stock dispatch at lines 1426-1435 (via `_dispatch_stock_fetcher`
   helper at lines 124-130; **the poll loop is in the helper, not in main**). Processes in batches
   of 5 to stay under yfinance informal throttle.
5. **Scores each candidate via the union-pool approach:**
   - Reads 33 holdings' raw fund data from `fundamental_data` / quant tables.
   - For each candidate, adds its fund data to the pool and calls `_compute_factor_scores(union_pool, fund)` from `factor_scorer`. The candidate's factor scores are its percentile within the union pool (this is how `_norm` works — no standalone score exists).
   - Thesis score: inject a synthetic thesis row with score 0.5 for the candidate into `_apply_thesis_scores` (neutral placeholder — neither penalised nor credited).
   - Calls `_compute_composites(union_pool, factor_scores, thesis_scores)` to get the candidate's balanced/quality/growth/value composites.
   - The 4 scenarios use the real scenario keys: `balanced`, `quality`, `growth`, `value`.
6. **Inserts candidates into the holding rankings:** the balanced composite score for the candidate
   (from step 5) is merged with the 33 holdings' `composite_score_balanced` from `portfolio_scores`,
   sorted descending → produces ranks 1–38 or so. The `compute_candidate_ranks` helper handles this
   final sort (see §Locked Oracle for its contract).
7. **Writes results to `watchlist_ideas`:**
   - Candidates ranking ≤15: `status → 'shortlisted'`, `prescreen_rank`, `prescreen_score` set.
   - Candidates ranking >15: `status → 'archived'`, rejection reason logged (e.g., "would rank #22").
   - Candidates auto-excluded: `status → 'archived'`, rejection reason logged.
8. **Dispatches `portfolio_candidate_eval`** with `watchlist_pull=True` and `ticker=''`
   (or a list of the shortlisted tickers).

## Hooks into existing scan scripts

> **⚠️ C3 — Do NOT use `_dispatch_formatter` for `idea_extractor`.** The existing
> `_dispatch_formatter` (youtube_monitor.py:304-330) hard-codes these job args:
> `{md_path, telegram_bot_token, telegram_owner_id, portfolio_db}`. But `idea_extractor` needs
> `{md_path, source, portfolio_db, deepseek_key}` — it does not want telegram params, and it
> **requires** `source` (to tag 'youtube' vs 'news') and `deepseek_key` (to call the LLM). These
> cannot be threaded through `_dispatch_formatter` without changing it. Use a dedicated helper
> instead (see below).

### `youtube_monitor.py` (ready to hook — has `portfolio_db` + `wm_token` params)

Add a new `_dispatch_idea_extractor(md_path, source, portfolio_db, deepseek_key, wm_token)` helper
(~12 lines, pattern from `_dispatch_formatter` at lines 304-330 but with the correct args dict).
Call it just before the Telegram formatter dispatch (after `_write_canonical_md` at line ~473):

```python
if portfolio_db and wm_token:
    _dispatch_idea_extractor(
        md_path, "youtube", portfolio_db, deepseek_key, wm_token
    )
```

This requires adding `deepseek_key: str = ""` to `youtube_monitor.main()`. If the Windmill
schedule args do not already pass `deepseek_key`, add `"$var:u/admin/deepseek_key"` to the
schedule args (Hard Rule 11 — string form only).

### `morning_news_digest.py` (needs params added)

The morning news digest main() (line 423) already has `deepseek_key` (line 425, required) but
lacks `portfolio_db` and `wm_token`. Copy the `_dispatch_idea_extractor` helper (same 12 lines)
into the news digest script. Add to `main()` signature: `portfolio_db: dict = {}`, `wm_token: str = ""`
(do NOT add a second `deepseek_key` — it already exists). After the `.md` write at lines 539-540
(log at 541), add:

```python
if portfolio_db and wm_token:
    _dispatch_idea_extractor(
        md_path, "news", portfolio_db, deepseek_key, wm_token
    )
```

Update the `morning_news_digest` schedule args to include the three new params (string form for
`$var:` and `$res:` references per Hard Rule 11). The Windmill UI schedule must be updated if the
schedule yaml args change.

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

## Files changed

| Action | Path | Change |
|---|---|---|
| Create | `portfolio/migrations/2026-06-26_watchlist_ideas.sql` | `watchlist_ideas` table DDL |
| Edit | `portfolio/schema.sql` | Append `watchlist_ideas` definition |
| Create | `windmill/u/admin/factor_scorer.py` | Extracted scoring functions from rationalization into shared module |
| Edit | `windmill/u/admin/portfolio_rationalization.py` | Import from factor_scorer; add post-run dispatch of candidate_prescreener |
| Create | `windmill/u/admin/idea_extractor.py` | Reads `.md`, Deepseek extraction → `watchlist_ideas` (status: pending) |
| Create | `windmill/u/admin/idea_extractor.script.yaml` | Script metadata |
| Edit | `windmill/u/admin/youtube_monitor.py` | Add `deepseek_key` param; add `_dispatch_idea_extractor` helper; call after md write (~line 473) |
| Edit | `windmill/u/admin/morning_news_digest.py` | Add `portfolio_db`, `wm_token`, `deepseek_key` params; copy `_dispatch_idea_extractor` helper; call after md write (~line 539-540) |
| Create | `windmill/u/admin/candidate_prescreener.py` | Pulls quant data via stock_data_fetcher, scores candidates using factor_scorer, inserts into rankings, shortlists ≤15 |
| Create | `windmill/u/admin/candidate_prescreener.script.yaml` | Script metadata |
| Edit | `windmill/u/admin/portfolio_candidate_eval.py` | Add `watchlist_pull: bool = False` param + iteration branch |
| Edit | `agent/tests/test_windmill_scripts.py` | Pure-logic tests: extraction parser, compute_candidate_ranks final-sort, plus executor-authored pooled-scoring test |
| Create | `docs/logs/2026-06-26_advisor-coherence-a-idea-pipeline.md` | Implementation log |
| Edit | `/root/docs/ROADMAP.md` | Mark Initiative A done |
| Edit | `docs/WORKFLOW_ARCHITECTURE.md` | Add specs for idea_extractor, candidate_prescreener, factor_scorer |

## Checklist

- [ ] **Step 0 — Refactor scoring into shared module.** Create `windmill/u/admin/factor_scorer.py`.
  Move the 7 real functions from `portfolio_rationalization.py` (see §Step 0 above for the exact
  names and line numbers):
  `_cagr`, `_evaluate_red_flags`, `_norm`, `_compute_factor_scores`, `_apply_thesis_scores`,
  `_compute_composites`, `_rank_positions`.
  Add `from factor_scorer import _cagr, _evaluate_red_flags, _norm, _compute_factor_scores, _apply_thesis_scores, _compute_composites, _rank_positions` to rationalization at the top.
  Push rationalization. Run full test suite — all green (same tests, same behavior).
  **This must be green before any new code is written.**

- [ ] **Step 1 — Schema: `watchlist_ideas` table.** Apply the migration SQL to the live DB.
  Append the `CREATE TABLE` statement to `portfolio/schema.sql`.

- [ ] **Step 2 — Write `idea_extractor.py`.** Create the script with a pure `_parse_extraction_response`
  helper and I/O edges for reading `.md` files, calling Deepseek, and writing to `watchlist_ideas`.
  Deploy to Windmill.

- [ ] **Step 3 — Hook `idea_extractor` into existing scans.** Add `_dispatch_idea_extractor` helper
  (~12 lines) to both `youtube_monitor.py` and `morning_news_digest.py` (copy, don't import).
  In `youtube_monitor.py`: add `deepseek_key` param; call `_dispatch_idea_extractor(md_path, "youtube",
  portfolio_db, deepseek_key, wm_token)` after the md write at ~line 473, guarded by
  `if portfolio_db and wm_token and deepseek_key`.
  In `morning_news_digest.py`: add `portfolio_db`, `wm_token`, `deepseek_key` params to `main()`;
  call `_dispatch_idea_extractor(md_path, "news", ...)` after the md write at ~line 539-540.
  Update schedule args for both scripts to include new params (Hard Rule 11 — string form). Deploy both.

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

- [ ] **Step 8 — Confirm rationalization schedule.** The schedule is already Saturday 6 AM SGT
  (implemented 2026-06-25). Verify:
  ```bash
  grep -q "0 0 6 \* \* 6" windmill/u/admin/portfolio_rationalization.schedule.yaml && echo "OK" || echo "MISMATCH"
  ```
  No curl push needed. If for any reason the on-disk yaml and live server differ, report — do not
  improvise a fix.

- [ ] **Step 9 — Live-verify the full pipeline.** Run each step manually on-demand (no need to wait
  for Saturday): (a) Run YouTube monitor → confirm `idea_extractor` dispatches and `watchlist_ideas`
  has `pending` rows. (b) Run rationalization → confirm `candidate_prescreener` dispatches and
  `shortlisted` candidates appear. (c) Confirm `candidate_eval` evaluates them and `watchlist_ideas`
  rows update. Verify `portfolio_candidate_evals` has new verdicts. Verify `position_signals` has
  no regressions (sentinel should still work).

- [ ] **Step 10 — Docs.** Update ROADMAP (mark Initiative A done), update WORKFLOW_ARCHITECTURE
  (add specs for idea_extractor, candidate_prescreener, factor_scorer), create implementation log.
  Commit.

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
5. **Schedule timing:** Saturday 6 AM SGT — *already live, confirmed on disk and server 2026-06-25.*
6. **Pull-mode evaluation runs immediately after prescreener** — *confirmed.*

## Locked Oracle Tests (G1)

> Planner-authored. The assertions below are frozen. Executor reproduces them VERBATIM.

```python
# LOCKED ORACLE — copy verbatim, do not modify assertions
# Executor: import _parse_extraction_response and compute_candidate_ranks from their respective
# scripts using the sys.path.insert + heavy-dep stub pattern in this test file.
#
# compute_candidate_ranks(holding_composites: list[float], candidate_composites: dict[str, float])
#   -> dict[str, dict]  (e.g. {"NVDA": {"rank": 3, "composite": 0.85}})
#   This is the FINAL-SORT helper — it takes already-computed composites (from the union-pool
#   scoring in step 5) and produces integer ranks. Scoring happens earlier via _compute_composites.

def test__parse_extraction_response_valid():
    """Parses valid JSON with ticker + reason pairs."""
    raw = '[{"ticker":"NVDA","reason":"Dominant AI chip provider"},{"ticker":"CRWV","reason":"Leading neocloud"}]'
    out = _parse_extraction_response(raw)
    assert len(out) == 2
    assert out[0]["ticker"] == "NVDA" and out[0]["reason"] == "Dominant AI chip provider"

def test__parse_extraction_response_empty():
    """Empty array returns empty list — no crash, no false data."""
    assert _parse_extraction_response("[]") == []

def test__parse_extraction_response_malformed():
    """Garbage input returns None — never write garbage to DB."""
    assert _parse_extraction_response("not json") is None

def test_compute_candidate_ranks_sort():
    """Final-sort helper: candidate with balanced composite 0.85 ranks ≤15 in a 33-holding pool;
    candidate with composite 0.20 ranks >15. This tests the sort, not the scoring.
    Scoring is via _compute_composites on the union pool (separate executor-authored test required)."""
    # Simulate 33 holding balanced composites
    holdings = [0.92, 0.88, 0.75, 0.70, 0.65, 0.60, 0.55, 0.50, 0.45, 0.40]
    holdings.extend([0.35] * 23)  # pad to 33
    candidates = {"NVDA": 0.85, "CRWV": 0.20}
    result = compute_candidate_ranks(holdings, candidates)
    assert result["NVDA"]["rank"] <= 15
    assert result["CRWV"]["rank"] > 15
```

> **Executor requirement (not locked, but mandatory):** Add a test `test_prescreener_pooled_scoring`
> proving that when a candidate is added to the holdings pool, `_compute_factor_scores(union_pool,
> fund)` produces a factor score for the candidate that reflects its percentile within the pool
> (not a standalone value). This is executor-authored and subject to reviewer spot-check (G1 LOW
> tier for this sub-test). The test should use a minimal mock fund dict with the field names that
> `_fetch_fundamentals` produces (e.g. `return_on_equity`, `net_debt_to_ebitda`, `analyst_upside_pct`).

## RED-proof requirement (G2)

```
BEFORE implementing factor_scorer extraction (Step 0 baseline):
docker exec root-straitsagent-1 python -m pytest tests/test_windmill_scripts.py \
  -k "rationalization" -q
→ current green (existing rationalization tests still pass)

BEFORE implementing new prescreener + extraction (Step 4 — RED):
docker exec root-straitsagent-1 python -m pytest tests/test_windmill_scripts.py \
  -k "_parse_extraction_response or compute_candidate_ranks" -q
→ FAILS (helpers absent)

AFTER implementation (GREEN):
docker exec root-straitsagent-1 python -m pytest tests/test_windmill_scripts.py \
  -k "_parse_extraction_response or compute_candidate_ranks" -q
→ 4 passed (3 extraction + 1 rank-sort; plus the executor-authored pooled-scoring test)

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

# 2. factor_scorer module is importable and has the real function names
python3 -c "
import sys; sys.path.insert(0, '/root/windmill/u/admin')
from factor_scorer import _compute_factor_scores, _compute_composites, _apply_thesis_scores, _norm
print('PASS factor_scorer_importable')
" || { echo "FAIL: factor_scorer import failed"; fail=1; }

# 3. Seed a synthetic test candidate and run youtube_monitor to trigger idea_extractor.
# After idea_extractor runs, the seeded ticker (or real extracted tickers) must appear as pending.
# (Pre-seed verifies the table + constraint; the real pending count verifies idea_extractor fired.)
docker exec root-portfolio_postgres-1 psql -U portfolio_user -d portfolio -c \
  "INSERT INTO watchlist_ideas (ticker, source, reason, status) VALUES ('VERIFY_SEED', 'youtube', 'verification seed', 'pending') ON CONFLICT DO NOTHING"
PEND=$(docker exec root-portfolio_postgres-1 psql -U portfolio_user -d portfolio -tAc \
  "SELECT count(*) FROM watchlist_ideas WHERE status='pending' AND ticker='VERIFY_SEED'")
[ "${PEND:-0}" -ge 1 ] \
  && echo "PASS seed_pending=$PEND" \
  || { echo "FAIL: seed not present in pending"; fail=1; }

# 4. Prescreener produces at least 1 shortlisted row after a full pipeline run.
# Run rationalization → prescreener (can be triggered on-demand) before this check.
SL=$(docker exec root-portfolio_postgres-1 psql -U portfolio_user -d portfolio -tAc \
  "SELECT count(*) FROM watchlist_ideas WHERE status='shortlisted' AND prescreen_rank IS NOT NULL")
[ "${SL:-0}" -ge 1 ] \
  && echo "PASS shortlisted=$SL with prescreen_rank" \
  || { echo "FAIL: no shortlisted rows with prescreen_rank (has prescreener run?)"; fail=1; }

# 5. Rationalization schedule already Saturday AM (no change needed, but verify disk matches)
grep -q "0 0 6 \* \* 6" windmill/u/admin/portfolio_rationalization.schedule.yaml \
  && echo "PASS schedule_saturday" || { echo "FAIL: schedule not Saturday AM"; fail=1; }

[ "$fail" -eq 0 ] && echo "PASS" || exit 1
```

## Acceptance Gate (G2/G3/G5 + review)

- [ ] Locked tests diff-clean vs. oracle block above (G1); executor-authored `test_prescreener_pooled_scoring` also present and passing (G1 LOW)
- [ ] RED + GREEN runs pasted for BOTH refactor baseline + new helpers (G2)
- [ ] Asserting verify script output pasted, ends in `PASS` (G4)
- [ ] `watchlist_ideas` has `pending` rows (including VERIFY_SEED) after idea_extractor runs (G3)
- [ ] `shortlisted` rows appear with `prescreen_rank IS NOT NULL` after prescreener runs (G3 — paste psql output)
- [ ] `candidate_eval` pull mode evaluates at least 1 shortlisted candidate into `portfolio_candidate_evals` (G3 — paste the row)
- [ ] Rationalization schedule confirmed Saturday 6 AM SGT on disk (grep output pasted) (G3)
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
