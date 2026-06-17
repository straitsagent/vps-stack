# Implementation Log — Morning News Digest (1.1) + GitOps Workflow
**Date:** 2026-06-03 (multi-session day — 5 sessions, ~6.2MB of transcript)
**Commits:** `<initial gitops commit>`, plus 15 commits reconstructed from session transcripts (see below)
**Files changed:** `windmill/u/admin/morning_news_digest.py`, `windmill/u/admin/morning_news_digest.script.yaml`, `windmill/u/admin/error_alert.py`, `windmill/u/admin/error_alert.script.yaml`, `windmill/u/admin/email_summary.py`, `windmill/u/admin/email_summary.script.yaml`, `wmill.yaml`, `.gitignore`, `CLAUDE.md`, `docs/ROADMAP.md`, `docs/WORKFLOW_ARCHITECTURE.md`, `shared/override_log.md`

---

## Plan Completed

Established the GitOps workflow for Windmill script management. Built Workflow 1.1 (Morning News Digest) — RSS headlines from major financial news sources, Deepseek AI summaries of Gmail newsletters, programmatic key-link extraction, and token cost tracking. Built Email Summary workflow (on-demand Deepseek summarisation of Gmail inbox). Added Hard Rules 7, 8, 9, and 12 to prevent recurrence of the day's incidents.

---

## All Tasks Performed

1. Created `windmill/` directory as the git-tracked script sync directory
2. Configured `wmill.yaml`: `includes: ["u/**"]` — tracks only user scripts, not system resources
3. Fixed `.gitignore` to include `windmill/` (it had been excluded as a data directory)
4. Pushed first tracked script `error_alert.py` (Workflow 5.2) as a baseline
5. Created initial `shared/override_log.md` for manual intervention tracking
6. Documented GitOps workflow in CLAUDE.md: write locally → push with `wmill script push` → test in UI → commit to git
7. Built Workflow 1.1 v1 — RSS digest from FT, Reuters, Straits Times, Google News filtered by APAC infrastructure keywords; scheduled 6:30 AM SGT daily
8. Revamped 1.1 to 5-section format: RSS headlines, Google News keyword alerts, Deepseek newsletter summaries via IMAP, newsletter headlines, section summary
9. User requested changes: drop Straits Times, add WSJ/NYT/Barron's, read newsletters from Gmail inbox
10. Attempted Gmail IMAP newsletter integration as the primary content source (see Bug 2)
11. Reverted to pre-revamp version after user rejected the restructured format
12. Re-implemented newsletter summaries via Gmail IMAP within the existing RSS-first structure
13. Switched Deepseek response parsing from fragile regex to JSON response format (see Bug 4)
14. Fixed empty summaries caused by infrastructure finance persona in system prompt (see Bug 3)
15. Added programmatic key-link extraction from newsletter HTML
16. Added token cost tracking and estimated API cost at top of email
17. Added <YOUR_WORK_EMAIL> to distribution list
18. Built Email Summary workflow — reads Gmail INBOX last 24h via IMAP, summarises with deepseek-chat
19. Created `docs/WORKFLOW_ARCHITECTURE.md` with full pseudocode specs for all workflows
20. Documented `gmail_smtp` deletion incident in `shared/override_log.md`
21. Added Hard Rule 7 (design approval before coding), Hard Rule 8 (never delete resources), Hard Rule 9 (use `wmill script push`), Hard Rule 12 (approval before modifying existing workflows)
22. Added hookify block rule `hookify.block-wmill-sync-push.local.md` — blocks `wmill sync push` at the tool layer
23. Added hookify block rule `hookify.block-gmail-smtp-delete.local.md` — blocks resource/variable deletion for `gmail_smtp`
24. Recreated `gmail_smtp` resource and `deepseek_key` variable via Windmill API after accidental deletion
25. Uploaded `keys.md` backup to Google Drive as a plain-text file
26. Consolidated project documentation into CLAUDE.md + ROADMAP.md (removed earlier scattered docs)

**Commit sequence (reconstructed):**
1. "Set up GitOps workflow for Windmill scripts"
2. "Add Workflow 1.1 — Morning News Digest"
3. "Revamp Morning Digest to 5-section format with newsletter AI summaries"
4. "Add WORKFLOW_ARCHITECTURE.md with per-workflow pseudocode specs"
5. "Document gmail_smtp incident and add Drive backup of keys.md"
6. "Consolidate docs into CLAUDE.md + ROADMAP.md"
7. "Add Email Summary workflow (Deepseek)"
8. "Require design approval before coding any workflow — Hard rule 7"
9. "Revamp morning_news_digest: merge RSS + Gmail newsletters"
10. "Cap newsletter roundup at 10 articles per source"
11. "Revert morning_news_digest to pre-revamp version"
12. "Revamp 1.1 Morning Digest: JSON summaries, key links, token tracking"
13. "Fix 1.1 summaries: generic prompt, programmatic links, cost at top"
14. "Add <YOUR_WORK_EMAIL> to Morning Digest distribution list"
15. "Update docs to reflect 1.1 revamp"
16. "Prevent recurrence of session bugs — Hard rules and documentation added"

---

## Bugs Encountered

**Bug 1 — `wmill sync push` wiped `gmail_smtp` resource and `deepseek_key` variable (occurred twice)**

Symptom: After running `wmill sync push`, all Windmill scripts failed with authentication errors. Morning digest and email summary stopped working. Investigation revealed `gmail_smtp` and `deepseek_key` were gone from the Windmill workspace.

Root cause: `wmill sync push` performs a full workspace sync — it does not just push script files. Despite `skipResources: true` flags, the command deployed stale archived versions of resources and variables that had been snapshotted to disk at an earlier state, overwriting the live credentials. The CLI treats the local disk as the source of truth for the entire workspace, not just scripts.

Fix: Manually recreated `gmail_smtp` (SMTP resource) and `deepseek_key` (plain variable) via the Windmill REST API:
```bash
curl -s -X POST "http://<VPS_IP>:8080/api/w/admins/resources/create" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"path":"u/admin/gmail_smtp","resource_type":"smtp","value":{...}}'

wmill variable add "<key>" u/admin/deepseek_key --plain-secrets
```
Added Hard Rule 8 (never delete/overwrite resources), Hard Rule 9 (use `wmill script push` only), and hookify block rule that rejects any `wmill sync push` Bash call at the tool layer. Removed broad `wmill sync *` pre-approval from `settings.json` as defense-in-depth.

---

**Bug 2 — Newsletter integration reverted after restructuring the digest without approval**

Symptom: The newsletter integration attempt restructured the morning digest from RSS-first to Gmail-IMAP-first as the primary content source, reorganising the sections. User described the result as having "butchered" the digest and requested a full revert.

Root cause: Claude redesigned the overall structure of a working workflow during implementation, without describing the structural change and getting explicit approval. The user's request was to add newsletter summaries — not to change the email's information architecture. The change was treated as an implementation detail rather than a design decision.

Fix: Reverted to pre-revamp version via git. Re-implemented newsletter summaries within the existing RSS-first structure, without changing section order or layout. Added Hard Rule 7 (describe full design in plain English and get approval before coding) and Hard Rule 12 (approval required before modifying any existing working workflow).

---

**Bug 3 — Deepseek infrastructure finance persona silently skipped newsletter summaries**

Symptom: Newsletter summaries returned empty strings for most sources. The digest would show newsletters in the source list but no summary content.

Root cause: The Deepseek system prompt contained: "You are an infrastructure finance professional providing a morning briefing." Deepseek interpreted general news content (politics, tech, markets) as outside the scope of an infrastructure finance professional and returned empty or near-empty summaries rather than surfacing an error.

Fix: Removed the persona entirely from the system prompt. Replaced with a plain instruction: "Summarise the following newsletter content in 3-5 sentences, focusing on the key stories and themes." Hard Rule 10 was added: always show the exact LLM prompt text and get explicit approval before coding it — domain-specific personas can cause silent content filtering.

---

**Bug 4 — Fragile regex parsing of Deepseek free-text responses**

Symptom: Newsletter summaries and key-link extraction produced empty or garbled results intermittently. The output varied across runs even with the same input content.

Root cause: The initial implementation asked Deepseek to respond in a structured plain-text format with labelled sections (`SUMMARY:`, `KEY LINKS:`), then used regex to parse those sections. Deepseek varied its formatting — sometimes omitting labels, sometimes adding extra whitespace or punctuation — causing the regex to fail silently.

Fix: Switched to `response_format={"type": "json_object"}` and instructed Deepseek to return a JSON object with defined keys (`summary`, `key_links`). JSON parsing is deterministic and raises a clear exception on failure rather than returning empty strings.

---

## Lessons Learned

1. Never use `wmill sync push` for routine script deployments. The only safe command is `wmill script push <path>`. The `sync push` command treats the local disk as the source of truth for the entire workspace and will overwrite live credentials with stale disk state.
2. Hookify block rules at the tool layer are more reliable than prose rules or memory. The `wmill sync push` block has prevented a third incident — the model cannot reason its way around a tool-layer rejection.
3. When modifying an existing working workflow, always describe the structural changes and get explicit approval before coding. Implementation requests ("add newsletter summaries") do not authorise architectural changes ("restructure the email format").
4. LLM personas in system prompts cause silent content filtering. A persona like "infrastructure finance professional" causes the model to judge content relevance and skip anything it deems off-topic, returning empty output with no error signal. Keep prompts generic unless a persona is explicitly requested and tested.
5. Use `response_format=json_object` for any structured output from LLMs. Regex on free-text LLM responses is fragile — model formatting varies across runs, versions, and input content.
6. Store all credential recreation commands in `CLAUDE.md` and `override_log.md` immediately after a recovery. The second `gmail_smtp` recreation was significantly faster because the first recovery was documented.
7. Upload a `keys.md` backup to Google Drive after any credential rotation or new key addition. The VPS file is the primary store but Drive is the off-VPS backup for recovery without SSH access.
