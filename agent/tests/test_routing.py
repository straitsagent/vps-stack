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


# ── Telegram command menu (source-inspection) ────────────────────────────────
# Parse main.py source to extract and validate the TELEGRAM_COMMANDS list.
# Source-inspection avoids pulling in FastAPI which isn't installed on the host.

import ast
import os as _os

_MAIN_PY = _os.path.join(_os.path.dirname(__file__), "../main.py")


def _parse_telegram_commands() -> list[dict]:
    """Extract the TELEGRAM_COMMANDS list literal from main.py via AST parsing."""
    with open(_MAIN_PY) as f:
        src = f.read()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "TELEGRAM_COMMANDS":
                    return ast.literal_eval(node.value)
    raise AssertionError("TELEGRAM_COMMANDS not found as a module-level constant in main.py")


def test_command_list_is_alphabetical():
    """Command names must be in alphabetical order for discoverability."""
    commands = _parse_telegram_commands()
    names = [c["command"] for c in commands]
    assert names == sorted(names), \
        f"Commands not in alphabetical order. Got: {names}"


def test_digest_command_removed():
    """'digest' was a duplicate of 'news' and must be removed from the menu."""
    commands = _parse_telegram_commands()
    names = [c["command"] for c in commands]
    assert "digest" not in names, \
        "'digest' command still in menu — it duplicates /news"


def test_command_count_within_telegram_limits():
    """Telegram allows up to 100 commands."""
    commands = _parse_telegram_commands()
    assert len(commands) <= 100, \
        f"Too many commands: {len(commands)} (Telegram limit is 100)"


def test_all_command_names_within_32_chars():
    """Telegram limits command names to 32 characters."""
    for c in _parse_telegram_commands():
        assert len(c["command"]) <= 32, \
            f"Command name too long ({len(c['command'])} chars): {c['command']!r}"


def test_all_command_descriptions_within_256_chars():
    """Telegram limits command descriptions to 256 characters."""
    for c in _parse_telegram_commands():
        assert len(c["description"]) <= 256, \
            f"Description too long ({len(c['description'])} chars) for /{c['command']}"


def test_analyze_command_in_menu():
    """'/analyze' must be in the command menu."""
    names = [c["command"] for c in _parse_telegram_commands()]
    assert "analyze" in names, "'/analyze' command missing from menu"


def test_rationalize_command_in_menu():
    """'/rationalize' must be in the command menu."""
    names = [c["command"] for c in _parse_telegram_commands()]
    assert "rationalize" in names, "'/rationalize' command missing from menu"


def test_candidate_command_in_menu():
    """'/candidate' must be in the command menu."""
    names = [c["command"] for c in _parse_telegram_commands()]
    assert "candidate" in names, "'/candidate' command missing from menu"


# ── STRUCT_CANDIDATE_RE fast-path regex ──────────────────────────────────────

STRUCT_CANDIDATE_RE = re.compile(
    r"^candidate\s+(\S+)(.*)?$",
    re.IGNORECASE | re.DOTALL,
)


def test_struct_candidate_re_extracts_ticker():
    m = STRUCT_CANDIDATE_RE.match("candidate NVDA")
    assert m is not None
    assert m.group(1).upper() == "NVDA"


def test_struct_candidate_re_extracts_ticker_with_thesis():
    m = STRUCT_CANDIDATE_RE.match("candidate AAPL growth story in AI")
    assert m is not None
    assert m.group(1).upper() == "AAPL"
    assert "growth story" in (m.group(2) or "")


def test_struct_candidate_re_case_insensitive():
    assert STRUCT_CANDIDATE_RE.match("CANDIDATE nvda") is not None


def test_struct_candidate_re_no_match_bare_candidate():
    """Bare 'candidate' without a ticker must not match (falls through to classifier)."""
    assert STRUCT_CANDIDATE_RE.match("candidate") is None


def test_macro_brief_calls_run_macro_brief():
    """main.py must call pl.run_macro_brief for macro_brief intent (not the generic step-loop)."""
    import pathlib
    main_path = pathlib.Path(__file__).parent.parent / "main.py"
    src = main_path.read_text()
    assert "run_macro_brief" in src, \
        "main.py must call pl.run_macro_brief for macro_brief — the step-loop cannot handle 5 parallel news searches"
