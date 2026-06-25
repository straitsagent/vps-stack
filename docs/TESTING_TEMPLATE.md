# Artifact Harness Template

Copy-paste starting point for `_render_<script>_artifacts(world)` in `agent/tests/test_windmill_scripts.py`.

```python
# ── <SCRIPT> ASD ─────────────────────────────────────────────────────────────
_<SCRIPT>_ASD_FIELD_1   = "<unique string 1>"
_<SCRIPT>_ASD_FIELD_2   = "<unique string 2>"
_<SCRIPT>_ASD_NARRATIVE = _<SCRIPT>_ASD_FIELD_1 + " <realistic ~600-word narrative...>"

_<SCRIPT>_ASD = {
    "email_required":    [_<SCRIPT>_ASD_FIELD_1, _<SCRIPT>_ASD_FIELD_2],
    "telegram_required": [_<SCRIPT>_ASD_FIELD_1, _<SCRIPT>_ASD_FIELD_2],
    "shared_fields": [
        ("field 1", _<SCRIPT>_ASD_FIELD_1),
        ("field 2", _<SCRIPT>_ASD_FIELD_2),
    ],
    "min_telegram_words": 500,
}

_<SCRIPT>_WORLD = {
    "field_1_key": _<SCRIPT>_ASD_FIELD_1,   # sourced from ASD
    "narrative":   _<SCRIPT>_ASD_NARRATIVE,  # sourced from ASD
    # ... other world keys ...
}

# ── Harness ───────────────────────────────────────────────────────────────────
_<SCRIPT>_ARTIFACTS_CACHE = {}

def _render_<script>_artifacts(world=None):
    """
    Run the real <script>.main() with all I/O seams mocked at the edges.
    Returns (email_html: str, md_content: str, telegram_message: str).
    """
    import tempfile as _tf
    if world is None:
        world = _<SCRIPT>_WORLD
    _validate_world_vs_asd(world, _<SCRIPT>_ASD)

    mod = _load_<script>_module()
    tg_mod = _load_formatter("<script>")

    captured_email_html = [None]
    captured_md_content = [None]

    def mock_send_email(gmail_smtp, recipient, subject, html):
        captured_email_html[0] = html

    def mock_write_canonical_md(md_content, path):
        captured_md_content[0] = md_content

    with (
        patch.object(mod, "<api_call_1>", return_value=world["<key1>"]),
        patch.object(mod, "_send_email",         side_effect=mock_send_email),
        patch.object(mod, "_write_canonical_md", side_effect=mock_write_canonical_md),
        patch.object(mod, "_dispatch_formatter"),
    ):
        mod.main(
            gmail_smtp={"host": "smtp.gmail.com", "port": 587,
                        "username": "test@example.com", "password": "testpass"},
        )

    email_html = captured_email_html[0]
    md_content = captured_md_content[0]

    telegram_message = None
    if md_content:
        with _tf.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as tmp:
            tmp.write(md_content)
            tmp_path = tmp.name
        try:
            parsed_fm, narrative = tg_mod._parse_md_report(tmp_path)
            telegram_message = tg_mod._build_message(parsed_fm, narrative)
        finally:
            os.unlink(tmp_path)

    return email_html, md_content, telegram_message


def _get_<script>_artifacts(force_refresh=False):
    if "v" not in _<SCRIPT>_ARTIFACTS_CACHE or force_refresh:
        _<SCRIPT>_ARTIFACTS_CACHE.clear()
        _<SCRIPT>_ARTIFACTS_CACHE["v"] = _render_<script>_artifacts()
    return _<SCRIPT>_ARTIFACTS_CACHE["v"]


# ── Assertion tests ────────────────────────────────────────────────────────────
def test_<script>_email_and_telegram_agree():
    """Shared ASD fields must appear in BOTH email HTML and Telegram message."""
    email_html, _, tg_msg = _get_<script>_artifacts()
    assert email_html is not None, "_send_email was never called"
    assert tg_msg is not None, "_build_message returned None"
    failures = []
    for field_name, value in _<SCRIPT>_ASD["shared_fields"]:
        if value not in email_html:
            failures.append(f"  MISSING from email:    {field_name} = {value!r}")
        if value not in tg_msg:
            failures.append(f"  MISSING from Telegram: {field_name} = {value!r}")
    assert not failures, "Shared fields must appear in BOTH artifacts:\n" + "\n".join(failures)


def test_<script>_telegram_min_word_count():
    """Telegram message must be ≥500 words (Hard Rule 16)."""
    _, _, tg_msg = _get_<script>_artifacts()
    assert tg_msg is not None
    word_count = len(tg_msg.split())
    assert word_count >= _<SCRIPT>_ASD["min_telegram_words"], (
        f"Telegram has {word_count} words — must be ≥{_<SCRIPT>_ASD['min_telegram_words']}"
    )
```

**Seam factoring** (required for main() to be drivable in tests):
- `_send_email(gmail_smtp, recipient, subject, html)` — patches SMTP send
- `_build_md_content(front_matter, narrative) -> str` — pure, testable
- `_write_canonical_md(md_content, path)` — patches file write
- `_build_front_matter(...) -> dict` — pure, single source for email + Telegram
