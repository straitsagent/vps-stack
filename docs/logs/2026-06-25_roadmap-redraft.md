# ROADMAP Redraft — Implementation Log

**Date:** 2026-06-25
**Scope:** Full structural rewrite of `docs/ROADMAP.md`. Previous version organized around a
W1→W6 agent-sophistication march that drifted from both the live system state and the owner's intent.
New version reframes around a coherent portfolio advisor goal.

---

## Motivation

After ~73 commits of debugging and hardening, the roadmap had three problems:

1. **Wrong organizing metaphor.** W1→W6 framed the roadmap as an agent-sophistication ladder. But the
   agent is one component, not the through-line. The real goal is a portfolio advisor that reasons
   across both remove and add decisions.

2. **Reality drift.** `macro_research` (live, 7AM Mon–Fri) was undocumented. `macro_daily_push` was
   documented as live but its schedule was disabled. At least 5 Windmill schedules had cron/path drift
   vs disk `.yaml`. Empty tables (`portfolio_thesis`, `earnings_surprises`) were not flagged.

3. **Dead-end architecture undocumented.** The three broken seams — no idea pipeline from scans, no
   replacement screener, terminal `portfolio_candidate_evals` — were not documented anywhere.
   A human was silently bridging all three, but there was no written record of this or a plan to fix it.

---

## Audit Findings Applied

Three parallel audit agents ran before the redraft to surface the live state:

### Windmill live state
- `macro_research` schedule: live, 7AM Mon–Fri SGT → **added to Part 1 Daily Intelligence**
- `macro_daily_push` schedule: disabled on server → **marked ⚠️ DISABLED in Part 1, moved to Part 5 hygiene**
- `portfolio_earnings_post_check`: server runs 1AM SGT; disk/docs say 7AM → **drift noted in Part 1**
- `portfolio_price_fetcher`: server runs 7 days/wk; disk `.yaml` says Mon–Fri → **drift noted in Part 1**
- `fundamentals_fetcher`: hour + day differ between server and disk → **drift noted in Part 1**
- 5+ schedules with server path ≠ disk filename → **grouped in Part 5 schedule-drift table**

### Postgres live state
- **33 tables** confirmed (old docs claimed "14 research / 8 agent" in inconsistent ways)
- `portfolio_scores`: 124 rows — backbone live
- `portfolio_candidate_evals`: 1 row — live but terminal (nothing reads it)
- `portfolio_thesis`: 0 rows — W2 feature live but unused
- `earnings_surprises`: 0 rows — superseded by `earnings_analyses`
- All 13 quant tables from `stock_data_fetcher` populated

### Agent / architecture state
- W4a static planner live: `planner.py` with `portfolio_analysis`, `thesis_check`, `macro_brief`
- Agent-table count: 8 (old docs variously said 6 or 8 — fixed to 8)
- Three broken seams confirmed and documented for the first time

---

## Five Owner Decisions Driving the Structure

1. **Professional Intelligence deleted entirely.** APAC deal tracker, sponsor monitor, LNG spread
   alert — none built, none relevant to personal portfolio advisory. Removed from roadmap permanently.

2. **Portfolio advisor as centerpiece.** The new Part 2 is the largest section: data-flow diagram,
   three broken seams table, and four initiatives (A: idea pipeline, B: replacement screener,
   C: close the loop, D: quantitative precision).

3. **Dashboard as a dedicated container.** A new dedicated Docker service on `agent_net`, proxied via
   the public Caddy at `/opt/n8n/Caddyfile`. Net-new auth requirement. Clean separation from the
   agent FastAPI service (shared-fate, deploy, and security implications of coupling were the reason
   for dedicated container over embedding in the agent).

4. **ReAct sequenced after Parts 2–3.** W4b is most powerful when it has coherent, fully-wired
   advisor tools to reason over. Positioned as Part 4 (after advisor coherence + dashboard).

5. **Affection bot separation.** Config-only (~1 hour, no code change). Moved to Part 5 hygiene.

---

## Structural Changes Applied

### Old structure → New structure

| Old | New |
|---|---|
| Objective (W1→W6 ladder as spine) | Objective (portfolio advisor + push/pull surfaces) |
| Part 1 — What's Running | Part 1 — What's Running *(reality-synced, all audit corrections applied)* |
| Part 2 — Active: W1 Telegram Agent | *(removed — agent is now in Part 1 as one component)* |
| Part 3 — Agent Sophistication Roadmap (W2/W3/W4/W5/W6) | Part 2 — The Coherent Portfolio Advisor *(centerpiece)* |
| Part 4 — Agent Data Sources | *(absorbed into Part 2 initiatives)* |
| Part 5 — Professional Intelligence | **DELETED** |
| Part 6 — System Reliability | Part 5 — Infrastructure & Hygiene *(expanded)* |
| Part 7 — Lower Priority | Deleted / Parked *(expanded)* |
| *(none)* | Part 3 — The Dashboard *(new)* |
| *(none)* | Part 4 — Agent Reasoning / ReAct *(repositioned)* |
| *(none)* | Build Sequence *(explicit priority order before Part 1)* |
| Reference | Reference *(corrected: 33-table grouping, formatter status column)* |

### What was preserved

- All live component descriptions in Part 1 (with corrections applied)
- Full Windmill resource table (with affection split note)
- Research file index (audit docs, framework docs)
- Key paths table (expanded with `macro/` and `index.json`)
- Telegram formatter architecture table (added Status column)
- Portfolio rationalization and candidate eval detail (moved into Part 2 context)

### What was removed

- W-series as an organizing spine (W2/W3/W4/W5/W6 stage headers)
- Professional Intelligence (Part 5 in old ROADMAP)
- Part 4 Agent Data Sources as a standalone section
- "Portfolio Advisor Mode" as a W6 stage (absorbed into the new centerpiece)
- Lower Priority section (productivity workflows moved to Deleted/Parked)
- Repeated Portfolio Rationalization block at bottom of old ROADMAP (was duplicated)
- Telegram Agent Build Status table (content merged into Part 1 agent component)
- Stale "Agent Sophistication Roadmap" framing text

---

## Verification Pass

```
grep -i "deal tracker\|sponsor\|LNG\|infrastructure deal" /root/docs/ROADMAP.md
# → 0 hits ✅

grep "macro_research" /root/docs/ROADMAP.md
# → present in Part 1 Daily Intelligence ✅

grep "DISABLED" /root/docs/ROADMAP.md
# → macro_daily_push marked ⚠️ DISABLED ✅

grep "1AM\|drift" /root/docs/ROADMAP.md
# → portfolio_earnings_post_check drift noted in Part 1 ✅

grep "Three Broken Seams\|broken seam" /root/docs/ROADMAP.md
# → Part 2 leads with the three-seam table ✅

grep "Build Sequence" /root/docs/ROADMAP.md
# → explicit priority section before Part 1 ✅
```

W-series as spine: Part headers are now "Part 1/2/3/4/5" not "W1/W2/etc." W4a/W4b appear only in
Part 4 (agent reasoning) as implementation labels — not as the document's organizing metaphor. ✅

---

## Files Changed

| File | Action |
|---|---|
| `/root/docs/ROADMAP.md` | Full structural rewrite — new 9-section structure |
| `/root/docs/plans/2026-06-25_roadmap-redraft.md` | Created — persisted plan, Status: done |
| `/root/docs/logs/2026-06-25_roadmap-redraft.md` | Created — this file |

No Windmill scripts, agent code, tests, or CLAUDE.md changed.
(CLAUDE.md "Current Status" already points to ROADMAP.md — no pointer update needed.)
