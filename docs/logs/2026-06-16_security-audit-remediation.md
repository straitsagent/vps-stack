# Implementation Log — Full Codebase Security Audit and Remediation
**Date:** 2026-06-16
**Commits:** reconstructed from session transcripts
**Files changed:** `portfolio/schema.sql`, `portfolio/seed.sql`, `agent/main.py`, `windmill/u/admin/portfolio_earnings_analysis.py`, `windmill/u/admin/portfolio_earnings_post_check.script.yaml`, `CLAUDE.md`, `docs/ROADMAP.md`, `docs/WORKFLOW_ARCHITECTURE.md`, `.env` (gitignored), `agent.env` (gitignored), `agent/tests/` (35 new tests), 9 new schedule YAML files, multiple Windmill scripts (recipient_email, telegram_owner_id references)

---

## Plan Completed

Full codebase audit conducted (documented in `docs/audit/260616_full_codebase_audit.md`) producing 30 findings across Critical / High / Medium / Low severity tiers. All 30 findings remediated in the same session. Session concluded with repo migration: `windmill-automations` (prior repo with credential history) replaced by `vps-stack` (fresh history, no git secrets). All remediations applied to the initial commit of `vps-stack`.

---

## All Tasks Performed

1. Conducted structured codebase audit — scanned all scripts, schema, seed data, docs, and git history for credential exposure, schema drift, code correctness, logging gaps, and security hygiene.
2. Filed 30 findings in `docs/audit/260616_full_codebase_audit.md` — categorised Critical (5), High (8), Medium (10), Low (7).
3. Extracted all hardcoded credentials and personal identifiers from Windmill scripts — replaced recipient emails with `$var:u/admin/recipient_email`, Telegram chat IDs with `$var:u/admin/telegram_owner_id`, Windmill token with `$var:u/admin/wm_token`. Pushed all updated scripts.
4. Removed Google Drive file ID from `seed.sql`.
5. Replaced owner identity fields in `CLAUDE.md` with env var placeholders (`${OWNER_NAME}`, `${OWNER_TITLE}`, `${OWNER_EMPLOYER}`, `${OWNER_BACKGROUND}`); real values stored in gitignored `.env`.
6. Scrubbed remaining personal identifiers from `README.md` and `CLAUDE.md` — VPS IP, GCP SA email, GCP project name, bot username all replaced with `<YOUR_*>` placeholders.
7. Added `portfolio_scores` table DDL to `schema.sql` (was live in DB but missing from schema file).
8. Removed `board_members` table from `schema.sql` (table existed in schema but was populated only by a broken parser producing garbage rows; removed at source).
9. Populated `consolidation_group` for ADR pairs in `seed.sql` — `BABA`/`9988.HK` and `BIDU`/`9888.HK` were missing their consolidation group values.
10. Fixed FIRE intent silent failure in `agent/main.py` — added fallback reply and log entry for unknown intents.
11. Made `synthesiser_model` dynamic in earnings analysis email footer (was hardcoded `"Grok-4.3"`).
12. Applied `chmod 600` to `.env` and `agent.env` (both were 644 — world-readable).
13. Broadened hookify block rules — prior block only covered `gmail_smtp`; extended to cover all 18 other named Windmill resources.
14. Narrowed Windmill `wmill sync *` pre-approval to `wmill sync pull --yes` only (defense-in-depth against accidental `wmill sync push`).
15. Wrote 35 new tests covering 8 previously untested Windmill scripts; brought total to 272 passing.
16. Exported 9 schedule YAML files from Windmill UI using `wmill sync pull`; added all to git (7 were UI-only, invisible to future syncs).
17. Closed earnings_analysis outstanding issues (5 items) — corrected `portfolio_earnings_post_check.script.yaml` empty schema (4 missing params filled in).
18. Added Hard Rules 12–15 to `CLAUDE.md` based on lessons from the audit session.
19. Updated all docs to current state — `ROADMAP.md`, `WORKFLOW_ARCHITECTURE.md`, `CLAUDE.md` Current Status section, test count to 272.
20. Rotated credentials (out-of-band owner task), ran `git filter-repo` on prior history, migrated to fresh `vps-stack` repo with clean initial commit.

---

## Bugs Encountered

### Bug 1 — `portfolio_scores` table missing from `schema.sql`

**Symptom:** `schema.sql` defined 28 tables; `\dt` on the live DB returned 29. `portfolio_scores` was written by `portfolio_rationalization.py`, referenced in `test_windmill_scripts.py`, and existed on the live DB — but was never added to the schema file.

**Root cause:** The table was created directly on the live DB during the rationalization build session (2026-06-14) via inline DDL in the script. `schema.sql` was not updated to reflect it. The schema file had drifted from the live DB.

**Fix:** Added full `CREATE TABLE portfolio_scores` DDL to `schema.sql` — 23 columns including all 4 scenario rank columns, delta tracking columns, completeness score, and timestamps.

---

### Bug 2 — FIRE intent silent failure on unknown intents

**Symptom:** If a user sent a Telegram message that matched no known intent, the agent silently returned with no reply and no log entry. From the user's perspective the message was simply ignored — no error, no acknowledgement.

**Root cause:** `agent/main.py` lines 220–236 contained `if FIRE_EXECUTORS.get(intent) is None: return` — a bare return with no logging and no reply to the user. The pattern was copied from an early stub and never updated when the agent went live.

**Fix:** Replaced bare return with a fallback Telegram reply ("I didn't understand that. Try /help.") and a `logger.warning` entry with the unrecognised intent string. Unknown intents are now visible in logs and acknowledged to the user.

---

### Bug 3 — Seven schedule YAML files outside git (invisible to future syncs)

**Symptom:** `CLAUDE.md` listed 13 scheduled workflows; only 6 had `.schedule.yaml` files committed to git. The remaining 7 (including `portfolio_rationalization_monthly`, `portfolio_move_monitor_hourly`, and others) were UI-only schedules that would be silently wiped by any future `wmill sync push` that treated the git state as authoritative.

**Root cause:** Schedule YAML files were created in the Windmill UI during workflow builds and never exported. The GitOps workflow documented in `CLAUDE.md` covered scripts and metadata YAMLs but had no explicit step for exporting schedules.

**Fix:** Ran `wmill sync pull --yes` to export all current Windmill state to disk. Identified 7 schedule YAML files now present locally but not in git. Added all 7 to git. Added an explicit step to the GitOps workflow documentation: after creating or modifying a schedule, always run `wmill sync pull` and commit the resulting `.schedule.yaml`.

---

### Bug 4 — 53 personal identifier instances in committed docs

**Symptom:** `CLAUDE.md`, `README.md`, and other committed docs contained real values for VPS IP address, recipient email addresses, owner name and employer, GCP service account email, GCP project name, and Telegram bot username.

**Root cause:** Docs were written during development with real values for convenience. No pre-commit scrub was performed. The `windmill-automations` repo was private throughout, so no public exposure occurred — but a future repo migration or accidental visibility change would expose all values.

**Fix:** Full regex replacement across all committed docs. Real values moved to `.env` (gitignored); `CLAUDE.md` identity fields now reference `${OWNER_NAME}` etc. All network identifiers replaced with `<YOUR_VPS_IP>`, `<YOUR_RECIPIENT_EMAIL>`, `<YOUR_DOMAIN>`, etc. A1 and A2 closed as N/A (private repo, no public exposure) with rotation done as belt-and-suspenders.

---

## Lessons Learned

1. **Schema drift is a continuous risk.** The `portfolio_scores` gap (table live in DB, absent from schema.sql) emerged within two weeks of the initial schema being written. Schema files must be updated in the same commit that introduces a new table — never as a follow-up. The schema file is the contract; the live DB should be considered ephemeral.
2. **Silent returns at dispatch boundaries are a silent UX failure.** A bare `return` after a failed lookup in a user-facing handler means the user gets no feedback and the operator gets no log. Every dispatch path must have a fallback that both replies to the user and logs the event.
3. **GitOps must explicitly cover schedules, not just scripts.** The GitOps workflow documentation covered script files and metadata YAMLs but was silent on schedule files. An undocumented gap in a workflow becomes a recurring omission — the next build session will repeat it. Extend the checklist before the session ends.
4. **Scrub personal identifiers before any repo sharing consideration, not after.** The cost of retrofitting 53 placeholder substitutions after the fact is significant. The right time to establish `<YOUR_VPS_IP>` placeholders is when the doc is first written. A template (`.env.example`) from day one makes this automatic.
5. **Broad exception pre-approvals are a security gap.** The `wmill sync *` pre-approval silently covered `wmill sync push`, which has caused resource deletion and stale deployments twice. Pre-approvals should be as narrow as the actual intended use — `wmill sync pull --yes` only. The hookify block is the primary enforcement layer; removing the pre-approval is defense-in-depth.
6. **Repo migration is cleaner than filter-repo for deep credential history.** When multiple credentials are spread across many historical commits, `git filter-repo` per-file is error-prone and slow. A fresh repo with a single clean initial commit guarantees no history leakage and is safer when the old repo was private and exposure risk is low.
7. **Audit and remediation in the same session prevents drift.** Running the audit and immediately fixing all findings in one session ensures nothing falls off the backlog. Audit findings filed as issues and deferred to later sessions frequently remain open indefinitely.
