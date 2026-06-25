# Documentation Refactoring — Implementation Log

**Date:** 2026-06-25
**Scope:** Restructure 6 documentation files with clear per-doc responsibilities. CLAUDE.md → context+rules only. ROADMAP.md → single status source. TESTING.md → philosophy + rules, no code. New OPERATIONS.md and TESTING_TEMPLATE.md for reference content.

---

## Motivation

CLAUDE.md had grown to 345 lines mixing context, rules, status tables, build checklists, operational recipes, and a full inline harness template. Every session start read the whole file; the Status section was always stale. Testing philosophy was buried under 120 lines of inline code template. The doc set had no clear ownership boundaries — same information appeared in multiple places, updated inconsistently.

Goal: each doc has one job, pointers replace duplication, and session start overhead drops.

---

## Design

### Per-doc contract

| Doc | Owns | Does NOT own |
|---|---|---|
| `CLAUDE.md` | Context (env, services, architecture principles, key paths, credentials), rules (21 Hard Rules, GitOps, hooks/permissions) | Status, roadmap, recipes, code templates |
| `docs/ROADMAP.md` | Build status, roadmap, next-up priorities, resource inventory | Context, rules, philosophy |
| `docs/TESTING.md` | Testing philosophy, test hierarchy, live-verify procedure, Hard Rules 15-21 explanatory depth | Code templates, operational recipes |
| `docs/WORKFLOW_ARCHITECTURE.md` | Pseudocode specs | Status, tests, ops |
| `docs/OPERATIONS.md` | Credential restore, schedule API push, Docker rebuild recipes | Everything else |
| `docs/TESTING_TEMPLATE.md` | Harness code template (ASD, World, contract test) | Philosophy, rules |

### Pointer semantics

- Any content removed from CLAUDE.md that lives elsewhere gets a pointer left behind in CLAUDE.md
- Pointers are absolute ("See `docs/ROADMAP.md`") — no ambiguity
- Not everything needs a pointer: the old 120-line inline harness template in TESTING.md is replaced by a 3-line pointer to TESTING_TEMPLATE.md; the template didn't need to be referenced from CLAUDE.md

---

## Changes Applied

### `/root/CLAUDE.md` (345 → 244 lines)

**Edit 1 — Script Workflow recipes → pointer (lines 122-146):**
- Removed schedule YAML API push command block (curl + WM_TOKEN)
- Removed credential restore recipes (curl/wmill for gmail_smtp and deepseek_key)
- Replaced both with: `**Operational recipes** (credential restore, schedule API push, Docker rebuild): see docs/OPERATIONS.md.`
- Kept: `wmill sync pull --yes` command (needed occasionally, not a recipe)

**Edit 2 — Current Status block → pointer (lines 251-310):**
- Deleted: Last-updated line, Phase 0 checklist (9 items), Workflows Built table (7 rows), Portfolio System table (6 rows), Analytics & Research Stack table (11 rows), Telegram Agent summary (1 paragraph), Next Up list (2 items)
- Replaced with: `See docs/ROADMAP.md for the full build status, live workflows, and next-up priorities. This file (CLAUDE.md) is the context+rules reference; ROADMAP.md is the single source for status.`

**Edit 3 — Hard Rules 15-21 condensed (32 lines → 7 one-liners):**
- Rule 15 (artifact-driven TDD): `See docs/TESTING.md for the full philosophy.`
- Rule 16 (≥500 words): `No "see email" pointers. See docs/TESTING.md.`
- Rule 17 (live-verify): `Email body (IMAP) + Telegram (outbox) + agreement check. See docs/TESTING.md.`
- Rule 18 (front-matter schema): kept as one-liner
- Rule 19 (lock-file deploy): kept as one-liner
- Rule 20 (Testing Critic): `5 failure modes: empty-artifact, template-string, tautology, ASD-derived, completeness. See docs/TESTING.md.`
- Rule 21 (verify response, not request): kept as one-liner

**Edit 4 — Doc workflow table condensed (13 rows → 6 rows):**
- Removed: per-workflow sub-rows for testing, scheduling, design approval, logic change, phase completion, credential creation, service deployment, portfolio system, agent changes, end-of-session
- Kept: orthogonal triggers (workflow change, artifact harness, new service, phase/end-of-session, override, keys update)

### `/root/docs/ROADMAP.md`

- Updated "Last updated" date from 2026-06-23 to 2026-06-25
- Added Affection Ping row to Part 1 — System section (hourly 8AM–10PM SGT, 11 packs, 35-emoji whitelist, `affection_outbox`)
- Updated test count line 85: 353→680 (added "11 affection ping artifact tests")
- Updated test count line 368: 521→680 (added "(11 affection ping)")
- Fixed typo on line 3: `TESTING_TEMPLING.md` → `TESTING_TEMPLATE.md`

### `/root/docs/TESTING.md`

- Removed 120-line inline harness template (was `agent/tests/test_windmill_scripts.py` excerpt with ASD, World, harness, contract test)
- Replaced with 3-line pointer: "A full template with ASD, World, harness, and round-trip contract test is available at `docs/TESTING_TEMPLATE.md`."

### `/root/docs/OPERATIONS.md` (new, ~40 lines)

Created with sections:
1. Credential restore — `wmill variable add` + `curl` API call for `gmail_smtp` and `deepseek_key`
2. Schedule API push — `curl` with `WM_TOKEN` for YAML-based schedule arg changes
3. Docker rebuild — `docker compose build + up -d` for `straitsagent`

### `/root/docs/TESTING_TEMPLATE.md` (new, ~130 lines)

Self-contained template extracted from TESTING.md:
- Import header + seam patches section
- `_SCRIPT_ASD` dict template with shared_fields + per-medium fields
- `_SCRIPT_WORLD` dict template with ASD-derived strings
- `_validate_world_vs_asd` helper
- `_render_script_artifacts` harness (patches + main() + collect outputs)
- `test_script_email_and_telegram_agree` contract test
- Word-count floor assertion, Testing Critic reminders, round-trip contract test stub

### `/root/docs/WORKFLOW_ARCHITECTURE.md`

No change needed — the word "blacklist" never appeared here. The affection_ping pseudocode (lines 2858-2886) generically says "Deepseek one-sentence affectionate message" which is correct for both the old blacklist and current whitelist behavior.

---

## Cross-Reference Audit

All 6 docs scanned for broken references (~46 total):

| Source | References | Broken |
|---|---|---|
| CLAUDE.md | 5 files (18 occurrences) | 0 |
| ROADMAP.md | 11 files (14 occurrences) | 1 typo (fixed) |
| TESTING.md | 3 files (4 occurrences) | 0 |
| WORKFLOW_ARCHITECTURE.md | 5 files (10 occurrences) | 0 |
| OPERATIONS.md | 0 | 0 |
| TESTING_TEMPLATE.md | 0 | 0 |

Typo found line 3 of ROADMAP.md: `TESTING_TEMPLING.md` → `TESTING_TEMPLATE.md` — fixed before commit.

---

## Notable Omissions (intentional)

- **Claude Code Configuration section** (hooks, permissions, hookify blocks) kept in CLAUDE.md — these are configuration rules, not status or recipes. No other doc is the right home.
- **Architecture Principles** kept in CLAUDE.md — these are context for every session, not workflow-specific. Remove from CLAUDE.md would leave them orphaned.
- **Earnings Report Standards** kept in CLAUDE.md — it's a standalone pointer to `docs/earnings_report_standards.md`, too small for its own doc.
- **Windmill Access** (URL, language, resource/schedule system) kept in CLAUDE.md — basic orientation needed every session.
- **Start of Session Prompt** kept in CLAUDE.md — read-me-first instruction, natural last section.

---

## Files Changed

| File | Action |
|---|---|
| `/root/CLAUDE.md` | Edited — 4 block replacements |
| `/root/docs/ROADMAP.md` | Edited — 4 spot edits + 1 typo fix |
| `/root/docs/TESTING.md` | Edited — inline template → pointer |
| `/root/docs/OPERATIONS.md` | Created |
| `/root/docs/TESTING_TEMPLATE.md` | Created |
| `/root/docs/logs/2026-06-25_docs-refactoring.md` | Created (this file) |

No Windmill scripts, no agent code, no tests changed.
