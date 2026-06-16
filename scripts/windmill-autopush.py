#!/usr/bin/env python3
"""PostToolUse hook: auto-push Windmill scripts and enforce TDD on all Python edits.

Fires after every tool call. Two responsibilities:
  1. Windmill autopush — for .py files under windmill/u/admin/: syntax check,
     resource preflight, then wmill script push.
  2. TDD reminder — for ANY .py file under windmill/ or agent/: print a mandatory
     TDD checklist so it's impossible to forget tests after implementation.

Pre-push checks:
  1. Syntax validation — will not deploy broken code
  2. Resource/variable preflight — warns if any $res: or $var: references
     are missing from Windmill (does not block push, just warns)

Always exits 0 so it never blocks Claude Code.
"""

import sys
import json
import os
import re
import subprocess


def _load_dotenv(path="/root/.env"):
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()

WINDMILL_ROOT = "/root/windmill"
WATCHED_PREFIX = "/root/windmill/u/admin/"
AGENT_PREFIX = "/root/agent/"
WM_BASE = os.environ.get("WINDMILL_BASE_URL", "http://localhost:8080")
WM_WORKSPACE = "admins"
WM_TOKEN = os.environ.get("WINDMILL_TOKEN", "")

TDD_REMINDER = """
⚠️  TDD REQUIRED — do not mark this work complete until BOTH are done:
  1. Tests written + passing:
     docker exec root-straitsagent-1 python -m pytest tests/ -v
  2. Live end-to-end test run + ALL output fields verified (not just "no error")
"""


def check_windmill_refs(file_path):
    """Scan file for $res: and $var: references, return warnings for missing ones."""
    try:
        content = open(file_path).read()
    except Exception:
        return []

    res_refs = set(re.findall(r'\$res:(u/admin/[^\s\'"\\,}]+)', content))
    var_refs = set(re.findall(r'\$var:(u/admin/[^\s\'"\\,}]+)', content))

    if not res_refs and not var_refs:
        return []

    warnings = []

    for ref in sorted(res_refs):
        r = subprocess.run(
            ["curl", "-sf", "-o", "/dev/null",
             f"{WM_BASE}/api/w/{WM_WORKSPACE}/resources/get/{ref}",
             "-H", f"Authorization: Bearer {WM_TOKEN}"],
            capture_output=True
        )
        if r.returncode != 0:
            warnings.append(f"⚠️  Missing Windmill resource: $res:{ref}")

    for ref in sorted(var_refs):
        r = subprocess.run(
            ["curl", "-sf", "-o", "/dev/null",
             f"{WM_BASE}/api/w/{WM_WORKSPACE}/variables/get/{ref}",
             "-H", f"Authorization: Bearer {WM_TOKEN}"],
            capture_output=True
        )
        if r.returncode != 0:
            warnings.append(f"⚠️  Missing Windmill variable: $var:{ref}")

    return warnings


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    tool_name = data.get("tool_name", "")
    if tool_name not in ("Write", "Edit", "MultiEdit"):
        sys.exit(0)

    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    is_windmill = file_path.startswith(WATCHED_PREFIX) and file_path.endswith(".py")
    is_agent = file_path.startswith(AGENT_PREFIX) and file_path.endswith(".py")

    if not (is_windmill or is_agent):
        sys.exit(0)

    # Agent-only path: just print the TDD reminder, no push needed
    if is_agent and not is_windmill:
        print(json.dumps({"systemMessage": f"[agent code edited]{TDD_REMINDER}"}))
        sys.exit(0)

    rel_path = file_path[len(WINDMILL_ROOT):].lstrip("/")

    # 1. Syntax check
    check = subprocess.run(
        ["python3", "-m", "py_compile", file_path],
        capture_output=True,
        text=True
    )
    if check.returncode != 0:
        msg = {"systemMessage": f"[autopush] Syntax error in {rel_path} — skipping Windmill push.\n{check.stderr}"}
        print(json.dumps(msg))
        sys.exit(0)

    # 2. Resource/variable preflight
    ref_warnings = check_windmill_refs(file_path)

    # 3. Push
    result = subprocess.run(
        ["wmill", "script", "push", rel_path],
        capture_output=True,
        text=True,
        cwd=WINDMILL_ROOT
    )

    if result.returncode == 0:
        lines = [f"[autopush] Pushed {rel_path} to Windmill."]
    else:
        lines = [f"[autopush] Push failed for {rel_path}:\n{result.stderr}"]

    if ref_warnings:
        lines.append("")
        lines.append("[autopush] Resource preflight warnings:")
        lines.extend(ref_warnings)
        lines.append("Create missing resources/variables before running this script.")

    lines.append(TDD_REMINDER)
    print(json.dumps({"systemMessage": "\n".join(lines)}))
    sys.exit(0)


if __name__ == "__main__":
    main()
