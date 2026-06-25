# Planning Workflow — Implementation Log

**Date:** 2026-06-25
**Scope:** Add a formal plan-file workflow to the project. Establish `docs/plans/` as the durable
handoff artifact between expensive planning models (Opus in Claude Code) and cheap executor models
(Deepseek in opencode).

---

## Motivation

The project uses two kinds of model sessions: expensive planning (Opus, Claude Code plan mode) for
architectural decisions, and cheap execution (Deepseek v4 flash, opencode) for implementation.
There was no durable artifact capturing the planner's decisions in a form the executor could work
from independently. The executor either over-asked (wasting tokens) or improvised (violating
architecture intent).

Hard Rules 7 and 12 already require design approval before coding, but "describe in chat" only
lives in the conversation — it evaporates between sessions and is inaccessible from a fresh opencode
checkout.

---

## Draft plan review (what changed)

An initial draft (`docs/plans/2026-06-25_planning-workflow.md`) was written by Deepseek, then
reviewed in Claude Code plan mode. Review found three issues:

1. **Blocking gap:** the actual CLAUDE.md Planning Workflow prose was never written — Step 3 said
   "insert the content from §The Plan → Edit 1" but no such section existed.
2. **Undefined lifecycle:** the Status field transitions (who flips draft→approved→executing→done)
   were referenced but never defined.
3. **Over-engineered for single-user project:** the original plan added a `session-git-check.py`
   hook extension, a `.bashrc` wrapper change, and an `opencode.jsonc` edit — machinery whose only
   payoff is auto-surfacing queued plans in the terminal. A prose line in CLAUDE.md's session-start
   section achieves the same result at zero complexity.

The user chose **simplify scope**: keep the high-value core (plan-file convention + status lifecycle,
documented in CLAUDE.md) and drop the hook/bashrc/opencode machinery.

---

## Cross-tool handoff design

The user's real workflow is Opus in Claude Code → Deepseek in opencode. Two issues with a
CLAUDE.md-only solution:

- **Persistence gap.** Claude Code plan mode writes to `.claude/plans/<slug>.md`, which opencode
  never reads. The fix: on approval, persist the plan to `docs/plans/YYYY-MM-DD_<slug>.md` with
  `Status: approved` and commit. That committed file is what Deepseek reads from a clean checkout.

- **Grounding gap.** Deepseek in opencode has no CLAUDE.md context unless explicitly given it. Two
  grounding layers chosen (belt-and-suspenders for a weak executor model):
  1. Every plan carries a self-contained `## Execution` footer (portable to any tool/model).
  2. Root `AGENTS.md` (auto-loaded by opencode, no `opencode.jsonc` edit needed) carries the
     executor protocol so Deepseek is grounded every session.

---

## Changes applied

### `/root/CLAUDE.md`
- New `## Planning Workflow` section between Script Workflow and Claude Code Configuration.
  Covers: when required, location + naming, front-matter format, body structure, `## Execution`
  footer template, Status lifecycle table, session-start scan instruction.
- Rule 7: "describe in plain English / pseudocode and get approval" → "document as a plan file in
  `docs/plans/` (see Planning Workflow) and get explicit approval". Trivial-work escape preserved.
- Rule 12: "describe the proposed change" → "write a plan file describing the proposed change".
  Removed the redundant "Both require a `docs/plans/` artifact" tail (now covered by Rule 7/section).
- Session-start section: appended "Also scan `docs/plans/` for any plan with Status: approved or
  executing and surface it before other work."
- Doc-workflow table: new row "Plan file created/approved/executed/abandoned → `docs/plans/`
  (Status field is the source of truth; commit the file)."

### `/root/AGENTS.md` (new)
- Root file auto-loaded by opencode.
- Pointer to CLAUDE.md + the executor protocol (read plan, flip to executing, work checklist, verify,
  flip to done, commit, no improvising).

### `/root/docs/plans/2026-06-25_planning-workflow.md`
- `Status: draft` → `Status: abandoned`.
- One-line superseded note added before §1 pointing to this log.

---

## Files changed

| File | Action |
|---|---|
| `/root/CLAUDE.md` | Edited — new section + 4 spot edits |
| `/root/AGENTS.md` | Created |
| `/root/docs/plans/2026-06-25_planning-workflow.md` | Edited — status + superseded note |
| `/root/docs/logs/2026-06-25_planning-workflow.md` | Created (this file) |

No Windmill scripts, agent code, tests, hook files, or `.bashrc` changed.
