"""Tests for routing logic — slash stripping and draft group command parsing."""
import re


def _strip_slash(text: str) -> str:
    """Mirrors the slash-stripping logic in main.py handle_owner."""
    return text[1:] if text.startswith("/") else text


def test_slash_stripped_from_command():
    assert _strip_slash("/portfolio") == "portfolio"
    assert _strip_slash("/research NVDA") == "research NVDA"
    assert _strip_slash("/health") == "health"


def test_no_slash_unchanged():
    assert _strip_slash("portfolio") == "portfolio"
    assert _strip_slash("research NVDA deep") == "research NVDA deep"


def test_double_slash_only_strips_first():
    assert _strip_slash("//portfolio") == "/portfolio"


def test_empty_string_unchanged():
    assert _strip_slash("") == ""


# ── Drafts group command regexes (from main.py handle_drafts_group) ───────────

SEND_RE  = re.compile(r"^/send_(\d+)$", re.IGNORECASE)
IGNORE_RE = re.compile(r"^/ignore_(\d+)$", re.IGNORECASE)
EDIT_RE  = re.compile(r"^/edit_(\d+)\s+(.+)$", re.IGNORECASE | re.DOTALL)


def test_send_command_parses():
    m = SEND_RE.match("/send_42")
    assert m and m.group(1) == "42"


def test_send_command_case_insensitive():
    assert SEND_RE.match("/SEND_7") is not None


def test_ignore_command_parses():
    m = IGNORE_RE.match("/ignore_99")
    assert m and m.group(1) == "99"


def test_edit_command_parses():
    m = EDIT_RE.match("/edit_3 new reply text here")
    assert m and m.group(1) == "3" and m.group(2) == "new reply text here"


def test_invalid_send_does_not_match():
    assert SEND_RE.match("/send_") is None
    assert SEND_RE.match("/send_abc") is None
    assert SEND_RE.match("send_1") is None


# ── Structured research commands (STRUCT_RESEARCH_RE) ────────────────────────

STRUCT_RESEARCH_RE = re.compile(
    r"^(stockresearch|deepresearch|research)(?:\s+(.*))?\s*$",
    re.IGNORECASE | re.DOTALL,
)


def test_struct_re_matches_stockresearch():
    assert STRUCT_RESEARCH_RE.match("stockresearch NVDA") is not None


def test_struct_re_matches_research():
    assert STRUCT_RESEARCH_RE.match("research US inflation outlook") is not None


def test_struct_re_matches_deepresearch():
    assert STRUCT_RESEARCH_RE.match("deepresearch Federal Reserve policy 2026") is not None


def test_struct_re_case_insensitive():
    assert STRUCT_RESEARCH_RE.match("STOCKRESEARCH NVDA") is not None


def test_struct_re_no_match_portfolio():
    assert STRUCT_RESEARCH_RE.match("portfolio") is None


def test_struct_stockresearch_extracts_ticker():
    m = STRUCT_RESEARCH_RE.match("stockresearch NVDA earnings preview")
    assert m is not None
    cmd = m.group(1).lower()
    remainder = (m.group(2) or "").strip()
    parts = remainder.split(None, 1)
    ticker = parts[0].upper() if parts else ""
    question = parts[1].strip() if len(parts) > 1 else ""
    assert cmd == "stockresearch"
    assert ticker == "NVDA"
    assert question == "earnings preview"


def test_struct_stockresearch_ticker_uppercased():
    m = STRUCT_RESEARCH_RE.match("stockresearch nvda")
    assert m is not None
    remainder = (m.group(2) or "").strip()
    parts = remainder.split(None, 1)
    ticker = parts[0].upper() if parts else ""
    assert ticker == "NVDA"
