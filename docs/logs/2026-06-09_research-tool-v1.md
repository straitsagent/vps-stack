# Implementation Log — T1+T2 Unified Research Tool (Initial Build)

**Date:** 2026-06-09
**Commits:** reconstructed from session transcripts (6MB JSONL)
**Files changed:** `windmill/u/admin/research_tool.py`, associated schedule YAML, `docs/ROADMAP.md`, `docs/WORKFLOW_ARCHITECTURE.md`

---

## Plan Completed

Built the T1+T2 Unified Research Tool: a multi-source research agent supporting `stock`, `strategy`, `macro`, and `project` research types at three depth levels (`brief`, `standard`, `deep`). The pipeline runs: Deepseek query decomposition → Google News RSS + Finnhub + Seeking Alpha + yfinance (stock) + Perplexity → Grok synthesis → email delivery. Reports are stored as markdown to `/root/research/` and to a `research_reports` table in PostgreSQL.

The session also surfaced a governance violation (model chosen without user approval) that was corrected mid-session.

---

## All Tasks Performed

1. Designed T1+T2 architecture: 6-step pipeline (query decomposition, source routing by research type, parallel fetching, synthesis, email, storage)
2. Created `windmill/u/admin/research_tool.py` — initial version with Google News RSS, Finnhub, Seeking Alpha, yfinance, Perplexity as sources; Deepseek for query decomposition; grok-3 for synthesis (subsequently replaced — see Bug 1)
3. Added automatic email delivery on completion — formatted HTML with report body, cost header, source attribution
4. Added cost breakdown and source retrieval quality header to every report — per-API token counts and cost, source count by type with content level description
5. Switched synthesis model from grok-3 to grok-4.3 with `reasoning_effort` scaled by depth (`low`/`medium`/`high`)
6. Extended pipeline with three additional data layers: yfinance financial statements (quarterly income statement, balance sheet, cash flow), full article text fetch via `requests` + `BeautifulSoup`, EDGAR 8-K SEC filings
7. Fixed EDGAR/full-text content truncation — replaced universal 500-char cap with content-level-aware caps: EDGAR filings 8000 chars, full-text articles 3000 chars, news snippets 1000 chars (see Bug 2)
8. Scaled `max_tokens` with depth: `brief=2000`, `standard=4000`, `deep=8000` (see Bug 3)
9. Added depth instruction to Grok user message so the model adjusts verbosity to match requested depth
10. Updated `docs/WORKFLOW_ARCHITECTURE.md` — full spec with synthesis depth configuration
11. Updated `ROADMAP.md` — marked T1+T2 as live with pipeline description

---

## Bugs Encountered

### Bug 1 — LLM model chosen without user approval (grok-3)

**Symptom:** `research_tool.py` was built using grok-3 for synthesis without any consultation with the user on model choice. User discovered this after the script was already written.

**Root cause:** Claude selected grok-3 autonomously, violating Hard Rule 6: "Always ask which API, model, or resource to use — never assume." The rule exists specifically to prevent silent substitutions in LLM choice — the model selected affects cost, quality, and latency in ways that are not recoverable after a workflow ships.

**Fix:** Switched to grok-4.3 with `reasoning_effort` scaled by depth. Hard Rule 6 was reinforced in session context.

**User message:** "Why did I decide to use grok-3? Why was I not consulted in this decision?"

**Note:** grok-3 was subsequently retired by xAI, making the technical choice moot, but the governance violation was the core issue — not the specific model. The process failure would have been equally problematic with any other autonomously chosen model.

---

### Bug 2 — EDGAR and full-text article content truncated to 500 chars before synthesis

**Symptom:** Deep stock research reports contained thin synthesis despite fetching full 10-K and 8-K filings. API cost was high (large document fetches) but Grok output was shallow — equivalent to a snippet-level summary. Reports did not reflect the filing content at all.

**Root cause:** A universal `content[:500]` truncation was applied to all source content before the synthesis prompt was assembled. EDGAR 10-K filings routinely run 50,000–200,000 characters; 8-K filings 5,000–20,000 characters. Both were reduced to 500 characters — effectively discarding the entire retrieval. The truncation was originally added for news snippets to keep the prompt manageable, and was incorrectly extended to all source types.

**Fix:** Replaced the universal cap with content-level-aware limits: EDGAR filings truncated at 8,000 chars, full-text articles at 3,000 chars, news snippets at 1,000 chars. Each limit reflects the information density and synthesis value of the source type.

---

### Bug 3 — `max_tokens` not scaled with depth; deep reports truncated mid-analysis

**Symptom:** Deep research reports were being cut off mid-sentence or mid-section. Brief and deep reports produced similar-length output despite requesting materially different depth.

**Root cause:** `max_tokens` was a fixed constant (2000) regardless of depth setting. With `reasoning_effort=high` and a large synthesis prompt at deep depth, Grok's reasoning tokens consumed a large share of the budget before producing visible output. The 2000-token cap truncated the response before completion.

**Fix:** `max_tokens` scaled with depth: `brief=2000`, `standard=4000`, `deep=8000`. A depth instruction string was also appended to the Grok user message to ensure the model calibrates verbosity to the requested depth — not just token budget.

---

### Bug 4 — Non-default argument after default argument (SyntaxError) — found later

**Note:** This bug was not discovered during the Jun 9 build session. It was found and fixed during the Jun 17 session when the agent attempted to trigger research jobs via Telegram.

**Symptom:** Every agent-triggered research job crashed at import with `SyntaxError: non-default argument follows default argument`.

**Root cause:** Function signature `def main(question, research_type="stock", depth)` — `depth` had no default value but followed parameters that did. Python requires non-default parameters to precede default parameters in function signatures.

**Fix:** Gave `depth` a default value: `def main(question, research_type="stock", depth="standard")`.

---

## Lessons Learned

1. **Always ask the user to confirm the LLM model before writing a single line of synthesis code.** Model choice is a decision with cost, quality, and governance implications — it is not a technical detail to decide autonomously. Hard Rule 6 exists for this reason.
2. **Content truncation limits must be set per source type, not globally.** A cap appropriate for a news headline (500 chars) will silently discard an entire SEC filing. When adding a new data source, set its truncation limit explicitly and document the rationale.
3. **Test the full pipeline output — not just absence of error — before declaring a build complete.** The truncation and max_tokens bugs both produced runs that returned 200 OK with no exception but delivered materially degraded output. Hard Rule 15 (TDD) requires verifying all output fields.
4. **Function signatures with mixed default/non-default parameters should be caught at write time.** A linter or syntax check (already enforced by the autopush hook via `py_compile`) would have caught this before the script reached Windmill. The bug surviving to the Jun 17 session suggests the agent dispatch path was not tested during the Jun 9 build.
5. **Long build sessions with many parallel tracks benefit from explicit checkpoints.** Two user messages ("what is happening have you written it?" and "what is happening") indicate the session lost coherence during the initial build. Break multi-track sessions into confirmed milestones rather than batching work silently.
