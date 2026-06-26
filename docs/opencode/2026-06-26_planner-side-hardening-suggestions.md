# Planner-Side Hardening Suggestions (from opencode review session)

**To:** Claude Opus (planner)
**From:** GLM-5.2 (executor) — based on the 2026-06-26 DeepSeek implementation review log
**Status:** suggestions for Opus's next planning session — not yet applied

## Context

The review of 4 plan executions surfaced one planner-side process gap that AGENTS.md
(executor-side) cannot fix: prose oracles in HIGH-risk plans create wiggle room for
the executor. This file documents the suggested fix for Opus to apply to CLAUDE.md
and docs/EXECUTOR_CONTRACT.md.

## Suggestion 1 — CLAUDE.md: Planning Workflow → "Locked Oracle Tests (G1)" section

Add after the existing G1 description:

> **Prose oracles are forbidden.** The expected values must be embedded as a frozen
> Python code block (assertion + numeric tolerance), not as prose ("≈ -11.5"). Prose
> forces the executor to author the tolerance, which creates wiggle room and defeats
> the "copy verbatim" guarantee. Example of what NOT to write:
> `assert chg_5d ≈ -11.5` (prose — executor must choose the tolerance).
> Example of what TO write:
> ```python
> assert abs(dd["chg_5d"] - (-11.5)) < 0.5, dd
> ```

## Suggestion 2 — docs/EXECUTOR_CONTRACT.md: G1 section

Add a bullet under the existing G1 "Tiered ownership" and "Enforcement" bullets:

> - **Planner requirement:** locked assertions MUST be embedded as copy-pasteable
>   code (assertion + numeric tolerance), not prose ("≈ -11.5"). Prose oracles force
>   the executor to author the tolerance, defeating the "copy verbatim" guarantee.
>   Reviewers should reject HIGH-tier plans whose locked-oracle block contains prose
>   approximations instead of executable assertions.

## Why this matters

The position-sentinel Phase 1 plan embedded BABA drawdown expectations as prose
("`chg_5d ≈ -11.5`", "`vs_20d_high ≈ -27.3`"). The executor (correctly) authored a
`< 2.0` tolerance and the underlying math was right, but the prose form meant the
executor had latitude a frozen code block would not have granted. Future HIGH-tier
plans should remove this latitude by writing assertions as code, not prose.

## What AGENTS.md already covers (executor-side, applied this session)

- Pre-`done` acceptance-gate self-check — executor must confirm all checklist items
  (including docs) before flipping to `done`
- Model/prompt deviations are G5 deviations — stop and report, don't self-certify
- EXECUTOR_CONTRACT pointer — AGENTS.md now directs executors to read it before
  executing any plan
