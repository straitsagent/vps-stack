---
Subject: Separate affection bot data into its own `affection` Postgres database (prerequisite for affection memory)
Date: 2026-06-30
Status: draft
Planner model: claude-opus-4-8
Executor model: any
Risk tier: MEDIUM-HIGH (live data migration of 2 tables + 365 rows; repoints a running bot container + a live Windmill script/schedule; touches backup)
Hard Rules in force: [4, 7, 8, 9, 11, 12, 15, 22]
Complies with: docs/EXECUTOR_CONTRACT.md
Files to read before coding: docs/EXECUTOR_CONTRACT.md, docs/OPERATIONS.md, affection/main.py, windmill/u/admin/affection_ping.py, portfolio/schema.sql, scripts/drive-backup.sh
---

# Plan: Affection Data Separation

## Context

The affection bot is already its own container (`affectionbot`), but its data lives in the **shared
`portfolio` database** alongside financial data: `affection_conversation` (239 rows) and `affection_outbox`
(126 rows). The owner wants personal/social data structurally separated from financial data, and out of
reach of Hermes/OpenClaw.

A separate **database** (same Postgres instance) is the right boundary: Postgres grants are per-database, and
`hermes_ro`/`openclaw_ro` connect specifically to the `portfolio` database (`HERMES_RO_DSN=.../portfolio`),
so they **cannot** see a different database in the same instance. This is cheaper than a separate container
(no new container/volume) and achieves full isolation. This plan is the **prerequisite** for the affection
memory plan, which will then target the `affection` DB (making its INV-1 allowlist juggling moot).

Two consumers write these tables: the bot (`affection/main.py` via `DB_URL` env) and the Windmill
`affection_ping` (via the `portfolio_db` resource). Both must be repointed. No financial/portfolio script
reads affection tables (verified) — the only other references are in `agent/tests`.

## Scope decisions

- **New database `affection`** in the existing `root-portfolio_postgres-1` instance.
- **Dedicated `affection_user`** owns it (clean credential separation; `portfolio_user`/`hermes_ro` get no
  access to the `affection` DB). Password stored in `/root/secrets/affection.env` + a new Windmill resource.
- **Migrate both tables WITH data** (`affection_conversation` + `affection_outbox`).
- **`affection_conversation` gets a real schema definition** (currently created ad-hoc, absent from any
  schema file) in a new `affection/schema.sql`.
- **Drop the old tables from `portfolio`** only AFTER both consumers are verified writing to the new DB.
- **Backup:** add a second `pg_dump` for the `affection` DB to `drive-backup.sh`.
- HR8/9/11: create (not overwrite) a new `affection_db` Windmill resource; push the schedule via curl (not
  `wmill sync push`); resource refs in schedule args use string form (`"$res:u/admin/affection_db"`).

## Files changed

| Action | Path | Change |
|--------|------|--------|
| Create | `affection/schema.sql` | `affection_conversation` + `affection_outbox` DDL (source of truth for the affection DB) |
| Edit | `portfolio/schema.sql` | Remove `affection_outbox` DDL + its index (moved to affection DB) |
| Edit | `/root/secrets/affection.env` | `DB_URL` → `affection` DB as `affection_user` (gitignored) |
| Edit | `windmill/u/admin/affection_ping.py` | Param `portfolio_db` → `affection_db` |
| Edit | `windmill/u/admin/affection_ping*.schedule.yaml` | Arg `portfolio_db` → `"$res:u/admin/affection_db"` |
| Edit | `scripts/drive-backup.sh` | Add `pg_dump` of the `affection` DB |
| Edit | `docs/ROADMAP.md`, `docs/WORKFLOW_ARCHITECTURE.md`, `CLAUDE.md` | Note the new DB + service/data-layer change |

## Checklist

### Part 0 — Provision the affection database + user
- [ ] **A0.1** Create role + DB (password from a fresh secret; store in `affection.env` and keys.md):
  ```sql
  CREATE USER affection_user WITH PASSWORD '<pw>';
  CREATE DATABASE affection OWNER affection_user;
  ```
- [ ] **A0.2** Confirm `affection` DB exists and `affection_user` can connect.
- [ ] **A0.3** Commit (no secrets).

### Part 1 — Schema in the affection DB
- [ ] **A1.1** Capture the live `affection_conversation` + `affection_outbox` DDL:
  `docker exec root-portfolio_postgres-1 pg_dump -U portfolio_user -d portfolio --schema-only -t affection_conversation -t affection_outbox`.
- [ ] **A1.2** Write `affection/schema.sql` from that DDL (owned by `affection_user`).
- [ ] **A1.3** Apply to the affection DB: `docker exec -i root-portfolio_postgres-1 psql -U affection_user -d affection < affection/schema.sql`.
- [ ] **A1.4** Confirm both tables exist in the `affection` DB. Commit.

### Part 2 — Migrate the data
- [ ] **A2.1** Dump data only: `docker exec root-portfolio_postgres-1 pg_dump -U portfolio_user -d portfolio --data-only -t affection_conversation -t affection_outbox > /tmp/affection_data.sql`.
- [ ] **A2.2** Load into the affection DB: `docker exec -i root-portfolio_postgres-1 psql -U affection_user -d affection < /tmp/affection_data.sql`.
- [ ] **A2.3** Verify row counts MATCH the source (conversation **239**, outbox **126**). Paste both counts. STOP if mismatch.

### Part 3 — Repoint the bot container
- [ ] **A3.1** Update `/root/secrets/affection.env` `DB_URL` → `postgresql://affection_user:<pw>@portfolio_postgres:5432/affection`.
- [ ] **A3.2** `docker compose -f /root/docker-compose.yml up -d --force-recreate affectionbot` (re-read env_file).
- [ ] **A3.3** Confirm the bot connects to the affection DB: tail logs for a clean DB load; confirm `_load_memory(<chat_id>)` returns history (239-row table reachable). Paste evidence.

### Part 4 — Repoint the Windmill affection_ping
- [ ] **A4.1** Create the `affection_db` Windmill resource (curl POST per OPERATIONS.md; type postgresql; host/port/user=affection_user/password/dbname=affection). Do NOT touch `portfolio_db` (HR8).
- [ ] **A4.2** Edit `affection_ping.py`: rename the `portfolio_db` param to `affection_db` (it only writes `affection_outbox`).
- [ ] **A4.3** Update the `affection_ping` schedule arg(s): `portfolio_db` → `"$res:u/admin/affection_db"` (string form, HR11). Push schedule via curl (HR9 — not `wmill sync push`).
- [ ] **A4.4** `wmill script push windmill/u/admin/affection_ping.py`. Trigger one live run; confirm a new `affection_outbox` row lands in the **affection** DB (not portfolio). Paste evidence.

### Part 5 — Backup the new DB
- [ ] **A5.1** Add to `drive-backup.sh` (section 1, alongside the portfolio dump): `pg_dump -U affection_user -d affection | gzip > affection_db.sql.gz`, upload to `$DEST/`.
- [ ] **A5.2** Dry-run / syntax-check the script. Commit.

### Part 6 — Cut over: drop old tables from portfolio
- [ ] **A6.1** ONLY after Parts 3+4 verified writing to the affection DB: `DROP TABLE affection_conversation, affection_outbox` from the **portfolio** DB.
- [ ] **A6.2** Remove `affection_outbox` DDL + index from `portfolio/schema.sql`.
- [ ] **A6.3** Confirm the portfolio DB no longer has affection tables; both consumers still healthy. Commit.

### Part 7 — Tests + docs
- [ ] **A7.1** Update any `agent/tests` that connect to a DB for affection (point fixtures at the affection DB / adjust mocks). Full suite green.
- [ ] **A7.2** ROADMAP (running services: new `affection` DB + `affection_db` resource), WORKFLOW_ARCHITECTURE (data-layer note), CLAUDE.md (PostgreSQL row: affection DB separate). Commit.

## Locked Oracle Tests (G1)

```python
# LOCKED ORACLE — copy verbatim, do not modify assertions
import subprocess

def run(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd="/root")
    return r.returncode, r.stdout + r.stderr

def psql(db, sql, user="portfolio_user"):
    return run(f"docker exec root-portfolio_postgres-1 psql -U {user} -d {db} -tAc \"{sql}\"")

# O1: the affection database exists
rc, out = run("docker exec root-portfolio_postgres-1 psql -U portfolio_user -d postgres -tAc \"SELECT 1 FROM pg_database WHERE datname='affection'\"")
assert out.strip() == "1", f"O1 FAIL — affection database missing: {out.strip()}"
print("O1 PASS — affection database exists")

# O2: both tables exist in the affection DB with the migrated row counts
rc, out = psql("affection", "SELECT count(*) FROM affection_conversation", user="affection_user")
assert out.strip() == "239", f"O2 FAIL — affection.affection_conversation has {out.strip()} rows, expected 239"
rc, out = psql("affection", "SELECT count(*) FROM affection_outbox", user="affection_user")
assert int(out.strip()) >= 126, f"O2 FAIL — affection.affection_outbox has {out.strip()} rows, expected ≥126"
print("O2 PASS — tables migrated to affection DB with data")

# O3: the old tables are GONE from the portfolio DB
rc, out = psql("portfolio", "SELECT to_regclass('affection_conversation'), to_regclass('affection_outbox')")
assert out.strip() == "|", f"O3 FAIL — affection tables still present in portfolio DB: {out.strip()!r}"
print("O3 PASS — affection tables dropped from portfolio DB")

# O4: the bot's DB_URL points at the affection DB
rc, _ = run("grep -qE 'DB_URL=postgresql://[^@]+@portfolio_postgres:5432/affection' /root/secrets/affection.env")
assert rc == 0, "O4 FAIL — affection.env DB_URL does not point at the affection DB"
print("O4 PASS — bot DB_URL points at affection DB")

# O5: affection_ping uses the affection_db resource, not portfolio_db
rc, _ = run("grep -q 'affection_db' windmill/u/admin/affection_ping.py")
assert rc == 0, "O5 FAIL — affection_ping.py does not reference affection_db"
rc, _ = run("grep -q 'portfolio_db' windmill/u/admin/affection_ping.py")
assert rc != 0, "O5 FAIL — affection_ping.py still references portfolio_db"
print("O5 PASS — affection_ping repointed to affection_db")

# O6: hermes_ro/openclaw_ro structurally cannot see the affection DB (no grants there)
for role in ("hermes_ro", "openclaw_ro"):
    rc, out = psql("affection", f"SELECT count(*) FROM information_schema.role_table_grants WHERE grantee='{role}'", user="affection_user")
    assert out.strip() == "0", f"O6 FAIL — {role} has grants in the affection DB: {out.strip()}"
print("O6 PASS — Hermes/OpenClaw have no access in the affection DB")

# O7: backup dumps the affection DB
rc, _ = run("grep -q 'd affection' scripts/drive-backup.sh")
assert rc == 0, "O7 FAIL — drive-backup.sh does not pg_dump the affection DB"
print("O7 PASS — backup includes the affection DB")

# O8: suite green
rc, out = run("cd /root/agent && python3 -m pytest tests/test_windmill_scripts.py -q 2>&1 | tail -3")
assert rc == 0, f"O8 FAIL — suite failed:\n{out}"
print("O8 PASS — full suite green")

print("\nLOCKED ORACLE: PASS")
```

## RED-proof requirement (G2)

Before Part 0: paste the failing oracle (O1 affection DB missing, O3 tables still in portfolio, O4 DB_URL still
portfolio, O5 still portfolio_db, O7 backup unchanged). After all Parts, paste GREEN.

## Asserting Verification Script (G4)

```bash
#!/bin/bash
cd /root; fail=0
chk(){ [ "$1" -eq 0 ] && echo "PASS: $2" || { echo "FAIL: $2"; fail=1; }; }
PG="docker exec root-portfolio_postgres-1 psql -tAc"

$PG "SELECT 1 FROM pg_database WHERE datname='affection'" -U portfolio_user -d postgres | grep -q 1; chk $? "affection DB exists"
c=$(docker exec root-portfolio_postgres-1 psql -U affection_user -d affection -tAc "SELECT count(*) FROM affection_conversation"); [ "$c" = "239" ]; chk $? "conversation migrated (239)"
docker exec root-portfolio_postgres-1 psql -U portfolio_user -d portfolio -tAc "SELECT to_regclass('affection_outbox')" | grep -q affection; [ $? -ne 0 ]; chk $? "affection tables dropped from portfolio"
grep -qE 'DB_URL=postgresql://[^@]+@portfolio_postgres:5432/affection' /root/secrets/affection.env; chk $? "bot DB_URL repointed"
grep -q affection_db windmill/u/admin/affection_ping.py && ! grep -q portfolio_db windmill/u/admin/affection_ping.py; chk $? "affection_ping repointed"
grep -q 'd affection' scripts/drive-backup.sh; chk $? "backup dumps affection DB"
( cd agent && python3 -m pytest tests/test_windmill_scripts.py -q 2>&1 | tail -3 ); chk ${PIPESTATUS[0]} "suite green"
[ $fail -eq 0 ] && echo "PASS" || exit 1
```

## Acceptance Gate

- [ ] `affection` DB + `affection_user` provisioned; bot + affection_ping both write there (verified live)
- [ ] Data migrated with matching row counts (239 / ≥126); old tables dropped from portfolio
- [ ] `affection/schema.sql` is the source of truth; `affection_outbox` removed from `portfolio/schema.sql`
- [ ] Hermes/OpenClaw structurally cannot reach the affection DB (O6)
- [ ] `drive-backup.sh` dumps the affection DB; new password in `affection.env` + keys.md
- [ ] Full suite green; bot webhook healthy after recreate
- [ ] LOCKED ORACLE PASS (verbatim) + verify script ends `PASS`
- [ ] ROADMAP + WORKFLOW_ARCHITECTURE + CLAUDE.md updated

## Execution

1. Set Status: executing, commit.
2. Paste RED (G2).
3. Work Part 0 → 7 in order. **Do not drop the portfolio tables (Part 6) until Parts 3+4 are verified.**
4. Paste GREEN oracle + run the Asserting Verification Script (must end `PASS`).
5. Set Status: done, commit.
Satisfy all five gates in `docs/EXECUTOR_CONTRACT.md`; do not modify `# LOCKED ORACLE`; STOP on any deviation.
This migration moves live data — STOP and report on any row-count mismatch; never drop source tables before the new DB is verified.
