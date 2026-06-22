# Search API Audit — 2026-06-12

**Purpose:** Evaluate all search/data retrieval APIs available via keys against what is actually used in `research_tool.py`. Record endpoints, parameters, pricing, and live test results. Produce recommendations for stack changes (to be implemented in a separate session).

**Test queries used:**
- `"NVIDIA Q2 2026 earnings results"` — high-coverage ticker, widely indexed
- `"MAS Singapore monetary policy SGD outlook 2026"` — macro, moderate coverage
- `"Asia Pacific infrastructure project finance debt spreads 2026"` — niche, sparse coverage

---

## Current Stack in research_tool.py

| API | Endpoint | Cost/call | Depth used | Notes |
|---|---|---|---|---|
| Google News RSS | `news.google.com/rss/search` | Free | All | No key needed |
| Perplexity Search API | `api.perplexity.ai/search` | $0.005 | All | Batch multi-query |
| Exa | `api.exa.ai/search` | $0.007 | Standard + deep | Neural/semantic |
| Finnhub | `finnhub.io/api/v1/company-news` | Free (key) | All | News + fundamentals |
| Seeking Alpha RSS | seekingalpha XML | Free | All | Scraping |
| yfinance | Python lib | Free | All | Library call |
| SEC EDGAR | `sec.gov` public | Free | Deep + US only | 10-K/10-Q/8-K |
| Grok-4.3 (xAI) | `api.x.ai/v1` | $1.25/$2.50 per 1M in/out | All | Synthesis |
| Deepseek | `api.deepseek.com` | ~$0.15/$0.28 per 1M | All | Fallback synthesis |

---

## Perplexity Product Family

Perplexity offers three separate products. We use the Search API, which is the right choice.

### Search API (current — `POST https://api.perplexity.ai/search`)

**Pricing:** $5.00 per 1,000 requests ($0.005 flat, no token charges)

**Key parameters:**

| Parameter | Values | Status |
|---|---|---|
| `query` | string or array (batch) | ✅ Used (batch) |
| `max_results` | 1–20 | ✅ Used (3/5/10 by depth) |
| `search_context_size` | `low` / `medium` / `high` | ✅ Used (`high` always) |
| `search_recency_filter` | `hour` / `day` / `week` / `month` / `year` | ⚠️ **Not set** |
| `max_tokens_per_page` | integer | ⚠️ **Not set** |
| `search_after_date_filter` | MM/DD/YYYY | Not set |
| `search_domain_filter` | array, max 20 domains | Not set |

**Live test — recency filter impact:**

| Config | Latency | Top result dates |
|---|---|---|
| No filter (current) | 864ms | Mixed: 2025-08-27, 2026-02-25, some no-date |
| `search_recency_filter: "month"` | 1619ms | All May 2026 — highly relevant |

Adding `search_recency_filter: "month"` for stock/news queries would significantly improve result freshness at the cost of ~750ms extra latency. Worth doing.

**Docs:** https://docs.perplexity.ai/api-reference/search-post

---

### Sonar API (`POST https://api.perplexity.ai/chat/completions`)

LLM-wrapped search — search runs inside a chat completion, returns a synthesised answer.

**Pricing:** $5–$14 per 1K requests (by context size) + token rates on top.

**Verdict: ❌ Not suitable.** We use Grok-4.3 for synthesis. Paying for Perplexity's LLM on top adds cost with no benefit.

---

### Agent API (`POST https://api.perplexity.ai/v1/agent`)

Multi-provider LLM interface with tool invocations. Tools called as part of a completion, not standalone.

**Tool pricing:**

| Tool | Cost | What it returns |
|---|---|---|
| `web_search` | $0.005/call | Web results — same data as Search API, no advantage |
| `fetch_url` | **$0.0005/call** | Full page content from a given URL |
| `finance_search` | $0.005/call | SEC filings, company info, structured market data |
| `people_search` | $0.005/call | Professional profiles |
| `sandbox` | $0.03/session | Code execution |

**`fetch_url` note:** At $0.0005/URL this is the cheapest article extractor available. Current code uses `requests.get()` directly (free but no JS rendering). Perplexity `fetch_url` is worth evaluating as a replacement for full-text article fetching in standard/deep research runs.

**`finance_search` note:** Returns "SEC filings, company info, investment insights" — vague. Potentially useful for unstructured financial context that Finnhub doesn't cover. Not audited live.

**Docs:** https://docs.perplexity.ai/docs/agent-api/tools

---

## Exa — Extended Evaluation

Exa is currently used at standard + deep depth. The initial audit (NVIDIA query only) suggested it found SEC filings that Perplexity missed. Extended testing revealed the full picture.

### Test 1 — High-coverage ticker: NVIDIA Q2 2026 earnings

| Config | Latency | Results | Top dates |
|---|---|---|---|
| Exa, no date filter | 1,053ms | 5 | 2025-08-27, 2025-08-27, no-date, no-date, no-date |
| Exa, `startPublishedDate: "2026-05-01"` | 1,297ms | 5 | 2026-05-20, 2026-06-02, 2026-05-20, 2026-05-21, 2026-05-23 |

With date filter, result #1 was the actual **NVDA 8-K SEC filing** from SEC.gov, result #3 was the **10-Q**. However: the research tool already fetches EDGAR filings for free via `_fetch_edgar_filings()` using the sec.gov public API. Exa was not the source of EDGAR content in the current tool — it was a coincidental finding. Exa's actual use in the tool is general news/analysis retrieval.

### Test 2 — Perplexity with `search_domain_filter: ["sec.gov"]`

Result: Perplexity retrieved the same NVDA 8-K (sec.gov filing, 2026-05-20) as result #1, in 536ms at $0.005. Confirmed: SEC filings are accessible directly through Perplexity with domain filtering — no Exa required for this use case.

### Test 3 — Thin-coverage macro topic: MAS Singapore monetary policy

| API | Latency | Sources | Dates | Quality |
|---|---|---|---|---|
| Perplexity (recency=month) | 919ms | Straits Times, CNBC, MUFG Research, investinglive | All May 2026 | ✅ Fresh, diverse |
| Exa (startPublishedDate=2026-04-01) | 3,724ms | Business Times, ING Think, CNA, MarketScreener, The Star | All Apr 14 2026 | ⚠️ Clustered around single MAS event |

Perplexity wins — fresher (May vs April), more diverse, 4× faster.

### Test 4 — Niche specialist topic: Asia Pacific infra debt spreads

| API | Latency | Sources | Quality |
|---|---|---|---|
| Perplexity (recency=month) | 647ms | CDP guide, LSEG EM bonds, Morgan Stanley EM Debt Monitor, BIX Malaysia | General EM debt results, partially tangential |
| Exa (startPublishedDate=2026-04-01) | 3,731ms | **SIPA infra300 Debt Index**, **CFA Research Foundation**, Schroders Asia insurer infra, **AllianzGI APAC Credit Fund close** | Specialist industry sources — infra debt indices, private credit reports |

Exa wins on niche specialist topics. Neural search surfaces industry-specific documents (infra300 index, CFA Research Foundation papers) that keyword search doesn't prioritise. This is directly relevant to project and strategy research queries.

### Exa Verdict

**Drop from standard tier for `research_type: stock`.** For covered tickers, Perplexity returns equivalent or better results 4× faster and $0.002 cheaper. Neural search advantage doesn't materialise on high-coverage topics.

**Keep in standard tier for `research_type: project` and `research_type: strategy`**, and in all deep-tier research. This is where Exa earns its cost — it finds specialist financial documents (debt indices, private credit research, CFA papers) that keyword search misses.

**Add `startPublishedDate` to Exa calls** (same fix as Perplexity recency filter) — without it, Exa anchors on historical canonical documents.

| research_type | Brief | Standard | Deep |
|---|---|---|---|
| stock | — | ❌ Drop Exa | ✅ Keep Exa |
| macro | — | ✅ Keep Exa | ✅ Keep Exa |
| strategy | — | ✅ Keep Exa | ✅ Keep Exa |
| project | — | ✅ Keep Exa | ✅ Keep Exa |

---

## Web Search APIs (unused, have keys)

### Serper.dev

**Key:** `keys.md`
**Pricing:** $0.0003/query (2,500 free on signup)
**Rate limit:** Not documented; delivers in 1–2s

**Endpoints** (all at `google.serper.dev/<type>`):

| Endpoint | Type | Notes |
|---|---|---|
| `/search` | Web search | Organic, featured snippets, knowledge panel |
| `/news` | News | High freshness, 20+ results |
| `/images` | Image search | |
| `/videos` | Video search | |
| `/scholar` | Academic papers | |
| `/patents` | Patent search | |
| `/shopping` | E-commerce | |
| `/places` | Local / maps | |
| `/autocomplete` | Query suggestions | |

**Key parameters:** `q`, `num` (results count), `type`, `country`, `location`, `gl` (geo)

**Live test results:**

| Endpoint | Latency | Count | Top result dates |
|---|---|---|---|
| `/search` | 611ms | 9 | Aug 2025, Feb 2026, no-date (IR pages) |
| `/news` | 826ms | 23 | 6h, 10h, 14h, 2d — very fresh |

**Verdict: ✅ Strong candidate.** 16× cheaper than any other API. News endpoint returns very fresh results with high volume. Google-based results with structured JSON. Worth adding as a second news source layer, especially for the brief/standard research tiers.

**Docs:** https://serper.dev/ (see API reference in dashboard)

---

### Brave Search API

**Key:** `keys.md`
**Pricing:** $0.005/query ($5/K), $5 free monthly credit, 50 req/s capacity

**Endpoints:**

| Endpoint | Path | Notes |
|---|---|---|
| Web Search | `GET /res/v1/web/search` | Ranked results + snippets |
| News Search | `GET /res/v1/news/search` | News articles |
| LLM Context | `GET/POST /res/v1/llm/context` | Retrieval output shaped for LLM consumption |
| Images | `GET /res/v1/images/search` | |
| Videos | `GET /res/v1/videos/search` | |
| Summarizer | `GET /res/v1/summarizer/search` | |
| Answers | `POST /res/v1/chat/completions` | Grounded answer generation |
| Local POIs | `GET /res/v1/local/pois` | |
| Autosuggest | | $0.0005/query |
| Spellcheck | | $0.0005/query |

**Key parameters:** `q`, `count` (max 20), `offset`, `freshness` (pd/pw/pm/py or custom), `country`, `search_lang`, `extra_snippets` (up to 5 extra excerpts), `safesearch`

**Live test results:**

| Endpoint | Latency | Count | Top result dates |
|---|---|---|---|
| Web (`freshness=pm`) | 723ms | 5 | 1d, 1d, 2d, 3w, 3w |
| News (`freshness=pm`) | 511ms | 5 | 6h, 1d, 3w, 3w, 3w |

**Verdict: ⚠️ Viable but same price as Perplexity.** Independent crawl (not Google) gives different result set. `freshness` filter works well. Not meaningfully better than current Perplexity stack for the cost. Could be useful as a diversity layer for deep research. Would primarily substitute Perplexity, not complement it cheaply.

**Docs:** https://api-dashboard.search.brave.com/app/documentation/web-search/get-started

---

### Tavily

**Key:** `keys.md`
**Pricing:** $0.008/credit (basic/fast = 1 credit; advanced = 2 credits). 1K free credits/month.

**Endpoint:** `POST https://api.tavily.com/search`

**Key parameters:**

| Parameter | Values | Notes |
|---|---|---|
| `query` | string | |
| `search_depth` | `basic` / `advanced` / `fast` / `ultra-fast` | advanced = 2× cost |
| `topic` | `general` / `news` / `finance` | **Finance topic for structured financial queries** |
| `time_range` | `day` / `week` / `month` / `year` | Freshness filter |
| `start_date` / `end_date` | YYYY-MM-DD | Precise date window |
| `include_raw_content` | bool / `markdown` / `text` | Returns full article text |
| `chunks_per_source` | 1–3 | Max snippets per source (advanced only) |
| `max_results` | 0–20 | Default 5 |
| `include_answer` | bool / `basic` / `advanced` | LLM answer |
| `include_domains` / `exclude_domains` | arrays | Domain filter |
| `auto_parameters` | bool | Auto-select depth/settings |

**Live test results:**

| Config | Latency | Count | Dates |
|---|---|---|---|
| `topic=finance, depth=basic, time_range=month` | 1110ms | 5 | **None returned** |

Results were topically relevant (NVIDIA earnings) but publication dates were absent from the response, making it impossible to verify recency. This is a blocker for our pipeline which validates date cutoffs (Hard Rule 14).

**Verdict: ⚠️ Interesting `finance` topic specialisation but date transparency issue.** `include_raw_content` is useful for reducing separate article-fetch calls. Date issue needs investigation before adopting. Test with `include_usage: true` to verify credit accounting.

**Docs:** https://docs.tavily.com/documentation/api-reference/endpoint/search

---

### Linkup.so

**Key:** `keys.md`
**Pricing:** Varies by endpoint and depth. 4,000 free queries on signup.

**Endpoints and pricing:**

| Endpoint | Config | Cost |
|---|---|---|
| `POST /v1/search` | `depth=standard, outputType=searchResults` | $0.005 |
| `POST /v1/search` | `depth=standard, outputType=sourcedAnswer/structured` | $0.006 |
| `POST /v1/search` | `depth=deep, outputType=searchResults` | $0.05 |
| `POST /v1/search` | `depth=deep, outputType=sourcedAnswer/structured` | $0.055 |
| `GET /v1/fetch` | `renderJs=false` | $0.001 |
| `GET /v1/fetch` | `renderJs=true` | $0.005 |
| `POST /v1/research` | `reasoningDepth=S` | $0.25 |
| `POST /v1/research` | `reasoningDepth=M` | $0.50 |
| `POST /v1/research` | `reasoningDepth=L` | $1.50 |
| `POST /v1/research` | `reasoningDepth=XL` | $2.50 |

**Live test results:**

| Config | Latency | Count | Dates |
|---|---|---|---|
| `depth=standard, outputType=searchResults` | **6,605ms** | 20 | None |

6.6 second latency is prohibitive. Research tool already runs in 60-90s; adding a 6.6s source per query would significantly extend runtime.

**Verdict: ❌ Too slow for batch use in research pipeline.** `/v1/fetch` at $0.001/URL (no-JS) is interesting as a cheap article extractor — not tested. Research endpoint ($0.25–$2.50) is the most expensive product evaluated and duplicates our Grok synthesis approach.

**Docs:** https://docs.linkup.so/pages/documentation/development/pricing

---

### Google Custom Search JSON API

**Key + CSE ID:** `keys.md`
**Pricing:** $0.005/query, 100 free/day

**⚠️ SUNSET NOTICE: Google closed this API to new customers. Existing customers supported until January 1, 2027.** Do not build new integrations on this. Plan replacement before 2027.

**Docs:** https://developers.google.com/custom-search/v1/overview

---

### NewsAPI.org

**Key:** `keys.md`
**⚠️ Developer plan (free tier) is localhost-only** — cannot be used from VPS in production. Production plans start at $449/month.

**Verdict: ❌ Not viable.** Developer key only works from localhost. $449/month is out of budget.

**Docs:** https://newsapi.org/docs

---

### Supadata.ai

**Key:** `keys.md`
**Note: This is NOT a web search API.** Supadata provides transcript extraction from video platforms and web scraping.

**Endpoints:**

| Endpoint | Cost | Purpose |
|---|---|---|
| `GET /v1/transcript` | 1–2 credits | YouTube, TikTok, Instagram, X, video files |
| `GET /v1/metadata` | 1 credit | Video metadata |
| `GET /v1/youtube/search` | 1 credit | YouTube search |
| `GET /v1/youtube/channel` | 1 credit | Channel data |
| `GET /v1/web/scrape` | 1 credit | Single page scrape |
| `POST /v1/web/crawl` | 1 + 1/page | Site crawl |

**Verdict: ✅ Already in use (indirectly).** YouTube transcripts are fetched via RapidAPI key, which wraps a service like Supadata. If RapidAPI becomes expensive or unreliable, Supadata is a direct fallback. Not relevant to news/research search.

**Docs:** https://docs.supadata.ai

---

## URL Fetching / Article Extraction

Current research_tool.py fetches article full text via `requests.get()` for Exa results and direct URLs. Options:

| Method | Cost | JS rendering | Notes |
|---|---|---|---|
| Direct `requests.get()` | Free | No | Current; fails on JS-rendered pages |
| Perplexity `fetch_url` | $0.0005/URL | Unknown | Cheapest paid option; requires Agent API call |
| Linkup.so `/fetch` (no-JS) | $0.001/URL | No | Not tested |
| Linkup.so `/fetch` (JS) | $0.005/URL | Yes | Not tested |
| Firecrawl | Have key | Yes | Pricing not audited |
| ScrapingBee | Have key | Yes | Pricing not audited |

Perplexity `fetch_url` at $0.0005 is 10× cheaper than any JS-rendering alternative. Worth evaluating for standard/deep research runs where full article text adds synthesis quality.

---

## Finance-Specific APIs

See existing audit files for full results:
- `docs/audit/260605_fundamentals_api_audit.md` — field-by-field source mapping for Finnhub, yfinance, AlphaVantage, FMP
- `docs/audit/260605_api_endpoint_full_audit.md` — full endpoint audit: news, earnings, financials, macro, commodities, insider across all 4 sources

**Supplement — Perplexity `finance_search` tool:**
- Returns: "SEC filings, company info, investment-related insights" per docs
- Cost: $0.005/invocation
- Not live-tested. Could supplement Finnhub for unstructured financial context. Requires Agent API integration (not Search API).

---

## Sunset / Deprecated APIs

| API | Status | Action |
|---|---|---|
| Google Custom Search JSON API | Sunset Jan 2027 (existing customers only) | Plan replacement before 2027. Replace with Serper.dev (same Google base, 16× cheaper) |
| NewsAPI.org (current key) | Developer plan = localhost-only | Key is unusable from VPS. Mark as dead. |

---

## Recommendations — Approved for Implementation

### Changes to research_tool.py

| # | Change | Tiers affected | Cost impact |
|---|---|---|---|
| 1 | Add `search_recency_filter: "month"` to `_fetch_perplexity_batch` | All | None |
| 2 | Add `startPublishedDate` (30-day lookback) to `_fetch_exa_query` | Standard + deep | None |
| 3 | Drop Exa for `research_type: stock` at standard depth | Standard stock | −$0.007/run |
| 4 | Add `_fetch_serper_news` at brief + standard depth | Brief + standard | +$0.0003/run |
| 5 | Add `serper_key` param to `main()` | All | — |
| 6 | Move EDGAR 8-K fetch to standard depth (US stock only); keep 10-K/10-Q deep-only | Standard | Free |
| 7 | Add `forms` param to `_fetch_edgar_filings`; standard passes `["8-K"]`, deep passes `None` (all) | Standard + deep | Free |

### Stack by tier after changes

| Source | Brief | Standard (stock) | Standard (macro/project/strategy) | Deep |
|---|---|---|---|---|
| Google News RSS | ✅ | ✅ | ✅ | ✅ |
| Perplexity + recency filter | ✅ | ✅ | ✅ | ✅ |
| Serper news (new) | ✅ | ✅ | ✅ | ✅ |
| Exa + date filter | — | ❌ removed | ✅ | ✅ |
| EDGAR 8-K (expanded) | — | ✅ new | — | ✅ |
| EDGAR 10-K/10-Q | — | — | — | ✅ |
| Finnhub news | ✅ (US stock) | ✅ (US stock) | — | ✅ (US stock) |
| Seeking Alpha RSS | ✅ (stock) | ✅ (stock) | — | ✅ (stock) |
| yfinance news | ✅ (stock) | ✅ (stock) | — | ✅ (stock) |

### Keep (no change)

| API | Reason |
|---|---|
| Perplexity Search API | Right product; $0.005 flat; batch support |
| Exa | Keep for project/strategy/macro standard + all deep |
| Google News RSS | Free; remove only if Serper proves fully redundant |
| Finnhub, yfinance, Seeking Alpha | Free; no reason to remove |

### Drop / Flag

| API | Action |
|---|---|
| Google Custom Search | Sunset Jan 2027 — replace with Serper (same Google base, 16× cheaper) |
| NewsAPI.org key | Unusable from VPS (developer plan = localhost only). Dead key. |
| Brave Search | Same price as Perplexity, no quality advantage — skip |
| Tavily | Date transparency issue blocks adoption (Hard Rule 14). Re-evaluate when fixed. |
| Linkup.so | 6.6s latency — too slow for batch pipeline |
| Supadata.ai | Not a search API — YouTube transcript fallback only |

---

## Source Documentation Index

| API | Documentation URL |
|---|---|
| Perplexity Search API | https://docs.perplexity.ai/api-reference/search-post |
| Perplexity Pricing | https://docs.perplexity.ai/docs/getting-started/pricing |
| Perplexity Agent API Tools | https://docs.perplexity.ai/docs/agent-api/tools |
| Serper.dev | https://serper.dev/ (dashboard has API reference) |
| Brave Search API | https://api-dashboard.search.brave.com/app/documentation/web-search/get-started |
| Brave Pricing | https://api-dashboard.search.brave.com/documentation/pricing |
| Tavily | https://docs.tavily.com/documentation/api-reference/endpoint/search |
| Google Custom Search | https://developers.google.com/custom-search/v1/overview |
| Linkup.so Pricing | https://docs.linkup.so/pages/documentation/development/pricing |
| NewsAPI.org | https://newsapi.org/docs |
| Supadata.ai | https://docs.supadata.ai |
| Exa Pricing | https://exa.ai/pricing |
