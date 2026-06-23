# Automation Stack Roadmap

**Last updated:** 2026-06-23 (testing framework gap analysis applied — ASD convention, Testing Critic Hard Rule 20, Tier 0 production artifact verification — 625 tests passing)
**Owner:** ${OWNER_NAME}

> **Architecture specs:** Full pseudocode for every workflow lives in [`WORKFLOW_ARCHITECTURE.md`](WORKFLOW_ARCHITECTURE.md).

---

## Objective

Build a personal automation stack that thinks about your portfolio, monitors your markets, and is available on Telegram whenever you need it. The long-term target is a **sophisticated multi-tool reasoning agent** that acts as a portfolio advisor — not a query interface, but a counterpart that understands your positions, your thesis on each one, and the macro environment you're operating in.

The stack has two layers:
1. **Data & intelligence infrastructure** — Windmill scripts that collect, process, and store financial data on the VPS
2. **The Telegram agent** — a reasoning interface that queries this infrastructure and synthesises answers

---

## Guiding Principles

- **The agent is the delivery interface.** Telegram is where you interact. Email continues for scheduled digests, but the agent becomes the primary way to get intelligence from the stack.
- **Data richness enables agent sophistication.** Every data source added to the Postgres layer is a new capability for the agent. Build data infrastructure in service of agent tools, not as standalone email workflows.
- **Ship fast.** Each workflow should be buildable in a single Claude Code session.
- **One change at a time.** Build, test, deploy — then move to the next.
- **Email for scheduled automation; agent for on-demand reasoning.** The two modes complement each other — digests run unattended, agent answers the questions they raise.

---

## Part 1 — What's Running

Everything below is live and running unattended.

### Foundation
- Windmill at `http://<YOUR_VPS_IP>:8080` — Python scripts, cron schedules, resource system
- PostgreSQL (`portfolio_postgres`) — schema applied, 33 positions seeded
- GCP service account — Drive + Sheets APIs enabled
- Windmill resources: `u/admin/gmail_smtp`, `u/admin/portfolio_db`, `u/admin/deepseek_key`, `u/admin/rapidapi_key`, `u/admin/finnhub_key`, `u/admin/perplexity_key`, `u/admin/xai_key`, `u/admin/exa_key`

### Daily Intelligence
| Workflow | Schedule | Notes |
|---|---|---|
| 1.1 Morning News Digest | 6:30 AM SGT daily | RSS (WSJ/Reuters/NYT) + newsletter AI summaries. Recipients: <YOUR_RECIPIENT_EMAIL>, <YOUR_WORK_EMAIL> |
| 1.2 YouTube Channel Monitor | Every 6 hours | 37 channels, RapidAPI transcripts, Deepseek summaries, 3-retry logic |

### Portfolio System
| Component | Schedule | Notes |
|---|---|---|
| 2.1 Daily Price Fetcher | 5:45 AM + 5:45 PM SGT | yfinance EOD prices + USDHKD FX rate → `price_history`, `fx_rates` |
| 2.2 Portfolio Email | 6:00 AM + 6:00 PM SGT | ADR consolidation, top movers, Google News per mover |
| 2.3 Weekly Portfolio Review | Saturday 8:00 AM SGT | Week P&L, Finnhub news, Deepseek commentary |
| 2.4 Move Monitor | Hourly, Mon–Fri (HK + US sessions) | Alert on portfolio ±1.5% or position ±5% |
| 3.1 Fundamentals Fetcher | Sunday 6:00 PM SGT | Finnhub + yfinance → `fundamental_data` (P/E, targets, margins, ROE, ROIC) |
| 3.3 Portfolio Rationalization | **Weekly Monday 9PM SGT** (+ on-demand) | ✅ **Live.** 5-factor scoring × 4 scenarios, absolute red flags, completeness penalty, delta tracking, 2× Grok-4.3 calls + deepseek fallback. Optional `include_research=True` adds full LLM research reports into Grok Call 2 (deep mode). Script: `u/admin/portfolio_rationalization`. Table: `portfolio_scores`. Telegram: `portfolio_rationalize` / `deep rationalize`. Schedule: `u/admin/portfolio_rationalization_monthly`. See [`docs/portfolio_rationalization_framework.md`](portfolio_rationalization_framework.md) |
| 3.4 Portfolio Candidate Eval | On-demand (Telegram: `evaluate TICKER`) | ✅ **Live.** 3-gate ADD/WATCH/PASS verdict. **Auto-fetch**: dispatches `stock_data_fetcher` if quant data absent/stale (>3d), then dispatches `research_tool` if no recent stock report (>30d). Waits for DB confirmation before evaluating. Full research report included in Grok prompt if available. Script: `u/admin/portfolio_candidate_eval`. Table: `portfolio_candidate_evals`. |

### Research & Tools
| Component | Notes |
|---|---|
| Research Tool (`u/admin/research_tool`) | Manual trigger or via Telegram commands. stock/strategy/macro/project × brief/standard/deep. All depths: Google News + Perplexity + Serper. Standard+: Tavily (finance, time_range=month) + Brave (freshness=pm) + EDGAR 8-K + Exa (non-stock) + FRED macro data (macro type). Deep: Exa (all types) + EDGAR 10-K/10-Q + agentic gap analysis (Deepseek → routes Round 2 to news/sec/analyst/market_data). Grok-4.3 synthesis, max_tokens=8000 at deep. Stock fundamentals: DB-read first (_read_structured_stock_data) → dispatch stock_data_fetcher on stale/absent → fallback live fetch. ~$0.06/standard, ~$0.20/deep. |
| Stock Data Fetcher (`u/admin/stock_data_fetcher`) | Single-ticker generic data collector. Fetches 8 data types: company profile, 3yr financials (income/BS/CF/health), valuation multiples, ownership, insider transactions, earnings calendar, key management, peer comparisons. Persists to 14 PostgreSQL research tables. No synthesis, no email. Called on-demand by research_tool when data is stale/absent; can also be dispatched standalone or batch-looped by a caller. |

### System
| Component | Notes |
|---|---|
| 6.1 Daily Health Check | **8:00 AM SGT** — 3-layer notifications: (A) Deepseek per-schedule diagnosis on STALE/FAILED, (B) error_alert Telegram+Deepseek on any crash, (C) host deadman (08:30 SGT, systemd, direct Telegram). Content engine: 24h .md collector, per-type spec validators (macro/portfolio/youtube), Grok-4 holistic daily digest (700-1000w, Deepseek fallback). |
| 6.2 Windmill Error Alert | On failure — email + **Telegram** + Deepseek 1-line diagnosis |

### Telegram Agent W1
| Component | Status |
|---|---|
| Agent service (`/root/agent/`, FastAPI + Docker) | ✅ Live — `root-straitsagent-1` on `agent_net`. Bot: `@<YOUR_BOT_USERNAME>` |
| HTTPS webhook route | ✅ Live — `https://<YOUR_DOMAIN>/webhook/telegram` → Caddy → `straitsagent:8001` |
| DB schema (6 agent tables) | ✅ Applied to `portfolio` DB |
| Intent routing (Deepseek `deepseek-chat`) | ✅ 18 intents (W1) + 8 W2/W4 intents. 5 latency classes. Slash commands stripped. Pre-classifier shortcut for `/stockresearch`, `/research`, `/deepresearch` (0 classifier tokens). Single-word shortcuts + W2/W4 disambiguation. |
| Tool registry | FAST: portfolio_snapshot, portfolio_digest, ticker_detail, live_prices, health_check, news_digest, youtube_digest, **earnings** (unified — file-serve or Finnhub calendar), news_search, macro_indicators, thesis_read |
| | FIRE: email_summary |
| | ASYNC_NOTIFY: research, earnings_analysis (Windmill dispatch + 5s polling loop; completion sends report file content) |
| | GATED_WRITE: price_refresh, fundamentals_refresh, thesis_write |
| | MULTI_STEP: portfolio_analysis, thesis_check, macro_brief (planner.py — sequential FAST tool chains + Grok synthesis) |
| File-serve digests | ✅ news_digest / youtube_digest / portfolio_digest / **earnings** read from `/research/` — never trigger Windmill. Content >3,500 chars summarised via Deepseek before delivery (earnings: no summarisation, content is already concise). |
| Research tool | ✅ Tiered cache (stock only): <30d serve cached directly (no job); 30–90d dispatch standard; no cache dispatch deep. General commands (/research, /deepresearch) skip cache. Date shown in result header. |
| Message splitting | ✅ Replies >4,000 chars split into ≤4,000-char chunks at newline boundaries |
| Telegram command menu | ✅ 13 commands registered at startup via `set_my_commands()`: stockresearch (deep stock, tiered cache), research (general standard), deepresearch (general deep), earnings, portfolio, prices, news, youtube, macro, thesis, health, search, digest |
| Unit tests | ✅ 353 passing — `agent/tests/` (classifier, telegram, tools, routing, planner, db, schema, windmill scripts). TDD mandatory for ALL code — tests before implementation, live test after deployment. PostToolUse hook prints TDD reminder on every Python edit. |
| Env template | `/root/agent.env.example` (actual `agent.env` gitignored) |

---

## Part 2 — Active: W1 Telegram Agent

The agent is live on Telegram. Remaining setup item:

1. Create "Agent Drafts" Telegram group (owner + @<YOUR_BOT_USERNAME>) → copy group chat_id (negative integer) → `DRAFTS_GROUP_ID` in `/root/agent.env` → `docker compose up -d straitsagent`

---

## Part 3 — Agent Sophistication Roadmap (Primary Priority)

W1 is a **router with a chat interface** — it pattern-matches each message to a pre-defined tool, executes it once, and returns the result. The LLM makes exactly one decision per message (which tool) and then steps aside. It does not reason over results, chain tools, or synthesise across sources.

The stages below are the path from router to reasoning agent. W4 is the architectural inflection point — everything before it extends the current dispatch architecture. W4 is where the agent starts to plan dynamically.

---

### W2 — Tool Expansion ✅ COMPLETE

**What changes:** The router gets better-equipped. More tools so a wider range of questions get a direct answer instead of "not yet implemented."

**Architecture unchanged** — still classify → dispatch → return.

**Tools added (live):**

| Tool | Source | Status |
|---|---|---|
| `thesis_read` / `thesis_write` | `portfolio_thesis` Postgres table | ✅ Live — FAST read + GATED_WRITE upsert |
| `earnings` (unified) | `/research/earnings/` files + Finnhub fallback | ✅ Live — `/earnings ADBE` serves stored analysis file; `/earnings` shows Finnhub 14-day calendar. Replaced `earnings_calendar`. |
| `news_search` | Exa neural search API | ✅ Live — top 5 results with summaries |
| `macro_indicators` | Yahoo Finance v8 API | ✅ Live — SGD/USD, HKD/USD, VIX, Brent, UST 10Y |

**Why now:** Tool richness makes every subsequent stage more useful. By W4 the ReAct loop can only plan with what's in the tool registry — the more that's there, the more the agent can actually do.

---

### W3 — Proactive Alerts ✅ COMPLETE

**What changes:** Windmill-native scheduled scripts send Telegram alerts and trigger deep analysis jobs. Pattern: same as `portfolio_move_monitor.py` but Telegram + full earnings intelligence.

**Scripts live:**

| Script | Trigger | What it does |
|---|---|---|
| `portfolio_earnings_alert.py` | 9 PM SGT Mon–Fri | EPS surprise alerts; dispatches pre-earnings analysis job when upcoming earnings detected |
| `portfolio_analyst_alert.py` | 7:45 AM SGT daily | Analyst rating upgrades/downgrades, dedup via `agent_kv` |
| `portfolio_earnings_analysis.py` | Dispatched by alert/agent | Pre-earnings briefing OR post-earnings analysis with recommendation. EDGAR 8-K + Exa transcripts + yfinance + Grok-4.3. Output includes: date header, portfolio position (shares/value/weight), research synopsis (or seeded overview), sources list, token/cost footer. Writes to `/research/earnings/YYYY-MM-DD_{TICKER}_{pre\|post}.md`. Saves to `earnings_analyses` DB table. Emails `<YOUR_RECIPIENT_EMAIL>`. |
| `portfolio_earnings_post_check.py` | 7 AM SGT daily | Checks Finnhub for epsActual populated in last 3 days; dispatches post-earnings analysis if no existing `earnings_analyses` record |

**Windmill variables:** `u/admin/telegram_bot_token`, `u/admin/wm_token` (for job dispatch).

**DB table:** `earnings_analyses` (ticker, analysis_type, earnings_date, eps_estimate, eps_actual, revenue_estimate, revenue_actual, surprise_pct, recommendation, content, file_path).

---

### W4a — Static Multi-Step Planner ✅ COMPLETE

**What's live:** `planner.py` — `plan()` generates tool sequences; `synthesise()` unifies results. Three multi-step intents: `portfolio_analysis`, `thesis_check`, `macro_brief`. Dispatched via `MULTI_STEP` class in `main.py`. Falls back to single tool if planner fails.

### W4b — Dynamic ReAct Loop 🔲 NOT STARTED

**This is the architectural inflection point.** The agent reasons dynamically instead of matching to a pre-defined tool. The single Deepseek classification call is replaced by a reasoning loop:

```
Think: what information do I need to answer this?
Act:   call a tool
Observe: see the result
Think: is this enough? what do I need next?
Act:   call another tool (or stop)
Answer: synthesise everything
```

The LLM drives the loop — it decides at runtime which tools to call, in what order, and when it has enough information to answer.

**What this unlocks:**
- Questions that can't be anticipated at design time. New tools added to the registry become available to the agent without writing new dispatch logic.
- "Should I be worried about my China exposure given the tariff situation?" — agent pulls portfolio data, decides it needs macro context, fetches it, decides it needs recent news, fetches that, synthesises all three.
- Handling ambiguous or open-ended questions.

**Architecture changes required:**
- Replace Deepseek single-classification call with a reasoning loop
- Use a stronger model for the loop — Grok-4.3 or equivalent (Deepseek is fast but weaker at multi-step planning)
- Tool results injected back into LLM context as "observations"
- Stopping condition: LLM emits a "final answer" token/structure instead of another tool call
- Max-steps guard (e.g. 5 tool calls) to prevent runaway loops
- **This is the stage where LangGraph pays for itself** — it handles the loop mechanics, state tracking, and tool call parsing cleanly. Before W4, LangGraph adds overhead with no benefit; at W4, it earns its place.

---

### W5 — Persistent Memory & Proactive Reasoning 🔲

**What changes:** The agent stops being purely reactive.

**Richer memory.** Beyond conversation history, the agent maintains structured context per position (thesis, prior research, stated concerns) and per interaction pattern (what you ask about frequently, decisions you've made). This gets injected into every ReAct loop as standing context — "you've noted a concern about BABA's regulatory risk" or "you researched NVDA three times this week."

**Proactive alerts.** A scheduled reasoning job (not triggered by a message) runs periodically and notices things:
- A holding moves >5% intraday + earnings in 3 days → sends unprompted brief
- You haven't looked at a position >5% of portfolio in >30 days → nudge
- A macro event you care about (LNG, China policy) gets significant coverage → morning brief via WhatsApp

**Architecture changes required:**
- `agent_position_context` table (thesis, concerns, last-researched date per ticker) — already in W2 prerequisites
- Structured preference/pattern extraction into enriched `agent_conversation_history`
- Scheduled Windmill job or agent cron for the proactive reasoning pass
- Memory injection into the ReAct loop prompt

---

### W6 — Portfolio Advisor Mode 🔲

**What changes:** The agent has enough context about your portfolio, investment style, and stated views that its answers are genuinely personalised rather than generic data lookups. It stops being a query interface and starts being an analytical counterpart.

**Examples of what becomes possible:**
- "What do you think about my EQNR position?" — agent knows your thesis (energy transition hedge), current price vs average, macro conditions, recent news, and gives you a view rather than just data
- "Draft a weekly investment note on my top 5 positions" — coherent memo-style document, not a data dump
- "I'm thinking of trimming NVDA — talk me through it" — agent has context, pushes back intelligently, flags what you might be missing

**Architecture changes required:**
- Less new architecture; more prompt engineering, memory richness, and context quality
- Dedicated "analyst persona" system prompt encoding your investment style, portfolio philosophy, and key concerns
- Tool for storing and retrieving investment memos (`/root/research/` already handles this)

---

### W-Business — Business-Facing Agent 🔲 NOT PLANNED YET
- Second bot instance for external contacts — scope TBD
- Build after W1 is stable and W2/W3 tool expansion is complete

---

## Part 4 — Agent Data Sources

These are the data feeds that give the agent's tools something to reason over. Framed as agent capabilities, not standalone email scripts.

### Earnings Intelligence
- **4.1 Earnings Surprise Tracker** — Finnhub `/stock/earnings` — daily. Catch beats/misses on portfolio tickers. Feeds `earnings_calendar` tool and W5 proactive alerts.
- **3.2 Financial Statement Quarterly Pull** — yfinance `.income_stmt` / `.balance_sheet` / `.cashflow` — all 33 tickers post-earnings (Feb/May/Aug/Nov). Enables FCF yield, revenue growth trend, debt trajectory per position. Feeds research_tool deep synthesis.

### Market Intelligence
- **4.2 Insider Activity Feed** — Finnhub `/stock/insider-transactions` (US tickers) — Monday mornings. Buys only. Feeds `insider_activity` tool.
- **4.3 SEC 8-K Real-Time Alert** — Finnhub `/stock/filings` — hourly, Mon–Fri market hours. Material events: earnings releases, M&A, CEO changes. Feeds W5 proactive alerts.
- **4.4 Commodity Prices** — Alpha Vantage `WTI`, `BRENT`, `NATURAL_GAS` — weekly, cached in Postgres. Feeds `macro_snapshot` tool. Direct relevance: EQNR exposure.
- **4.5 News Sentiment DB Feed** — Alpha Vantage `NEWS_SENTIMENT` — daily. Store scored articles in `news_sentiment` table: ticker, relevance_score, sentiment_score, source, title, url. Feeds W5 signal layer.

---

## Part 5 — Professional Intelligence

Deal monitoring and market coverage relevant to infrastructure finance. Build after W3 agent stage or as standalone if time permits.

- **5.1 APAC Infrastructure Deal Tracker** — IJGlobal/PFI/Infralogic public RSS — daily. Filter: APAC, data centres, renewables, LNG, power. Email new deals only.
- **5.2 Sponsor News Monitor** — Google News RSS per sponsor (KKR, Actis, DigitalBridge, Macquarie, Stonepeak, Brookfield) — daily.
- **5.3 LNG Price & Spread Alert** — JKM vs TTF + Henry Hub — daily. Alert if spread moves >10% WoW. Feeds both `macro_snapshot` tool and standalone alert email.

---

## Part 6 — System Reliability

- **6.3 API Health Monitor** 🔲 — Weekly (Sunday evening, before 3.1 runs). Tests all key external API endpoints (Finnhub, yfinance, Alpha Vantage). Logs results to `api_health_log`. Emails summary on degradation or failure. Catches silent breakage before it corrupts data. Reference: `docs/audit/260605_api_endpoint_full_audit.md`.

---

## Part 7 — Lower Priority

### Portfolio System Extensions
- **2.5 Advanced Analyses** — Rolling 30-day P&L, portfolio vs SPY/HSI benchmark, sector/geography breakdown, concentration flags
- **P2b Portfolio Email: AI News Analysis** — Deepseek "why did this move?" summary per mover in the % Movers section
- **P2c Portfolio Email: Earnings Preview + Macro Header** — Upcoming earnings (Finnhub, 7-day window) + macro snapshot line (10Y UST / WTI / NG) in email header
- **1.1a Morning Digest: Economic Calendar** — High-impact macro events this week (Finnhub `/calendar/economic`) — Fed, CPI, NFP

### Productivity Workflows
- **7.1 Weekly Agenda Prep** — Google Calendar pull → clean agenda email, Sunday 7 PM SGT
- **7.2 Chess Puzzle Reminder** — Daily 9 PM SGT, direct Lichess link
- **7.3 Reading List Digest** — Google Sheets reading list → weekend digest, Friday 6 PM SGT
- **1.3 LinkedIn Post Reminder** — Monday 8 AM SGT, suggested P2I topic from week's headlines

---

## Parked

| Item | Why parked |
|---|---|
| F3 — Signal Collection | Deprioritised in favour of research_tool. Revisit when agent needs structured signal input. |
| F4 — Stock Idea Generator | Requires F3 first. |
| Deep Stock Analysis / Buy-Hold Tool | Full article scraping needed; some sources block scrapers; may need paid news API. Design as standalone tool when ready. |
| Old Portfolio Analysis Agent spec | Superseded by W-series agent + research_tool. |
| WhatsApp transport | Switched to Telegram due to LID protocol issues on the owner's phone. Baileys bridge code removed. Revisit via hosted bridge (Green API ~$15/mo) if needed. |

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
| `docs/portfolio_rationalization_framework.md` | Full design spec: 5-factor scoring model, 4 weighting scenarios, per-position scorecard structure, Grok prompt, schema, schedule |
| `docs/portfolio_candidate_eval_framework.md` | Full design spec v1.1: 3-gate candidate evaluation (Gate 1 red flags + Gate 2 portfolio fit + Gate 3 universe benchmark), ADD/WATCH/PASS verdict, per-factor triplets. Script live: `u/admin/portfolio_candidate_eval`. |

### Key Paths
| Path | Purpose |
|---|---|
| `/root/windmill/u/admin/` | All Windmill scripts — git source of truth |
| `/root/agent/` | Telegram agent service (Docker: `straitsagent`) |
| `/root/portfolio/schema.sql` | Full DB schema including agent tables |
| `/root/agent.env.example` | Env template for agent service |
| `/root/shared/keys.md` | All API keys (chmod 600, never commit) |
| `/root/shared/override_log.md` | Manual intervention log |
| `docs/WORKFLOW_ARCHITECTURE.md` | Full pseudocode spec for every workflow |
| `/root/research/news/` | Morning digest .md files — `YYYY-MM-DD.md` — written by `morning_news_digest.py` |
| `/root/research/youtube/` | YouTube digest .md files — `YYYY-MM-DD_HHMM.md` per run — written by `youtube_monitor.py` |
| `/root/research/portfolio/` | Portfolio email .md files — `YYYY-MM-DD_{am\|pm}.md` — written by `portfolio_email.py` |
| `/root/research/earnings/` | Earnings analysis .md files — `YYYY-MM-DD_{TICKER}_{pre\|post}.md` — written by `portfolio_earnings_analysis.py` |

---

## Windmill Resources

All variables and resources are in the `u/admin` workspace. Credentials come from `/root/shared/keys.md`.

| Path | Type | Purpose |
|---|---|---|
| `u/admin/deepseek_key` | variable | Deepseek API key — model `deepseek-v4-flash` |
| `u/admin/rapidapi_key` | variable | RapidAPI key — YouTube transcripts |
| `u/admin/youtube_feeds` | variable | JSON array of 37 YouTube channels |
| `u/admin/youtube_processed_state` | variable | Dedup state — `{processed: [...], attempts: {...}}` |
| `u/admin/portfolio_db` | resource (postgresql) | Portfolio DB — host: `portfolio_postgres`, db: `portfolio` |
| `u/admin/gmail_smtp` | resource (smtp) | Gmail SMTP — `straitsagent@gmail.com` |
| `u/admin/finnhub_key` | variable | Finnhub API key |
| `u/admin/perplexity_key` | variable | Perplexity Search API key |
| `u/admin/xai_key` | variable | xAI/Grok API key (grok-4.3) |
| `u/admin/exa_key` | variable | Exa neural search API key |
| `u/admin/telegram_bot_token` | variable | Telegram bot token |
| `u/admin/wm_token` | variable | Windmill API token — used by alert/post-check scripts |
| `u/admin/serper_key` | variable | Serper.dev API key ($0.0003/call) |
| `u/admin/tavily_key` | variable | Tavily Search API key (1K free/month) |
| `u/admin/brave_key` | variable | Brave Search API key (1K free/month) |
| `u/admin/fred_key` | variable | FRED API key — macro data |
| `u/admin/recipient_email` | variable | Default report recipient email |
| `u/admin/telegram_owner_id` | variable | Owner Telegram chat ID |
| `u/admin/affection_group_id` | variable | Telegram group chat_id for hourly affection sticker pings (negative int) |
| `u/admin/affection_sticker_packs` | variable | Comma-separated Telegram sticker pack names (default: `BubuDudu`) |

### Telegram Formatter Architecture (md-driven)

Every Windmill notification now uses a **canonical markdown → dedicated formatter** pattern:

1. **Main script** writes `/research/<type>/<date>.md` with: JSON front-matter block + ≥500-word narrative + `<!-- DETAIL -->` separator.
2. **`<name>_telegram.py` formatter** reads the `.md`, builds the ≥500-word self-contained Telegram message, sends via the shared sender, logs full text + writes `telegram_outbox`.

| Formatter Script | Main Script |
|---|---|
| `u/admin/macro_daily_push_telegram` | `u/admin/macro_daily_push` |
| `u/admin/portfolio_email_telegram` | `u/admin/portfolio_email` |
| `u/admin/portfolio_review_telegram` | `u/admin/portfolio_review` |
| `u/admin/portfolio_rationalization_telegram` | `u/admin/portfolio_rationalization` |
| `u/admin/portfolio_move_monitor_telegram` | `u/admin/portfolio_move_monitor` |
| `u/admin/portfolio_analyst_alert_telegram` | `u/admin/portfolio_analyst_alert` |
| `u/admin/health_check_telegram` | `u/admin/health_check` |
| `u/admin/youtube_monitor_telegram` | `u/admin/youtube_monitor` |

**`telegram_outbox` table** — Postgres, every Telegram send logged with: `script_name`, `message_text`, `char_count`, `word_count`, `delivered`, `error`. Index on `sent_at DESC`.

---

## Telegram Agent Build Status

| Component | Status | Notes |
|---|---|---|
| Agent service (FastAPI) | ✅ Live | `/root/agent/` — `root-straitsagent-1`, `agent_net` network |
| Telegram adapter | ✅ Live | `telegram.py` — parse_inbound, send_message (Markdown + 400 retry), verify_signature |
| Webhook HTTPS route | ✅ Live | `https://<YOUR_DOMAIN>/webhook/telegram` → Caddy → `straitsagent:8001` |
| Telegram bot | ✅ Live | Token in `agent.env`, webhook registered with secret token |
| Slash command support | ✅ Live | `/portfolio`, `/research NVDA` etc. — leading `/` stripped before classification |
| DB schema (8 agent tables) | ✅ Applied | `agent_*` tables + `portfolio_thesis` + `agent_kv` in `portfolio` DB |
| Unit tests (pytest) | ✅ 521 passing | `agent/tests/` — classifier, telegram, tools, db.py (16 ops), schema (14 tables), Windmill scripts, W3/W4 coverage, 8 formatter behavioral tests |
| Telegram command menu | ✅ Live | 13 commands: stockresearch, research, deepresearch, earnings, portfolio, prices, news, youtube, macro, thesis, health, search, digest |
| W2 tools: portfolio_snapshot, prices, news_search, macro_indicators, news/youtube/portfolio digest | ✅ Live | FAST class |
| W2 tools: portfolio_thesis (read/write) | ✅ Live | thesis_read (FAST), thesis_write (GATED_WRITE) |
| W3 earnings alert | ✅ Live | `portfolio_earnings_alert.py` — 9 PM SGT Mon–Fri |
| W3 analyst alert | ✅ Live | `portfolio_analyst_alert.py` — 7:45 AM SGT daily |
| W3 earnings analysis (pre + post) | ✅ Live | `portfolio_earnings_analysis.py` — Grok-4.3 synthesis |
| W3 earnings post-check | ✅ Live | `portfolio_earnings_post_check.py` — 7 AM SGT daily (cron `0 0 7 * * *` Asia/Singapore) |
| W4 multi-step reasoning | ✅ Live | `planner.py` — portfolio_analysis, thesis_check, macro_brief intents |
| portfolio_rationalize tool | ✅ Live | ASYNC_NOTIFY — FAST if file ≤30 days; dispatches Windmill otherwise |
| Agent Drafts Telegram group | ⏳ Pending | Create group → add bot → set `DRAFTS_GROUP_ID` in `agent.env` → rebuild container |

---

## Portfolio Rationalization

**Script:** `u/admin/portfolio_rationalization.py` | **Schedule:** Weekly Monday 9PM SGT (+ on-demand via Telegram: `portfolio_rationalize` / `deep rationalize`)

5-factor scoring model (Quality 30%, Growth 25%, Valuation 20%, Sentiment 15%, Thesis 10%) across 4 weighting scenarios (Balanced, Quality-biased, Growth-biased, Value-biased). Absolute red flags trigger automatic Reduce. Completeness penalty for missing data. Delta tracking vs prior run (all 4 scenarios). Batched Grok-4.3 Call 1 (2× 15-position batches) + Grok-4.3 Call 2 synthesis with Deepseek fallback. Optional `include_research=True` adds full LLM research reports into Call 2. Writes to `portfolio_scores` table.

See `docs/portfolio_rationalization_framework.md` v1.2 for full design spec.
