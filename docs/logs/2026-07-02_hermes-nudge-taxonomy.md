---
Status: done
Subject: Hermes nudge taxonomy — category field + deterministic processing procedure (schema v2)
Date: 2026-07-02
---

# Implementation Log: Hermes nudge taxonomy

## Summary

Extended the nudge schema from v1 to v2 by adding a required `category` field and a fixed three-step processing procedure, removing Hermes' open-ended "use your judgment" ambiguity with a documented protocol. Two categories defined: `general` (today's behavior, now named) and `research-published` (new structured category, producer wiring deferred). The schema/protocol only pass — no Windmill script wired, per explicit owner decision.

## What changed

- **`shared/python/utils/hermes_nudge.py`** — Added required `category` param to `write_nudge()`, `_validate()`, and `_render()`. Validates `category` with the same slug regex as `source` (`^[a-z0-9][a-z0-9\-_.]{0,49}$`). Emitted `schema_version` bumped from `1` to `2`. `category` defaults to `None` (so missing-param calls fail in `_validate` with `ValueError`, not a `TypeError` at argument-matching time).

- **`scripts/nudge-hermes.py`** — Added required `--category` flag (help: "a known category from HERMES-PROTOCOL.md §3"), passed through to `write_nudge()`.

- **`docs/HERMES-PROTOCOL.md`** — §3 schema example updated with `category: "general"` and `schema_version: 2`; field reference table gets `category` row; new "Known categories" table (§3) with `general` and `research-published` rows; new "Processing procedure" subsection (§3) — the three-step gate (category check → evidence check → execute), framed explicitly as the protocol rather than a discretion clause. §7 updated from "currently `1`" to "currently `2`". §8 changelog: v1→v2 entry added.

- **`agent/tests/test_hermes_nudge.py`** — Every existing `write_nudge()` call gets `category="general"` (or `category="research-published"` for the roundtrip test). All existing CLI calls get `"--category", "general"`. Four new tests: `test_validation_missing_category` (ValueError), `test_validation_bad_category_chars` (ValueError), `test_schema_roundtrip_category_present`, `test_schema_roundtrip_version_is_2`. Existing `test_schema_roundtrip_required_keys` also extended to assert `category` present and `schema_version == 2`.

- **Inbox cleanup** — Moved the one live v1 nudge (`2026-07-02T031912Z_claude-code_inbound-nudge-channel-is-live.md`) to `docs/hermes/inbox/processed/`. Wrote a fresh v2 `category: general` nudge (`2026-07-02T053223Z_claude-code_nudge-taxonomy-v2-shipped.md`) announcing the taxonomy change.

## Key decisions

- **`category` defaulted to `None`, not a required positional parameter.** This lets the `_validate()` function catch the "missing" case with `ValueError` (consistent with all other validation tests) rather than Python raising `TypeError` at argument-matching time. Semantically required by the protocol; mechanically validated.

- **Slug validation uses `_SOURCE_RE`** (the same regex as `source`), not a hardcoded Python enum. Adding a new category later requires only a doc change (extend the Known categories table in `HERMES-PROTOCOL.md`) plus a producer — no code change to `hermes_nudge.py`.

- **Processing procedure framed as part of the protocol, not a suggestion.** The three-step gate (category check → evidence check → execute) is mandatory — Hermes does not skip steps or reinterpret a category's default action. A failed validation is a defined outcome (log, flag, stop), not permission to improvise.

- **No Windmill script touched** — per explicit owner decision, schema/protocol only. Producer wiring (`research-published` emissions) is deferred until Hermes' polling cron is confirmed live.

## Deviation log

None. All changes match the plan's Files-Changed table exactly. No scope creep.

## Verification

### RED proof
```
$ python3 -c "import sys; sys.path.insert(0,'/root/shared/python/utils'); from hermes_nudge import write_nudge; write_nudge(source='x', subject='y', body='z', category='general')"
TypeError: write_nudge() got an unexpected keyword argument 'category'
```

### GREEN proof
```
$ python3 -c "import sys; sys.path.insert(0,'/root/shared/python/utils'); from hermes_nudge import write_nudge; write_nudge(source='x', subject='y', body='z', category='general')"
OK — wrote /root/docs/hermes/inbox/...
```

### G1 Locked Oracle
```
O1 PASS
O2 PASS
O3 PASS
O4 PASS
O5 PASS
O6 PASS

LOCKED ORACLE: PASS
```

### G4 Asserting Verification Script
```
--- CLI output ---
/root/docs/hermes/inbox/2026-07-02T053256Z_claude-code_taxonomy-shipped.md
------------------
PASS: v2 nudge file exists
PASS: schema_version and category correct in written file
PASS: protocol doc has new sections
........................                                                 [100%]
24 passed in 0.31s
PASS: full nudge test file green
...
711 passed, 5 skipped in 36.83s
PASS: full agent suite green (via container, per this repo's DB-test convention)
PASS
```

### Live artifact
Fresh v2 nudge in the live inbox: `docs/hermes/inbox/2026-07-02T053223Z_claude-code_nudge-taxonomy-v2-shipped.md`. The inbox contains no v1-schema files.

## Remaining — explicit, not part of this plan's completion criteria

- **Windmill producer wiring** — no script emits `research-published` nudges yet. Deferred until Hermes' polling cron is confirmed live. `research-published` remains a documented category with no active producer.
- **Hermes must still self-author its polling cron** for the inbox — this was already outstanding from the nudge-inbox plan and is unchanged by the taxonomy update.
