# Open-Source Research Agent Audit — 2026-06-12

## Purpose

Evaluate the current landscape of open-source autonomous research agents to determine:
1. Whether any are worth adopting wholesale to replace or augment `research_tool.py`
2. What capability gaps exist in our stack relative to the best available alternatives
3. Which selective improvements are worth backporting

Conducted as part of the ongoing search API and tooling audit series. See also `260612_search_api_audit.md` (search API evaluation) and `260605_api_endpoint_full_audit.md` (financial data API audit).

---

## Scope

Agents evaluated: Claude Code (this system, used to conduct this research), GPT Researcher, STORM/Co-STORM, Vane (Perplexica), HuggingFace Open Deep Research (smolagents), LangChain Open Deep Research, DeerFlow 2.0, FinSight, FinRobot.

Benchmark data: FinDeepResearch (Oct 2025), FinDeepForecast (Jan 2026), Deep FinResearch Bench (Apr 2026).

All live GitHub metadata (stars, forks, release dates) as of 2026-06-12.

**Note on methodology:** This audit was itself produced using Claude Code as a research agent (subagent with WebSearch + WebFetch tools). The capabilities used to produce this report are therefore directly observable and are evaluated in Section 3 below alongside the external agents.

---

## Our Current Stack (Baseline)

For comparison purposes, the system being evaluated against is:

**`u/admin/research_tool` (Windmill script)**
- Query decomposition: Deepseek-chat
- Search sources: Google News RSS + Perplexity Search API (`search_recency_filter: "month"`) + Serper.dev news (`brief`/`standard`, $0.0003/call) + Exa neural search (non-stock at `standard`, all at `deep`, 30-day `startPublishedDate`) + Finnhub company news (US tickers) + Seeking Alpha RSS + yfinance news
- Financial data: yfinance quarterly financials (income/balance/CF), SEC EDGAR 8-K (`standard`+`deep`), 10-K/10-Q MD&A (`deep` only)
- Portfolio context: live PostgreSQL query (`price_history` + `fundamental_data`) injected into synthesis prompt
- Synthesis: Grok-4.3 (`reasoning_effort` scales low/medium/high with depth, `max_tokens` 1500/3000/6000)
- Tiered cache: auto-adjusts dispatch depth based on prior research age (<30d → brief, 30–90d → standard, >90d → deep)
- Output: markdown report + PostgreSQL `research_reports` upsert + email to `<YOUR_RECIPIENT_EMAIL>`
- Depth cost estimate: brief ~$0.03 | standard ~$0.06 | deep ~$0.12

**Telegram Agent (`root-straitsagent-1`)**
- Natural language intent classification → dispatches `research_tool` as a Windmill job
- 11 command intents: research, earnings, portfolio, news, youtube, macro, thesis, health, search, digest, prices
- W4 multi-step reasoning: planner.py for `portfolio_analysis`, `thesis_check`, `macro_brief`
- Earnings pipeline: pre/post analysis auto-dispatched from `portfolio_earnings_alert.py`

---

## Claude Code as a Research Agent — How This Audit Was Produced

This section documents the actual capabilities used to conduct this research, which were not evaluated in the original comparison. Claude Code is itself a research agent and belongs in this comparison.

### What Claude Code did to produce this report

1. **Task decomposition** — broke the research brief into per-agent sub-tasks and identified benchmark sources to find
2. **Spawned a general-purpose subagent** with a detailed prompt covering all 8 agents and 3 benchmark studies
3. **WebSearch** — ran ~20–30 targeted searches across GitHub, arXiv, documentation sites, and comparison articles (queries like "gpt-researcher deep research architecture 2026", "FinDeepResearch benchmark arxiv", "DeerFlow bytedance capabilities", etc.)
4. **WebFetch** — fetched and read ~10–15 source URLs directly: GitHub READMEs, arXiv paper abstracts, documentation pages (docs.gptr.dev, huggingface.co/blog), deep-link pages within repos
5. **Synthesis** — combined all findings into a structured comparison in a single pass
6. **Document authoring** — wrote the full audit markdown, then separately composed and sent the email via SMTP

**Observed metrics:** 40 tool uses, 56,713 tokens consumed, ~7 minutes elapsed.

### Claude Code capability profile

| Capability | Detail |
|---|---|
| **Search mechanism** | WebSearch (provider not disclosed by runtime) + WebFetch (direct URL read of any public page) |
| **Search depth** | Fully adaptive — decides how many searches to run and what to look for next based on what each search returns |
| **Sub-question decomposition** | Native LLM reasoning — decomposes topics, identifies gaps, decides follow-up searches in real time |
| **Parallel subagents** | Can spawn multiple subagents in parallel via Agent tool — independent context windows, different specialisations |
| **Code execution** | Yes — Bash and Python directly on the VPS; can call any API, run scripts, read/write files mid-research |
| **File system access** | Yes — Read, Write, Edit tools; can incorporate local documents, database dumps, prior research files |
| **LLM quality** | Claude Sonnet 4.6 / Opus (frontier model) |
| **Structured financial data** | None natively — would require explicit Bash/Python calls to yfinance, Finnhub, EDGAR |
| **Cost per research run** | Not tracked per-run; billed as Claude Code usage (not visible as $ per task) |
| **Output format** | Ad hoc — produces whatever the task requires; no standard template |
| **Persistence** | Session memory only; file-based memory across sessions (`/root/.claude/projects/`); no structured research DB |
| **Scheduling / automation** | Cannot self-schedule; requires a live session |
| **Delivery** | Outputs to conversation; email via Python smtplib when instructed |

### Claude Code vs research_tool.py — direct comparison

| Dimension | Claude Code | research_tool.py |
|---|---|---|
| **Search adaptability** | ✅ Fully adaptive — changes direction based on findings | ❌ Fixed query count (3/5/10), single decomposition pass |
| **Source flexibility** | ✅ Any public URL, any search query, GitHub, arXiv, PDFs | ❌ Constrained to configured source list |
| **Structured financial data** | ❌ None natively | ✅ Finnhub + yfinance + EDGAR + portfolio DB |
| **Portfolio context** | ❌ Only what user provides in conversation | ✅ Live PostgreSQL query per run |
| **Cost transparency** | ❌ Opaque within Claude Code billing | ✅ Token count + USD cost logged per run |
| **Persistence / cache** | ❌ Session-scoped; file memory only | ✅ PostgreSQL research_reports + 90-day tiered cache |
| **Automation** | ❌ Requires live session | ✅ Windmill scheduling + Telegram dispatch |
| **Reproducibility** | ❌ Ad hoc searches, non-reproducible | ✅ Same sources, same order, same structure every run |
| **Report template** | ❌ Free-form | ✅ Structured markdown with cost/source header |
| **Reasoning quality** | ✅ Can reason about conflicting evidence, flag uncertainty, adjust approach | ❌ Single synthesis pass, no meta-reasoning about source quality |
| **Code execution mid-research** | ✅ Can run Python, fetch APIs, compute values inline | ✅ Runs inside Windmill worker (same capability, different context) |
| **Multi-step task handling** | ✅ Can chain research → analysis → document → email → commit in one session | ❌ Single-purpose: retrieve → synthesise → email |

### Where Claude Code fits in the agent landscape

Architecturally, Claude Code is closest to **HuggingFace Open Deep Research (smolagents)** — a code-first agent that writes and executes code to call tools, with adaptive multi-step reasoning. The key differentiator vs all evaluated open-source agents is that Claude Code is backed by a frontier LLM (Claude Sonnet/Opus) whereas most open-source agents default to GPT-4 or Deepseek.

**Practical division of labour:**

| Use case | Right tool | Why |
|---|---|---|
| One-off research on a new topic (this audit) | Claude Code | Adaptive, flexible, no setup; good for breadth-first exploration |
| Repeatable stock research on portfolio tickers | research_tool.py | Structured financial data, cost tracking, cache, automation |
| Scheduled / unattended research | research_tool.py | Windmill scheduling, no live session needed |
| Research requiring live portfolio context | research_tool.py | PostgreSQL positions + fundamentals pre-wired |
| Multi-source ad hoc investigation | Claude Code | Can read any URL, follow citations, synthesise across diverse source types |
| Research to be shared externally | Neither (currently) | Neither produces client-ready formatted output without further work |

---

## Agent Evaluations

### 1. GPT Researcher (`assafelovic/gpt-researcher`)

**Repository:** https://github.com/assafelovic/gpt-researcher  
**Docs:** https://docs.gptr.dev  
**Stars/Activity:** 27,600 stars, 3,700 forks, 2,980 commits. Release v3.5.0 shipped 2026-05-28. Actively maintained (178 open issues, regular merge cadence).

#### Architecture

Planner-executor-publisher pattern with three core components:

- **`ResearchConductor`** — decomposes the research topic into sub-questions
- **`BrowserManager` + `WorkerPool`** — parallel scraping of sources
- **`ContextManager`** — compresses findings to fit LLM context windows (smart aggregation, not naive truncation)
- **`ReportGenerator`** — synthesises into final output

Two research modes:

| Mode | Mechanism | Time | Cost (o3-mini High) |
|---|---|---|---|
| **Standard** | Single-pass parallel retrieval | 30–60s | Cents |
| **Deep Research** | Recursive breadth/depth tree | ~5 min | ~$0.40 |

Deep Research config: `deep_research_breadth=4` (parallel queries per node), `deep_research_depth=2` (recursion levels), `deep_research_concurrency=2`. Maintains ~25k word context window across the full tree. Uses reasoning models at "High" effort for final synthesis.

#### Search Sources

Configurable via `RETRIEVER` env var. Multiple retrievers can be chained (`RETRIEVER=tavily,exa`):

| Retriever | Type | Notes |
|---|---|---|
| Tavily | Web search API | Default |
| Bing | Web search API | Microsoft |
| Google Custom Search | Web search API | Requires API key + CSE |
| Serper.dev | Web search API | Google-based |
| DuckDuckGo | Web search | Free, no key |
| SearchAPI | Web search | Aggregator |
| SearXNG | Meta-search engine | Self-hosted |
| Exa | Neural search API | |
| ArXiv | Academic preprints | STEM focus |
| PubMedCentral | Medical literature | Niche |

No native financial data retriever. Financial content accessed only via general web search.

#### Finance Capability

Weak. No structured financial data APIs. No EDGAR, no Finnhub, no yfinance integration. Example in docs: "strategic risks for NVIDIA" — corporate narrative only, not quantitative analysis. Does not distinguish between research types (stock vs macro vs strategy).

#### Output Format

2,000+ word markdown reports. Exportable to PDF, Word. Inline citations. Optional AI-generated illustrations. No financial statement tables, no portfolio context, no cost header.

#### Deployment

pip package, Docker, FastAPI server, MCP server (plugs into Claude/Cursor/Cline). Self-hosted only. MIT licence.

#### Cost Model

Free. User pays LLM + search API costs. Deep Research: ~$0.40/task with o3-mini High reasoning. With Deepseek-R1 as the reasoning model: likely $0.05–0.10.

#### Limitations

- No financial data APIs (Finnhub, yfinance, EDGAR absent)
- Deep Research produces ~2,000 words — short for a proper equity note
- No structured quantitative output (no tables, no financial metrics)
- No portfolio context injection
- Cites misinformation as a known risk — "experimental" software disclaimer

#### Verdict

Strong for narrative/thematic research. Not suitable for quantitative equity work without custom retriever extensions. The Deep Research tree recursion pattern is the one architectural idea worth backporting.

---

### 2. STORM / Co-STORM (`stanford-oval/storm`)

**Repository:** https://github.com/stanford-oval/storm  
**Paper (STORM):** https://arxiv.org/abs/2402.14207 (NAACL 2024)  
**Paper (Co-STORM):** EMNLP 2024  
**Stars/Activity:** 28,400 stars, 2,600 forks, 238 commits. Release v1.1.0 shipped January 2025. Activity has slowed — last major update 18 months ago as of this audit.

#### Architecture

Two-stage pipeline:

**Stage 1 — Pre-writing (perspective-guided question asking):**
- Surveys related topics via web search
- Simulates conversations between a "Wikipedia writer" persona and multiple expert personas
- Each persona generates deep follow-up questions that a single query would miss
- Produces a structured outline from the conversation tree

**Stage 2 — Writing:**
- Aggregates all gathered evidence into a full article
- Inline citations linked to retrieved sources

**Co-STORM extension:**
- Three agent roles: LLM experts, Moderator, Human user
- Dynamic hierarchical mind map of gathered concepts
- Turn management protocol allows human steering mid-research
- Trades full autonomy for higher quality on complex topics

#### Search Sources

YouRM, BingSearch, SerperRM, BraveRM, SearXNG, DuckDuckGoSearchRM, TavilySearchRM, GoogleSearch, VectorRM (local documents), AzureAISearch.

Cost-optimised LLM routing: cheaper models for conversation simulation (information gathering), stronger models for final article generation.

#### Finance Capability

Not designed for finance. Output is a Wikipedia-style encyclopaedic article — wrong format for an investment memo. No financial data APIs. Produces narrative background research well, but cannot generate a structured equity note.

#### Output Format

Wikipedia-style long-form article with section headers and inline citations. Not memo or report format. Stanford explicitly states output "requires significant editing before publication."

#### Deployment

Python package, Streamlit demo (local), hosted demo at storm.genie.stanford.edu (70,000+ registered users). Docker available. MIT licence.

#### Limitations

- Slow development cadence — last release January 2025
- Output format is encyclopaedic, unsuitable for an investment note
- No quantitative or structured financial data
- Co-STORM requires manual interaction — not autonomous
- Citation hallucination on smaller source chunks noted in the EMNLP paper

#### Verdict

Best fit for deep company/sector background research before writing your own analysis. The perspective-guided question generation is a thoughtful technique — relevant if implementing a Sub-question Decomposition upgrade in research_tool. Wrong tool as a standalone equity research agent.

---

### 3. Vane / Perplexica (`ItzCrazyKns/Perplexica`)

**Repository:** https://github.com/ItzCrazyKns/Perplexica  
**Stars/Activity:** 35,300 stars, 3,900 forks. Release v1.12.2 shipped 2026-04-10. Renamed from Perplexica to Vane on 2026-03-09 (branding change only). Actively maintained.

#### Architecture

RAG-based answering engine, not a deep research agent:

1. Query submitted → SearXNG queries multiple underlying search engines
2. Results re-ranked with embedding similarity
3. Top-ranked results fed to LLM for cited answer generation

Single-pass retrieval only. No recursive research loop. Three quality modes: Speed, Balanced, Quality.

SearXNG is the meta-engine: aggregates Google, Bing, DuckDuckGo, and others without direct API access. Tavily and Exa direct integrations are in development but not yet shipped as of this audit.

#### Finance Capability

Very low. A "stock prices" widget surfaces contextual price data. No structured financial data pull. Not designed for multi-step equity research.

#### Comparison: Vane vs Perplexity Search API

| Dimension | Vane (self-hosted) | Perplexity Search API |
|---|---|---|
| Search quality | SearXNG meta-engine (indirect) | Sonar model tuned for search |
| LLM | Your choice (Ollama, OpenAI, Anthropic) | Sonar Pro / Sonar |
| Privacy | Full — no data leaves VPS | Cloud |
| Cost | Infrastructure + LLM only | $0.005/request |
| Single-pass | Yes | Yes |
| Finance specialisation | None | None |
| Verdict | Weaker on search quality | Better search quality per query |

#### Limitations

- Single-pass — not a research agent, a search assistant
- SearXNG only mature backend at time of audit
- No financial data integration
- TypeScript-first codebase — harder to extend with Python financial tools
- Strictly weaker than Perplexity Search API on retrieval quality

#### Verdict

Not relevant to our stack. We already use Perplexity Search API which is objectively better than Vane's SearXNG approach. Privacy-first use case is the only differentiated value, which is not a requirement here.

---

### 4. HuggingFace Open Deep Research (`huggingface/smolagents`)

**Repository:** https://github.com/huggingface/smolagents  
**Blog post:** https://huggingface.co/blog/open-deep-research  
**Stars/Activity:** ~18,000 stars (smolagents repo). The `open_deep_research` implementation lives in `smolagents/examples/`. Actively developed.

#### Architecture

Code-agent framework — the key differentiator vs all other agents here:

- Agent writes and executes Python code to call tools, rather than emitting JSON tool-call blobs
- Nesting, loops, and conditionals available natively in the agent's tool-call logic
- Two primary tools: text-based web browser (adapted from Microsoft Magentic-One) and a text file inspector
- Iterative retrieval with context window management

**Performance on GAIA validation set:**
| System | Score |
|---|---|
| OpenAI Deep Research | 67.36% |
| HF Open Deep Research (code agent) | 55.15% |
| Magentic-One (prior SOTA) | 46.00% |
| JSON-based agent (same model) | 33.00% |

Code-based agents significantly outperform JSON-based agents on general research benchmarks.

#### Finance Capability

None out of the box. However, the code-execution paradigm means you can write financial tool calls (yfinance, Finnhub, EDGAR) as Python functions and the agent can call them with loops and conditional logic. More extensible than JSON-tool-call agents for this use case.

#### Limitations

- Text-only web browsing — cannot handle JavaScript-heavy pages or PDF figures
- Context window overflow in the current demo on very long research tasks
- `open_deep_research` is an example, not a polished product
- No standard report template or citation formatting
- Finance data: nothing ships out of the box

#### Verdict

The most architecturally interesting agent in the general-purpose category. The code-first tool-call paradigm is worth noting if we ever rewrite the agent runtime. Not a ready-to-deploy solution.

---

### 5. LangChain Open Deep Research (`langchain-ai/open_deep_research`)

**Repository:** https://github.com/langchain-ai/open_deep_research  
**Local variant:** https://github.com/langchain-ai/local-deep-researcher (9,200 stars)  
**Stars/Activity:** 11,700 stars, 1,700 forks, 213 commits. #6 on Deep Research Bench leaderboard (score 0.4943). GPT-5 support added August 2025.

#### Architecture

LangGraph Plan-and-Execute workflow with parallel sub-agent pattern:

1. **Supervisor agent** — breaks topic into sub-tasks, assigns to worker sub-agents
2. **Worker sub-agents** — each has an isolated context window, independently researches its sub-task
3. **Compression step** — each worker compresses findings before returning to supervisor
4. **Final synthesis** — supervisor generates comprehensive report from compressed sub-findings

LLM role assignment:
| Role | Default Model |
|---|---|
| Summarisation | GPT-4.1-mini |
| Research agent | GPT-4.1 |
| Compression | GPT-4.1 |
| Final report | GPT-4.1 |

All roles configurable. LangGraph Studio provides a visual graph editor for modifying the workflow.

#### Search Sources

Tavily (default). MCP-compatible — any MCP server can be plugged in as a retriever. Native web search for Anthropic and OpenAI models as alternative backends.

#### Finance Capability

Low out of the box. No financial data tools ship by default. However, the LangGraph architecture makes it straightforward to insert a financial data retrieval node (Finnhub or EDGAR tool step) between research and synthesis. The visual graph editor in LangGraph Studio simplifies node insertion.

**Local Deep Researcher variant:** Fully offline/zero-cost option. Uses Ollama (local LLM) + DuckDuckGo (no API key required). Iterative IterDRAG pattern — generates reflection and refines queries over multiple rounds. Useful reference if a zero-cost offline research mode is ever needed.

#### Limitations

- Default search is Tavily-only
- Performance trails OpenAI/Gemini proprietary agents on all benchmarks
- Evaluation cost: $20–100+ per 100 benchmark examples
- No finance-specific tooling

#### Verdict

The most "enterprise-extensible" general framework. LangGraph's explicit graph model makes financial data node insertion cleaner than most other architectures. Still requires custom development — not finance-ready out of the box.

---

### 6. DeerFlow 2.0 (`bytedance/deer-flow`)

**Repository:** https://github.com/bytedance/deer-flow  
**Stars/Activity:** 71,000+ stars (#1 GitHub Trending February 2026). 9,600 forks, 2,256 commits. 568 open issues.

#### Architecture

LangGraph + LangChain foundation. Five specialist agent roles executing in parallel pipelines:

| Agent | Role |
|---|---|
| Coordinator | Parses task, orchestrates pipeline |
| Planner | Decomposes task into sub-tasks |
| Researcher | Web search + retrieval |
| Coder | Code execution in sandboxed filesystem |
| Reporter | Synthesises final output |

**Key differentiators vs other agents in this list:**
- Sandboxed code execution — container filesystem at `/mnt/user-data/outputs/`; agents can write and run Python
- Persistent cross-session memory
- Progressive skill loading (modular capability modules that load on demand)
- Designed for "minutes to hours" long-horizon tasks, not just single queries

Output types: documents, slide decks, web pages, markdown reports — richer than any other agent here.

#### Search Sources

BytePlus InfoQuest (ByteDance's proprietary search + crawl toolset) as primary. Tavily as fallback. MCP-compatible.

#### Finance Capability

Not finance-specific. However, the Coder agent can execute Python scripts in the sandbox — meaning yfinance/Finnhub data pulls, ratio calculations, or even DCF models could be wired in as callable tools that actually run, not just retrieve text.

#### Deployment

Docker (local development mode). `DeerFlowClient` Python client. Designed for `127.0.0.1` loopback — production network deployment requires additional security hardening.

#### Limitations

- **BytePlus InfoQuest dependency** — primary search component is ByteDance-proprietary. Requires a ByteDance account. Creates a dependency on Chinese tech company infrastructure for core search functionality.
- Security model is loopback-first — not designed for multi-user or public deployment
- 568 open issues — high for a young project; adoption scale has outrun maintenance bandwidth
- Star count is inflated by trending visibility (February 2026) — not necessarily indicative of production deployments
- No structured financial data tools ship out of the box

#### Verdict

Most powerful architecture in this survey for building a custom research agent from scratch. The code execution sandbox + LangGraph extensibility makes it the best starting point if we were rebuilding from zero. The ByteDance search dependency is a concern. Not worth adopting as-is.

---

### 7. FinSight (`RUC-NLPIR/FinSight`) — Finance-Specific

**Repository:** https://github.com/RUC-NLPIR/FinSight  
**Paper:** ACL 2026  
**Stars/Activity:** 213 stars, 48 forks. Published early 2026. Very small community — academic project.

#### Architecture

Finance-domain multi-agent pipeline with shared state:

1. **Data Collector** — structured data pull from financial APIs
2. **Deep Search Agent** — web search + crawl for news and analyst commentary
3. **Data Analyzer** — quantitative analysis, ratio computation
4. **Report Generator** — publication-quality output

Shared variable space between all agents. Resumable checkpoints (can restart from a failed step). **VLM (Qwen-VL) for chart analysis** — reads and interprets charts embedded in annual reports, earnings presentations, and investor decks.

#### Data Sources

| Market | Sources |
|---|---|
| US | yfinance (OHLCV + financials), FRED (CPI, GDP, unemployment, rates, 10Y yield), Serper/Google search, web crawl |
| China / Hong Kong | AkShare (A-share data, institutional filings), efinance (HK-specific formats) |
| Macro | Commodity prices, FX reserves, LPR rates, China CPI/PPI/GDP |

#### Finance Capability

Highest in this survey. Purpose-built for equity research. Output reports include:

- Executive summary with investment thesis
- Quantitative financial statement analysis (income, balance sheet, cash flow, key ratios)
- Institutional holder and shareholding structure
- 20,000+ word length
- Source-traced inline citations
- Export formats: Markdown, DOCX, PDF

VLM chart reading is a capability not present in any other agent here and not in our current stack.

#### Limitations

- 213 stars — brand new, minimal community validation or production testing
- China/HK market data is first-class; US data coverage is narrower than FinRobot
- No SGX/Singapore, Eurozone, Japan financial data sources
- No SEC EDGAR integration
- Academic project — production reliability unknown
- Requires significant API key configuration upfront

#### Verdict

The most relevant architecture reference for our stack. The Data Collector → Analyzer → Report Generator pipeline with VLM chart reading is the right template if we ever want 20k-word publication-quality output. Too new and unvalidated to deploy directly — worth watching.

---

### 8. FinRobot (`AI4Finance-Foundation/FinRobot`) — Finance-Specific

**Repository:** https://github.com/AI4Finance-Foundation/FinRobot  
**Stars/Activity:** 7,200 stars, 1,200 forks, 317 commits. Maintained.

#### Architecture

Four-layer framework:

| Layer | Description |
|---|---|
| Financial AI Agents | Eight specialised agents (market forecaster, document analyst, valuation agent, etc.) |
| Financial LLMs Algorithms | Financial Chain-of-Thought (FinCoT), multi-source data fusion |
| LLMOps/DataOps | Smart Scheduler allocates tasks by agent performance metrics |
| Foundation Models | Primarily GPT-4 (hard dependency) |

Three core modules: Perception (multimodal financial data ingestion), Brain (LLM reasoning), Action (tool execution).

#### Data Sources

Financial Modeling Prep (FMP) — income statement, balance sheet, cash flow (3-year history + projections). Finnhub — real-time market data. Yahoo Finance — historical OHLCV. SEC filings via FinNLP — document parsing.

#### Finance Capability

Strongest built-in financial capability in this survey for US equities:

- 3-year financial projections (model-driven, not just historical display)
- DCF valuation model
- 15+ chart types in HTML/PDF output
- Investment thesis + risk assessment + buy/sell recommendation section
- Professional report format suitable for client distribution

#### Limitations

- **GPT-4 hard dependency** — expensive per run ($2–5), limited model flexibility vs other agents
- No Singapore market data (SGX not covered)
- US-centric by design — HK market only via Yahoo Finance (limited vs FinSight's AkShare)
- 57 open issues — moderate maintenance backlog
- "Not financial advice" disclaimer — academic project, not production-tested at scale
- No tiered depth / cost control

#### Verdict

Most mature finance-specific agent for US equity analysis. The GPT-4 dependency is a dealbreaker on cost versus Deepseek/Grok alternatives. The valuation model and report format are worth studying as a template.

---

## Benchmark Evidence

### FinDeepResearch Benchmark (October 2025)

**Source:** https://arxiv.org/abs/2510.13936  
**Scope:** 16 methods tested across 64 companies, 8 markets, 4 languages  
**Method categories:** 6 deep research agents, 5 reasoning+search LLMs, 5 reasoning-only LLMs

**Key findings:**
- Proprietary agents dominated: OpenAI Deep Research, Gemini Deep Research, Perplexity, Grok performed significantly above all open-source alternatives
- DeerFlow was evaluated in the open-source category but showed inferior performance vs frontier models on financial tasks
- Open-source agents performed adequately on narrative/qualitative sections; struggled most on quantitative metrics (EPS forecasts, revenue projections, sector-specific KPIs)

### FinDeepForecast Benchmark (January 2026)

**Source:** https://arxiv.org/abs/2601.05039  
**Scope:** Financial forecasting accuracy specifically

**Key findings:**
- Highest score achieved by any method: **39.5 / 100**
- Performance peaks in US and China markets (data-rich ecosystems)
- Performance collapses in Japan and smaller/emerging markets
- All AI systems (including proprietary) significantly underperform professional analysts on quantitative accuracy

### Deep FinResearch Bench (April 2026)

**Source:** https://arxiv.org/html/2604.21006  

**Key findings:**
- AI systems consistently underperform professional analysts on:
  - Revenue and EPS forecasting accuracy
  - Sector-specific KPI coverage
  - Assumption justification and transparency
  - Hallucination rates on numerical claims
- Gap is most pronounced for multi-year forward projections

**Implication:** No open-source agent is production-ready as a standalone quantitative equity research tool as of mid-2026. The benchmark ceiling for AI-generated equity research is still well below professional analyst standards on quantitative measures.

---

## Head-to-Head Comparison Table

| Capability | research_tool.py | Claude Code | GPT Researcher | DeerFlow 2.0 | FinRobot | FinSight |
|---|---|---|---|---|---|---|
| Search sources | Google News + Perplexity + Serper + Exa + Finnhub + SA + yfinance | WebSearch + WebFetch (any public URL) | Tavily/Serper/Exa/Bing/DuckDuckGo + 6 more | BytePlus InfoQuest + Tavily + MCP | FMP + Finnhub + Yahoo Finance + SEC/FinNLP | yfinance + FRED + Serper + AkShare |
| Search adaptability | ❌ Fixed query count | ✅ Fully adaptive, iterative | ⚠️ Fixed tree depth | ⚠️ Configurable | ❌ Fixed | ❌ Fixed |
| SEC EDGAR | ✅ 8-K std+deep; 10-K/Q deep | ❌ (web search only) | ❌ | ❌ | ✅ via FinNLP | ❌ |
| Structured financials | ✅ yfinance quarterly | ❌ (would need Bash call) | ❌ | ❌ | ✅ FMP 3-year + DCF | ✅ yfinance + AkShare |
| Macro data APIs | ❌ web search only | ❌ web search only | ❌ | ❌ | ❌ | ✅ FRED |
| Portfolio DB context | ✅ Live positions + fundamentals | ❌ | ❌ | ❌ | ❌ | ❌ |
| Tiered depth + cost estimate | ✅ Brief/Standard/Deep | ❌ Ad hoc | ✅ Standard + Deep | Configurable | ❌ Single mode | ❌ Single mode |
| Tiered cache (auto-depth) | ✅ 90-day window | ❌ | ❌ | ❌ | ❌ | ❌ |
| Recursive sub-query tree | ❌ Flat queries | ✅ Native reasoning | ✅ breadth=4, depth=2 | ✅ | ❌ | ❌ |
| Code execution mid-research | ✅ (Windmill worker) | ✅ (Bash/Python on VPS) | ❌ | ✅ (sandboxed) | ❌ | ❌ |
| LLM quality | Grok-4.3 | Claude Sonnet 4.6 / Opus | Any (25+ providers) | Any (OpenAI-compat) | GPT-4 (hardcoded) | Deepseek (default) |
| LLM cost transparency | ✅ Logged per run (~$0.10 deep) | ❌ Opaque (Claude Code billing) | ~$0.40 deep (o3-mini) | LLM cost only | $2–5 (GPT-4) | ~$1–3 |
| Earnings pipeline (pre/post) | ✅ Auto-dispatched | ❌ | ❌ | ❌ | ❌ | ❌ |
| Chart/figure reading (VLM) | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ Qwen-VL |
| Report format | Structured markdown + email | Ad hoc, task-dependent | Markdown / PDF / Word | Docs, slides, web | HTML / PDF with charts | DOCX / PDF (20k words) |
| Meta-reasoning on sources | ❌ Single synthesis pass | ✅ Can flag conflicts, gaps, uncertainty | ❌ | ❌ | ❌ | ❌ |
| HK ticker support | ✅ yfinance + non-EDGAR paths | N/A (web search) | N/A | N/A | ❌ US only | ✅ AkShare |
| SGX / Singapore market | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Natural language dispatch | ✅ Telegram + intent classification | ✅ (is the dispatcher) | ❌ | ❌ | ❌ | ❌ |
| Scheduling / automation | ✅ Windmill cron + alerts | ❌ Requires live session | ❌ | ❌ | ❌ | ❌ |
| Reproducibility | ✅ Same sources, same structure | ❌ Ad hoc, non-reproducible | ⚠️ Varies by retriever | ⚠️ | ⚠️ | ⚠️ |
| Production maturity | ✅ Live, 166 tests | ✅ Production (Anthropic) | ✅ v3.5.0 | ⚠️ 568 open issues | ⚠️ Academic | ⚠️ 213 stars, new |

---

## Capability Gaps — What They Have That We Don't

### Gap 1: Recursive Sub-Query Tree (GPT Researcher / DeerFlow)

**What it is:** Instead of generating N flat parallel queries, the agent generates top-level questions, then for each generates follow-up sub-questions based on what was found. Results from parent queries inform child queries.

**Current approach:** `depth=deep` generates 10 flat queries via Deepseek decomposition, runs them all in parallel, aggregates results.

**Their approach (GPT Researcher):** `breadth=4, depth=2` → 4 top-level queries → each spawns 4 sub-queries = 16 targeted queries with hierarchical context. The sub-queries are aware of what the parent query found.

**Impact:** Better coverage on complex, multi-faceted topics (e.g. "NVDA competitive position in 2026" vs simple keyword queries). The tree structure naturally finds niche documents that flat query sets miss.

**Implementation path:** Modify `research_tool.py` — after initial Deepseek decomposition, run a second Deepseek call per top-level query with retrieved snippets as context to generate follow-up queries. Adds ~3-5 Deepseek calls ($0.001 total) and ~3-5 additional search queries per deep run.

### Gap 2: Publication-Quality Formatted Reports (FinSight / FinRobot)

**What it is:** FinSight produces 20,000-word PDF/DOCX reports with institutional formatting: executive summary, financial statement tables, charts, shareholding structure, and source-traced citations in a format suitable for distribution. FinRobot generates HTML/PDF with 15+ chart types and a DCF valuation model.

**Current approach:** Clean markdown with a cost/source footer. Delivered via email and readable in Telegram preview. 300–2,500 words depending on depth.

**Gap significance:** Low for personal use (the current recipient is the email inbox). High if reports are ever shared with colleagues or clients.

**Implementation path:** python-docx (DOCX) or reportlab/WeasyPrint (PDF) for report rendering. The synthesis content is already structured markdown — the gap is template rendering only, not content.

### Gap 3: VLM Chart Reading (FinSight)

**What it is:** FinSight uses Qwen-VL to read and interpret charts, graphs, and figures embedded in annual reports, earnings presentations, and investor decks (PDFs, images). Extracts data points from visual sources that text-only parsers miss.

**Current approach:** Text-only parsing. BeautifulSoup extracts `<p>` and `<article>` tags. If a key figure (revenue breakdown, segment growth chart) is only present as an image in a 10-K or investor presentation, it is silently missed.

**Gap significance:** Medium. Most EDGAR 10-K filings have the underlying data in XBRL-tagged text alongside charts. The gap mainly affects investor presentations, earnings slides, and HK annual reports (which are PDF-heavy).

**Implementation path:** Add an optional VLM pass on PDF pages when fetching EDGAR or HK filings. GPT-4o or Qwen-VL via API. Cost: $0.002–0.005 per page. Selective — only run on filings where text extraction yields low-quality results.

### Gap 4: Macro Data APIs (FinSight/FRED)

**What it is:** FinSight integrates FRED (Federal Reserve Economic Data) directly — CPI, GDP, unemployment rate, 10Y yield, interest rate decisions, FX reserves. Structured data, not web-scraped text.

**Current approach:** Macro data arrives via web search (Google News, Perplexity). Structured macro figures are incidentally in articles but not systematically pulled.

**Gap significance:** Medium for macro research type. A `/macro` query on "US inflation outlook" currently synthesises from news articles. With FRED, the actual CPI time series and Fed meeting minutes would be directly available.

**Implementation path:** Add a `_fetch_fred_data()` function in `research_tool.py`. FRED API is free, no auth required beyond an API key (free registration). Activate for `research_type=macro`. Store macro key at `u/admin/fred_key`.

---

## What We Have That They Don't

Features unique to our stack not present in any of the evaluated agents:

1. **Portfolio DB context injection** — every research run automatically pulls live position size, current price, portfolio weight, and fundamental ratios for the ticker being researched, and includes this as structured context in the synthesis prompt. No other agent has this — it requires a persistent portfolio database.

2. **Tiered cache with auto-depth dispatch** — the agent checks `research_reports` PostgreSQL table: if prior research exists within 30 days, dispatches `brief` update; 30–90 days → `standard`; >90 days → `deep`. Transparent to the user. No other agent has this.

3. **Earnings pipeline (pre + post)** — `portfolio_earnings_alert.py` monitors the Finnhub earnings calendar for portfolio tickers, auto-dispatches `portfolio_earnings_analysis.py` for pre-earnings briefings, and `portfolio_earnings_post_check.py` triggers post-earnings analysis once EPS actuals are populated. No equivalent in any evaluated agent.

4. **Research type routing** — the `research_type` parameter (stock/strategy/macro/project) adjusts which sources are queried, what system prompt is used, and how the synthesis is structured. General-purpose agents use the same pipeline for all query types.

5. **Cost-efficiency** — Grok-4.3 at $1.25/$2.50 per 1M tokens (input/output) is 10–20× cheaper than GPT-4 used by FinRobot, and produces higher-quality financial reasoning per the Grok-4 launch evals. Deep run: ~$0.10 vs $2–5 for FinRobot.

6. **Natural language Telegram dispatch** — intent classification, multi-turn context, portfolio/thesis commands, earnings calendar, health check. No other agent in this survey has a production messaging interface.

---

## Recommendations

### Adopt wholesale: None

No agent is worth replacing `research_tool.py` with. The general-purpose agents (GPT Researcher, DeerFlow, LangChain, STORM) all lack structured financial data APIs that are core to our stack. The finance-specific agents (FinRobot, FinSight) either have GPT-4 cost problems, are too US-centric, are too new/unvalidated, or lack the HK market coverage we need.

**Claude Code** (this system) is already available as a complementary research capability for one-off, adaptive, breadth-first research tasks — as demonstrated by this audit itself. It is not a replacement for `research_tool.py` for scheduled, structured financial research on portfolio tickers, but it fills the gap for exploratory work where source flexibility and adaptive reasoning matter more than reproducibility and cost tracking.

### Selective improvements (priority order)

| Priority | Improvement | Source Inspiration | Effort | Expected Impact |
|---|---|---|---|---|
| **1 — Medium** | Recursive sub-query tree for `depth=deep` | GPT Researcher Deep Research | Low (2–3 Deepseek calls + search loop) | Better niche topic coverage, richer deep reports |
| **2 — Low** | FRED macro data API integration | FinSight | Low (free API, add function) | Better structured macro data for `research_type=macro` |
| **3 — Low** | DOCX/PDF report export | FinRobot / FinSight | Medium (python-docx template) | Only valuable if reports are shared externally |
| **4 — Very Low** | VLM chart reading on PDF filings | FinSight | High (VLM API integration + PDF rendering) | Niche — most EDGAR filings have text equivalents |

Priority 1 (recursive sub-query tree) is the only change that would materially improve output quality with minimal cost or complexity increase. All others are low priority given our primary delivery channel is personal email + Telegram.

---

## Source Documentation Index

| Source | URL |
|---|---|
| GPT Researcher GitHub | https://github.com/assafelovic/gpt-researcher |
| GPT Researcher docs — search engines | https://docs.gptr.dev/docs/gpt-researcher/search-engines |
| GPT Researcher docs — deep research | https://deepwiki.com/assafelovic/gpt-researcher/4.3-deep-research-mode |
| GPT Researcher site | https://gptr.dev |
| STORM GitHub | https://github.com/stanford-oval/storm |
| STORM NAACL 2024 paper | https://arxiv.org/abs/2402.14207 |
| STORM hosted demo | https://storm.genie.stanford.edu |
| Vane (Perplexica) GitHub | https://github.com/ItzCrazyKns/Perplexica |
| HuggingFace smolagents | https://github.com/huggingface/smolagents |
| HF Open Deep Research blog | https://huggingface.co/blog/open-deep-research |
| LangChain Open Deep Research | https://github.com/langchain-ai/open_deep_research |
| LangChain Local Deep Researcher | https://github.com/langchain-ai/local-deep-researcher |
| DeerFlow 2.0 GitHub | https://github.com/bytedance/deer-flow |
| FinSight GitHub | https://github.com/RUC-NLPIR/FinSight |
| FinRobot GitHub | https://github.com/AI4Finance-Foundation/FinRobot |
| FinDeepResearch benchmark (Oct 2025) | https://arxiv.org/abs/2510.13936 |
| FinDeepForecast benchmark (Jan 2026) | https://arxiv.org/abs/2601.05039 |
| Deep FinResearch Bench (Apr 2026) | https://arxiv.org/html/2604.21006 |
| Tavily Company Researcher | https://github.com/tavily-ai/tavily_company_researcher |

---

## Related Audit Documents

| File | Contents |
|---|---|
| `docs/audit/260612_search_api_audit.md` | Search API evaluation: Perplexity, Serper, Exa, Brave, Tavily, Linkup, etc. — endpoints, pricing, live test results |
| `docs/audit/260605_api_endpoint_full_audit.md` | Financial data API audit: news, earnings, financials, macro, commodities, insider data |
| `docs/audit/260605_fundamentals_api_audit.md` | Fundamentals API field mapping: Finnhub vs FMP vs AlphaVantage, HK/US coverage |
