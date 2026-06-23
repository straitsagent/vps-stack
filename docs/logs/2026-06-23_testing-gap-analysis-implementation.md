# Testing Gap Analysis — Implementation Log

**Date:** 2026-06-23  
**Scope:** Close 4 architectural gaps (A1–A4) and 6 named implementation gaps identified in external gap analysis (artifact 95ca8b71)

---

## Gaps Addressed

### A1 + A4 — Artifact Specification Documents (ASD)

**Problem:** `_HC_WORLD` was hand-crafted to make assertions pass. Tests were validating code against itself with no external specification reference. World fixtures could be designed to pass their own assertions rather than derived from a spec.

**Fix:**
- Introduced `_HC_ASD` dict as the authoritative pre-implementation spec with 4 named constants
- `_HC_WORLD` now sources all key strings from `_HC_ASD_*` constants (world references ASD, not reverse)
- Added `_validate_world_vs_asd(world, asd)` helper — called at top of every harness; fails immediately if ASD updated without updating world
- Updated `test_hc_email_and_telegram_agree` to iterate `_HC_ASD["shared_fields"]` mechanically

**Files:** `agent/tests/test_windmill_scripts.py`

---

### A2 — Testing Critic (Hard Rule 20)

**Problem:** Same-model review cannot catch same-model blind spots. No formal adversarial review process before committing tests.

**Fix:**
- Added Hard Rule 20 to CLAUDE.md: mandatory 5-point adversarial checklist before committing any artifact test
- Added "Testing Critic" section to TESTING.md with examples of each failure mode
- Applied checklist to all 10 existing HC artifact tests — all passed

**Checklist:**
1. Empty-artifact: can empty/None artifacts pass all assertions?
2. Template-string: could asserted strings come from boilerplate, not world fixture?
3. Tautology: is any assertion pre-sized to match the fixture?
4. ASD-derived: is every asserted string in the ASD?
5. Completeness: does `_agree` test cover ALL ASD `shared_fields`?

**Files:** `CLAUDE.md`, `docs/TESTING.md`

---

### A3 — Tier 0 Production Artifact Verification

**Problem:** All testing is pre-deployment. No automated feedback after delivery — failures only discovered when a broken/missing email is noticed.

**Fix:**
- Added `_fetch_sent_body(gmail_smtp, subject_fragment, hours)` — extends existing IMAP logic to fetch full RFC822 body
- Added `_artifact_body_check(body, required_markers)` — pure function, returns `{pass, missing, found}`
- Added `ARTIFACT_MARKERS` dict — structural HTML markers for 8 sending scripts
- Added `_write_artifact_verification(portfolio_db, ...)` — writes results to new DB table
- Tier 0 block in `main()` runs after email send; non-blocking (try/except, failures only logged + written to DB)
- New `artifact_verification` Postgres table — `(id, checked_at, script_name, email_ok, missing_sections, email_subject)`

**Files:** `windmill/u/admin/health_check.py`, `portfolio/schema.sql`

---

### G4 — Word-count assertion (implementation gap)

**Problem:** No harness was asserting that the world fixture actually drives ≥500 Telegram words.

**Fix:**
- Added `test_hc_telegram_min_word_count` — asserts `len(tg_msg.split()) >= _HC_ASD["min_telegram_words"]`
- This test immediately **caught a real problem**: `_HC_WORLD["digest"]` was only ~70 words, producing a 143-word Telegram message
- Fixed by replacing the short stub with a realistic ~600-word narrative constant `_HC_ASD_DIGEST_NARRATIVE`

**Files:** `agent/tests/test_windmill_scripts.py`

---

### G1, G2, G3, G5, G6 — TESTING.md implementation gaps

- **G1** — Added explicit "broken artifact" definition (5 conditions: empty body, missing section, wrong field value, <500 words, delivery failure)
- **G2** — Testing Critic checklist point 3 is the tautology enforcement mechanism
- **G3** — Rule: `shared_fields` in `_agree` tests must iterate `_SCRIPT_ASD["shared_fields"]`, not a hand-picked subset
- **G5** — Added copy-paste harness template to TESTING.md covering all required elements (ASD → world → harness → assertions)
- **G6** — Explicit rollout order defined: macro_research → portfolio_email → portfolio_review → portfolio_rationalization → portfolio_move_monitor → portfolio_analyst_alert → youtube_monitor

**Files:** `docs/TESTING.md`

---

## Test Results

- Before: 624 tests passing
- After: **625 tests passing** (1 new: `test_hc_telegram_min_word_count`)
- Testing Critic self-audit applied to all 10 HC artifact tests — all 5 points passed
- Schema migration applied to live Postgres

---

## Pending

- **Phase C rollout** — apply ASD + seam factoring + harness + word-count test + Tier 0 markers to 7 remaining scripts in defined order
