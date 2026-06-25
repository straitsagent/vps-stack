# AGENTS.md

Full project context and rules: see `CLAUDE.md` — read it first.

## Executing a plan (opencode / Deepseek)

Plans for substantive work live in `docs/plans/YYYY-MM-DD_<slug>.md`, committed to git. To execute
the plan you were pointed at:

1. Read the named plan file in full.
2. Set its front-matter `Status: executing`, commit.
3. Work the `- [ ]` checklist top to bottom; tick each item when its success criteria are met.
4. Run the plan's Verification section.
5. Set `Status: done`, commit.

Do not redesign. If the plan is ambiguous, wrong, or missing detail, stop and report — do not
improvise. This mirrors each plan's own `## Execution` footer (intentional redundancy).
