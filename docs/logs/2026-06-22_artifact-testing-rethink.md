# Artifact-Driven Testing Rethink — Implementation Log
**Date:** 2026-06-22  
**Scope:** `health_check.py`, `test_windmill_scripts.py`, `docs/TESTING.md`, `CLAUDE.md`, `docs/WORKFLOW_ARCHITECTURE.md`, `/deploy-windmill` + `/digest` skills.

---

## Motivation

Across multiple sessions the test suite was green while the human received broken or missing artifacts:
- **YouTube digest miscount** — tests only checked source substrings, never rendered output
- **health_check email missing digest/spec/diagnoses (2026-06-22)** — content engine ran inside the `if telegram_bot_token` block, *after* the email was already sent; Telegram (reading the `.md`) had all the content; email had none

Root cause was structural: ~150 of ~330 tests were source-substring checks (`assert "smtp" in src`). Zero tests ran a sending script's `main()` and inspected the rendered email HTML or Telegram text. No test rendered both artifacts from one `main()` run. A fake `_make_md` in the contract tests drifted silently from what `main()` actually wrote.

The user's instruction: **fundamentally rethink the testing approach**, not just add another Hard Rule. Make artifact-driven testing and development the governing philosophy — so a test earns its place only if its failure means the human gets a broken or missing artifact.

---

## Changes Made

### health_check.py — Seam factoring

Added four helper functions to make `main()` drivable in tests (I/O interceptable at the edges):

**`_send_email(gmail_smtp, recipient_email, subject, html)`**  
Factored from the inline SMTP block (lines 908–920 before refactor). Tests patch this to capture the email HTML without making real SMTP calls.

**`_build_front_matter(tg_date, ok_count, total, fm_rows, token_usage, outbox_rows, diagnoses, spec_checks, content_inventory, digest) → dict`**  
Factored to produce the single source dict shared between email and Telegram. Previously, `digest`/`spec_checks`/`diagnoses` were passed as direct args to `build_html()` AND put in `front_matter` separately — dual plumbing that caused the bug.

**`_build_md_content(front_matter, narrative) → str`**  
Pure function. Factored from the inline `.md` string assembly. Testable in isolation; used by the contract test instead of the stale test-local `_make_md` copy.

**`_write_canonical_md(md_content, path)`**  
Factored from the inline `open(md_path, "w")` write. Tests patch this to capture `.md` content without touching the filesystem.

**Structural fix — single source of truth:**  
`main()` now builds `front_matter` before `build_html`. Both email HTML and the `.md` (Telegram) read `digest`/`spec_checks`/`diagnoses` from `front_matter[...]`. The dual-plumbing that caused the missing-digest bug is structurally prevented.

**Execution order in main():**
1. Schedule loop (collect rows, diagnoses, token data)  
2. Content engine (`_collect_24h_reports`, `_spec_check`, `_synthesise_daily_digest`) — runs unconditionally  
3. Build `token_usage`, `fm_rows`, `outbox_rows`  
4. `front_matter = _build_front_matter(...)` — single source  
5. `html = build_html(..., digest=front_matter["digest"], spec_checks=front_matter["spec_checks"], diagnoses=front_matter["diagnoses"])` — email gets fields from front_matter  
6. `_send_email(...)` — interceptable  
7. If Telegram configured: `_build_md_content(front_matter, narrative)` → `_write_canonical_md(...)` → `_dispatch_formatter(...)` — interceptable

---

### test_windmill_scripts.py — Artifact tests

**`_HC_WORLD` fixture** (minimum-viable-realistic; tautology ban enforced):
- sent_subjects: 3 recent email subject strings  
- content_reports: 1 macro report  
- spec_violations: 1 distinct violation string (`"narrative.word_count must be ge2400 but got 1850"`)  
- digest: 5-sentence distinct text starting `"Executive brief 22 Jun 2026: equity markets posted modest gains..."`  
- diagnosis: `{root_cause: "SMTP rate limit exceeded on Gmail relay.", remediation: "Add exponential backoff and retry logic."}`  
- outbox_rows: 1 delivered row

**`_render_health_check_artifacts(world)`** harness:
1. Loads `health_check` module + `health_check_telegram` formatter  
2. Patches pytz stub to add working `timezone()` method  
3. Mocks 10 seams: `fetch_sent_subjects`, `wmill_get` (first per_page=1 call → FAILED, rest → OK), `_diagnose_failure`, `_collect_24h_reports`, `_spec_check`, `_synthesise_daily_digest`, `_query_telegram_outbox_24h`, `_dispatch_formatter`, `_send_email` (captures HTML), `_write_canonical_md` (captures `.md`)  
4. Calls real `main()` with fake creds + `deepseek_key="fake-deepseek-key-for-test"` (needed to open the synthesis gate)  
5. Renders real Telegram message via `_parse_md_report` + `_build_message` on captured `.md`  
6. Returns `(email_html, md_content, telegram_message)`

**9 new artifact assertion tests:**

| Test | Asserts |
|------|---------|
| `test_hc_email_contains_digest` | digest text in email HTML |
| `test_hc_email_contains_each_diagnosis` | root_cause + remediation in email HTML |
| `test_hc_email_contains_spec_failures` | spec violation string in email HTML |
| `test_hc_email_contains_all_status_rows` | every SCHEDULES label in email HTML |
| `test_hc_telegram_contains_digest` | digest text in Telegram message |
| `test_hc_telegram_contains_diagnoses` | root_cause + remediation in Telegram message |
| `test_hc_telegram_contains_spec` | spec violation string in Telegram message |
| `test_hc_telegram_contains_rows` | every SCHEDULES label in Telegram message |
| **`test_hc_email_and_telegram_agree`** | **ALL shared fields present in BOTH artifacts** |

**RED → GREEN proof:**  
Re-broke `main()` to omit digest/spec/diagnoses from email (exact shipped bug). `test_hc_email_contains_digest` and `test_hc_email_and_telegram_agree` went RED with:
```
MISSING from email: digest[:50] = 'Executive brief 22 Jun 2026...'
MISSING from email: diagnosis root_cause = 'SMTP rate limit exceeded on Gmail relay.'
MISSING from email: spec violation = 'narrative.word_count must be ge2400 but got 1850'
```
Restored fix → GREEN.

**`test_contract_health_check_rows_survive` updated (Part 4):**  
Replaced test-local `_make_md(fm, narrative)` fake with real `hc._build_md_content(fm, narrative)`. The formatter now tested against exactly what `main()` writes — closes the stale-copy gap.

**2 misleading substring tests pruned (Part 5):**
- `test_health_build_html_all_ok_text` — `assert "All " in src and " OK" in src` — superseded by `test_hc_email_contains_all_status_rows`  
- `test_health_build_html_issue_count` — `assert "issue" in src.lower()` — superseded by same

---

### docs/TESTING.md (new)

Canonical testing philosophy document. Contents:
- **The principle** (verbatim): "A test earns its place only if its failure means the human gets a broken or missing artifact."
- **Test hierarchy** (4 tiers, high→low): artifact-render → round-trip contract → architecture guard → substring (lowest value, must have comment if used)
- **Artifact-driven development flow**: design from artifact → write artifact test (RED) → implement → GREEN → live body inspection
- **`_render_<script>_artifacts(world)` harness pattern** with code structure, `world` fixture requirements, seam factoring requirements
- **Key cross-check test** (`test_<script>_email_and_telegram_agree`) — the structural catch for dual-plumbing bugs
- **Live verification procedure** (IMAP email body + Telegram text + agreement check)
- **Rollout status table** (health_check ✅; others pending)

---

### CLAUDE.md

**Architecture Principles section:** Added `"Test the artifact the human receives — see docs/TESTING.md"` as a standing principle alongside the existing email/sheets/postgres principles.

**Key Paths:** Added `docs/TESTING.md` row.

**Hard Rule 15 rewritten:**  
Old: generic TDD + tautology ban mixed with subprocess test instructions.  
New: leads with "the RED/GREEN target is the rendered artifact", requires `_render_<script>_artifacts` harness for every sending script, `test_<script>_email_and_telegram_agree` as the highest-authority check, substring tests explicitly demoted with comment requirement, round-trip contract tests must use real `_build_md_content`. Points to `docs/TESTING.md`.

**Hard Rule 17 extended to email body:**  
Old: Telegram-only — logged text + telegram_outbox check.  
New: Email body (IMAP) now required — fetch actual body, assert sections present; `success: True` and subject line explicitly called out as insufficient. Agreement check (shared fields in both email + Telegram) added as a requirement.

**Documentation Workflow table:** Added `"Artifact-render harness added to a script → docs/TESTING.md rollout table"` row.

**Session-start reading list + Start of Session Prompt:** Added `docs/TESTING.md` as mandatory read before writing any test or modifying a sending script.

**Current Status:** Updated to reflect 624 tests passing; artifact-testing philosophy as the context for this session.

---

### docs/WORKFLOW_ARCHITECTURE.md

**Testing Contract section** added at top (after preamble, before "How to read this document"):
- Required test shape for every sending workflow
- Seam factoring requirements
- Scripts with seams factored: `health_check` ✅

**Workflow 6.1:** Added note pointing to `_render_health_check_artifacts(world)` harness, the 9 artifact tests, and `docs/TESTING.md`.

**Last updated** line updated to 2026-06-22.

---

### Custom skills

**`~/.claude/commands/deploy-windmill.md` — Step 0:**  
Old: "Are tests written? Run pytest. Confirm RED."  
New: "Write or confirm an **artifact-render test** first — `_render_<script>_artifacts(world)` → assert each user-visible field in email_html AND tg_msg. Source-substring tests do NOT count."

**`~/.claude/commands/deploy-windmill.md` — Step 4:**  
Old: "confirm the email actually arrives" (subject-level check).  
New: "Email body (IMAP): fetch actual body, assert each content section present. Telegram: logs + telegram_outbox. Agreement: shared fields in both."

**`~/.claude/commands/digest.md` — Step 5:**  
Same upgrade: live artifact inspection replaces "email arrived" check.

---

## Verification

**RED → GREEN proof:** documented above — 2 tests go RED on the exact shipped bug, GREEN on the fix.

**Container test count:**
- Before this session's work: 617 passed (prior session)  
- After commit: **624 passed, 1 skipped**  
- Net new: 9 artifact tests + 1 updated contract test − 2 pruned substring tests = 7 net new passing tests  

**Commit:** `d069eb5` — pushed to `vps-stack` main.

**Deployed:** `health_check.py` pushed to Windmill via `wmill script push u/admin/health_check.py`.

---

## What is NOT done yet (rollout)

The artifact-driven approach is proven on `health_check`. The same treatment (seam factoring + artifact harness + contract test update + substring pruning) is pending for:

| Script | Work needed |
|--------|-------------|
| `macro_research` | `_send_email` partial (exists); `_build_md_content`, `_write_canonical_md`, `_build_front_matter` needed; harness + 9 tests |
| `portfolio_email` | All 4 seams + harness + 9 tests |
| `portfolio_review` | All 4 seams + harness + 9 tests |
| `portfolio_rationalization` | All 4 seams + harness + 9 tests |
| `portfolio_move_monitor` | Seams + harness |
| `portfolio_analyst_alert` | Seams + harness |
| `youtube_monitor` | Seams + harness |

Each script ships as its own commit, verified by its own artifact tests + live IMAP body inspection.
