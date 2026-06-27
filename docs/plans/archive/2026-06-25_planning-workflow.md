---
Subject: 2026-06-25 — Planning Workflow: plan-driven handoff to cheap executor models
Date: 2026-06-25
Status: abandoned
Planner model: deepseek-v4-flash (this session)
Executor model: deepseek-v4-flash (same session, separate execution pass)
Hard Rules in force: [7, 9, 11, 12, 15, 17, 18, 20]
Files to read before coding: CLAUDE.md, .bashrc (lines 100-112), scripts/session-git-check.py, .config/opencode/opencode.jsonc
---

**Superseded:** Scope reduced after review. The planning convention (plan-file format, status lifecycle, AGENTS.md) was adopted; the hook/bashrc/opencode.jsonc machinery was dropped. See `docs/logs/2026-06-25_planning-workflow.md` for the full decision record.

## 1. Context

The project uses two kinds of models: expensive planning models (Claude Opus, GLM-5.2) for architectural decisions, and cheap execution models (Deepseek v4 flash) for implementation. Currently there is no durable artifact that captures the planning model's decisions in a form the cheap model can execute from a fresh git checkout with zero access to the planning conversation. The cheap model either over-asks questions (wasting tokens) or silently makes judgement calls (violating architecture intent).

This workflow adds a formal `docs/plans/` file as the handoff artifact. The planning model writes a complete, unambiguous spec; the executor ticks a checklist and produces code. The workflow also extends the Claude Code SessionStart hook and opencode config so both tools surface queued plans in the session briefing automatically.

## 2. Files to create / modify / delete

| Action | Path | Purpose |
|--------|------|---------|
| Create | `/root/docs/plans/.gitkeep` | Track the empty directory in git |
| Modify | `/root/CLAUDE.md` | Add Planning Workflow section; rewrite Rule 7; update Rule 12; update SessionStart Prompt; add row to doc workflow table |
| Modify | `/root/.bashrc` | Update `claude()` wrapper prompt (line 107) to include plan queue scan |
| Modify | `/root/scripts/session-git-check.py` | Extend with plan queue check (glob docs/plans/, parse Status field, count checklist progress) |
| Modify | `/root/.config/opencode/opencode.jsonc` | Add `"instructions": ["/root/CLAUDE.md"]` |
| Create | `/root/docs/logs/2026-06-25_planning-workflow.md` | Implementation log for this work |

## 3. Exact names and signatures

### session-git-check.py changes
- **New function:** none (logic is inline in `main()` after existing git-check block)
- **New import** at top: `import glob`
- **New constants:** `PLANS_DIR = "/root/docs/plans"` (optional — inline string is fine)
- **Parsing strategy:** read first 4096 bytes, split on `---`, iterate lines in middle section for `status:` and `subject:` prefixes. No YAML library — avoid new deps.
- **Checklist count:** for executing plans, read full file, count `- [ ]` + `- [x]` as total, count `- [x]` as done.

### opencode.jsonc
```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "instructions": ["/root/CLAUDE.md"]
}
```
`instructions` value: array of strings. Each string is a file path (may be absolute, relative to project root, or using `~/`). Verify against https://opencode.ai/config.json before writing.

### CLAUDE.md new section header
`## Planning Workflow` — inserted between the `## Script Workflow (GitOps)` section (ends with the `wmill sync pull` code block) and the `## Claude Code Configuration` section (starts with `Claude Code is configured with hooks`).

## 4. Step-by-step execution order with checklist

- [ ] **Step 1.** Create `/root/docs/plans/.gitkeep`
  - `mkdir -p /root/docs/plans && touch /root/docs/plans/.gitkeep`
  - Success criteria: `ls /root/docs/plans/.gitkeep` returns 0
  - Next step depends on: nothing

- [ ] **Step 2.** Read `/root/CLAUDE.md` in full to confirm current line positions
  - Success criteria: confirm the existing `## Script Workflow (GitOps)` section ends at approximately line 127 and `## Claude Code Configuration` starts at approximately line 131
  - Next step depends on: Step 2 confirms exact anchor lines

- [ ] **Step 3.** Insert the new `## Planning Workflow` section into `/root/CLAUDE.md` between Script Workflow and Claude Code Configuration
  - Use a unique `oldString` match: the `---` separator at the end of Script Workflow (line 129: `---`) followed by the blank line and `## Claude Code Configuration`
  - Insert: the full Planning Workflow section as specified in §The Plan → Edit 1
  - Success criteria: re-read CLAUDE.md shows the new section between the two existing sections
  - Next step depends on: Step 3 complete (anchors for Steps 4-6 shift)

- [ ] **Step 4.** Rewrite Hard Rule 7 in `/root/CLAUDE.md`
  - oldString: the current Rule 7 text (starts `7. **Before writing any code for a workflow**...`)
  - newString: `7. **For substantive work (see Planning Workflow), the design is documented as a plan file in `docs/plans/`.** For trivial work, describe inline in chat and get verbal approval. Either way, only start coding after explicit approval.`
  - Success criteria: `grep "plain English" CLAUDE.md` returns no matches; `grep "plan file in" CLAUDE.md` returns 1 match

- [ ] **Step 5.** Update Hard Rule 12 in `/root/CLAUDE.md`
  - oldString: current Rule 12 text starting `12. **Before modifying any existing working workflow...**`
  - newString: `12. **Before modifying any existing working workflow, write a plan file describing the proposed change and get explicit approval.** Do not rebuild, restructure, or redesign a working script on your own judgement. Rule 7 covers new workflows; this rule covers changes to existing ones. Both require a `docs/plans/` artifact when the change is substantive.`
  - Success criteria: re-read Rule 12 shows the new text

- [ ] **Step 6.** Update SessionStart Prompt in `/root/CLAUDE.md`
  - oldString: `Read CLAUDE.md and docs/ROADMAP.md in /root/. We are working on [Phase X / specific workflow name]. Begin.`
  - newString: `Read CLAUDE.md and docs/ROADMAP.md in /root/. Scan docs/plans/ for any plan files with Status: approved or executing — if found, surface each one at the top of this briefing with its Subject, checklist progress (X/N complete), and ask whether to execute, revise, or defer. We are working on [Phase X / specific workflow name]. Begin.`
  - Success criteria: re-read shows the new prompt string with "Scan docs/plans/"

- [ ] **Step 7.** Add new row to Documentation Workflow table in `/root/CLAUDE.md`
  - Insert row after the "Keys file updated" row:
    ```
    | Plan file created/approved/executed/abandoned | `docs/plans/` (status flag is the source of truth; commit the file) |
    ```
  - Success criteria: table has 7 rows (including header row)

- [ ] **Step 8.** Edit `/root/.bashrc` line 107
  - oldString (the existing bash function line): do NOT match the whole function — match just the `command claude "..."` part
  - Exact oldString: `command claude "Read /root/CLAUDE.md and /root/docs/ROADMAP.md, check git status, and deliver the session briefing."`
  - newString: `command claude "Read /root/CLAUDE.md and /root/docs/ROADMAP.md, scan /root/docs/plans/ for queued work (Status: approved or executing), and deliver the session briefing."`
  - Success criteria: `source /root/.bashrc` produces no error; `type claude` shows the new text

- [ ] **Step 9.** Extend `/root/scripts/session-git-check.py` with plan queue check
  - Add `import glob` to top of file (after existing `import json` on line 10, or as a new line after `import sys`)
  - After the existing git-check block (after line ~55: `lines.append("---")` and `lines.append("")`), before `if not lines: sys.exit(0)`:
    ```
    # --- Plan queue check ---
    plans_dir = "/root/docs/plans"
    queued = []
    for path in sorted(glob.glob(f"{plans_dir}/*.md")):
        try:
            with open(path) as f:
                head = f.read(4096)
        except OSError:
            continue
        status_val = None
        subject = path.rsplit("/", 1)[-1]
        body = head.split("---", 2)
        if len(body) >= 2:
            for line in body[1].splitlines():
                s = line.strip()
                if s.lower().startswith("status:"):
                    status_val = s.split(":", 1)[1].strip().lower()
                elif s.lower().startswith("subject:"):
                    subject = s.split(":", 1)[1].strip()
                if status_val:
                    break
        if status_val in ("approved", "executing"):
            progress = ""
            if status_val == "executing":
                full = ""
                try:
                    with open(path) as f:
                        full = f.read()
                except OSError:
                    pass
                total = full.count("- [ ]") + full.count("- [x]")
                done = full.count("- [x]")
                if total:
                    progress = f" (checklist {done}/{total})"
            queued.append((path, status_val, subject, progress))

    if queued:
        lines.append("[plan-queue] Queued plan files:")
        lines.append("")
        for path, status, subject, progress in queued:
            lines.append(f"  \u2022 {subject} \u2014 Status: {status}{progress}")
            lines.append(f"    {path}")
        lines.append("")
        lines.append(
            "INSTRUCTION: Surface each queued plan at the top of the briefing "
            "with its Subject and progress (if executing). Ask the user whether "
            "to execute, revise, or defer each one before proceeding to other work."
        )
        lines.append("")
        lines.append("---")
        lines.append("")
    ```
  - Update docstring at top (lines 2-7): append a second bullet describing the plan queue scan
  - Success criteria: `python3 /root/scripts/session-git-check.py` runs without error (returns 0 or prints valid JSON). Create a dummy plan with `Status: approved`, run script, confirm it appears in output. Delete dummy plan after testing.

- [ ] **Step 10.** Update `/root/.config/opencode/opencode.jsonc`
  - Before writing: fetch `https://opencode.ai/config.json` and verify the `instructions` field's schema accepts an array of absolute file paths
  - If absolute paths accepted: write `{"$schema": "https://opencode.ai/config.json", "instructions": ["/root/CLAUDE.md"]}`
  - If not accepted: create `/root/AGENTS.md` with content `See /root/CLAUDE.md` and use `"instructions": ["/root/AGENTS.md"]`
  - Verify the file parses: `python3 -c "import json; json.load(open('/root/.config/opencode/opencode.jsonc'))"`
  - Success criteria: file parses as valid JSON; inform user they must restart opencode for changes to take effect
  - Next step depends on: schema verification result

- [ ] **Step 11.** Create `/root/docs/logs/2026-06-25_planning-workflow.md`
  - Implementation log following the format of `2026-06-25_docs-refactoring.md`
  - Sections: Motivation, 5 confirmed decisions, 9 edits applied, Self-check applied to the plan
  - Success criteria: file exists at path

- [ ] **Step 12.** Commit all changes
  - `git add CLAUDE.md .bashrc scripts/session-git-check.py .config/opencode/opencode.jsonc docs/plans/.gitkeep docs/logs/2026-06-25_planning-workflow.md`
  - `git commit -m "docs: add Planning Workflow for plan-driven handoff to cheap executor models"`
  - Success criteria: `git log --oneline -1` shows the new commit
  - Next step depends on: Steps 1-11 all complete

## 5. Pre-execution checklist

- [ ] `/root/CLAUDE.md` read in full — confirm Script Workflow section and Claude Code Configuration section anchors
- [ ] `/root/.bashrc` lines 100-112 read — confirm `claude()` wrapper text at line 107 matches the oldString
- [ ] `/root/scripts/session-git-check.py` read in full — confirm extension point after line 59 and before the `if not lines:` guard
- [ ] `/root/.config/opencode/opencode.jsonc` read — confirm current content is `{"$schema": "https://opencode.ai/config.json"}`
- [ ] Fetch `https://opencode.ai/config.json` to verify `instructions` schema before Step 10

## 6. Three failure points + handling

**Failure 1: session-git-check.py crashes on malformed plan front-matter**
- **Trigger:** `python3 /root/scripts/session-git-check.py` returns non-zero or produces invalid JSON
- **Action:** All `open()` calls in the new block are already wrapped in `try/except OSError`. If a plan file has no front-matter (no `---` separator), the `body = head.split("---", 2)` block will produce `len(body) < 2`, and the parsing is skipped — no crash. If the status value is not recognized (`status_val not in ("approved", "executing")`), the file is simply skipped. Worst case: the hook silently omits that plan from the queue list — the model will not be briefed about it, but nothing crashes.
- **Do NOT:** add PyYAML or any other dependency. The hook fires on every session start and must be zero-overhead.

**Failure 2: opencode rejects absolute paths in `instructions`**
- **Trigger:** After restart, opencode logs `ConfigInvalidError` related to `instructions` field, or the CLAUDE.md content is not present in system context
- **Action:** Fall back to creating `/root/AGENTS.md` with content `See /root/CLAUDE.md` and setting `"instructions": ["/root/AGENTS.md"]`. Delete the absolute path reference.
- **Do NOT:** inline CLAUDE.md content into AGENTS.md — that creates drift when CLAUDE.md is later updated without updating the copy.

**Failure 3: plan queue check duplicates with the `claude()` wrapper's prompt**
- **Trigger:** The `claude()` wrapper (Step 8) says "scan /root/docs/plans/ for queued work" AND the session-git-check.py hook (Step 9) also surfaces queued plans. The model sees the request twice — once from the shell prompt, once from the systemMessage.
- **Action:** This is acceptable — redundancy is better than miss. The hook's systemMessage is structured (list of paths + progress), while the shell prompt is a general instruction. The hook output appears first in context (systemMessage injected before the first user turn), then the shell prompt text appears as the first user message. The model will process both, see they describe the same set of plans, and not re-iterate. No dedup logic needed.
- **Do NOT:** remove either the wrapper instruction or the hook — they serve different entry points (wrapper for `claude` invocations, hook for every session including `claude --resume`).

## 7. Forbidden-phrase audit

Checked this plan file for: "as appropriate", "as needed", "similar to", "you may want to", "or similar". Zero hits.

## 8. Self-check

1. **All 8 sections present and complete?** ✅
2. **Every "create file" path listed AND parent directory verified?** Create paths: `docs/plans/.gitkeep` (parent `docs/plans/` exists as of this plan's writing), `docs/logs/2026-06-25_planning-workflow.md` (parent `docs/logs/` exists). All modify paths listed with current-content citations.
3. **Every "Files to read before coding" path verified?** All 4 verify: `CLAUDE.md` and `scripts/session-git-check.py` for Claude Code hook, `.bashrc` for wrapper, `.config/opencode/opencode.jsonc` for opencode config.
4. **No Windmill `$res:` / `$var:` references in this workflow** — it's a docs/config change, not a windmill script.
5. **Every step has explicit success criteria?** ✅ All 12 steps have `Success criteria:` lines.
6. **Three failure points + handling included?** ✅
7. **Forbidden-phrase audit pass?** ✅ Zero hits.
8. **Junior-model test:** A fresh Claude Code session reading CLAUDE.md (with the new Planning Workflow section) + .bashrc + session-git-check.py + opencode.jsonc can execute all 12 steps without asking questions. The opencode schema verification in Step 10 has explicit fallback instructions. The plan uses `oldString`/`newString` edit patterns consistently with the project's existing CLAUDE.md conventions (matching unique strings, not line numbers). ✅
