---
Status: executing
Subject: Fix affection bot tool-call XML leak
Date: 2026-07-01
---

# Implementation Log: Affection Bot Tool-Call XML Leak

## Summary

Fixed a bug where the affection bot sent raw DeepSeek DSML tool-call XML to the user.
The leak happened when the second-pass DeepSeek call (made with `tools=[]`) wanted to
call a tool; with no tools defined, DeepSeek emitted the tool call as text in the
`content` field using DSML XML markers.

## What changed

- **`affection/main.py`**:
  - Added `import re`, `MAX_TOOL_DEPTH = 3`, `_sanitize_content()` regex function
  - Changed second-pass `tools=[]` to `tools=ALL_TOOLS` (root cause fix)
  - Added depth guard: when `depth >= MAX_TOOL_DEPTH`, returns a friendly fallback
  - Added recursive tool-loop in the second pass: if the model emits `tool_calls`
    again, execute them and recurse with `depth + 1`
  - Added `_sanitize_content(reply)` before sending to Telegram (defensive layer)
- **`agent/tests/test_windmill_scripts.py`**: 3 new source-code tests (regex strip,
  ALL_TOOLS presence, MAX_TOOL_DEPTH)

## Root cause

`chat_with_search` second pass used `tools=[]` (line 420). When DeepSeek wanted to
call `search_memory` again (after the first "no results" response), the empty tool
list forced it to emit the tool call as text inside `content`.

## Verification

### G1 Locked Oracle
```
O1 PASS — second pass uses ALL_TOOLS
O2 PASS — _sanitize_content defined
O3 PASS — MAX_TOOL_DEPTH defined
O4 PASS — reply sanitized before send
O5 PASS — 3 tests present
O6 PASS — new tests green
LOCKED ORACLE: PASS
```

### G4 Asserting Verification Script
All 6 checks PASS.

## Remaining

- Live verify: trigger the same input ("what do you remember") via Telegram to
  confirm no DSML XML leaks. Not yet run — owner to decide.
