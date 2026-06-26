# AGENTS.md

Full project context and rules: see `CLAUDE.md` — read it first.

> **Before executing any plan, read `docs/EXECUTOR_CONTRACT.md`** — the Five Gates
> (locked oracle, RED-before-GREEN, evidence-not-claims, asserting verify, STOP-on-
> deviation) apply to every plan, not just the high-risk ones. AGENTS.md is a quick
> summary; the contract is the binding standard.

## Executing a plan (opencode / Deepseek)

Plans for substantive work live in `docs/plans/YYYY-MM-DD_<slug>.md`, committed to git. To execute
the plan you were pointed at:

1. Read the named plan file in full.
2. Set its front-matter `Status: executing`, commit.
3. Work the `- [ ]` checklist top to bottom; tick each item when its success criteria are met.
4. Run the plan's Verification section.
5. **Before flipping to `done`:** confirm every item in the plan's `## Acceptance Gate`
   checklist is satisfied — including docs edits (ROADMAP, CLAUDE.md,
   WORKFLOW_ARCHITECTURE). A skipped docs item is a review-gate violation even if the
   code is correct. The reviewer (human or frontier) flips `done`, not the executor —
   self-certification is never sufficient (see `docs/EXECUTOR_CONTRACT.md` Review Gate).

Do not redesign. If the plan is ambiguous, wrong, or missing detail, stop and report — do not
improvise. This mirrors each plan's own `## Execution` footer (intentional redundancy).

### Deviations include model and prompt changes
If the owner approves a model or prompt change mid-execution (e.g. swapping Deepseek
for Grok-4.3), **stop and report it** — do not self-certify the swap in the
implementation log and continue. G5 (STOP on deviation) covers *any* change from the
plan as written, including the approved LLM model, the exact prompt text, and
threshold constants. The owner confirming the change does not exempt the executor
from reporting it as a deviation before proceeding.
