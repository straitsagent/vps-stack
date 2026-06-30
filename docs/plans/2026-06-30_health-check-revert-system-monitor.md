---
Subject: Expand health_check into a comprehensive Windmill + VPS system monitor; remove LLM analysis; deprecate StraitsAgent health Telegram ping
Date: 2026-06-30
Status: executing
Planner model: claude-opus-4-8
Risk tier: MEDIUM-HIGH (modifies one working delivery workflow + formatter + schedule + tests; ADDS a host-side systemd collector writing into the read-only research seam)
Hard Rules in force: [4, 7, 12, 15, 16, 17, 18, 20, 22]
Complies with: docs/EXECUTOR_CONTRACT.md
Files to read before coding: CLAUDE.md, docs/EXECUTOR_CONTRACT.md, docs/TESTING.md, windmill/u/admin/health_check.py, windmill/u/admin/health_check_telegram.py, agent/tests/test_windmill_scripts.py, scripts/drive-backup.sh, /etc/systemd/system/drive-backup.timer
---

# Plan: Health Check → Comprehensive System Monitor

## Context

`health_check` (daily 08:00 SGT) is the Windmill **system monitor**: it checks every scheduled workflow for
run/failure/staleness, aggregates LLM token cost, runs Tier-0 artifact verification, and audits `telegram_outbox`.
It also accreted an **LLM analytical layer** — `_synthesise_daily_digest()` (Grok-4 "chief of staff" 700–1000 word
brief) and a deterministic ≥500-word `_build_health_narrative()`. Both are being removed: analysis/interpretation
moves to **Hermes** (Reflexive Alpha System, `docs/plans/2026-06-29_reflexive-alpha-system.md`), and the owner finds
the narrative unnecessary.

In its place the health check is **expanded into a comprehensive system monitor** covering not just Windmill
workflows but **VPS host health** — disk, memory, load, Docker containers — and the **daily Drive backup** status.
This directly addresses a real gap: the 2026-06-28/29 Drive backup outage went unnoticed for two days because
nothing monitored it. The health check will now catch it.

**Architectural constraint (verified):** `health_check` runs inside a Windmill worker that connects to a **dind
sidecar** (`DOCKER_HOST=tcp://dind:2375`), is privileged but mounts **only** `/root/research:/research` — no host
root fs, no host `/proc`, no host docker socket. It therefore **cannot** read host `df`/`free`/`docker ps`/`systemctl`
directly. The correct pattern (= **WS-A of the Hermes integration roadmap**, so this doubles as WS-A): a **host-side
collector** writes a metrics JSON into the already-mounted `/research/system/`, and `health_check` reads it. Hermes
(which reads `/research:ro`) gets the same system visibility for free.

**Delivery & consumption:** the health **email is KEPT** (system-monitor delivery). The **Telegram ping is removed**
(formatter retained on disk, per the 2026-06-29 rationalise precedent). The canonical `.md` becomes a **comprehensive
deterministic structured report** (markdown tables, no LLM narrative) that Hermes consumes to write its daily feedback
(the Hermes feedback job is WS-1 of the reflexive roadmap — out of scope here, enabled by this plan).

## Scope decisions (locked)

- **Email KEPT**, monitor-only content (no Daily Brief, no narrative).
- **`_build_health_narrative` REMOVED** — replaced by a deterministic structured body (tables/sections).
- **`_synthesise_daily_digest` REMOVED** — analysis moves to Hermes.
- **`deepseek_key` KEPT** (used by `_diagnose_failure`); **`xai_key` REMOVED** (digest-only).
- **Telegram dispatch REMOVED**; `health_check_telegram.py` retained on disk.
- **`telegram_outbox` audit KEPT** (monitoring, not analysis).
- **New host collector** writes `/research/system/vps_health.json`; health_check reads it (does not weaken any sandbox — collector runs on host, worker only reads the mounted file).

## New component: host system-metrics collector

| Item | Detail |
|---|---|
| Script | `/root/scripts/system-metrics-collector.py` — pure stdlib; collects metrics, writes JSON atomically |
| Output | `/root/research/system/vps_health.json` with `collected_at` (UTC ISO) + the metrics below |
| systemd | `/etc/systemd/system/system-metrics.service` + `system-metrics.timer` (every 30 min), reuses the `drive-backup.timer` pattern |
| Metrics | **disk** (`df` for `/` + docker root): pct used per mount · **memory** (total/used/available MiB + pct) · **load** (1/5/15 + core count) · **docker** (host `docker ps -a` → counts of running/exited/restarting + a `{name: state}` map; health_check flags any container whose state is not `running`/`Up`, excluding known one-shot/`Exited (0)` jobs) · **backup** (`systemctl show drive-backup.service` → Result, ExecMainStatus, ExecMainExitTimestamp age; `drive-backup.timer` active) · **uptime** |

Collector failures must not crash silently (Hard Rule 4): on any metric error it still writes the JSON with that
metric's value set to an `{"error": "..."}` object, so `health_check` can surface the gap.

## health_check thresholds (deterministic alerts)

| Signal | WARN | CRIT |
|---|---|---|
| Disk (any mount) | ≥ 85% | ≥ 95% |
| Memory available | < 10% | < 5% |
| Load (1-min) | > cores | > cores × 2 |
| Docker containers | any expected not running | — |
| Drive backup | last run 26–48h ago | failed (Result≠success) or > 48h |
| Collector JSON | stale > 90 min | missing |

## Files changed

| Action | Path | Change |
|--------|------|--------|
| Create | `scripts/system-metrics-collector.py` | Host collector → `/research/system/vps_health.json` |
| Create | `/etc/systemd/system/system-metrics.service` + `.timer` | 30-min timer (committed copies under `scripts/systemd/` for backup) |
| Edit | `windmill/u/admin/health_check.py` | Remove `_synthesise_daily_digest` + `_build_health_narrative`; remove digest from main/front-matter/email; remove Telegram dispatch; drop `xai_key`/telegram-token params; build deterministic structured `.md` body; **read `/research/system/vps_health.json`** and add System Resources + Backup sections + thresholds; remove "Digest" from `SPEC_RULES["Health Check"]` |
| Edit | `windmill/u/admin/health_check_telegram.py` | Tolerate missing `digest`/narrative keys (retained-on-disk; round-trip parity, HR 18) |
| Edit | `windmill/u/admin/health_check_daily.schedule.yaml` | Remove `xai_key`, `telegram_bot_token`, `telegram_owner_id` args |
| Edit | `agent/tests/test_windmill_scripts.py` | Invert telegram-push test; update `_agree` harness (monitor-only email, system-resources + backup sections present, no Daily Brief/narrative); front-matter round-trip drops `digest`, adds `system`/`backup` keys; add collector unit test |
| Edit | `docs/ROADMAP.md` | Health check row → comprehensive system monitor (Windmill + VPS + backup); Telegram retired; WS-A partially delivered (system-metrics seam) |
| Edit | `docs/WORKFLOW_ARCHITECTURE.md` | Health check spec rewrite; new collector component |
| Edit | `CLAUDE.md` | Running-services/formatter notes: collector timer added; health_check_telegram retired |

## Front-matter schema change (Hard Rule 18)

Front-matter loses `digest`, gains `system` (resource snapshot) + `backup` (status) blocks. Per HR 18 the formatter
`health_check_telegram._build_message` + its round-trip contract test are updated in the **same commit** (formatter
retained-on-disk; made tolerant of the new schema).

## Checklist

### Part 0 — host system-metrics collector
- [ ] **H0.1** Write `scripts/system-metrics-collector.py` (stdlib only): collect disk/memory/load/docker/backup/uptime; atomic write to `/root/research/system/vps_health.json`; per-metric error isolation (HR 4).
- [ ] **H0.2** Run it once manually; confirm valid JSON with all keys + a recent `collected_at`.
- [ ] **H0.3** Add `system-metrics.service` + `system-metrics.timer` (30-min) under `/etc/systemd/system/`; commit copies under `scripts/systemd/`. `systemctl enable --now system-metrics.timer`.
- [ ] **H0.4** Confirm timer fires and JSON refreshes (`systemctl list-timers system-metrics.timer`; JSON `collected_at` advances).

### Part 1 — health_check.py: remove analysis, add system monitoring
- [ ] **H1.1** Delete `_synthesise_daily_digest()` and `_build_health_narrative()`.
- [ ] **H1.2** Remove the digest synthesis block + `digest`/`narrative` locals in `main()`.
- [ ] **H1.3** Remove `digest` from `_build_front_matter()`; ADD `system` + `backup` keys from the JSON.
- [ ] **H1.4** Remove Daily Brief `digest_section` and the narrative block from the email; build a deterministic structured body (workflow status table + System Resources table + Backup status + token cost + tier-0).
- [ ] **H1.5** Rewrite `_build_md_content()` to emit the comprehensive deterministic `.md` (front-matter + structured sections; no LLM narrative).
- [ ] **H1.6** Remove the `_dispatch_formatter("health_check_telegram", …)` Telegram dispatch (and helper if now unused).
- [ ] **H1.7** Drop `xai_key`, `telegram_bot_token`, `telegram_owner_id` from `main()`. KEEP `deepseek_key`, `gmail_smtp`, `recipient_email`, `portfolio_db`, `wm_token`.
- [ ] **H1.8** Add a `_read_system_metrics()` reader for `/research/system/vps_health.json` with staleness/missing guards; apply the threshold table; fold WARN/CRIT into overall health status.
- [ ] **H1.9** `SPEC_RULES["Health Check"]` → `["Schedules", "Telegram Outbox"]` (drop "Digest").
- [ ] **H1.10** `py_compile` passes; autopush deploys clean.

### Part 2 — formatter + schedule
- [ ] **H2.1** `health_check_telegram.py`: tolerate missing `digest`/narrative; render from new `system`/`backup`/`rows` keys; no crash on new schema.
- [ ] **H2.2** `health_check_daily.schedule.yaml`: remove `xai_key`/telegram-token args; push schedule via API (NOT `wmill sync push`).

### Part 3 — tests (RED→GREEN)
- [ ] **H3.1** Invert `test_health_check_has_telegram_push` → `test_health_check_no_telegram_push` (dispatch + token param ABSENT).
- [ ] **H3.2** Update health_check `_agree` harness: monitor-only email; assert System Resources + Backup sections render with values from a faked `vps_health.json`; assert NO Daily Brief/narrative.
- [ ] **H3.3** Front-matter round-trip: `digest` absent; `system` + `backup` present; `ok_count`/`rows`/`total` present.
- [ ] **H3.4** Collector unit test: feed faked `df`/`free`/`systemctl` outputs (monkeypatched), assert JSON shape + threshold-relevant fields + per-metric error isolation.
- [ ] **H3.5** Full suite passes. Paste tail + count.

### Part 4 — live verify (Hard Rule 17)
- [ ] **H4.1** Collector live: JSON present, fresh, all sections populated with real host values.
- [ ] **H4.2** Trigger one live `health_check`: (a) email arrives with System Resources + Backup sections and NO Daily Brief/narrative; (b) `/research/health/<today>.md` written as comprehensive deterministic report, no `digest`/narrative, with `system`+`backup` front-matter; (c) NO `health_check_telegram` row in `telegram_outbox` for this run.
- [ ] **H4.3** Negative check: confirm a backup-stale or disk-high condition would surface (simulate by hand-editing a copy of the JSON and dry-running the threshold logic, or temporarily lower a threshold).

### Part 5 — docs
- [ ] **H5.1** ROADMAP: health check row + WS-A note + formatter table.
- [ ] **H5.2** WORKFLOW_ARCHITECTURE: health check spec + collector component.
- [ ] **H5.3** CLAUDE.md: collector timer in services; formatter retired note.

## Locked Oracle Tests (G1)

```python
# LOCKED ORACLE — copy verbatim, do not modify assertions.
import subprocess, json, os

def run(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd="/root")
    return r.returncode, r.stdout + r.stderr

HC = "windmill/u/admin/health_check.py"

# O1: LLM analysis layers removed
rc1, _ = run(f"grep -q '_synthesise_daily_digest' {HC}")
rc2, _ = run(f"grep -q '_build_health_narrative' {HC}")
assert rc1 != 0 and rc2 != 0, "O1 FAIL — digest and/or narrative still present"
print("O1 PASS — digest + narrative removed")

# O2: Telegram dispatch removed
rc, _ = run(f"grep -q 'health_check_telegram' {HC}")
assert rc != 0, "O2 FAIL — health_check still dispatches health_check_telegram"
print("O2 PASS — Telegram dispatch removed")

# O3: xai_key removed from main; deepseek_key retained
rc, out = run(f"grep -n 'def main' {HC}")
assert 'xai_key' not in out and 'deepseek_key' in out, f"O3 FAIL — main signature wrong: {out}"
print("O3 PASS — xai removed, deepseek kept")

# O4: health_check reads the system metrics JSON
rc, _ = run(f"grep -q 'vps_health.json' {HC}")
assert rc == 0, "O4 FAIL — health_check does not read /research/system/vps_health.json"
print("O4 PASS — system metrics consumed")

# O5: collector exists and emits valid JSON with required keys
assert os.path.exists("/root/scripts/system-metrics-collector.py"), "O5 FAIL — collector missing"
rc, out = run("python3 /root/scripts/system-metrics-collector.py")
assert rc == 0, f"O5 FAIL — collector run failed: {out}"
data = json.loads(open("/root/research/system/vps_health.json").read())
for k in ("collected_at", "disk", "memory", "load", "docker", "backup"):
    assert k in data, f"O5 FAIL — JSON missing key {k}: {list(data)}"
print("O5 PASS — collector emits disk/memory/load/docker/backup")

# O6: systemd timer installed for the collector
rc, out = run("systemctl is-enabled system-metrics.timer 2>&1")
assert "enabled" in out, f"O6 FAIL — system-metrics.timer not enabled: {out}"
print("O6 PASS — collector timer enabled")

# O7: schedule cleaned
rc, _ = run("grep -qE 'xai_key|telegram_bot_token|telegram_owner_id' windmill/u/admin/health_check_daily.schedule.yaml")
assert rc != 0, "O7 FAIL — schedule still passes removed args"
print("O7 PASS — schedule args cleaned")

# O8: suite green + inverted test present
rc, out = run("cd /root/agent && python3 -m pytest tests/test_windmill_scripts.py -q 2>&1 | tail -5")
assert rc == 0, f"O8 FAIL — suite failed:\n{out}"
rc2, _ = run("grep -q 'test_health_check_no_telegram_push' /root/agent/tests/test_windmill_scripts.py")
assert rc2 == 0, "O8 FAIL — inverted test missing"
print("O8 PASS — suite green + inverted test present")

print("\nLOCKED ORACLE: PASS")
```

## RED-proof requirement (G2)

Before Part 1: confirm O1/O2/O4 FAIL (digest+narrative+dispatch present, no JSON read) and the existing
`test_health_check_has_telegram_push` PASSES (old behaviour). Before Part 0: O5/O6 FAIL (no collector/timer).
Paste RED. After edits, paste GREEN (oracle PASS).

## Asserting Verification Script (G4)

```bash
#!/bin/bash
fail=0
cd /root
HC=windmill/u/admin/health_check.py
chk(){ [ "$1" -eq 0 ] && echo "PASS: $2" || { echo "FAIL: $2"; fail=1; }; }

grep -q '_synthesise_daily_digest' $HC; [ $? -ne 0 ]; chk $? "digest removed"
grep -q '_build_health_narrative' $HC; [ $? -ne 0 ]; chk $? "narrative removed"
grep -q 'health_check_telegram' $HC; [ $? -ne 0 ]; chk $? "telegram dispatch removed"
grep -q 'vps_health.json' $HC; chk $? "system metrics consumed"
test -f scripts/system-metrics-collector.py; chk $? "collector exists"
python3 scripts/system-metrics-collector.py >/dev/null 2>&1; chk $? "collector runs"
python3 -c "import json; d=json.load(open('research/system/vps_health.json')); assert all(k in d for k in ('collected_at','disk','memory','load','docker','backup'))"; chk $? "collector JSON shape"
systemctl is-enabled system-metrics.timer 2>&1 | grep -q enabled; chk $? "collector timer enabled"
grep -qE 'xai_key|telegram_bot_token|telegram_owner_id' windmill/u/admin/health_check_daily.schedule.yaml; [ $? -ne 0 ]; chk $? "schedule cleaned"
( cd agent && python3 -m pytest tests/test_windmill_scripts.py -q 2>&1 | tail -3 ); [ ${PIPESTATUS[0]} -eq 0 ]; chk $? "suite green"
grep -q 'test_health_check_no_telegram_push' agent/tests/test_windmill_scripts.py; chk $? "inverted test present"

[ $fail -eq 0 ] && echo "PASS" || exit 1
```

## Acceptance Gate

- [ ] `_synthesise_daily_digest` + `_build_health_narrative` removed; `.md` is comprehensive deterministic report
- [ ] Host collector + 30-min timer live; `/research/system/vps_health.json` fresh with disk/memory/load/docker/backup
- [ ] health_check reads the JSON; System Resources + Backup sections in email + `.md`; thresholds wired
- [ ] Telegram dispatch removed; formatter retained; `telegram_outbox` audit kept
- [ ] `xai_key`/telegram-token args removed from `main()` + schedule; `deepseek_key` kept
- [ ] HR 18: formatter + round-trip test updated same commit (digest→system/backup)
- [ ] RED→GREEN: telegram-push test inverted; collector unit test added
- [ ] Live: monitor email (no brief/narrative) + `.md` (no digest/narrative, has system+backup) + no telegram row
- [ ] LOCKED ORACLE PASS (verbatim) + verify script ends `PASS`
- [ ] ROADMAP + WORKFLOW_ARCHITECTURE + CLAUDE.md updated

## Execution

1. Set Status: executing, commit.
2. Paste RED (O1/O2/O4/O5/O6 fail; old telegram test passes) BEFORE editing.
3. Work Part 0 → 5 top to bottom; tick each `- [ ]` as criteria are met.
4. Paste GREEN oracle + run the Asserting Verification Script (must end `PASS`).
5. Set Status: done, commit.
Satisfy all five gates in `docs/EXECUTOR_CONTRACT.md`; do not modify `# LOCKED ORACLE` assertions; STOP on any deviation.
Do not redesign. If the plan is ambiguous or wrong, stop and report — do not improvise.
