# Macro Telegram Synthesis Redesign — Implementation Log
**Date:** 2026-06-21  
**Scope:** `macro_daily_push_telegram.py` — replaced full narrative dump with Deepseek synthesis; expanded Yahoo/FRED display; added news headlines block.

---

## Motivation

`macro_research.py` generates a ~2,500-word HTML email. The prior formatter piped the first 600 words of that raw narrative directly into Telegram — producing an incoherent text-truncation rather than a readable synthesis. Additionally, the Yahoo numbers block only showed 8 symbols and FRED was absent entirely.

Target: ~500–700 word self-contained Telegram message with a coherent LLM synthesis + full macro numbers + top news sources.

---

## Changes Made

### 1. `_synthesise_telegram` — new function
Calls Deepseek `deepseek-chat` with a 400-450 word synthesis prompt:
- `temperature=0.3`, `max_tokens=700`
- Prompt instructs: flowing analytical prose, no bullets/headers, end with a complete sentence
- Fallback: first 600 words of narrative if key absent or API call fails

**Iteration notes:**
- First attempt (`max_tokens=1000`) produced 899 words with a truncated mid-sentence ending
- Fixed with reduced token budget + explicit "End with a complete sentence." instruction
- Result: ~450-word synthesis, complete final sentence

### 2. Yahoo grid expanded: 8 → 13 symbols (3 per row)
```
SP500  NDX    HSI
CSI300 VIX    UST10Y
DXY    EUR/USD USD/JPY
USD/SGD USD/HKD Gold
Brent
```

### 3. FRED block: 0 → 13 series in 4 grouped lines
```
Rates: Fed Funds X.XX%  SOFR X.XX%  2Y X.XX%  10Y-2Y +0.XXpp  10Y-3M +0.XXpp
Inflation: CPI X.XX%  PCE X.XX%  5Y BE X.XX%  10Y BE X.XX%
Credit: HY OAS X.XXpp  IG OAS X.XXpp  FCI +X.XXX
Labour: Unemp X.XX%
```
Formatting rules: spreads (T10Y2Y, T10Y3M) as `pp`, NFCI as signed float (no % suffix), values >100 as `X.X`, rest as `X.XX%`.

### 4. News headlines block: top 4 from `news_headlines` front-matter
```
_In focus:_
• Headline truncated to 70 chars — Source (date)
```

### 5. `main()` signature: added `deepseek_key: str = ""`
### 6. `macro_daily_push_telegram.script.yaml`: added `deepseek_key` parameter
### 7. `macro_research.py` `_dispatch_formatter`: added `deepseek_key` to args dict

---

## TDD Evidence

14 new tests added to `agent/tests/test_windmill_scripts.py`:

| Test | Type | Result |
|---|---|---|
| `test_macro_tg_has_synthesise_telegram` | Structural | GREEN |
| `test_macro_tg_main_accepts_deepseek_key` | Structural | GREEN |
| `test_macro_tg_yaml_has_deepseek_key` | Structural | GREEN |
| `test_macro_dispatch_passes_deepseek_key` | Structural | GREEN |
| `test_macro_tg_synthesise_calls_deepseek` | Behavioural | GREEN |
| `test_macro_tg_source_includes_hsi` | Behavioural | GREEN |
| `test_macro_tg_source_includes_ndx` | Behavioural | GREEN |
| `test_macro_tg_source_includes_hy_oas` | Behavioural | GREEN |
| `test_macro_tg_source_includes_unrate` | Behavioural | GREEN |
| `test_macro_tg_source_includes_nfci` | Behavioural | GREEN |
| `test_contract_macro_tg_synthesis_appears_in_message` | Contract | GREEN |
| `test_contract_macro_tg_expanded_fred_values_visible` | Contract | GREEN |
| `test_contract_macro_tg_expanded_yahoo_hsi_visible` | Contract | GREEN |
| `test_contract_macro_tg_news_headlines_visible` | Contract | GREEN |

Full suite: **383 passed, 1 skipped** (previously 369).

---

## Live Verification

Formatter triggered via Windmill REST API with `$res:u/admin/portfolio_db` + `$var:u/admin/deepseek_key`.

**Job logs (verified):**
```
INFO [Telegram] Sending (3136 chars, 545 words):
*Macro — Sat 21 Jun, 7:19 PM SGT*

S&P: 5,967  NDX: 21,488  HSI: 24,282
...
Rates: Fed Funds 4.33%  SOFR 4.30%  2Y 3.98%  ...
...
[450-word Deepseek synthesis — complete final sentence]
...
_In focus:_
• [4 headlines with sources and dates]
```

**Outbox query:**
```sql
SELECT word_count, delivered, error FROM telegram_outbox 
ORDER BY created_at DESC LIMIT 1;
-- word_count: 545 | delivered: true | error: null
```

Confirmed: ≥500 words, delivered, no error, no "→ email" pointer.

---

## Backward Compatibility

Old flat-schema `.md` files (8 Yahoo symbols, no nested `indicators.yahoo`) continue to render correctly — `_build_message` detects `"yahoo" in raw_indicators` and falls back to treating the top-level `indicators` dict as the Yahoo block.

---

## Outstanding

- `CPIAUCSL` / `PCEPI` rendered as raw index level (334.0) rather than YoY% (~3.4%) in the first live run. The `units=pc1` fix in `macro_research.py` was deployed but the test `.md` predated it. Next scheduled run (Mon 7:00 AM SGT) will confirm correct rendering.
