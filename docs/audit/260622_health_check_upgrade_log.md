# Health Check Upgrade — Self-Notifying + Holistic Daily Brief
**Date:** 2026-06-22  
**Scope:** `health_check.py`, `health_check_telegram.py`, `error_alert.py`, `healthcheck-deadman.py`, schedule YAML, systemd timer.

---

## Motivation

Two structural design flaws identified:
1. **Silent failure**: the health check had no watcher — if it crashed or never ran, nothing fired. The workspace error handler (`error_alert.py`) existed but was email-only and deadman-blind.
2. **Content-blind**: health check only checked job metadata and email subject lines, never the actual content the system produced.

---

## Changes Made

### Layer A — Per-schedule Deepseek diagnosis (health_check.py)
- New `_diagnose_failure(label, path, status, error, age_str, deepseek_key) → {root_cause, remediation}`
- Called for each STALE/FAILED row in the schedule loop
- Results in `front_matter["diagnoses"]` list
- `main()` gained `deepseek_key` param

### Layer B — error_alert.py upgrade
- Added `_deepseek_diagnose(path, error, deepseek_key) → str` (1-line root-cause)
- Added `_send_telegram(bot_token, owner_id, path, job_id, error, diagnosis)` (best-effort)
- `main()` gained `telegram_bot_token`, `telegram_owner_id`, `deepseek_key` params
- `error_alert.script.yaml` updated with 3 new params
- Workspace error-handler `extra_args` updated via REST API — now passes all 5 args

### Layer C — Host deadman switch
- `/root/scripts/healthcheck-deadman.py` — pure `_should_alert(api_ok, jobs, now) → (bool, str)`
- Fires at 08:30 SGT via `~/.config/systemd/user/healthcheck-deadman.{service,timer}`
- Reads `WM_TOKEN`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_OWNER_ID` from `/root/agent.env`
- Alerts directly to Telegram API — no Windmill dependency
- Docker-compose: added `/root/scripts:/scripts:ro` mount for container test access

### Content Engine (health_check.py Parts 2A+B+C)
- `_collect_24h_reports(now, research_root="/research") → list` — scans 5 subdirs
- `SPEC_RULES` dict + `_spec_check(report) → {output, pass, violations}`:
  - macro: ≥12 Yahoo symbols, 13 FRED series, news_headlines present
  - portfolio: total_value/total_pnl/total_pnl_pct present
  - youtube: videos/video_count present
- `_synthesise_daily_digest(reports, xai_key, deepseek_key) → str`:
  - Grok-4 (`api.x.ai/v1`) primary, Deepseek fallback
  - 700-1000 word executive brief: numbered sections, bullet points, exec summary, conclusion
  - `main()` gained `xai_key` param
- New front-matter keys: `diagnoses`, `spec_checks`, `content_inventory`, `digest`

### health_check_telegram.py rewrite
- `_build_message` now renders: header → digest → ops status → spec failures → AI diagnoses → token usage → outbox audit
- All new keys optional (backward compatible with pre-upgrade `.md` files)
- Round-trip contract tests cover all 4 new keys

### Schedule + YAML (Part 2E)
- `health_check_daily.schedule.yaml`: `0 0 7 * * *` → `0 0 8 * * *` + added `portfolio_db`, `wm_token`, `deepseek_key`, `xai_key` args
- Schedule updated via REST API
- `health_check.script.yaml` description updated
- `health_check.script.lock` created with: pytz, requests, openai, psycopg2-binary, typing-inspection (and transitive deps)

---

## TDD Evidence

38 new tests in `agent/tests/test_windmill_scripts.py`:

| Section | Tests | Result |
|---|---|---|
| Part 1A (diagnosis) | 7 | GREEN |
| Part 1B (error_alert) | 5 | GREEN |
| Part 1C (deadman) | 7 | GREEN |
| Part 2A (collector) | 3 | GREEN |
| Part 2B (spec check) | 5 | GREEN |
| Part 2C (digest) | 4 | GREEN |
| Part 2D (contract) | 3 | GREEN |
| Part 2E (schedule) | 1 | GREEN |
| Fixed regressions | 2 | GREEN |

**Full suite: 420 passed, 1 skipped**

---

## Live Verification

Job `019eed3f-cb1f-9bcd-d775-b18f2fd39eb6` (2026-06-22 10:54 SGT):

```
INFO [Digest] 526 words synthesised  (Grok-4)
WARNING [SpecCheck] 5 spec failure(s)  (expected — old flat-schema .md files)
INFO [md] Written /research/health/2026-06-22_1054.md
INFO [Dispatch] health_check_telegram dispatched job_id=019eed40-...
```

Formatter job:
```
[HealthCheckTelegram] Message built: 830 words
[Telegram] Sending (5678 chars, 830 words):
[Telegram] Delivered OK
```

DB: `delivered=True`, `word_count=830`, `error=NULL`.

Digest preview (first 200 chars):
> "Markets delivered a bifurcated session in which US mega-cap technology and AI-exposed names advanced while Hong Kong and China holdings lagged, leaving the portfolio flat-to-up on the day..."

---

## Spec Check Notes

5 failures on the first run are expected: older macro `.md` files used the flat `indicators` schema (single-level dict) rather than the new nested `indicators.yahoo` / `indicators.fred` format. The spec validator correctly flags these. Next scheduled macro run will produce a conforming file.

---

## Deadman Smoke Test

```bash
$ python3 /root/scripts/healthcheck-deadman.py
WARNING [Deadman] Alerting: Health check last succeeded 235m ago
INFO [Deadman] Telegram alert sent.
Exit code: 2
```

Correctly fired (last scheduled run was 07:00 SGT, 3.5h before test — exceeds 90m threshold). Will be silent after tomorrow's 08:00 run.

---

## Commit

`98e6845` — feat: self-notifying health check + holistic daily brief
