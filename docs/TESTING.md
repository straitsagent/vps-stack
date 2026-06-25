# Testing Philosophy — Test the Artifact the Human Receives

**Last updated:** 2026-06-23

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

## What "Broken" Means

An artifact is **broken** if any of the following are true:

- **(a)** Email body is empty, not sent, or not delivered.
- **(b)** A required section is absent (digest, diagnoses, spec failures, status rows).
- **(c)** A field value is wrong: null, `$0` where not expected, wrong sign (negative rendered as positive), wrong currency.
- **(d)** Telegram `word_count < 500` (Hard Rule 16).
- **(e)** `delivered = false` or `error IS NOT NULL` in `telegram_outbox`.

Tier 0 (production verification) and Tier 1 (artifact-render tests) each catch a different subset of
these. Both are required.

---

## Test Hierarchy (High → Low Authority)

| Tier | Type | Authoritative for | When |
|------|------|-------------------|------|
| **0 — Production verify** | `health_check` fetches delivered email bodies, checks structural markers via `_artifact_body_check` | Actual delivery + structural completeness post-deployment | Automated daily (runs inside health_check) |
| **1 — Artifact-render** | `_render_<script>_artifacts(world)` → assert on `email_html` + `tg_msg` | Email and Telegram content correctness | Always required for every script that sends email or Telegram |
| **2 — Round-trip contract** | `_build_md_content(fm, narrative)` → `_parse_md_report` → `_build_message` → assert fields | `.md` front-matter → formatter round-trip | One per formatter (8 total); uses the **real** `_build_md_content`, never a test-local fake |
| **3 — Architecture guard** | Source-level or module-level structural invariants | Script topology — e.g. no direct `_send_telegram` calls in main scripts; all 8 formatter `_send_telegram` copies are byte-identical | Structural constraints that render-tests can't catch |
| **4 — Substring** | `assert "keyword" in src` | Nothing rendered-content-related | Only for things with no artifact path (e.g., confirming a constant exists in source). **Lowest value.** Add a comment explaining why no artifact test is possible. |

---

## Artifact Specification Documents (ASD)

Every sending script has a `_<SCRIPT>_ASD` dict in `test_windmill_scripts.py`. The ASD is the
**authoritative pre-implementation spec** — it is written before the world fixture, and the world
fixture is built to contain the ASD's required strings. This prevents the world fixture from being
crafted to pass its own assertions (gap A4).

**ASD format:**
```python
_<SCRIPT>_ASD = {
    # Strings that MUST appear in email_html — distinct, non-template values from the world fixture
    "email_required": ["<unique string from world>", ...],
    # Strings that MUST appear in tg_msg
    "telegram_required": ["<unique string from world>", ...],
    # The shared set: (label, value) tuples — drives test_<script>_email_and_telegram_agree
    # mechanically. Add here, not in the test.
    "shared_fields": [
        ("field label", "<unique string>"),
        ...
    ],
    "min_telegram_words": 500,
}
```

**World fixture** is then built to contain those ASD strings:
```python
_<SCRIPT>_WORLD = {
    "diagnosis": {
        "root_cause": _<SCRIPT>_ASD_ROOT_CAUSE,    # references ASD constant
        ...
    },
    ...
}
```

**`_validate_world_vs_asd(world, asd)`** is called at the top of every harness. It asserts every
ASD-required string appears somewhere in the world fixture — fails loudly if the ASD is updated
without updating the world.

**Invariant:** ASD → world fixture → assertions. Never the reverse.

---

## Testing Critic (Gap A2 — adversarial self-review)

Before committing any artifact test, apply this 5-point adversarial checklist. A test **fails the
Critic** if the answer to any question is "yes":

1. **Empty-artifact check:** Can `email_html` and `tg_msg` both be empty strings/`None` and all
   assertions still pass? (Harness must have `assert email_html is not None` and
   `assert tg_msg is not None` guards — enforced by Hard Rule 20.)

2. **Template-string check:** Could any asserted string appear in boilerplate HTML/template text
   *independently* of the world fixture? (e.g., asserting `"Email"` or `"Schedule"` which appear in
   every template header — use world-fixture-unique strings only.)

3. **Tautology check:** Is any asserted value derived from a fixture value pre-sized to match the
   threshold? (e.g., feeding a 500-word fixture into `_build_message` and asserting ≥500 words —
   use a realistic narrative, not a padded stub.)

4. **ASD-derived check:** Is every asserted string present in `_SCRIPT_ASD`? If not, document in a
   comment why no ASD entry exists.

5. **Completeness check:** Does `test_<script>_email_and_telegram_agree` cover **all**
   `_SCRIPT_ASD["shared_fields"]` entries? The test must iterate `_SCRIPT_ASD["shared_fields"]`
   directly — not a hand-picked subset.

This checklist is encoded as Hard Rule 20 in CLAUDE.md.

---

## Artifact-Driven Development (the build process)

Building starts from the target artifact — not from the code.

1. **Design** (Hard Rule 7): Show the exact email and Telegram the human will receive. Include all sections, all field values. Get approval.
2. **Write the ASD first:** Define `_<SCRIPT>_ASD` with the required strings. These are your spec.
3. **Write the artifact test (RED):** Build `_<SCRIPT>_WORLD` from the ASD. Write `_render_<script>_artifacts(world)`. Assert each ASD-required field. Apply the Testing Critic checklist. Confirm the test **fails**.
4. **Implement:** Write the code to make the test green.
5. **Confirm GREEN:** All artifact tests pass. Word-count assertion ≥500 passes.
6. **Live verify** (see below): Trigger a real run. Read the actual email body (IMAP). Read the actual Telegram text. Assert the same fields present in both.

Done = ASD written → RED → GREEN → live body inspected → both artifacts agree.

---

## The `_render_<script>_artifacts(world)` Harness Pattern

Every sending script gets one harness function in `agent/tests/test_windmill_scripts.py`.
Copy the pattern from any existing harness there (e.g. `_render_health_check_artifacts`).
A standalone template is available at `docs/TESTING_TEMPLATE.md`.

---

## Key Cross-Check Test

Every sending script must have a `test_<script>_email_and_telegram_agree` test. The `shared_fields`
list **must be derived from `_SCRIPT_ASD["shared_fields"]`** — never a hand-written subset:

```python
# ✅ Correct — ASD-derived, mechanical coverage
shared_fields = _HC_ASD["shared_fields"]

# ❌ Wrong — hand-written subset, will miss new ASD entries
shared_fields = [
    ("digest", _HC_WORLD["digest"][:50]),
    ...  # could silently miss new required fields
]
```

---

## Tier 0 — Production Artifact Verification

Tier 0 runs automatically inside `health_check.py` daily. It fetches actual delivered email bodies
via IMAP and checks for structural markers from `ARTIFACT_MARKERS`.

**Implementation in `health_check.py`:**
- `_fetch_sent_body(gmail_smtp, subject_fragment, hours=25)` — IMAP fetch, returns HTML body
- `_artifact_body_check(body, required_markers)` — pure check, returns `{pass, missing, found}`
- `ARTIFACT_MARKERS` dict — per-script structural HTML markers (field labels, section headers)

**What Tier 0 catches that Tier 1 misses:**
- Delivery failure (email never arrived)
- Script deployed with broken seams (e.g. `_send_email` was accidentally removed)
- Template regression that removes structural sections from the HTML
- Post-deploy regressions between green tests and a live run

**What Tier 0 does NOT replace:**
- Tier 1 artifact-render tests (Tier 0 checks structure, Tier 1 checks content correctness)
- Hard Rule 17 live verification on first deploy (Tier 0 is automated; Hard Rule 17 is manual + inspected)

---

## Live Verification Procedure (Hard Rule 17)

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
- `test_<script>_email_and_telegram_agree` (and its equivalents) encode this as an automated test

---

## Verify the Response, Not the Request (Hard Rule 21)

Hard Rule 17's procedures (IMAP body fetch, `word_count ≥ 500`, "→ email" pointer check) are
written for ≥500-word text reports. For non-report sends (stickers, short messages, emojis) or any
send where the API may silently drop parameters, Rule 17's *principle* (inspect the actual delivered
artifact) still applies — but the *procedure* must be adapted. Hard Rule 21 closes this gap.

**The problem:** APIs may return `ok: true` while silently dropping parameters. Telegram's
`sendSticker` accepts a `caption` parameter but never delivers it — the response has no `caption`
field, and no error is returned. A test that asserts `payload["caption"] == X` proves the code
*sent* the parameter; it does not prove the user *received* it.

### Testing rule

Mock the API to return a **realistic response** — including fields the API actually returns,
**omitting** fields it silently drops. Then assert on the response, not the request:

```python
# ❌ Wrong — asserts on the request payload. Proves nothing about delivery.
assert payload["caption"] == "hello there"

# ✅ Correct — mocks a realistic sendSticker response (no caption field),
# asserts the code detects the missing field and reports failure.
class _FakeStickerResp:
    def json(self):
        return {"ok": True, "result": {"message_id": 1, "sticker": {"emoji": "🥰"}}}
        # note: no "caption" field — Telegram drops it silently

def test_send_sticker_detects_missing_caption(monkeypatch):
    mod = _load_affection_mod()
    monkeypatch.setattr(requests, "post", lambda *a, **kw: _FakeStickerResp())
    delivered, err = mod._send_sticker("tok", "-123", "FILE", "hello there")
    # Code must detect that caption was not delivered and report it
    assert "caption" in err.lower(), "Must flag missing caption in error"
```

For sends where the response *does* include the content field (e.g. `sendMessage` returns
`result.text`), assert directly on that field:

```python
# ✅ Correct — asserts the text field is present and matches in the response
assert response["result"]["text"] == "hello there"
```

### Live verification rule

Inspect the actual API response JSON. Do not trust `ok: true`, `delivered: True` from your own
code, or DB rows written by your own code. For every user-visible field the send is supposed to
deliver:

| Send type | What to check in the response | What is NOT verification |
|---|---|---|
| `sendMessage` (text) | `result.text` present and matches expected content | `ok: true`; `delivered: True` in your DB |
| `sendSticker` | `result.sticker.emoji` present and matches expected emoji; `result.sticker.file_id` matches what was sent | `ok: true`; `payload["sticker"]` in the request |
| `sendSticker` with caption | **Caption is never in the response** — if a caption is needed, send it via `sendMessage` first, then verify `result.text` on the `sendMessage` response | `payload["caption"]` in the request |
| Sticker content audit | Resolve `file_id` back to its emoji via `getStickerSet`, assert emoji is in the expected set (e.g. `_AFFECTIONATE_EMOJIS`) | Trusting `random.choice` picked correctly |

### Worked example — the bugs this rule would have caught

**Bug 1 (2026-06-23): `sendSticker` caption silently dropped.**
- What shipped: `_send_sticker` sent `caption` in the `sendSticker` payload, checked `body.get("ok")`, reported `delivered: True`.
- What Rule 21 requires: inspect `sendSticker` response — no `caption` field present. Code must detect this and either send caption via `sendMessage` or report failure.
- What the test should have been: mock `sendSticker` returning `{ok: true, result: {sticker: {...}}}` (no caption), assert `_send_sticker` flags the missing caption.

**Bug 2 (2026-06-23): Angry-emoji sticker paired with loving caption.**
- What shipped: `random.choice` over 77 stickers including 😡😢😭😈, no emoji filter, no verification of delivered sticker's emoji.
- What Rule 21 requires: resolve delivered `file_id` to its emoji via `getStickerSet`, assert emoji is affectionate.
- What the live verification should have been: `getStickerSet` → find the sticker by `file_id` → check `sticker.emoji` ∈ `_AFFECTIONATE_EMOJIS`.

---

## Files

| File | Purpose |
|------|---------|
| `agent/tests/test_windmill_scripts.py` | All tests — ASD dicts, artifact-render harnesses, round-trip contracts, architecture guards |
| `windmill/u/admin/health_check.py` | Proven example: `_send_email`, `_build_md_content`, `_write_canonical_md`, `_build_front_matter` factored; Tier 0 `_fetch_sent_body` + `_artifact_body_check` |
| `docs/WORKFLOW_ARCHITECTURE.md` | Per-workflow front-matter schema contracts |
| `CLAUDE.md` Hard Rules 15–21 | Encoding of this philosophy as rules |

---

## Rollout Status

Per-script checklist: ASD written → seams factored → harness RED→GREEN → word_count ≥500 →
`_agree` test ASD-derived → substring tests pruned → Tier 0 `ARTIFACT_MARKERS` entry added →
live verify (Hard Rule 17).

| Script | ASD | Seams factored | Artifact harness | `_agree` ASD-derived | Word-count test | Tier 0 markers | Substring tests pruned | Live verified |
|--------|-----|---------------|-----------------|---------------------|-----------------|----------------|----------------------|---------------|
| `health_check` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ (2 pruned) | 🔲 |
| `macro_research` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | 🔲 | 🔲 |
| `portfolio_email` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | 🔲 | 🔲 |
| `portfolio_review` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | 🔲 | 🔲 |
| `portfolio_rationalization` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | 🔲 | 🔲 |
| `portfolio_move_monitor` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | 🔲 | 🔲 |
| `portfolio_analyst_alert` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | 🔲 | 🔲 |
| `youtube_monitor` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | 🔲 | ✅ |

**Rollout order:** `macro_research` (partial seams) → `portfolio_email` → `portfolio_review` →
`portfolio_rationalization` → `portfolio_move_monitor` → `portfolio_analyst_alert` → `youtube_monitor`.
Each is one commit, per the same pattern as `health_check`.
