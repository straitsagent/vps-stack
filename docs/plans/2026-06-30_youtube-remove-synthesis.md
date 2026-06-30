---
Subject: Remove the daily synthesis commentary from youtube_monitor (email + .md); keep per-video summaries
Date: 2026-06-30
Status: executing
Planner model: claude-opus-4-8
Risk tier: MEDIUM (modifies one working delivery workflow + its formatter + tests; .md body contract change)
Hard Rules in force: [7, 12, 15, 16, 17, 18, 20, 22]
Complies with: docs/EXECUTOR_CONTRACT.md
Files to read before coding: CLAUDE.md, docs/EXECUTOR_CONTRACT.md, docs/TESTING.md, windmill/u/admin/youtube_monitor.py, windmill/u/admin/youtube_monitor_telegram.py, agent/tests/test_windmill_scripts.py
---

# Plan: Remove YouTube Daily Synthesis Commentary

## Context

The YouTube monitor email (daily 18:00 SGT, email-only since the 2026-06-29 rationalise plan) is too verbose.
It currently leads with a **"Daily Synthesis"** block — a ≥500-word LLM narrative produced by
`_synthesise_24h()` (Deepseek) over the last 24h of videos — followed by the per-video summaries. The owner
wants the synthesis commentary **removed from both the email and the `.md`**, keeping the **individual video
summaries**.

This mirrors the 2026-06-30 health-check revert (remove the LLM synthesis layer, keep the deterministic
content). The per-video summaries (`detail_block`) are the artifact to retain.

## Scope decisions (locked)

- **Email KEPT**, but synthesis block removed; it now renders only the per-video summaries.
- **`.md` KEPT**, synthesis narrative removed; body becomes the per-video summaries (`detail_block`).
- **Per-video summary generation KEPT** (`_summarise_video` / per-video Deepseek calls) — only the 24h
  *aggregate synthesis* is removed.
- **`deepseek_key` KEPT** — still used for per-video summaries and the idea_extractor dispatch.
- **`youtube_monitor_telegram.py` RETAINED on disk** (dispatch already retired); updated to the new `.md`
  shape for round-trip parity (Hard Rule 18).
- Front-matter is unchanged (`date_str`, `n_summarised`, `videos`) — no synthesis key exists there, so the
  front-matter schema itself does not change; only the `.md` body does.

## Files changed

| Action | Path | Change |
|--------|------|--------|
| Edit | `windmill/u/admin/youtube_monitor.py` | Delete `_SYNTHESIS_PROMPT`, `_collect_24h_videos`, `_synthesise_24h`; remove the synthesis collect/call block in `main()`; rebuild `.md` body from `detail_block` only; drop `synthesis` param + Daily Synthesis block from `build_email_html`; update the email-send call |
| Edit | `windmill/u/admin/youtube_monitor_telegram.py` | Adapt `_parse_md_report`/`_build_message` to the new `.md` (no synthesis narrative); render/tolerate per-video body; round-trip parity (HR 18) |
| Edit | `agent/tests/test_windmill_scripts.py` | Invert/remove synthesis tests; update the youtube artifact harness to assert per-video summaries present + NO "Daily Synthesis" |
| Edit | `docs/WORKFLOW_ARCHITECTURE.md` | YouTube spec: remove DAILY SYNTHESIS block from output; email = per-video summaries only |
| Edit | `docs/ROADMAP.md` | YouTube row: note synthesis commentary removed (per-video summaries only) |

## New `.md` structure

Before: `front-matter` + `{synthesis narrative}` + `<!-- DETAIL -->` + `{per-video summaries}`
After:  `front-matter` + `<!-- DETAIL -->` + `{per-video summaries}`  (synthesis region removed; keep the
`<!-- DETAIL -->` marker for structural consistency with the other canonical `.md` files, with no narrative
above it).

## Tests affected (RED→GREEN)

Existing tests that assert the synthesis (must be inverted/removed):
- `test_youtube_email_renders_synthesis` (asserts `"Daily Synthesis" in html`) → invert to assert it is ABSENT and per-video summaries are present.
- `test_youtube_formatter_uses_synthesis_narrative` → remove/replace (no synthesis narrative any more).
- `test_youtube_monitor_collect_24h_fn_exists` → remove (function deleted).
- `test_youtube_monitor_synthesise_24h_fn_exists` → remove (function deleted).
- `_render_youtube_monitor_artifacts` + `test_youtube_monitor_email_and_telegram_agree` / `_telegram_min_word_count` / `_md_content_valid` → update to the new structure: assert each per-video title + summary appears in `email_html` and `.md`; drop synthesis-based word-count expectations.

## Checklist

### Part 1 — youtube_monitor.py
- [ ] **Y1.1** Delete `_SYNTHESIS_PROMPT`, `_collect_24h_videos`, `_synthesise_24h`.
- [ ] **Y1.2** Remove the synthesis collect/synthesise/fallback block in `main()`; delete the `synthesis` local.
- [ ] **Y1.3** Rebuild `.md` content: `front-matter` + `<!-- DETAIL -->` + `detail_block` (per-video summaries); no synthesis.
- [ ] **Y1.4** `build_email_html`: drop the `synthesis` parameter and the Daily Synthesis block; keep the per-video list.
- [ ] **Y1.5** Update the `build_email_html(...)` call site to the new signature.
- [ ] **Y1.6** KEEP `deepseek_key` (per-video summaries + idea_extractor). `py_compile` passes; autopush deploys clean.

### Part 2 — formatter
- [ ] **Y2.1** `youtube_monitor_telegram.py`: adapt to the new `.md` (empty synthesis region); render the per-video body or tolerate gracefully; no crash. Round-trip parity with the new schema (HR 18).

### Part 3 — tests (RED→GREEN)
- [ ] **Y3.1** Invert `test_youtube_email_renders_synthesis` → `test_youtube_email_omits_synthesis`: assert `"Daily Synthesis" not in html` AND at least one per-video title/summary present.
- [ ] **Y3.2** Remove `test_youtube_formatter_uses_synthesis_narrative`, `test_youtube_monitor_collect_24h_fn_exists`, `test_youtube_monitor_synthesise_24h_fn_exists`.
- [ ] **Y3.3** Update `_render_youtube_monitor_artifacts` + agree/min-word/md-valid tests: assert per-video summaries appear in email + `.md`; remove synthesis assumptions.
- [ ] **Y3.4** Full suite passes. Paste tail with count.

### Part 4 — live verify (Hard Rule 17)
- [ ] **Y4.1** Trigger one live youtube_monitor run: (a) email arrives with per-video summaries and NO "Daily Synthesis" block; (b) `/research/youtube/<latest>.md` has front-matter + per-video summaries, no synthesis narrative; (c) per-video titles/links intact.

### Part 5 — docs
- [ ] **Y5.1** WORKFLOW_ARCHITECTURE YouTube spec updated (no DAILY SYNTHESIS).
- [ ] **Y5.2** ROADMAP YouTube row updated.

## Locked Oracle Tests (G1)

```python
# LOCKED ORACLE — copy verbatim, do not modify assertions.
import subprocess, re

def run(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd="/root")
    return r.returncode, r.stdout + r.stderr

YM = "windmill/u/admin/youtube_monitor.py"

# O1: the 24h synthesis machinery is gone
for fn in ("_synthesise_24h", "_collect_24h_videos", "_SYNTHESIS_PROMPT"):
    rc, _ = run(f"grep -q '{fn}' {YM}")
    assert rc != 0, f"O1 FAIL — {fn} still present in youtube_monitor.py"
print("O1 PASS — synthesis machinery removed")

# O2: build_email_html no longer takes a synthesis arg
rc, out = run(f"grep -n 'def build_email_html' {YM}")
assert 'synthesis' not in out, f"O2 FAIL — build_email_html still takes synthesis: {out}"
print("O2 PASS — email builder drops synthesis param")

# O3: deepseek_key retained (per-video summaries still need it)
rc, _ = run(f"grep -q 'deepseek_key' {YM}")
assert rc == 0, "O3 FAIL — deepseek_key wrongly removed"
print("O3 PASS — deepseek_key retained")

# O4: the rendered email omits the Daily Synthesis header but keeps per-video summaries
rc, out = run("cd /root/agent && python3 -m pytest tests/test_windmill_scripts.py -k youtube -q 2>&1 | tail -5")
assert rc == 0, f"O4 FAIL — youtube tests failed:\n{out}"
print("O4 PASS — youtube tests green")

# O5: the synthesis-fn-exists tests are gone and an omits-synthesis test exists
rc1, _ = run("grep -q 'test_youtube_monitor_synthesise_24h_fn_exists' /root/agent/tests/test_windmill_scripts.py")
rc2, _ = run("grep -q 'test_youtube_monitor_collect_24h_fn_exists' /root/agent/tests/test_windmill_scripts.py")
assert rc1 != 0 and rc2 != 0, "O5 FAIL — synthesis-fn-exists tests still present"
rc3, _ = run("grep -qE 'omits_synthesis|not in html.*Daily Synthesis|Daily Synthesis.*not in' /root/agent/tests/test_windmill_scripts.py")
assert rc3 == 0, "O5 FAIL — no test asserts synthesis is omitted"
print("O5 PASS — synthesis tests inverted")

# O6: full suite passes
rc, out = run("cd /root/agent && python3 -m pytest tests/test_windmill_scripts.py -q 2>&1 | tail -3")
assert rc == 0, f"O6 FAIL — suite failed:\n{out}"
print("O6 PASS — full suite green")

print("\nLOCKED ORACLE: PASS")
```

## RED-proof requirement (G2)

Before Part 1: confirm O1 FAILs (synthesis fns present) and `test_youtube_email_renders_synthesis` passes
(asserts the OLD "Daily Synthesis" behaviour). Paste RED. After edits, paste GREEN (oracle PASS).

## Asserting Verification Script (G4)

```bash
#!/bin/bash
fail=0
cd /root
YM=windmill/u/admin/youtube_monitor.py
for fn in _synthesise_24h _collect_24h_videos _SYNTHESIS_PROMPT; do
  grep -q "$fn" $YM && { echo "FAIL: $fn present"; fail=1; } || echo "PASS: $fn removed"
done
grep -n 'def build_email_html' $YM | grep -q synthesis && { echo "FAIL: email builder keeps synthesis"; fail=1; } || echo "PASS: email builder clean"
grep -q deepseek_key $YM && echo "PASS: deepseek_key retained" || { echo "FAIL: deepseek_key removed"; fail=1; }
( cd agent && python3 -m pytest tests/test_windmill_scripts.py -q 2>&1 | tail -3 )
[ ${PIPESTATUS[0]} -eq 0 ] && echo "PASS: suite green" || { echo "FAIL: suite"; fail=1; }
[ $fail -eq 0 ] && echo "PASS" || exit 1
```

## Acceptance Gate

- [ ] `_synthesise_24h` / `_collect_24h_videos` / `_SYNTHESIS_PROMPT` removed
- [ ] `build_email_html` no longer takes/render synthesis; per-video list intact
- [ ] `.md` body = per-video summaries only; no synthesis narrative; front-matter unchanged
- [ ] `deepseek_key` retained (per-video summaries + idea_extractor)
- [ ] HR 18: formatter + round-trip test updated in the same commit
- [ ] RED→GREEN: synthesis-render test inverted; synthesis-fn-exists tests removed
- [ ] Live run: email has per-video summaries, NO Daily Synthesis; `.md` matches
- [ ] LOCKED ORACLE PASS (verbatim) + verify script ends `PASS`
- [ ] WORKFLOW_ARCHITECTURE + ROADMAP updated

## Execution

1. Set Status: executing, commit.
2. Paste RED (O1 fails; old synthesis-render test passes) BEFORE Part 1.
3. Work Part 1 → 5 top to bottom; tick each as criteria are met.
4. Paste GREEN oracle + run the Asserting Verification Script (must end `PASS`).
5. Set Status: done, commit.
Satisfy all five gates in `docs/EXECUTOR_CONTRACT.md`; do not modify `# LOCKED ORACLE` assertions; STOP on any deviation.
Do not redesign. If the plan is ambiguous or wrong, stop and report — do not improvise.
