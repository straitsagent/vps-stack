# Testing Philosophy — Test the Artifact the Human Receives

**Last updated:** 2026-06-22

---

## The Principle

> A test earns its place only if its failure means the human gets a broken or missing artifact.
>
> The authoritative tests render the **actual email HTML** and the **actual Telegram message**
> from **one real `main()` run** (I/O faked only at the edges) and assert that every
> user-visible field appears in **both**.
>
> Logs, `success: True`, and subject lines are **not** verification.

This replaced the prior pattern of source-substring checks (`assert "smtp" in src`) and
`success: True` / subject-line checks, which gave a false confidence that code worked while
the human was receiving broken or empty artifacts.

**Worked examples — tests that would have caught shipped bugs:**

| Bug | What shipping-tested | What would have caught it |
|-----|---------------------|--------------------------|
| YouTube digest miscount | Source substring `"email_count" in src` | `_render_artifacts()` + `assert count in email_html` |
| health_check email missing digest/spec/diagnoses (2026-06-22) | 4 `build_html` call tests + `success: True` | `test_hc_email_and_telegram_agree` |

---

## Test Hierarchy (High → Low Authority)

| Tier | Type | Authoritative for | Allowed when |
|------|------|-------------------|--------------|
| **1 — Artifact-render** | `_render_<script>_artifacts(world)` → assert on `email_html` + `tg_msg` | Email and Telegram content for every sending script | Always required for every script that sends email or Telegram |
| **2 — Round-trip contract** | `_build_md_content(fm, narrative)` → `_parse_md_report` → `_build_message` → assert fields | `.md` front-matter → formatter round-trip | One per formatter (8 total); uses the **real** `_build_md_content`, never a test-local fake |
| **3 — Architecture guard** | Source-level or module-level structural invariants | Script topology — e.g. no direct `_send_telegram` calls in main scripts; all 8 formatter `_send_telegram` copies are byte-identical | Structural constraints that render-tests can't catch |
| **4 — Substring** | `assert "keyword" in src` | Nothing rendered-content-related | Only for things with no artifact path (e.g., confirming a constant exists in source). **Lowest value.** Add a comment explaining why no artifact test is possible. |

---

## Artifact-Driven Development (the build process)

Building starts from the target artifact — not from the code.

1. **Design** (Hard Rule 7): Show the exact email and Telegram the human will receive. Include all sections, all field values. Get approval.
2. **Write the artifact test first (RED)**: `_render_<script>_artifacts(world)` → assert each field from the design appears in `email_html` AND `tg_msg`. Confirm the test fails.
3. **Implement**: Write the code to make the test green.
4. **Confirm GREEN**: All artifact tests pass.
5. **Live verify** (see below): Trigger a real run. Read the actual email body (IMAP). Read the actual Telegram text (formatter logs + `telegram_outbox`). Assert the same fields present in both.

Done = RED → GREEN → live body inspected → both artifacts agree.

---

## The `_render_<script>_artifacts(world)` Harness Pattern

Every sending script gets one harness function in `agent/tests/test_windmill_scripts.py`.

**Structure:**
```python
def _render_<script>_artifacts(world=None):
    """
    Run the real <script>.main() with all I/O seams mocked at the edges.
    Returns (email_html: str, md_content: str, telegram_message: str).
    """
    # 1. Load the script module
    mod = _load_<script>_module()
    tg_mod = _load_formatter("<script>")

    # 2. Mock edge I/O only (all external calls that don't produce artifact content):
    #    - Network/API helpers (wmill_get, fetch_sent_subjects, LLM synthesis, etc.)
    #    - _send_email     → capture email HTML
    #    - _write_canonical_md → capture .md content
    #    - _dispatch_formatter → no-op (we render Telegram manually)

    # 3. Run real main() with fake but realistic creds
    mod.main(gmail_smtp={...}, telegram_bot_token="fake", ...)

    # 4. Render the real Telegram message from the captured .md
    parsed_fm, narrative = tg_mod._parse_md_report(tmp_md_path)
    tg_msg = tg_mod._build_message(parsed_fm, narrative)

    return email_html, md_content, tg_msg
```

**The `world` fixture** must be minimum-viable-realistic (Hard Rule 15 tautology ban):
- Use distinct strings that must appear in the artifact (not generic placeholders)
- Include at least one FAILED/STALE schedule, one spec failure, one diagnosis
- Do NOT pre-size to match assertion thresholds

**Seam factoring** (required for main() to be drivable in tests):
- `_send_email(gmail_smtp, recipient, subject, html)` — patches SMTP send
- `_build_md_content(front_matter, narrative) -> str` — pure, testable
- `_write_canonical_md(md_content, path)` — patches file write
- `_build_front_matter(...) -> dict` — pure, single source for email + Telegram

Scripts that have these seams: `health_check`. Rollout to others: `portfolio_email`, `macro_research`, `portfolio_review`.

---

## Key Cross-Check Test

Every sending script must have a `test_<script>_email_and_telegram_agree` test:

```python
def test_hc_email_and_telegram_agree():
    """
    Shared fields (digest, each diagnosis, each spec violation) must appear
    in BOTH email HTML and Telegram message.
    This catches any code path where email and Telegram render from different sources.
    """
    email_html, _, tg_msg = _get_hc_artifacts()
    shared_fields = [
        ("digest", _HC_WORLD["digest"][:50]),
        ("diagnosis root_cause", _HC_WORLD["diagnosis"]["root_cause"]),
        ...
    ]
    for field_name, value in shared_fields:
        assert value in email_html, f"{field_name} missing from email"
        assert value in tg_msg,     f"{field_name} missing from Telegram"
```

---

## Live Verification Procedure (Hard Rule 17 + email extension)

After any live run of a sending script, all of the following must be true before
declaring it works:

**Email body (IMAP):**
- Fetch the email body (not just subject) from Gmail Sent folder via IMAP
- Assert each section present: digest, spec failures, diagnoses, status rows
- `success: True` / subject line is **not** verification

**Telegram:**
- Read `[Telegram] Sending (N chars, M words)` in formatter job logs — confirm M ≥ 500
- Query `telegram_outbox`: confirm `delivered = true`, `word_count ≥ 500`, `error IS NULL`
- Compare header values to `.md` front-matter
- Confirm no "→ email" / "see full report in email" pointer

**Agreement check:**
- The shared field set (digest, diagnoses, spec violations, schedule rows) must be present in both
- `test_hc_email_and_telegram_agree` (and its equivalents) encode this as an automated test

---

## Files

| File | Purpose |
|------|---------|
| `agent/tests/test_windmill_scripts.py` | All tests — artifact-render harnesses, round-trip contracts, architecture guards |
| `windmill/u/admin/health_check.py` | Proven example: `_send_email`, `_build_md_content`, `_write_canonical_md`, `_build_front_matter` factored |
| `docs/WORKFLOW_ARCHITECTURE.md` | Per-workflow front-matter schema contracts |
| `CLAUDE.md` Hard Rules 15–19 | Encoding of this philosophy as rules |

---

## Rollout Status

| Script | Seams factored | Artifact harness | `_agree` test | Substring tests pruned |
|--------|---------------|-----------------|---------------|----------------------|
| `health_check` | ✅ | ✅ | ✅ | ✅ (2 pruned) |
| `portfolio_email` | ✗ | ✗ | ✗ | ✗ |
| `macro_research` | ✗ (partial — `_send_email` exists) | ✗ | ✗ | ✗ |
| `portfolio_review` | ✗ | ✗ | ✗ | ✗ |
| `portfolio_rationalization` | ✗ | ✗ | ✗ | ✗ |
| `portfolio_move_monitor` | ✗ | ✗ | ✗ | ✗ |
| `portfolio_analyst_alert` | ✗ | ✗ | ✗ | ✗ |
| `youtube_monitor` | ✗ | ✗ | ✗ | ✗ |
