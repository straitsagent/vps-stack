---
Subject: Hermes nudge taxonomy — category field + deterministic processing procedure (schema v2)
Date: 2026-07-02
Status: done
Planner model: claude-sonnet-5
Executor model: unassigned — plan only, not to be executed without explicit instruction
Risk tier: LOW-MEDIUM (breaking schema change to a not-yet-consumed schema — no live poller exists yet, so version bump is low-blast-radius; still held to Hard Rule 18's rigor since HERMES-PROTOCOL.md §7 already commits to it)
Hard Rules in force: [6, 7, 12, 15, 18, 20, 22]
Complies with: docs/EXECUTOR_CONTRACT.md
Files to read before coding: CLAUDE.md, docs/EXECUTOR_CONTRACT.md, docs/TESTING.md, docs/HERMES-PROTOCOL.md (current §3/§7), shared/python/utils/hermes_nudge.py, agent/tests/test_hermes_nudge.py, docs/plans/2026-07-02_hermes-nudge-inbox.md (the plan this extends)
---

# Plan: Hermes nudge taxonomy — category field + processing procedure

## Context

After the nudge inbox shipped (`docs/plans/2026-07-02_hermes-nudge-inbox.md`), the owner raised a real
gap: a generic "advisory, use your judgment" envelope gives Hermes no playbook. His concrete example —
Windmill publishes new research, a nudge tells Hermes, Hermes reads it and summarizes it back to the
owner over Telegram — needs Hermes to know *in advance* what a nudge of that kind means and what to do
with it, not reinterpret it fresh every time.

The design question this raised (worked through in conversation, not re-litigated here): does a
documented per-category default action reopen INV-6 (Hermes stays analysis-only, no dispatch)? No —
every action a category maps to ("read a file, summarize it, message the owner") is something Hermes
can **already** do inside its existing sandbox. Nothing here grants new capability; it only removes
ambiguity about which existing capability to use and when.

The owner then pushed back hard on "recommended action, Hermes can deviate for any reason" as too
vague — he wants the protocol *followed*, not treated as a suggestion. The resolution: replace
open-ended "judgment" with a **fixed, three-step decision procedure** that is itself part of the
protocol (not a Hermes discretion clause):

1. Does the nudge parse and declare a category documented in `HERMES-PROTOCOL.md`? If not → do not act,
   log/flag, stop.
2. Does its evidence check out (referenced file exists, non-empty, content plausibly matches what the
   category/subject claims)? If not → do not act, file a feedback finding flagging it, stop.
3. Only then: execute that category's mapped default action **exactly as documented** — no
   reinterpretation of the action itself.

This *is* "follow the protocol" — the validation gate is a protocol step, not a discretion clause. It
also directly delivers the anomaly-detection property the owner asked for in the same conversation
("identify what is amiss... ignore what looks strange") — validation failure is a defined outcome, not
freelancing.

**Scope, per explicit owner decision:** this plan is schema + protocol only. It does **not** wire any
Windmill script to actually emit `research-published` nudges — no live consumer (Hermes' polling cron)
is confirmed running yet, so wiring a producer now repeats the exact dead-branch risk the original plan
was written to avoid. A CLI-simulated example proves the schema/procedure; live producer wiring is a
follow-up plan once Hermes' cron is confirmed live.

**Category taxonomy starts at two, not one** — `category` becomes a *required* field (needed for gate 1
of the procedure to mean anything), which means every nudge, including the freeform kind already sent
(e.g. the "channel is live" announcement), needs a value. Two categories close that gap cleanly:
- `general` — no specific playbook; today's existing behavior, now named. Default action: read, use
  judgment, no mandated response. Covers ad hoc Claude Code notices.
- `research-published` — the new, structured one. Producer: any Windmill script that publishes a dated
  research `.md` (not wired in this plan). Default action: read the referenced file, produce a summary,
  send it to the owner via Hermes' own Telegram bot.

## Files changed

| Action | Path | Change |
|--------|------|--------|
| Edit | `shared/python/utils/hermes_nudge.py` | Add required `category` param + validation (slug-format, same pattern as `source` — not a hardcoded enum, so future categories don't need a code change, only a protocol-doc update); bump emitted `schema_version` to `2` |
| Edit | `scripts/nudge-hermes.py` | Add required `--category` CLI flag |
| Edit | `docs/HERMES-PROTOCOL.md` | §3 restructured: schema table gets `category`; new "Known categories" table (`general`, `research-published`); new "Processing procedure" subsection (the 3-step gate, verbatim from Context above); §7 changelog entry for the v1→v2 bump |
| Edit | `agent/tests/test_hermes_nudge.py` | All existing `write_nudge()` calls updated to pass `category`; new tests for category validation (required, slug format), schema_version bump, category present in front-matter round-trip |
| Cleanup | `docs/hermes/inbox/` | The one live v1-schema nudge (`2026-07-02T031912Z_claude-code_inbound-nudge-channel-is-live.md`, no `category` field) is superseded — move it to `processed/` and write a fresh v2 nudge (`category: general`) announcing the taxonomy itself, so the live inbox only ever contains v2+ nudges once this ships |

No Windmill script, no compose/container change, no schema change to the outbound feedback channel.

## Design

### Updated nudge schema (v2)

```yaml
---
schema_version: 2
nudge_id: "2026-07-02T120000Z-claude-code-nudge-taxonomy-shipped"
source: "claude-code"
category: "general"          # NEW, required — must match a category documented in HERMES-PROTOCOL.md §3
created_at: "2026-07-02T12:00:00Z"
urgency: "soon"
expires_at: null
advisory: true
evidence:
  - type: "plan"
    ref: "docs/plans/2026-07-02_hermes-nudge-taxonomy.md"
subject: "Nudge taxonomy shipped"
---
```

`category` validation mirrors `source`'s existing regex (`^[a-z0-9][a-z0-9\-_.]{0,49}$`) — a slug, not
a hardcoded Python enum. This is a deliberate choice: adding a *new* category later is a documentation
change (extend the "Known categories" table in `HERMES-PROTOCOL.md`) plus, per §7's own rule, a code
version bump only if the *schema shape* changes — not every time a new category value is introduced.
Hermes' own gate-1 check ("is this category documented?") is what actually enforces the taxonomy at
read time; `hermes_nudge.py` only enforces "is this a well-formed slug," matching how `source` already
works.

### `HERMES-PROTOCOL.md` — new "Known categories" table (§3 addition)

| Category | Producer | Meaning | Evidence expectation | Default action |
|---|---|---|---|---|
| `general` | any | No specific playbook — informational, same as today's behavior | none required | Read; use your own judgment; no mandated response |
| `research-published` | a Windmill research script (not wired yet — see Future work) | New research artifact written to `/research/**` | `evidence` must include one `{type: "research-md", ref: <path under /research/>}` entry pointing at an existing, non-empty file | Read the referenced file; produce a summary; send it to the owner via your Telegram bot |

### `HERMES-PROTOCOL.md` — new "Processing procedure" subsection (§3 addition)

Verbatim three-step gate from Context above, framed explicitly as "this is the protocol, not a
suggestion — the validation step is part of following it, not a deviation from it." Ties directly to
existing §5 (prompt-injection/trust boundary): a category/evidence mismatch is exactly the kind of thing
§5 already asks Hermes to treat with suspicion.

### Test additions (`agent/tests/test_hermes_nudge.py`)

- `test_validation_missing_category` — `write_nudge()` without `category` raises `ValueError`
- `test_validation_bad_category_chars` — non-slug category raises `ValueError`
- `test_schema_roundtrip_category_present` — written file's front-matter has `category` matching input
- `test_schema_roundtrip_version_is_2` — `schema_version: 2` in every written nudge
- All pre-existing `write_nudge(...)` calls across the file gain `category="general"` (or
  `category="research-published"` where a test is specifically about that category) — this is a
  mechanical update, not new test logic; every previously-covered property (atomic write, permissions,
  naming, CLI) keeps its existing assertion, now exercised with the v2 call signature

## Checklist

- [ ] Add `category` param + slug validation to `write_nudge()`; bump emitted `schema_version` to `2`
- [ ] Add required `--category` flag to `scripts/nudge-hermes.py`
- [ ] Update `docs/HERMES-PROTOCOL.md`: schema table, "Known categories" table, "Processing procedure"
  subsection, §7 changelog entry
- [ ] Update `agent/tests/test_hermes_nudge.py`: mechanical `category=` additions to existing calls, plus
  the 4 new tests listed above
- [ ] Move the one live v1 nudge to `processed/`; write one fresh v2 `category: general` nudge announcing
  the taxonomy shipped
- [ ] Confirm no Windmill script was touched (scope boundary — Windmill wiring stays a follow-up)

## Locked Oracle Tests (G1)

```python
# LOCKED ORACLE — copy verbatim, do not modify assertions
import subprocess, os

def run(c):
    r = subprocess.run(c, shell=True, capture_output=True, text=True, cwd="/root", executable="/bin/bash")
    return r.returncode, r.stdout + r.stderr

# O1 — category is required
rc, o = run("python3 -m pytest agent/tests/test_hermes_nudge.py -q -k missing_category 2>&1 | tail -5")
assert rc == 0, f"O1 FAIL: {o}"
print("O1 PASS")

# O2 — category validated as slug (same family as source)
rc, o = run("python3 -m pytest agent/tests/test_hermes_nudge.py -q -k bad_category 2>&1 | tail -5")
assert rc == 0, f"O2 FAIL: {o}"
print("O2 PASS")

# O3 — schema_version bumped to 2, category present in round-trip
rc, o = run("python3 -m pytest agent/tests/test_hermes_nudge.py -q -k 'roundtrip_category or version_is_2' 2>&1 | tail -5")
assert rc == 0, f"O3 FAIL: {o}"
print("O3 PASS")

# O4 — protocol doc has the new sections
rc, o = run("cat docs/HERMES-PROTOCOL.md")
assert rc == 0, "O4 FAIL: HERMES-PROTOCOL.md missing"
for marker in ["Known categories", "research-published", "Processing procedure", "schema_version: 2"]:
    assert marker in o, f"O4 FAIL: missing '{marker}'"
print("O4 PASS")

# O5 — full nudge test suite green (no regression on pre-existing properties)
rc, o = run("python3 -m pytest agent/tests/test_hermes_nudge.py -q 2>&1 | tail -5")
assert rc == 0, f"O5 FAIL: {o}"
print("O5 PASS")

# O6 — real live CLI run with --category lands a v2 nudge
rc, o = run('python3 scripts/nudge-hermes.py --source claude-code --subject "oracle taxonomy check" --category general --urgency whenever --body-file <(echo "check")')
assert rc == 0, f"O6 FAIL: {o}"
path = o.strip().splitlines()[-1]
assert os.path.isfile(path), f"O6 FAIL: {path} does not exist"
content = open(path).read()
assert 'schema_version: 2' in content and 'category: "general"' in content, f"O6 FAIL: wrong schema in {path}"
print("O6 PASS")

print("\nLOCKED ORACLE: PASS")
```

## RED-proof requirement (G2)

Before implementing, `category` does not exist as a parameter — paste:
```bash
python3 -c "import sys; sys.path.insert(0,'/root/shared/python/utils'); from hermes_nudge import write_nudge; write_nudge(source='x', subject='y', body='z', category='general')"
```
failing with `TypeError: write_nudge() got an unexpected keyword argument 'category'`, then the same
call succeeding after implementation.

## Asserting Verification Script (G4)

```bash
cd /root
fail=0
chk(){ [ "$1" -eq 0 ] && echo "PASS: $2" || { echo "FAIL: $2"; fail=1; }; }

OUTPUT=$(python3 scripts/nudge-hermes.py --source claude-code --subject "taxonomy shipped" --category general --urgency soon --body-file <(echo "v2 verify body"))
echo "--- CLI output ---"; echo "$OUTPUT"; echo "------------------"
PATH_OUT=$(echo "$OUTPUT" | tail -1)
[ -f "$PATH_OUT" ]; chk $? "v2 nudge file exists"

grep -q 'schema_version: 2' "$PATH_OUT" && grep -q 'category: "general"' "$PATH_OUT"
chk $? "schema_version and category correct in written file"

grep -q "Known categories" docs/HERMES-PROTOCOL.md && grep -q "research-published" docs/HERMES-PROTOCOL.md && grep -q "Processing procedure" docs/HERMES-PROTOCOL.md
chk $? "protocol doc has new sections"

python3 -m pytest agent/tests/test_hermes_nudge.py -q 2>&1 | tail -5
chk ${PIPESTATUS[0]:-$?} "full nudge test file green"

docker exec root-straitsagent-1 python -m pytest tests/ -q 2>&1 | tail -5
chk ${PIPESTATUS[0]:-$?} "full agent suite green (via container, per this repo's DB-test convention)"

[ $fail -eq 0 ] && echo "PASS" || exit 1
```

## Acceptance Gate

- [ ] `category` is a required parameter; missing or malformed input raises `ValueError` (fail loud)
- [ ] `schema_version` is `2` in every nudge written after this ships
- [ ] `docs/HERMES-PROTOCOL.md` documents both categories, the processing procedure, and the v1→v2
  changelog entry
- [ ] The processing procedure is framed as *part of* the protocol, not a discretion clause — no
  language implying Hermes may skip the validation gate or reinterpret a category's default action
- [ ] The one live v1 nudge is moved to `processed/`; the live inbox contains only v2+ content after
  this ships
- [ ] No Windmill script modified — scope boundary held (schema/protocol only, per explicit owner
  decision; producer wiring is a named follow-up, not built here)
- [ ] LOCKED ORACLE O1–O6 pass verbatim; RED→GREEN pasted; G4 ends in `PASS`

## Execution

**Do not execute this plan without an explicit instruction to do so.** Per standing direction: my job
on this repo is planning unless told otherwise. On explicit "go"/"execute"/"implement this":
1. Set `Status: executing`, commit.
2. Work the checklist top to bottom.
3. Paste RED run, then GREEN run. Run the LOCKED ORACLE verbatim + G4 (ends `PASS`).
4. Write the implementation log (Hard Rule 23).
5. Set `Status: done`, commit, push.
Do not wire any Windmill script — out of scope by explicit owner decision. Do not redesign; if
ambiguous, stop and report.
