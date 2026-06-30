# Automation Stack Roadmap

**Last updated:** 2026-06-29 (rationalise StraitsAgent pushes; Perplexity key added to Hermes; plans reviewed)
**Owner:** ${OWNER_NAME}

> **Architecture specs:** Full pseudocode for every workflow lives in [`WORKFLOW_ARCHITECTURE.md`](WORKFLOW_ARCHITECTURE.md).
> **Testing philosophy:** [`TESTING.md`](TESTING.md). **Operations / runbooks:** [`OPERATIONS.md`](OPERATIONS.md).

---

## Objective

Build a personal **portfolio advisor** — a coherent system that tells you what to keep, what to cut, and what to buy next. It reasons across both **remove** and **add** decisions with quantitative precision, and delivers intelligence through two surfaces:

- **Push** — email digests, Telegram alerts, and proactive notifications from Windmill-scheduled scripts
- **Pull** — a web dashboard where you can navigate portfolio positions, research reports, news digests, and advisor outputs

The Telegram agent is the interactive front-end for the advisor — one component of the stack, not the organizing spine. Every workflow serves the portfolio advisor goal.

---

## Build Sequence

What gets built next, in priority order:

1. **Reality-sync + hygiene** — reconcile cron drift, split affection bot, decide empty-table fate (fast, low-risk — Part 5)
2. **Portfolio coherence seams** — idea pipeline → replacement screener → close the loop (the advisor's missing connective tissue — Part 2 A/B/C)
3. **Quantitative precision** — historical valuation percentiles, factor exposures, risk matrix, sizing math (Part 2D)
4. **Dashboard** — scaffold early (view existing data immediately); enrich as the advisor matures; parallelizable with 2+3 (Part 3)
5. **ReAct reasoning layer** — dynamic agent reasoning over the fully-wired advisor tools (Part 4)

**✅ Live (out-of-band, security-led):** **OpenClaw sandboxed assistant** (Part 6) — a self-hosted, owner-only agent runtime with read-only access to the research corpus + Postgres. Deployed and secrets-consolidated 2026-06-27. Its overlap with the Part 4 ReAct layer is now ripe to reconsider.

**✅ Live + integrating (security-led):** **Hermes agent** (Part 7) — confined autonomous agent, in active daily use, now graduating from A/B trial to a planned **integration layer**. Approved roadmap [`docs/plans/2026-06-29_hermes-integration-roadmap.md`](plans/2026-06-29_hermes-integration-roadmap.md) sequences three workstreams (system visibility → research-MD quality → analysis takeover) under seven security invariants that never weaken the sandbox.

---

## Part 1 — What's Running

Everything below is live and running unattended unless noted.

> **Schedules reconciled 2026-06-25** — git filenames now match live server paths; cron values verified. `earnings_post_check` canonicalized to 7 AM SGT; `price_fetcher` confirmed 7 days/week.

### Foundation

- Windmill at `http://<YOUR_VPS_IP>:8080` — Python scripts, cron schedules, resource system
- PostgreSQL (`portfolio_postgres`, same instance, 2 databases: `portfolio` + `affection`) — `portfolio` schema applied, 33 positions seeded. **31 tables in portfolio DB, 2 tables in affection DB (separate).** Affection bot data isolated from financial data.
- GCP service account — Drive + Sheets APIs enabled
- Windmill resources: `u/admin/gmail_smtp`, `u/admin/portfolio_db`, `u/admin/affection_db` (new 2026-06-30), `u/admin/deepseek_key`, `u/admin/rapidapi_key`, `u/admin/finnhub_key`, `u/admin/perplexity_key`, `u/admin/xai_key`, `u/admin/exa_key`

### Daily Intelligence

| Workflow | Schedule | Notes |
|---|---|---|
| Morning News Digest | 6:30 AM SGT daily | RSS (WSJ/Reuters/NYT) + newsletter AI summaries. Email + idea_extractor. Telegram retired 2026-06-29. |
| YouTube Channel Monitor | Daily 18:00 SGT | 37 channels, RapidAPI transcripts, Deepseek per-video summaries, 3-retry logic. Email only (Telegram retired 2026-06-29; 24h synthesis commentary removed 2026-06-30). |
| Macro Research | 7:00 AM SGT Mon–Fri | Perplexity macro scan → Deepseek synthesis → `/research/macro/YYYY-MM-DD_HHMM.md` + email. Telegram retired 2026-06-29. **Live but previously undocumented.** |
| Macro Daily Push | — | **Parked 2026-06-26** — main script retained for reference; disabled schedule removed (server + disk). `macro_research` handles the macro push. Its formatter `macro_daily_push_telegram` remains live (used by `macro_research`). |

### Portfolio System

| Component | Schedule | Notes |
|---|---|---|
| Daily Price Fetcher | 5:45 AM + 5:45 PM SGT, 7 days/week | yfinance EOD prices + USDHKD FX rate → `price_history`, `fx_rates` |
| Portfolio Email | 6:00 AM + 6:00 PM SGT | ADR consolidation, top movers, Google News per mover. Email only. Telegram retired 2026-06-29. |
| Weekly Portfolio Review | Saturday 8:00 AM SGT | Week P&L, Finnhub news, Deepseek commentary. Email + Telegram. |
| Move Monitor | Hourly, Mon–Fri (HK + US sessions) | Alert on portfolio ±1.5% or position ±5%. Telegram. |
| Fundamentals Fetcher | Sunday 6:00 PM SGT | Finnhub + yfinance → `fundamental_data` (P/E, targets, margins, ROE, ROIC) |
| Portfolio Rationalization | Weekly Saturday 6AM SGT (+ on-demand via Telegram) | ✅ Live. 5-factor scoring × 4 scenarios, Grok-4.3 + Deepseek fallback. Writes `portfolio_scores`. |
| Portfolio Candidate Eval | On-demand (Telegram: `evaluate TICKER`) | ✅ Live. 3-gate ADD/WATCH/PASS. Auto-fetches quant data + research. Writes `portfolio_candidate_evals`. |
| Portfolio Earnings Alert | 9:00 PM SGT Mon–Fri | EPS surprise alerts; dispatches pre-earnings analysis job. Telegram. |
| Portfolio Analyst Alert | 7:45 AM SGT daily | Analyst rating upgrades/downgrades, dedup via `agent_kv`. Telegram. |
| Position Sentinel | On-demand (Phase 1); hourly schedule ready for Phase 2 | ✅ Phase 1 live. Cumulative-price alerts (≤-8%/3d, ≤-12%/5d, ≤-20% vs 20d-high). News materiality scored (Deepseek 0–3) + logged. Confluence logic built, awaiting calibration for Phase 2 activation. Formatter: `position_sentinel_telegram` (9th formatter). |
| Portfolio Earnings Analysis | Dispatched by alert or agent | Pre/post-earnings briefing: EDGAR 8-K + Exa transcripts + Grok-4.3. Writes `/research/earnings/`. |
| Portfolio Earnings Post-Check | 7:00 AM SGT daily | Checks Finnhub for epsActual; dispatches post-earnings analysis if needed. |

### Research & Tools

| Component | Notes |
|---|---|
| Research Tool (`u/admin/research_tool`) | Manual trigger or Telegram. stock/strategy/macro/project × brief/standard/deep. Google News + Perplexity + Serper + Tavily + Brave + EDGAR + Exa + FRED. Grok-4.3 synthesis. Writes `research_reports`. **2026-06-27:** "Reported EPS" column-detection bug fixed (was silently dropping EPS Surprises table); `lxml==5.3.0` added to lock (same as `stock_data_fetcher`). |
| Stock Data Fetcher (`u/admin/stock_data_fetcher`) | Single-ticker collector → 13 quant tables. Called on-demand by research_tool and candidate_eval; can be dispatched standalone. |

### System

| Component | Notes |
|---|---|
| Daily Health Check | 8:00 AM SGT — comprehensive system monitor: Windmill workflow status + VPS host health (disk/memory/load/Docker) + Drive backup status. Deterministic alerts via threshold rules. Host deadman at 08:30 SGT via systemd. Telegram notification retired. |
| Windmill Error Alert | On failure — email + Telegram + Deepseek 1-line diagnosis |
| Affection Ping | 2-hourly 9AM–11PM SGT — random sticker (11 packs) + Deepseek caption → Telegram group. Logs to `affection_outbox`. Runs on its own bot (`StraitsAffectionBot` via `u/admin/affection_bot_token`), separate from the main agent. |
| Short-Term Memory Synthesis (affection) | Daily 02:00 SGT — Deepseek `deepseek-chat` synthesis of last 7 days of `affection_conversation` per chat_id. UPSERTs into `affection_short_term_memory`. |
| Long-Term Memory Synthesis (affection) | Weekly Sun 02:30 SGT — Deepseek synthesis of all `affection_conversation` (capped 500 msgs) per chat_id, integrates prior memory. UPSERTs into `affection_long_term_memory`. |

### Telegram Agent

| Component | Status |
|---|---|
| Agent service (FastAPI + Docker) | ✅ Live — `root-straitsagent-1` on `agent_net`. Bot: `@<YOUR_BOT_USERNAME>` |
| HTTPS webhook | ✅ `https://<YOUR_DOMAIN>/webhook/telegram` → Caddy → `straitsagent:8001` |
| Intent routing | ✅ Deepseek `deepseek-chat`. 5 latency classes. Slash-command shortcuts. |
| Tool registry | FAST: portfolio_snapshot, portfolio_digest, ticker_detail, live_prices, health_check, news_digest, youtube_digest, earnings, news_search, macro_indicators, thesis_read |
| | FIRE: email_summary |
| | ASYNC_NOTIFY: research, earnings_analysis |
| | GATED_WRITE: price_refresh, fundamentals_refresh, thesis_write |
| | MULTI_STEP: portfolio_analysis, thesis_check, macro_brief (static planner — W4a) |
| Unit tests | ✅ 495 passing — `agent/tests/` (classifier, telegram, tools, routing, planner, db, schema, Windmill scripts, formatter behavioral tests, affection ping artifact tests). Note: count reduced from ~680 after rationalise E6 removed Telegram dispatch tests for 4 retired scripts (2026-06-29). Testing Phase D (approved) will add ≥10 new harness tests. |
| Agent Drafts Telegram group | ⏳ Pending — create group → add bot → set `DRAFTS_GROUP_ID` in `agent.env` → rebuild container |

---

## Part 2 — The Coherent Portfolio Advisor

The centerpiece of the next build phase. The goal: a system that reasons across both **what to remove** and **what to add** — automatically, with quantitative grounding, without a human bridging each step.

### Current Data Flow

```
[YouTube / News scans]
     |
     |  ✗ no extraction — tickers/ideas evaporate
     ↓
[stock_data_fetcher] ─────────────→ [13 quant tables]
     ↑                                     |
[research_tool] ──────────────────→ [research_reports]
                                          |
                    [portfolio_rationalization] ──→ [portfolio_scores]
                                                          |
                         ✗ human supplies ticker          |
                                          ↓               ↓
                    [portfolio_candidate_eval] ←──────────┘
                                          |
                               [portfolio_candidate_evals]
                                          |
                               ✗ terminal — nothing reads it
```

### The Three Broken Seams (all currently human-bridged)

| Seam | Problem | Initiative |
|---|---|---|
| **A. No idea pipeline** | YouTube + news scans never extract or store candidate tickers. Good ideas mentioned in scanned content evaporate. | Idea Pipeline |
| **B. No replacement screener** | `portfolio_rationalization` flags EXIT/TRIM but `replacement_ticker` column is filled by a human, not the system. Nothing searches for what to buy instead. | Replacement Screener |
| **C. Terminal verdicts** | `portfolio_candidate_evals` has ADD/WATCH/PASS verdicts. Nothing reads them. They accumulate but never feed back into the rationalization cycle or a watchlist. | Close the Loop |

---

### Initiative A — Idea Pipeline ✅ (Phase 1 — 2026-06-27)

**Goal:** Capture tickers and investment ideas from the YouTube monitor and morning news digest — automatically, without losing them to the scroll.

**Approach:**
- Post-processing LLM extraction pass on YouTube + news scan output (low-cost Deepseek call after each scan run)
- New DB table: `watchlist_ideas` (ticker, source, reason, added_at, status: `pending` / `evaluated` / `archived`)
- `candidate_eval` pull mode: periodically (or on-demand via Telegram) reads `pending` watchlist_ideas and evaluates them
- Generalises the existing auto-dispatch pattern already built into `candidate_eval` — minimal new code

---

### Initiative B — Replacement Screener ✅ (Phase 1 — 2026-06-27)

**Goal:** When `portfolio_rationalization` recommends EXIT/TRIM, automatically generate and rank candidate replacements — no human needed to supply a ticker.

**Approach:**
- On EXIT/TRIM signal: extract sector + factor profile of the flagged position from `portfolio_scores`
- Screener query: peers from `peer_comparisons` + expanded universe (ETF constituents, curated list) → filter by sector / factor match → rank by composite score
- Auto-populate `replacement_ticker` in `portfolio_scores` for the top-ranked candidate
- Auto-dispatch `candidate_eval` for the top candidate(s) — feeds into the same pipeline as Initiative A

---

### Initiative C — Close the Loop ✅ (Phase 1 — 2026-06-26)

**Goal:** `portfolio_candidate_evals` verdicts feed back into the advisor cycle rather than terminating there.

**Approach:**
- WATCH/ADD verdicts write to `watchlist_ideas` (status: `watchlist`)
- `watchlist_ideas` becomes the shared idea store — the output of A, B, and C all flows here
- Next rationalization run includes watchlist items in its narrative section ("monitored candidates")
- Dashboard (Part 3) exposes the watchlist as a navigable view

---

### Initiative D — Quantitative Precision 🔲

**Goal:** Improve the numeric quality of the advisor's scoring and recommendations. All four sub-items are solvable with data already in the DB.

**Current gaps:**

| Gap | Fix | New DB artifact |
|---|---|---|
| Only `beta` stored — no factor exposures (value/growth/momentum/quality) | Regress returns against Fama-French proxies from `price_history` | `factor_exposures` table |
| Valuation ranked cross-sectionally only — no per-ticker historical percentile | Compute from existing `financial_statements` history | `valuation_percentiles` table |
| No persisted correlation matrix or portfolio-level risk decomposition | Compute from `price_history` (33 positions, daily closes) | `risk_matrix` table |
| Position sizing is narrative (min/median/max) — no vol-target or risk-contribution math | Replace narrative with vol-target math (e.g. 1% daily vol per position); output as suggested weight range in rationalization | — (computed at scoring time) |

**Build order:** historical valuation percentiles → correlation/risk matrix → factor exposures → vol-target sizing.

---

## Part 3 — The Dashboard

A read-only web portal to navigate advisor outputs, portfolio positions, and research history. Parallelizable with Part 2 — Phase 1 (scaffold) immediately makes existing data navigable; Phases 2–4 enrich as the advisor matures.

### Architecture

- **Container:** Dedicated `dashboard` service in `/root/docker-compose.yml` — own image, joined to `agent_net` and `default` networks
- **Edge:** New route in `/opt/n8n/Caddyfile` proxying `https://<YOUR_DOMAIN>/dash` (or similar) → `dashboard:3000`; auto-TLS via the existing public Caddy
- **Auth:** Token-based or HTTP Basic auth enforced at the Caddy layer — **net-new requirement, no unauthenticated public exposure**
- **Data (read-only):**
  - Postgres — read-only role (`portfolio_user`), 127.0.0.1:5432
  - `/research/` directory mount — `.md` files via `/root/research/index.json` manifest

### Views (phased)

| Phase | View | Data source |
|---|---|---|
| 1 — Scaffold + auth | Login page + connectivity health | Auth layer; Postgres ping |
| 2 — Portfolio | Positions table, P&L, move history, scores | `portfolio_positions`, `price_history`, `portfolio_scores` |
| 3 — Research & news | Browse news / YouTube / macro / earnings digests chronologically | `/research/*.md` via `index.json` |
| 4 — Advisor outputs | Rationalization scorecard, candidate evals, watchlist, replacement candidates | `portfolio_scores`, `portfolio_candidate_evals`, `watchlist_ideas` |

**Status:** 🔲 Not started

---

## Part 4 — Agent Reasoning (ReAct)

The Telegram agent's dynamic reasoning layer. Sequenced **after** Parts 2–3 so it has a fully-wired, coherent set of advisor tools to reason over.

> **⚠️ Reconsider vs OpenClaw (Part 6).** OpenClaw is a general-purpose sandboxed agent that can already reason over the research corpus and DB. Before building W4b, reassess whether the dynamic-reasoning need is better served by OpenClaw (with curated read-only tools) than by extending the bespoke `straitsagent` planner — to avoid maintaining two overlapping agent reasoning stacks. Decision deferred until OpenClaw is live.

### What's Live — W4a Static Planner

`planner.py` generates linear tool sequences for `portfolio_analysis`, `thesis_check`, `macro_brief`. Sequential plan → execute → synthesise. No iteration, no feedback loops.

### W4b — Dynamic ReAct Loop 🔲

**What changes:** The `MULTI_STEP` branch gets an iteration controller. The LLM decides at runtime which tools to call, in what order, and when it has enough information to answer.

**Why sequence it here:** A ReAct loop today hits all three broken seams — no idea pipeline, no replacement candidates, terminal verdicts. After Parts 2–3, the same loop can answer "what should I be moving into instead of BABA?" end-to-end without human bridging.

**Architecture (medium change — not a rewrite):**
- Slots into existing `MULTI_STEP` branch in `main.py`
- Reuses all `FAST_EXECUTORS` as the tool interface (no new tool contracts)
- Adds: iteration controller, per-step token accounting, stopping condition (LLM emits `{"action": "final_answer", ...}` structure vs `{"action": "tool_call", ...}`)
- Max-steps guard (5 tool calls) to prevent runaway loops
- Reasoning model: Grok-4.3 (Deepseek handles classification only)

---

## Part 5 — Infrastructure & Hygiene

Fast, low-risk items. Run these before or in parallel with the main build sequence.

### Affection Bot Separation ✅ done (2026-06-26)

The hourly affection ping now runs on its own Telegram bot (`StraitsAffectionBot`) via `u/admin/affection_bot_token`. No code change — one schedule-arg edit live-verified with a one-off run. See `docs/logs/2026-06-26_affection-bot-split.md`.

### Schedule-Drift Reconciliation ✅ done (2026-06-25)

Resolved: see `docs/logs/2026-06-25_schedule-drift-reconcile.md`.

### Empty Table Decisions

| Table | Rows | Recommended action |
|---|---|---|
| `portfolio_thesis` | 33 rows | ✅ Resolved 2026-06-26 — Grok-4.3 auto-draft seeder from research_reports. Write-if-absent. See log. |
| `earnings_surprises` | 132 rows / 33 tickers | ✅ Resolved 2026-06-26 — yfinance column-detection bug fixed; `lxml` added to lock; backfilled. See log. |

### Macro Daily Push — Formal Disposition ✅ Done (2026-06-26)

Parked: schedule removed (server + disk). `macro_daily_push.py` and its tests retained. Formatter `macro_daily_push_telegram.py` stays live — dispatched by `macro_research`. See log.

### API Health Monitor 🔲 (lower priority)

Weekly (Sunday evening). Tests all key external API endpoints. Logs to `api_health_log`. Emails on degradation. Reference: `docs/audit/260605_api_endpoint_full_audit.md`.

---

## Part 6 — OpenClaw Sandboxed Assistant ✅ Live (2026-06-27)

A self-hosted, owner-only AI agent runtime (`openclaw` container, model `openai/gpt-5.4-mini`, bot `@StraitsClawBot`) running as a **sandboxed assistant**: it can run code and write files only inside its own throwaway container workspace, with **no /root access and no secrets**, **read-only** access to the research corpus + Postgres, reachable only by the owner over Telegram polling. Security is the primary design driver — the container is treated as potentially compromised at all times (LLM-driven shell + indirect-prompt-injection surface), so the worst case is "read research the owner already owns + burn the API key."

**Plans (both `Status: done`):** [`docs/plans/2026-06-27_openclaw-secure-deployment.md`](plans/2026-06-27_openclaw-secure-deployment.md) (HIGH-tier; reviewed by opencode/Deepseek-V4) + [`docs/plans/2026-06-27_secrets-consolidation.md`](plans/2026-06-27_secrets-consolidation.md). Implementation logs in `docs/opencode/2026-06-27_openclaw-implementation-log.md` + `docs/logs/2026-06-27_secrets-consolidation.md`. Independently re-verified live: LOCKED ORACLE 5/5, verify script all-PASS, DB privilege enforcement confirmed.

**Containment design (the security spine — all confirmed live):**
- **Network isolation** — two dedicated networks: `root_openclaw_egress` (internet for LLM/Telegram/web) + `root_openclaw_db` (`internal: true`, shared only with `portfolio_postgres`). Never joins `root_default` → never reaches the privileged `dind:2375` container-escape vector or the Windmill control plane (probe-verified unreachable).
- **Container hardening** — non-root (`1000:1000`), `read_only` rootfs + `/tmp` tmpfs, `cap_drop: [ALL]`, `no-new-privileges`, `mem_limit: 1g` / `pids_limit: 256`. Only the Control UI is published, on **loopback `127.0.0.1:18789`** (SSH-tunnel access only — not externally reachable).
- **Data scope** — `/research:ro` + `/config:ro` + writable `/workspace` only (the `/docs` mount was **revoked** to shrink read surface); a `openclaw_ro` Postgres role with an **explicit `GRANT SELECT` allowlist** over 24 research/quant/market tables, deliberately excluding `key_management`, `agent_*`, `telegram_outbox`, `affection_outbox` (PII/secrets). Reads + PII/secret denials confirmed by privilege.
- **Secrets** — consolidated to `/root/secrets/` (mode 700); `openclaw.env` (Telegram token + LLM key + `openclaw_ro` DSN) carries no host secrets; env hygiene verified (only the 3 intended vars in-container).
- **Channel** — dedicated Telegram bot, long-polling, `allowFrom = [owner chat_id]`. No Caddy route, no webhook, no public inbound exposure. Second-sender rejection confirmed.

**Phasing (delivered):** Phase 0 hardening + Phase 1 deploy ✅; Phase 2 was split per review — **secrets consolidation ✅ done** (`/root/secrets/` 700), **research relocation** deferred to its own future plan (needs a git-tracking story for 104 tracked files), **docs relocation dropped** (no security value — openclaw's `/docs` access revoked instead).

**Relationship to other parts:** overlaps Part 4 (ReAct) — see the warning there; the dynamic-reasoning approach is to be reconsidered now that OpenClaw is live. Distinct from the existing `straitsagent` Telegram agent (Part 1), which remains the portfolio-advisor front-end.

**Status:** ✅ Live. Follow-up: research-relocation plan (own design); optional functional test of web-browse capability (the `browser-automation` skill is disabled by the read-only `/config` mount).

---

## Part 7 — Hermes Agent (Nous Research) ✅ Live (2026-06-28)

A self-improving autonomous agent — **confined sandbox (Model A)** alongside OpenClaw.
Container `hermes`, bot `@StraitsHermesBot`, model `deepseek/deepseek-v4-pro`
via OpenRouter (owner-only Telegram polling). Read+write scratch in
`/research/hermes` and `/docs/hermes`; parent trees read-only. `terminal.backend:
local` inside the hardened container (no Docker socket, no dind).

**Containment (mirrors OpenClaw's security spine):**
- **Network isolation** — two dedicated networks: `root_hermes_egress` (internet for
  LLM/Telegram) + `root_hermes_db` (`internal: true`, shared only with
  `portfolio_postgres`). Never reaches `dind:2375` or the Windmill control plane.
- **Container hardening** — non-root (`1000:1000`), `read_only` rootfs + `/tmp` tmpfs,
  `cap_drop: [ALL]`, `no-new-privileges`, `mem_limit: 1g` / `pids_limit: 256`.
  No published ports.
- **Data scope** — `/research:ro` + `/docs:ro` with `/research/hermes:rw` and
  `/docs/hermes:rw` nested scratch folders. Config and `.env` live on the `/workspace` state volume — writable by design (Hermes persists model switches and runtime state across sessions; sandbox controls are the security boundary).
  `hermes_ro` Postgres role (24-table SELECT allowlist, same as `openclaw_ro`).
- **Secrets** — OpenRouter API key + Telegram bot token + `HERMES_RO_DSN` + 6 web-search API keys (Brave, Tavily, Exa, Firecrawl, Serper, Perplexity — added 2026-06-28/29) in
  `/root/secrets/hermes.env` (600, gitignored).
- **Channel** — dedicated Telegram bot, long-polling, `TELEGRAM_ALLOWED_USERS` set
  to owner chat ID. No Caddy route, no webhook, no public inbound exposure.

**Self-managed cron jobs (owner-approved):** Hermes runs three of its own scheduled jobs (managed in its `/workspace` state, **not** the host crontab): a daily World Cup 2026 briefing, a daily portfolio health check (read-only SQL via `HERMES_RO_DSN`), and a cron dispatch monitor that watches its own jobs. All deliver to the owner over Telegram.

**Status:** ✅ Live and in active daily use, alongside OpenClaw.

### SSH Backend — Sandbox VPS 🔲 (approved 2026-06-29, executing tomorrow)

Hermes cannot install system packages at runtime due to `read_only` rootfs (by design). The hermes-agent SSH backend (verified in v0.17.0 source: `tools/environments/ssh.py`) routes all terminal/file execution over ControlMaster SSH to a **separate, disposable sandbox VPS** — giving Hermes full sudo on the sandbox while the main VPS is never touched.

- **Config:** `TERMINAL_ENV=ssh` + `TERMINAL_SSH_HOST/USER/KEY` in `hermes.env`; `openssh-client` added to Dockerfile; dedicated ed25519 key in `/workspace/.ssh/id_hermes` (persists in hermes_state volume)
- **Sandbox:** Cheap VPS (Hetzner CPX11 ~€3.29/mo), `hermes` user with sudo, no firewall route back to main VPS
- **Security:** Dedicated SSH key only; if sandbox is compromised, rebuild it — main VPS unaffected
- **Plan:** [`docs/plans/2026-06-29_hermes-ssh-backend.md`](plans/2026-06-29_hermes-ssh-backend.md) — requires user to provision sandbox VPS first (P1–P3)

### Integration Roadmap 🔲 (approved 2026-06-29)

Hermes has proven useful enough to graduate from A/B trial to a planned **integration layer**. The approved parent roadmap — [`docs/plans/2026-06-29_hermes-integration-roadmap.md`](plans/2026-06-29_hermes-integration-roadmap.md) — sequences three workstreams under **seven non-negotiable security invariants** (the sandbox is never weakened: Hermes stays read-only + off the `root_default`/`dind`/Windmill networks; no Docker socket; PII/secret tables stay denied; **analysis-only — no job dispatch**).

- **WS-A — System visibility 🟡 (partially delivered 2026-06-30)** Producers running *outside* the sandbox push Windmill job-health + container/system-health JSON into `/research/system/` (which Hermes already reads `:ro`). Reuses `health_check.py` + the `drive-backup.timer` host-timer pattern. **The Hermes container spec does not change** — LOCKED ORACLE O1–O8 still pass verbatim. Delivered: host collector writes vps_health.json every 30min; health_check reads it and surfaces VPS + backup status in email and canonical .md.
- **WS-B — Analysis takeover 🔲** Clean producer/interpreter split: Windmill schedules + StraitsAgent keep *producing* artifacts and *dispatching* jobs; Hermes becomes the *interpreter*. StraitsAgent keeps webhook routing, confirmations, transactional commands (`/portfolio`, `/prices`, `/health`, `/thesis` write) and all Windmill dispatch. Overlapping analytical commands (`/analyze`, `/macro`, `/deepresearch`, and the interpretation half of `/research` `/rationalize` `/candidate`) soft-deprecate over three reversible, usage-gated phases. **First increment delivered 2026-06-29:** 4 automations stopped from pushing Telegram (macro_research, morning_news_digest, portfolio_email, youtube_monitor); YouTube cadence daily 18:00 SGT with email-only delivery. ([`docs/plans/archive/2026-06-29_rationalise-straitsagent-pushes.md`](plans/archive/2026-06-29_rationalise-straitsagent-pushes.md))
- **WS-C — Research `.md` quality 🔲** Overhaul the corpus Hermes reads: one unified machine-parseable front-matter schema, recency/staleness metadata, cross-file linking (extend `/research/index.json`), and structured metric tables in prose. Schema-design + sign-off first (Hard Rule 18 contract migration), then `macro_research` as the reference script, then roll-out — each script pairing formatter + round-trip test in one commit.

Recommended order: **WS-A → WS-C → WS-B**. Each workstream spawns its own `EXECUTOR_CONTRACT`-compliant child plan when picked up.

### The Reflexive Alpha System 🔲 (draft 2026-06-29) — the overarching objective

The integration roadmap above wires Hermes *into* the stack. This parent roadmap sets the **why**: build an institutional-grade investment research and portfolio management system that reliably generates alpha, by making the stack **self-improving**. Three agents, each with a complementary strength: **Hermes = always-on conscience** (observes outputs, critiques against an institutional rubric, self-improves via `background_review`); **Claude Code = stateless hands** (builds/fixes anything, plan-driven, artifact-tested); **owner = director** (sets objective, approves). The keystone is **WS-1: a Hermes→Claude feedback channel** (dated docs in `/docs/hermes/feedback/` → read at my SessionStart) that closes the broken loop edge where the human currently relays Hermes' observations by hand. Then WS-2 (institutional review rubric as a Hermes skill), WS-3 (= integration WS-C corpus quality), WS-4 (heavy risk analytics via the SSH sandbox), WS-5 (the four institutional pillars, prioritised *by the loop itself*). The channel is a **suggestion channel, never imperative** (INV-8) and **injection-contained** (INV-9): Hermes suggests, nothing is implemented without the director and I discussing it first, then I build through the normal gated pipeline. Producer runs **daily**; feedback documents are dated (append-only audit trail). ([`docs/plans/2026-06-29_reflexive-alpha-system.md`](plans/2026-06-29_reflexive-alpha-system.md), building on Hermes' own [`docs/hermes/2026-06-28_institutional-grade-roadmap.md`](hermes/2026-06-28_institutional-grade-roadmap.md))

## Deleted / Parked

### Professional Intelligence — REMOVED

The APAC deal tracker, sponsor news monitor, and LNG spread alert have been **removed from the roadmap**. These were never built and are not relevant to the personal portfolio advisor focus.

Deleted items (will not be built):
- 5.1 APAC Infrastructure Deal Tracker (IJGlobal/PFI/Infralogic RSS)
- 5.2 Sponsor News Monitor (KKR, Actis, DigitalBridge, Macquarie, Stonepeak, Brookfield)
- 5.3 LNG Price & Spread Alert (JKM vs TTF + Henry Hub)

If professional intelligence becomes relevant again, start a new plan from scratch — do not restore these items.

### Productivity Workflows — Parked (low priority)

Revisit only after the portfolio advisor track is materially complete:
- Weekly Agenda Prep (Google Calendar → email, Sunday 7PM SGT)
- Chess Puzzle Reminder (daily 9PM SGT, Lichess link)
- Reading List Digest (Google Sheets → weekend digest, Friday 6PM SGT)
- LinkedIn Post Reminder (Monday 8AM SGT, topic from week's headlines)

### Other Parked Items

| Item | Why parked |
|---|---|
| F3 — Signal Collection | Superseded by Initiative A (structured idea extraction from scans) |
| F4 — Stock Idea Generator | Superseded by Initiatives A + B |
| Deep Stock Analysis / Buy-Hold Tool | Requires article scraping; some sources block. Revisit as standalone tool when needed |
| W5/W6 staging model (Persistent Memory / Portfolio Advisor Mode) | The W-series stage model served bootstrapping. These goals are now absorbed into the coherent advisor build (Parts 2–4) |
| W-Business — Business-Facing Agent | Not planned |
| WhatsApp transport | Switched to Telegram due to LID protocol issues. Revisit via hosted bridge if needed |
| Part 4 Agent Data Sources (old) | Earnings Surprise Tracker + Financial Statement Quarterly Pull are now handled by research_tool / stock_data_fetcher. Revisit as scheduled batch fetcher if gaps emerge |

---

## Reference

### Research Files

| File | Contents |
|---|---|
| `docs/audit/260616_full_codebase_audit.md` | Full codebase audit (2026-06-16) — 30 findings across 4 phases |
| `docs/audit/260616_audit_remediation_record.md` | Remediation record — all 30 findings resolved same-day; 2 pending user action |
| `docs/audit/260605_fundamentals_api_audit.md` | 3.0: confirmed field-by-field source mapping, live test results |
| `docs/audit/260605_api_endpoint_full_audit.md` | Full endpoint audit: news, earnings, financials, macro, commodities, insider |
| `docs/audit/260612_search_api_audit.md` | Search API audit — all available APIs, pricing, live tests, recommendations |
| `docs/design/2026-06-13_portfolio-rationalization-framework.md` | Full design spec: 5-factor scoring model, 4 weighting scenarios, per-position scorecard |
| `docs/design/2026-06-15_portfolio-candidate-eval-framework.md` | Full design spec v1.1: 3-gate candidate evaluation, ADD/WATCH/PASS verdict |

### Key Paths

| Path | Purpose |
|---|---|
| `/root/windmill/u/admin/` | All Windmill scripts — git source of truth |
| `/root/agent/` | Telegram agent service (Docker: `straitsagent`) |
| `/root/portfolio/schema.sql` | Full DB schema — authoritative table list |
| `/root/agent.env.example` | Env template for agent service |
| `/root/secrets/keys.md` | All API keys (chmod 600, never commit) |
| `/root/shared/override_log.md` | Manual intervention log |
| `docs/WORKFLOW_ARCHITECTURE.md` | Full pseudocode spec for every workflow |
| `docs/TESTING.md` | Artifact-driven testing philosophy |
| `docs/OPERATIONS.md` | Operational runbooks: credential restore, schedule push, Docker rebuild |
| `/root/research/news/` | Morning digest .md files — `YYYY-MM-DD.md` |
| `/root/research/youtube/` | YouTube digest .md files — `YYYY-MM-DD_HHMM.md` per run |
| `/root/research/portfolio/` | Portfolio email .md files — `YYYY-MM-DD_{am\|pm}.md` |
| `/root/research/macro/` | Macro research .md files |
| `/root/research/earnings/` | Earnings analysis .md files — `YYYY-MM-DD_{TICKER}_{pre\|post}.md` |
| `/root/research/index.json` | Research file manifest — used by dashboard and agent file-serve |

### Windmill Resources

All variables and resources are in the `u/admin` workspace. Credentials from `/root/secrets/keys.md`.

| Path | Type | Purpose |
|---|---|---|
| `u/admin/deepseek_key` | variable | Deepseek API key — `deepseek-v4-flash` |
| `u/admin/rapidapi_key` | variable | RapidAPI key — YouTube transcripts |
| `u/admin/youtube_feeds` | variable | JSON array of 37 YouTube channels |
| `u/admin/youtube_processed_state` | variable | Dedup state — `{processed: [...], attempts: {...}}` |
| `u/admin/portfolio_db` | resource (postgresql) | Portfolio DB — host: `portfolio_postgres`, db: `portfolio` |
| `u/admin/gmail_smtp` | resource (smtp) | Gmail SMTP — `straitsagent@gmail.com` |
| `u/admin/finnhub_key` | variable | Finnhub API key |
| `u/admin/perplexity_key` | variable | Perplexity Search API key |
| `u/admin/xai_key` | variable | xAI/Grok API key (grok-4.3) |
| `u/admin/exa_key` | variable | Exa neural search API key |
| `u/admin/telegram_bot_token` | variable | Main agent Telegram bot token |
| `u/admin/affection_bot_token` | variable | Affection ping bot token (separate from main agent) |
| `u/admin/wm_token` | variable | Windmill API token — job dispatch |
| `u/admin/serper_key` | variable | Serper.dev API key |
| `u/admin/tavily_key` | variable | Tavily Search API key |
| `u/admin/brave_key` | variable | Brave Search API key |
| `u/admin/fred_key` | variable | FRED API key — macro data |
| `u/admin/recipient_email` | variable | Default report recipient email |
| `u/admin/telegram_owner_id` | variable | Owner Telegram chat ID |
| `u/admin/affection_group_id` | variable | Telegram group chat_id for affection sticker pings |
| `u/admin/affection_sticker_packs` | variable | Comma-separated sticker pack names (11 packs) |

### Database Tables (33 total)

The authoritative schema is `/root/portfolio/schema.sql`. Groups below are approximate:

| Group | Tables |
|---|---|
| Portfolio core (4) | `portfolio_positions`, `price_history`, `fx_rates`, `fundamental_data` |
| Advisor / scoring (2) | `portfolio_scores`, `portfolio_candidate_evals` |
| Research (2) | `research_reports`, `research_metadata` |
| Stock quant data (13) | `company_profiles`, `financial_statements`, `valuation_data`, `ownership_data`, `insider_transactions`, `earnings_calendar`, `management_data`, `peer_comparisons`, `stock_snapshots`, `income_statements`, `balance_sheets`, `cash_flow_statements`, `financial_health` |
| Earnings (2) | `earnings_analyses`, `earnings_surprises` |
| Agent (8) | `agent_conversation_history`, `agent_kv`, `portfolio_thesis`, `telegram_outbox`, `affection_outbox`, `watchlist_candidates`, `agent_memory`, `agent_sessions` |
| Macro (2) | `macro_summaries`, `macro_research` *(or similar — verify against schema.sql)* |
| Planned (not yet created) | `watchlist_ideas` (Part 2A/C), `valuation_percentiles` (Part 2D), `risk_matrix` (Part 2D), `factor_exposures` (Part 2D) |

### Telegram Formatter Architecture (md-driven)

Every Windmill notification uses a **canonical markdown → dedicated formatter** pattern:

1. **Main script** writes `/research/<type>/<date>.md`: JSON front-matter + ≥500-word narrative + `<!-- DETAIL -->` separator.
2. **`<name>_telegram.py` formatter** reads the `.md`, builds the ≥500-word self-contained Telegram message, sends via the shared sender, logs to `telegram_outbox`.

| Formatter Script | Main Script | Status |
|---|---|---|
| `u/admin/macro_daily_push_telegram` | `u/admin/macro_daily_push` | ⚠️ Retained — main script disabled; dispatch by `macro_research` also retired 2026-06-29 |
| `u/admin/portfolio_email_telegram` | `u/admin/portfolio_email` | ⚠️ Retained on disk — dispatch removed 2026-06-29 (Hermes will consume `.md`) |
| `u/admin/portfolio_review_telegram` | `u/admin/portfolio_review` | ✅ Live |
| `u/admin/portfolio_rationalization_telegram` | `u/admin/portfolio_rationalization` | ✅ Live |
| `u/admin/portfolio_move_monitor_telegram` | `u/admin/portfolio_move_monitor` | ✅ Live |
| `u/admin/portfolio_analyst_alert_telegram` | `u/admin/portfolio_analyst_alert` | ✅ Live |
| `u/admin/health_check_telegram` | `u/admin/health_check` | ⚠️ Retained on disk — dispatch removed 2026-06-30 (system monitor; Telegram retired) |
| `u/admin/youtube_monitor_telegram` | `u/admin/youtube_monitor` | ⚠️ Retained on disk — dispatch removed 2026-06-29 (Hermes will consume `.md`) |
| `u/admin/position_sentinel_telegram` | `u/admin/position_sentinel` | ✅ Live (9th formatter) |
