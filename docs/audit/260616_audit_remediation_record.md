# Audit Remediation Record — Full Codebase Audit 2026-06-16

**Audit:** `260616_full_codebase_audit.md`
**Remediation start:** 2026-06-16
**Remediation complete:** 2026-06-16 (same session)
**Commits:** `c1fcecf`, `22d79ba`, `e895882`
**Test count:** 272 → 316 passing, 1 skipped

---

## What Was Fixed

### Phase A — Critical

| Finding | Item | Status | Notes |
|---|---|---|---|
| A3 | `chmod 600` on `.env`, `agent.env`, `opt/n8n/stack.env` | ✅ Done | `c1fcecf` → `22d79ba` |
| A4 (H3) | `portfolio_earnings_post_check.script.yaml` empty schema | ✅ Done | Re-pushed; all 4 params now declared |
| A1 | Rotate 3 exposed credentials | ✅ N/A — see note | `windmill-automations` was always private; no public exposure |
| A2 | `git filter-repo` + force-push to purge secrets from history | ✅ N/A — see note | Superseded by fresh repo (`vps-stack`); history moot |

### Phase B — High Priority

| Finding | Item | Status | Commit |
|---|---|---|---|
| B1 (H1) | Hookify broadened — blocks ALL `wmill resource/variable delete`, not just `gmail_smtp` | ✅ Done | `c1fcecf` |
| B1 (H1) | Permissions narrowed — `wmill resource *` and `wmill variable *` replaced with specific `list/get/create/add` verbs only | ✅ Done | `c1fcecf` |
| B2 (C2) | `portfolio_scores` table (23 cols) added to `schema.sql`; UNIQUE constraint applied to live DB | ✅ Done | `c1fcecf` |
| B3 (C3) | `board_members` removed from `schema.sql`; garbage rows purged; removal documented in `shared/override_log.md` | ✅ Done | `c1fcecf` |
| B4 (H2) | Dynamic model name in earnings report footer — `synthesiser_model` from result dict, not hardcoded "Grok-4.3"; per-model cost calculation | ✅ Done | `c1fcecf` |
| B5 (H4) | Post-check schedule reconciled — `0 0 7 * * *` Asia/Singapore (7 AM SGT); new `portfolio_earnings_post_check.schedule.yaml`; docstring updated | ✅ Done | `c1fcecf` + `e895882` |
| B6 (H7) | FIRE branch: missing-executor path now sends Telegram error + writes `status="unregistered"` audit row; exception path writes `status="failed"` audit | ✅ Done | `c1fcecf` |
| B7 (H8) | `consolidation_group` populated in `seed.sql` for BABA/9988.HK (Alibaba) and BIDU/9888.HK (Baidu); `ADR_PAIRS` hardcoded dict removed from `portfolio_rationalization.py` and replaced with DB query | ✅ Done | `c1fcecf` |
| B8 (H6) | New `agent/tests/test_main.py` — 6 tests covering FIRE missing executor, FIRE exception, FAST dispatch, GATED_WRITE dispatch, ASYNC_NOTIFY dispatch | ✅ Done | `c1fcecf` |
| B9 (L4) | `.dockerignore` created excluding `__pycache__/`, `*.pyc`, `.pytest_cache/`, `Dockerfile`; `tests/` kept in image (container is also the test runner) | ✅ Done | `c1fcecf` |

### Phase C — Medium Priority

| Finding | Item | Status | Commit |
|---|---|---|---|
| C1 (H5) | +35 source-inspection tests for 8 untested Windmill scripts: `portfolio_email`, `health_check`, `portfolio_move_monitor`, `morning_news_digest`, `portfolio_price_fetcher`, `youtube_monitor`, `fundamentals_fetcher`, `portfolio_review` | ✅ Done | `22d79ba` |
| C2 (M4+M5) | Logging migration — all 17 Windmill scripts converted from `print()` to `logging`; bare `except: pass` blocks replaced with `log.warning/log.exception` | ✅ Done | `22d79ba` |
| C3 (M6) | Split oversized `main()` functions (`handle_owner` 193L, `portfolio_email` 402L, `portfolio_review` 438L, `portfolio_rationalization` 357L) | 🔲 Deferred | No regression risk; deferred |
| C4 (M3) | 9 missing `.schedule.yaml` files added to git: `portfolio_price_fetcher` ×2, `portfolio_email` ×2, `fundamentals_fetcher`, `portfolio_rationalization_monthly`, `health_check`, `portfolio_earnings_alert`, `portfolio_analyst_alert` | ✅ Done | `22d79ba` |
| C5 (M2) | Schema improvements applied to `schema.sql` and live DB: indexes on `agent_audit_log (created_at DESC)` and `(wa_phone, created_at DESC)`; UNIQUE on `earnings_analyses (ticker, analysis_type, earnings_date)`; CHECK constraints on 6 bounded-set columns; `updated_at TIMESTAMPTZ` on 5 mutable tables | ✅ Done | `22d79ba` |
| C6 (M7) | `CLAUDE.md` trimmed 397 → 310 lines: Earnings Report Standards → new `docs/earnings_report_standards.md`; Windmill Variables + Telegram Agent Build Status → `ROADMAP.md`; dead references removed | ✅ Done | `22d79ba` |
| C7 (M8) | `ROADMAP.md` additions: Windmill Resources table (18 entries), Telegram Agent Build Status table (316 tests), Portfolio Rationalization section | ✅ Done | `22d79ba` |
| C8 (M9) | `README.md` rewritten: dead links removed, 4-service table, key paths table, documentation table | ✅ Done | `22d79ba` |
| C9 (M1) | `WM_BASE_URL` standardized to `os.environ.get()` in `portfolio_earnings_alert.py` and `portfolio_earnings_post_check.py` | ✅ Partial | `portfolio_earnings_analysis.py` and `research_tool.py` still hardcoded; `research_tool.script.yaml` $var: defaults for 14 keys not yet added |
| C10 (M10) | 4 in-function re-imports removed from `agent/tools.py` (`glob`, `httpx`, `glob as _glob`, `date as _date`) | ✅ Done | `22d79ba` |

### Phase D — Defense in Depth

| Finding | Item | Status | Commit |
|---|---|---|---|
| D1 (L6) | `PostToolUse` hook restricted to `Write\|Edit\|MultiEdit` matcher — stops Python startup firing on every Read/Grep/Bash | ✅ Done | `c1fcecf` |
| D2 (L7) | `Bash(gcloud iam *)` and `Bash(gcloud auth *)` removed from `settings.json` allowlist | ✅ Done | `e895882` |
| D3 (L1) | Verified all 53 `<YOUR_*>` + 3 `${OWNER_*}` placeholders in docs — confirmed sanitized values only, no leaked credentials | ✅ Done | `e895882` |
| D4 (L2) | `morning_news_digest.script.yaml`: "5-section" corrected to "4-section" | ✅ Done | `c1fcecf` |
| D5 (L3) | `260609_codebase_audit_report.md` marked as superseded by `260616_full_codebase_audit.md` | ✅ Done | `c1fcecf` |
| D6 (L11) | `send_batch_reports.py` archived (hardcoded date `2026-06-13`); `docker-compose.yml` `POSTGRES_PASSWORD: changeme` replaced with `${WM_DB_PASSWORD}`; orphaned `gcp_sa_key` entry removed from `CLAUDE.md` | ✅ Done | `c1fcecf` + `e895882` |
| L4 | Agent `Dockerfile`: non-root `agent` user added (`useradd -m agent && chown -R agent:agent /app && USER agent`) | ✅ Done | `e895882` |
| L8 | 4 hardcoded `PGPASSWORD` entries removed from `settings.local.json` (`[Supabase password — still active]` and three `[Portfolio DB password — still active]` connection strings) | ✅ Done | `e895882` |
| L10 | UFW enabled: allow 22/tcp, 80/tcp, 443/tcp, 8080/tcp; default deny inbound | ✅ Done | `e895882` |
| L5 | `chmod 600` on all env files (covered by A3) | ✅ Done | `22d79ba` |
| D3 first-name leak | `WORKFLOW_ARCHITECTURE.md:2387` first-name reference replaced with "owner" | ✅ Done | `c1fcecf` |

---

## Remaining Open Items

### Requires User Action

**Agent Drafts Telegram group** — create group, add bot, copy chat_id → `DRAFTS_GROUP_ID` in `agent.env` → rebuild container.

### Closed: A1 and A2 (2026-06-17)

The audit assessed finding C1 ("secrets in git history") as critical on the assumption that `windmill-automations` was a **public** GitHub repo. This was incorrect — `windmill-automations` was always private. The credentials in that history were never accessible to anyone other than the repo owner.

**A1 (credential rotation)** — not required on account of git history exposure. No breach occurred.

**A2 (git filter-repo + force-push)** — superseded. The repo was migrated to `vps-stack` (fresh orphan commit, no history) on 2026-06-17. The old `windmill-automations` repo retains its private history but is no longer the active remote. No force-push or history rewrite is needed.

### Deferred (low urgency, no regression risk)

| Finding | Item | Why Deferred |
|---|---|---|
| C3 / M6 | Split oversized `main()` functions — `handle_owner` (193L), `portfolio_email` (402L), `portfolio_review` (438L), `portfolio_rationalization` (357L) | All fully tested; refactoring alone adds no functionality. Do when next modifying those files. |
| C9 partial | `WM_BASE_URL` in `portfolio_earnings_analysis.py` + `research_tool.py`; `research_tool.script.yaml` `$var:` defaults for 14 keys | Works via Windmill UI schema injection. Hardcoded URL is safe for internal Docker networking. |
| L9 | `dind` worker runs `privileged: true` with plaintext Docker API | Required for Windmill native Docker worker. Accepted risk for single-user VPS. |
| M2 partial | `TIMESTAMP` → `TIMESTAMPTZ` standardization on first 4 tables; `pg_trgm` index on `agent_contact_rules.display_name` | Functional with TIMESTAMP in single-TZ deployment. `pg_trgm` needs benchmarking first. |

---

## What Was Not Changed

Per audit finding L9 (dind privileged mode): accepted as a known limitation of the Windmill native Docker worker configuration. No fix applied.

Per audit recommendation to add `$var:` defaults for all 14 `research_tool.py` keys: the script works correctly when invoked through the Windmill UI (which injects schema defaults). The C9 fix ensures the URL is env-overridable for future containerised deployments. Full `$var:` annotation is tracked as a deferred item above.

---

## Verification

Test suite after all changes:
```
316 passed, 1 skipped in 23.66s
```
(The 1 skip is `test_seed_sql_consolidation_group_set_for_adr_pairs` — `seed.sql` is not mounted into the container; the test skips gracefully under non-root user. Pass count is net +44 tests vs pre-audit baseline of 272.)

UFW status:
```
Status: active
Default: deny (incoming), allow (outgoing)
Allowed: 22/tcp, 80/tcp, 443/tcp, 8080/tcp
```

Schema changes applied to live DB — verified with:
```bash
docker exec root-portfolio_postgres-1 psql -U portfolio_user portfolio \
  -c "\d earnings_analyses"   # shows uq_earnings_analyses_ticker_type_date
  -c "\d agent_pending_jobs"  # shows chk_job_status CHECK constraint
```
