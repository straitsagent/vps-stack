# Weekly Schedule Cycle — All Windmill Jobs

**Generated:** 2026-06-26
**All times in SGT (UTC+8) unless noted**
**17 enabled schedules, 17 distinct workflows**

---

## Monday – Friday

| Time (SGT) | Workflow | Frequency | Notes |
|---|---|---|---|
| 00:00, 06:00, 12:00, 18:00 | YouTube Channel Monitor | Every 6h | 37 channels, RapidAPI transcripts, Deepseek summaries |
| 05:45 AM | Portfolio Price Fetcher (AM) | Daily, 7 days | yfinance EOD prices + USDHKD FX → `price_history`, `fx_rates` |
| 06:00 AM | Portfolio Email (AM) | Mon–Fri | ADR consolidation, top movers, Google News per mover. Email + Telegram |
| 06:30 AM | Morning News Digest | Daily, 7 days | RSS (WSJ/Reuters/NYT) + newsletter AI summaries. Email + Telegram |
| 07:00 AM | Macro Research | Mon–Fri | Perplexity macro scan → Deepseek synthesis → Telegram push |
| 07:00 AM | Portfolio Earnings Post-Check | Daily, 7 days | Checks Finnhub for epsActual; dispatches post-earnings analysis |
| 07:45 AM | Portfolio Analyst Alert | Daily, 7 days | Analyst rating upgrades/downgrades, dedup via `agent_kv`. Telegram |
| 08:00 AM | Daily Health Check | Daily, 7 days | Deepseek diagnosis on STALE/FAILED; Telegram alert on crash |
| 08:00 ↓ 22:00 | Affection Ping | Hourly, 8 AM–10 PM, 7 days | Random sticker (12 packs) + Deepseek caption → Telegram group |
| 09:00 ↓ 16:00 | Portfolio Move Monitor (HK/Asia) | Hourly, Mon–Fri | Alert on ±1.5% portfolio or ±5% position. Telegram |
| 17:45 PM | Portfolio Price Fetcher (PM) | Daily, 7 days | yfinance EOD prices + USDHKD FX → `price_history`, `fx_rates` |
| 18:00 PM | Portfolio Email (PM) | Mon–Fri | ADR consolidation, top movers, Google News per mover. Email + Telegram |
| 21:00 PM | Portfolio Earnings Alert | Mon–Fri | EPS surprise alerts; dispatches pre-earnings analysis job. Telegram |
| 21:00 PM ↓ 04:00 AM+1 | Portfolio Move Monitor (US) | Hourly, Mon–Fri (ET hours) | Alert on ±1.5% portfolio or ±5% position in US session. Telegram |

---

## Saturday (SGT)

| Time (SGT) | Workflow | Frequency | Notes |
|---|---|---|---|
| 00:00, 06:00, 12:00, 18:00 | YouTube Channel Monitor | Every 6h | |
| 05:45 AM | Portfolio Price Fetcher (AM) | Daily | |
| 06:00 AM | **Portfolio Rationalization** | Weekly, Saturday | 5-factor scoring × 4 scenarios, KEEP/TRIM/EXIT. Email + Telegram |
| 06:30 AM | Morning News Digest | Daily | |
| 07:00 AM | Portfolio Earnings Post-Check | Daily | |
| 07:45 AM | Portfolio Analyst Alert | Daily | |
| 08:00 AM | **Weekly Portfolio Review** | Weekly, Saturday | Week P&L, Finnhub news, Deepseek commentary. Email + Telegram |
| 08:00 ↓ 22:00 | Affection Ping | Hourly, 7 days | |
| 17:45 PM | Portfolio Price Fetcher (PM) | Daily | |

---

## Sunday (SGT)

| Time (SGT) | Workflow | Frequency | Notes |
|---|---|---|---|
| 00:00, 06:00, 12:00, 18:00 | YouTube Channel Monitor | Every 6h | |
| 05:45 AM | Portfolio Price Fetcher (AM) | Daily | |
| 06:30 AM | Morning News Digest | Daily | |
| 07:00 AM | Portfolio Earnings Post-Check | Daily | |
| 07:45 AM | Portfolio Analyst Alert | Daily | |
| 08:00 AM | Daily Health Check | Daily | |
| 08:00 ↓ 22:00 | Affection Ping | Hourly, 7 days | |
| 17:45 PM | Portfolio Price Fetcher (PM) | Daily | |
| 18:00 PM (SGT) | **Fundamentals Fetcher** | Weekly, Sunday | Finnhub + yfinance → `fundamental_data` (P/E, targets, margins, ROE, ROIC). Cron: `0 0 10 * * 7 UTC` = 6 PM SGT |

---

## Summary by Workflow

| # | Workflow | Schedule | Per Week |
|---|----------|----------|----------|
| 1 | YouTube Channel Monitor | Every 6h | 28 runs |
| 2 | Portfolio Price Fetcher (AM) | Daily 5:45 AM | 7 runs |
| 3 | Portfolio Price Fetcher (PM) | Daily 5:45 PM | 7 runs |
| 4 | Morning News Digest | Daily 6:30 AM | 7 runs |
| 5 | Portfolio Email (AM) | Mon–Fri 6:00 AM | 5 runs |
| 6 | Portfolio Email (PM) | Mon–Fri 6:00 PM | 5 runs |
| 7 | Macro Research | Mon–Fri 7:00 AM | 5 runs |
| 8 | Portfolio Earnings Post-Check | Daily 7:00 AM | 7 runs |
| 9 | Portfolio Analyst Alert | Daily 7:45 AM | 7 runs |
| 10 | Daily Health Check | Daily 8:00 AM | 7 runs |
| 11 | Affection Ping | Hourly 8 AM–10 PM | 98 runs |
| 12 | Portfolio Move Monitor (Asia/HK) | Hourly Mon–Fri 9 AM–4 PM | 40 runs |
| 13 | Portfolio Move Monitor (US) | Hourly Mon–Fri 9 PM–4 AM (ET hours) | 40 runs |
| 14 | Portfolio Earnings Alert | Mon–Fri 9:00 PM | 5 runs |
| 15 | Portfolio Rationalization | Saturday 6:00 AM | 1 run |
| 16 | Weekly Portfolio Review | Saturday 8:00 AM | 1 run |
| 17 | Fundamentals Fetcher | Sunday 6:00 PM | 1 run |
| | **Total** | | **~271 runs/week** |

---

## Notes

- **Affection Ping dominates volume** — 98 of 271 runs (36%). Hourly from 8 AM–10 PM.
- **Move monitors (combined)** — 80 runs/week (30%). Hourly during Asian + US trading sessions, Mon–Fri only.
- **Most workflows are daily or more frequent** — only 3 are weekly: rationalization (Sat 6 AM), portfolio review (Sat 8 AM), fundamentals fetcher (Sun 6 PM).
- **No schedules currently run at:** Saturday/Sunday 9 AM–4 PM (move monitors are Mon–Fri only).
- **Coherence pipeline (not yet built):** Once Plans 1–3 are implemented, candidate_prescreener and replacement_screener will be dispatched by rationalization on Saturday ~6:05 AM, and candidate_eval pull mode will run ~6:30 AM. See `docs/design/2026-06-26_portfolio-coherence-seams-design.md`.
- **Position Sentinel:** Script is deployed; schedule YAML exists but is `enabled: false` (Phase 2). Currently run on-demand for Phase 1 calibration.
- **Windmill Error Alert:** Not a scheduled Windmill job — triggered by Windmill's internal failure handler. Not shown above.
