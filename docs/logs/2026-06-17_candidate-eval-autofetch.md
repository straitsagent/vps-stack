# Implementation Log — Candidate Eval Auto-Fetch + Research Integration
**Date:** 2026-06-17
**Commits:** `c151e73`, `7f70aab`
**Files changed:** `portfolio_candidate_eval.py`, `portfolio_candidate_eval.script.yaml`, `portfolio_rationalization.py`, `portfolio_rationalization.script.yaml`, `portfolio_rationalization_monthly.schedule.yaml`, `agent/tools.py`, `agent/classifier.py`, `agent/tests/test_windmill_scripts.py`, `docs/ROADMAP.md`

---

## Plan Completed

Three gaps identified from the first live run of `portfolio_candidate_eval`:

**Change 1 — Auto-dispatch stock data + research in candidate eval** (`portfolio_candidate_eval.py`)
- Gate check: before loading fundamentals, inspect `valuation_snapshots` freshness (absent/stale/>3d → dispatch `stock_data_fetcher`) and `research_reports` freshness (absent/stale/>30d → dispatch `research_tool`)
- New params: `wm_token`, `finnhub_key`, `perplexity_key`, `serper_key`, `tavily_key`, `exa_key`, `brave_key`
- New functions: `_check_data_staleness`, `_dispatch_stock_fetcher`, `_check_research_staleness`, `_dispatch_research_tool`
- YAML: 7 new params with `$var:` defaults

**Change 2 — Use research report in candidate eval Grok prompt + email** (`portfolio_candidate_eval.py`)
- New function: `_fetch_latest_research` — reads full `research_reports` content for the ticker
- `_assemble_prompt()`: prepends full research report content to Grok prompt when available (no truncation — grok-4.3 context window handles it)
- `_build_report_body()`: inline preview (first 400 words) in email body

**Change 3 — Optional research synthesis in portfolio rationalization** (`portfolio_rationalization.py`)
- New param: `include_research: bool = False`
- New function: `_fetch_research_reports` — loads full research content for all portfolio tickers
- Integration: appended to Grok Call 2 prompt when `include_research=True`; code path unchanged when `False`
- Schedule: changed from monthly (1st of month) to weekly (every Monday 9PM SGT)
- YAML: added `include_research` boolean parameter

**Telegram wiring** (`agent/tools.py`, `agent/classifier.py`)
- `dispatch_candidate_eval`: passes 8 new keys to Windmill job payload
- `dispatch_rationalization`: forwards `include_research` flag
- Classifier: added `{"include_research": bool}` to `portfolio_rationalize` intent; added shortcuts "rationalize with research" / "full rationalization" / "deep rationalize" / "deep rationalise"

**TDD** (`agent/tests/test_windmill_scripts.py`)
- 9 new source-inspection tests (RED before implementation, GREEN after)
- Final test count: 353 passing, 1 skipped

---

## All Tasks Performed

1. Wrote 9 tests, confirmed RED
2. Added `_check_data_staleness()` — queries `valuation_snapshots` for `fetched_date`
3. Added `_dispatch_stock_fetcher()` — POSTs to `stock_data_fetcher`, polls for completion
4. Added `_check_research_staleness()` — queries `research_reports` for `created_at`
5. Added `_dispatch_research_tool()` — POSTs to `research_tool`, polls for completion
6. Added `_fetch_latest_research()` — reads full research report content
7. Modified `_assemble_prompt()` — prepends research block
8. Modified `_build_report_body()` — inline research preview
9. Added 7 new params to `main()` signature
10. Updated `portfolio_candidate_eval.script.yaml`
11. Added `_fetch_research_reports()` to `portfolio_rationalization.py`
12. Added `include_research` param and guarded block in `portfolio_rationalization.py`
13. Updated `portfolio_rationalization.script.yaml`
14. Updated `portfolio_rationalization_monthly.schedule.yaml` (weekly cadence, `include_research: false`)
15. Updated `agent/tools.py` — both dispatch functions
16. Updated `agent/classifier.py` — intent schema + new shortcuts
17. Confirmed 353 tests GREEN
18. Committed `c151e73`
19. Ran live E2E test on AAPL — exposed 3 bugs (see below)
20. Fixed all 3 bugs, committed `7f70aab`
21. Verified clean E2E: "stock_data_fetcher confirmed fresh data after 10s" + "Found research report dated 2026-06-17"
22. Updated `docs/ROADMAP.md`

---

## Bugs Encountered

### Bug 1 — API polling timeout: `jobs/completed/get` never returned completion

**Symptom:** `_dispatch_stock_fetcher` and `_dispatch_research_tool` dispatched sub-jobs successfully (job IDs returned), but the polling loop always timed out. Both sub-jobs were actually completing and writing data to DB — confirmed via direct psql queries.

**Initial implementation:**
```python
for attempt in range(timeout_s // 5):
    time.sleep(5)
    r = requests.get(f"{WM_BASE}/api/w/{WM_WORKSPACE}/jobs/completed/get/{job_id}", headers=headers, timeout=10)
    if r.status_code == 200:
        return True
```

**Investigation steps:**
1. Added `log.warning()` debug lines — still didn't appear in job logs (revealed Bug 2)
2. Once correct code was running (after Bug 3 fix): tested `jobs/completed/get/{id}` — returns HTTP 404 while running, 200 when done. But the poll was still failing.
3. Tested `jobs/get/{id}` — returns HTTP 404 always from inside workers.
4. Tested `jobs_u/get/{id}` — returns HTTP 200 with a `type` field (`"QueuedJob"`, `"RunningJob"`, `"CompletedJob"`). Changed poll to check `type == "CompletedJob"`. Still inconsistent.

**Root cause:** Windmill's internal job status API endpoints are unreliable from within Windmill worker containers due to internal routing issues. The endpoints return unexpected status codes depending on the execution environment.

**Fix:** Replaced all API polling with direct DB-check polling. After dispatching the sub-job, loop checking `_check_data_staleness()` or `_check_research_staleness()` against PostgreSQL directly until data is confirmed fresh:

```python
for attempt in range(timeout_s // 5):
    time.sleep(5)
    if _check_data_staleness(ticker, portfolio_db) == "fresh":
        log.info(f"[AutoFetch] confirmed fresh data after {(attempt+1)*5}s")
        return True
```

**Why this is better architecturally:** Verifies the outcome (data landed in DB) rather than job status. A job can complete successfully but fail to write data; API polling would return True in that case. DB-check polling cannot.

---

### Bug 2 — `print()` output not captured in Windmill job logs

**Symptom:** Added `print("[DEBUG] inside polling loop")` statements to diagnose Bug 1. These never appeared in the Windmill job log viewer.

**Root cause:** Windmill workers capture **stderr only**. Python's `print()` writes to stdout and is silently discarded. Python's `logging` module (configured with `logging.basicConfig(level=logging.INFO)`) writes to stderr — `log.info()`, `log.warning()`, `log.error()` all appear in Windmill logs.

**Fix:** Use `log.warning()` (not `log.info()`, which may be filtered at some log levels) or `log.error()` for debug output when investigating Windmill script behaviour.

**Rule for future:** Never use `print()` in Windmill scripts for diagnostic output. Always use `log.warning()` or `log.error()`. Add `logging.basicConfig(level=logging.INFO)` at module top level.

---

### Bug 3 (root cause of all polling failures) — Nested f-string broke Windmill lock generation

**Symptom:** Despite multiple script pushes after fixing Bug 1, Windmill continued executing the old version of the script. New job runs showed hash `31257cdd349ef36d` in `v2_job.runnable_id` regardless of how many times `wmill script push` succeeded.

**Investigation:**
1. `wmill script push` reported success — no error from CLI
2. Windmill UI confirmed new script versions were present
3. Queried `v2_job` table: `SELECT runnable_id FROM v2_job WHERE id = '<job_id>'` — confirmed old hash for all new jobs
4. Queried `script` table for all non-archived hashes of `portfolio_candidate_eval`:
   ```sql
   SELECT hash, has_lock, lock_error_logs FROM script
   WHERE path = 'u/admin/portfolio_candidate_eval'
   AND archived = false
   ORDER BY created_at DESC;
   ```
5. Found `lock_error_logs` on the latest hash: `"Error parsing code for imports: f-string: expecting '}' at byte offset 40938"`

**Root cause:** Windmill uses a Rust-based parser to scan Python source code for imports and generate a pip lockfile. A **nested f-string** (triple-quoted f-string inside an outer f-string expression) is valid Python 3.12 syntax but crashes the Rust parser:

```python
# BROKEN — nested f-string crashes Windmill's Rust import scanner:
prompt = f"""
...
{f"""== EXISTING RESEARCH REPORT (standard stock analysis, {research_report[1]}) ==
{research_report[0]}
[Note: Use the above qualitative context...]
""" if research_report else ""}
...
"""
```

When lock generation fails, Windmill **silently falls back to the last successfully-locked script hash** and executes that instead. No error is surfaced in the Windmill UI — the push succeeds, the version is stored, but jobs use the old code. This is the most dangerous failure mode for Windmill script development.

**Fix:** Extract the conditional content into a plain string variable built before the f-string, using string concatenation (no nested f-strings):

```python
# FIXED — plain string variable, no nesting:
if research_report:
    research_block = (
        "== EXISTING RESEARCH REPORT (standard stock analysis, " + research_report[1] + ") ==\n"
        + research_report[0]
        + "\n\n[Note: Use the above qualitative context...]\n\n"
    )
else:
    research_block = ""

prompt = f"""
...
{research_block}
...
"""
```

After fix: new hash got `has_lock=true`, `lock_error_logs=null`. Windmill started using the new code.

**Rule for future:** Never use nested f-strings in Windmill Python scripts. Conditionally-rendered multi-line content must be pre-built as a plain string variable, then embedded in the outer f-string. This includes `{f"..." if condition else ""}` patterns.

---

## Debugging Methodology for Windmill Lock/Hash Issues

When edits appear not to take effect despite successful `wmill script push`:

1. **Check lock error logs on the latest hash:**
   ```sql
   SELECT hash, has_lock, lock_error_logs
   FROM script
   WHERE path = 'u/admin/<script_name>'
   AND archived = false
   ORDER BY created_at DESC LIMIT 5;
   ```
   If `lock_error_logs` is non-null, lock generation failed. Find and fix the parse error.

2. **Verify which hash a specific job ran:**
   ```sql
   SELECT runnable_id FROM v2_job WHERE id = '<uuid>';
   -- Convert bigint to hex: printf '%x\n' <bigint> (note: may need sign handling for negatives)
   ```
   Compare against the hash column in `script` table to confirm which version executed.

3. **Confirm a fix took effect:** After pushing the fix, check `has_lock=true` and `lock_error_logs IS NULL` for the new hash before running a test job.

4. **For debugging from within workers:** Use `log.warning()` or `log.error()` — `print()` is silently discarded (stdout vs stderr).

---

## Lessons Learned / Rules for Future Implementations

1. **No nested f-strings in Windmill Python scripts.** Pre-build all conditional multi-line content as a plain string variable before embedding it in any f-string. Pattern to avoid: `{f"..." if cond else ""}` inside an outer f-string.

2. **Always verify lock generation after first push.** After writing a new Windmill script, immediately query `script.lock_error_logs` on the latest hash before running any test. Failing to do this wastes multiple debugging rounds chasing symptoms of stale code.

3. **Poll DB directly, not Windmill job API, for sub-job completion from workers.** Windmill's internal job status endpoints (`jobs/completed/get`, `jobs_u/get`) are unreliable from within worker containers. For sub-job dispatch patterns: dispatch → poll the expected outcome in DB (e.g. `_check_data_staleness()`) → proceed.

4. **`print()` does not appear in Windmill job logs.** Use `logging.basicConfig(level=logging.INFO)` at module top and `log.warning()` for any diagnostic output that needs to appear in the job log viewer.

5. **When live test output does not match edits, check the DB before any other debugging.** Symptoms of stale code (poll timing out, logic not changing, log lines absent) should trigger an immediate `SELECT lock_error_logs FROM script WHERE path = '...' AND archived = false ORDER BY created_at DESC LIMIT 1` before adding more debug lines or restarting workers.

6. **TDD tests passed but live tests failed — the test surface was too shallow.** The 9 source-inspection tests verified presence of function names and keywords in source code. They could not detect parse errors that only manifest in Windmill's Rust scanner. For Windmill-specific code patterns (f-strings, import structures), add a `py_compile` check and consider a Windmill lock generation check as part of the test suite.
