---
Subject: Secrets consolidation to /root/secrets (700) + revoke openclaw /docs mount
Date: 2026-06-27
Status: executing
Planner model: claude-sonnet-4-6
Executor model: any
Risk tier: MEDIUM (moves 6 secret files, edits 3 env_file paths + 1 mount, recreates 3 services; fully reversible; no git-tracked data moves)
Hard Rules in force: [1, 5, 6, 8, 9, 12, 22]
Complies with: docs/EXECUTOR_CONTRACT.md
Supersedes: the Phase 3 (secrets) + openclaw-docs portions of docs/plans/2026-06-28_phase2-relocation.md
Review: docs/opencode/2026-06-27_phase2-relocation-plan-review.md
Files to read before coding: CLAUDE.md, /root/docker-compose.yml, docs/OPERATIONS.md, docs/EXECUTOR_CONTRACT.md
---

# Plan: Secrets consolidation + revoke openclaw /docs access

## Context

Slimmed-down successor to the Phase 2 relocation plan. The plan review
(`docs/opencode/2026-06-27_phase2-relocation-plan-review.md`) established that:

- **Research/docs relocation is dropped/deferred** — moving `/root/docs` and `/root/research`
  would pull ~196 git-tracked files out of the repo (root = `/root`), with no security gain
  (bind mounts already prevent any `/root` traversal from the containers). Research relocation,
  which the owner still wants, gets its **own** future plan with an explicit git-tracking story.
- **Secrets consolidation is the real, low-risk win** and ships here.
- **Plus an owner-requested hardening:** revoke openclaw's `/docs:ro` mount (shrink its read
  surface). Openclaw **keeps** its `/research:ro` access.

**Why this is low-risk (verified):** no secret file is bind-mounted into any container — only
three `env_file:` references (straitsagent→`agent.env`, affectionbot→`affection.env`,
openclaw→`openclaw.env`). `keys.md` and `windmill-sa-key.json` are not mounted anywhere; the GCP
SA key is consumed at runtime via a Windmill *resource*, so the on-disk copy is a reference/backup
and moving it does not touch any runtime path. So this change moves no live data path — it edits
file locations + 3 env_file paths + removes 1 mount.

### Secret files in scope

| File | From | To |
|---|---|---|
| Root compose env | `/root/.env` | `/root/secrets/.env` (+ symlink `/root/.env` → it) |
| Agent env | `/root/agent.env` | `/root/secrets/agent.env` |
| Affection env | `/root/affection.env` | `/root/secrets/affection.env` |
| OpenClaw env | `/root/openclaw.env` | `/root/secrets/openclaw.env` |
| API keys | `/root/shared/keys.md` | `/root/secrets/keys.md` |
| GCP SA key | `/root/shared/windmill-sa-key.json` | `/root/secrets/windmill-sa-key.json` |

**Not moved:** `/root/shared/override_log.md`, `/root/shared/python/`, `/root/shared/js/`
(non-secret operational files stay in `shared/`).

## Files changed

| Action | Path | Change |
|---|---|---|
| **CREATE** | `/root/secrets/` | New dir, mode `700` |
| **MOVE** | 6 secret files | Per table above |
| **SYMLINK** | `/root/.env` → `/root/secrets/.env` | Compose auto-reads `.env` from project dir |
| **EDIT** | `/root/.gitignore` | Add `secrets/` (the `keys.md`/`windmill-sa-key.json` rules are anchored to `shared/` and won't match the new location) |
| **EDIT** | `/root/docker-compose.yml` | 3 `env_file:` paths → `/root/secrets/…`; **remove openclaw `- /root/docs:/docs:ro` volume line** |
| **EDIT** | `/root/CLAUDE.md` | Key Paths + Credentials sections: `shared/keys.md`→`secrets/keys.md`, `shared/windmill-sa-key.json`→`secrets/windmill-sa-key.json`; note `/root/secrets/` (700) |
| **EDIT** | `/root/AGENTS.md`, `docs/OPERATIONS.md`, `README.md` | Any `/root/shared/keys.md` / `windmill-sa-key.json` path references → `/root/secrets/…` (only files that actually reference them) |

## Checklist

### Phase A — Pre-flight

- [ ] **A1 — Backup.** `tar czf /root/backups/pre-secrets-$(date +%Y%m%d-%H%M%S).tar.gz /root/.env /root/agent.env /root/affection.env /root/openclaw.env /root/shared/keys.md /root/shared/windmill-sa-key.json` — confirm `tar tzf` lists all 6.
- [ ] **A2 — No runtime hardcoded path refs.** Confirm nothing reads the old absolute paths at runtime:
  ```bash
  grep -rn "/root/shared/keys.md\|/root/shared/windmill-sa-key.json" \
    /root/windmill /root/scripts /root/agent /root/docker-compose.yml 2>/dev/null \
    | grep -v "\.md:" || echo "PASS: no runtime code references old secret paths"
  ```
  (Doc `.md` references are expected and handled in Phase D.) If any code/compose reference appears, STOP and report.
- [ ] **A3 — Services healthy.** `docker compose ps` — all up. Paste.

### Phase B — Consolidate secrets

- [ ] **B1 — Create dir.** `install -d -m 700 /root/secrets` ; assert `stat -c '%a' /root/secrets` = `700`.
- [ ] **B2 — gitignore first** (before any move, so a stray add can't catch them mid-flight). Add `secrets/` to `/root/.gitignore`; assert `git check-ignore /root/secrets/keys.md` succeeds.
- [ ] **B3 — Move the 5 non-`.env` files.**
  ```bash
  mv /root/agent.env /root/affection.env /root/openclaw.env /root/secrets/
  mv /root/shared/keys.md /root/secrets/keys.md
  mv /root/shared/windmill-sa-key.json /root/secrets/windmill-sa-key.json
  stat -c '%a %n' /root/secrets/* | grep -v '^600' && echo "FAIL: perm" || echo "PASS: all 600"
  ```
- [ ] **B4 — Move `.env` + symlink.**
  ```bash
  mv /root/.env /root/secrets/.env
  ln -s /root/secrets/.env /root/.env
  test -L /root/.env && test "$(readlink /root/.env)" = "/root/secrets/.env" && test -f /root/.env && echo "PASS: symlink"
  ```

### Phase C — Compose edits + recreate

- [ ] **C1 — Update env_file paths** in `/root/docker-compose.yml`:
  - straitsagent: `- agent.env` → `- /root/secrets/agent.env`
  - affectionbot: `- affection.env` → `- /root/secrets/affection.env`
  - openclaw: `env_file: [ openclaw.env ]` → `env_file: [ /root/secrets/openclaw.env ]`
- [ ] **C2 — Remove openclaw `/docs` mount.** Delete the line `      - /root/docs:/docs:ro` from the openclaw `volumes:` block. (openclaw retains `/research:ro`, `/config:ro`, `/workspace`.) `openclaw.json` does not reference `/docs` — no config change needed.
- [ ] **C3 — Validate compose parses** with the moved `.env`: `docker compose config >/dev/null && echo "PASS: compose valid"`. (Confirms the `.env` symlink resolves at parse time.)
- [ ] **C4 — Recreate the 3 services.**
  ```bash
  docker compose up -d --force-recreate straitsagent affectionbot openclaw
  ```
  Wait for all `Up`. Check clean startup (openclaw's skill-symlink / last-good / EROFS noise is expected — see implementation log Bugs 5-6):
  ```bash
  docker compose logs --tail 20 straitsagent affectionbot 2>&1 \
    | grep -iE 'error|fail|panic' | grep -v 'skill symlink\|last-good\|EROFS' \
    && echo "FAIL: startup errors" || echo "PASS: clean startup"
  ```

### Phase D — Docs

- [ ] **D1 — CLAUDE.md** Key Paths + Credentials: update the two `shared/…` secret paths to `secrets/…`; add `/root/secrets/` (mode 700) as the credentials home.
- [ ] **D2 — AGENTS.md, docs/OPERATIONS.md, README.md**: update any `/root/shared/keys.md` or `windmill-sa-key.json` references to `/root/secrets/…`. (Grep each first; only edit files that reference them.)

## Locked Oracle Tests (G1)

```bash
# LOCKED ORACLE — copy verbatim, do not modify assertions

# O1: /root/secrets exists, mode 700
test "$(stat -c '%a' /root/secrets)" = "700"

# O2: all 6 secret files present in /root/secrets, mode 600
for f in .env agent.env affection.env openclaw.env keys.md windmill-sa-key.json; do
  test -f "/root/secrets/$f" || { echo "MISSING /root/secrets/$f"; exit 1; }
  test "$(stat -c '%a' "/root/secrets/$f")" = "600" || { echo "PERM /root/secrets/$f"; exit 1; }
done

# O3: /root/.env is a symlink to /root/secrets/.env
test -L /root/.env && test "$(readlink /root/.env)" = "/root/secrets/.env"

# O4: old locations gone
! test -e /root/agent.env -o -e /root/affection.env -o -e /root/openclaw.env
! test -f /root/shared/keys.md
! test -f /root/shared/windmill-sa-key.json

# O5: secrets dir is gitignored
git -C /root check-ignore /root/secrets/keys.md >/dev/null

# O6: 3 env_file references now point at /root/secrets/
test "$(docker compose -f /root/docker-compose.yml config 2>/dev/null | grep -c '/root/secrets/.*\.env')" -ge 3

# O7: openclaw has NO /docs mount but KEEPS /research
! docker inspect openclaw --format '{{range .Mounts}}{{.Destination}} {{end}}' | grep -qw /docs
docker inspect openclaw --format '{{range .Mounts}}{{.Destination}} {{end}}' | grep -qw /research
```

## RED-proof requirement (G2)

RED state = **pre-execution**: `/root/secrets/` does not exist, secrets are still at old paths,
`/root/.env` is a regular file (not a symlink), openclaw still mounts `/docs`. Run the LOCKED
ORACLE and Verification Script before any move — every check fails. Paste that run, then execute
and paste the GREEN run.

## Asserting Verification Script (G4)

```bash
#!/bin/bash
fail=0

echo "=== 1. /root/secrets is 700 ==="
test "$(stat -c '%a' /root/secrets)" = "700" && echo "  PASS" || { echo "  FAIL"; fail=1; }

echo "=== 2. 6 secret files present + 600 ==="
for f in .env agent.env affection.env openclaw.env keys.md windmill-sa-key.json; do
  if test -f "/root/secrets/$f" && test "$(stat -c '%a' "/root/secrets/$f")" = "600"; then
    echo "  PASS: $f"; else echo "  FAIL: $f"; fail=1; fi
done

echo "=== 3. /root/.env symlink ==="
test -L /root/.env && test "$(readlink /root/.env)" = "/root/secrets/.env" && echo "  PASS" || { echo "  FAIL"; fail=1; }

echo "=== 4. Old paths gone ==="
( test -e /root/agent.env || test -f /root/shared/keys.md || test -f /root/shared/windmill-sa-key.json ) \
  && { echo "  FAIL: old path remains"; fail=1; } || echo "  PASS"

echo "=== 5. secrets/ gitignored ==="
git -C /root check-ignore /root/secrets/keys.md >/dev/null && echo "  PASS" || { echo "  FAIL"; fail=1; }

echo "=== 6. compose parses with moved .env ==="
docker compose -f /root/docker-compose.yml config >/dev/null 2>&1 && echo "  PASS" || { echo "  FAIL: compose invalid"; fail=1; }

echo "=== 7. env_file -> /root/secrets/ (>=3) ==="
c=$(docker compose -f /root/docker-compose.yml config 2>/dev/null | grep -c '/root/secrets/.*\.env')
test "$c" -ge 3 && echo "  PASS ($c)" || { echo "  FAIL ($c)"; fail=1; }

echo "=== 8. openclaw env vars still loaded ==="
docker exec openclaw sh -c 'env | grep -cE "OPENAI_API_KEY|TELEGRAM_BOT_TOKEN|OPENCLAW_RO_DSN"' | grep -q '3' \
  && echo "  PASS" || { echo "  FAIL: openclaw env"; fail=1; }

echo "=== 9. openclaw /docs removed, /research kept ==="
docker exec openclaw sh -c 'test ! -e /docs' && echo "  PASS: /docs gone" || { echo "  FAIL: /docs still mounted"; fail=1; }
docker exec openclaw ls /research/index.json >/dev/null 2>&1 && echo "  PASS: /research kept" || { echo "  FAIL: /research lost"; fail=1; }

echo "=== 10. services healthy ==="
for s in straitsagent affectionbot openclaw; do
  docker inspect "$s" --format '{{.State.Status}}' 2>/dev/null | grep -q running \
    && echo "  PASS: $s running" || { echo "  FAIL: $s"; fail=1; }
done

[ $fail -eq 0 ] && echo "PASS" || exit 1
```

## Acceptance Gate
- [ ] Backup tarball exists before any move
- [ ] A2 pre-flight: no runtime code/compose references the old secret paths
- [ ] `/root/secrets/` created mode 700; all 6 files moved, all 600; `/root/.env` is a symlink
- [ ] `secrets/` added to `.gitignore`; `git check-ignore` confirms the moved files are ignored
- [ ] Old paths (`/root/agent.env` etc., `/root/shared/keys.md`, `/root/shared/windmill-sa-key.json`) gone
- [ ] 3 `env_file:` paths updated to `/root/secrets/`; compose still parses
- [ ] openclaw `/docs` mount removed; openclaw retains `/research`; env vars still loaded
- [ ] straitsagent + affectionbot + openclaw recreated, running, clean startup
- [ ] RED run pasted (pre-move, all fail) then GREEN run (post-move, all pass)
- [ ] LOCKED ORACLE passes verbatim (G1)
- [ ] Verification Script ends in `PASS` (G4)
- [ ] CLAUDE.md (+ any other doc that references the moved paths) updated and committed

## Execution
1. Set Status: executing, commit.
2. Paste the RED run (LOCKED ORACLE + verify script — all fail on old layout).
3. Work Phases A–D top to bottom; tick each `- [ ]` only when its success criteria are met.
4. Run LOCKED ORACLE (must pass verbatim) then the Verification Script (must end in `PASS`).
5. Update docs (Phase D), commit.
6. Reviewer flips Status: done per the Acceptance Gate.

Satisfy all five gates in `docs/EXECUTOR_CONTRACT.md`; do not modify the `# LOCKED ORACLE` block;
never `wmill sync push` (Hard Rule 9). If a service won't start after the env_file move, halt and
report — restore from the A1 tarball; do not improvise.

---

## Follow-up (separate plans, not this one)
- **Research relocation** — owner wants `/root/research` → `/srv/shared/research`; needs its own
  HIGH-tier plan that resolves the git-tracking question (104 tracked files): relocate the repo,
  keep research in-repo + symlink into `/srv`, or move it out of git with an explicit versioning
  story. Not started.
- **Docs relocation** — dropped. Replaced by the openclaw `/docs`-mount revocation in this plan.
