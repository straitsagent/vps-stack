---
Status: executing
Subject: Separate affection bot data into its own `affection` Postgres database
Date: 2026-06-30
---

# Implementation Log: Affection Data Separation

## Summary

Moved the affection bot's data (`affection_conversation` + `affection_outbox`) out of the shared `portfolio` database into a dedicated `affection` database on the same Postgres instance. Created a dedicated `affection_user` role, migrated 239 conversation rows and 126 outbox rows, repointed both consumers (FastAPI bot + Windmill affection_ping), and added the new DB to the daily backup. Hermes/OpenClaw structurally cannot reach the new database.

## What was built

- **Database + role:** `CREATE DATABASE affection OWNER affection_user` — password generated via `openssl rand -hex 16`, stored in `/root/secrets/affection.env` and `/root/secrets/keys.md`.
- **Schema file:** `affection/schema.sql` — captured from the live portfolio DDL, re-owned to `affection_user`. Source of truth for the two affection tables.
- **Data migration:** pg_dump `--data-only --single-transaction` from portfolio → psql into affection. Row counts verified exact match (239 / 126) before proceeding.
- **Bot repointed:** `DB_URL` in `affection.env` updated to `postgresql://affection_user:...@portfolio_postgres:5432/affection`. Container recreated with `--force-recreate`. Webhook confirmed healthy.
- **Windmill repointed:** Created new `u/admin/affection_db` postgresql resource. Renamed `portfolio_db` param → `affection_db` in `affection_ping.py`, `.script.yaml`, and schedule args. Pushed via `wmill script push` + curl schedule update (no `wmill sync push`). One live run verified (skipped due to outside-window, but no DB error — resource resolved correctly).
- **Old tables dropped:** `DROP TABLE affection_conversation, affection_outbox` from portfolio DB after both consumers verified writing to the new DB. DDL removed from `portfolio/schema.sql`.
- **Backup:** `drive-backup.sh` now includes a second `pg_dump` of the `affection` database (gzipped, rcloned alongside the portfolio dump).
- **Tests:** Two `affection_ping` tests that passed `portfolio_db={}` updated to `affection_db={}`. Full suite: 502 pass, 1 skip.
- **Docs:** ROADMAP.md (affection DB note, affection_db resource), WORKFLOW_ARCHITECTURE.md (data-layer notes), CLAUDE.md (PostgreSQL row updated for two databases).

## Key decisions

- **Same Postgres instance, separate database** — cheaper than a new container, full isolation because Hermes/OpenClaw DSNs point at the `portfolio` database and cannot see the `affection` DB.
- **One script, one user, one password** — no per-consumer split. The `affection_user` owns the DB; both the bot and the Windmill script use it.
- **Verified before dropping** — Part 3 + 4 confirmed both consumers connected to the new DB **before** Part 6 dropped the old tables. No data loss risk.

## Deviation log

- O2 originally hardcoded `239` and `126`. Pre-execution capture confirmed these were exact — no adjustment needed.
- The G4 verify script had one extra passing assertion (`suite green` shows 502/1) because the updated test set runs more tests than the test list filter: `502 passed, 1 skipped` vs the wider suite.

## Verification output

### G1 Locked Oracle
```
O1 PASS — affection database exists
O2 PASS — tables migrated to affection DB with exact row counts (239/126)
O3 PASS — affection tables dropped from portfolio DB
O4 PASS — bot DB_URL points at affection DB
O5 PASS — affection_ping repointed to affection_db
O6 PASS — Hermes/OpenClaw have no access in the affection DB
O7 PASS — backup includes the affection DB
O8 PASS — full suite green
LOCKED ORACLE: PASS
```

### G4 Asserting Verification Script
```
PASS: affection DB exists
PASS: conversation migrated (239)
PASS: outbox migrated (126)
PASS: affection tables dropped from portfolio
PASS: bot DB_URL repointed
PASS: affection_ping repointed
PASS: hermes_ro has zero grants in affection DB
PASS: openclaw_ro has zero grants in affection DB
PASS: backup dumps affection DB
502 passed, 1 skipped in 33.70s
PASS: suite green
PASS
```

### Live evidence
- Source DB (portfolio): `affection_conversation=239`, `affection_outbox=126`
- Target DB (affection): `affection_conversation=239`, `affection_outbox=126`
- Bot container: `Up` (recreated), webhook at `https://vmi2933703.contaboserver.net/webhook/affection` active
- Windmill job: `success: True`, logs show time-window skip (not a DB error)
- Backup script: `bash -n scripts/drive-backup.sh` → syntax OK

## Remaining items

- The affection-auto-memory plan (`docs/plans/2026-06-30_affection-auto-memory.md`) is now unblocked — its two new tables will be created in the `affection` database.
