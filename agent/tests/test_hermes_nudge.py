"""Tests for the Hermes nudge inbox writer (shared/python/utils/hermes_nudge.py)
and its CLI wrapper (scripts/nudge-hermes.py)."""
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile

import pytest
import yaml

sys.path.insert(0, "/root/shared/python/utils")

from hermes_nudge import URGENCY_LEVELS, write_nudge  # noqa: E402


@pytest.fixture
def tmp_inbox():
    d = tempfile.mkdtemp()
    inbox = os.path.join(d, "inbox")
    yield inbox
    shutil.rmtree(d, ignore_errors=True)


def _read_front_matter(path):
    text = open(path).read()
    parts = text.split("---")
    assert len(parts) >= 3, f"expected YAML front-matter delimiters, got: {text[:200]}"
    return yaml.safe_load(parts[1]), "---".join(parts[2:])


class TestSchemaRoundtrip:
    def test_schema_roundtrip_required_keys(self, tmp_inbox):
        path = write_nudge(
            source="claude-code",
            subject="Test subject",
            body="Test body content.",
            urgency="soon",
            evidence=[{"type": "plan", "ref": "docs/plans/x.md"}],
            inbox_dir=tmp_inbox,
        )
        fm, body = _read_front_matter(path)
        for key in ("schema_version", "nudge_id", "source", "created_at", "urgency",
                    "expires_at", "advisory", "evidence", "subject"):
            assert key in fm, f"missing key {key}"
        assert fm["advisory"] is True
        assert fm["source"] == "claude-code"
        assert fm["urgency"] == "soon"
        assert fm["evidence"] == [{"type": "plan", "ref": "docs/plans/x.md"}]
        assert "advisory notice, not an instruction" in body

    def test_schema_roundtrip_no_evidence(self, tmp_inbox):
        path = write_nudge(source="claude-code", subject="No evidence", body="body", inbox_dir=tmp_inbox)
        fm, _ = _read_front_matter(path)
        assert fm["evidence"] in ([], None)
        assert fm["advisory"] is True


class TestValidation:
    def test_validation_empty_source(self, tmp_inbox):
        with pytest.raises(ValueError, match="source"):
            write_nudge(source="", subject="s", body="b", inbox_dir=tmp_inbox)

    def test_validation_bad_source_chars(self, tmp_inbox):
        with pytest.raises(ValueError, match="source"):
            write_nudge(source="Claude Code!", subject="s", body="b", inbox_dir=tmp_inbox)

    def test_validation_empty_subject(self, tmp_inbox):
        with pytest.raises(ValueError, match="subject"):
            write_nudge(source="claude-code", subject="", body="b", inbox_dir=tmp_inbox)

    def test_validation_subject_too_long(self, tmp_inbox):
        with pytest.raises(ValueError, match="subject"):
            write_nudge(source="claude-code", subject="x" * 201, body="b", inbox_dir=tmp_inbox)

    def test_validation_empty_body(self, tmp_inbox):
        with pytest.raises(ValueError, match="body"):
            write_nudge(source="claude-code", subject="s", body="", inbox_dir=tmp_inbox)

    def test_validation_bad_urgency(self, tmp_inbox):
        with pytest.raises(ValueError, match="urgency"):
            write_nudge(source="claude-code", subject="s", body="b", urgency="critical", inbox_dir=tmp_inbox)

    def test_validation_malformed_evidence_not_list(self, tmp_inbox):
        with pytest.raises(ValueError, match="evidence"):
            write_nudge(source="claude-code", subject="s", body="b", evidence="not-a-list", inbox_dir=tmp_inbox)

    def test_validation_malformed_evidence_entry(self, tmp_inbox):
        with pytest.raises(ValueError, match="evidence"):
            write_nudge(source="claude-code", subject="s", body="b", evidence=[{"type": "plan"}], inbox_dir=tmp_inbox)

    def test_validation_bad_expires_at(self, tmp_inbox):
        with pytest.raises(ValueError, match="expires_at"):
            write_nudge(source="claude-code", subject="s", body="b", expires_at="not-a-date", inbox_dir=tmp_inbox)

    def test_validation_good_expires_at_accepted(self, tmp_inbox):
        path = write_nudge(source="claude-code", subject="s", body="b",
                            expires_at="2026-07-03T00:00:00Z", inbox_dir=tmp_inbox)
        fm, _ = _read_front_matter(path)
        assert fm["expires_at"] == "2026-07-03T00:00:00Z"


class TestAtomicWrite:
    def test_atomic_no_tmp_remnants(self, tmp_inbox):
        for i in range(5):
            write_nudge(source="claude-code", subject=f"atomic check {i}", body="b", inbox_dir=tmp_inbox)
        leftover = [f for f in os.listdir(tmp_inbox) if f.startswith(".tmp-")]
        assert leftover == [], f"leftover temp files: {leftover}"

    def test_atomic_full_content_present_immediately(self, tmp_inbox):
        path = write_nudge(source="claude-code", subject="content check", body="full body text", inbox_dir=tmp_inbox)
        assert os.path.getsize(path) > 0
        assert "full body text" in open(path).read()


class TestPermissionsBootstrap:
    def test_bootstrap_chown_and_not_world_writable(self, tmp_inbox):
        write_nudge(source="claude-code", subject="perm check", body="b", inbox_dir=tmp_inbox)
        st = os.stat(tmp_inbox)
        mode = stat.S_IMODE(st.st_mode)
        assert mode & 0o002 == 0, f"inbox_dir must not be world-writable, mode={oct(mode)}"
        processed = os.path.join(tmp_inbox, "processed")
        assert os.path.isdir(processed)
        pmode = stat.S_IMODE(os.stat(processed).st_mode)
        assert pmode & 0o002 == 0, f"processed dir must not be world-writable, mode={oct(pmode)}"


class TestNamingConvention:
    def test_naming_filename_pattern(self, tmp_inbox):
        path = write_nudge(source="claude-code", subject="WS-1 consumer live!", body="b", inbox_dir=tmp_inbox)
        filename = os.path.basename(path)
        assert re.match(
            r"^\d{4}-\d{2}-\d{2}T\d{6}Z_claude-code_ws-1-consumer-live(-[0-9a-f]{4})?\.md$",
            filename,
        ), filename

    def test_naming_nudge_id_matches_filename_stem(self, tmp_inbox):
        path = write_nudge(source="claude-code", subject="stem check", body="b", inbox_dir=tmp_inbox)
        fm, _ = _read_front_matter(path)
        stem = os.path.splitext(os.path.basename(path))[0]
        assert fm["nudge_id"] == stem

    def test_naming_collision_appends_suffix(self, tmp_inbox):
        path1 = write_nudge(source="claude-code", subject="collide", body="b1", inbox_dir=tmp_inbox)
        path2 = write_nudge(source="claude-code", subject="collide", body="b2", inbox_dir=tmp_inbox)
        assert path1 != path2
        assert os.path.isfile(path1) and os.path.isfile(path2)


class TestCli:
    def _run_cli(self, *extra_args):
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write("cli test body")
            body_file = f.name
        try:
            return subprocess.run(
                [sys.executable, "/root/scripts/nudge-hermes.py",
                 "--source", "claude-code", "--subject", "cli test",
                 "--body-file", body_file, *extra_args],
                capture_output=True, text=True,
            )
        finally:
            os.unlink(body_file)

    def test_cli_valid_call_exits_zero(self, tmp_inbox):
        result = self._run_cli("--urgency", "soon", "--inbox-dir", tmp_inbox)
        assert result.returncode == 0, result.stderr
        path = result.stdout.strip()
        assert os.path.isfile(path)

    def test_cli_invalid_urgency_exits_nonzero(self, tmp_inbox):
        result = subprocess.run(
            [sys.executable, "/root/scripts/nudge-hermes.py",
             "--source", "claude-code", "--subject", "bad", "--urgency", "notaurgency",
             "--body-file", "/etc/hostname", "--inbox-dir", tmp_inbox],
            capture_output=True, text=True,
        )
        assert result.returncode != 0
