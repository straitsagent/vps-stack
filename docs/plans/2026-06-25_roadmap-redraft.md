---
Subject: 2026-06-25 — Full redraft of docs/ROADMAP.md
Date: 2026-06-25
Status: done
Planner model: claude-sonnet-4-6 (Claude Code plan mode)
Executor model: claude-sonnet-4-6 (same session)
Hard Rules in force: [7, 12]
Files to read before coding: docs/ROADMAP.md, .claude/plans/please-review-the-plan-virtual-candle.md
---

# Plan: Full redraft of docs/ROADMAP.md

## Context

After ~73 commits of debugging, refactoring, and hardening (Telegram formatter architecture,
artifact-driven testing, macro/health rebuilds, bug fixes), the roadmap has drifted from both
reality and the owner's intent. The current ROADMAP.md is organized around a W1→W6
"router → reasoning agent" march that no longer reflects how the stack is actually used or where
energy should go. A live audit (Windmill, Postgres, agent) confirmed the drift and surfaced the
real architecture.

The owner wants a **full structural rewrite** around five decisions:
1. **Delete Professional Intelligence entirely** (APAC deal tracker, sponsor monitor, LNG — old Part 5).
2. **Center on a coherent portfolio advisor** — pull rationalization, candidate eval, research, and
   scan-driven idea generation into one whole that recommends both what to **remove** and what
   **better candidates to add**, with improved **quantitative precision**.
3. **Add a web dashboard** (new) to visualize/navigate portfolio + research + news — **dedicated
   container** behind the existing public Caddy, with its own auth.
4. **Split affection pings into a separate bot** (near config-only).
5. **Reposition the dynamic ReAct agent** as the reasoning layer *over* the coherent advisor,
   sequenced after the coherence + quant foundations.

Outcome: a ROADMAP.md that is reality-synced, framed around the portfolio-advisor goal, with a clear
build sequence and the dead professional-intelligence track removed.

## Audit ground-truth (drives the rewrite)

**Live state corrections (Part 1 must reflect):**
- `macro_research` is **live** (7AM Mon–Fri) but undocumented → add it.
- `macro_daily_push` is documented-live but its schedule is **disabled** → mark parked/disabled.
- Cron drift, server vs disk/docs: `portfolio_earnings_post_check` runs **1AM** on server (docs say 7AM);
  `portfolio_price_fetcher` daily+evening run **7 days/wk** on server (disk says Mon–Fri);
  `fundamentals_fetcher` hour/day differ; 5 schedules have server paths ≠ disk filenames.
- Empty tables: `portfolio_thesis` (W2 thesis feature unused), `earnings_surprises` (0 rows).
- DB has **33 tables** (docs claim "14 research / 8 agent"); agent-table count is internally
  inconsistent in docs (6 vs 8).

**Portfolio advisor — current data flow (the coherence problem):**
- Backbone solid: `stock_data_fetcher` → 13 quant tables ← `research_tool` → `research_reports`.
- `portfolio_rationalization` reads quant tables → writes `portfolio_scores` (the one shared handoff).
- `portfolio_candidate_eval` reads `portfolio_scores`, **auto-dispatches** `stock_data_fetcher` +
  `research_tool` for a named ticker → writes `portfolio_candidate_evals` (**terminal — nothing reads it**).
- **Three broken seams, all human-bridged:** (a) scans never emit structured tickers/ideas (no
  extraction, no idea store); (b) rationalization flags EXIT/TRIM but nothing screens for a
  replacement (the `replacement_ticker` column exists but only a human fills it); (c) candidate
  verdicts are a dead end.
- **Quant gaps:** only `beta` stored (no factor exposures); valuation ranked cross-sectionally only
  (no per-ticker historical percentile); no persisted correlation/risk matrix; sizing is min/median/max
  narrative (no vol-target/risk-contribution math); universe limited to US `peer_comparisons` or
  human-supplied. Daily snapshots + 3-statement history already in DB are sufficient raw material.

**Dashboard:** none exists (agent serves JSON only). Public Caddy `/opt/n8n/Caddyfile` (80/443,
auto-TLS) is the edge. Data ready: Postgres (`portfolio_user`@127.0.0.1:5432) + `/research/*.md` with
`/root/research/index.json` manifest. Net-new requirement: **auth**.

**Affection split:** `affection_ping.schedule.yaml` passes `$var:u/admin/telegram_bot_token` (shared).
Already decoupled otherwise (own `affection_group_id`, own sender code, own `affection_outbox`).
Split = new BotFather token + new `u/admin/affection_bot_token` var + one-line schedule edit + add
bot to chat. No code change required.

**ReAct (W4b):** W4a static planner is live (linear plan→execute→synthesise, no feedback). W4b slots
into the existing `MULTI_STEP` branch, reuses `FAST_EXECUTORS`; medium change (iteration controller +
per-step token accounting), not a rewrite.

## The deliverable — new ROADMAP.md structure

Full rewrite. New top-to-bottom structure:

1. **Objective (reframed).** A coherent personal **portfolio advisor** with two delivery surfaces —
   *push* (email + Telegram digests/alerts) and *pull* (the new dashboard). It reasons across both
   **remove** and **add** decisions with quantitative precision. Drop the W1→W6 spine as the
   organizing metaphor; the agent becomes one component, not the through-line.

2. **Build Sequence.** Explicit priority order: hygiene → coherence seams → quant precision →
   dashboard → ReAct.

3. **Part 1 — What's Running (reality-synced).** Accurate live inventory with every audit correction
   applied. Known drift note pointing to Part 5.

4. **Part 2 — The Coherent Portfolio Advisor (centerpiece).** Current-state data-flow diagram with
   the three broken seams. Then four initiatives: A (idea pipeline), B (replacement screener),
   C (close the loop), D (quantitative precision).

5. **Part 3 — The Dashboard.** Dedicated container on `agent_net`, proxied via public Caddy,
   own auth (net-new). Read-only Postgres + `/research` mount. Phased views.

6. **Part 4 — Agent Reasoning (ReAct over the advisor).** W4a live; W4b after Parts 2–3.

7. **Part 5 — Infrastructure & Hygiene.** Affection-bot separation, schedule-drift reconciliation,
   empty-table decisions, macro_daily_push disposition, API health monitor.

8. **Deleted / Parked.** Professional Intelligence removed. Productivity workflows parked.

9. **Reference.** Corrected resource inventory, key paths, DB-table grouping (33 total), formatter
   architecture table with live/disabled status.

## Files

| Action | Path | Purpose |
|--------|------|---------|
| Rewrite | `/root/docs/ROADMAP.md` | Full restructure per the outline above |
| Persist | `/root/docs/plans/2026-06-25_roadmap-redraft.md` | This plan (you are reading it) |
| Create | `/root/docs/logs/2026-06-25_roadmap-redraft.md` | Implementation log |

## Verification

- `grep -i "deal tracker\|sponsor\|LNG\|infrastructure deal" /root/docs/ROADMAP.md` → 0 hits ✅
- `grep "macro_research" /root/docs/ROADMAP.md` → at least 1 hit ✅
- `grep "macro_daily_push" /root/docs/ROADMAP.md` → marked DISABLED ✅
- `grep "1AM\|earnings_post_check" /root/docs/ROADMAP.md` → cron drift noted ✅
- `grep -i "W1\|W2\|W3\|W4\|W5\|W6" /root/docs/ROADMAP.md` → no W-series as spine framing ✅
- Three broken seams stated explicitly in Part 2 ✅
- Build sequence stated explicitly before Part 1 ✅

## Execution

1. Set front-matter Status: executing, commit.
2. Work the checklist top to bottom; tick each `- [ ]` when its success criteria are met.
3. Run the Verification section.
4. Set Status: done, commit.
Do not redesign. If the plan is ambiguous or wrong, stop and report — do not improvise.
