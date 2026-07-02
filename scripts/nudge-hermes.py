#!/usr/bin/env python3
"""CLI wrapper for writing an advisory nudge into Hermes' inbox.

See /root/docs/HERMES-PROTOCOL.md for the full contract. Prints the written
path on success (exit 0); prints the error to stderr and exits 1 on any
validation failure.

Usage:
  python3 scripts/nudge-hermes.py \
    --source claude-code --subject "..." --urgency soon \
    --body-file /tmp/nudge-body.md \
    --evidence plan=docs/plans/2026-07-02_hermes-nudge-inbox.md
"""

import argparse
import sys

sys.path.insert(0, "/root/shared/python/utils")

from hermes_nudge import URGENCY_LEVELS, write_nudge  # noqa: E402


def _parse_evidence(pairs):
    evidence = []
    for pair in pairs or []:
        if "=" not in pair:
            raise ValueError(f"--evidence must be TYPE=REF, got {pair!r}")
        etype, ref = pair.split("=", 1)
        evidence.append({"type": etype, "ref": ref})
    return evidence or None


def main():
    parser = argparse.ArgumentParser(description="Write an advisory nudge to Hermes' inbox")
    parser.add_argument("--source", required=True)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--urgency", default="whenever", choices=URGENCY_LEVELS)
    parser.add_argument("--body-file", required=True, help="path to a file containing the nudge body")
    parser.add_argument("--evidence", action="append", default=[], help="TYPE=REF, repeatable")
    parser.add_argument("--expires-at", default=None)
    parser.add_argument("--inbox-dir", default=None)
    args = parser.parse_args()

    try:
        with open(args.body_file) as f:
            body = f.read()
        evidence = _parse_evidence(args.evidence)
        kwargs = {}
        if args.inbox_dir:
            kwargs["inbox_dir"] = args.inbox_dir
        path = write_nudge(
            source=args.source,
            subject=args.subject,
            body=body,
            urgency=args.urgency,
            evidence=evidence,
            expires_at=args.expires_at,
            **kwargs,
        )
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)

    print(path)
    sys.exit(0)


if __name__ == "__main__":
    main()
