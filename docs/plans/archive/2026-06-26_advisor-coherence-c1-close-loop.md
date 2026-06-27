---
Subject: Advisor Coherence Phase 1 — Close the Loop (show candidate eval verdicts in rationalization report)
Date: 2026-06-26
Status: done
Planner model: claude-sonnet-4-6 (Claude Code plan mode)
Executor model: deepseek (opencode) or any
Hard Rules in force: [7, 9, 15, 17]
Risk tier: HIGH (planner-locked oracle — simple assertions, but oracle is planner-authored per contract)
Initiative: C (close-the-loop) — build order 1 of 3
Complies with: docs/EXECUTOR_CONTRACT.md
Files to read before coding: CLAUDE.md, docs/TESTING.md, windmill/u/admin/portfolio_rationalization.py (lines 1193-1278, 1240-1252), windmill/u/admin/portfolio_rationalization_telegram.py, portfolio/schema.sql (portfolio_candidate_evals table)
---

# Plan: Advisor Coherence Phase 1 — Close the Loop

## Context — why this matters

The portfolio system has two independent decision engines that do not talk to each other:

- **`portfolio_candidate_eval`** produces ADD / WATCH / PASS verdicts. When you evaluate a ticker via
  Telegram (`/candidate NVDA`), the result goes into `portfolio_candidate_evals` and sits there —
  **terminal**. Nothing reads it. Not the rationalization report, not the Telegram agent's overview
  tools, not the dashboard.
- **`portfolio_rationalization`** scores held positions and recommends KEEP / TRIM / EXIT. But it has
  no knowledge that you previously evaluated NVDA and got an ADD verdict. The two systems are
  completely disconnected.

This plan connects them. After rationalization scores its KEEP / TRIM / EXIT recommendations, it
reads recent ADD / WATCH verdicts from the candidate evaluation table and renders a new
**Section D — Monitored Candidates** in the weekly report. When you read your Saturday
rationalization email, you see your active watchlist candidates right below the KEEP / TRIM / EXIT
table — no need to switch contexts or remember what you evaluated three weeks ago.

## What it does

Adds a new section to the rationalization report. After the per-position scorecards (Section C),
before the report footer, a new query reads `portfolio_candidate_evals` for all
`verdict IN ('ADD', 'WATCH')` rows with `eval_date` within the last 60 days. It renders them as a
markdown table listing ticker, verdict, evaluation date, and binding constraint (the one-sentence
flag from the candidate evaluator).

If no recent ADD / WATCH rows exist, the section is cleanly omitted. This means the rationalization
report gets a new section only when there is meaningful data to show.

The Telegram formatter (`portfolio_rationalization_telegram.py`) also gains this section so the
Telegram version of the report includes the monitored candidates. The formatter reads the
front-matter of the canonical `.md` file and surfaces the `monitored_candidates` key.

**Concrete example of what Section D looks like in the report:**

```markdown
## Section D — Monitored Candidates

These are tickers you have evaluated via candidate eval in the last 60 days
that received an ADD or WATCH verdict. They are not yet held.

| Ticker | Verdict | Evaluated | Reason |
|--------|---------|-----------|--------|
| NVDA   | ADD     | 2026-06-24 | None — exceeded all gates |
| CRWV   | WATCH   | 2026-06-22 | High debt-to-equity ratio |
| RDDT   | WATCH   | 2026-06-20 | Limited operating history |
```

## Files changed

| Action | Path | Change |
|--------|------|--------|
| Edit | `windmill/u/admin/portfolio_rationalization.py` | Add `_render_monitored_candidates(cur, since_days=60)` pure helper; insert Section D after the per-position scorecards block (~line 1216, before the `---` footer); add `monitored_candidates` key to front-matter dict (~line 1240) |
| Edit | `windmill/u/admin/portfolio_rationalization_telegram.py` | Read the new front-matter key and surface monitored candidates in the Telegram message |
| Edit | `agent/tests/test_windmill_scripts.py` | Add 2 pure-logic tests for the Section D renderer |
| Edit | `/root/docs/ROADMAP.md` | Mark Initiative C done |
| Create | `/root/docs/logs/2026-06-26_advisor-coherence-c1-close-loop.md` | Implementation log |

No new tables. No new scripts. No LLM calls. No schedule changes.

## Checklist

- [ ] **Step 1 — Confirm insertion points.** Read `portfolio_rationalization.py` to confirm: (a) the
  scorecards block ends at what line, (b) the front-matter dict is at what line, (c) where `report_md`
  is assembled. These line numbers may have shifted since the plan was written; use actual grep output,
  not the plan's line references.

- [ ] **Step 2 — Write the RED tests.** Add to `agent/tests/test_windmill_scripts.py`:
  - `test_render_monitored_candidates_renders_table` — feeds fake rows with ticker, verdict, eval_date,
    binding_constraint; asserts ticker + verdict + date appear in rendered markdown
  - `test_render_monitored_candidates_empty` — feeds an empty list; asserts empty string returned
    (section omitted cleanly)
  - Rebuild the agent container, run the tests, confirm RED (helper absent).

- [ ] **Step 3 — Implement the helpers.** Add TWO functions to the rationalization script:

  **`_query_monitored_candidates(cur, since_days=60) -> list[dict]`** — query helper:
  ```sql
  SELECT DISTINCT ON (ticker) ticker, verdict, eval_date, binding_constraint
  FROM portfolio_candidate_evals
  WHERE verdict IN ('ADD', 'WATCH')
    AND eval_date >= CURRENT_DATE - INTERVAL '60 days'
  ORDER BY ticker, eval_date DESC
  ```
  Returns a list of dicts (one per ticker, latest verdict only — `DISTINCT ON (ticker)` prevents a
  ticker evaluated twice in 60 days from appearing twice).

  **`_render_monitored_candidates(rows: list[dict]) -> str`** — pure renderer, no DB:
  Takes the list of dicts from the query helper. Renders as a markdown table with the exact format
  shown above. Returns empty string `""` if rows is empty.
  Confirm GREEN — run the tests from Step 2 inside the agent container. Run full test suite — no
  regressions.

- [ ] **Step 4 — Wire into the report assembly.** In `portfolio_rationalization.py`, after the
  per-position scorecards block and before the `---` footer / report assembly:
  ```python
  monitored_rows = _query_monitored_candidates(cur)
  monitored = _render_monitored_candidates(monitored_rows)
  if monitored:
      report_md += f"\n\n{monitored}"
  ```
  Add `"monitored_candidates": monitored` to the front-matter dict so the Telegram formatter can see it.
  The formatter (`portfolio_rationalization_telegram.py`) already reads front-matter keys and builds its
  message — add one more field to surface this table in the Telegram output.

- [ ] **Step 5 — Deploy.** Push both scripts via `wmill script push` (Hard Rule 9 — never sync push):
  ```bash
  cd /root/windmill && wmill script push u/admin/portfolio_rationalization.py && wmill script push u/admin/portfolio_rationalization_telegram.py
  ```

- [ ] **Step 6 — Live-verify (Hard Rule 17 — read the actual artifact, not success:True).**
  Trigger rationalization on-demand via Telegram or the Windmill UI:
  - Read the resulting `.md` file from `/research/portfolio/rationalization_YYYY-MM-DD.md` — confirm
    Section D appears and lists real ADD / WATCH verdicts from your `portfolio_candidate_evals` table.
  - Read `telegram_outbox` for the rationalization run — confirm the Telegram message body includes
    the monitored candidates table.
  - If Section D is absent and `portfolio_candidate_evals` has ADD / WATCH rows within 60 days, STOP
    and report (the renderer is not working).
  - If Section D is absent and `portfolio_candidate_evals` has NO ADD / WATCH rows within 60 days, this
    is expected — the section is cleanly omitted. This is still a PASS.

- [ ] **Step 7 — Docs + commit.** Create implementation log at
  `docs/logs/2026-06-26_advisor-coherence-c1-close-loop.md`. Update ROADMAP.md: mark Initiative C done.
  Commit:
  ```bash
  cd /root
  git add windmill/u/admin/portfolio_rationalization.py windmill/u/admin/portfolio_rationalization_telegram.py \
          agent/tests/test_windmill_scripts.py docs/ROADMAP.md \
          docs/logs/2026-06-26_advisor-coherence-c1-close-loop.md
  git commit -m "feat(coherence): Close the Loop — show monitored candidates in rationalization report"
  git push
  ```

## Locked Oracle Tests (G1)

> Planner-authored. The assertions below are frozen. Executor reproduces them VERBATIM — do not weaken
> or alter any assertion to make a test pass. Fix the implementation code, not the test.
>
> **Executor note:** `_render_monitored_candidates(rows)` is the **pure renderer** — no DB cursor,
> no side-effects. `_query_monitored_candidates(cur)` is the separate query helper. Import the pure
> renderer into the test using the same `sys.path.insert` + heavy-dep stub pattern already used by
> other windmill-script tests in this file.

```python
# LOCKED ORACLE — copy verbatim, do not modify assertions

def test_render_monitored_candidates_renders_table():
    # _render_monitored_candidates(rows) is the pure renderer; import it from portfolio_rationalization.
    rows = [
        {"ticker": "NVDA", "verdict": "ADD", "eval_date": "2026-06-24", "binding_constraint": None},
        {"ticker": "CRWV", "verdict": "WATCH", "eval_date": "2026-06-22", "binding_constraint": "High D/E ratio"},
    ]
    out = _render_monitored_candidates(rows)
    assert out != "", "non-empty input must produce non-empty output"
    assert "NVDA" in out and "ADD" in out and "2026-06-24" in out
    assert "CRWV" in out and "WATCH" in out and "High D/E ratio" in out
    assert "Monitored Candidates" in out


def test_render_monitored_candidates_empty():
    assert _render_monitored_candidates([]) == ""
```

## RED-proof requirement (G2)

```
BEFORE implementing (RED):
docker exec root-straitsagent-1 python -m pytest tests/test_windmill_scripts.py \
  -k "render_monitored_candidates" -q
→ FAILS (no module/function yet)

AFTER implementing (GREEN):
docker exec root-straitsagent-1 python -m pytest tests/test_windmill_scripts.py \
  -k "render_monitored_candidates" -q
→ 2 passed
```

## Asserting Verification Script (G4)

```bash
# Read the latest rationalization .md, confirm Section D appears (if any monitored candidates exist)
MD_PATH=$(ls -t /root/research/portfolio/rationalization_*.md | head -1)
ODD=$(docker exec root-portfolio_postgres-1 psql -U portfolio_user -d portfolio -tAc \
  "SELECT count(*) FROM portfolio_candidate_evals WHERE verdict IN ('ADD','WATCH') AND eval_date >= CURRENT_DATE - INTERVAL '60 days'")
if [ "$ODD" -gt 0 ]; then
  grep -q "Monitored Candidates" "$MD_PATH" && echo "PASS section_d_with_candidates" || { echo "FAIL: Section D missing but DB has $ODD candidates"; exit 1; }
else
  echo "PASS section_d_omitted (0 recent candidates)"
fi
```

## Acceptance Gate (G2/G3/G5 + review)

- [ ] Locked tests diff-clean vs. the oracle block above (G1)
- [ ] RED + GREEN runs pasted (G2)
- [ ] Asserting verify script pasted, ends in `PASS` (G4)
- [ ] Section D in the live `.md` file names real ADD / WATCH tickers (G3)
- [ ] Telegram outbox row for the rationalization run includes monitored candidates (G3)

## Execution

1. Set front-matter `Status: executing`, commit.
2. Work the checklist top to bottom; Step 2 must be RED before Step 3.
3. Run the Asserting Verification Script. Paste the output.
4. Confirm every item in the Acceptance Gate above is satisfied.
5. Set `Status: done`, commit.
Do not redesign. If the plan is ambiguous or wrong, stop and report — do not improvise.
