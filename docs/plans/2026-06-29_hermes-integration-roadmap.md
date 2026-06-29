---
Subject: Hermes ↔ stack integration roadmap — read-only visibility, analysis takeover, research-MD quality
Date: 2026-06-29
Status: approved
Planner model: claude-sonnet-4-6
Risk tier: ROADMAP (parent plan; each workstream spawns its own executable child plan under docs/plans/)
Hard Rules in force: [6, 7, 10, 12, 13, 15, 16, 17, 18, 19, 20, 22]
Files to read before executing any child plan: CLAUDE.md, docs/EXECUTOR_CONTRACT.md, docs/TESTING.md, docs/ROADMAP.md (Part 7), docs/plans/archive/2026-06-28_hermes-contained-deployment.md
---

# Roadmap: Tighter Hermes ↔ Stack Integration

## Context

Hermes (`@StraitsHermesBot`, sandboxed Nous agent, `deepseek/deepseek-v4-pro` via OpenRouter) has proven
useful and is running three self-suggested cron jobs (World Cup briefing, daily portfolio health check,
cron dispatch monitor). The owner wants tighter integration along three axes:

1. **Give Hermes read visibility into more of the system** so it can monitor and analyse the stack.
2. **Slowly deprecate StraitsAgent Telegram-bot functionality** as Hermes takes over.
3. **Improve the quality of the research `.md` files** the Windmill automations produce and Hermes reads.

This document is the **parent roadmap**. It fixes the architecture and the security invariants, then
sequences three workstreams. **No code is executed from this file** — each workstream is implemented by its
own executable child plan (full `docs/EXECUTOR_CONTRACT.md` G1–G5 compliance) created in a later session.

### The single fact that shapes everything

Hermes is, by deliberate design, a **read-only, network-isolated observer** (verified live, LOCKED ORACLE
O1–O8 of the deployment plan):

| Boundary | Current state |
|---|---|
| Networks | `hermes_egress` (internet) + `hermes_db` (internal, Postgres-only). **NOT** on `root_default`/`agent_net` → cannot reach Windmill API or `dind` Docker daemon. |
| DB | `hermes_ro` role, **24-table SELECT allowlist**, `statement_timeout=15s`. Excludes `telegram_outbox`, `agent_conversation_history`, `agent_kv`, `key_management`. |
| Filesystem | `/research:ro` + `/docs:ro` (full trees) read-only; writable scratch only at `/research/hermes`, `/docs/hermes`, `hermes_state:/workspace`. |
| Hardening | non-root `1000:1000`, `read_only` rootfs, `cap_drop: ALL`, `no-new-privileges`, `mem 1g`, `pids 256`, no published ports. |

Both "monitor more of the system" (WS-A) and "take over from StraitsAgent" (WS-B) collide with this boundary.
The roadmap's core architectural decision — confirmed by the owner — is to **never weaken the sandbox**:
we extend Hermes by **pushing state into the read-only seams it already has**, and by **moving interpretation
(not dispatch) to Hermes**. The Hermes container spec in `docker-compose.yml` ideally does not change at all.

## Security Invariants (apply to EVERY child plan — non-negotiable)

A child plan that would violate any of these must STOP and be re-scoped, not implemented.

- **INV-1** Hermes stays off `root_default` and `agent_net`. No Windmill-API reachability, no `dind` reachability.
- **INV-2** No Docker socket (`/var/run/docker.sock`) mounted into Hermes. Ever.
- **INV-3** Hermes container keeps: non-root, `read_only` rootfs, `cap_drop: ALL`, `no-new-privileges`, no published ports. LOCKED ORACLE O1–O8 must still pass after any change.
- **INV-4** Hermes gains data only via (a) files dropped into `/research/**` or `/docs/**` by a producer running **outside** Hermes, or (b) additive `GRANT SELECT` to `hermes_ro` on **non-PII, non-secret** tables/views reachable on `hermes_db`.
- **INV-5** No PII/secret exposure: `telegram_outbox`, `affection_outbox`, `agent_conversation_history`, `agent_kv`, `key_management` remain denied to `hermes_ro`. (Owner explicitly scoped WS-A to exclude these.)
- **INV-6** Hermes remains analysis-only. It does **not** gain the ability to trigger Windmill jobs or perform gated DB writes. Dispatch and writes stay with StraitsAgent.
- **INV-7** Any front-matter schema change obeys Hard Rule 18: formatter `_build_message` + round-trip contract test updated in the **same commit**; lock-file rule (HR 19) respected.

---

## Workstream A — Hermes system visibility (read-only export seams)

**Goal:** Let Hermes monitor **Windmill job/schedule health** and **container/system health** — *without* giving it
Windmill-network or Docker access. (Owner excluded outbox and conversation history from scope.)

**Architecture:** a producer running **outside** the Hermes sandbox writes structured snapshots into the
read-only corpus Hermes already reads. Two feeds:

| Feed | Producer (outside Hermes) | Sink (Hermes reads) | Notes |
|---|---|---|---|
| Windmill job/schedule health | Extend existing `health_check.py` (already writes `/research/health/*.md`, already Hermes-readable) **or** a dedicated `system_state_export` Windmill script | `/research/system/windmill_health.json` (+ keep the `.md`) | Reuse — `health_check.py` already queries schedule status, failures, staleness, token cost. Emit a machine-readable JSON sidecar for Hermes. |
| Container/system health | Host-side exporter: a small systemd timer (pattern already used by `drive-backup.timer`) running `docker ps`/`df`/resource stats, writing JSON to `/root/research/system/` | `/research/system/containers.json` | Runs on host with Docker access; Hermes never touches the socket. Mirrors the existing host-timer pattern. |

**Why this is the lowest-risk workstream:** the Hermes container definition does **not change** — O1–O8 still pass
verbatim. We only add a producer + a new subdir under the already-mounted `/research`. Optionally, if Hermes
should *query* (not just read files) this state, add an additive `GRANT SELECT` to `hermes_ro` on a read-only
Postgres **view** of Windmill job status (INV-4/INV-5 compliant) — decide in the child plan.

**Reuse:** `health_check.py` (`_build_health_narrative`, front-matter assembly), `drive-backup.timer` systemd pattern,
`/research/index.json` manifest.

**Child-plan deliverables:** producer script(s) + systemd unit; `/research/system/` schema doc; a Hermes-side
skill/cron that reads the feed and reports anomalies; LOCKED ORACLE re-run proving O1–O8 unchanged.

---

## Workstream B — Shift analysis to Hermes; StraitsAgent keeps dispatch & writes

**Goal:** Hermes becomes the **interpretation/analysis** layer; StraitsAgent retains **transactional** duties.
**Model (owner-selected):** analysis-only — **no dispatch seam, no sandbox change.**

**Division of labour (the clean split):**

- **Producers (unchanged):** Windmill schedules + StraitsAgent dispatch continue to PRODUCE artifacts
  (research reports → `research_reports` table + `/research/**`; rationalization, candidate evals, earnings).
- **Interpreter (Hermes):** reads those artifacts (it already has `research_reports` + `/research:ro`) and does
  the synthesis/Q&A/monitoring the owner currently asks StraitsAgent for.

**StraitsAgent — KEEP (never deprecate):** webhook routing, owner/SILENT_GROUPS gating, confirmation flow,
job-completion polling, conversation history; transactional commands `/portfolio` (snapshot), `/prices`
(gated write), `/health`, `/thesis` write (gated); and **all Windmill job dispatch** (`research_tool`,
`portfolio_rationalization`, `portfolio_candidate_eval`, `portfolio_earnings_analysis`, `portfolio_price_fetcher`,
`fundamentals_fetcher`). These require the Windmill network Hermes is walled off from (INV-1/INV-6).

**StraitsAgent — DEPRECATION CANDIDATES (analytical overlap):** `/analyze`, `/macro`, `/deepresearch`, and the
*interpretation* half of `/research`, `/rationalize`, `/candidate`. The dispatch half stays; the LLM-synthesis
half migrates to Hermes.

**Phased soft-deprecation (each phase = its own child plan):**
1. **Phase B1 — Signpost:** overlapping analytical commands append a pointer in their reply ("for deeper analysis, ask Hermes"). No behaviour change. Reversible.
2. **Phase B2 — Thin the synthesis:** StraitsAgent dispatch commands return the raw artifact + a short factual summary; the long LLM narrative is dropped from StraitsAgent (Hermes owns interpretation). Update affected `agent/tools.py` tools + tests.
3. **Phase B3 — Evaluate removal:** after a usage window, decide whether to remove the analytical tools entirely. Keep tests green; CLAUDE.md/ROADMAP updated.

**Reuse:** `agent/tools.py` tool registry, `agent/classifier.py` intent routing, `agent/tests/` (680+ tests gate every change).

**Child-plan deliverables:** the command-by-command deprecation matrix; per-phase edits to `agent/tools.py`
with updated tests; ROADMAP "Telegram Agent" status updates.

---

## Workstream C — Research `.md` quality overhaul (all four improvements)

**Goal:** make the `.md` corpus Hermes reads consistent, machine-parseable, time-aware, and cross-linked.
Owner selected **all four** improvements.

**The four improvements:**
1. **Unified machine-parseable front-matter** — one schema across all `.md`-producing scripts:
   `meta` (generated_at, workflow_type, data_sources, content_type, depth) · `summary` (word_count,
   date_period, key_metrics, executive_summary) · `recency` · `quality_signals` · `workflow_specific` (the
   existing per-script payload nested here). Highest leverage, highest contract-risk (HR 18/19).
2. **Recency/staleness metadata** — standard `recency` block (`last_run_utc`, `next_scheduled_run`,
   `max_age_hours`, `is_stale`, `staleness_reason`). Generalise what `health_check.py` already computes. Low risk.
3. **Cross-file linking** — reports reference related reports by path (macro ↔ portfolio ↔ earnings ↔ youtube);
   extend the existing `/research/index.json` manifest into a traversable graph Hermes can walk.
4. **Structured data tables in prose** — embed markdown metric tables alongside the narrative (e.g. macro
   sections get an indicator table) so Hermes extracts time-series, not just paragraphs.

**Scripts in scope (8):** `macro_research`, `health_check`, `morning_news_digest`, `youtube_monitor`,
`portfolio_email`, `portfolio_review`, `portfolio_rationalization`, plus `research_tool` (markdown outputs).

**Sequencing within C (critical — this is a contract migration):**
- **C0 — Schema design:** write the canonical schema as a doc (`docs/research_md_schema.md`) + a shared
  validator. No script changes yet. Get explicit sign-off (Hard Rule 18 is a contract).
- **C1 — Reference implementation:** migrate ONE script first — recommend `macro_research` (just refactored,
  well understood) — formatter + round-trip test in the **same commit** (HR 18/19). Live-verify Hermes parses it.
- **C2 — Roll out** to the remaining 7 scripts, one commit each, each with formatter + round-trip test updates.
- **C3 — Cross-linking + recency** layered on once the schema is uniform; extend `/research/index.json`.

**Reuse:** `macro_research.py` `_write_canonical_md`/`_synthesise_section`, `health_check.py` recency logic,
`/research/index.json`, the formatter round-trip contract tests in `agent/tests/test_windmill_scripts.py`.

**Child-plan deliverables:** `docs/research_md_schema.md`; per-script migration plans (each its own commit,
each obeying HR 18/19/20 with a round-trip oracle); updated `WORKFLOW_ARCHITECTURE.md` §front-matter.

---

## Recommended sequencing across workstreams

Each can proceed independently, but there is a natural dependency order:

1. **WS-A first** — foundation, lowest security risk (no container change), and it makes Hermes able to
   self-monitor the very automations WS-C will improve.
2. **WS-C next** — better inputs make Hermes's analysis materially better, which is the precondition for WS-B.
3. **WS-B last** — shift interpretation to Hermes only once it is well-fed (good artifacts from C, system
   visibility from A). B's phases are reversible and usage-gated.

The owner asked for the roadmap only; **no first implementation increment is scheduled here.** The next session
picks a workstream and writes its executable child plan.

## Verification (of this roadmap, not of code)

This roadmap is correct/ready when:
- [ ] Every workstream complies with all seven Security Invariants (no INV violation anywhere above).
- [ ] WS-A requires **zero** change to the Hermes container spec (producers run outside the sandbox).
- [ ] WS-B introduces **no** new Hermes capability (analysis-only; dispatch/writes stay with StraitsAgent).
- [ ] WS-C's schema work (C0) precedes any script change, and every script migration pairs formatter + round-trip test in one commit (HR 18/19).
- [ ] Each workstream names a clear first child plan and the existing code/patterns it reuses.

## Execution (of child plans, later)

This file is a roadmap, not an executable plan. When a workstream is picked:
1. Copy `docs/plans/_TEMPLATE.md`; write the workstream's executable child plan with full
   `docs/EXECUTOR_CONTRACT.md` G1–G5 (LOCKED ORACLE, RED-proof, artifact evidence, asserting verify script, STOP-on-deviation).
2. The child plan's LOCKED ORACLE must re-assert the relevant Security Invariants (e.g. WS-A re-runs Hermes O1–O8).
3. Implement, verify, set child plan Status: done, commit. Update this roadmap's workstream status.
