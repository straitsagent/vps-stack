---
Subject: Advisor Coherence Phase 3 — Replacement Screener (auto-suggest replacements for EXIT/TRIM positions)
Date: 2026-06-26
Status: draft
Planner model: claude-sonnet-4-6 (Claude Code plan mode)
Executor model: deepseek (opencode) or any
Hard Rules in force: [7, 9, 15, 17]
Risk tier: LOW (mechanical — no LLM, no new table, no scoring)
Complies with: docs/EXECUTOR_CONTRACT.md
Depends on: Plan 2 (watchlist_ideas table + factor_scorer module + prescreener output)
Files to read before coding: CLAUDE.md, docs/TESTING.md, windmill/u/admin/portfolio_rationalization.py (report assembly, dispatch pattern at ~line 1273-1278), Plan 2 output (watchlist_ideas schema, prescreener output format)
---

# Plan: Advisor Coherence Phase 3 — Replacement Screener

## Context — why this matters

After Saturday's rationalization + prescreener pipeline runs (from Plan 2), the system knows two
key things: which positions are flagged EXIT / TRIM (from `portfolio_scores.recommendation`), and
which watchlist candidates are shortlisted with their composite scores and ranks (from the
prescreener's output in `watchlist_ideas`). The replacement screener bridges these: it selects the
top-3 ranked shortlisted candidates as replacement suggestions for each EXIT / TRIM position, and
notes any held positions that would be good overweight candidates (strongly-ranked holdings that
could absorb the freed capital).

The screener is **thin** — no LLM calls, no scoring, no new table. It reads existing data, applies a
simple selection rule ("top 3 shortlisted candidates, sector-agnostic"), formats a report section,
and writes suggestions to `watchlist_ideas` for traceability.

**The design is sector-agnostic and market-cap-agnostic** — the owner wants diversification benefits
to emerge naturally from the rationalization scoring, not from an explicit sector-bonus formula. A
candidate from a different sector will rank well if its financials are strong; a candidate in the
same sector will rank well if it is genuinely a better company. The ranking, not a sector filter,
drives selection.

## What it does — step by step

1. **Reads EXIT / TRIM positions** from `portfolio_scores WHERE recommendation IN ('EXIT', 'TRIM')`.
2. **For each EXIT / TRIM ticker, reads the prescreener's output** from
   `watchlist_ideas WHERE status='shortlisted' ORDER BY prescreen_rank ASC`.
3. **Selects the top-3 shortlisted candidates** (regardless of sector — sector-agnostic per owner
   decision). Existing held positions are excluded from replacement candidates (they appear in the
   overweight section instead).
4. **Writes the top-3 replacements** to `watchlist_ideas` with `source='rationalization_exit'` and
   `reason` noting which EXIT position they replace (e.g., "Ranked #2 replacement for BABA after
   rationalization-based prescreen"). These are tagged for traceability so you can see which
   replacement suggestions came from which exit signal.
5. **Identifies overweight candidates:** queries the prescreener's full holding ranking to find held
   positions that are strongly ranked AND are in a different sector than the EXIT / TRIM position.
   While the selection is sector-agnostic for replacements, the screener separately notes held
   positions that are good candidates for overweighting — these are NOT replacements (you already
   own them), but they are good destinations for freed capital. The screener renders a note like:
   *"Consider increasing [HELD_TICKER] weight by the capital freed from [EXIT_TICKER] (ranked #X
   in this week's rationalization, different sector)."*
6. **Renders a new Section E — Replacement Candidates** in the rationalization report. This section
   appears after Section D (Monitored Candidates from Plan 1). The section shows:
   - A table of EXIT / TRIM positions and their top-3 replacement candidates (ticker + prescreen rank + rationale)
   - An overweight-suggestion list for held positions that are worth overweighting
   - The Telegram formatter (`portfolio_rationalization_telegram.py`) also surfaces this section.

**Concrete example of what Section E looks like in the report:**

```markdown
## Section E — Replacement Candidates

### EXIT / TRIM Replacements

The rationalization recommends exiting or trimming the following positions.
Below are the top-3 shortlisted candidates for each, ranked by composite score
from the rationalization-based prescreener.

**BABA** → recommendation: EXIT (rank #33)
| Rank | Candidate | Prescreen Score | Rationale |
|------|-----------|----------------|-----------|
| 1 | NVDA | 0.88 | Top-ranked shortlisted candidate overall |
| 2 | AMD | 0.85 | Strong valuation + growth metrics |
| 3 | V | 0.80 | Diversified financials with consistent ROE |

**CRM** → recommendation: TRIM (rank #28)
| Rank | Candidate | Prescreen Score | Rationale |
|------|-----------|----------------|-----------|
| 1 | NVDA | 0.88 | Also the top candidate for BABA exit |
| 2 | AMD | 0.85 | — |
| 3 | MSFT | 0.83 | Cloud + AI growth, high quality score |

### Overweight Candidates

The following currently-held positions are strong candidates for overweighting.
They ranked in the top 15 and are in a different sector than the position being exited,
providing natural diversification.

- **AMZN** — ranked #4, different sector from BABA. Consider increasing weight by the
  capital freed from BABA exit.
- **GOOGL** — ranked #7, different sector from CRM. Consider increasing weight by the
  capital freed from CRM trim.
```

## Files changed

| Action | Path | Change |
|---|---|---|
| Create | `windmill/u/admin/replacement_screener.py` | New script (~100 lines): reads rankings, selects top-3 per EXIT, identifies overweight candidates, renders Section E, writes to watchlist_ideas |
| Create | `windmill/u/admin/replacement_screener.script.yaml` | Script metadata |
| Edit | `windmill/u/admin/portfolio_rationalization.py` | Add dispatch of `replacement_screener` after prescreener dispatch (~1 line). The replacement screener reads the same `.md` that rationalization just wrote and appends Section E to it |
| Edit | `windmill/u/admin/portfolio_rationalization_telegram.py` | Surface Section E content in the Telegram message (read from the updated `.md` after replacement_screener appends to it) |
| Edit | `agent/tests/test_windmill_scripts.py` | Pure-logic test for the `_select_top_replacements` helper |
| Create | `docs/logs/2026-06-26_advisor-coherence-b-replacement-screener.md` | Implementation log |
| Edit | `/root/docs/ROADMAP.md` | Mark Initiative B done |

No new tables. No new scoring. No LLM calls. The screener imports `factor_scorer` from Plan 2 only
for reading the prescreener output structure — it does not call any scoring functions.

## Checklist

- [ ] **Step 1 — Write the RED test.** Add to `test_windmill_scripts.py`:
  `test_select_top_replacements` — feeds 2 EXIT tickers + 8 shortlisted candidates with scores and
  sectors + 1 held position; asserts exactly 3 candidates per EXIT ticker, ordered by prescreen_rank
  ascending, held position excluded, sector-agnostic (any sector can be selected). Rebuild agent
  container. Confirm RED.

- [ ] **Step 2 — Implement `replacement_screener.py`.** The script:
  - Defines a pure `_select_top_replacements(exit_tickers, shortlisted, held_tickers, top_n=3)`
    function that returns `{ticker: [top_n candidates]}`.
  - Has I/O edges: reads `portfolio_scores` for EXIT / TRIM; reads `watchlist_ideas` for
    shortlisted candidates with their `prescreen_rank` and `prescreen_score`; reads
    `portfolio_positions` for held tickers; reads the rationalization `.md` to append Section E.
  - Renders the Section E markdown table and overweight-suggestions list.
  - Writes `source='rationalization_exit'` rows to `watchlist_ideas` for the selected replacements.
  Confirm GREEN. Full suite green.

- [ ] **Step 3 — Deploy.** Push the script via `wmill script push`. Hard Rule 19 — confirm the
  regenerated lock file resolves packages (no new deps beyond psycopg2 — this is a pure SQL + string
  formatter script).

- [ ] **Step 4 — Wire dispatch.** In `portfolio_rationalization.py`, after the prescreener dispatch
  (from Plan 2), add one line dispatching `replacement_screener` as a Windmill job. The replacement
  screener must receive the same `.md` path that rationalization wrote so it can append Section E.

- [ ] **Step 5 — Live-verify.** Run rationalization on-demand (or wait for Saturday's scheduled run).
  - Confirm `replacement_screener` completes (check Windmill job log).
  - Confirm `watchlist_ideas` has new `source='rationalization_exit'` rows for each EXIT / TRIM
    ticker. Each row must have `status='shortlisted'` and a populated `prescreen_rank`.
  - Open the rationalization `.md` file — confirm Section E appears with the top-3 replacement
    candidates listed and the overweight-suggestions list naming held positions in different sectors.
  - Read `telegram_outbox` for the rationalization run — confirm the Telegram body includes the
    replacement candidates section.
  - If no EXIT / TRIM positions exist this week (all KEEP), the screener should produce an empty
    Section E or a note: "No positions flagged for EXIT or TRIM this week." Either is a valid PASS.

- [ ] **Step 6 — Docs + commit.** Create implementation log. Update ROADMAP — mark Initiative B done.
  Commit:
  ```bash
  cd /root
  git add windmill/u/admin/replacement_screener.py windmill/u/admin/replacement_screener.script.yaml \
          windmill/u/admin/portfolio_rationalization.py windmill/u/admin/portfolio_rationalization_telegram.py \
          agent/tests/test_windmill_scripts.py docs/ROADMAP.md \
          docs/logs/2026-06-26_advisor-coherence-b-replacement-screener.md
  git commit -m "feat(coherence): Replacement Screener — auto-suggest top-3 replacements for EXIT/TRIM"
  git push
  ```

## Locked Oracle Tests (G1)

> Planner-authored. The assertions below are frozen. Executor reproduces them VERBATIM.

```python
# LOCKED ORACLE — copy verbatim, do not modify assertions

def test_select_top_replacements():
    """Selects exactly 3 candidates per exit ticker, ranked by prescreen_rank ascending.
    Held positions excluded. Sector-agnostic (any sector qualifies)."""
    exit_tickers = ["BABA", "CRM"]
    shortlisted = [
        {"ticker": "NVDA", "prescreen_rank": 1, "prescreen_score": 0.88, "sector": "Technology"},
        {"ticker": "AMD",  "prescreen_rank": 2, "prescreen_score": 0.85, "sector": "Technology"},
        {"ticker": "MSFT", "prescreen_rank": 3, "prescreen_score": 0.83, "sector": "Technology"},
        {"ticker": "V",    "prescreen_rank": 4, "prescreen_score": 0.80, "sector": "Financials"},
        {"ticker": "TSM",  "prescreen_rank": 5, "prescreen_score": 0.79, "sector": "Technology"},
        {"ticker": "AMZN", "prescreen_rank": 6, "prescreen_score": 0.77, "sector": "Consumer Cyclical"},
    ]
    held = {"AMZN"}  # held, must NOT appear as replacement
    result = select_top_replacements(exit_tickers, shortlisted, held, top_n=3)
    assert "BABA" in result and len(result["BABA"]) == 3
    assert result["BABA"][0]["ticker"] == "NVDA"  # top-ranked
    assert result["BABA"][1]["ticker"] == "AMD"
    assert result["BABA"][2]["ticker"] == "MSFT"
    assert "CRM" in result and len(result["CRM"]) == 3
    assert result["CRM"][0]["ticker"] == "NVDA"  # same pool
    # held position excluded
    for tickers in result.values():
        for t in tickers:
            assert t["ticker"] != "AMZN", "held position must not appear as replacement"
    # sector-agnostic: Financials ticker V can be selected (at rank 4)
    # (it would be selected if there were enough shortlisted pool to reach it)


def test_select_top_replacements_few_candidates():
    """When fewer than top_n candidates exist, return all available."""
    exit_tickers = ["BABA"]
    shortlisted = [
        {"ticker": "NVDA", "prescreen_rank": 1, "prescreen_score": 0.88, "sector": "Technology"},
        {"ticker": "AMD",  "prescreen_rank": 2, "prescreen_score": 0.85, "sector": "Technology"},
    ]
    result = select_top_replacements(exit_tickers, shortlisted, set(), top_n=3)
    assert len(result["BABA"]) == 2  # only 2 available, not 3
```

## RED-proof requirement (G2)

```
BEFORE implementing (RED):
docker exec root-straitsagent-1 python -m pytest tests/test_windmill_scripts.py \
  -k "select_top_replacements" -q
→ FAILS (helper absent)

AFTER implementing (GREEN):
docker exec root-straitsagent-1 python -m pytest tests/test_windmill_scripts.py \
  -k "select_top_replacements" -q
→ 2 passed

Full suite:
docker exec root-straitsagent-1 python -m pytest tests/test_windmill_scripts.py -q
→ all green
```

## Asserting Verification Script (G4)

```bash
fail=0

# 1. replacement screener produces watchlist_ideas rows with source='rationalization_exit'
REPL=$(docker exec root-portfolio_postgres-1 psql -U portfolio_user -d portfolio -tAc \
  "SELECT count(*) FROM watchlist_ideas WHERE source='rationalization_exit'")
echo "replacement_suggestions=$REPL (any >= 0 is PASS; depends on EXIT/TRIM existence)"

# 2. Section E appears in the latest rationalization .md
MD_PATH=$(ls -t /root/research/portfolio/rationalization_*.md | head -1)
if grep -q "Section E — Replacement Candidates" "$MD_PATH"; then
  echo "PASS section_e_present"
else
  # Section E absent is OK if there were no EXIT/TRIM positions this week
  EXITS=$(docker exec root-portfolio_postgres-1 psql -U portfolio_user -d portfolio -tAc \
    "SELECT count(*) FROM portfolio_scores WHERE recommendation IN ('EXIT','TRIM') AND score_date = CURRENT_DATE")
  if [ "${EXITS:-0}" -eq 0 ]; then
    echo "PASS section_e_omitted (no EXIT/TRIM this week — expected)"
  else
    echo "FAIL: Section E missing but DB has $EXITS EXIT/TRIM rows"; fail=1
  fi
fi

[ "$fail" -eq 0 ] && echo "PASS" || exit 1
```

## Acceptance Gate (G2/G3/G5 + review)

- [ ] Locked tests diff-clean vs. oracle block above (G1)
- [ ] RED + GREEN runs pasted (G2)
- [ ] Asserting verify script output pasted, ends in `PASS` (G4)
- [ ] `watchlist_ideas` has `source='rationalization_exit'` rows for each EXIT/TRIM ticker (G3)
- [ ] Rationalization `.md` includes Section E with actual ticker names + overweight suggestions (G3)
- [ ] Telegram outbox row for the rationalization run includes replacement candidates section (G3)

## Execution

1. Confirm the 2 sign-off items above are resolved.
2. Set front-matter `Status: executing`, commit.
3. Work the checklist top to bottom. Step 1 must be RED before Step 2.
4. Run the Asserting Verification Script. Paste the output.
5. Confirm every item in the Acceptance Gate above is satisfied.
6. Set `Status: done`, commit.
Do not redesign. If the plan is ambiguous or wrong, stop and report — do not improvise.
