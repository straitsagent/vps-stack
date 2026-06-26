# portfolio_thesis Seeding — Implementation Log

**Date:** 2026-06-26
**Model:** Grok-4.3 (reasoning_effort=medium) via `$var:u/admin/xai_key` (owner chose more powerful reasoning model over Deepseek)
**Approach:** Hybrid auto-draft — one-shot seeder reads best research_report per position, drafts via Grok-4.3, writes with `[auto-draft]` prefix, never clobbers owner edits.

## What changed
- New Windmill script: `u/admin/portfolio_thesis_seeder` — `_build_thesis_prompt`, `_parse_thesis_response` pure helpers + `_pick_research_content`, `_call_llm` (Grok-4.3), `_write_thesis` I/O edges.
- 4 unit tests added to `test_windmill_scripts.py` (RED→GREEN): prompt genericness, valid parse with conviction normalization, invalid conviction→Medium default, blank/malformed→None guard.
- Full suite: 485 passed (no regressions).

## Live verification (Hard Rule 17)
- NVDA one-off: `seeded: ['NVDA']`. Row: conviction=High, target=$298.93, 4 catalysts, `[auto-draft]` prefix.
- Backfill all 33: 32 seeded, NVDA skipped_existing. No errors, no no_research.
- Conviction histogram: 22 Medium, 11 High.
- No-clobber: re-run → all 33 `skipped_existing`.

## Model change from plan
Plan specified Deepseek `deepseek-chat`. Owner chose Grok-4.3 with reasoning for better thesis quality. Prompt unchanged from plan approval.

## Downstream effect
- `portfolio_rationalization` Thesis factor (10% weight) now has conviction data for all 33 positions.
- Previously: every position scored 0 on this factor. Now: High=1.0, Medium=0.6, Low=0.2.
- `portfolio_earnings_analysis` now has investment_thesis + conviction for briefing context.
- Agent `thesis_read` / `thesis_write` now operate on seeded rows.
