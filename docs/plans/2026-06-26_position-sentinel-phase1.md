---
Subject: Proactive Position Sentinel — automatic catalyst monitoring, materiality triage & critical alerts
Date: 2026-06-26
Status: approved
Planner model: claude-opus-4 (Claude Code plan mode)
Executor model: deepseek (opencode) or any
Hard Rules in force: [1, 4, 6, 7, 9, 10, 11, 15, 16, 17, 18, 19, 20, 22]
Risk tier: HIGH (planner-locked oracle)
Complies with: docs/EXECUTOR_CONTRACT.md
Deliverable: new ROADMAP pillar (the path) + executor-ready Phase 1 build plan
Files to read before coding: CLAUDE.md, docs/TESTING.md, docs/WORKFLOW_ARCHITECTURE.md, docs/ROADMAP.md, windmill/u/admin/portfolio_move_monitor.py, windmill/u/admin/portfolio_email.py, windmill/u/admin/portfolio_analyst_alert.py, windmill/u/admin/portfolio_earnings_alert.py
---

# Plan: Proactive Position Sentinel

## Context — the gap this closes

The portfolio system reacts to **price** and to **scheduled** events, but it does not proactively
monitor **information** about held positions, score its **materiality**, or auto-assemble the **"why"**
behind a move. The BABA episode is the proof:

- **The move monitor never fired on BABA all week.** Day-by-day it fell -3.2 / -0.3 / -2.0 / -2.3 /
  -2.7 / **-4.7%** — the largest single session was under the ±5% position threshold, so nothing
  triggered. Yet cumulatively BABA was **-11.5% over 5 trading days and -27.3% from its 20-day high**
  (9988.HK: -11.1% / -25.0%). The entire slide was invisible.
- Even where price *did* move, **no system assembled the confluence** (Anthropic distillation
  accusation → letter to Congress; a 67% EPS collapse; Pentagon military-linked listing; China retail
  contraction; AI travel curbs). The owner had to hand-pull that from claude.ai.

**Goal:** a sentinel that continuously watches held-position information, scores how material it is,
fuses it with price behaviour, and **proactively pushes a critical alert + synthesized analysis** when
it matters — no manual prompting.

**Everything needed already exists as reusable parts** — this wires them into a loop, it is not a
green-field build:

| Capability | Reuse | Location |
|---|---|---|
| Per-holding news fetch | `fetch_news(query)` (Google News RSS) | `portfolio_email.py:195` |
| Push alert (md→formatter→Telegram) | `_dispatch_formatter(...)` | `portfolio_move_monitor.py:25`, `portfolio_analyst_alert.py:50` |
| Auto-dispatch a synthesis job | `_dispatch_pre_analysis` → `jobs/run/p/...portfolio_earnings_analysis` | `portfolio_earnings_alert.py:45` |
| Dedup / run-state | `agent_kv` SELECT/INSERT (`analyst_alert_state`) | `portfolio_analyst_alert.py:171` |
| The "why" synthesis engines | `research_tool` (Google News+Perplexity+Serper+Tavily+Brave+EDGAR+Exa→Grok-4.3), `portfolio_earnings_analysis` (EDGAR 8-K+Exa→Grok) | `windmill/u/admin/` |
| Cumulative price math | `price_history` (daily closes, all positions) | Postgres |
| Acute intraday price alert | `portfolio_move_monitor` (±5% pos / ±1.5% port, session-aligned hourly) | live |

---

## The trigger model (answers the design questions)

Three **independent** trigger families, each with its own threshold, plus a **confluence** escalation.
All thresholds are config constants (tunable; values below are the proposed starting point — sign-off).

| # | Trigger family | Source | Starting threshold | Severity | Action |
|---|---|---|---|---|---|
| i-a | **Price — acute** (exists) | move_monitor (intraday) | position ≥ ±5% / portfolio ≥ ±1.5% single session | HIGH | existing alert (unchanged) |
| i-b | **Price — cumulative** (NEW — the BABA gap) | `price_history` | position ≤ **-8% / 3 trading days** OR ≤ **-12% / 5d** OR ≤ **-20% vs 20-day high** | HIGH | **Phase 1 alert (enabled)** |
| ii | **News — materiality** (NEW) | `position_events` | any item **materiality = 3**, OR **cumulative materiality ≥ 4** over rolling 72h (stacking headlines) | MED→HIGH | Phase 2 alert (log-only in P1) |
| iii | **Confluence** (NEW — the BABA case) | i ∧ ii in same window | any price trigger (i-a or i-b) **AND** any news item materiality ≥ 2 in rolling 72h | **CRITICAL** | Phase 2: **auto-dispatch deep-dive synthesis** → critical push |

Why this shape:
- **Cumulative price** is the single most important addition — it would have caught BABA on 24 Jun,
  two days early, with near-zero false-positive risk (it's pure arithmetic on reliable price data).
  That's why Phase 1 enables it immediately.
- **News-only** catches thesis-threatening headlines *before* price reacts, but depends on the
  materiality scorer being calibrated → runs **log-only** until Phase 2.
- **Confluence** is the rare, loud, "give me the full picture" event — both a price signal and material
  news. BABA was confluence: cumulative -11.5% **and** ≥3 stacked material headlines.
- Downside is the default for criticals (a holder's risk); large up-moves are optional informational
  notes, not criticals.

### How news materiality is tracked
1. **Ingest** — each scan, for every holding: `fetch_news(company)` (Google News RSS) + optionally
   Finnhub `company-news`. (Phase 1 = Google News only to stay lean.)
2. **Dedup** — by URL/headline hash against `position_events` (and a per-run cursor in `agent_kv`), so
   each item is scored once.
3. **Triage (LLM, cheap)** — each NEW item → one Deepseek call returning STRICT JSON:
   `materiality` 0–3, `category` (earnings|regulatory|legal|geopolitical|competitive|analyst|m&a|guidance|other),
   `direction` (neg|neutral|pos), `impact` (one line). Rubric:
   - **0** routine/noise · **1** minor/context · **2** material (could move thesis or price) ·
     **3** critical/thesis-threatening (regulatory/legal action, earnings collapse, guidance cut,
     government designation, fraud).
4. **Store** in `position_events`; **aggregate** rolling materiality per ticker for triggers ii/iii.

This is exactly what would have scored BABA's week as a cluster of 2s and 3s → news + confluence fire.

---

## The roadmap path (new pillar — "Proactive Position Sentinel")

Add as a new ROADMAP pillar and insert at **priority 2 in the Build Sequence** (high value, mostly
reuse, directly owner-requested). Four phases, each shipping standalone value:

- **Phase 1 — Signal spine + cumulative-price alert (this plan).**
  New `position_events` + `position_signals` tables; `position_sentinel` script (session-aligned
  hourly) ingests per-holding news → Deepseek materiality triage → `position_events`; computes
  cumulative price drawdown from `price_history` → `position_signals`. **Enable the cumulative-price
  alert now** (reliable). News-materiality + confluence detected and **logged only** (calibration).

- **Phase 2 — Confluence critical alert + auto-synthesis.**
  On confluence (or news materiality ≥3), auto-dispatch `research_tool` (stock/deep) or
  `portfolio_earnings_analysis` via the existing `_dispatch` pattern → the "full picture" writeup
  (catalyst confluence + bull/bear + thesis impact + suggested action) → critical Telegram + email
  push. Turn on news-only alerts once the materiality bar is calibrated on Phase-1 logs.

- **Phase 3 — Thesis-aware triage.** Once `portfolio_thesis` is seeded (separate plan), compare each
  material event against the stored thesis/conviction → escalate thesis-threatening events, suppress
  noise; maintain a per-position `thesis_status` (intact | at-risk | broken).

- **Phase 4 — Daily Sentinel Briefing + dashboard + ReAct.** Consolidated daily "what's material and
  why" digest; surface `position_events` in the dashboard (Part 3); let the agent answer "why is X
  moving?" from the event log instead of a cold web search (ties to Part 4 ReAct).

**Cross-cutting principle — alert fatigue is the #1 failure mode.** Controls: severity tiers, log-only
calibration before enabling each new alert class, per-(ticker,signal) dedup cooldown in `agent_kv`,
and confluence-gating for the loudest pushes.

---

## Phase 1 — executor-ready build plan

### Sign-off gates (Hard Rules 6 + 10) — approving this plan approves:
1. **Models:** Deepseek `deepseek-chat` for materiality triage (high-volume, cheap); Grok-4.3 for the
   Phase-2 confluence synthesis (matches `research_tool`/`earnings_analysis`). Confirm or substitute.
2. **Materiality triage prompt** (generic framing, Hard Rule 10):
   ```
   You are triaging a single news headline about a company a portfolio holds. Using ONLY the
   headline/snippet provided, return STRICT JSON and nothing else:
   {"materiality": 0|1|2|3, "category": "earnings|regulatory|legal|geopolitical|competitive|analyst|m&a|guidance|other",
    "direction": "neg|neutral|pos", "impact": "<one short clause: why it matters or 'routine'>"}
   materiality: 0=routine/noise, 1=minor/context, 2=material (could move the thesis or price),
   3=critical/thesis-threatening (regulatory or legal action, earnings collapse, guidance cut,
   government designation, fraud). Be conservative: reserve 3 for genuinely thesis-changing news.
   Ticker: {ticker}
   Headline: {headline}
   Snippet: {snippet}
   ```
3. **Starting threshold constants** (trigger table above).

### Files changed
| Action | Path | Change |
|---|---|---|
| Create | `portfolio/migrations/2026-06-26_position_sentinel.sql` | `position_events` + `position_signals` DDL (+ apply to live DB) |
| Edit | `portfolio/schema.sql` | append the two table definitions (authoritative schema) |
| Create | `windmill/u/admin/position_sentinel.py` | main monitor script (+ `.script.yaml`) |
| Create | `windmill/u/admin/position_sentinel.schedule.yaml` | session-aligned hourly schedule (mirror move_monitor cron) |
| Create | `windmill/u/admin/position_sentinel_telegram.py` | formatter (9th) reading the canonical `.md` (+ `.script.yaml`) |
| Edit | `agent/tests/test_windmill_scripts.py` + `test_schema.py` | pure-logic + schema tests (RED→GREEN) |
| Edit | `docs/ROADMAP.md` | add the pillar + Build-Sequence insert |
| Edit | `CLAUDE.md` | formatter count 8 → 9; list `position_sentinel_telegram` |
| Edit | `docs/WORKFLOW_ARCHITECTURE.md` | pseudocode for `position_sentinel` |
| Create | `docs/logs/2026-06-26_position-sentinel-phase1.md` | implementation log |

### Schema (new tables)
```sql
CREATE TABLE IF NOT EXISTS position_events (
    id            SERIAL PRIMARY KEY,
    ticker        TEXT NOT NULL,
    published_at  TIMESTAMPTZ,
    fetched_at    TIMESTAMPTZ DEFAULT NOW(),
    source        TEXT,
    headline      TEXT NOT NULL,
    url           TEXT,
    url_hash      TEXT NOT NULL,          -- dedup key
    materiality   SMALLINT,               -- 0..3
    category      TEXT,
    direction     TEXT,                   -- neg|neutral|pos
    impact        TEXT,
    UNIQUE (ticker, url_hash)
);
CREATE TABLE IF NOT EXISTS position_signals (
    id            SERIAL PRIMARY KEY,
    ticker        TEXT NOT NULL,
    signal_date   DATE NOT NULL DEFAULT CURRENT_DATE,
    signal_type   TEXT NOT NULL,          -- price_cumulative | news_materiality | confluence
    severity      TEXT NOT NULL,          -- HIGH | CRITICAL | MED
    detail        JSONB DEFAULT '{}',     -- {chg_3d, chg_5d, vs_20d_high, news_ids[], cum_materiality}
    alerted       BOOLEAN DEFAULT FALSE,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);
```

### Script structure — `position_sentinel.py`
`main(portfolio_db, deepseek_key, finnhub_key="", telegram_bot_token, telegram_owner_id, wm_token)`
- **Pure helpers (unit-tested — these carry the logic):**
  - `_cumulative_drawdowns(closes: list[float]) -> dict` → `{chg_3d, chg_5d, vs_20d_high}` from an
    ordered close series (mirrors the SQL window math already validated against BABA).
  - `_price_signal(dd: dict, cfg) -> str|None` → returns `"price_cumulative"` if any threshold breached.
  - `_parse_materiality(raw: str) -> dict|None` → strict-JSON parse + normalize (materiality clamped
    0–3, category/direction whitelisted, blank/garbage → None so noise is never stored as material).
  - `_aggregate_materiality(events, window_h=72) -> int` and `_confluence(price_sig, agg, items, cfg)`.
  - `_url_hash(url)`.
- **I/O at edges:** `_fetch_news` (reuse Google News RSS pattern), `_call_deepseek_triage`,
  `_load_closes(cur, ticker)`, `_load_recent_events(cur, ticker)`, DB writes, `_dispatch_formatter`.
- **Flow per holding:** load closes → drawdowns → price signal; fetch news → dedup (url_hash) → triage
  NEW items → store `position_events`; aggregate materiality; evaluate triggers → write
  `position_signals`. **Phase-1 alerting:** if a `price_cumulative` signal is new (not alerted in the
  last cooldown window per `agent_kv`), write the canonical `.md` and `_dispatch_formatter
  ("position_sentinel_telegram", ...)`. `news_materiality`/`confluence` signals are written with
  `alerted=false` (log-only) — Phase 2 turns these into pushes.
- **Silent exit** when no price-cumulative signal fires (mirror move_monitor's no-op exit).

### Canonical `.md` + formatter (Hard Rules 16, 18, 19)
`position_sentinel.py` writes `/research/portfolio/sentinel_<ts>.md`: JSON front-matter
(signals list: ticker, type, severity, drawdowns, top material headlines) + ≥500-word narrative +
`<!-- DETAIL -->`. `position_sentinel_telegram.py` reads it and builds the ≥500-word self-contained
Telegram message (copy `_send_telegram`/`_split_telegram_message` verbatim from an existing formatter;
no cross-script imports). Front-matter schema change ⇒ formatter `_build_message` + a round-trip
contract test in the same commit.

### TDD (Hard Rules 15, 20) — write RED first
In `test_windmill_scripts.py`, load via the established `sys.modules` stub pattern (stub
`requests, psycopg2, feedparser, openai`). Tests:
- `test_cumulative_drawdowns_matches_baba` — feed BABA's real close series
  `[..., 99.80, 95.07]`; assert `chg_5d ≈ -11.5`, `vs_20d_high ≈ -27.3` (anchors the math to the
  real case; not a tautology — values come from price arithmetic, not a fixture echo).
- `test_price_signal_fires_on_baba_thresholds` and `test_price_signal_silent_on_calm_series`
  (empty-artifact guard: a flat series returns None).
- `test_parse_materiality_valid_and_clamps` (e.g. `materiality: 5` → clamped/ rejected) and
  `test_parse_materiality_blank_returns_none`.
- `test_confluence_requires_price_and_news` (price-only → not confluence; price + a ≥2 item → confluence).
- `test_position_sentinel_telegram_build_message_500_words` + front-matter round-trip contract.
- `test_schema.py`: `position_events` / `position_signals` columns present.

### Deploy + live-verify (Hard Rules 9, 17)
- Apply the migration to the live DB; `wmill script push` both scripts (Hard Rule 9 — never sync push).
- **Live-verify on real holdings (the artifact, not ok:True):** run `position_sentinel` once; confirm
  `position_signals` contains a `price_cumulative` HIGH row for **BABA/9988.HK** with the correct
  drawdowns, `position_events` has triaged rows with materiality scores, and a Telegram alert landed
  in `telegram_outbox` whose body names the triggering tickers + drawdowns. Confirm calm names produce
  no signal.

---

## Verification (after Phase 1)
- `SELECT ticker, signal_type, severity, detail->>'chg_5d' FROM position_signals ORDER BY created_at DESC` shows the cumulative-price signals; BABA present.
- `position_events` populated with non-null materiality across holdings; blank/garbage never stored.
- Telegram alert rendered ≥500 words, self-contained, names tickers + drawdowns (read `telegram_outbox`).
- Full pytest green inside the agent container; `git status` clean after commit.

## Out of scope (later phases)
Confluence auto-synthesis + news/confluence pushes (Phase 2), thesis-aware triage (Phase 3, needs the
thesis-seeding plan), daily briefing + dashboard + ReAct "why is X moving" (Phase 4). Finnhub
company-news as a second source (Phase 1 uses Google News only).

## Locked Oracle Tests (G1)
> Planner-authored. The pure-helper tests in the TDD section ARE the locked oracle. Wrap them in
> `# LOCKED ORACLE — copy verbatim, do not modify assertions` and reproduce unchanged:
> - `_cumulative_drawdowns(<BABA real closes …,99.80,95.07>)` → `chg_5d ≈ -11.5` and `vs_20d_high ≈ -27.3`
>   (anchored to real price math — not a fixture echo).
> - `_price_signal` fires on the BABA series; returns `None` on a flat series (empty-artifact guard).
> - `_parse_materiality('{"materiality":5,…}')` clamped/rejected; blank/garbage → `None`.
> - `_confluence(price_only) is False`; `_confluence(price + a ≥2 news item)` is True.
> - `position_sentinel_telegram._build_message(...)` ≥ 500 words + front-matter round-trip contract.
> Fix the code to pass — never weaken a locked assertion.

## RED-proof requirement (G2)
Paste BEFORE implementing (fails — helpers absent), then GREEN after:
```bash
docker exec root-straitsagent-1 python -m pytest tests/test_windmill_scripts.py -k "cumulative_drawdowns or price_signal or parse_materiality or confluence or position_sentinel" -q
```

## Asserting Verification Script (G4)
```bash
docker exec root-portfolio_postgres-1 psql -U portfolio_user -d portfolio -tAc \
  "SELECT count(*) FROM position_signals WHERE signal_type='price_cumulative' AND ticker IN ('BABA','9988.HK') AND (detail->>'chg_5d')::float <= -10" \
| { read n; [ "${n:-0}" -ge 1 ] && echo "baba_cum_signal=$n" || { echo "FAIL: no BABA cumulative signal"; exit 1; }; }
docker exec root-portfolio_postgres-1 psql -U portfolio_user -d portfolio -tAc \
  "SELECT count(*) FROM position_events WHERE materiality IS NOT NULL" \
| { read n; [ "${n:-0}" -gt 0 ] && echo "events=$n" || { echo "FAIL: no triaged events"; exit 1; }; }
docker exec root-portfolio_postgres-1 psql -U portfolio_user -d portfolio -tAc \
  "SELECT count(*) FROM telegram_outbox WHERE sent_at > NOW()-INTERVAL '15 min' AND message ILIKE '%BABA%'" \
| { read n; [ "${n:-0}" -ge 1 ] && echo "PASS alert_sent=$n" || { echo "FAIL: no BABA alert in outbox"; exit 1; }; }
```
Close-out pastes this output ending in `PASS`. (Adjust `telegram_outbox` column name to the live schema if it differs — STOP and report if so, do not guess.)

## Acceptance Gate (G2/G3/G5 + review)
- [ ] Locked tests diff-clean vs the block above (G1)
- [ ] RED + GREEN runs pasted (G2)
- [ ] Asserting verify script output pasted, ends in `PASS` (G4)
- [ ] A BABA `price_signals` row + the rendered Telegram body pasted (G3)
- [ ] Sign-off items (models, materiality prompt, thresholds) confirmed before code

## Execution
1. Confirm the three sign-off items (models, materiality prompt, thresholds). If not approved, STOP.
2. Set front-matter `Status: executing`, commit.
3. Build order: schema → pure helpers + RED tests → script to GREEN → formatter + contract test →
   deploy → live-verify on BABA → docs (ROADMAP pillar, CLAUDE.md formatter count, WORKFLOW_ARCHITECTURE) → commit.
4. Run the Verification section. Set `Status: done`, commit.
Do not redesign. If any command errors or output differs from "Expected", STOP and report.
