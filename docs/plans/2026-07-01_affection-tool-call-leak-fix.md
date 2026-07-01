---
Subject: Fix affection bot tool-call XML leak (DSML markup in user-visible Telegram messages)
Date: 2026-07-01
Status: executing
Planner model: deepseek-v4-flash (opencode)
Executor model: any
Risk tier: LOW
Hard Rules in force: [4, 7, 12, 15, 17, 20, 22]
Complies with: docs/EXECUTOR_CONTRACT.md
Files to read before coding: affection/main.py, docs/TESTING.md, agent/tests/test_windmill_scripts.py
---

# Plan: Fix affection bot tool-call XML leak

## Context

The affection bot sent raw DeepSeek DSML tool-call XML to the user.
The leaked markup: `<｜｜DSML｜｜tool_calls>\n<｜｜DSML｜｜invoke name="search_memory">...`

Root cause: second-pass DeepSeek call uses `tools=[]`, disabling tool-calling.
When the model wants another tool call, it falls back to emitting DSML XML in `content`.

## Files changed

| Action | Path | Change |
|--------|------|--------|
| Edit | `affection/main.py` | Fix second pass to use `tools=ALL_TOOLS`; add `_sanitize_content()`; add `MAX_TOOL_DEPTH=3` |
| Edit | `agent/tests/test_windmill_scripts.py` | Add 3 tests + `_load_bot_mod()` helper |

## Locked Oracle (G1)

```python
# LOCKED ORACLE — copy verbatim, do not modify assertions
import os, subprocess
def run(c):
    r = subprocess.run(c, shell=True, capture_output=True, text=True, cwd="/root")
    return r.returncode, r.stdout + r.stderr

AF = "/root/affection/main.py"
# O1
rc, o = run(f"grep -A2 'messages = build_messages(chat_id)' {AF} | head -10")
assert "tools=ALL_TOOLS" in o, f"O1 FAIL: {o}"
print("O1 PASS")
# O2
rc, _ = run(f"grep -q 'def _sanitize_content' {AF}")
assert rc == 0, "O2 FAIL"
print("O2 PASS")
# O3
rc, _ = run(f"grep -q 'MAX_TOOL_DEPTH' {AF}")
assert rc == 0, "O3 FAIL"
print("O3 PASS")
# O4
rc, o = run(f"grep -B1 -A1 'send_telegram(chat_id, reply)' {AF}")
assert "sanitize" in o, "O4 FAIL"
print("O4 PASS")
# O5
for n in ("test_sanitize_content_strips_dsml_markers","test_chat_with_search_second_pass_uses_all_tools","test_chat_with_search_max_tool_depth_returns_fallback"):
    rc, _ = run(f"grep -q '{n}' /root/agent/tests/test_windmill_scripts.py")
    assert rc == 0, f"O5 FAIL missing {n}"
print("O5 PASS")
# O6
rc, o = run("cd /root/agent && python3 -m pytest tests/test_windmill_scripts.py -q 2>&1 | tail -3")
assert rc == 0, f"O6 FAIL: {o}"
print("O6 PASS")
print("\nLOCKED ORACLE: PASS")
```

## Asserting Verification Script (G4)

```bash
cd /root; fail=0
chk(){ [ "$1" -eq 0 ] && echo "PASS: $2" || { echo "FAIL: $2"; fail=1; }; }
grep -q 'def _sanitize_content' affection/main.py; chk $? "sanitize fn"
grep -q 'MAX_TOOL_DEPTH' affection/main.py; chk $? "MAX_TOOL_DEPTH"
grep -A2 'messages = build_messages(chat_id)' affection/main.py | head -10 | grep -q 'tools=ALL_TOOLS'; chk $? "ALL_TOOLS"
grep -B1 -A1 'send_telegram(chat_id, reply)' affection/main.py | grep -q 'sanitize'; chk $? "sanitized send"
for t in test_sanitize_content_strips_dsml_markers test_chat_with_search_second_pass_uses_all_tools test_chat_with_search_max_tool_depth_returns_fallback; do grep -q "$t" agent/tests/test_windmill_scripts.py; chk $? "test $t"; done
( cd agent && python3 -m pytest tests/test_windmill_scripts.py -q -k 'sanitize_content or second_pass_uses_all_tools or max_tool_depth' 2>&1 | tail -3 ); chk ${PIPESTATUS[0]} "new tests"
[ $fail -eq 0 ] && echo "PASS" || exit 1
```

## Acceptance Gate

- [ ] second pass uses `tools=ALL_TOOLS`
- [ ] `_sanitize_content()` strips DSML markers
- [ ] `MAX_TOOL_DEPTH=3` prevents infinite loops
- [ ] `send_telegram` called with sanitized content
- [ ] 3 new tests, suite green
- [ ] LOCKED ORACLE PASS + verify script ends PASS

## Execution

1. Flip Status to executing, commit.
2. Work the checklist.
3. Run verification.
4. Leave Status: executing for reviewer.
