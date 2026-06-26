---
Subject: portfolio_thesis Seeding — hybrid auto-draft theses from research_reports, owner reviews
Date: 2026-06-25
Status: done
Planner model: claude-opus-4 (Claude Code)
Executor model: deepseek (opencode) or any
Hard Rules in force: [1, 6, 7, 10, 11, 15, 17, 19, 20, 22]
Risk tier: HIGH (planner-locked oracle)
Complies with: docs/EXECUTOR_CONTRACT.md
Files to read before coding: CLAUDE.md, docs/TESTING.md, docs/OPERATIONS.md, windmill/u/admin/portfolio_rationalization.py (thesis factor), agent/tools.py (run_thesis_write)
---

# Plan: portfolio_thesis Seeding (Hygiene Initiative 4 of 5)

## Context

`portfolio_thesis` has **0 rows**. It is load-bearing:
- `portfolio_rationalization.py` — `_fetch_thesis` (line 343) + `_apply_thesis_scores` (line 563)
  compute the **Thesis factor (10% weight in every scenario)**. Crucially the score is
  **`conviction` only**: `CONVICTION = {"High": 1.0, "Medium": 0.6, "Low": 0.2}` (line 565); catalysts/
  risks/target are context, not score inputs. With the table empty, every position scores 0 on this
  factor — a silent 10% dead weight in the ranking.
- `portfolio_earnings_analysis.py:94` reads `investment_thesis, conviction` for briefing context.
- Agent tools `thesis_read` (FAST) and `thesis_write` (GATED_WRITE) read/write it.

**Decision (owner, this session): hybrid auto-draft → review.** A new one-shot Windmill script
LLM-drafts a thesis per holding **from that holding's own `research_reports`**, writes it only where no
thesis yet exists (never clobbers a hand-edited one), and the owner then refines convictions for the
names that matter via the existing agent `thesis_write` command. All 33 positions have research
(82 reports / 36 tickers; depths: standard 68 / deep 9 / brief 5), so coverage is complete.

### Why a new script (not the agent thesis_write)
`thesis_write` writes one thesis from owner-supplied text. Seeding 33 from existing research is a
distinct batch job: read best report → LLM-draft → write-if-absent. It reuses the same table and the
same `ON CONFLICT (ticker)` contract as `tools.py:851`.

---

## ⚠️ Requires sign-off before coding (Hard Rules 6 + 10)

Approving this plan = approving **both** of the following:

**(1) Model:** Deepseek `deepseek-chat` via `$var:u/admin/deepseek_key`
(`OpenAI(api_key=..., base_url="https://api.deepseek.com")`, temperature 0.3) — same client pattern as
`portfolio_rationalization.py:689`. No Anthropic (owner preference). Confirm or substitute
(OpenRouter / xAI / Perplexity) at approval.

**(2) The exact LLM prompt** (generic framing per Hard Rule 10 — no persona):
```
You are drafting a concise investment thesis for a single equity position, using ONLY the research
provided below. Do not invent facts that the research does not support.

Return STRICT JSON with exactly these keys and nothing else (no markdown, no commentary):
{
  "investment_thesis": "<2-4 sentences: the core reason to own this stock>",
  "conviction": "High" | "Medium" | "Low",
  "key_catalysts": ["<short catalyst>", "..."],
  "risks": ["<short risk>", "..."],
  "target_price_usd": <number or null>
}

Rules:
- conviction reflects how strong and well-supported the bull case is in the research:
  High = strong, differentiated, well-evidenced; Medium = reasonable but balanced; Low = weak or heavily caveated.
- 2 to 4 items each for key_catalysts and risks. Keep every field tight and plain-text.
- target_price_usd: a 12-month price target only if the research supports one, else null.

Ticker: {ticker}
Research:
{research_content}
```

---

## Files changed

| Action | Path | Change |
|--------|------|--------|
| Create | `windmill/u/admin/portfolio_thesis_seeder.py` | New one-shot seeder script |
| Create | `windmill/u/admin/portfolio_thesis_seeder.script.yaml` | Script metadata (summary, lang python3) |
| Edit | `agent/tests/test_windmill_scripts.py` | Add loader + pure-logic regression tests (RED→GREEN) |
| Edit | `/root/docs/ROADMAP.md` | Part 5 empty-table item: portfolio_thesis resolved; drop `(0 rows)` note |
| Create | `/root/docs/logs/2026-06-25_portfolio-thesis-seeding.md` | Implementation log |

No existing script changes. No schedule (run on-demand / one-shot).

### Environment facts the executor needs
- Run from `/root`; git from `/root` only. Tests run **inside** the agent container (Hard Rule 15):
  `docker exec root-straitsagent-1 python -m pytest tests/test_windmill_scripts.py -q`. The container
  has no `openai`/`psycopg2` resolvable for bare import → tests must stub them (pattern below).
- Windmill: `http://localhost:8080`, workspace `admins`.
  `WM_TOKEN=$(grep "WM_TOKEN" /root/agent.env | cut -d= -f2 | tr -d ' ')`.
- Postgres: `docker exec root-portfolio_postgres-1 psql -U portfolio_user -d portfolio -c "<SQL>"`.
- Deploy: `wmill script push u/admin/portfolio_thesis_seeder.py` from `/root/windmill` (Hard Rule 9).
- **Preflight (already verified):** `$var:u/admin/deepseek_key` ✅ and `$res:u/admin/portfolio_db` ✅ exist.
- Target table contract (`portfolio_thesis`, UNIQUE(ticker)):
  `ticker, thesis_date, investment_thesis, key_catalysts JSONB, risks JSONB, conviction CHECK(High|Medium|Low), target_price_usd NUMERIC(12,2)`.

---

## Checklist

### Step 1 — Write the seeder script (structure)
`windmill/u/admin/portfolio_thesis_seeder.py` — separate **pure** logic (testable) from I/O (edges):

Requirements header + imports:
```python
# Requirements:
# psycopg2-binary>=2.9
# openai>=1.0
```
`main(portfolio_db: postgresql = {}, deepseek_key: str = "", ticker: str = "", overwrite: bool = False) -> dict`
- If `ticker` given → process only that one; else → all tickers from `portfolio_positions`.
- Returns `{"ok": bool, "seeded": [...], "skipped_existing": [...], "no_research": [...], "errors": {...}}`.

**Pure helpers (no I/O — these are what the tests exercise):**
```python
def _build_thesis_prompt(ticker: str, research_content: str) -> str:
    # returns the approved prompt text with {ticker} and {research_content} filled.

def _parse_thesis_response(raw: str) -> dict | None:
    # Strip optional ```json fences; json.loads; normalize:
    #   conviction -> one of High/Medium/Low (case-insensitive match), else "Medium"
    #   key_catalysts/risks -> list[str] (coerce non-list to [], drop non-str/empty)
    #   investment_thesis -> stripped str; if empty/missing -> return None (don't write a blank thesis)
    #   target_price_usd  -> float if numeric and > 0 else None
    # Returns dict {investment_thesis, conviction, key_catalysts, risks, target_price_usd} or None.
```
**I/O helpers (faked at edges in tests / exercised live):**
```python
def _pick_research_content(cur, ticker) -> str | None:
    # SELECT content FROM research_reports WHERE ticker=%s AND content IS NOT NULL
    # ORDER BY (CASE depth WHEN 'deep' THEN 3 WHEN 'standard' THEN 2 ELSE 1 END) DESC,
    #          word_count DESC NULLS LAST, created_at DESC
    # LIMIT 1;  -> returns content or None

def _call_deepseek(deepseek_key, prompt) -> str:
    # OpenAI(api_key=deepseek_key, base_url="https://api.deepseek.com")
    # model="deepseek-chat", temperature=0.3, max_tokens=700  -> message content

def _write_thesis(cur, ticker, parsed, overwrite) -> str:
    # if not overwrite: INSERT ... ON CONFLICT (ticker) DO NOTHING  (never clobber owner edits)
    # if overwrite:     INSERT ... ON CONFLICT (ticker) DO UPDATE ...
    # Mark drafts so the owner can spot them: prefix investment_thesis with "[auto-draft] ".
    # Returns "seeded" | "skipped_existing".
    # Columns: ticker, thesis_date(CURRENT_DATE), investment_thesis, key_catalysts::jsonb,
    #          risks::jsonb, conviction, target_price_usd, updated_at(NOW()).
```
`main` loop per ticker: `_pick_research_content` → (skip→no_research if None) → `_build_thesis_prompt`
→ `_call_deepseek` → `_parse_thesis_response` → (skip→errors if None) → `_write_thesis`. Wrap each
ticker in try/except so one failure doesn't abort the batch (Hard Rule 4 — log, don't silently fail).

### Step 2 — Write the failing tests first (RED) — Hard Rule 15
Add to `agent/tests/test_windmill_scripts.py` (new section). The artifact is the `portfolio_thesis`
row; the pure logic that determines row validity is `_parse_thesis_response` + `_build_thesis_prompt`.
```python
# ── portfolio_thesis_seeder — pure-logic regression ──────────────────────────
THESIS_SEEDER = os.path.join(os.path.dirname(__file__), "../../windmill/u/admin/portfolio_thesis_seeder.py")

def _load_thesis_seeder():
    from unittest.mock import MagicMock
    for _m in ("psycopg2", "openai"):
        sys.modules.setdefault(_m, MagicMock())
    sys.modules.setdefault("windmill_http_client", MagicMock())
    spec = importlib.util.spec_from_file_location("_thseed", THESIS_SEEDER)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod

def test_thesis_prompt_is_generic_and_has_json_contract():
    m = _load_thesis_seeder()
    p = m._build_thesis_prompt("NVDA", "NVDA has strong datacenter demand...")
    assert "NVDA" in p and "investment_thesis" in p and "conviction" in p
    assert "ONLY" in p  # research-grounded instruction present
    # generic framing guard (Hard Rule 10): no persona injected
    assert "infra" not in p.lower() and "banker" not in p.lower()

def test_parse_thesis_response_valid_normalizes_fields():
    m = _load_thesis_seeder()
    raw = '```json\n{"investment_thesis":"Owns the AI accelerator stack.","conviction":"high",' \
          '"key_catalysts":["Blackwell ramp","DC capex"],"risks":["China export limits"],' \
          '"target_price_usd":190}\n```'
    out = m._parse_thesis_response(raw)
    assert out["conviction"] == "High"           # normalized from "high"
    assert out["investment_thesis"].startswith("Owns")
    assert out["key_catalysts"] == ["Blackwell ramp", "DC capex"]
    assert out["target_price_usd"] == 190.0

def test_parse_thesis_response_bad_conviction_defaults_medium():
    m = _load_thesis_seeder()
    out = m._parse_thesis_response('{"investment_thesis":"x","conviction":"Strong","key_catalysts":[],"risks":[],"target_price_usd":null}')
    assert out["conviction"] == "Medium"
    assert out["target_price_usd"] is None

def test_parse_thesis_response_blank_or_malformed_returns_none():
    """Empty-artifact guard (Testing Critic #1): never write a blank/garbage thesis."""
    m = _load_thesis_seeder()
    assert m._parse_thesis_response("not json at all") is None
    assert m._parse_thesis_response('{"investment_thesis":"  ","conviction":"High"}') is None
```
**Run, confirm RED:**
```bash
docker exec root-straitsagent-1 python -m pytest tests/test_windmill_scripts.py -k "thesis_seeder or thesis_prompt or thesis_response" -q
```
Expected: FAIL — module/file does not exist yet (or helpers undefined).

**Testing Critic (Hard Rule 20):** ① blank/malformed → None guards empty-artifact; ② asserts on
fixture-unique strings ("Blackwell ramp"), not template text; ③ conviction normalization asserts a
*transform* ("high"→"High", "Strong"→"Medium"), not an echo; ④ no email/TG ASD (collector script) —
documented; ⑤ all output fields covered across the valid + default tests.

### Step 3 — Implement to GREEN, then deploy
- Implement Step-1 script until the Step-2 tests pass.
- Full file green: `docker exec root-straitsagent-1 python -m pytest tests/test_windmill_scripts.py -q`.
- Deploy: `cd /root/windmill && wmill script push u/admin/portfolio_thesis_seeder.py && cd /root`.
  Hard Rule 19 — confirm the generated `.script.lock` resolves real packages (the live run in Step 4 proves it).

### Step 4 — Live-verify ONE ticker (Hard Rule 17 — verify the row, not ok:True)
```bash
WM_TOKEN=$(grep "WM_TOKEN" /root/agent.env | cut -d= -f2 | tr -d ' ')
docker exec root-portfolio_postgres-1 psql -U portfolio_user -d portfolio -c "SELECT ticker,conviction FROM portfolio_thesis WHERE ticker='NVDA';"  # expect 0 rows
curl -s -X POST "http://localhost:8080/api/w/admins/jobs/run_wait_result/p/u%2Fadmin%2Fportfolio_thesis_seeder" \
  -H "Authorization: Bearer $WM_TOKEN" -H "Content-Type: application/json" \
  -d '{"portfolio_db":"$res:u/admin/portfolio_db","deepseek_key":"$var:u/admin/deepseek_key","ticker":"NVDA"}' \
  | python3 -c "import sys,json;d=json.load(sys.stdin);print('ok:',d.get('ok'),'| seeded:',d.get('seeded'))"
docker exec root-portfolio_postgres-1 psql -U portfolio_user -d portfolio -c \
  "SELECT ticker, conviction, target_price_usd, left(investment_thesis,80) AS thesis, jsonb_array_length(key_catalysts) AS n_cat FROM portfolio_thesis WHERE ticker='NVDA';"
```
**Success — ALL must hold:** `ok: True`, `seeded` includes NVDA; the SELECT returns **1 row** with
`conviction` ∈ {High,Medium,Low}, a non-blank `[auto-draft]`-prefixed thesis, and ≥1 catalyst.
**If conviction is null/invalid or thesis blank:** STOP and report.

> Use a real holding if NVDA is not in the portfolio — pick any from
> `SELECT ticker FROM portfolio_positions ORDER BY ticker LIMIT 1;`.

### Step 5 — Backfill all 33 (write-if-absent; never clobbers)
```bash
WM_TOKEN=$(grep "WM_TOKEN" /root/agent.env | cut -d= -f2 | tr -d ' ')
curl -s -X POST "http://localhost:8080/api/w/admins/jobs/run_wait_result/p/u%2Fadmin%2Fportfolio_thesis_seeder" \
  -H "Authorization: Bearer $WM_TOKEN" -H "Content-Type: application/json" \
  -d '{"portfolio_db":"$res:u/admin/portfolio_db","deepseek_key":"$var:u/admin/deepseek_key"}' \
  | python3 -c "import sys,json;d=json.load(sys.stdin);print('ok:',d.get('ok'));print('seeded:',len(d.get('seeded',[])));print('skipped_existing:',d.get('skipped_existing'));print('no_research:',d.get('no_research'));print('errors:',d.get('errors'))"
docker exec root-portfolio_postgres-1 psql -U portfolio_user -d portfolio -c \
  "SELECT conviction, count(*) FROM portfolio_thesis GROUP BY conviction ORDER BY 2 DESC;"
```
**Success:** NVDA shows under `skipped_existing` (proves no-clobber); remaining ~32 seeded; the
conviction histogram is populated. Note any ticker in `no_research`/`errors`.

### Step 6 — Owner review pass (the "hybrid" half)
Print the seeded set for the owner to refine the convictions that matter (only conviction drives the
score). Owner edits via the agent: `thesis NVDA` to read, then a `thesis_write`-style message to update.
```bash
docker exec root-portfolio_postgres-1 psql -U portfolio_user -d portfolio -c \
  "SELECT ticker, conviction, target_price_usd, left(investment_thesis,70) FROM portfolio_thesis ORDER BY conviction, ticker;"
```
This step is owner-driven and does not block commit.

### Step 7 — Docs + commit
1. `/root/docs/ROADMAP.md`: Part 5 "Empty Table Decisions" — set `portfolio_thesis` action to
   `✅ Resolved 2026-06-25 — hybrid auto-draft seeder; owner refines convictions. See log.`; remove the
   `*(0 rows — see Part 5)*` note after `portfolio_thesis` in the Database Tables section (~line 398).
2. Create `/root/docs/logs/2026-06-25_portfolio-thesis-seeding.md` (log: root cause empty, hybrid
   approach, model+prompt approved, RED→GREEN, live NVDA verify, backfill counts, no-clobber proof).
3. Commit from `/root`:
   ```bash
   cd /root
   git add windmill/u/admin/portfolio_thesis_seeder.py windmill/u/admin/portfolio_thesis_seeder.script.yaml \
           windmill/u/admin/portfolio_thesis_seeder.script.lock agent/tests/test_windmill_scripts.py \
           docs/ROADMAP.md docs/logs/2026-06-25_portfolio-thesis-seeding.md
   git commit -m "$(printf 'feat(portfolio_thesis): hybrid auto-draft seeder from research_reports\n\nNew one-shot seeder LLM-drafts a thesis per holding from its own research\n(Deepseek deepseek-chat), writes write-if-absent (never clobbers owner edits),\nmarks drafts [auto-draft]. Populates the rationalization Thesis factor\n(conviction-driven, 10%% weight) that was silently scoring 0 for all 33.\nPure _parse/_build helpers unit-tested RED->GREEN; live-verified one ticker;\nbackfilled all positions.\n\nCo-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>')"
   git push
   ```
**Success:** full pytest green; `git status` clean; push succeeded.

---

## Verification (run after the checklist)
- `SELECT count(*) FROM portfolio_thesis;` ≈ 33 (minus any no_research/errors), every row conviction ∈ {High,Medium,Low}.
- Re-running the seeder reports the existing rows under `skipped_existing` (no-clobber holds).
- `docker exec root-straitsagent-1 python -m pytest tests/test_windmill_scripts.py -q` — all green.
- `git status` clean after commit + push.

## Out of scope (subsequent hygiene plans)
`macro_daily_push` disposition (separate plan), optional API health monitor, the `research_tool.py:585`
column twin-bug. The downstream rationalization re-run picks up the new convictions automatically — no
reader change here.

## Locked Oracle Tests (G1)
> Planner-authored. The Step-2 tests ARE the locked oracle. Wrap them in
> `# LOCKED ORACLE — copy verbatim, do not modify assertions` and reproduce unchanged:
> - `_parse_thesis_response('{"conviction":"high",...}')['conviction'] == 'High'` (normalize)
> - `_parse_thesis_response('{"conviction":"Strong",...}')['conviction'] == 'Medium'` (invalid→default)
> - `_parse_thesis_response('not json') is None` and blank `investment_thesis` → `None` (never write blank)
> - `_build_thesis_prompt(...)` contains the JSON keys + "ONLY" and NO persona ("infra"/"banker" absent)
> Fix the parser/prompt to pass — never weaken an assertion.

## RED-proof requirement (G2)
Paste BEFORE implementing (fails — module/helpers absent), then GREEN after:
```bash
docker exec root-straitsagent-1 python -m pytest tests/test_windmill_scripts.py -k "thesis_seeder or thesis_prompt or thesis_response" -q
```

## Asserting Verification Script (G4)
```bash
docker exec root-portfolio_postgres-1 psql -U portfolio_user -d portfolio -tAc \
  "SELECT count(*) FROM portfolio_thesis" \
| { read n; [ "${n:-0}" -ge 30 ] && echo "rows=$n" || { echo "FAIL: only $n thesis rows"; exit 1; }; }
docker exec root-portfolio_postgres-1 psql -U portfolio_user -d portfolio -tAc \
  "SELECT count(*) FROM portfolio_thesis WHERE conviction NOT IN ('High','Medium','Low')" \
| { read n; [ "${n:-1}" -eq 0 ] && echo "PASS all_conviction_valid" || { echo "FAIL: $n invalid conviction"; exit 1; }; }
```
Close-out pastes this output ending in `PASS`, plus the re-run showing the seeded ticker under `skipped_existing` (no-clobber, G3).

## Acceptance Gate (G2/G3/G5 + review)
- [ ] Locked tests diff-clean vs the block above (G1)
- [ ] RED + GREEN runs pasted (G2)
- [ ] Asserting verify script output pasted, ends in `PASS` (G4)
- [ ] One-ticker live row + no-clobber re-run output pasted (G3)
- [ ] Sign-off items (model + exact prompt) confirmed before any code (Hard Rules 6/10)

## Execution
1. Confirm the two sign-off items (model + prompt). If owner has not approved, STOP.
2. Set front-matter `Status: executing`, commit.
3. Work the checklist top to bottom; Step 2 must be RED before Step 3; Step 4 must pass before Step 5.
4. Run the Verification section.
5. Set `Status: done`, commit.
Do not redesign. If any command errors or output differs from "Expected", STOP and report.
