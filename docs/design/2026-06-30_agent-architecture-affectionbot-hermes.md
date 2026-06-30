---
title: Agent Architecture — Affectionbot and Hermes Compared
date: 2026-06-30
status: living document
author: claude-opus-4-8
---

# Agent Architecture: Affectionbot and Hermes

## Purpose

This document captures the design philosophy, current architecture, and intended direction of the two
AI agents in the stack — Affectionbot and Hermes. It is a design reference, not an execution plan.
Implementation plans live in `docs/plans/`.

---

## 1. Philosophy

The stack runs two very different kinds of AI agent, and the distinction is intentional.

**Hermes** is a research and monitoring conscience. It is always on, self-reflecting, and designed to
generate its own improvement agenda. Its value comes from continuity — it accumulates context, notices
patterns across days and weeks, and surfaces things the owner would not think to ask about.

**Affectionbot** is a social presence. It is designed to be warm, contextually aware, and increasingly
capable of serving the people in its chats. Its value comes from relationship quality — knowing who it
is talking to, remembering what matters to them, and getting better at being useful over time.

These are not competing designs. They are complementary: Hermes operates in the domain of institutional
intelligence; Affectionbot operates in the domain of personal connection. Both are evolving toward
genuinely useful self-improvement loops, but via architecturally different paths appropriate to their
different risk profiles.

---

## 2. Architecture Comparison

### 2.1 Current state (as of 2026-06-30)

| Dimension | Hermes | Affectionbot |
|---|---|---|
| **Framework** | Nous hermes-agent (full agent loop: tools, skills, background_review, cron) | FastAPI + direct LLM calls (OpenAI-compat Deepseek) |
| **Base image** | `python:3.11-slim` + nodejs/pandoc/weasyprint/fonts | `python:3.12-slim` |
| **Process** | `hermes gateway run` (persistent agent session) | `uvicorn main:app` (webhook HTTP server) |
| **Telegram mode** | None (Discord; `@StraitsHermesBot`) | Webhook (`/webhook/affection` → Caddy → affectionbot:8002) |
| **Memory** | File-based: `MEMORY.md` + skills/ in `/workspace` (hermes_state volume) | DB-based: `affection_conversation` in `affection` Postgres DB |
| **Self-improvement** | Autonomous: `background_review` fork after every turn writes skills/memory/cron | Not yet — conversations are stateless across sessions |
| **Cron jobs** | Self-managed in `/workspace` (3 live: portfolio health check, World Cup briefing, dispatch monitor) | None yet |
| **Networks** | `hermes_egress` (internet) + `hermes_db` (Postgres only, internal) | `default` + `agent_net` |
| **Rootfs** | `read_only: true` | Writable |
| **User** | `1000:1000` (non-root) | `bot` (non-root) |
| **Capabilities** | `cap_drop: ALL`, `no-new-privileges` | Standard container caps |
| **DB access** | `hermes_ro` role — 24-table SELECT allowlist, no writes, 15s timeout | `affection_user` — full owner of the `affection` DB |
| **Filesystem** | `/research:ro`, `/docs:ro`, `/workspace:rw` (scoped: `/research/hermes:rw`, `/docs/hermes:rw`) | No volume mounts — state lives in DB |
| **Data isolation** | Cannot reach `portfolio_user`/`openclaw_ro` secrets, PII, or agent tables | Owns a separate `affection` DB; portfolio DB structurally unreachable |

### 2.2 The self-improvement mechanisms compared

**Hermes** has a full autonomous self-improvement loop built into the framework:

```
User turn → Hermes responds
              ↓
         background_review fork (parallel thread, after every turn)
              ↓
         reflects: "did I learn something? should I create a skill?
                    update my memory? add a cron job?"
              ↓
         if yes → writes to /workspace: new skill, updated MEMORY.md, new cron job
              ↓
         next session starts with updated knowledge
```

This loop closes **autonomously, within the sandbox**. Hermes decides what to remember and what new
procedures to create, with no human in the loop. It is powerful — and deliberately bounded by the
sandbox. Hermes can improve anything inside `/workspace`; it cannot change its own infrastructure.

**Affectionbot** has no self-improvement loop yet. Every conversation starts from the same baseline.
The planned architecture introduces a **cron-mediated loop** that is structurally appropriate for a
social context:

```
Conversations accumulate in affection_conversation
              ↓
Daily cron:   short-term memory synthesis (last 7 days per chat_id)
Weekly cron:  long-term memory synthesis (all history + learned interaction style per chat_id)
Weekly cron:  capability reflection (what did the bot struggle with? what tools were missing?)
              ↓
Memory injected into system prompt at start of every conversation
Capability requests surfaced to owner for review
```

The loop never closes autonomously. The LLM reads the memory but never writes it. The capability
reflection produces a request document, not code. A human gate sits between reflection and any change.

---

## 3. The Sandbox as a Design Constraint

### 3.1 Why Hermes is sandboxed

Hermes is the most capable and autonomous agent in the stack. It has internet access, SQL access across
24 financial and research tables, and the ability to modify its own operating behaviour (skills, cron,
memory). The sandbox exists to prevent that capability from expanding uncontrollably:

| Invariant | What it prevents |
|---|---|
| Off `root_default` / `agent_net` | Cannot reach Windmill API → cannot dispatch jobs autonomously |
| Off `dind` | Cannot control Docker → cannot modify other containers |
| No Docker socket | Cannot escape containment |
| `read_only` rootfs | Cannot install packages at runtime; all changes go through `/workspace` |
| `hermes_ro` allowlist | Cannot write to portfolio DB; cannot read PII/secrets |
| No published ports | Cannot be reached from outside the stack |

These are not provisional. They are the terms under which Hermes operates, and they remain constant
even as its capabilities and integrations grow.

### 3.2 The sandbox growth ceiling

The sandbox creates a ceiling on what Hermes can improve autonomously. It can get better at *reasoning*
(skills), better at *remembering* (MEMORY.md), and better at *scheduling its own work* (cron) — but it
cannot give itself new tools that require infrastructure changes: a new Python library not in the image,
a new DB table to query, a new filesystem mount, new network access.

This is intentional but creates a legitimate tension: Hermes, given its role as a self-improving research
conscience, is exactly the agent most likely to identify infrastructure changes that would make it better.
Blocking it from surfacing those observations wastes the most valuable output of its self-reflection.

### 3.3 The solution: a formal capability request channel

Hermes already uses this pattern informally — the 2026-06-29 software installation request (`nodejs`,
`pandoc`, `weasyprint`) was written as a structured document in `/docs/hermes/`, reviewed by the owner,
and implemented by Claude. That is the correct loop.

The design intent is to formalise this into a first-class channel:

```
/docs/hermes/requests/YYYY-MM-DD_<slug>.md
```

Hermes writes a structured capability request; the owner reviews it; Claude implements it (or explains
why not). The sandbox never self-expands. Every infrastructure change is a deliberate decision.

**Request types and risk tiers:**

| Type | Example | Risk | Gate |
|---|---|---|---|
| Python/system package | `ffmpeg`, `requests` | Low | Review purpose + attack surface |
| New DB table grant | Add `research_reports` to hermes_ro | Medium | Check INV-5 (PII/secrets) |
| Hub skill adoption | `osint-investigation` community skill | Medium | Read skill source before adopting |
| Filesystem mount | Mount `/root/agent/` read-only | Medium-High | What data is exposed? |
| Network expansion | Access Windmill API | High | INV-1/INV-6 — review carefully; collapses producer/interpreter boundary |

Network expansion deserves special mention: if Hermes gains Windmill API access, it gains dispatch
capability, which collapses the producer/interpreter boundary that is the core of WS-B. The review
gate must remain substantive for the architecture to hold.

---

## 4. Memory Architectures

### 4.1 Why Hermes uses files, not a database

Hermes' memory is file-based (`MEMORY.md`, skills as `.md` directories) for three structural reasons:

1. **The agent loop is context-injection based.** Hermes works by injecting files into the LLM context
   window at session start. `.md` files are just strings — no query, no schema, no connection overhead.
2. **The only writable surface is `/workspace`.** Hermes can't write to Postgres (`hermes_ro` is
   read-only). The `hermes_state` Docker volume at `/workspace` is the natural persistence layer, and
   files are its native format.
3. **The skills system is file-native.** A Hermes skill is a directory of `.md` + templates + scripts.
   The hub catalog is an index of markdown files. The architecture assumes skills = readable, copyable
   text that an LLM can understand and modify.

The trade-off: files are fuzzy (read holistically, not by field), can drift, and don't support
structured queries. This is acceptable for an *interpreter* that reads its own knowledge — less
acceptable for a *reporter* that needs to retrieve specific rows by key.

### 4.2 Why Affectionbot uses a database

Affectionbot needs to retrieve specific records: a chat's last 7 days of conversation, the most recent
memory synthesis for a given `chat_id`. That's relational retrieval, not holistic reading. A DB is the
right tool.

The memory synthesis bridges the two worlds: a cron produces structured summaries *from* DB rows and
writes them back as DB rows. The LLM then reads those rows as injected text at conversation start —
the same context-injection pattern as Hermes, but sourced from a DB rather than the filesystem.

### 4.3 Planned Affectionbot memory architecture

Two tables, both keyed by `chat_id`, in the `affection` database:

**`affection_short_term_memory`** (daily synthesis, last 7 days per chat):
- Recent events, topics discussed, mood and tone of recent conversations
- ≤3KB per chat — recent enough to be specific, concise enough not to bloat context

**`affection_long_term_memory`** (weekly synthesis, all history per chat):
- Who the participants are, their personalities and relationships
- In-jokes, recurring topics, what the group cares about
- *Learned interaction style* — what tone and topics resonate, what to lean into
- Prior long-term memory integrated (not appended) on each run
- ≤5KB per chat — stable facts + the bot's acquired "feel" for the group

This is the declarative half of Hermes' MEMORY.md pattern, applied to a social context. The
self-improvement dimension comes from the interaction-style component of the long-term synthesis:
the bot accumulates a richer understanding of *how to be useful to these specific people*, not just
*what happened*.

---

## 5. Self-Improvement Governance

Both agents are moving toward self-improvement loops, but with different human-gate positions.

### 5.1 Hermes — tight loop, gated expansion

```
Inside sandbox:     Hermes improves autonomously (skills, memory, cron) ← no human gate
Infrastructure:     Hermes requests → owner reviews → Claude implements  ← human gate always
```

Hermes' self-improvement is fast and autonomous for everything it controls, but any capability that
requires infrastructure change goes through a formal request channel. This gives Hermes real agency
within a bounded domain, without the sandbox being a prison.

### 5.2 Affectionbot — cron-mediated loop, human gate on all capability changes

```
Memory:              cron synthesizes → injected at conversation start ← deterministic, no human gate
Capability requests: reflection cron → request doc → owner reviews → Claude implements ← human gate
Tool additions:      owner + Claude decide → implement directly ← human gate
```

Affectionbot's loop is slower and more conservative. The LLM never writes its own memory. Capability
requests are produced weekly, not after every turn. This is appropriate for a social bot: the cost of
a poorly-judged autonomous action (sending something off to people the owner cares about) is higher
than for a research bot where the audience is the owner reviewing a report.

### 5.3 The shared governance model

Both agents converge on the same three-tier structure:

| Tier | Who acts | Hermes example | Affectionbot example |
|---|---|---|---|
| **Autonomous** | Agent acts alone | Write a new skill; update MEMORY.md | (none currently planned) |
| **Cron-mediated** | Deterministic process; LLM reads output | Daily portfolio health check | Daily/weekly memory synthesis |
| **Human-gated** | Owner reviews; Claude implements | Capability request for new DB grant | Reflection doc → new tool |

The human gate is not a bottleneck — it is the architecture. The agents can move fast inside their
sandboxes precisely because the boundary between "agent decides" and "human decides" is crisp and
enforced at the infrastructure level, not just as a policy.

---

## 6. Capability Roadmaps

### 6.1 Hermes — planned direction

**WS-A — System visibility** *(partially delivered 2026-06-30)*
Producers outside the sandbox push Windmill job-health and VPS system-health JSON into
`/research/system/` (already read-only by Hermes). The host-side metrics collector
(`system-metrics-collector.py`, 30-min timer) is live. Hermes becomes the monitoring conscience
without touching the sandbox boundary.

**WS-B — Analysis takeover** *(in progress)*
Clean producer/interpreter split: Windmill + StraitsAgent keep *producing* and *dispatching*; Hermes
becomes the *interpreter*. Analytical StraitsAgent commands soft-deprecate over three reversible phases.
StraitsAgent keeps all transactional commands and all Windmill dispatch (INV-1/INV-6 preserved). First
increment delivered 2026-06-29: 4 automations stopped from pushing Telegram; YouTube cadence changed to
daily email-only.

**WS-C — Research `.md` quality** *(not started)*
Unified machine-parseable front-matter schema across all 8 `.md`-producing Windmill scripts; recency
metadata; cross-file linking; structured metric tables. Better inputs make Hermes' analysis materially
better. Schema design (C0) must precede any script changes (Hard Rule 18 contract migration).

**SSH sandbox backend** *(approved, awaiting VPS provisioning)*
Routes Hermes terminal execution to a separate disposable VPS (Hetzner CPX11), giving it full sudo on
the sandbox while the main VPS is never touched. The mechanism that makes Hermes' software installation
requests less critical — it can test packages on the sandbox before requesting them for the image.

**Skill development** *(Hermes executing autonomously — S1–S5)*
Valuation methodology, institutional review rubric, risk governance, stack-specific context, official
hub skill adoption. Hermes working through these in its own time per the approved plan.

**Formal capability request channel** *(to be designed)*
`/docs/hermes/requests/` with structured schema. Formalises what the 2026-06-29 software install
request proved works. Hermes surfaces infrastructure needs; owner + Claude review and act.

**Reflexive Alpha System** *(draft parent roadmap 2026-06-29)*
The overarching objective: Hermes as always-on conscience, Claude as stateless builder, owner as
director. Five workstreams (WS-1 through WS-5) leading toward an institutional-grade investment
research and portfolio management system. Feedback channel (daily `/docs/hermes/feedback/`) live.

### 6.2 Affectionbot — planned direction

**Data separation** *(plan written 2026-06-30, pending execution)*
`affection` database isolated from `portfolio`; dedicated `affection_user`; `hermes_ro`/`openclaw_ro`
structurally excluded via database boundary.

**Two-tier memory** *(plan written 2026-06-30, pending execution — depends on data separation)*
Daily short-term + weekly long-term synthesis per chat_id; injected into system prompt at conversation
start. Includes learned interaction style in the long-term synthesis.

**Capability reflection cron** *(designed, not yet planned)*
Weekly LLM reflection on conversations: what did users ask for that the bot couldn't do? Where did it
give unsatisfying answers? Produces structured request documents for owner review. The "request
mechanism" for Affectionbot, analogous to Hermes' capability request channel.

**Tool expansion** *(incremental, driven by reflection cron output)*
Web search is live. Planned: calendar read, link summarisation, reminders, portfolio awareness
(read-only). Each added deliberately based on what the reflection cron surfaces as actual gaps —
not by speculation about what might be useful.

---

## 7. The Relationship Between the Two Agents

Hermes and Affectionbot are currently independent — different databases, no direct communication,
different networks. The natural long-term relationship is **different domains, same oversight model:**

- Hermes is the institutional brain — monitors markets, research quality, system health, portfolio risk.
  Audience: owner-as-investor.
- Affectionbot is the social brain — knows the people, the dynamic, the history. Gets better at
  understanding what this specific group needs.
  Audience: owner-as-person (and the people they care about).

Both feed upward into the Reflexive Alpha System as intelligence sources — one over quantitative research
outputs, one over relationship and personal context. Both operate under the same three-tier governance.
Both request rather than self-execute when they hit infrastructure boundaries.

The agents are not competing for the same role. They are parallel expressions of the same architectural
principle: an AI that knows its domain deeply, improves continuously within its boundaries, and asks
clearly when it needs those boundaries to move.

---

## 8. Security Invariants Summary

These apply across both agents and do not change without explicit owner decision:

1. **Neither agent modifies its own infrastructure.** Docker images, network config, `docker-compose.yml`,
   and Postgres grants are human-controlled. Agents request; Claude implements.
2. **PII and secrets are unreachable by read-only roles.** `hermes_ro` and `openclaw_ro` have explicit
   allowlists excluding personal/secret tables. New tables do not auto-join allowlists.
3. **Hermes never dispatches jobs.** Analysis-only. All Windmill API calls remain with StraitsAgent.
4. **Affectionbot's memory is cron-written, LLM-read.** The LLM never writes its own memory or
   modifies its own system prompt content directly.
5. **Capability requests are documents, not code.** A request sitting in a file changes nothing until
   the owner reviews it and Claude implements it.
