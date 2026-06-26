# Portfolio Coherence — Design Document

**Date:** 2026-06-26
**Status:** design approved; implementation plans written to `docs/plans/`
**Author:** claude-sonnet-4-6 (planning) + opencode/Deepseek (executor) — collaboration

---

## 1. What "coherence" means

The portfolio system today consists of several independent, well-tested workflows that each do one
thing well. The YouTube monitor watches 37 finance channels and summarises transcripts every 6 hours.
The morning news digest scans RSS feeds and newsletter summaries at 6:30 AM SGT daily. The
candidate evaluator runs a 3-gate ADD / WATCH / PASS verdict for any ticker you ask about. The
rationalization engine scores 33 holdings every week and recommends KEEP / TRIM / EXIT.

But these workflows do not talk to each other. When a YouTube video mentions that CoreWeave is the
leading neocloud play, that insight disappears after the Telegram notification. When you evaluate a
candidate and get an ADD verdict, the rationalization report never mentions it. When rationalization
says EXIT BABA, nothing suggests what to replace it with.

**Coherence means closing these seams.** Making the system reason across both "what should I keep"
and "what should I buy next" without a human bridging each step. The three initiatives this
document describes (A, B, C) are the connective tissue — they extract ideas from scans, pre-filter
them using the rationalization's own scoring methodology, evaluate them through the 3-gate system,
show them in the weekly report, and auto-suggest replacements for positions being trimmed or exited.

---

## 2. The three broken seams (what exists today)

### Seam A — No idea pipeline

Every 6 hours, the YouTube monitor writes a `.md` file to `/research/youtube/` containing Deepseek's
synthesis of 37 channel transcripts. Every morning, the news digest writes to `/research/news/`.
These files contain specific ticker mentions and investment ideas. Today, those mentions are read
once (by the Telegram formatter) and then forgotten. Good ideas evaporate.

### Seam B — No replacement screener

When `portfolio_rationalization` recommends EXIT or TRIM for a position, the `portfolio_scores`
table records the recommendation. But nothing reads that recommendation and asks "replace with
what?" The `replacement_ticker` parameter exists on `portfolio_candidate_evals` (added during the
candidate evaluation framework build), but it is only filled when a human explicitly passes a
replacement ticker to the candidate evaluator. The system never auto-suggests one. Worse, the
current `portfolio_rationalization.py` has no knowledge of the replacement concept at all — the
script does not read `portfolio_candidate_evals`, does not query `peer_comparisons`, and does not
suggest any candidate for an EXIT'd position.

### Seam C — Terminal verdicts

When `portfolio_candidate_eval` produces an ADD or WATCH verdict, it writes a row to
`portfolio_candidate_evals`. That row sits there, unread by any other system. The weekly
rationalization report has no Section D for "here are the candidates you've been evaluating."
The Telegram agent has no `/watchlist` command to surface them. The verdicts are database rows
with no consumer.

---

## 3. The solution — three plans, built in dependency order

The work is broken into three independent plans, each shipping standalone value. Plans 2 and 3
depend on Plan 1 only in the sense that Plan 1's Section D provides a natural home for the output
of Plans 2 and 3. They can be built and verified independently.

### Plan 1: Close the Loop — show monitored candidates in the rationalization report

**What it changes:** The weekly rationalization report gains a new Section D — **Monitored
Candidates**. After the per-position scorecards (Section C), the script queries
`portfolio_candidate_evals` for all ADD and WATCH verdicts from the last 60 days and renders them
as a markdown table with ticker, verdict, evaluation date, and binding constraint. The Telegram
formatter also surfaces this section. If no recent ADD / WATCH rows exist, the section is cleanly
omitted.

**Why it's small:** No new tables, no new scripts, no LLM calls. A new pure helper
(`_render_monitored_candidates`) with two unit tests, a query, and a markdown table renderer.
Maybe 40 lines of code.

**Why it matters:** This is the surface where all downstream work (Plan 2's shortlisted candidates,
Plan 3's replacement suggestions) will appear. Without it, both Plans 2 and 3 produce output that
has no visible place in the report.

### Plan 2: Idea Pipeline + Rationalization-based Prescreener

This is the largest plan — it builds three new scripts, a new database table, a shared scoring
module, and two hooks into existing scan scripts.

#### Part A — Idea extraction from scans

The YouTube monitor and morning news digest each write `.md` files summarising research content.
After each run, a new lightweight script called `idea_extractor.py` reads the just-written `.md`
file and sends it to Deepseek with a narrow, structured prompt:

> *"Identify any publicly-traded companies or ETFs mentioned as investment ideas, themes,
> catalysts, or risks. For each, return JSON with ticker + one-sentence reason."*

Deepseek returns a JSON array of {ticker, reason} pairs. The script writes each to a new
`watchlist_ideas` table with status `pending` and source `youtube` or `news`. The table has a
UNIQUE(ticker, source) constraint — if MSFT was already extracted from a prior YouTube scan, it is
not re-added.

**Why Deepseek:** The extraction prompt is narrow and structured. Deepseek `deepseek-chat` is the
cheapest capable model that can produce strict JSON from unstructured text. At ~$0.001 per scan
(2,000 tokens in, 200 tokens out), the cost across 5 scans per day is roughly $0.005/day.

**Hooks into existing scans:** `youtube_monitor.py` already has the `_dispatch_formatter` helper
and `portfolio_db` + `wm_token` params. One additional dispatch line sends `idea_extractor` as a
Windmill job after the `.md` is written. `morning_news_digest.py` needs `portfolio_db` and
`wm_token` params added (mechanical, 4–5 lines) and the same dispatch line.

#### Part B — Rationalization-based prescreener

The heart of the Plan 2 design. Every Saturday at 6 AM SGT, the rationalization script scores all
33 positions and writes `portfolio_scores`. It then dispatches a new script called
`candidate_prescreener.py` (via the same dispatch pattern as the Telegram formatter).

The prescreener does the following, in sequence:

1. **Reads the just-produced `portfolio_scores`** — gets all 33 holdings' composite scores across
   all 4 weighting scenarios (Balanced, Quality-tilted, Growth-tilted, Value-tilted) and their
   ranks 1–33.

2. **Reads all `pending` watchlist candidates** from `watchlist_ideas`. These have been
   accumulating all week from YouTube and news scans.

3. **Applies automatic exclusions** before wasting fetcher calls:
   - Checks `portfolio_candidate_evals` for any PASS verdict on the same ticker within 30 days.
     If found, the candidate is auto-archived (you already rejected it).
   - Checks whether the ticker is already a held position in `portfolio_positions`. If so, it is
     auto-archived (you already own it — it is not a "candidate").

4. **Dispatches `stock_data_fetcher`** for each remaining candidate. This pulls fresh quant data
   from yfinance and Finnhub (both free). The fetcher populates `company_profiles`,
   `financial_statements`, `valuation_data`, `financial_health_metrics`, and other quant tables.
   Because yfinance has no hard rate limit, candidates are processed in batches of 5 to stay
   under informal throttling. The prescreener polls the DB until each candidate's data lands
   (same polling pattern as `portfolio_candidate_eval.py:1426-1450`).

5. **Scores each candidate** using a shared `factor_scorer.py` module — the same scoring functions
   that `portfolio_rationalization.py` uses. This is the key architectural decision: **the
   prescreener does not invent a new scoring system.** It reuses the same 5-factor scoring
   (Valuation, Quality, Growth, Sentiment, Thesis) that already governs the KEEP / TRIM / EXIT
   decision. The only difference is the Thesis factor — a watchlist candidate has no thesis yet, so
   it gets a neutral placeholder of 0.5 (where High=1.0, Medium=0.6, Low=0.2, absent=0.0). This
   means the candidate is neither penalised nor credited on the thesis factor.

6. **Inserts candidates into the holding rankings.** Takes the 33 holdings' composite scores +
   all candidate composite scores, sorts by balanced-weighted composite, and produces ranks 1–N
   (where N = 33 + number of candidates). Candidates that rank ≤15 are `shortlisted` — they
   would survive the rationalization's own top-15 KEEP logic. Candidates that rank >15 are
   `archived` with the rejection reason logged (e.g., "would rank #22").

7. **Writes results** to `watchlist_ideas` (status, prescreen_rank, prescreen_score).

8. **Dispatches `portfolio_candidate_eval`** with `watchlist_pull=True` — this triggers Part C.

**Why the rationalization scoring:** The rationalization algorithm is the most proven
decision-making logic in the stack. It scores 33 holdings every week and has been calibrated
through multiple review sessions. If a candidate would not crack the top 15 when run through the
same formulas that determine KEEP / TRIM / EXIT, it is not worth the expensive Grok-4.3
evaluation. This reuses existing logic rather than reinventing a new quantitative filter.

**Why the prescreener uses `stock_data_fetcher` (free):** yfinance and Finnhub are free for our
volume. The `stock_data_fetcher` already populates all the quant tables. Calling it for each
candidate costs nothing in API fees — only compute time (~10 seconds per candidate, batched
in groups of 5 = ~2 minutes for 20 candidates). There is no reason to limit the candidate pool
when the data collection is free.

**Why the Thesis factor gets 0.5:** Rationalization's Thesis factor maps conviction to a score
(High=1.0, Medium=0.6, Low=0.2, absent=0.0). A watchlist candidate has no thesis yet — scoring
0 would unfairly penalise it against held positions that have Grok-4.3-drafted theses (from the
thesis seeder). Scoring the full 10% of the composite at 0.5 is neutral — it does not boost the
candidate, but it does not drag it either.

#### Part C — Candidate evaluation pull mode

`portfolio_candidate_eval.py` gains a new parameter: `watchlist_pull: bool = False`. When set to
`True`, the script reads `shortlisted` rows from `watchlist_ideas ORDER BY prescreen_rank ASC` and
iterates them through the existing 3-gate evaluation loop. This is the same evaluation that runs
when you type `/candidate NVDA` via Telegram — the script auto-dispatches `stock_data_fetcher` (for
fresh quant data) and `research_tool` (for Perplexity + multiple search APIs + Grok-4.3 synthesis),
runs the 3-gate ADD / WATCH / PASS check, and writes the verdict to `portfolio_candidate_evals`.

The pull mode reuses all existing dispatch helpers, the polling pattern, the gate logic, and the
Grok-4.3 evaluation prompt. The only new code is the iteration loop at the top of `main()` that
reads `watchlist_ideas` rows instead of taking a single `ticker` argument.

After evaluation, each `watchlist_ideas` row is updated: `status → 'evaluated'`, `eval_date → today`.
If the verdict is ADD or WATCH, `status → 'watchlist'` (meaning it will appear in Plan 1's
Section D in the next Saturday's rationalization report).

#### Part D — Rationalization schedule amendment

The rationalization schedule moves from **Monday 9 PM SGT to Saturday 6 AM SGT.** This is set by
the owner, who wants the portfolio review on Saturday morning. All three plan components follow
this lead:

| Saturday SGT | What runs | Trigger |
|---|---|---|
| 6:00 AM | `portfolio_rationalization` | Windmill cron |
| 6:05 AM | `candidate_prescreener` | Dispatched by rationalization's post-run hook |
| 6:05 AM | `replacement_screener` | Dispatched by rationalization's post-run hook (parallel with prescreener) |
| 6:30 AM | `portfolio_candidate_eval` (pull mode) | Dispatched by prescreener's post-run hook |

The schedule `.yaml` file and the live server schedule are both updated. The ROADMAP is also
updated to reflect Saturday 6 AM.

#### Part E — The `factor_scorer` refactor (Step 0)

Before any Plan 2 code is built, the scoring functions currently embedded in
`portfolio_rationalization.py` must be extracted into a shared module `factor_scorer.py`. These
functions are:
- `_score_valuation` — P/E, P/B, EV/EBITDA percentile vs. own history
- `_score_quality` — ROE, margins, debt ratios, earnings consistency
- `_score_growth` — revenue growth, earnings growth, estimate revisions
- `_score_sentiment` — analyst ratings, price momentum, short interest
- `_score_thesis` — conviction from `portfolio_thesis`
- `_compute_composite` — blends the 5 factors through 4 weighting scenarios
- `_apply_scenario_weights` — the scenario-weighting logic

The extraction is mechanical: cut from rationalization, paste into `factor_scorer.py`, add
`from factor_scorer import ...` to rationalization. No behavioral change. The full test suite
must pass identically before and after this refactor. This is enforced by running the suite
before the extraction (baseline) and after (verification) — any difference is a regression.

Both `candidate_prescreener.py` and `portfolio_rationalization.py` import from `factor_scorer.py`
after the refactor.

### Plan 3: Replacement Screener

This is the thinnest plan in the stack — about 100 lines of Python. No LLM calls, no new tables,
no new scoring. It depends on Plan 2 only for the `watchlist_ideas` table (output of the
prescreener) and the `factor_scorer` module (for reading prescreener output structure, not for
calling any scoring functions).

#### What it does

After the prescreener runs and shortlists candidates, the replacement screener bridges EXIT / TRIM
signals with the shortlisted candidate pool:

1. **Reads `portfolio_scores`** for `recommendation IN ('EXIT', 'TRIM')`.
2. **Reads `watchlist_ideas`** for all `shortlisted` candidates (already ranked by prescreen).
3. **Selects the top-3 shortlisted candidates** for each EXIT / TRIM ticker, using a pure helper
   `_select_top_replacements(exit_tickers, shortlisted, held_tickers, top_n=3)`. The selection is
   sector-agnostic — any sector qualifies. The owner's design principle is that diversification
   should emerge naturally from the scoring, not from an explicit sector-bonus formula.
4. **Excludes held positions** from replacement candidates. An already-held position is not a
   "replacement" — it is already owned. Instead, held positions that rank strongly are surfaced
   as **overweight candidates** in a separate list.
5. **Writes the selections** to `watchlist_ideas` with `source='rationalization_exit'` and a
   `reason` field noting which EXIT position each replacement is for. This provides traceability
   — you can see which replacement suggestions came from which exit signal.
6. **Renders Section E — Replacement Candidates** in the rationalization report. This section
   shows two tables: replacement candidates for each EXIT / TRIM position (ticker, prescreen
   rank, score, rationale) and overweight candidates (held positions that are strong candidates
   for absorbing freed capital).
7. **The Telegram formatter** surfaces Section E in the Telegram message, making the replacement
   candidates visible in the Saturday morning Telegram push alongside Section D's monitored
   candidates.

#### Why sector-agnostic

The owner explicitly chose this. A sector bonus (e.g., "+10% score for different-sector
candidates") would be re-inventing a scoring formula outside the rationalization framework.
Instead, the rationalization's own scoring, which already factors in valuation, quality, growth,
and sentiment, determines which candidates rank highly. If a Technology candidate scores well
on quality and growth metrics, it will rank well regardless of whether the EXIT'd position is
Technology or Financials. The system trusts its own scoring rather than layering on heuristic
adjustments.

#### Overweight suggestions

When a held position ranks in the top 15 and is in a different sector than the EXIT'd position,
the screener notes it as an overweight candidate. This is not a replacement — you already own it.
But it is a sensible destination for the capital freed by the EXIT. The report says something like:

> *"Consider increasing AMZN weight by the capital freed from BABA (AMZN ranked #4 in this
> week's rationalization, different sector)."*

This gives you a quick read on which holdings are strong enough to absorb freed capital, without
the system ever making a trade recommendation — it is a capital-allocation *suggestion*, not an
order.

---

## 4. The `watchlist_ideas` table — the shared idea store

All three coherence plans converge on a single new database table. This is the central data
structure — it is where extracted ideas land, where prescreened candidates are shortlisted,
where replacement suggestions are tagged, and where the evaluation pipeline reads from.

```sql
CREATE TABLE IF NOT EXISTS watchlist_ideas (
    id              SERIAL PRIMARY KEY,
    ticker          TEXT NOT NULL,
    source          TEXT NOT NULL,         -- 'youtube' | 'news' | 'rationalization_exit'
    source_ref      TEXT,                  -- the .md filename or eval_date
    reason          TEXT,                  -- one-sentence reason from extraction or prescreen
    added_at        TIMESTAMPTZ DEFAULT NOW(),
    status          TEXT NOT NULL DEFAULT 'pending',
    eval_date       DATE,                  -- when candidate_eval processed it
    prescreen_rank  INTEGER,               -- rank from rationalization-based prescreen
    prescreen_score NUMERIC(6,4),          -- composite score from factor_scorer
    UNIQUE (ticker, source)
);
```

**Status lifecycle:**

```
                  ┌─ idea_extractor ─┐
                  │  (YouTube scan)   │
                  │  source: youtube  │
                  └───────┬───────────┘
                          │
                    status: pending
                          │
              ┌───────────▼───────────┐
              │ candidate_prescreener  │
              │                       │
              │ Scores via factor_scorer │
              │ Inserts into holdings  │
              │ ranking (top-15 check) │
              └───────┬───────────────┘
                      │
            ┌─────────┴─────────┐
            │                   │
       rank ≤ 15           rank > 15
            │                   │
    status: shortlisted    status: archived
            │              (rejection logged)
            │
    ┌───────▼──────────────────────┐
    │ portfolio_candidate_eval     │
    │ (pull mode)                  │
    │                              │
    │ 3-gate ADD / WATCH / PASS    │
    └───────┬──────────────────────┘
            │
    ┌───────┴───────┐
    │               │
   ADD/WATCH       PASS
    │               │
 status:        status:
 watchlist      archived
    │
    │  (appears in Plan 1's Section D
    │   on next Saturday's report)
```

---

## 5. The Saturday SGT dispatch chain (complete picture after all 3 plans)

```
Saturday 6:00 AM SGT — Windmill cron fires
    │
    ├── portfolio_rationalization.swift
    │   - Scores 33 holdings via factor_scorer
    │   - Produces KEEP / TRIM / EXIT (recommendation column)
    │   - Renders Section D: Monitored Candidates (Plan 1)
    │   - Writes portfolio_scores
    │   - Writes canonical .md to /research/portfolio/
    │   - Dispatches portfolio_rationalization_telegram
    │
    ├── Dispatches candidate_prescreener (Plan 2)
    │   - Reads pending watchlist_ideas
    │   - Auto-excludes: PASS within 30 days (rejected); already held
    │   - Dispatches stock_data_fetcher for each candidate (batch of 5)
    │   - Scores via factor_scorer (same formulas as rationalization)
    │   - Inserts into holdings ranking → shortlisted if ≤15
    │   - Dispatches portfolio_candidate_eval with watchlist_pull=True
    │
    ├── Dispatches replacement_screener (Plan 3, parallel with prescreener)
    │   - Reads EXIT / TRIM from portfolio_scores
    │   - Reads shortlisted candidates from watchlist_ideas
    │   - Selects top-3 replacements per EXIT/TRIM (sector-agnostic)
    │   - Identifies overweight candidates (held, top-15, different sector)
    │   - Appends Section E to the rationalization .md
    │   - Writes source='rationalization_exit' rows to watchlist_ideas
    │
    └── portfolio_candidate_eval (pull mode, ~6:30 AM)
        - Reads shortlisted candidates from watchlist_ideas
        - For each: dispatches stock_data_fetcher + research_tool
        - 3-gate ADD / WATCH / PASS via Grok-4.3
        - Writes verdict to portfolio_candidate_evals
        - Updates watchlist_ideas

Result: By roughly 7:00 AM SGT, the Saturday rationalization email + Telegram message contain:
  - Section C: Per-position scorecards (existing)
  - Section D: Monitored Candidates — tickers you've evaluated that got ADD / WATCH (Plan 1)
  - Section E: Replacement Candidates — top-3 for each EXIT / TRIM + overweight suggestions
    (Plan 3)

And `watchlist_ideas` is populated with shortlisted candidates whose full Grok-4.3 evaluations
are in `portfolio_candidate_evals`, ready for Section D inclusion in next week's report.
```

---

## 6. Why this design, not alternatives

### Why use the rationalization scoring for the prescreener instead of a standalone quantitative filter

The rationalization algorithm is the most proven decision logic in the stack. It scores 33
holdings every week and has been calibrated through months of review. A standalone quantitative
filter (e.g., "P/E > 0, ROE > 10%, D/E < 3") would be:
- **Arbitrary** — the thresholds would be tuned by intuition, not by the same methodology that
  governs the KEEP / TRIM / EXIT decision
- **Disconnected** — a candidate that passes a standalone filter might still rank poorly when run
  through the full 5-factor scoring that actual rationalization uses
- **Duplicative** — maintaining two scoring systems means two sets of bugs, two calibration
  passes, and inconsistent results

By reusing rationalization's scoring functions via the shared `factor_scorer` module, the
prescreener asks: *"Would this candidate survive rationalization's top-15 cut?"* The answer
is the same answer the rationalization algorithm itself would give.

### Why sector-agnostic screening for replacements

The owner explicitly chose this. A sector bonus (e.g., "+10% for different-sector") would be
a heuristic adjustment layered on top of the scoring formulas — defeating the purpose of reusing
rationalization's methodology. If the scoring system produces a diversified shortlist (which it
does — the top candidates naturally span multiple sectors because they are scored on financial
merit, not sector membership), no bonus is needed. If it produces a concentrated shortlist, the
owner can manually prioritise diversification — that is a human judgment, not an algorithm's
place to decide.

### Why `stock_data_fetcher` calls for the prescreener instead of limited DB queries

yfinance and Finnhub are free for our volume. The `stock_data_fetcher` populates 13 quant tables
from a single call. Quering only `peer_comparisons` or `company_profiles` (as earlier drafts
suggested) would miss financial statements, valuation metrics, and health ratios — all of which
the `factor_scorer` needs to compute its 5-factor scores. The full fetcher call is the same API
cost (zero) as a limited query, and it provides complete data for the ranking. There is no reason
to limit the fetcher.

### Why the prescreener runs weekly, not continuously

Extraction from scans runs daily (every scan). The prescreener runs weekly (Saturday AM). This is
because the prescreener's ranking output is only meaningful in the context of the rationalization's
current rankings — which are produced weekly, not daily. Running the prescreener daily against
stale rationalization scores (from last Saturday) would compare candidates against an outdated
baseline. Saturday's rationalization run produces a fresh baseline; the prescreener runs
immediately after.

---

## 7. Implementation order and dependencies

| Order | Plan | Depends on | Can parallelise? |
|---|---|---|---|
| 1 | Plan 1 (Close the Loop) | Nothing | Yes — standalone |
| 2 | Plan 2 (Idea Pipeline + Prescreener) | Nothing (factor_scorer refactor is internal to Plan 2) | No — Plan 3 needs its output |
| 3 | Plan 3 (Replacement Screener) | Plan 2's `watchlist_ideas` table + `factor_scorer` module | No — needs Plan 2's output |

**Recommended execution:** Plan 1 first (quickest, produces immediate value, no schema change,
unblocks the display surface for Plans 2 and 3). Plan 2 second (largest, establishes the
`watchlist_ideas` infrastructure and `factor_scorer` shared module). Plan 3 third (thin,
mechanical, reads Plan 2's output).

All three plans use the existing planning convention: `docs/plans/YYYY-MM-DD_*.md`, with
front-matter, EXECUTOR_CONTRACT compliance (locked oracle tests, RED→GREEN, asserting
verification scripts, acceptance gate), and Hard Rule sign-off items where applicable.

---

## 8. Cost estimate

| Workflow | LLM Calls | Cost Per Run | Runs Per Week | Weekly Cost |
|---|---|---|---|---|
| `idea_extractor` (YouTube) | Deepseek extraction (~$0.001) | $0.001 × 4 = $0.004/day | 28 | ~$0.03 |
| `idea_extractor` (News) | Deepseek extraction (~$0.001) | $0.001 | 7 | ~$0.01 |
| `candidate_prescreener` | None (pure math + SQL) | $0.00 | 1 | $0.00 |
| `portfolio_candidate_eval` (pull mode) | Grok-4.3 evaluation (~$0.02-0.05 per candidate) | $0.05 × 3–10 candidates | 1 | ~$0.15–0.50 |
| **Total weekly** | | | | **~$0.20–0.55** |

At the high end (~10 shortlisted candidates), the weekly Grok-4.3 evaluation cost is about $0.50.
At the low end (3–5 candidates), it is about $0.15. The extraction cost (~$0.04/week) is negligible.

---

## 9. Files in play

### New files created by these plans

| File | Plan | Purpose |
|---|---|---|
| `portfolio/migrations/2026-06-26_watchlist_ideas.sql` | 2 | `watchlist_ideas` table DDL |
| `windmill/u/admin/factor_scorer.py` | 2 | Shared scoring functions extracted from rationalization |
| `windmill/u/admin/idea_extractor.py` | 2 | Ticker extraction from scan `.md` files via Deepseek |
| `windmill/u/admin/candidate_prescreener.py` | 2 | Rationalization-based candidate ranking |
| `windmill/u/admin/replacement_screener.py` | 3 | Top-3 replacement selection + Section E renderer |
| `docs/design/2026-06-26_portfolio-coherence-seams-design.md` | — | This document |

### Existing files modified by these plans

| File | Plan | Change |
|---|---|---|
| `portfolio/schema.sql` | 2 | Append `watchlist_ideas` definition |
| `windmill/u/admin/portfolio_rationalization.py` | 1, 2, 3 | Section D renderer (Plan 1), import from factor_scorer + dispatch prescreener + dispatch replacement screener (Plan 2, 3) |
| `windmill/u/admin/portfolio_rationalization_telegram.py` | 1, 3 | Surface Section D and Section E in Telegram message |
| `windmill/u/admin/portfolio_rationalization.schedule.yaml` | 2 | Monday 9 PM → Saturday 6 AM SGT |
| `windmill/u/admin/youtube_monitor.py` | 2 | One-line dispatch of `idea_extractor` |
| `windmill/u/admin/morning_news_digest.py` | 2 | Add params + dispatch of `idea_extractor` |
| `windmill/u/admin/portfolio_candidate_eval.py` | 2 | Add `watchlist_pull` param + iteration branch |
| `agent/tests/test_windmill_scripts.py` | 1, 2, 3 | Pure-logic tests for all new helpers |
| `docs/ROADMAP.md` | 1, 2, 3 | Mark initiatives done; update rationalization schedule |
| `docs/WORKFLOW_ARCHITECTURE.md` | 2, 3 | Add specs for new scripts |
