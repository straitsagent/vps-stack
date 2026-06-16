#!/usr/bin/env python3
"""SessionStart hook: git check.

If uncommitted/unpushed work exists from a prior session, instructs Claude
to update docs, commit, and push before responding to the user.
Session briefing is handled automatically via the claude() shell wrapper.
"""

import subprocess
import json
import sys

REPO = "/root"


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def main():
    lines = []

    # --- Git check ---
    status = run(["git", "-C", REPO, "status", "--porcelain"])
    modified = [
        line[3:].strip()
        for line in status.stdout.splitlines()       # no strip() — preserves leading space on first line
        if len(line) >= 3 and not line.startswith("??")
    ]

    log = run(["git", "-C", REPO, "log", "origin/main..HEAD", "--oneline"])
    unpushed = [l for l in log.stdout.splitlines() if l.strip()]

    if modified or unpushed:
        lines.append("[session-git-check] Outstanding git work from a previous session.")
        lines.append("")
        lines.append(
            "INSTRUCTION (do this first, before responding to the user): "
            "Read the git diff of modified files, update CLAUDE.md and ROADMAP.md "
            "to reflect work done in the previous session, then commit and push to git."
        )
        lines.append("")
        if modified:
            lines.append("Uncommitted changes to tracked files:")
            for f in modified:
                lines.append(f"  {f}")
        if unpushed:
            lines.append("")
            lines.append("Unpushed commits:")
            for c in unpushed:
                lines.append(f"  {c}")
        lines.append("")
        lines.append(
            "Steps: (1) git diff modified files, (2) update docs, "
            "(3) git add + commit + push, (4) then proceed to the briefing below."
        )
        lines.append("")
        lines.append("---")
        lines.append("")

    if not lines:
        sys.exit(0)

    print(json.dumps({"systemMessage": "\n".join(lines)}))
    sys.exit(0)


if __name__ == "__main__":
    main()
