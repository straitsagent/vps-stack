---
Subject: Executor-Handoff Hardening — make plan verification non-fakeable for any executor model
Date: 2026-06-26
Status: done
Planner model: claude-opus-4 (Claude Code plan mode)
Executor model: Claude Code (frontier) — this plan authors locked oracles + governance, so it is NOT a cold-handoff plan
Hard Rules in force: [7, 9, 15, 17, 20] (+ introduces a new Hard Rule 22)
Complies with: docs/EXECUTOR_CONTRACT.md (the artifact this plan creates)
Files to read before coding: CLAUDE.md, docs/TESTING.md, windmill/AGENTS.md, the 4 plans in docs/plans/
---

# Plan: Executor-Handoff Hardening

## Context — correct diagnosis first

The remaining plans are **specific** (exact commands, payloads, code). What they lack is
**enforceable, non-fakeable verification**. A capable but non-frontier executor (DeepSeek V4 Pro,
GLM 5.2, Sonnet 4.6) can: write a test that passes trivially, edit a test to go green, accept
`success: True` without reading the artifact, or improvise past an error. SWE-bench-class models score
well precisely because the benchmark hands them a **hidden oracle they cannot game** — our plans don't.
So the executor's benchmark rank is the wrong lever; the fix is to put a **locked oracle + evidence +
review gate** into the workflow so "done" means the same thing regardless of who (or what) executes.

This also closes a structural gap found in the audit: the verification discipline lives in `CLAUDE.md`
and `docs/TESTING.md`, **which an opencode executor never loads** (it reads `AGENTS.md`), and none of it
is machine-checkable. And the Claude-Code safety nets (hookify `sync push` block, PostToolUse autopush)
**do not run under opencode** — so for an external executor, Hard Rule 9 is currently prose-only.

**Decisions (owner, this session):**
- Enforcement tier: **contract doc + per-plan asserting verify scripts** (tool-agnostic; no git hook / CI).
- Oracle ownership: **tiered** — planner (frontier/Claude Code) authors frozen acceptance tests for
  high-risk plans; executor authors tests + mandatory frontier/human review for mechanical plans.

**Outcome:** any plan in `docs/plans/` becomes safe to hand to Sonnet / DeepSeek / GLM because
correctness is gated by artifacts the model cannot fake, not by trusting its self-report.

---

## The Five Gates (the core standard)

| Gate | Rule | How it's enforced (no infra) |
|---|---|---|
| **G1 — Locked Oracle** | Designated test assertions are FROZEN. Executor copies them **verbatim** and may not alter assertions to pass. Tiered: planner authors them for high-risk plans; executor authors + reviewer validates for mechanical ones. | Plan embeds the assertions in a fenced `# LOCKED ORACLE — copy verbatim` block. Reviewer diffs the committed test file against that block; any change to a locked assertion = reject. |
| **G2 — RED before GREEN** | Executor pastes the **failing** test run (failing for the right reason — `AttributeError`/assertion, not import error) BEFORE implementing, then the **passing** run after. | Close-out requires both pastes. No RED paste ⇒ not done. |
| **G3 — Evidence, not claims** | Every checklist item marked done is backed by **pasted raw output** (psql rows, `telegram_outbox` body, IMAP email, job result). `success: True` / "looks correct" is never evidence (Hard Rule 17, generalized). | Reviewer reads the pasted artifact, not the summary. |
| **G4 — Asserting verify script** | Each plan ships a `verify` script that **prints AND asserts** the decisive artifacts and **exits non-zero on any failure**, ending in an explicit `PASS`. | Close-out pastes the script's full output ending in `PASS`. The script — not the model's word — is the oracle for the live/integration side. |
| **G5 — STOP on deviation** | If any command's output differs from "Expected," **halt and report**. Never improvise, never retry blindly, never edit the oracle to fit. | Already in plans; elevated to contract + Hard Rule 22. |

**Asserting-verify idiom** (the pattern G4 standardizes):
```bash
docker exec root-portfolio_postgres-1 psql -U portfolio_user -d portfolio -tAc \
  "SELECT count(*) FROM earnings_surprises WHERE surprise_pct IS NOT NULL" \
| { read n; [ "${n:-0}" -gt 0 ] && echo "PASS rows=$n" || { echo "FAIL: empty"; exit 1; }; }
```

**Review gate (close-out):** a reviewer (human or frontier) confirms — G1 locked tests diff-clean,
G2 RED+GREEN pasted, G4 script output ends in `PASS`, G3 artifacts match intent — **then** flips the
plan `Status: done`. Self-certification by the executor is not sufficient.

---

## Part A — General workflow fix

### A1. Create `docs/EXECUTOR_CONTRACT.md` (the canonical, tool-agnostic standard)
Sections: Purpose (every `docs/plans/` file is cold-executable by any model) · **The Five Gates**
(verbatim from above, with the asserting-verify idiom) · **Review gate / close-out checklist** ·
**Environment caveats for non-Claude-Code executors** (hookify + autopush are Claude-Code-only →
run `wmill script push <path>` **yourself**, **never** `wmill sync push` (Hard Rule 9); run tests with
`docker exec root-straitsagent-1 python -m pytest …`; do not edit `# LOCKED ORACLE` blocks) ·
**Pre-done self-check** (mirrors the Testing Critic, Hard Rule 20).

### A2. Amend `CLAUDE.md`
- **Planning Workflow → Body spec:** add four now-mandatory plan sections — **Locked Oracle Tests**,
  **RED-proof requirement**, **Asserting Verification Script**, **Acceptance Gate (reviewer checklist)**.
- **Hard Rules:** add **Rule 22 — "Cross-model handoff contract. Any plan intended for execution must
  satisfy `docs/EXECUTOR_CONTRACT.md`: a locked oracle (G1), RED-before-GREEN proof (G2), artifact
  evidence not claims (G3), an asserting verify script (G4), and STOP-on-deviation (G5). Completion is
  gated by review, not self-report."**
- **`## Execution` footer template:** insert a line — "Satisfy all five gates in
  `docs/EXECUTOR_CONTRACT.md`; do not modify `# LOCKED ORACLE` assertions; STOP on any deviation."
- Add a one-line pointer near Planning Workflow: "Handoff standard: `docs/EXECUTOR_CONTRACT.md`."

### A3. Amend `windmill/AGENTS.md` (the opencode/DeepSeek entry point)
Fill the empty "Project-specific instructions" with a MANDATORY block: before executing any
`docs/plans/` file, read `../docs/EXECUTOR_CONTRACT.md` and comply with the Five Gates; never
`wmill sync push` (the Claude-Code hookify block does NOT run here — Hard Rule 9 is manual); run tests
in the `root-straitsagent-1` container; never edit `# LOCKED ORACLE` assertions; STOP and report on
deviation. (This is the only path by which an opencode model inherits the contract.)

### A4. Create `docs/plans/_TEMPLATE.md`
A skeleton every future plan copies: front-matter (incl. `Complies with: docs/EXECUTOR_CONTRACT.md`
and a risk tier) → Context → Files-changed table → Checklist → **Locked Oracle Tests** →
**RED-proof requirement** → **Asserting Verification Script** → **Acceptance Gate** → `## Execution`
footer. Keeps the standard self-propagating.

---

## Part B — Retrofit the 4 existing plans

Each gets the four mandatory sections. The high-risk plans already contain the right test code in-body;
the retrofit mostly **marks it LOCKED**, adds the RED-proof line, converts the prose verification into
an **asserting** script, and adds the acceptance gate. Add `Complies with: docs/EXECUTOR_CONTRACT.md`
+ a `Risk tier:` line to each front-matter.

| Plan | Tier | Locked oracle (frozen assertions) | Asserting verify script checks |
|---|---|---|---|
| `2026-06-26_position-sentinel-phase1.md` | **HIGH (planner-locked)** | `_cumulative_drawdowns(BABA series)` → `chg_5d≈-11.5`, `vs_20d_high≈-27.3`; `_price_signal` fires on BABA / silent on flat; `_parse_materiality` clamps 0–3 & blank→None; `_confluence` needs price∧news; formatter front-matter round-trip + ≥500 words | `position_signals` has a BABA `price_cumulative` row with `chg_5d ≤ -10`; `position_events` rows have non-null materiality; a `telegram_outbox` row names BABA + a drawdown; calm names → no signal |
| `2026-06-25_earnings-surprises-fetcher-fix.md` | **HIGH (planner-locked)** | `_pick_col` finds `Reported EPS`; `_extract_surprises` → 4 rows, recomputed `3.608`, future NaN excluded; blank→`[]` | `earnings_surprises` rows>0 with non-null `surprise_pct`; AAPL ≥1 row |
| `2026-06-25_portfolio-thesis-seeding.md` | **HIGH (planner-locked)** | `_parse_thesis_response` conviction normalize ("high"→High, "Strong"→Medium), blank→None; `_build_thesis_prompt` generic (no persona) | `portfolio_thesis` rows≈33, every `conviction ∈ {High,Medium,Low}`; re-run shows `skipped_existing` (no clobber) |
| `2026-06-25_macro-daily-push-disposition.md` | **LOW (executor+review)** | none (mechanical) — executor writes none; reviewer validates | `schedules/get …macro_daily_push` → HTTP 404; disk `.schedule.yaml` gone; `macro_daily_push_telegram.py` present; pytest green |

For each high-risk plan, wrap its existing in-body test code in a `# LOCKED ORACLE — copy verbatim, do
not modify assertions` fence and add: "Executor must reproduce these assertions unchanged; reviewer
diffs the committed test file against this block (G1)."

---

## Acceptance Gate for THIS plan (dog-foods the contract)
- `docs/EXECUTOR_CONTRACT.md` exists and defines the Five Gates + review gate + env caveats.
- `CLAUDE.md` shows Hard Rule 22 and the four mandatory plan sections; `grep -c "EXECUTOR_CONTRACT" CLAUDE.md windmill/AGENTS.md` ≥ 1 each.
- `docs/plans/_TEMPLATE.md` exists with all mandatory sections.
- All 4 retrofitted plans contain a `# LOCKED ORACLE` block (or, for macro, an explicit "no oracle —
  mechanical" note) and an **Asserting Verification Script** section; `grep -L "Asserting Verification" docs/plans/2026-06-2*.md` returns nothing for the 4 (i.e. all present).
- `git status` clean after commit.

## Verification (asserting script for this plan)
```bash
cd /root
fail=0
for f in docs/EXECUTOR_CONTRACT.md docs/plans/_TEMPLATE.md; do [ -f "$f" ] || { echo "FAIL missing $f"; fail=1; }; done
grep -q "Hard Rule 22\|Rule 22" CLAUDE.md || { echo "FAIL: Rule 22 not in CLAUDE.md"; fail=1; }
grep -q "EXECUTOR_CONTRACT" windmill/AGENTS.md || { echo "FAIL: AGENTS.md pointer missing"; fail=1; }
for p in 2026-06-26_position-sentinel-phase1 2026-06-25_earnings-surprises-fetcher-fix 2026-06-25_portfolio-thesis-seeding 2026-06-25_macro-daily-push-disposition; do
  grep -q "Asserting Verification" "docs/plans/$p.md" || { echo "FAIL: no verify section in $p"; fail=1; }
done
[ $fail -eq 0 ] && echo "PASS" || exit 1
```

## Out of scope
Active git hooks / CI gates (owner chose the no-infra tier — revisit later if handoffs still leak).
Re-running the 4 plans themselves (this only hardens their specs; execution is separate).

## Execution
1. Set `Status: executing`, commit.
2. Build A1→A4 (contract, CLAUDE.md, AGENTS.md, template), then Part B retrofits.
3. Run the Verification asserting script; confirm `PASS`.
4. Set `Status: done`, commit.
This plan is executed in Claude Code (frontier) because it authors the locked oracles and governance.
Do not modify `# LOCKED ORACLE` assertions in the retrofits. STOP and report on any deviation.
