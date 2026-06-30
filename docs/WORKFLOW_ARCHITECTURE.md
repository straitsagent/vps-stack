# Workflow Architecture

**Last updated:** 2026-06-29 (YouTube schedule daily 18:00 SGT; synthesis in email; Telegram dispatch retired from 4 scripts; macro_research Finnhub migration)  
**Owner:** the owner  
**Purpose:** Human-readable / pseudocode spec for every workflow in the stack. Claude Code reads this before building or modifying any workflow. Each built workflow is documented in full. Planned workflows have a brief stub — fill in the full spec before coding.

---

## Testing Contract (read before building or modifying any workflow)

Every sending workflow (email or Telegram) must have an artifact-render test in `agent/tests/test_windmill_scripts.py`. See `docs/TESTING.md` for the full pattern, ASD convention, Testing Critic checklist, and Tier 0.

**The required test shape for each sending script:**
- `_<SCRIPT>_ASD` dict — the authoritative pre-implementation spec; defines `email_required`, `telegram_required`, `shared_fields`, `min_telegram_words`. Written first, before world fixture or tests.
- `_<SCRIPT>_WORLD` — derived from ASD constants (world references ASD, not the reverse). `_validate_world_vs_asd(world, asd)` called at top of harness.
- `_render_<script>_artifacts(world)` — runs real `main()` with I/O seams mocked; returns `(email_html, md_content, telegram_message)`
- `test_<script>_email_and_telegram_agree` — **the cross-check**: iterates `_SCRIPT_ASD["shared_fields"]` mechanically; must cover all shared fields
- `test_<script>_telegram_min_word_count` — asserts `len(tg_msg.split()) >= 500`
- Apply **Testing Critic checklist** (Hard Rule 20) before committing any artifact test

**Seam factoring (required for main() to be test-drivable):**
- `_send_email(gmail_smtp, recipient, subject, html)` — SMTP send, interceptable in tests
- `_build_front_matter(...) -> dict` — assembles the shared source dict (one source for email + Telegram)
- `_build_md_content(front_matter, narrative) -> str` — pure; produces the `.md` string
- `_write_canonical_md(md_content, path)` — file write, interceptable in tests

**Tier 0 — production artifact verification:**
- Each script in `ARTIFACT_MARKERS` (health_check.py) has structural HTML markers checked daily
- `_fetch_sent_body` + `_artifact_body_check` run inside health_check `main()` after email send
- Results written to `artifact_verification` Postgres table; failures logged as warnings
- Add a `ARTIFACT_MARKERS` entry for every new sending script

Scripts with full artifact harnesses (Phase C ✅): `health_check`, `macro_research`, `portfolio_email`, `portfolio_review`, `portfolio_rationalization`, `portfolio_move_monitor`, `portfolio_analyst_alert`, `youtube_monitor`. Testing Phase D (approved): adds harnesses for `morning_news_digest`, `portfolio_price_fetcher`, `fundamentals_fetcher`.

---

## How to read this document

Each built workflow follows this structure:
- **Trigger** — what fires it
- **Inputs** — resources, APIs, credentials consumed
- **Logic** — step-by-step pseudocode
- **Output** — what the email looks like

Planned workflows are stubs with trigger + one-line description only. Expand the stub into a full spec (and get explicit approval) before writing any code.

---

## Phase 1 — Daily Intelligence

---

### Workflow 1.1 — Morning News Digest ✅ LIVE

**Script:** `u/admin/morning_news_digest`  
**Trigger:** Cron — 6:30 AM SGT daily  
**Send to:** `<YOUR_RECIPIENT_EMAIL>`, `<YOUR_WORK_EMAIL>`

**Inputs:**
- Gmail SMTP/IMAP credentials (`$res:u/admin/gmail_smtp`)
- Deepseek API key (`$var:u/admin/deepseek_key`) — model: `deepseek-v4-flash`
- Google News RSS (no auth, public)
- NYT RSS feeds (no auth, public)

**Logic:**

```
── Section 1: Key Headlines (RSS) ──────────────────────────────
cutoff = now - 24h

for each source in [Reuters, WSJ, Barron's, NYT World, NYT Business, NYT Economy]:
    fetch RSS feed (Google News site: search or direct NYT feed)
    collect up to 5 articles published within cutoff
    record: title, link, pub_time

── Section 2: Google News Keyword Alerts ────────────────────────
for each keyword in [LNG Asia, Infrastructure Finance APAC, Data Centre Singapore]:
    fetch Google News RSS search results
    collect up to 5 articles published within cutoff
    record: title, link, pub_time

── Section 3: Newsletter AI Summaries ───────────────────────────
cutoff = now - 24h

connect to Gmail via IMAP (same credentials as SMTP)
fetch all inbox emails since (cutoff - 24h buffer)
filter to exact cutoff window by timestamp

split emails into two buckets:
    key_newsletters  → sender domain matches any of:
                        reuters.com, interactive.wsj.com,
                        barrons.com, nytimes.com, marketwatchmail.com
    other_emails     → everything else

for each key newsletter:
    extract body:
        prefer text/plain
        fall back to HTML: strip <style>/<script> blocks, then strip tags
        truncate to 3000 chars
    extract links programmatically from HTML:
        regex <a href> on raw HTML
        filter out tracking/unsubscribe/image URLs
        keep up to 5 links with anchor text ≥ 10 chars
    call Deepseek deepseek-v4-flash (plain text response):
        prompt: "Summarise in 3-5 sentences. Cover key events, market
                 moves, deals, policy changes. Direct and factual, no filler."
    record: source_name, subject, time, summary, links[]
    accumulate: prompt_tokens, completion_tokens

── Section 4: Other Inbox Items ─────────────────────────────────
list all other_emails sorted by time descending
record: time (SGT), sender_name (display name), subject

── Send ──────────────────────────────────────────────────────────
build HTML email with 4 numbered sections
header (below title): deepseek-v4-flash · N calls · X prompt + Y tokens · est. $0.000X
print usage stats to Windmill logs
send via Gmail SMTP to all recipients
```

**Output email — section structure:**
```
Morning Digest — [Weekday, DD Month YYYY]
deepseek-v4-flash · N calls · X prompt + Y completion tokens · est. $0.000X

1. Key Headlines
   REUTERS
   · HH:MM  Headline text (linked)
   [repeat per source]

2. Google News Alerts
   LNG ASIA
   · HH:MM  Headline text (linked)
   [repeat per keyword]

3. Newsletter Summaries
   [Source · HH:MM SGT]
   Subject line
   AI summary (3-5 sentences)
   Clickable links (up to 5, extracted from newsletter HTML)
   [repeat per key newsletter]

4. Other Inbox Items
   HH:MM SGT · Sender Name — Subject
   [all non-key-source emails]
```

---

### Workflow 1.2 — YouTube Channel Monitor ✅ LIVE

**Script:** `u/admin/youtube_monitor`  
**Trigger:** Cron — `0 0 18 * * *` SGT (daily 18:00 SGT), schedule `u/admin/youtube_monitor_hourly`  
**Send to:** `<YOUR_RECIPIENT_EMAIL>`

**Inputs:**
- Feed list: `$var:u/admin/youtube_feeds` — JSON array of `{channel_name, rss_url}`. Edit in Windmill UI to add/remove channels. Sourced from Drive "Youtube" sheet on 2026-06-03 (37 channels).
- Dedup state: `$var:u/admin/youtube_processed_state` — JSON list of seen video IDs, rolling 1000-ID window. Managed by the script via Windmill REST API + `WM_TOKEN`.
- RapidAPI YouTube transcript key (`$var:u/admin/rapidapi_key`) — host: `youtube-transcribe-fastest-youtube-transcriber.p.rapidapi.com`
- Deepseek API key (`$var:u/admin/deepseek_key`) — model: `deepseek-chat`
- Gmail SMTP (`$res:u/admin/gmail_smtp`)

**Logic:**

```
── Step 1: Load feed list ───────────────────────────────────────
GET u/admin/youtube_feeds via Windmill variables API (WM_TOKEN)
parse JSON array → list of {channel_name, rss_url}

── Step 2: Load processed video IDs ─────────────────────────────
GET u/admin/youtube_processed_state via Windmill variables API (WM_TOKEN)
parse JSON list → set of already-seen video_ids

── Step 3: Fetch and filter RSS feeds ───────────────────────────
cutoff = now (UTC) - 65 minutes
fresh_videos = []

for each (channel_name, rss_url):
    GET rss_url (no auth, public Atom feed)
    parse XML — each <entry> has:
        yt:videoId  → video_id
        title       → title
        published   → published_at (ISO 8601)
        link href   → watch_url
    for each entry:
        if published_at >= cutoff AND video_id not in processed_set:
            add to fresh_videos: {video_id, channel_name, title, watch_url, published_at}

if fresh_videos is empty: exit (no email sent)

── Step 4: Retrieve transcripts ─────────────────────────────────
for each video in fresh_videos:
    GET https://youtube-transcribe-fastest-youtube-transcriber.p.rapidapi.com/transcript
        params: url=<watch_url (URL-encoded)>, video_id=<video_id>, lang=en
        headers: x-rapidapi-host, x-rapidapi-key
    if status == success: transcript = response.data.text
    if error or transcript empty: transcript = "[Transcript unavailable]"

── Step 5: Summarise ────────────────────────────────────────────
for each video with a transcript:
    call Deepseek deepseek-chat:
        prompt:
            "Summarise the following YouTube video transcript in 4-6 sentences.
             Cover the main topic, key points, and any notable conclusions or
             recommendations. Be concise and factual.

             Title: {title}

             {transcript}"
    record summary

── Step 6: Log processed videos ─────────────────────────────────
merge new video_ids into existing set, trim to 1000, POST back to
u/admin/youtube_processed_state via Windmill variables API

── Step 6b: Write canonical .md ─────────────────────────────────
write /research/youtube/YYYY-MM-DD_HHMM.md:
    JSON front-matter block (date_str, n_summarised, videos)
    <!-- DETAIL --> separator
    per-video summaries
    (24h synthesis commentary removed 2026-06-30 — per-video summaries only)

── Step 7: Send email ────────────────────────────────────────────
build HTML email (no Daily Synthesis block — removed 2026-06-30):
    Per-video blocks, sorted by published_at descending:
        CHANNEL NAME (bold, uppercase)
        Video title (hyperlinked to watch_url)
        Published: HH:MM SGT
        Summary paragraph (or "[Transcript unavailable]")
        ---
send via Gmail SMTP
```

**Output email:**
```
Subject: YouTube Digest — DD Mon YYYY, HH:MM SGT (N new videos)

CHANNEL NAME
Video title (linked to YouTube)
Published: HH:MM SGT
[4-6 sentence summary]

---

CHANNEL NAME
Video title (linked to YouTube)
Published: HH:MM SGT
[4-6 sentence summary]

---
```

**Design decisions:**
- 65-minute lookback (not 60) to absorb clock jitter — note: with daily 18:00 SGT schedule this captures only videos published in the ~hour before the run; wider coverage would require a 24h+ lookback (future improvement)
- Deduplication via Windmill variable `u/admin/youtube_processed_state` — Google Sheets service account permission could not be granted, so state moved to Windmill-native storage
- Email skipped entirely if no fresh videos — no noise (daily cadence: runs once at 18:00 SGT)
- Transcript failures logged as "[Transcript unavailable]" but don't block the rest of the run
- Videos sorted newest-first in the email
- RapidAPI key stored as new Windmill variable `u/admin/rapidapi_key` (plain secret)
- Each run writes its own `/research/youtube/YYYY-MM-DD_HHMM.md` file (one file per run, not appended). The Telegram agent reads the latest file via alphabetical sort — returns the latest daily batch. Telegram push retired 2026-06-29; Hermes will consume `.md` directly.

---

### Workflow 1.3 — LinkedIn Post Reminder 🔲 NOT BUILT

**Trigger:** Cron — Monday 8:00 AM SGT  
**Description:** Sends a Gmail reminder with a suggested P2I topic based on the week's news headlines.

---

## W1 — Telegram Agent

**Service:** `root-straitsagent-1` (FastAPI, Docker)  
**Code:** `/root/agent/`  
**Bot:** `@<YOUR_BOT_USERNAME>` — webhook at `https://<YOUR_DOMAIN>/webhook/telegram`

### Message routing

```
Telegram message
  → POST /webhook/telegram (secret-token verified)
  → parse_inbound() → {phone, text, msg_id, ...}
  → strip leading "/" → track was_slash
  → [if was_slash] STRUCT_RESEARCH_RE match: stockresearch|research|deepresearch
      → pre-classifier shortcut: build args directly, skip classifier (router_tokens=0)
  → [else] clf.classify(text, history) — Deepseek deepseek-chat, 18 intents
  → tool_class = TOOL_CLASSES[intent]
  → execute via FAST / FIRE / ASYNC_NOTIFY / GATED_WRITE path
  → send_message() — splits at newlines if >4,000 chars, sends N chunks
```

**Structured research commands** (bypass classifier; `was_slash` guard ensures plain-text `research NVDA` still routes through classifier):

| Command | research_type | depth | cache |
|---|---|---|---|
| `/stockresearch TICKER [question]` | stock | deep | tiered: <30d serve cached; 30–90d dispatch standard; no cache dispatch deep |
| `/research QUESTION` | strategy | standard | none — always fresh |
| `/deepresearch QUESTION` | strategy | deep | none — always fresh |

### Tool latency classes

| Class | Behaviour | Tools |
|---|---|---|
| FAST | In-process, synchronous | portfolio_snapshot, portfolio_digest, ticker_detail, live_prices, health_check, news_digest, youtube_digest |
| FIRE | Dispatch Windmill job, return immediately | email_summary |
| ASYNC_NOTIFY | Dispatch Windmill job + poll loop; sends second message when done | research |
| GATED_WRITE | Confirmation prompt first, then execute on "confirm/yes" | price_refresh, fundamentals_refresh |

### File-serve digests

Windmill scripts write dated `.md` files alongside email sends. The agent reads the latest file — it never re-triggers Windmill for digest content.

```
news_digest:       reads /research/news/YYYY-MM-DD.md          (latest by alpha sort)
youtube_digest:    reads /research/youtube/YYYY-MM-DD_HHMM.md  (latest daily run)
portfolio_digest:  reads /research/portfolio/YYYY-MM-DD_{am|pm}.md
```

**Summarisation:** if file content >3,500 chars, call `deepseek-chat` to condense before delivery:
- News: "8-10 most important stories as bullets, grouped by theme"
- YouTube: "channel — title: one-sentence takeaway per video with a real summary"
- Portfolio: no summarisation (always <4,000 chars)

Falls back to truncation at 3,500 chars if Deepseek call fails.

**`/research` mount:** `/root/research:/research:ro` bind-mounted into `straitsagent` container — written by Windmill workers, read by the agent.

### Intent disambiguation (classifier.py)

Key pairs the LLM is guided to distinguish:
- `portfolio_snapshot` — "live prices / current portfolio" → queries Postgres directly
- `portfolio_digest` — "portfolio update / latest report / portfolio email" → reads stored .md

---

## Phase 5 — Deal & Market Monitoring

---

### Workflow 5.1 — APAC Infrastructure Deal Tracker 🔲 NOT BUILT

**Trigger:** Cron — daily  
**Description:** Scrapes IJGlobal/PFI/Infralogic public RSS for APAC infra deals; deduplicates via Google Sheets log; emails new deals only.

---

### Workflow 5.2 — Sponsor News Monitor 🔲 NOT BUILT

**Trigger:** Cron — daily  
**Description:** Google News RSS per sponsor name (KKR, Actis, DigitalBridge, Macquarie, Stonepeak, Brookfield); deduplicates via Sheets; emails new articles only.

---

### Workflow 5.3 — LNG Price & Spread Alert 🔲 NOT BUILT

**Trigger:** Cron — daily  
**Description:** Fetches JKM/TTF spread and Henry Hub; alerts only if spread moves >10% week-on-week.

---

## Phase 7 — Personal & Productivity

---

### Workflow 7.1 — Weekly Agenda Prep 🔲 NOT BUILT

**Trigger:** Cron — Sunday 7:00 PM SGT  
**Description:** Pulls Google Calendar events for the coming week and emails a clean agenda.

---

### Workflow 7.2 — Chess Puzzle Reminder 🔲 NOT BUILT

**Trigger:** Cron — daily 9:00 PM SGT  
**Description:** Sends a short reminder email with direct link to Lichess daily puzzle.

---

### Workflow 7.3 — Reading List Digest 🔲 NOT BUILT

**Trigger:** Cron — Friday 6:00 PM SGT  
**Description:** Pulls unread items from a Google Sheets reading list and emails as a weekend reading digest.

---

## Phase 8 — Manual Research Tools

---

### Workflow 8.1 — Company News Brief Generator 🔲 NOT BUILT

**Trigger:** Manual (Windmill form — company name input)  
**Description:** Scrapes recent news for a company, calls Claude API, generates and emails a 1-page brief.

---

### Workflow 8.2 — Meeting Prep Auto-Brief 🔲 NOT BUILT

**Trigger:** Manual (Windmill form — counterparty + meeting date)  
**Description:** Pulls recent news and deal history from Sheets, generates and emails a formatted briefing note via Claude API.

---

### Workflow 8.3 — Substack Draft Assistant 🔲 NOT BUILT

**Trigger:** Manual (Windmill form — topic/thesis input)  
**Description:** Calls Claude API with P2I framework context; generates and emails a draft outline + intro paragraph.

---

## Phase 6 — System & Reliability

---

### Workflow 6.1 — Comprehensive System Monitor ✅ LIVE (updated 2026-06-30)

**Script:** `u/admin/health_check`  
**Formatter:** `u/admin/health_check_telegram` (retained on disk — dispatch removed)  
**Schedule:** `u/admin/health_check_daily` — **8:00 AM SGT** daily  
**Send to:** `<YOUR_RECIPIENT_EMAIL>` (email only — Telegram retired)  
**Canonical output:** `/research/health/YYYY-MM-DD_HHMM.md` (comprehensive deterministic report)

**Host collector:** `scripts/system-metrics-collector.py` via `system-metrics.timer` (every 30min). Writes `/root/research/system/vps_health.json` with disk/memory/load/Docker/backup metrics. health_check reads it from `/research/system/vps_health.json`.

**Artifact-render test:** `_render_health_check_artifacts(world)` in `agent/tests/test_windmill_scripts.py` — runs real `main()` with I/O seams mocked, asserts system resources + backup status + diagnoses + spec violations + schedule labels appear in email HTML. `test_hc_email_and_telegram_agree` is the cross-check. See `docs/TESTING.md` for pattern.

**Inputs:**
- `$res:u/admin/gmail_smtp`, `$var:u/admin/recipient_email`
- `$res:u/admin/portfolio_db`, `$var:u/admin/wm_token`
- `$var:u/admin/deepseek_key` (failure diagnosis)

**Notification layers:**

| Layer | Mechanism | Catches |
|---|---|---|
| A — In-script diagnosis | Deepseek called for each STALE/FAILED schedule → `diagnoses` front-matter key | Per-schedule failures with root cause + remediation |
| B — Global crash (error_alert.py) | Windmill workspace error hook → email + Telegram + Deepseek 1-line diagnosis | health_check itself crashing, any other job crash |
| C — Host deadman | `/root/scripts/healthcheck-deadman.py` + systemd timer at 08:30 SGT → direct Telegram API | health_check never ran, scheduler wedged, Windmill down |

**Schedules monitored (6 total):**

| Schedule path | Label | Max age | Notes |
|---|---|---|---|
| `u/admin/morning_news_digest` | Morning News Digest | 26h | Has LLM (single run) |
| `u/admin/portfolio_price_fetcher_daily` | Portfolio Price Fetcher (AM) | 26h / 72h† | weekday_only |
| `u/admin/portfolio_email_daily` | Portfolio Email (AM) | 26h / 72h† | weekday_only |
| `u/admin/portfolio_price_fetcher_evening` | Portfolio Price Fetcher (PM) | 26h / 72h† | weekday_only |
| `u/admin/portfolio_email_evening` | Portfolio Email (PM) | 26h / 72h† | weekday_only |
| `u/admin/youtube_monitor_hourly` | YouTube Monitor (daily 18:00 SGT) | 26h | Has LLM — per-video summaries (24h synthesis removed 2026-06-30). Schedule changed 2026-06-29 |

† 72h on Sat/Sun/Mon — portfolio scripts intentionally skip weekends

**Logic:**

```
sgt_now = current time in Asia/Singapore

# Layer A — schedule loop
diagnoses = []
for each schedule:
    GET /api/w/admins/jobs/completed/list?schedule_path=<path>&per_page=1
    if no jobs → status = STALE
    else:
        job = most recent completed job
        age_h = (now_utc - job.started_at) / 3600
        if not job.success → status = FAILED
        elif age_h > max_age_h → status = STALE
        else → status = OK
    if status in (STALE, FAILED):
        diagnoses.append(_diagnose_failure(label, path, status, error, age_str, deepseek_key))
        # → {label, root_cause, remediation} via Deepseek deepseek-chat

# Content engine
content_reports = _collect_24h_reports(now_sgt)
    # scans /research/{macro,portfolio,youtube,news,health}/*.md, mtime < 26h
    # parses JSON front-matter block + narrative
    # returns [{type, path, mtime, front_matter, narrative, word_count}]

spec_checks = [_spec_check(r) for r in content_reports]
    # per-type validators:
    #   macro:     indicators.market ≥ 12 symbols, indicators.fred ≥ 13 series, news_headlines present
    #   portfolio: total_value / total_pnl / total_pnl_pct present
    #   youtube:   videos or video_count present
    # returns {output, pass, violations[]}

digest = _synthesise_daily_digest(content_reports, xai_key, deepseek_key)
    # primary:  OpenAI(api_key=xai_key, base_url="https://api.x.ai/v1"), model="grok-4", max_tokens=1500
    # fallback: OpenAI(api_key=deepseek_key, base_url="https://api.deepseek.com"), model="deepseek-chat"
    # prompt: executive daily brief 700-1000w, numbered sections + bullets + exec summary + conclusion

# Token usage + outbox audit (unchanged)
token_usage = _query_llm_token_usage_24h(wm_token)
outbox_rows = _query_telegram_outbox_24h(portfolio_db)

# Write canonical .md
front_matter = {
    tg_date, ok_count, total, rows,
    token_usage, outbox_rows,
    diagnoses,       # Layer A results
    spec_checks,     # per-output pass/fail + violations
    content_inventory,  # [{type, path, word_count}]
    digest           # Grok-4 holistic brief text
}
write /research/health/YYYY-MM-DD_HHMM.md

# Dispatch formatter (unchanged)
dispatch health_check_telegram with md_path → Telegram delivery
send HTML email (digest at top, ops table, spec failures, diagnoses)
```

**Front-matter schema:**
```json
{
  "tg_date": "22 Jun",
  "ok_count": 4,
  "total": 6,
  "rows": [{"label": "...", "status": "OK|STALE|FAILED", "age_str": "...", "error": ""}],
  "token_usage": [{"job": "...", "model": "...", "tokens": 0, "cost_usd": 0.0}],
  "outbox_rows": [{"script_name": "...", "delivered": true, "word_count": 0, "error": null, "sent_at": "..."}],
  "diagnoses": [{"label": "...", "root_cause": "...", "remediation": "..."}],
  "spec_checks": [{"output": "macro|portfolio|youtube|news|health", "pass": true, "violations": []}],
  "content_inventory": [{"type": "...", "path": "...", "word_count": 0}],
  "digest": "700-1000w holistic executive brief text"
}
```

**Telegram message structure (health_check_telegram.py):**
```
Header: 🏥 Daily Brief — {date} · {ok_count}/{total} OK

[Digest section — Grok-4 brief, or narrative fallback]

Ops Status
  ✅ Morning News Digest          4h 24m ago
  ✅ Portfolio Price Fetcher (AM)  5h 9m ago
  ...
  ❌ Portfolio Email (PM)          FAILED · 40h 54m ago

⚠️ Spec Failures (N of M outputs)
  macro  indicators.yahoo must have ≥12 symbols

🔍 AI Diagnoses
  Portfolio Email (PM)
  Cause: SMTP configuration failure
  Fix:   Check credentials and restart

📊 24h Token Usage
  Morning News Digest  deepseek-chat  8,011 tokens  $0.0014

📬 Telegram Formatter Audit (last 24h)
  health_check  ✅  866w  22 Jun 02:52
  ...
```

**Layer C — Host deadman switch:**
- Script: `/root/scripts/healthcheck-deadman.py`
- Systemd: `~/.config/systemd/user/healthcheck-deadman.{service,timer}`
- `OnCalendar=*-*-* 00:30:00 UTC` (= 08:30 SGT), fires 30 min after the brief
- Pure `_should_alert(api_ok, jobs, now) → (bool, str)`:
  - API unreachable → alert "Windmill API unreachable from host"
  - No jobs, or newest job not `success`, or newest job age > 90 min → alert
  - Otherwise silent (exit 0)
- POST directly to `https://api.telegram.org/bot{token}/sendMessage` — no Windmill dependency

**Design decisions:**
- Rescheduled 7:00 → 8:00 AM SGT so all morning outputs are written before the brief reads them
- Deadman fires 30 min after the brief — catches silent failures, scheduler wedges, full outage
- Layer B (error_alert) catches crashes; Layer C catches "it never ran" — complementary, not redundant
- Spec failures on old flat-schema macro `.md` files are expected until the next macro run produces the new nested `indicators.yahoo/fred` schema
- weekday_only flag: extends max_age to 72h on Sat/Sun/Mon for portfolio scripts — prevents false STALE alerts

---

### Workflow 6.2 — Windmill Error Alert ✅ LIVE

**Script:** `u/admin/error_alert`  
**Trigger:** Windmill workspace error hook — fires on any job failure  
**Send to:** `<YOUR_RECIPIENT_EMAIL>` (email) + owner Telegram (direct)

**Inputs:**
- `$res:u/admin/gmail_smtp`, `$var:u/admin/recipient_email`
- Job metadata from Windmill hook: `job_id`, `path`, `error`, `workspace_id`, `schedule_path`, `started_at`
- `$var:u/admin/telegram_bot_token`, `$var:u/admin/telegram_owner_id` (Telegram alert)
- `$var:u/admin/deepseek_key` (1-line diagnosis)

**Logic:**

```
receive from Windmill hook:
    job_id, path, error, workspace_id, schedule_path, started_at

# Email (existing, best-effort)
format HTML alert email: subject "Windmill Error — [path]", job details + stack trace
send via Gmail SMTP

# Deepseek 1-line diagnosis (best-effort, never blocks email)
diagnosis = _deepseek_diagnose(path, error, deepseek_key)
    → single sentence root-cause from deepseek-chat, '' on failure

# Telegram alert (best-effort, never raises)
_send_telegram(bot_token, owner_id, path, job_id, error, diagnosis)
    → POST https://api.telegram.org/bot{token}/sendMessage
    → message: "⚠️ Windmill Error\nJob: {path}\nID: {job_id}\nError: {error[:300]}\nDiagnosis: {diagnosis}"
```

**Output email:**
```
Subject: Windmill Error — u/admin/[script_name]

Job:      u/admin/[script_name]
Job ID:   [uuid]
Workspace: admins

Error:
[full error message / stack trace]
```

---

### Workflow 6.3 — API Health Monitor 🔲 NOT BUILT

**Script:** `u/admin/api_health_monitor`  
**Schedule:** Weekly, Sunday evening SGT (before F1 fundamentals fetcher runs)  
**Send to:** `<YOUR_RECIPIENT_EMAIL>` (alert only — silent if all pass)

**Why:** Free-tier API endpoints break without notice. FMP v3 died Aug 2025; AV COMPANY_OVERVIEW moved to premium silently. Any downstream workflow using a broken endpoint will return nulls or crash without a clear cause. This catches breakage before it corrupts data or silently degrades workflow output.

**Inputs:**
- `$res:u/admin/portfolio_db` (to log results)
- API keys: Finnhub, Alpha Vantage (key 1), FMP (all from keys.md / Windmill variables)

**Logic:**
```
define test_suite: list of {source, endpoint, test_ticker, required_fields[]}

for each test in test_suite:
    call endpoint with test_ticker
    check: response is not error object
    check: required_fields are present and non-null
    record: source, endpoint, status (OK/FAIL/DEGRADED), response_time_ms, timestamp
    INSERT INTO api_health_log

if any status != OK:
    build alert email with failing endpoints
    send via Gmail SMTP

always: log run to Windmill job result
```

**Test suite (initial):**

| Source | Endpoint | Test ticker | Required fields |
|---|---|---|---|
| Finnhub | `/stock/metric` | NVDA | `peBasicExclExtraTTM`, `pbAnnual` |
| Finnhub | `/company-news` | NVDA | at least 1 article returned |
| Finnhub | `/stock/earnings` | AAPL | `actual`, `estimate` |
| Finnhub | `/stock/recommendation` | NVDA | `buy`, `hold` |
| Finnhub | `/stock/insider-transactions` | NVDA | at least 1 transaction |
| Finnhub | `/stock/filings` | AAPL | at least 1 filing |
| Finnhub | `/calendar/economic` | — | at least 10 events returned |
| yfinance | `.info` | 9988.HK | `trailingPE`, `targetMeanPrice` |
| yfinance | `.income_stmt` | 9988.HK | `Total Revenue` row present |
| yfinance | `.calendar` | 9988.HK | `Earnings Date` present |
| Alpha Vantage | `NEWS_SENTIMENT` | NVDA | `feed` list non-empty |
| Alpha Vantage | `INCOME_STATEMENT` | AAPL | `quarterlyReports` non-empty |
| FMP | `/stable/profile` | 9988.HK | `marketCap`, `sector` |
| FMP | `/stable/key-metrics-ttm` | AAPL | `returnOnEquityTTM` |
| FMP | `/stable/income-statement` | NVDA | `revenue`, `netIncome` |
| FMP | `/stable/earnings-calendar` | — | at least 1 event returned |

**New PostgreSQL table:** `api_health_log`
```sql
CREATE TABLE api_health_log (
    id           SERIAL PRIMARY KEY,
    run_date     DATE NOT NULL,
    source       TEXT NOT NULL,       -- Finnhub, yfinance, AlphaVantage, FMP
    endpoint     TEXT NOT NULL,
    test_ticker  TEXT,
    status       TEXT NOT NULL,       -- OK, FAIL, DEGRADED
    response_ms  INTEGER,
    notes        TEXT,                -- error message or field that was null
    created_at   TIMESTAMP DEFAULT NOW()
);
```

_Expand to full spec before building. Confirm test suite before building — add/remove endpoints as the workflow stack grows._

---

## Phase 2 — Portfolio System

---

### 2.0 — PostgreSQL Infrastructure

**Type:** One-time setup — not a scheduled workflow  
**Files:** `/root/docker-compose.yml` (modified), `/root/portfolio/schema.sql`, `/root/portfolio/seed.sql`

**Design decisions:**
- PostgreSQL added to existing `/root/docker-compose.yml` alongside Windmill (Option A). Windmill worker containers share the same Docker network and connect to Postgres by service name `postgres` — port not exposed to host.
- Tickers stored in yfinance format: `HKG:XXXX` normalised to `XXXX.HK` on seed.
- `price_history` stores prices in local currency only. FX conversion (HKD → USD at ~7.8) done at query time in P2 — not stored.
- DB credentials stored as Windmill postgresql resource `u/admin/portfolio_db`.

**Step 1 — Docker**

```
add to /root/docker-compose.yml:

  service: portfolio_postgres
    image: postgres:16
    environment:
      POSTGRES_DB:       portfolio
      POSTGRES_USER:     portfolio_user
      POSTGRES_PASSWORD: <secret — also stored in Windmill resource>
    volumes:
      - portfolio_db_data:/var/lib/postgresql/data
    restart: unless-stopped
    (no ports block — internal Docker network only)

add to volumes section:
  portfolio_db_data:
```

**Step 2 — Schema (schema.sql)**

```sql
CREATE TABLE IF NOT EXISTS portfolio_positions (
    id                   SERIAL PRIMARY KEY,
    ticker               TEXT    NOT NULL UNIQUE,  -- yfinance format: AMZN, 9988.HK
    company_name         TEXT    NOT NULL,
    shares               NUMERIC NOT NULL,
    currency             TEXT    NOT NULL,          -- 'USD' or 'HKD'
    consolidation_group  TEXT,                      -- group name for ADR+local pairs (e.g. 'Alibaba')
    last_updated         TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS fx_rates (
    id            SERIAL PRIMARY KEY,
    rate_date     DATE NOT NULL,
    from_currency TEXT NOT NULL,
    to_currency   TEXT NOT NULL,
    rate          NUMERIC NOT NULL,                 -- 1 from_currency = rate to_currency
    created_at    TIMESTAMP DEFAULT NOW(),
    UNIQUE (rate_date, from_currency, to_currency)
);

CREATE TABLE IF NOT EXISTS price_history (
    id           SERIAL PRIMARY KEY,
    ticker       TEXT    NOT NULL,
    price_date   DATE    NOT NULL,
    close_price  NUMERIC NOT NULL,                  -- local currency (USD or HKD)
    currency     TEXT    NOT NULL,
    created_at   TIMESTAMP DEFAULT NOW(),
    UNIQUE (ticker, price_date)
);
```

**Step 3 — Seed (seed.sql)**

Sourced from PortfolioData Google Sheet (Drive ID: `1cwG4_KVAjJM0aK7F9h4amqUN2zFYUji60Wx-96ECQdM`), Sheet1. 33 positions. HKG:XXXX tickers normalised to XXXX.HK.

```sql
INSERT INTO portfolio_positions (ticker, company_name, shares, currency) VALUES
    ('META',    'Meta Platforms Inc',              200,  'USD'),
    ('AMZN',    'Amazon.com Inc',                  550,  'USD'),
    ('GOOGL',   'Alphabet Inc Class A',             300,  'USD'),
    ('9988.HK', 'Alibaba Group Holding Ltd',       4500, 'HKD'),
    ('BRK-B',   'Berkshire Hathaway Inc Class B',   140,  'USD'),
    ('BABA',    'Alibaba Group Holding Ltd - ADR',  400,  'USD'),
    ('UBER',    'Uber Technologies Inc',            600,  'USD'),
    ('NVDA',    'NVIDIA Corp',                      300,  'USD'),
    ('WIX',     'Wix.Com Ltd',                      400,  'USD'),
    ('0700.HK', 'Tencent Holdings Ltd',             500,  'HKD'),
    ('XLV',     'Health Care Select Sector SPDR',   225,  'USD'),
    ('ADBE',    'Adobe Inc',                        100,  'USD'),
    ('TSM',     'Taiwan Semiconductor Mfg Co Ltd',  100,  'USD'),
    ('PYPL',    'PayPal Holdings Inc',              450,  'USD'),
    ('CRM',     'Salesforce Inc',                   100,  'USD'),
    ('RDDT',    'Reddit Inc',                       100,  'USD'),
    ('NTES',    'NetEase Inc',                      150,  'USD'),
    ('ADM',     'Archer-Daniels-Midland Co',        300,  'USD'),
    ('3690.HK', 'Meituan',                         1400,  'HKD'),
    ('PINS',    'Pinterest Inc',                    550,  'USD'),
    ('QCOM',    'Qualcomm Inc',                      80,  'USD'),
    ('AMAT',    'Applied Materials Inc',             50,  'USD'),
    ('9888.HK', 'Baidu Inc',                        800,  'HKD'),
    ('CRWV',    'CoreWeave Inc',                    150,  'USD'),
    ('AMD',     'Advanced Micro Devices Inc',        50,  'USD'),
    ('TCOM',    'Trip.com Group Ltd',               150,  'USD'),
    ('V',       'Visa Inc',                          20,  'USD'),
    ('BIDU',    'Baidu Inc',                         50,  'USD'),
    ('NVO',     'Novo Nordisk A/S',                 100,  'USD'),
    ('EQNR',    'Equinor ASA',                      200,  'USD'),
    ('SERV',    'Serve Robotics Inc',               400,  'USD'),
    ('MSFT',    'Microsoft Corp',                     5,  'USD'),
    ('GRAB',    'Grab Holdings Ltd',                200,  'USD')
ON CONFLICT (ticker) DO NOTHING;
```

**Step 4 — Apply schema and seed**

```bash
# Wait for postgres to be ready, then:
docker exec -i <postgres_container_name> psql -U portfolio_user -d portfolio < /root/portfolio/schema.sql
docker exec -i <postgres_container_name> psql -U portfolio_user -d portfolio < /root/portfolio/seed.sql
```

**Step 5 — Windmill resource**

```
create resource u/admin/portfolio_db (type: postgresql):
    host:     portfolio_postgres
    port:     5432
    dbname:   portfolio
    user:     portfolio_user
    password: <same secret as Docker env>
```

---

### 2.1 — Daily Price Fetcher ✅ LIVE

**Script:** `u/admin/portfolio_price_fetcher`  
**Schedules:** `u/admin/portfolio_price_fetcher_daily` (5:45 AM SGT) + `u/admin/portfolio_price_fetcher_evening` (5:45 PM SGT)  
**Inputs:** `$res:u/admin/portfolio_db`

**Logic:**
```
connect to portfolio_db (psycopg2)
read all (ticker, currency) from portfolio_positions → 33 rows

── FX rate ─────────────────────────────────────────────
fetch yf.Ticker("USDHKD=X").history(period="5d", auto_adjust=True)
take last row: rate_date, rate (rounded to 6dp)
INSERT INTO fx_rates (rate_date, 'USD', 'HKD', rate)
    stored as: 1 USD = rate HKD
ON CONFLICT (rate_date, from_currency, to_currency) DO NOTHING
log: "FX  USDHKD=X  date  rate  (inserted|already in DB)"

── EOD prices ──────────────────────────────────────────
inserted = 0, skipped = 0, failed = []

for each (ticker, currency):
    hist = yf.Ticker(ticker).history(period="5d", auto_adjust=True)
    if empty: log FAIL, add to failed[], continue
    for each of the last 2 rows (hist.tail(2)):
        price_date  = row index date
        close_price = row Close (rounded 4dp)
        INSERT INTO price_history (ticker, price_date, close_price, currency)
        ON CONFLICT (ticker, price_date) DO NOTHING
        track inserted / skipped counts
    log: "OK  ticker  latest_date  latest_price  currency"

conn.commit()
log summary: "{inserted} rows inserted, {skipped} already in DB, {len(failed)} tickers failed"
raise RuntimeError only if failed count > half of total (triggers error alert)
```

**Design decisions:**
- Schedule args must use string format for resource references: `"$res:u/admin/portfolio_db"` — NOT dict form `{"$res": "..."}`. Windmill only resolves the string form; the dict form is passed unresolved and causes `KeyError` at runtime. (Bug hit 2026-06-04, all 4 portfolio schedules affected.)
- Per-ticker loop (not batch yf.download) — cleaner error isolation per ticker
- `auto_adjust=True` — adjusts for splits and dividends
- Inserts last 2 rows per ticker (not just 1) so P2 has yesterday's price from the very first run — avoids a "no P&L on day 1" cold-start problem
- Weekends/holidays: yfinance returns last trading day's price; ON CONFLICT DO NOTHING means 0 inserts, silent exit — correct behaviour
- Error alert fires only if >50% of tickers fail (systemic outage), not for isolated failures
- BRK-B stored with hyphen (yfinance format) — BRK.B returns empty

---

### 2.2 — Portfolio Email ✅ LIVE

**Script:** `u/admin/portfolio_email`  
**Schedules:** `u/admin/portfolio_email_daily` (6:00 AM SGT, "US Close") + `u/admin/portfolio_email_evening` (6:00 PM SGT, "Asia Close")  
**Inputs:** `$res:u/admin/portfolio_db`, `$res:u/admin/gmail_smtp`  
**Dependencies:** `psycopg2-binary>=2.9`, `pytz>=2024.1`, `feedparser>=6.0`  
**Send to:** `<YOUR_RECIPIENT_EMAIL>`

**Logic:**
```
── Weekend check ───────────────────────────────────────
if today (SGT) is Saturday or Sunday: exit, no email
session = "Asia Close" if hour >= 12 else "US Close"

── DB queries ──────────────────────────────────────────
WITH ranked AS (
    ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY price_date DESC)
)
JOIN portfolio_positions with ranked rn=1 (today price) and rn=2 (yesterday price)
store both price_today and price_yest per position

fetch latest FX rates per currency pair from fx_rates
    fx_map: ('USD','HKD') → 7.8349 means 1 USD = 7.8349 HKD
    to_usd(amount, currency) = amount / fx_map[('USD', currency)]

── Compute per position ─────────────────────────────────
value_today_usd = to_usd(price_today * shares, currency)
if price_yest exists:
    value_yest_usd = to_usd(price_yest * shares, currency)
    pnl     = value_today_usd - value_yest_usd
    pnl_pct = pnl / value_yest_usd * 100
else:
    pnl = pnl_pct = None   ← shows '—' in email

── Portfolio totals ─────────────────────────────────────
total_value  = sum(value_today_usd)
total_pnl    = sum(pnl) for positions where pnl is not None
alloc_pct    = value_today_usd / total_value * 100

── ADR/local consolidation ──────────────────────────────
positions with same consolidation_group → merged into one display row
    group value   = sum(member value_today_usd)
    group pnl     = sum(member pnl)
    group pnl_pct = group_pnl / sum(member value_yest_usd) * 100
    group label   = consolidation_group.upper()  (e.g. "ALIBABA", "BAIDU")
    member rows shown indented beneath group header
standalone positions → individual rows
display_items sorted by USD value descending

── Top movers ($ impact) ────────────────────────────────
movers = display_items where pnl is not None
top_up:   top 5 by pnl descending (largest positive $ impact)
top_down: top 5 by pnl ascending  (largest negative $ impact)
portfolio_impact = position_pnl / total_value * 100  ← shown in parentheses per row

── Top % movers + news ──────────────────────────────────
top_pct_movers = top 5 display_items by abs(pnl_pct) descending
for each mover:
    search_query = it['company']
        standalone → full company name (e.g. "NVIDIA Corp")
        group      → group name (e.g. "Alibaba")
    fetch Google News RSS:
        https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en
    collect up to 5 headlines with links (feedparser)
    price display:
        standalone: "{sym}{price_yest:,.2f} → {sym}{price_today:,.2f}"
        group: per-member "{ticker}: {sym}{prev} → {sym}{curr}" joined by ·

── Build HTML + send ────────────────────────────────────
build HTML email with 3 sections: Top Movers, % Movers — Market Context, All Positions
send via Gmail SMTP
```

**Output email:**
```
Subject: Portfolio — 4 Jun 2026 | Asia Close | $1.08M | Day: -$9,040 (-0.83%)

Portfolio — Wednesday, 4 June 2026  ·  Asia Close
Prices as of 3 Jun 2026  ·  USDHKD 7.8349

Total Value   $1,083,911
Day P&L       -$9,040 (-0.83%)

── Top Movers ──────────────────────────────────────────
▲ TICKER  +$X,XXX  (+X.XX%)  Company Name (portfolio impact: +X.XX%)
▲ ...
▼ TICKER   -$X,XXX  (-X.XX%)  Company Name (portfolio impact: -X.XX%)
▼ ...

── % Movers — Market Context ───────────────────────────
▲ CRWV  +5.23%  $105.12 → $110.93  CoreWeave Inc
  · Headline 1 (linked)
  · Headline 2 (linked)
  ...

▼ SERV  -3.21%  $8.51 → $8.24  Serve Robotics Inc
  · Headline 1 (linked)
  ...

── All Positions (sorted by USD value, largest first) ──
Ticker    Company              Shares  Price            Value (USD)  Day P&L    Day%    Alloc%
AMZN      Amazon.com Inc         550   $250.02          $137,511     +$320     +0.23%   12.7%
ALIBABA   [group header]                                $xxx,xxx     +$xxx     +x.xx%    x.x%
  ↳ BABA    Alibaba ADR           400   $127.21         $50,884
  ↳ 9988.HK Alibaba HK          4500   HK$123.40        $71,xxx
             (in USD)                   ($15.81)
...
TOTAL                                                  $1,083,911   -$9,040   -0.83%   100%
```

**Design decisions:**
- Weekend skip: Python weekday() check in SGT timezone — no email Sat/Sun
- Session label: "US Close" (morning run, before 12:00 SGT), "Asia Close" (evening run, ≥ 12:00 SGT)
- FX-agnostic: `to_usd()` looks up fx_map by currency pair — new currencies auto-supported when P1 fetches their rate
- Non-USD price column shows both local currency and USD equivalent (smaller gray text)
- P&L shown as `—` when only one day of price history exists (first run)
- ADR consolidation: `consolidation_group` column in `portfolio_positions` groups tickers — e.g. BABA + 9988.HK → "Alibaba". Group row shows consolidated totals; member rows shown indented below.
- Top Movers: sorted by absolute USD $ impact, top 5 each direction. Portfolio impact = position_pnl / total_value — shows contribution to overall portfolio move.
- % Movers: top 5 by abs(pnl_pct) across all display items (groups count as one item). Shows biggest % movers regardless of portfolio weight. Prev→curr price shown in native currency. News from Google News RSS, no auth required, up to 5 headlines per mover.
- FX stored as USD→HKD: 1 USD = rate HKD; to_usd = local_price / rate

---

### P2b — Portfolio Email: AI News Analysis 🔲 NOT BUILT (extension)

**Trigger:** Extension of P2 — upgrade to the "% Movers — Market Context" section  
**Description:** Basic news headlines for top % movers are already in P2. P2b would upgrade the section with Deepseek AI summarisation — for each % mover, call Deepseek to generate a 2-3 sentence "why did this move?" summary based on the fetched headlines.

_Expand to full spec before building. Requires adding `deepseek_key` variable to P2 script._

---

### 2.5 — Advanced Analyses 🔲 PLANNED

Expand stub before building. Planned analyses:
- Rolling 30-day performance per position and portfolio
- Portfolio vs. benchmark (SPY, HSI)
- Sector and geography breakdown
- Concentration flags (position > X% of portfolio)

---

## Phase 3 — Analytics Infrastructure

---

### 3.0 — API Audit ✅ COMPLETE

**Research file:** `/root/docs/audit/260605_fundamentals_api_audit.md`  
**Tested:** 2026-06-05, live from VPS against actual portfolio tickers.

**Decision: multi-source field-level routing, $0/mo, no paid plan required.**

**US tickers — three-source stack (all free):**

```
Finnhub  /stock/metric?metric=all  (60 calls/min, single call per ticker)
    peBasicExclExtraTTM → P/E
    pbAnnual            → P/B
    evEbitdaTTM         → EV/EBITDA
    revenueGrowthTTMYoy → revenue growth YoY
    netProfitMarginTTM  → net margin
    totalDebt/totalEquityAnnual → debt/equity

Alpha Vantage  OVERVIEW  (25 calls/day × 2 keys = 50/day combined)
    AnalystTargetPrice  → analyst target  ← only free source for this field
    Sector, Country     → classification
    MarketCapitalization → market cap

FMP  /stable/key-metrics-ttm  (250 calls/day free, US only)
    returnOnEquityTTM, returnOnInvestedCapitalTTM → capital efficiency (supplementary)
    evToEBITDATTM, grahamNumberTTM
```

**HK tickers — yfinance only (confirmed working from VPS with sleep(2)):**

```
yfinance  .info
    trailingPE, priceToBook, enterpriseToEbitda
    revenueGrowth, profitMargins, debtToEquity
    targetMeanPrice, marketCap, sector, country

Live results (2026-06-05):
    9988.HK  PE=19.3  PB=1.86  EV/EBITDA=21.2  margin=10.1%  target=HK$183.77
    0700.HK  PE=16.4  PB=3.17  EV/EBITDA=14.8  margin=30.6%  target=HK$709.36
    3690.HK  PE=None* PB=2.74  margin=-10.9%*   target=HK$109.18
    9888.HK  PE=None* PB=1.12  EV/EBITDA=15.0  margin=1.0%   target=HK$179.60
    * Null PE / negative margins correct — loss-making companies, not data gaps
```

**Ruled out:**
- Finnhub HK: API returns error for all HK tickers
- Alpha Vantage HK: all fields null for HK tickers
- FMP paid plan: not needed — yfinance covers HK fully; FMP v3 legacy endpoints dead post-Aug 2025
- FMP financial-ratios-ttm: returns empty even for US at free tier (paywalled)

**Pre-F1 gate:** Investigate `stock-analysis-db` Supabase project (prior n8n stock research DB — credentials in keys.md) before finalising F1 schema.

---

### 3.1 — Fundamentals Infrastructure ✅ LIVE

**Script:** `u/admin/fundamentals_fetcher`
**Schedule:** `u/admin/fundamentals_fetcher_weekly` — Sunday 10:00 UTC (6:00 PM SGT)
**Inputs:** `$res:u/admin/portfolio_db`, `$var:u/admin/finnhub_key`
**New table:** `fundamental_data` (schema added to `/root/portfolio/schema.sql`)

**Sources per exchange:**
- US tickers (~20): Finnhub `/stock/metric` (valuation ratios + ROE/ROI) + yfinance `.info` (analyst target, sector, country, market cap + fallbacks)
- HK tickers (~13): yfinance `.info` (all fields). Analyst targets in HKD converted to USD via `fx_rates` table.
- No Alpha Vantage — 25 calls/day limit too restrictive for batch use. AV reserved for selective use in future workflows (e.g. F3 macro data) with daily-drip pattern only.
- No FMP — `/stable/key-metrics-ttm` returned 402 on free tier (confirmed paywalled 2026-06-06). ROE/ROI sourced from Finnhub `roeTTM`/`roiTTM` instead — same call, no extra cost.

**Logic:**
```
1. Load all tickers from portfolio_positions, split US vs HK
   Fetch latest USDHKD rate from fx_rates

2. US tickers — two source calls per ticker:
   a. Finnhub /stock/metric?metric=all (sleep 0.5s between calls)
      → pe_ratio (peBasicExclExtraTTM), pb_ratio (pbAnnual), ev_ebitda (evEbitdaTTM),
        debt_equity (totalDebt/totalEquityAnnual)
      → revenue_growth_yoy (revenueGrowthTTMYoy ÷ 100 → decimal)
      → net_margin (netProfitMarginTTM ÷ 100 → decimal)
      → roe (roeTTM ÷ 100 → decimal), roic (roiTTM ÷ 100 → decimal)
      NOTE: Finnhub returns revenue_growth, net_margin, roe, roic as percentages
            (e.g. 70.68 = 70.68%) — normalise to decimal by dividing by 100

   b. yfinance .info (sleep 2s between calls)
      → analyst_target_usd (targetMeanPrice), market_cap_usd (marketCap),
        sector, country
      also used as fallback for any Finnhub null fields (returns decimal format)

   merge: Finnhub primary for valuation fields, yfinance fills nulls
   record source per field in sources_json JSONB column

3. HK tickers — yfinance .info only (sleep 2s between calls)
   convert analyst_target HKD → USD using USDHKD rate
   convert market_cap HKD → USD if returned in HKD

4. Upsert all rows into fundamental_data
   ON CONFLICT (ticker, as_of_date) DO UPDATE all fields

5. Log run summary to Windmill job result:
   - tickers processed (US + HK counts)
   - field coverage % per column (non-null count / total)
   - any tickers with >50% null fields
   - total runtime in seconds

6. Raise RuntimeError if >50% of tickers failed entirely
   → triggers 5.2 Windmill Error Alert
```

**New PostgreSQL table:**
```sql
CREATE TABLE IF NOT EXISTS fundamental_data (
    id                   SERIAL PRIMARY KEY,
    ticker               TEXT    NOT NULL,
    exchange             TEXT    NOT NULL,        -- 'US' or 'HK'
    as_of_date           DATE    NOT NULL,
    pe_ratio             NUMERIC,
    pb_ratio             NUMERIC,
    ev_ebitda            NUMERIC,
    revenue_growth_yoy   NUMERIC,                 -- decimal e.g. 0.702 = 70.2%
    net_margin           NUMERIC,                 -- decimal e.g. 0.630 = 63.0%
    debt_equity          NUMERIC,
    analyst_target_usd   NUMERIC,                 -- always USD
    market_cap_usd       NUMERIC,                 -- always USD
    sector               TEXT,
    country              TEXT,
    roe                  NUMERIC,                 -- Finnhub roeTTM (US); yfinance returnOnEquity (HK)
    roic                 NUMERIC,                 -- Finnhub roiTTM (US only; HK = NULL)
    sources_json         JSONB,                   -- which API returned each field
    updated_at           TIMESTAMP DEFAULT NOW(),
    UNIQUE (ticker, as_of_date)
);
```

**Design decisions:**
- History accumulates: UNIQUE on (ticker, as_of_date) — one row per weekly run per ticker. Enables F3/F4 to read fundamental momentum (P/E direction, analyst target trend) week over week. ~1,700 rows/year, trivial storage.
- analyst_target_usd: HK targets returned in HKD by yfinance, converted to USD using latest rate from fx_rates. US targets returned in USD directly. Uniform currency for F3/F4 comparison.
- Alpha Vantage design rule: AV 25 calls/day limit makes batch ticker loops unworkable. Any future AV integration must use a daily-drip pattern (e.g. 3-5 tickers/day) rather than processing all tickers in one run.
- yfinance NaN handling: `_safe_float()` helper rejects NaN (float('nan') != float('nan')) and returns None. Prevents silent NaN upserts corrupting the DB.
- Error policy: per-ticker failures log a warning and continue. Only fail the whole job if >50% of tickers return no data at all (systemic outage).

---

### 3.3 — Portfolio Rationalization ✅ LIVE

**Script:** `u/admin/portfolio_rationalization`  
**Schedule:** `u/admin/portfolio_rationalization` — weekly Saturday 6AM SGT  
**Trigger:** Also on-demand via Telegram (`portfolio_rationalize` / `deep rationalize`)  
**Full spec:** `docs/design/2026-06-13_portfolio-rationalization-framework.md` v1.2  
**Inputs:** `$res:u/admin/portfolio_db`, `$var:u/admin/xai_key`, `$var:u/admin/deepseek_key`, `$res:u/admin/gmail_smtp`, `$var:u/admin/recipient_email`  
**Optional param:** `include_research: bool = False` — when True, loads full `research_reports` content into Grok Call 2 prompt

**Logic:**
```
1. Load all positions from portfolio_positions; load fundamentals, valuations,
   financial health, insider, portfolio_thesis from DB

2. Compute _compute_factor_scores() for each position:
   Quality (30%): net_margin, roe, roic, fcf_quality
   Growth (25%): revenue_growth_yoy, earnings_cagr, analyst_consensus (target vs current)
   Valuation (20%): pe_ratio, pb_ratio, ev_ebitda, fcf_yield
   Sentiment (15%): insider_flow_ratio (net_insider_90d / market_cap), short_interest
   Thesis (10%): thesis_alignment (0/0.5/1 from DB)
   Completeness penalty: score_factor_coverage (0–5) + metric_coverage_pct

3. Score each position across 4 weighting scenarios:
   balanced, quality_biased, growth_biased, value_biased
   Normalise via _norm() (percentile rank within pool, skips None)

4. Rank positions 1–N per scenario; compute # top-half across scenarios (rank-robustness)
   Compute delta vs prior run (_fetch_prior_ranks) — all 4 scenarios

5. Apply absolute red flags: debt_equity > 5, interest_coverage < 1.5,
   negative_equity, revenue_decline > 30%, net_margin < -20%, fcf_quality < -0.3
   _apply_red_flag_override() forces EXIT (red-flag override) for any flagged position

6. Grok-4.3 Call 1 (batched — 15 positions per call):
   Per-position narrative with show-your-work JSON:
   {"verdict": "KEEP|TRIM|EXIT", "rationale_sentences": [{"text": "...", "evidence": ["metric"]}]}
   Deepseek fallback on xAI outage

7. Grok-4.3 Call 2 (global synthesis):
   Portfolio-wide commentary, sector/geo concentrations, macro context
   If include_research=True: full research_reports content for all tickers prepended
   Delta summary across all 4 scenarios

8. Build email report: ranking tables per scenario + top-half robustness + delta arrows +
   per-position scorecards with evidence tags + red-flag section + global commentary

9. Upsert portfolio_scores table (all 4 scenario ranks + delta_rank_* columns)
   Email to recipient_email
```

**Key tables:** `portfolio_scores` (ranks, deltas, factor scores per run)

---

### 3.4 — Portfolio Candidate Eval ✅ LIVE

**Script:** `u/admin/portfolio_candidate_eval`  
**Trigger:** On-demand — Telegram: `evaluate TICKER`, `should I add TICKER`, `candidate TICKER`  
**Full spec:** `docs/design/2026-06-15_portfolio-candidate-eval-framework.md` v1.1  
**Inputs:** `$res:u/admin/portfolio_db`, `$var:u/admin/xai_key`, `$var:u/admin/deepseek_key`, `$res:u/admin/gmail_smtp`, `$var:u/admin/recipient_email`, `$var:u/admin/wm_token`, `$var:u/admin/finnhub_key`, + search/perplexity/brave/exa/serper/tavily keys  
**Optional params:** `universe_tickers`, `thesis_text`, `replacement_ticker`

**Logic:**
```
0. Cache check: portfolio_candidate_evals for ticker with eval_date > 30d ago
   → return cached result if found (TTL=30d; B11)

1. Auto-fetch: _check_data_staleness(ticker) — queries valuation_snapshots
   If absent/stale (>3d): dispatch stock_data_fetcher, poll DB directly until fresh
   _check_research_staleness(ticker) — queries research_reports
   If absent/stale (>30d): dispatch research_tool (stock, standard), poll DB until fresh

2. Load fundamentals: _fetch_fundamentals_for_ticker() — reads from all research DB tables
   Load latest research: _fetch_latest_research() — reads research_reports content

GATE 1 — Absolute red-flag check (same thresholds as rationalization):
   debt_equity > 5, interest_coverage < 1.5, negative_equity,
   revenue_decline > 30%, net_margin < -20%, fcf_quality < -0.3
   → Any flag → PASS immediately

GATE 2 — Portfolio fit (6 sub-checks):
   B1: price correlation vs all portfolio positions (yfinance fallback for short history)
   B2: fundamental cosine similarity (sector, country, factor vector)
   Sector / geography overlap counts
   B8: currency-exposure check (HKD/USD soft 30% limit)
   B3: factor gap-fill (pool_median_F < 50 AND candidate_F > pool_p60_F; ≥2 = gap-fill)
   B7: if replacement_ticker: recompute Gate 2 net of exit position
   Sizing context (current position count, sector concentrations)

GATE 3 — Universe benchmark:
   Load peer_comparisons table (populated by stock_data_fetcher)
   B4: min_pool=5; flag below_min_universe (3–4 peers), thin_universe (<3 peers)
   B9: _validate_universe() heterogeneity guard (market-cap CoV, sector/country diversity)
   B10: check portfolio_scores.score_date — warn if >35d stale
   Per-factor triplets: {absolute, portfolio_pct, universe_pct}
   universe_composite_pct = weighted percentile vs peer universe

VERDICT (deterministic):
   ADD:   gate1 ok AND universe_composite_pct ≥ 60 AND no blocking constraint
   WATCH: gate1 ok AND universe_composite_pct ≥ 40 AND ≤1 mutable constraint
   PASS:  otherwise

Grok-4.3 synthesis: show-your-work JSON (verdict + rationale_sentences with evidence arrays)
   Full research report prepended to Grok prompt if available
   Deepseek-chat fallback

Persist to portfolio_candidate_evals; build rich HTML email report with all gate data
```

**Key tables:** `portfolio_candidate_evals` (ticker, verdict, gate results, eval_date — 30d TTL)

---

### 2.3 + 2.4 — Portfolio Review & Move Monitor ✅ LIVE

_These scripts are part of Phase 2 (Portfolio System). Specs included here for continuity with the analytics build sequence._

---

#### 2.3 — Script: `u/admin/portfolio_review`

**Schedule:** Weekly, Saturday 8:00 AM SGT (`0 0 8 * * 6`)  
**Inputs:** `portfolio_db` (postgresql resource), `finnhub_key`, `deepseek_key`  
**Send to:** `<YOUR_RECIPIENT_EMAIL>`

**Logic:**

```
1. LOAD DATA
   connect to portfolio_postgres
   fetch all positions: ticker, currency, quantity from portfolio_positions
   
   for each ticker, fetch latest two Friday closes from price_history:
     SELECT price_date, close_usd FROM price_history
     WHERE ticker = %s ORDER BY price_date DESC LIMIT 2
   → prev_close (T-7), curr_close (T-0)
   → week_pct = (curr - prev) / prev
   → week_dollar_impact = week_pct × (quantity × curr_close)
   
   fetch latest fundamental_data row per ticker (most recent as_of_date):
     pe_ratio, analyst_target_usd, market_cap_usd, sector, country
   
   fetch latest USDHKD rate from fx_rates (for display only — prices already in USD)

2. COMPUTE PORTFOLIO SUMMARY
   total_value = sum(quantity × curr_close) for all tickers
   week_pnl = sum(week_dollar_impact) for all tickers
   week_pct_total = week_pnl / (total_value - week_pnl)
   
   sector_weights: group positions by sector → pct of total_value
   geo_weights: US vs HK/China split by country field from fundamental_data

3. RANK MOVERS
   top10_impact = sort all positions by abs(week_dollar_impact) DESC, take 10
   top10_pct    = sort all positions by abs(week_pct) DESC, take 10
   news_tickers = deduplicated union of top10_impact + top10_pct (up to ~15 tickers)

4. FETCH NEWS  (Finnhub /company-news)
   for each ticker in news_tickers:
     GET https://finnhub.io/api/v1/company-news
       params: symbol=ticker, from=7_days_ago, to=today
     extract up to 5 headlines + summaries per ticker
     rate-limit: sleep 0.3s between calls
   → news_by_ticker: dict of ticker → list of {headline, summary, datetime}
   skip HK tickers (Finnhub company news is US only — use yfinance .news as fallback)

5. BUILD DEEPSEEK PROMPT
   context block:
     - week P&L summary (total value, week pnl, week pct)
     - top 10 impact movers: ticker, week%, dollar impact
     - top 10 % movers: ticker, week%, dollar impact
     - for each ticker in news_tickers: ticker + up to 5 headlines
   
   prompt:
     "You are reviewing a personal investment portfolio for the week ending [date].
      Below is the week's price performance and recent news headlines for the top movers.
      Write a 2-3 paragraph portfolio commentary covering:
      1. What drove the notable movers this week (tie to news where possible)
      2. Any valuation observations (e.g. large discount to analyst target, elevated P/E)
      3. Key themes or risks across the portfolio (concentration, China exposure, sector trends)
      Be factual and concise. Do not give buy/sell recommendations."
   
   call Deepseek deepseek-chat with context + prompt
   → commentary (string)

6. BUILD EMAIL
   subject: "Portfolio Review — Week ending [Friday date]"
   
   sections:
     PORTFOLIO SNAPSHOT
       total value, week P&L ($, %), sector weights, geo weights
     
     TOP 10 — PORTFOLIO IMPACT
       ticker | week% | dollar impact — sorted by abs(dollar impact) DESC
     
     TOP 10 — PRICE MOVERS
       ticker | week% | dollar impact — sorted by abs(week%) DESC
     
     ALL POSITIONS
       ticker | week% | prev→curr price | vs analyst target (% disc/prem) | P/E
       sorted by abs(week%) DESC
       HK prices shown as USD equivalent
       note: analyst target and P/E may be null for ETFs
     
     WEEKLY COMMENTARY
       Deepseek narrative
   
   render as HTML, send via Gmail SMTP

7. ERROR HANDLING
   if fewer than 2 price rows for a ticker: skip price calc, mark as "no data"
   if fundamental_data missing for ticker: omit vs-target and P/E columns for that row
   if Finnhub news fails for a ticker: omit from news context, continue
   if Deepseek call fails: send email without commentary section, note the failure
   if >50% of tickers have no price data: raise RuntimeError, do not send email
```

**Output email:**
```
Portfolio Review — Week ending Fri DD Mon YYYY
33 positions · Total value: $XXX,XXX · Week P&L: +$X,XXX (+X.X%)

PORTFOLIO SNAPSHOT
  Total value: $XXX,XXX  |  Week P&L: +$X,XXX (+X.X%)
  Technology XX%  Energy XX%  Healthcare XX%  ...
  US XX%  HK/China XX%

TOP 10 — PORTFOLIO IMPACT
  NVDA   +8.2%   +$4,230
  AAPL   +1.4%   +$1,100
  ...

TOP 10 — PRICE MOVERS
  SMCI   +14.2%  +$340
  TCOM   +5.1%   +$620
  ...

ALL POSITIONS
  Ticker | Week%  | Prev→Curr   | vs Target  | P/E
  NVDA   | +8.2%  | $900→$973   | -12% disc  | 35x
  TCOM   | +5.1%  | $58→$61     | -31% disc  | 14x
  ...

WEEKLY COMMENTARY
  [Deepseek narrative]
```

---

#### 2.4 — Script: `u/admin/portfolio_move_monitor`

**Schedule:** Hourly, Mon–Fri, 9:00 AM–6:00 PM SGT (`0 0 1-10 * * 1-5`)  
**Inputs:** `portfolio_db` (postgresql resource), `gmail_smtp` (optional — omit to suppress email and return data only)  
**Send to:** `<YOUR_RECIPIENT_EMAIL>`  
**Silent by default** — only sends email if thresholds are breached  
**Note:** `gmail_smtp` defaults to `{}`. When omitted, the script skips the email send and returns the alert dict directly. Used by the Telegram agent to query live prices without triggering an email.

**Logic:**

```
1. fetch all positions: ticker, quantity from portfolio_positions
2. fetch prior Friday close per ticker from price_history (most recent close_usd)
3. fetch live prices via yfinance .fast_info.last_price for all tickers
   (batch: one Ticker object per ticker, sleep 0.2s between)
4. for each ticker:
     intraday_pct = (live_price - prior_close) / prior_close
     dollar_impact = intraday_pct × (quantity × prior_close)
5. portfolio_move = sum(dollar_impact) / total_portfolio_value
6. check thresholds:
     portfolio_alert = abs(portfolio_move) >= 0.015  (±1.5%)
     position_alerts = [t for t if abs(intraday_pct[t]) >= 0.05]  (±5%)
7. if neither threshold breached: exit silently
8. if threshold breached: send condensed alert email
     subject: "Portfolio Alert — [+X.X% / -X.X%] — [DD Mon HH:MM SGT]"
     body: portfolio move summary + list of positions breaching ±5%
           + all positions sorted by abs(intraday_pct) DESC
```

---

**Design decisions:**
- No cost basis / YTD P&L — `portfolio_positions` has no purchase price. Week-over-week only.
- No buy/sell signals — pure data view. AI commentary provides qualitative context.
- News fetched only for top movers (up to ~15 tickers) — Finnhub free tier has rate limits; fetching all 33 weekly would be wasteful.
- Finnhub company news is US only — HK tickers fall back to yfinance `.news` for headlines.
- Move monitor uses prior Friday close as baseline (not prior day close) to give a weekly-anchored intraday view.
- Sector P/E median: not computed — requires universe data beyond the 33 positions. `fundamental_data` P/E is shown as-is; sector context is implicit in the Deepseek commentary.

---

### F3 — Signal Collection 🚫 PARKED

**Was:** Extensions to 1.1 + 1.2 to extract ticker mentions into `newsletter_signals` + `youtube_signals` tables.  
**Prerequisite:** None  
**Parked:** Deprioritised in favour of T1/T2 Shared Tools. Revisit after T1/T2 are live.

---

### F4 — Stock Idea Generator 🚫 PARKED

**Was:** Weekly script — aggregate signals from F3 + fundamentals from 3.1 → Deepseek thesis per candidate → weekly report  
**Prerequisite:** F3 (parked) + 3.1 (live). Universe TBD (data infra + energy sectors).  
**Parked:** F3 must be built first. Revisit once F3 is live.

---

## Ad-hoc Scripts

---

### Email Summary (manual, no schedule)

**Script:** `u/admin/email_summary`  
**Trigger:** Manual run in Windmill UI  
**Send to:** `<YOUR_RECIPIENT_EMAIL>` (configurable)

**Inputs:**
- Gmail SMTP/IMAP credentials (`$res:u/admin/gmail_smtp`)
- Deepseek API key (`$var:u/admin/deepseek_key`)
- `hours_back` parameter (default 24)

**Logic:**

```
connect to Gmail via IMAP
fetch all inbox emails in last [hours_back] hours
for each email: collect from, subject, time, body (up to 2000 chars)

concatenate all emails into single text block

call Deepseek deepseek-chat:
    prompt: "Summarise {n} emails into 4 sections:
             1. Overview — count, key senders, main themes
             2. Action Required — needs reply or decision (bullet list)
             3. FYI — newsletters and notifications, no action needed
             4. Quick Hits — any other notable items"

convert markdown response to HTML
send digest email via Gmail SMTP
```

**Output email:**
```
Inbox Summary — DD Mon YYYY
{n} emails · last {hours_back}h

1. Overview
   [AI paragraph]

2. Action Required
   · [item]
   · [item]

3. FYI
   · [item]

4. Quick Hits
   · [item]
```

---

---

## Shared Tools

Reusable Windmill scripts callable by other workflows via `wmill.run_script_by_path()`. Not scheduled. No email output of their own — return structured data to the caller.

### T1 + T2 — Unified Research Tool ✅ LIVE

**Script:** `u/admin/research_tool`  
**Type:** Callable Windmill script (manual trigger or called by other workflows)  
**Note:** T1 (stock research) and T2 (general research) are unified in one script via `research_type` parameter. Stock-specific sources, DB context, and financial statements activate when `ticker` is provided.

**Script signature:**
```python
def main(
    question: str,
    research_type: str,   # stock | strategy | macro | project
    depth: str,           # brief | standard | deep
    ticker: str = "",     # optional — activates stock-specific sources + DB context + financials
    portfolio_db: dict = {},
    gmail_smtp: dict = {},
    perplexity_key: str = "",
    xai_key: str = "",
    exa_key: str = "",
    deepseek_key: str = "",
    finnhub_key: str = "",
    serper_key: str = "",
    tavily_key: str = "",   # standard + deep, topic=finance, time_range=month
    brave_key: str = "",    # standard + deep, freshness=pm
    fred_key: str = "",     # standard + deep, research_type=macro only
    wm_token: str = "",     # Windmill API token — dispatch stock_data_fetcher on stale/absent DB data
)
```

**Source coverage by depth:**

| Source | brief | standard | deep | Notes |
|---|---|---|---|---|
| Google News RSS | ✅ | ✅ | ✅ | 5 results per query |
| Perplexity Search API | ✅ | ✅ | ✅ | search_recency_filter=month; $0.01/batch |
| Serper.dev news | ✅ | ✅ | ✅ | $0.0003/call |
| Finnhub company-news | ✅ stock US | ✅ | ✅ | 10 articles |
| Seeking Alpha RSS | ✅ stock | ✅ | ✅ | 5 articles |
| yfinance news | ✅ stock | ✅ | ✅ | 5 articles |
| **Tavily** | ❌ | ✅ | ✅ | topic=finance, time_range=month (Hard Rule 14 workaround); sentinel date "freshness:month"; 1K free/month |
| **Brave Search** | ❌ | ✅ | ✅ | freshness=pm (past month); relative dates converted to ISO |
| Exa neural search | ❌ | ✅ non-stock | ✅ all | $0.007/query × 3; 30-day date filter |
| EDGAR 8-K | ❌ | ✅ US | ✅ US | 3 most recent |
| EDGAR 10-K + 10-Q | ❌ | ❌ | ✅ US | MD&A sections extracted |
| **FRED macro data** | ❌ | ✅ macro | ✅ macro | 7 series: CPI, GDP, UNRATE, DGS10, FEDFUNDS, DEXSIUS, DEXUSEU |
| **Agentic gap analysis** | ❌ | ❌ | ✅ | Deepseek identifies gaps → routes Round 2 to news/sec/analyst/market_data |

**Inputs:**
- Deepseek API (`$var:u/admin/deepseek_key`) — query decomposition + gap analysis at deep
- Perplexity Search API (`$var:u/admin/perplexity_key`) — batch web search; `search_recency_filter: "month"`
- Serper.dev news API (`$var:u/admin/serper_key`) — Google-based news, $0.0003/call; all depths
- Tavily Search API (`$var:u/admin/tavily_key`) — finance-focused search; standard + deep; time_range=month; no pub dates in response (sentinel date used)
- Brave Search API (`$var:u/admin/brave_key`) — news search; standard + deep; freshness=pm; relative dates converted
- FRED API (`$var:u/admin/fred_key`) — macro data series; standard + deep; research_type=macro only
- Exa REST API (`$var:u/admin/exa_key`) — neural web search; standard + deep (non-stock at standard, all at deep); 30-day filter
- xAI/Grok (`$var:u/admin/xai_key`) — single synthesis call, model `grok-4.3`
- Finnhub `/company-news` (`$var:u/admin/finnhub_key`) — US tickers only, stock type
- Google News RSS — free, all research types
- Seeking Alpha RSS — free headlines, stock type
- yfinance `.news` — all tickers, stock type
- yfinance financial statements — quarterly income stmt, balance sheet, cash flow; stock type; all depths
- SEC EDGAR (free, no auth) — 8-K: standard + deep (US tickers); 10-K + 10-Q MD&A: deep only
- PostgreSQL `portfolio_db` — price_history + fundamental_data ratios; stock type only
- Gmail SMTP (`$res:u/admin/gmail_smtp`) — optional email delivery on completion
- Docker volume `/research/` (host: `/root/research/`) — markdown file storage

**Logic:**

```
── Step 1: Query decomposition (Deepseek) ───────────────────────
call deepseek-chat:
    "Generate {n} targeted search queries for: {question}
     research_type={research_type}. Return JSON array of strings."
    depth=brief    → n=3
    depth=standard → n=5
    depth=deep     → n=10
queries = parsed JSON array

── Step 2a: Google News RSS (all types, all depths) ─────────────
for each query in queries:
    feedparser.parse("https://news.google.com/rss/search?q={query}&...")
    collect entries[:5]: {source="google_news", title, url, snippet, date}

── Step 2b: Stock-specific news (stock type only, all depths) ────
if ticker and research_type="stock":
    Finnhub /company-news (US tickers, skip .HK):
        collect articles[:10]: {source="finnhub", headline, summary[:300], url}
    Seeking Alpha RSS:
        feedparser.parse("https://seekingalpha.com/api/sa/combined/{TICKER}.xml")
        collect entries[:5]: {source="seeking_alpha", title, link, summary}
    yfinance .news (all tickers including HK):
        collect[:5]: {source="yfinance", headline, url}

── Step 2c: Perplexity Search API (all types, all depths) ────────
batch_size=5; POST https://api.perplexity.ai/search per batch
{ "query": batch, "max_results": 5, "search_context_size": "high",
  "search_recency_filter": "month" }
→ {source="perplexity", title, url, snippet, date}

── Step 2d: Serper.dev news (all types, all depths) ──────────────
if serper_key:
    POST https://google.serper.dev/news
    { "q": combined_queries, "num": 10 }
    → {source="serper", title, url, snippet, date}
    cost: $0.0003/call

── Step 2d2: Tavily finance search (standard + deep) ─────────────
if tavily_key and depth in ["standard", "deep"]:
    POST https://api.tavily.com/search
    { "api_key": key, "query": combined_queries, "topic": "finance",
      "time_range": "month", "max_results": 10, "include_raw_content": "markdown" }
    → {source="tavily", title, url, snippet (article text), date="freshness:month"}
    note: Tavily returns no publication dates — time_range=month enforces freshness
          (Hard Rule 14 workaround); date field set to sentinel "freshness:month"
    free tier: 1000 searches/month

── Step 2d3: Brave Search news (standard + deep) ─────────────────
if brave_key and depth in ["standard", "deep"]:
    GET https://api.search.brave.com/res/v1/news/search
    headers: { "X-Subscription-Token": brave_key }
    params: { "q": combined_queries, "count": 10, "freshness": "pm", "extra_snippets": "true" }
    → {source="brave", title, url, snippet, date (converted from relative e.g. "1d" → ISO)}
    _parse_brave_relative_date(): "1d"→yesterday, "3w"→3 weeks ago, "2mo"→60 days ago
    free tier: 1000 searches/month

── Step 2d4: FRED macro data (standard + deep; macro type only) ──
if fred_key and depth in ["standard", "deep"] and research_type="macro":
    for each series in [CPIAUCSL, GDP, UNRATE, DGS10, FEDFUNDS, DEXSIUS, DEXUSEU]:
        GET https://api.stlouisfed.org/fred/series/observations
        params: { "series_id": s, "api_key": key, "sort_order": "desc", "limit": 3 }
        → {source="fred", title="FRED: {label} ({id})", snippet="{label}: {value} (as of {date})",
           date, content_level="full_text"}
    free, requires registration at fred.stlouisfed.org

── Step 2e: Exa REST API (standard + deep; routing by type) ──────
use_exa = depth in ["standard", "deep"] AND NOT (depth="standard" AND research_type="stock")
if use_exa:
    for each query in queries[:3]:
        POST https://api.exa.ai/search
        { "query": q, "numResults": 5, "useAutoprompt": True, "type": "auto",
          "startPublishedDate": now-30d, "contents": {"text": {"maxCharacters": 400}} }
        headers: {"x-api-key": exa_key}
        → {source="exa", title, url, snippet (article extract), date}
    note: Exa skipped for stock@standard — Perplexity equivalent, 4× cheaper+faster

── Step 2f: SEC EDGAR (standard + deep; US tickers only) ─────────
if ticker and not ticker.endswith(".HK"):
    if depth="standard": fetch up to 3× 8-K only (earnings releases, material events)
    if depth="deep":     fetch 1× 10-K, 1× 10-Q, up to 3× 8-K
    GET https://www.sec.gov/files/company_tickers.json → resolve ticker → CIK
    GET https://data.sec.gov/submissions/CIK{cik:010d}.json → recent filings list
    for 10-K/10-Q: BeautifulSoup → find MD&A section → extract up to 5000 chars
    for 8-K: full text up to 3000 chars
    → {source="edgar_10k/10q/8k", title, url (EDGAR archive), content, date}
    rate limit: 0.5s sleep between requests; User-Agent header required

── Step 3: Aggregate + deduplicate ──────────────────────────────
deduplicate by URL (keep first); sort by source_priority:
    edgar_10k(0) > edgar_10q(1) > edgar_8k(2) > fred(3) > finnhub(4) > seeking_alpha(5)
    > yfinance(6) > google_news(7) > perplexity(8) > tavily(9) > brave(10) > exa(11) > serper(12)

── Step 3b: Full article text fetch (standard + deep only) ───────
if depth in ["standard", "deep"]:
    for each item in deduped (skip: perplexity, seeking_alpha, edgar_*):
        requests.get(url, UA=Chrome, timeout=10)
        BeautifulSoup: strip script/style/nav/footer; extract <article> or <p> tags
        if len(text) >= 150: item["snippet"] = text[:2000]; mark "full_text"
        else: keep original snippet; mark "snippet"
        pre-skip known paywalls: bloomberg.com, ft.com, wsj.com, barrons.com, reuters.com/plus
    → source quality table shows full_text vs snippet count per source

── Step 3c: Agentic gap analysis (deep only) ─────────────────────
if depth="deep":
    _iterative_gap_analysis(deduped, question, research_type, deepseek_key):
        if not deepseek_key or not sources: return []
        POST https://api.deepseek.com/chat/completions
        prompt: "You found {N} sources about '{question}' (research_type={type}).
                 Review their titles and sources. Identify up to 3 specific coverage gaps.
                 Return JSON: {"gaps": [{"description", "query", "source_type"}]}
                 source_type: news | sec | analyst | market_data
                 If coverage sufficient: return {"gaps": []}"
        → list of {description, query, source_type} (max 3)

    for each gap in gaps:
        print "[Round 2] fetching for gap: '{description}' — source_type={type}"
        route to source by source_type:
            "news"        → Perplexity (batch [gap_query], max_results=3)
                          → Brave (gap_query, max_results=5)
            "sec"         → EDGAR 8-K fetch for ticker (US only)
            "analyst"     → Exa (gap_query, max_results=3)
            "market_data" → Finnhub company-news (US tickers) OR yfinance.news
        deduplicate against seen_urls; apply article fetch to new results
        append to deduped; re-sort by source_priority

    print "[Round 2] {n} new sources added from gap analysis"

── Step 4: DB context + structured stock fundamentals (stock type only) ──────
if ticker and portfolio_db:
    _read_structured_stock_data(ticker, portfolio_db):
        psycopg2: check valuation_snapshots for staleness
        absent (no row) or stale (>3 days) AND wm_token set:
            _dispatch_stock_fetcher(ticker, portfolio_db, finnhub_key, wm_token):
                POST /api/w/admins/jobs/run/p/u/admin/stock_data_fetcher
                payload: {ticker, portfolio_db, finnhub_key}
                poll /jobs/completed/get/{job_id} every 5s, timeout=60s
                return True on success, False on timeout/error
            if ok: re-read from DB
        read all 14 tables → format markdown sections:
            overview (company_profiles), fin (income+BS+CF+health),
            val (valuation_snapshots), own (ownership+institutional_holders),
            ins (insider_transactions), earn (next_earnings+earnings_surprises),
            mgmt (key_management), comp (peer_comparisons)
        returns (sections_dict, staleness: "fresh"|"stale"|"absent")
    stale sections prepend "> Data as of {date}" note
    returns ({}, "absent") on any DB error — graceful fallback

elif is_stock (no portfolio_db):
    live-fetch all 8 from APIs: _fetch_company_overview, _fetch_yfinance_financials,
    _fetch_yfinance_valuation, _fetch_ownership, _fetch_insider_transactions,
    _fetch_earnings_calendar, _fetch_management, _fetch_competitors

Always live-fetched (not in stock_data_fetcher):
    _fetch_mdna_synopsis(ticker, deepseek_key) — Deepseek-chat, EDGAR 10-Q MD&A text
    _fetch_board_of_directors(ticker) — EDGAR DEF 14A (parser bug pending fix)

_build_db_context(ticker, portfolio_db):
    psycopg2: price_history (last 30 days) + fundamental_data (latest row) → ratios block

── Step 5: Synthesis (Grok-4.3 via xAI API) ─────────────────────
reasoning_effort = {brief: "low", standard: "medium", deep: "high"}
max_tokens      = {brief: 1500, standard: 3000, deep: 8000}

depth_instruction appended to user_message:
  brief:    "provide a concise summary. 2–3 sentences per section. Target 300–400 words."
  standard: "provide a thorough analysis. 2–4 paragraphs per section with specific numbers. Target 700–1,000 words."
  deep:     "produce a comprehensive, investment-grade analysis. 4–6 paragraphs per section.
             Go beyond summarising — analyse implications, compare competing evidence, quantify
             wherever possible. Reference financial statements and SEC filings where available.
             Call out uncertainties and conflicting signals.
             [if gap_round2_count > 0]: Note: {N} sources added from targeted gap analysis (Round 2);
             acknowledge where follow-up sources confirmed, extended, or contradicted Round 1 findings.
             Target 1,800–2,500 words."

snippet length passed to Grok is content-level-aware (NOT a flat 500-char cap):
  edgar_10k / edgar_10q → up to 5000 chars
  edgar_8k              → up to 3000 chars
  full_text (article fetch) → up to 2000 chars
  snippet (headlines/RSS)   → up to 500 chars

user_message = question + ticker + depth_instruction + db_context + fin_context
             + numbered source list with content-aware snippets
POST https://api.x.ai/v1/chat/completions
model: grok-4.3, reasoning_effort: per depth, max_tokens: per depth, temperature: 0.3
→ structured markdown with inline citations [N]

── Step 6: Build report + store ──────────────────────────────────
prepend header: cost breakdown table + source retrieval quality table
    (quality table: full_text count vs snippet count per source, with notes on
     skipped sources e.g. "deep only" or "HK ticker — not in EDGAR")
write to /research/{stocks,strategy,macro,projects}/YYYY-MM-DD_{slug}.md
upsert PostgreSQL research_reports
append to /research/index.json

── Step 7: Email delivery ────────────────────────────────────────
if gmail_smtp provided:
    send to <YOUR_RECIPIENT_EMAIL>
    subject: "Research [{ticker}]: {question} — {type}/{depth}"

OUTPUT: { file_path, word_count, source_count, queries, total_tokens, est_cost_usd, db_id, preview }
```

**System prompts by research_type:**

```
stock:
"You are a professional equity research analyst. Analyse the question using the sources
provided. Structure your response as:
1. Business Overview — what the company does, key revenue drivers, business model
2. Financial Position — use DB metrics and financial statements (P/E, P/B, ROE, revenue trend, margins, debt)
3. Competitive Position — moat, market share, key competitors
4. Catalysts — near-term upside drivers (product launches, contract wins, macro tailwinds)
5. Risks — execution risk, competitive threats, macro headwinds, valuation risk
Use inline citations [N] referencing source numbers. Be factual and direct."

strategy:
"You are a strategy consultant and industry analyst. Analyse the question using the sources
provided. Structure your response as:
1. Market Structure — size, growth, key players, concentration
2. Competitive Dynamics — basis of competition, switching costs, barriers to entry
3. Moat Analysis — which players have durable advantage and why
4. Strategic Positioning — winners and losers in the current competitive landscape
5. Outlook — how the dynamics are likely to shift over 3-5 years
Use inline citations [N] referencing source numbers. Be factual and direct."

macro:
"You are a macroeconomist and sovereign analyst. Analyse the question using the sources
provided. Structure your response as:
1. Proximate Drivers — immediate causes of the trend or event
2. Structural Factors — underlying economic or political dynamics
3. Policy Response — central bank, fiscal, or regulatory actions taken or expected
4. Asset Transmission — how this affects equities, rates, FX, commodities
5. Outlook — base case trajectory and key downside risks
Use inline citations [N] referencing source numbers. Be factual and direct."

project:
"You are a project finance banker and credit analyst. Analyse the question using the sources
provided. Structure your response as:
1. Project Overview — technology, capacity, location, sponsor, stage
2. Revenue & Offtake — contract structure, counterparty quality, price exposure
3. Construction Risk — contractor, EPC structure, completion risk mitigants
4. Credit Considerations — leverage, DSCR expectations, lender requirements
5. Key Risks — permitting, grid connection, fuel supply, force majeure, political risk
Use inline citations [N] referencing source numbers. Be factual and direct."
```

**Source routing by research_type and depth:**

| Source | stock | strategy | macro | project | depth gate |
|---|---|---|---|---|---|
| Google News RSS | ✓ | ✓ | ✓ | ✓ | all |
| Finnhub /company-news | ✓ (US only) | — | — | — | all |
| Seeking Alpha RSS | ✓ | — | — | — | all |
| yfinance .news | ✓ | — | — | — | all |
| yfinance financials (income stmt, BS, CF) | ✓ | — | — | — | all |
| Perplexity Search API | ✓ | ✓ | ✓ | ✓ | all |
| Exa (neural search) | ✓ | ✓ | ✓ | ✓ | std/deep |
| Full article text fetch | ✓ | ✓ | ✓ | ✓ | std/deep |
| SEC EDGAR (10-K, 10-Q, 8-K) | ✓ (US only) | — | — | — | deep only |

**Cost estimate (observed):**

| depth | approx total | output |
|---|---|---|
| brief | ~$0.03–0.05 | ~300–400 words |
| standard | ~$0.05–0.10 | ~700–1,000 words |
| deep | ~$0.07–0.12 (CRWV: $0.0765, 81 sources, 1,583 words) | ~1,800–2,500 words |

**Storage:**
- Markdown files: `/research/{stocks,strategy,macro,projects}/YYYY-MM-DD_{slug}.md` (Docker volume: host `/root/research/`)
- PostgreSQL: `research_reports` table (see schema below)
- Index: `/research/index.json`

**PostgreSQL schema:**
```sql
CREATE TABLE IF NOT EXISTS research_reports (
  id             SERIAL PRIMARY KEY,
  created_at     TIMESTAMP DEFAULT NOW(),
  question       TEXT NOT NULL,
  research_type  TEXT NOT NULL,
  depth          TEXT NOT NULL,
  ticker         TEXT,
  file_path      TEXT,
  word_count     INTEGER,
  sources        TEXT[],
  search_queries TEXT[],
  total_tokens   INTEGER,
  est_cost_usd   NUMERIC(8,4),
  content        TEXT
);
```

**Infrastructure requirements:**
- Docker volume mount in windmill_worker: `- /root/research:/research`
- Host directories: `/root/research/{stocks,strategy,macro,projects}/` + `/root/research/index.json`
- Windmill variables: `u/admin/perplexity_key`, `u/admin/xai_key`, `u/admin/exa_key`

---

## Stock Data Fetcher (`u/admin/stock_data_fetcher`)

**Script:** `u/admin/stock_data_fetcher`
**Type:** Callable Windmill script — single-ticker, no synthesis, no email.

**Purpose:** Separate data collection from research synthesis. Fetches all structured
fundamentals for one ticker and persists to the 14 PostgreSQL research tables. Called
on-demand by research_tool when DB data is stale/absent; can also be dispatched standalone
or looped over any ticker list (portfolio, watchlist, S&P 500) by a batch caller.

**Script signature:**
```python
def main(
    ticker: str,           # required — e.g. "NVDA", "0005.HK"
    portfolio_db: dict = {},
    finnhub_key: str = "",
) -> dict:
    # returns {"ticker", "ok", "tables_written": [...], "error"}
```

**What it fetches (8 functions):**

| Function | Source | Tables written |
|---|---|---|
| `_fetch_company_overview` | yfinance `.info` | `company_profiles` |
| `_fetch_yfinance_financials` | yfinance `.income_stmt`, `.balance_sheet`, `.cashflow` | `income_statements`, `balance_sheets`, `cashflow_statements`, `financial_health_metrics` |
| `_fetch_yfinance_valuation` | yfinance `.info` | `valuation_snapshots` |
| `_fetch_ownership` | yfinance `.institutional_holders` | `ownership_snapshots`, `institutional_holders` |
| `_fetch_insider_transactions` | yfinance `.insider_transactions` | `insider_transactions` |
| `_fetch_earnings_calendar` | yfinance `.calendar`, `.earnings_history` | `next_earnings`, `earnings_surprises` |
| `_fetch_management` | yfinance `.info["companyOfficers"]` | `key_management` |
| `_fetch_competitors` | Finnhub `/stock/peers` (US only) + yfinance | `peer_comparisons` |

**What it does NOT fetch (kept as live fetches in research_tool):**
- MD&A synopsis — Deepseek-chat on EDGAR 10-Q text (LLM cost per call)
- Board of directors — EDGAR DEF 14A (parser bug pending fix: captures meeting notice boilerplate)

**Staleness gate (read side — in research_tool):**
- Check `valuation_snapshots` for ticker: no row → `"absent"`, `fetched_date < today-3` → `"stale"`, else `"fresh"`
- 3-day threshold covers weekends without triggering unnecessary re-fetches

**Logic:**
```
ticker = ticker.strip().upper()
fetch_company_overview → overview_data
fetch_yfinance_financials → fin_data
fetch_yfinance_valuation → val_data
fetch_ownership → own_data
fetch_insider_transactions → ins_data
fetch_earnings_calendar → earn_data
fetch_management → mgmt_data
fetch_competitors (skip Finnhub for .HK tickers) → comp_data
_store_stock_snapshot(ticker, portfolio_db, all_data) → writes to 14 tables
return {"ticker": ticker, "ok": True, "tables_written": [...], "error": None}
on any exception: return {"ticker": ticker, "ok": False, "tables_written": [], "error": str(e)}
```

**Infrastructure requirements:**
- Windmill resource: `$res:u/admin/portfolio_db`
- Windmill variable: `$var:u/admin/finnhub_key`
- Windmill API token: `$var:u/admin/wm_token` (used by research_tool to dispatch this script)

---

## Phase 4 — Market Intelligence & Alerts

Source reference: `/root/docs/audit/260605_api_endpoint_full_audit.md`

---

### Extensions to Existing Workflows

#### P2c — Portfolio Email: Earnings Preview + Macro Snapshot 🔲 NOT BUILT

**Type:** Extension to `u/admin/portfolio_email`  
**Prerequisite:** None — uses already-confirmed free endpoints

- **Earnings preview:** 1 call to Finnhub `/calendar/earnings` (date range = today + 14 days), filter to portfolio tickers, prepend to email: "Upcoming: BABA 2026-08-12 · NVDA 2026-08-20"
- **Macro snapshot:** 4 Alpha Vantage calls/week (`TREASURY_YIELD`, `WTI`, `BRENT`, `NATURAL_GAS`), cache in Windmill variable, prepend to email: "10Y UST: 4.52% | WTI: $71.4 | Brent: $75.1 | NG: $2.8"

_Expand to full spec before building._

---

#### 1.1a — Morning Digest: Economic Calendar Section 🔲 NOT BUILT

**Type:** Extension to `u/admin/morning_news_digest`  
**Source:** Finnhub `/calendar/economic` — free, 589+ events globally  
**Logic:** Fetch events for next 7 days, filter to `impact=high`, group by date, append as new section 5 to digest email  
**Output:** "High-impact events this week" — Fed decisions, CPI, NFP, PBOC/BOJ meetings

_Expand to full spec before building._

---

### New Standalone Scripts

### 4.1 — Earnings Surprise Tracker 🔲 NOT BUILT

**Trigger:** Cron — runs daily, checks for new earnings actuals in last 24h  
**Source:** Finnhub `/stock/earnings`  
**Logic:** For each portfolio ticker, fetch earnings history. Detect entries where `actual != None` and result not previously alerted (track seen in Windmill variable or DB). Email alert on new actuals.  
**Output:** "NVDA beat by +5.1% ($5.74 vs $5.46 est) | BABA missed by -2.3%"

_Expand to full spec before building._

---

### 4.2 — Insider Trading Alert 🔲 NOT BUILT

**Trigger:** Cron — Monday morning SGT  
**Source:** Finnhub `/stock/insider-transactions` (US tickers only, free)  
**Logic:** For each US portfolio ticker, fetch transactions from last 7 days. Filter to code=P (purchase). Alert on any meaningful purchase — sales ignored (routine, uninformative).  
**Output:** "Insider buy: [Name], [Role], [Company] — [N] shares at $[price] on [date]"  
**HK tickers:** Not covered by Finnhub (SEC-based only); no free alternative for HKEX director dealings.

_Expand to full spec before building._

---

### 4.3 — SEC 8-K Filing Alert 🔲 NOT BUILT

**Trigger:** Cron — hourly, Mon–Fri, market hours SGT  
**Source:** Finnhub `/stock/filings` (US tickers, free)  
**Logic:** For each US portfolio ticker, check for new Form 8-K filings since last run. Dedup via Windmill variable or `api_health_log`. Alert on any new 8-K.  
**Output:** "[Company] filed 8-K — [date] — [direct SEC link]"  
**Catches:** Earnings releases, M&A announcements, CEO changes, material events

_Expand to full spec before building._

---

### 4.4 — Commodity Price Monitor 🔲 NOT BUILT

**Trigger:** Cron — Monday AM SGT (weekly) + alert on threshold breach  
**Source:** Alpha Vantage `WTI`, `BRENT`, `NATURAL_GAS` (3 AV calls/run)  
**Logic:** Fetch latest weekly price. Compute WoW % change. Alert if WTI >±5% WoW or NatGas >±10% WoW.  
**Output:** Weekly snapshot email + threshold alert when triggered  
**Relevance:** EQNR direct exposure; macro context for energy sector holdings (energy_transportation thesis)

_Expand to full spec before building._

---

### 4.5 — News Sentiment DB Feed 🔲 NOT BUILT

**Trigger:** Cron — daily  
**Source:** Alpha Vantage `NEWS_SENTIMENT` (1–2 AV calls/day)  
**Prerequisite for:** F4 Idea Generator — provides richer scored signals than raw headline extraction

**Logic:**
```
call AV NEWS_SENTIMENT:
    tickers = [comma-separated portfolio tickers + watchlist]
    topics  = energy_transportation, technology, financial_markets
    limit   = 200 (max free tier)

for each article in feed:
    for each ticker_sentiment in article.ticker_sentiment:
        INSERT INTO news_sentiment:
            ticker, relevance_score, sentiment_score, sentiment_label,
            source, title, url, published_at

deduplicate by url + ticker combination
```

**New PostgreSQL table:** `news_sentiment`
```sql
CREATE TABLE news_sentiment (
    id                SERIAL PRIMARY KEY,
    ticker            TEXT NOT NULL,
    published_at      TIMESTAMP NOT NULL,
    source            TEXT,
    title             TEXT,
    url               TEXT,
    relevance_score   NUMERIC,   -- 0 to 1
    sentiment_score   NUMERIC,   -- -1 to +1
    sentiment_label   TEXT,      -- Bearish / Somewhat-Bearish / Neutral / Somewhat-Bullish / Bullish
    overall_sentiment TEXT,      -- article-level label
    created_at        TIMESTAMP DEFAULT NOW(),
    UNIQUE (url, ticker)
);
```

_Expand to full spec before building. Confirm AV call budget allocation (1–2/day leaves 48–49 calls for other uses)._

---

### Portfolio Analysis Agent 🚫 PARKED (ideaboard)

**Spec:** `docs/design/2026-06-16_portfolio-analysis-agent-spec.md`
**Trigger:** Weekly, Sunday 7:00 AM SGT (`0 23 * * 6`)
**Description:** 6-step Windmill Flow. Fetches latest portfolio email, parses positions, researches each material position (>1% alloc) via Tavily web search, runs 3-pass Claude analysis (per-position verdict → self-critique → portfolio synthesis), formats HTML report, delivers via Gmail + stores to `portfolio_analysis` PostgreSQL table.
**Pre-build:** Resolve Gmail access method; decide DB-direct vs HTML parsing for Step 2; decide whether this replaces F3; add `anthropic_api_key` + `tavily_api_key` to Windmill.

*Expand to full spec before building. Full spec at `docs/design/2026-06-16_portfolio-analysis-agent-spec.md`.*

---

### 3.2 — Financial Statement Quarterly Pull 🔲 NOT BUILT

**Trigger:** Manual or cron post-earnings season (Feb, May, Aug, Nov)  
**Source:** yfinance `.income_stmt`, `.balance_sheet`, `.cashflow` — all 33 tickers, free  
**Prerequisite for:** F3 Portfolio Review (FCF yield, revenue growth trend, debt trajectory)

**Logic:**
```
for each ticker in portfolio_positions:
    info = yf.Ticker(ticker)
    pull: income_stmt (annual + quarterly), balance_sheet, cashflow
    upsert into financial_statements table
    sleep(2)

log: tickers processed, any failures
```

**New PostgreSQL table:** `financial_statements`
```sql
CREATE TABLE financial_statements (
    id           SERIAL PRIMARY KEY,
    ticker       TEXT NOT NULL,
    period_end   DATE NOT NULL,
    period_type  TEXT NOT NULL,    -- annual, quarterly
    line_item    TEXT NOT NULL,    -- e.g. 'Total Revenue', 'Free Cash Flow'
    value        NUMERIC,
    currency     TEXT,
    updated_at   TIMESTAMP DEFAULT NOW(),
    UNIQUE (ticker, period_end, period_type, line_item)
);
```

_Expand to full spec before building. ~2 minutes runtime for 33 tickers. Zero API cost._

---

## W — Telegram Agent

---

### W1 — Personal Agent ✅ LIVE

---

#### Design rationale

**Why a standalone service at all (not Windmill)?**

Telegram is a push system. Telegram's servers POST every inbound message to your webhook URL the moment it arrives. This means something must be permanently running at a public HTTPS address, waiting for Telegram to knock. Windmill scripts run on demand and stop when done — they can't be the permanent listener. A standalone service is unavoidable.

Given that a standalone service is required regardless, the question becomes how much logic to put in it vs. Windmill. The agent runs all message-handling logic inside the service for two reasons: (1) latency — routing every message through a Windmill job adds 2-3s cold start, noticeable in a chat interface; (2) the polling loop (see below) can't be replaced by Windmill.

**What FastAPI is doing**

FastAPI is a Python web framework. Here it runs a permanent HTTP server with one job: receive POST requests from Telegram and hand them off for processing.

When you send a Telegram message to @<YOUR_BOT_USERNAME>:
```
You send "/portfolio"
  → Telegram's servers POST the update to https://<YOUR_DOMAIN>/webhook/telegram
  → FastAPI validates the X-Telegram-Bot-Api-Secret-Token header (set at webhook registration)
  → FastAPI returns HTTP 200 immediately
  → FastAPI spawns a background task to actually process the message
```

The immediate 200 return is critical — it's not the reply to you, just an acknowledgment that delivery succeeded. The actual Telegram reply is sent separately once processing completes. This design prevents Telegram from retrying and sending you duplicate messages.

**What the persistent polling loop is solving**

Research takes 60-120 seconds. You don't want to wait silently. The design is:

```
You: "/research TSLA deep"
Agent (immediately): "Starting deep research on TSLA — ~90s. I'll message you when done."
... 90 seconds pass ...
Agent (pushes to you): "✅ TSLA Research complete | 89 sources | $0.08 ..."
```

After sending the ACK, the agent dispatches the research job to Windmill and records the Windmill job UUID in Postgres. Something then needs to notice when that job finishes and push the result to Telegram.

The polling loop is a background task that runs inside the agent container forever, independently of any incoming messages. Every 5 seconds it wakes up, queries `agent_pending_jobs` for any `status='running'` rows, and asks Windmill: "is job X done yet?" When Windmill says yes, it fetches the result and sends it to Telegram.

This loop cannot be a Windmill script because Windmill scripts run to completion and stop — they don't run indefinitely. A Windmill cron approximation (checking every minute) would mean research results take up to a minute to arrive after they're ready, which is broken in a chat context.

**Why not LangGraph (or LangChain, AutoGen, etc.)**

LangGraph builds stateful AI agents as directed graphs — nodes are LLM/tool calls, edges are conditional transitions. It's designed for multi-hop reasoning: LLM calls tool A → gets result → decides to call tool B → synthesises everything → decides whether to loop or finish.

This agent doesn't do any of that. Every inbound message maps to exactly one tool call, executed once:

```
classify intent → look up tool in registry → execute tool → send reply
```

No loops, no dynamic routing between tools, no back-and-forth reasoning. The "state machine" is three branches (owner command / Drafts group command / contact message) with a dispatch table inside the owner branch. That's 50 lines of plain Python. LangGraph would wrap those 50 lines in a graph framework, add a large dependency, and provide no benefit for this structure.

The rule applied: frameworks add value when they remove complexity you'd otherwise build yourself. LangGraph removes complexity of multi-hop tool chaining and cross-turn agent state. This agent has neither. State is in Postgres (simpler and more inspectable than LangGraph state objects), and tool dispatch is a dictionary lookup.

---

#### Architecture overview

```
┌─────────────────────────────────────────────────────┐
│  Docker container: straitsagent                     │
│                                                     │
│  FastAPI (main.py)                                  │
│  ├── POST /webhook/telegram ← inbound updates       │
│  │     verify secret token header                   │
│  │     asyncio.create_task(handle_message()) ──┐   │
│  │     return HTTP 200 immediately             │   │
│  │                                             ▼   │
│  │     handle_message()                            │
│  │     ├── classifier.py  → Deepseek API           │
│  │     ├── tools.py:                               │
│  │     │   FAST      → direct Postgres query       │
│  │     │   FIRE      → Windmill dispatch + ACK     │
│  │     │   ASYNC     → Windmill dispatch + ACK     │
│  │     │               + write to pending_jobs     │
│  │     │   GATED     → write to pending_confs      │
│  │     └── telegram.py → Bot API (reply)           │
│  │                                                 │
│  polling_loop() [state.py — runs forever]          │
│  └── every 5s: query pending_jobs                  │
│      → Windmill REST: is job done?                 │
│      → if yes: telegram.py → send reply            │
│                                                     │
└──────────────┬──────────────────┬──────────────────┘
               ▼                  ▼
         Telegram Bot API    Windmill + Postgres
         (outbound msgs)     (tool execution + data)
```

Both the message handler and the polling loop run in the same Python process using `asyncio` — cooperative multitasking, so neither blocks the other.

---

#### End-to-end walkthrough

**Fast query ("/portfolio"):**
```
1. Telegram POSTs update to FastAPI webhook
2. Secret-token header verified → return 200 → spawn handle_message()
3. expire_stale_confirmations() — clear any timed-out confirm gates
4. Load last 10 conversation turns from Postgres
5. Leading "/" stripped → Deepseek classifies: {intent: "portfolio_snapshot", args: {}}
6. portfolio_snapshot() queries Postgres directly → builds text summary
7. telegram.send_message() → you receive the reply
8. append_history() + write_audit() → Postgres
Total time: ~1-2 seconds
```

**Research request ("/stockresearch TSLA earnings preview"):**
```
1-4. Same as above (note: was_slash=True since command started with /)
5. STRUCT_RESEARCH_RE matches "stockresearch TSLA earnings preview" → pre-classifier shortcut
   args = {research_type: "stock", depth: "deep", ticker: "TSLA", question: "earnings preview"}
   router_tokens = 0 (no classifier call)
6. dispatch_research() → check research_reports cache (ticker present):
   - <30 days old: return cached content + date directly — no Windmill job (job_id=None)
   - 30–90 days old: dispatch at depth=standard
   - No cache: dispatch at depth=deep (stock always forces deep when no cache)
7. POST to Windmill → receives job UUID
8. telegram.send_message() → "Starting research on TSLA — ~2 min."
9. create_pending_job(job_uuid, phone, "research") → Postgres
10. handle_message() returns — done
--- polling_loop() takes over ---
11. Every 5s: poll Windmill GET /jobs_u/completed/get_result_maybe/{uuid}
12. After ~90s: Windmill returns {synthesis, source_count, est_cost_usd, file_path, ...}
13. format_research_result() → includes today's date in header → split if >4000 chars → telegram.send_message()
14. update_job_status("delivered") → Postgres
```

**General research ("/deepresearch US rate outlook 2026"):**
```
1-4. Same as above (was_slash=True)
5. STRUCT_RESEARCH_RE matches "deepresearch US rate outlook 2026"
   args = {research_type: "strategy", depth: "deep", question: "US rate outlook 2026"}
   No ticker → cache never checked
6. dispatch_research() → cache=None (no ticker) → dispatch at depth=deep
7-14. Same polling + delivery flow as above
```

**Inbound from a contact (e.g. Sarah messages the agent):**
```
1-2. Same — secret-token verify, 200, spawn handle_message()
3. phone != OWNER_ID → handle_contact()
4. get_contact(phone) → check auto_reply flag
   - auto_reply=true: draft_reply() via Deepseek → send to Sarah directly
   - auto_reply=false (default): continue
5. draft_reply() generates a suggested response using contact notes + message
6. create_draft(phone, inbound_text, draft) → Postgres
7. send_message(DRAFTS_GROUP_ID, draft_notification):
   "📨 *Sarah*: 'Are we still on for Friday?'
    Draft: 'Yes, still on — see you at 7.'
    /send_42 · /edit_42 [new text] · /ignore_42"
8. owner replies /send_42 in Drafts group → handle_drafts_group() → send to Sarah
```

---

**Service:** `/root/agent/` (FastAPI + uvicorn, Python 3.12)  
**Docker service:** `straitsagent` in `/root/docker-compose.yml` — joins `root_default` and `agent_net` networks  
**Webhook URL:** `https://<YOUR_DOMAIN>/webhook/telegram`  
**Env file:** `/root/agent.env` (gitignored) — template at `/root/agent.env.example`

**Inputs:**
- `TELEGRAM_OWNER_ID` — owner's Telegram chat_id (<YOUR_TELEGRAM_CHAT_ID>) — only this chat_id can issue commands
- `TELEGRAM_BOT_TOKEN` — @<YOUR_BOT_USERNAME> token
- `TELEGRAM_WEBHOOK_SECRET` — arbitrary secret passed as `X-Telegram-Bot-Api-Secret-Token` header for request validation
- `DRAFTS_GROUP_ID` — Telegram group chat_id for draft approvals (negative integer, fill after group creation)
- Deepseek API (`DEEPSEEK_KEY`) — intent classification + draft generation
- xAI/Grok API (`XAI_KEY`) — research synthesis via research_tool
- Portfolio Postgres (`AGENT_DB_URL`) — direct queries + state tables
- Windmill REST API (`WM_TOKEN`, `WM_BASE_URL=http://windmill_server:8000`)

**Service files:**
| File | Purpose |
|---|---|
| `main.py` | FastAPI app — `POST /webhook/telegram` inbound handler + health endpoint |
| `config.py` | Env var loading — all constants in one place |
| `classifier.py` | Deepseek intent classification + draft reply generation |
| `tools.py` | Tool registry — FAST/FIRE/ASYNC_NOTIFY/GATED_WRITE executors; tiered research cache |
| `windmill_client.py` | Windmill REST API — `run_job`, `poll_job_result`, `run_sync` |
| `telegram.py` | Telegram Bot API — `send_message` (Markdown, 400 retry), `verify_signature`, `parse_inbound`, `mark_read` (no-op), `set_my_commands` (called at startup lifespan) |
| `db.py` | All Postgres ops — async-safe via `asyncio.to_thread` |
| `state.py` | Background asyncio polling loop — checks running jobs every 5s, pushes results; message splitting >4000 chars |
| `formatter.py` | Draft notification and confirmation prompt text builders |
| `tests/` | pytest unit tests — `test_telegram.py`, `test_tools.py`, `test_routing.py`, `test_windmill_scripts.py` |

---

**Message flow — inbound from owner:**

```
POST /webhook/telegram
  → verify X-Telegram-Bot-Api-Secret-Token header
  → parse_inbound() → {phone: str(chat_id), text, msg_id, is_group, ...}
  → mark_read(msg_id) [no-op for Telegram]
  → strip leading "/" from text (slash commands)
  → expire_stale_confirmations(phone)
  → phone == TELEGRAM_OWNER_ID?
      YES → handle_owner()
      NO  → phone == DRAFTS_GROUP_ID? → handle_drafts_group()
             else → handle_contact()
```

**handle_owner() state machine:**

```
1. Check agent_pending_confirmations for this phone (unexpired)
   → if found: handle_confirmation_response()
     - "confirm"/"yes" → execute gated tool → send result
     - "cancel"/"no"   → cancel and ack
     - anything else   → re-prompt

2. Classify intent (Deepseek deepseek-chat)
   system prompt: tool list with arg schemas
   last 4 history turns as context
   → {intent, args, confidence, router_tokens}

3. Dispatch by TOOL_CLASS[intent]:

   FAST  → execute directly (DB query or Windmill sync job ≤45s)
            → send reply → append_history → write_audit

   FIRE  → dispatch Windmill job with gmail_smtp (sends email itself)
            → send ACK: "triggered — check inbox in ~Xs"
            → write_audit

   ASYNC_NOTIFY → dispatch_research() → get job_id
                  → send ACK: "Starting deep research on X... ~90s."
                  → create_pending_job(job_id, phone, "research", args)
                  → polling_loop() picks it up every 5s
                  → on completion: format_research_result() → send_message()

   GATED_WRITE → create_confirmation(phone, tool, args)
                 → send: "This will write X. Reply confirm or cancel."
                 → (next message from phone handles confirmation)
```

**handle_contact() — inbound from third party:**

```
1. get_contact(phone) → check auto_reply flag + rule_prompt
   if auto_reply=true:
     draft_reply(inbound_text, contact) via Deepseek
     send_message(phone, draft)
     return

2. (default) draft-and-approve:
     draft = draft_reply(inbound_text, contact)
     draft_id = create_draft(phone, inbound_text, draft)
     notify_target = DRAFTS_GROUP_ID if set, else TELEGRAM_OWNER_ID
     send_message(notify_target, draft_notification(draft_id, name, text, draft))

   Notification format:
     "📨 *Sarah*: 'Are we still on for Friday?'
      Draft: 'Yes, still on — see you at 7.'
      /send_42 · /edit_42 [new text] · /ignore_42"
```

**handle_drafts_group() — owner approves/rejects:**

```
/send_<id>              → get_pending_draft(id) → send_message(phone, draft) → resolve_draft(id, "sent")
/ignore_<id>            → resolve_draft(id, "ignored")
/edit_<id> <new text>   → send_message(phone, new_text) → resolve_draft(id, "sent")
```

**Outbound message (owner-initiated):**

```
owner: "message John that I'll send the NVDA brief by EOD"
  → classifier: intent=outbound_message, args={contact_name_or_phone="John", message="..."}
  → search_contacts_by_name("John") → resolve phone/chat_id
  → create_draft(to_phone, "[outbound] msg", msg)
  → send draft_notification to DRAFTS_GROUP_ID
  → owner /send_<id> in Drafts group → agent sends to John
```

---

**Tool registry:**

| Intent | Class | Execution | Returns |
|---|---|---|---|
| `portfolio_snapshot` | FAST | Direct Postgres: `price_history` + `portfolio_positions` + `fx_rates` | Formatted text summary |
| `ticker_detail` | FAST | Direct Postgres: `fundamental_data` + `price_history` | PE, target, price trend for one ticker |
| `live_prices` | FAST | Windmill sync: `portfolio_move_monitor` (no gmail_smtp) | Portfolio move %, position alerts |
| `health_check` | FAST | Windmill sync: `health_check` (no gmail_smtp) | Schedule status, 24h token cost |
| `email_summary` | FIRE | Windmill dispatch: `email_summary` with gmail_smtp | ACK only — email sent by script |
| `news_digest` | FIRE | Windmill dispatch: `morning_news_digest` with gmail_smtp | ACK only |
| `youtube_digest` | FIRE | Windmill dispatch: `youtube_monitor` with gmail_smtp | ACK only |
| `research` | ASYNC_NOTIFY | Windmill dispatch: `research_tool` (with gmail_smtp) → poll every 5s; tiered cache (90d window) | Immediate ACK + async push; email sent by script on completion |
| `price_refresh` | GATED_WRITE | Confirmation → `portfolio_price_fetcher` | Confirmation gate then dispatch |
| `fundamentals_refresh` | GATED_WRITE | Confirmation → `fundamentals_fetcher` | Confirmation gate then dispatch |

---

**State tables (all in `portfolio` DB):**

```sql
agent_contact_rules       -- phone → display_name, relationship, auto_reply, rule_prompt, notes
agent_draft_queue         -- pending/sent/edited/ignored drafts
agent_conversation_history -- last N turns per phone (loaded as LLM context)
agent_pending_jobs        -- running Windmill jobs being polled
agent_pending_confirmations -- 5-minute TTL confirmation gates for GATED_WRITE tools
agent_audit_log           -- one row per inbound message: intent, tool, latency, tokens, cost, status
```

---

**Polling loop (`state.py`):**

```
asyncio background task — started on FastAPI lifespan startup
every 5 seconds:
    get_running_jobs() → all rows with status='running'
    for each job:
        poll_job_result(job_id) via Windmill GET /jobs_u/completed/get_result_maybe/{id}
        if None → still running, skip
        if result → format_research_result() → split if >4000 chars
                    → send_message(phone, chunk) for each chunk
                    → update_job_status(job_id, "delivered")
        if RuntimeError → update_job_status(job_id, "failed")
                          send_message(phone, "❌ research failed: {error}")
```

---

**Caddy routing:**

```
/opt/n8n/Caddyfile:
  <YOUR_DOMAIN> {
    handle /webhook/telegram* { reverse_proxy straitsagent:8001 }
    handle { reverse_proxy n8n:5678 }
  }

/opt/n8n/docker-compose.yml:
  caddy service joins external network 'agent_net'

/root/docker-compose.yml:
  straitsagent service joins both 'default' and 'agent_net' networks
```

---

**Live status:**

Agent is fully operational on Telegram. Remaining setup:

1. Create "Agent Drafts" Telegram group (owner + @<YOUR_BOT_USERNAME>) → copy group chat_id (negative integer)
2. Set `DRAFTS_GROUP_ID=<chat_id>` in `/root/agent.env`
3. `docker compose up -d straitsagent`
4. Smoke test: send `/portfolio` in the Drafts group → @<YOUR_BOT_USERNAME> should reply with snapshot

**Webhook registration (already done — for reference):**
```bash
curl -X POST "https://api.telegram.org/bot<TOKEN>/setWebhook" \
  -d "url=https://<YOUR_DOMAIN>/webhook/telegram" \
  -d "secret_token=<TELEGRAM_WEBHOOK_SECRET>"
```

**Running tests before rebuild:**
```bash
cd /root/agent && python -m pytest tests/ -v
docker compose up -d --build straitsagent
```

---

**Observability queries:**

```sql
-- Recent interactions
SELECT created_at, intent_detected, tool_called, tool_latency_ms,
       estimated_cost_usd, status
FROM agent_audit_log ORDER BY created_at DESC LIMIT 20;

-- Daily cost
SELECT DATE(created_at) day, COUNT(*) turns,
       ROUND(SUM(estimated_cost_usd)::numeric, 4) cost_usd
FROM agent_audit_log GROUP BY 1 ORDER BY 1 DESC;

-- Active async jobs
SELECT job_id, tool_name, tool_args,
       ROUND(EXTRACT(EPOCH FROM NOW() - dispatched_at)/60, 1) AS mins_running
FROM agent_pending_jobs WHERE status = 'running';

-- Pending drafts
SELECT id, wa_phone, inbound_text, draft_reply, created_at
FROM agent_draft_queue WHERE status = 'pending' ORDER BY created_at;
```

---

---

### W2 — Tool Expansion ✅ LIVE

Added four FAST tools and one GATED_WRITE tool to the registry. No architecture change — still classify → dispatch → return. Tools added:

| Tool | Intent | Class | Source | Notes |
|---|---|---|---|---|
| `thesis_read` | `thesis_read` | FAST | `portfolio_thesis` table | Returns formatted investment thesis + conviction for a ticker |
| `thesis_write` | `thesis_write` | GATED_WRITE | `portfolio_thesis` table | Upserts thesis (JSONB: catalysts, risks, conviction). Requires user confirmation before write. |
| `earnings` (unified) | `earnings` | FAST | `/research/earnings/` files + Finnhub fallback | `/earnings ADBE` → reads latest stored analysis file (pre or post, whichever is newest). `/earnings` (no ticker) → Finnhub 14-day calendar for all portfolio tickers. If no file exists for ticker, Finnhub date + hint to trigger analysis. Replaces `earnings_calendar`. |
| `news_search` | `news_search` | FAST | Exa neural search | Top 5 results with summaries. Direct API call (no Windmill). |
| `macro_indicators` | `macro_indicators` | FAST | Yahoo Finance v8 API | SGD/USD, HKD/USD, VIX, Brent crude, UST 10Y. |

---

### W3 — Proactive Alerts ✅ LIVE

Four Windmill scripts that run on schedule or are dispatched on demand. Send Telegram alerts directly (not via agent webhook).

---

#### `portfolio_earnings_alert.py` — Weekday 9 PM SGT

Scans Finnhub calendar for portfolio tickers with earnings in next 7 days. Two actions:
1. If `epsActual` populated + `|surprise| > 5%` → sends EPS surprise alert to Telegram
2. If upcoming earnings (no `epsActual` yet) + no pre-analysis in `earnings_analyses` table → dispatches `portfolio_earnings_analysis` (analysis_type=pre) as async Windmill job

---

#### `portfolio_analyst_alert.py` — 7:45 AM SGT daily

Checks Finnhub for analyst rating changes. Deduplicates via `agent_kv` table (key = `analyst_{ticker}_{date}_{firm}`). Sends Telegram for new upgrades/downgrades only.

---

#### `portfolio_earnings_analysis.py` — Dispatched (no fixed schedule)

Main earnings intelligence script. Two modes: `analysis_type=pre` or `analysis_type=post`.

**Pre-earnings flow:**
1. Load portfolio context: position sizing from `price_history` + `fx_rates`, fundamentals from `fundamental_data`, thesis from `portfolio_thesis`, prior pre-analysis from `earnings_analyses`
2. Research synopsis: `_extract_research_synopsis()` strips metadata preamble from latest `research_reports` entry (first 600 chars of narrative, skipping cost/source tables) OR dispatches `research_tool` (standard depth) via `_dispatch_and_wait_research()` if no entry exists (240s timeout); fallback `_get_seeded_overview()` via Exa + `_grok_brief()` if dispatch fails
3. Earnings date + EPS estimate from Finnhub `/calendar/earnings` (today → +30d)
4. Quarterly financial trend from yfinance `.quarterly_financials` (last 4Q: revenue, gross profit, net income)
5. Prior quarter 8-K from EDGAR EFTS search (`https://efts.sec.gov/LATEST/search-index?q="{ticker}"&forms=8-K`) → Exhibit 99.1 full text
6. Prior earnings call transcript via Exa: `"{company} earnings call transcript … site:seekingalpha.com OR site:fool.com"`
7. Analyst preview articles via Exa (top 2)
8. Grok-4.3 synthesis (`reasoning_effort=high`) → structured briefing

**Post-earnings flow:**
1–2. Same context load as pre
3. Actual EPS/revenue from Finnhub `/calendar/earnings` (last 3 days)
4. Current quarter 8-K from EDGAR (last 5 days) → Exhibit 99.1 press release
5. Earnings call transcript via Exa (most recent)
6. Analyst reactions/price target changes via Exa (top 3)
7. Quarterly trend from yfinance
8. Grok-4.3 synthesis → analysis + Buy/Accumulate/Hold/Reduce/Sell recommendation

**Output format (all 6 standards mandatory — see CLAUDE.md Earnings Report Standards):**
```
# {TICKER} Pre-Earnings Briefing / Post-Earnings Analysis
**Date written:** YYYY-MM-DD | **Expected/Earnings date:** YYYY-MM-DD

## Portfolio Position — {Company}
{shares} @ {currency} {price} = USD {value} ({pct}% of portfolio)

## Company Overview
{research synopsis or seeded 150-word overview}

---
{Grok synthesis}

---
**Sources used (N):**
  - SEC EDGAR 8-K (prior quarter press release)
  - Earnings call transcript (SeekingAlpha/Fool via Exa)
  - ...
**Model:** Grok-4.3 | **Tokens:** X in / Y out | **Est. cost:** USD 0.00XX
```

**Delivery:** Telegram to owner + email to `<YOUR_RECIPIENT_EMAIL>` + write to `/research/earnings/YYYY-MM-DD_{TICKER}_{pre|post}.md` + insert to `earnings_analyses` table.

**Dispatch sources:** (a) `portfolio_earnings_alert.py` for pre-analysis, (b) `portfolio_earnings_post_check.py` for post-analysis, (c) agent `earnings_analysis` intent (ASYNC_NOTIFY class) for manual trigger.

---

#### `portfolio_earnings_post_check.py` — 9 AM SGT daily

Morning detector for earnings that dropped overnight. For each portfolio ticker:
1. Query Finnhub calendar for last 3 days
2. If `epsActual` populated AND no `earnings_analyses` row with `analysis_type='post'` for that ticker+date → dispatch `portfolio_earnings_analysis` (post mode) as async Windmill job

Prevents duplicate post-analyses via DB check (not `agent_kv`).

---

#### Agent intent: `earnings_analysis` (ASYNC_NOTIFY)

Classifier recognises: "run earnings ADBE", "fresh pre-earnings NVDA", "trigger earnings analysis TSLA", "run post earnings ADBE".
Dispatches `portfolio_earnings_analysis` Windmill job (with `wm_token` so research can be auto-dispatched if missing) and returns immediate ACK. Polling loop reads `result["file_path"]` and sends report content when complete.

#### Agent intent: `earnings` (FAST — file-serve)

Classifier recognises: "earnings", "earnings ADBE", "/earnings", "/earnings ADBE".
Reads `/research/earnings/` for the latest file matching the ticker. No Windmill dispatch — instant response.
Registered in Telegram command menu as `/earnings`.

---

### W4 — Multi-step Reasoning ✅ LIVE

`planner.py` — a lightweight sequential planner. Three multi-step intents that chain FAST tools and synthesise with Grok-4.3.

**Architecture:**

```
classify intent → MULTI_STEP class → planner.plan() → [tool1, tool2, ...] → execute each → planner.synthesise() → reply
```

`plan()` takes the intent + args and returns an ordered list of FAST tool calls. `synthesise()` takes all tool results and runs a single Grok-4.3 call to produce a coherent answer.

**Live intents:**

| Intent | Tools chained | Output |
|---|---|---|
| `portfolio_analysis` | portfolio_snapshot + macro_indicators + earnings | Portfolio snapshot with macro context and upcoming earnings |
| `thesis_check` | thesis_read + ticker_detail + news_search | Thesis vs current fundamentals + recent news |
| `macro_brief` | macro_indicators + news_search | Macro snapshot with relevant headlines |

Falls back to single-tool dispatch if planner raises.

---

### W-Business Agent 🔲 NOT PLANNED

Second instance of W1 codebase — same Python code, different env file and bot token. For external contacts to interact with. Scope TBD.

---

## Canonical .md Front-Matter Schema (Hard Rule 18 Contract)

Every main script writes a `.md` to `/research/<type>/YYYY-MM-DD[_suffix].md` with this structure:

````
```json
{ <front-matter keys — see per-script schema below> }
```

<≥500-word LLM narrative>

<!-- DETAIL -->

<optional wide tables / per-item detail — formatter ignores everything below this marker>
````

The formatter reads only the JSON front-matter and the narrative. Any change to the keys listed below **must** update the formatter and the round-trip contract test in `agent/tests/test_windmill_scripts.py` in the same commit (Hard Rule 18).

### 1. `macro_research` → `macro_daily_push_telegram`

The primary macro writer is now `macro_research` (live, 7:00 AM SGT Mon–Fri). The formatter is still `macro_daily_push_telegram` and accepts both the new nested schema (below) and the old flat schema for backward compatibility.

```json
{
  "script": "macro_research",
  "timestamp": "<ISO8601 datetime SGT>",
  "indicators": {
    "yahoo": {
      "<SYMBOL>": {"value": <float|null>, "change_pct": <float|null>}
    },
    "fred": {
      "<SERIES_ID>": {"value": <float|null>, "date": "<YYYY-MM-DD>", "label": "<str>"}
    }
  },
  "fed_items": [
    {"title": "<str>", "date": "<YYYY-MM-DD>", "type": "<speech|press>", "speaker": "<str|null>", "url": "<str>"}
  ],
  "news_headlines": [
    {"title": "<str>", "source": "<str>", "date": "<YYYY-MM-DD>", "query": "<str>"}
  ]
}
```

**Yahoo symbols fetched (26, stored under custom name keys):** VIX, SP500, NDX, RUT, Nikkei, DAX, FTSE, HSI, CSI300, UST5Y, UST10Y, UST30Y, HYG, LQD, DXY, EURUSD, GBPUSD, USDJPY, USDCNY, USDSGD, USDHKD, Gold, Brent, Copper, NatGas. (mapped from raw Yahoo tickers internally in `macro_research.py`).

**FRED series fetched (13):** `DFF` (Fed Funds), `SOFR`, `DGS2` (2Y yield), `T10Y2Y` (10Y–2Y spread), `T10Y3M` (10Y–3M spread), `T5YIE` (5Y BE inflation), `T10YIE` (10Y BE inflation), `BAMLH0A0HYM2` (HY OAS spread), `BAMLC0A0CM` (IG OAS spread), `NFCI` (Chicago Fed FCI), `CPIAUCSL` (CPI, `units=pc1`), `PCEPI` (PCE, `units=pc1`), `UNRATE` (Unemployment).

**Formatter output (~545 words, single Telegram message):**
1. Header: `*Macro — <day> <date>, <time> SGT*`
2. Weekend note if all `abs(change_pct) < 0.01`
3. Yahoo grid — 13 symbols, 3 per row: SP500, NDX, HSI, CSI300, VIX, 10Y, DXY, EUR/USD, USD/JPY, USD/SGD, USD/HKD, Gold, Brent
4. FRED grouped block — all available series in 4 lines: `Rates:` (DFF/SOFR/2Y/10Y-2Y/10Y-3M) · `Inflation:` (CPI/PCE/5Y BE/10Y BE) · `Credit:` (HY OAS/IG OAS/FCI) · `Labour:` (Unemp)
5. Fed Watch: first `fed_items` entry title + date (italic)
6. Deepseek synthesis: `_synthesise_telegram(narrative, deepseek_key)` — 400-450 word executive synthesis of the 6-section narrative, flowing prose, `deepseek-chat` temp=0.3 max_tokens=700. Falls back to first 600 words of narrative if key absent or call fails.
7. In focus: top 4 `news_headlines` entries

**Formatter params:** `md_path`, `telegram_bot_token`, `telegram_owner_id`, `deepseek_key` (required), `portfolio_db` (optional, for outbox).

**FRED value formatting:** spreads (`T10Y2Y`, `T10Y3M`) show signed pp (e.g. `+0.27pp`); NFCI shows signed 3dp (e.g. `-0.505`); values >100 (raw index level, CPI/PCE if `units=pc1` not applied) rendered without `%`; all others `X.XX%`. **None value rendering:** `null` → `N/A`. **USDHKD:** ~7.84 (not inverted).

**Old flat schema (macro_daily_push, now disabled):** `indicators` was a flat dict `{"VIX": {"value", "change_pct"}, ...}` with 8 symbols. Formatter still accepts this for backward compat (synthesis still runs on whatever narrative is provided).

---

### 2. `portfolio_email` → `portfolio_email_telegram`

```json
{
  "script": "portfolio_email",
  "date_str": "<e.g. Sat 20 Jun>",
  "time_label": "<e.g. 11pm SGT>",
  "session": "<US Close|Asia Close>",
  "total_value": <float>,
  "total_pnl": <float>,
  "total_pnl_pct": <float>,
  "gainers": [{"label": "<ticker>", "pnl_pct": <float>, "pnl": <float>}],
  "losers":  [{"label": "<ticker>", "pnl_pct": <float>, "pnl": <float>}]
}
```

**Key note:** gainer/loser items use `"label"` (not `"ticker"`). `time_label` must be uppercase SGT.

---

### 3. `portfolio_review` → `portfolio_review_telegram`

```json
{
  "script": "portfolio_review",
  "we_str": "<e.g. 19 Jun>",
  "total_value": <float>,
  "week_pnl": <float>,
  "week_pct_total": <float>,
  "gainers": [{"label": "<ticker>", "week_pct": <float>, "week_impact": <float>}],
  "losers":  [{"label": "<ticker>", "week_pct": <float>, "week_impact": <float>}]
}
```

**Key note:** mover items use `"label"` (not `"ticker"`). **Sign rule:** `week_pnl < 0` renders as `-$N.Nk` (not `$N.Nk` without the minus).

---

### 4. `portfolio_rationalization` → `portfolio_rationalization_telegram`

```json
{
  "script": "portfolio_rationalization",
  "today_str": "<e.g. 20 Jun>",
  "n_positions": <int>,
  "top3": [{"ticker": "<str>", "score": <float — composite balanced score>, "verdict": "<KEEP|TRIM|EXIT>"}],
  "bot3": [{"ticker": "<str>", "score": <float — composite balanced score>, "verdict": "<KEEP|TRIM|EXIT>"}]
}
```

**Key notes:** `score` is the composite balanced score (e.g. 55.5) — **not** the rank integer. `verdict` comes from `call1_structured[t].get("verdict")` — **not** `"recommendation"`.

---

### 5. `portfolio_move_monitor` → `portfolio_move_monitor_telegram`

Only written when a breach fires (portfolio ±1.5% or position ±5%).

```json
{
  "script": "portfolio_move_monitor",
  "time_str": "<e.g. 10:30 AM SGT>",
  "portfolio_move": <float — signed %>,
  "total_impact": <float — signed $ impact>,
  "pct_threshold": <float — e.g. 1.5>,
  "position_alerts": [{"ticker": "<str>", "intraday_pct": <float>, "dollar_impact": <float>}],
  "pos_threshold": <float — e.g. 5.0>
}
```

---

### 6. `portfolio_analyst_alert` → `portfolio_analyst_alert_telegram`

Only written when a rating change fires.

```json
{
  "script": "portfolio_analyst_alert",
  "today_str": "<e.g. 20 Jun>",
  "alerts": [
    {"ticker": "<str>", "action": "<Upgrade|Downgrade|Initiation>",
     "old_rating": "<str>", "new_rating": "<str>", "period": "<e.g. last 7 days>"}
  ]
}
```

---

### 7. `health_check` → `health_check_telegram`

```json
{
  "script": "health_check",
  "tg_date": "<e.g. 20 Jun>",
  "ok_count": <int>,
  "total": <int>,
  "rows": [
    {"label": "<schedule label>", "status": "<OK|STALE|FAILED>",
     "age_str": "<e.g. 2h ago>", "error": "<str|null>"}
  ],
  "token_usage": [
    {"job": "<label>", "model": "<str>", "tokens": <int>, "cost_usd": <float>}
  ],
  "outbox_rows": [
    {"script_name": "<str>", "delivered": <bool>, "word_count": <int>,
     "error": "<str|null — BELOW_MIN_WORDS:N if synthesis failed>", "sent_at": "<str>"}
  ]
}
```

**`outbox_rows`** is populated by `_query_telegram_outbox_24h()` — surfaces formatter delivery failures and word-count violations to the health report.

---

### 8. `youtube_monitor` → `youtube_monitor_telegram`

```json
{
  "script": "youtube_monitor",
  "date_str": "<e.g. 20 Jun>",
  "n_summarised": <int>,
  "videos": [
    {"title": "<str>", "watch_url": "<https://youtu.be/...>",
     "channel_name": "<str>", "summary": "<str|null>"}
  ]
}
```

**Narrative:** the `≥500-word 24h synthesis` generated by `_synthesise_24h()`. If synthesis fails (empty string) the formatter sends the shorter fallback but flags `BELOW_MIN_WORDS:N` in `telegram_outbox.error` so `health_check` surfaces the violation.

---

### 9. `position_sentinel` → `position_sentinel_telegram`

**Script:** `u/admin/position_sentinel`
**Schedule:** On-demand (Phase 1); hourly `0 0 * * * 1-5` YAML ready for Phase 2 activation
**Inputs:** `portfolio_db` (postgresql resource), `deepseek_key` ($var), `xai_key` ($var)
**Trigger families:**
- **(i-a) Price acute** — single session ≥±5% (existing move monitor threshold)
- **(i-b) Price cumulative** — ≤-8%/3d, ≤-12%/5d, ≤-20% vs 20d-high (Phase 1 live)
- **(ii) News materiality** — Deepseek 0–3 score; ≥2 = material; ≥3 = critical/thesis-threatening (logged Phase 1; push Phase 2)
- **(iii) Confluence** — price signal ∧ materiality ≥2 (Phase 2 activation)

**Pure helpers (unit-tested, locked oracle):**
- `_cumulative_drawdowns(closes)` → `{chg_3d, chg_5d, vs_20d_high}`
- `_price_signal(dd, cfg)` → `"price_cumulative"` or `None`
- `_parse_materiality(llm_str)` → int 0–3, clamped; blank → `None`
- `_aggregate_materiality(events)` → max score for ticker
- `_confluence(price_sig, max_materiality)` → bool
- `_url_hash(url)` → dedup key for `position_events`

**DB tables written:**
- `position_events` — `(ticker, url_hash, headline, source, materiality_score, fetched_at)` — one row per news item scored
- `position_signals` — `(ticker, signal_type, detail JSONB, fired_at)` — one row per triggered alert

**Pseudocode:**
```
1. fetch portfolio_positions → tickers[]
2. for each ticker:
   a. fetch last 20 closes from price_history
   b. dd = _cumulative_drawdowns(closes)
   c. price_sig = _price_signal(dd, cfg)
   d. if price_sig: write position_signals; queue for formatter
   e. fetch Google News RSS (feedparser) → headlines[]
   f. for each headline not in position_events (url_hash dedup):
        score = _triage_news(headline, ticker, deepseek_key)
        write position_events
3. for each queued signal: dispatch position_sentinel_telegram
```

**Front-matter contract (canonical .md):**
```json
{
  "script": "position_sentinel",
  "ticker": "<str>",
  "signal_type": "<price_cumulative|price_acute|news_material|confluence>",
  "chg_3d": <float|null>,
  "chg_5d": <float|null>,
  "vs_20d_high": <float|null>,
  "max_materiality": <int|null>,
  "top_headline": "<str|null>",
  "fired_at": "<ISO str>"
}
```

**Phase roadmap:**
- Phase 1 (live): cumulative-price alerts; news materiality logged only
- Phase 2: confluence push + Grok-4.3 synthesis dispatch on critical signals
- Phase 3: thesis-aware triage (requires `portfolio_thesis` seeded — now done)

---

### 10. `affection_ping` (non-report — Hard Rule 16 exempt)

**Not part of the md-driven formatter architecture.** This is a standalone hourly sticker ping, not a financial report. Rule 16 (≥500-word report) is exempt — see `shared/override_log.md`.

**Script:** `u/admin/affection_ping`
**Schedule:** `0 */2 9-23 * * *` (9AM–11PM SGT every 2 hours)
**Output:** One `sendSticker` API call with a Deepseek-generated one-sentence caption to the configured Telegram group.

**Pseudocode:**
```
1. now = datetime.now(SGT); if hour < 8 or hour > 22: return {skipped: True}
2. packs = parse comma-separated affection_sticker_packs
3. all_stickers = []
   for pack in packs:
     GET getStickerSet?name={pack}
     if ok: all_stickers.extend(stickers)
   if empty: raise RuntimeError
4. sticker = random.choice(all_stickers); file_id = sticker.file_id
5. caption = Deepseek one-sentence affectionate message (temp=0.9, max_tokens=80)
   fallback: random from _FALLBACK_CAPTIONS list
6. POST sendSticker {chat_id: affection_group_id, sticker: file_id, caption: caption}
7. INSERT INTO affection_outbox (recipient_id, sticker_pack, sticker_file_id,
     caption, llm_model, delivered, error)
8. return {sent_at, group_id, sticker_pack, file_id, caption, delivered, error}
```

**DB table:** `affection_outbox` in the `affection` database (separate from `portfolio` since 2026-06-30 — Hermes/OpenClaw cannot reach it). Isolated from `telegram_outbox` — no `word_count` column, not audited by `health_check`.

**Windmill variables:** `u/admin/affection_group_id` (negative group chat_id), `u/admin/affection_sticker_packs` (11 packs: `BubuDudu`, `Kittylove`, `PusheenTheCat`, `LoveDove`, `catlove2`, `LoveKitten`, `Cute_couple`, `PenguinsLove`, `BunnyAndBear`, `BearAndBunny`, `peachlovesgoma`). Windmill resource `u/admin/affection_db` (postgresql, points at the `affection` database).

---

### 11. `idea_extractor` (Idea Pipeline — Plan A, 2026-06-27)

**Script:** `u/admin/idea_extractor`
**Trigger:** Dispatched by `youtube_monitor` (after every 6h scan) and `morning_news_digest` (daily 6:30 AM SGT).
**Output:** `watchlist_ideas` rows (status: pending), one per extracted ticker with source='youtube' or 'news'.

**Pseudocode:**
```
1. content = read .md file from md_path
2. if content empty: return
3. call Deepseek (deepseek-chat) with owner-approved extraction prompt (temp=0, max_tokens=512)
4. parse JSON response via _parse_extraction_response(raw) → [{ticker, reason}, ...] or None
5. sanitise tickers (skip non-tickers: single letters, "S&P 500", "tech sector", >5 chars)
6. for each extracted pair: INSERT INTO watchlist_ideas (ticker, source, source_ref, reason, status='pending')
   ON CONFLICT (ticker, source) DO NOTHING
```

**Cost:** ~$0.001/extraction (2000 tokens input, 200 output). ~$0.005/day at current scan rate.

---

### 12. `candidate_prescreener` (Idea Pipeline — Plan A, 2026-06-27)

**Script:** `u/admin/candidate_prescreener`
**Trigger:** Dispatched by `portfolio_rationalization` after report generation (Saturday 6 AM SGT).
**Output:** `watchlist_ideas.status` updated → `shortlisted` (rank ≤15) or `archived`.

**Pseudocode:**
```
1. read pending candidates from watchlist_ideas WHERE status='pending'
2. auto-exclude: already-held positions (from portfolio_positions), PASS verdicts within 30 days
3. for each remaining candidate: dispatch stock_data_fetcher (batches of 5)
4. for each candidate with quant data:
   a. build union pool = 33 holdings + candidate
   b. call _compute_factor_scores(union_pool, fund) from factor_scorer
   c. inject neutral thesis (score=0.5) → _apply_thesis_scores
   d. call _compute_composites → get candidate's balanced composite
5. insert candidates into holdings ranking via compute_candidate_ranks
6. rank ≤15 → status='shortlisted', rank >15 → status='archived'
7. if any shortlisted: dispatch candidate_eval with watchlist_pull=True
```

**Key design:** Uses the same 5-factor scoring formulas as rationalization (via `factor_scorer`). Candidates are scored within the union pool (holdings + candidate), not standalone. Neutral thesis score (0.5) ensures no penalty/credit for unvetted candidates.

---

### 13. `factor_scorer` (shared module — Plan A, 2026-06-27)

**Path:** `u/admin/factor_scorer.py`
**Used by:** `portfolio_rationalization`, `candidate_prescreener`
**Exports:** `_cagr`, `_evaluate_red_flags`, `_norm`, `_compute_factor_scores`, `_apply_thesis_scores`, `_compute_composites`, `_rank_positions`

All functions are pure arithmetic — no DB reads, no I/O. Operate only on passed-in dicts/lists.
