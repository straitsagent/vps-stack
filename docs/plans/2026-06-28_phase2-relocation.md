---
Subject: Phase 2 — Research / secrets / docs relocation (filesystem trust boundary)
Date: 2026-06-28
Status: draft
Planner model: Deepseek V4 (opencode)
Executor model: any
Risk tier: HIGH (touches 3 compose mounts, 14 research-writing scripts, 6 secret files, 5 doc files)
Hard Rules in force: [1, 5, 6, 7, 8, 9, 10, 11, 12, 15, 17, 20, 21, 22]
Complies with: docs/EXECUTOR_CONTRACT.md
Review: docs/opencode/2026-06-27_openclaw-implementation-log.md (this is the follow-up doc-deliverable from Acceptance Gate)
Files to read before coding: CLAUDE.md, /root/docker-compose.yml, docs/OPERATIONS.md, docs/EXECUTOR_CONTRACT.md
---

# Plan: Phase 2 — Filesystem Relocation (trust boundary)

## Context

This is the deferred **Acceptance Gate follow-up** from the OpenClaw deployment plan
(`docs/plans/2026-06-27_openclaw-secure-deployment.md`, line 212-222). Today:

- Research (`/root/research`, ~222 `.md` files) is inside `/root`, shared via bind mounts to 3
  services. The trust boundary is mount-discipline (ro vs rw), not filesystem ownership.
- Secrets (`.env` × 5, `keys.md`, `windmill-sa-key.json`) are scattered across `/root/` and
  `/root/shared/`. There is no single locked-down directory.
- Docs (`/root/docs/`, ~50 `.md` files) sit next to secrets and source code.

**Goal:** enforce the trust boundary with the filesystem, not just mount flags.

| What | From | To | Rationale |
|---|---|---|---|
| Research corpus | `/root/research/` | `/srv/shared/research/` | Read-only consumers (straitsagent, openclaw) cannot traverse parent to reach `/root`; rw consumer (windmill_worker) writes to a tree that contains no secrets by construction |
| Secrets | `/root/*.env`, `/root/shared/keys.md`, `/root/shared/windmill-sa-key.json` | `/root/secrets/` (mode `700`) | Single locked-down directory; every `env_file:` and path reference points to it |
| Docs | `/root/docs/` | `/srv/shared/docs/` | Same rationale as research — no `/root` traversal path from openclaw |

**What does NOT move:** `/root/agent/`, `/root/affection/`, `/root/portfolio/`, `/root/openclaw/`,
`/root/windmill/`, `/root/scripts/`, `/root/shared/override_log.md`, `/root/shared/python/`,
`/root/shared/js/` — these are source code, git-tracked repos, or non-secret operational files.

**Current bind-mount consumers (pre-relocation):**

| Host path | Container path | Service(s) | Mode |
|---|---|---|---|
| `/root/research` | `/research` | `windmill_worker`, `straitsagent`, `openclaw` | rw / ro / ro |
| `/root/docs` | `/docs` | `openclaw` | ro |
| `/root/windmill` | `/windmill` | `straitsagent` | ro |
| `/root/scripts` | `/scripts` | `straitsagent` | ro |

**Current env_file consumers:**

| env_file | Service |
|---|---|
| `agent.env` | `straitsagent` |
| `affection.env` | `affectionbot` |
| `openclaw.env` | `openclaw` |
| (`.env` — compose auto-read) | all Windmill services via `${VAR}` interpolation |

**Research-writing scripts (14 total):** all use `/research/` inside the container; only
`portfolio_rationalization.py` line 11 mentions `/root/research/` in a docstring (not at runtime).
No script hardcodes the host path `/root/research` at runtime — the mount-change is transparent.

---

## Files changed

| Action | Path | Change |
|---|---|---|
| **MOVE** | `/root/research/` → `/srv/shared/research/` | Research corpus (222 `.md` + `index.json`) |
| **MOVE** | `/root/.env` → `/root/secrets/.env` | Root compose env; symlink at `/root/.env` → `/root/secrets/.env` |
| **MOVE** | `/root/agent.env` → `/root/secrets/agent.env` | Agent env; compose path updated |
| **MOVE** | `/root/affection.env` → `/root/secrets/affection.env` | Affection env; compose path updated |
| **MOVE** | `/root/openclaw.env` → `/root/secrets/openclaw.env` | OpenClaw env; compose path updated |
| **MOVE** | `/root/shared/keys.md` → `/root/secrets/keys.md` | API keys |
| **MOVE** | `/root/shared/windmill-sa-key.json` → `/root/secrets/windmill-sa-key.json` | GCP SA key |
| **MOVE** | `/root/docs/` → `/srv/shared/docs/` | Docs corpus (~50 `.md`) |
| **EDIT** | `/root/docker-compose.yml` | 3 mount paths + 4 env_file paths |
| **EDIT** | `/root/windmill/u/admin/portfolio_rationalization.py` | Docstring line 11 (`/root/research/` → `/srv/shared/research/`) |
| **EDIT** | `/root/CLAUDE.md` | Key Paths table, Credentials section |
| **EDIT** | `/root/AGENTS.md` | Repo layout table |
| **EDIT** | `/root/docs/ROADMAP.md` | Filesystem table |
| **EDIT** | `/root/docs/OPERATIONS.md` | Credential restore paths |
| **EDIT** | `/root/README.md` | Filesystem table |

---

## Checklist

### Phase 1 — Pre-flight backup + validation

- [ ] **P1.1 — Backup tarball.** Create a timestamped backup of everything that will move:
  ```bash
  tar czf /root/backups/pre-relocation-$(date +%Y%m%d-%H%M%S).tar.gz \
    /root/research/ /root/docs/ /root/.env /root/agent.env /root/affection.env \
    /root/openclaw.env /root/shared/keys.md /root/shared/windmill-sa-key.json
  ```
  Success: tarball exists and `tar tzf` lists all expected paths.

- [ ] **P1.2 — Verify all services healthy.** `docker compose ps` shows all 9 core services `Up (healthy)` or `Up`. Specifically: `db`, `windmill_server`, `dind`, `windmill_worker`, `straitsagent`, `portfolio_postgres`, `affectionbot`, `openclaw`, `caddy`. Paste the output.

- [ ] **P1.3 — Verify research is writable by windmill_worker.** Run a canary write via the worker:
  ```bash
  docker compose exec windmill_worker touch /research/.pre-relocation-canary && \
  docker compose exec windmill_worker rm /research/.pre-relocation-canary && \
  echo "PASS: research rw from worker"
  ```
  Success: "PASS: research rw from worker" — no permission error.

- [ ] **P1.4 — Verify research is readable by straitsagent and openclaw.**
  ```bash
  docker compose exec straitsagent ls /research/news/*.md >/dev/null 2>&1 && echo "PASS: straitsagent" || echo "FAIL: straitsagent"
  docker exec openclaw ls /research/news/*.md >/dev/null 2>&1 && echo "PASS: openclaw" || echo "FAIL: openclaw"
  ```
  Success: both PASS.

### Phase 2 — Research relocation

- [ ] **P2.1 — Stop research-consuming services.** Take down straitsagent and openclaw (they mount research `:ro` — `mv` may fail if the mount is held):
  ```bash
  docker compose stop straitsagent openclaw
  ```
  `windmill_worker` stays up (rw mount — docker will handle the inode change on next job).

- [ ] **P2.2 — Create target directory and move research.**
  ```bash
  mkdir -p /srv/shared
  mv /root/research /srv/shared/research
  ls /srv/shared/research/index.json && echo "PASS: research moved" || echo "FAIL: move"
  ```
  Success: `ls` confirms `index.json` at new path; `/root/research` no longer exists.

- [ ] **P2.3 — Update compose mount paths.** In `/root/docker-compose.yml`:
  - `windmill_worker`: `/root/research:/research` → `/srv/shared/research:/research`
  - `straitsagent`: `/root/research:/research:ro` → `/srv/shared/research:/research:ro`
  - `openclaw`: `/root/research:/research:ro` → `/srv/shared/research:/research:ro`

- [ ] **P2.4 — Recreate windmill_worker to pick up new mount.**
  ```bash
  docker compose up -d --force-recreate windmill_worker
  ```
  Wait for `healthy`; verify the mount took effect:
  ```bash
  docker compose exec windmill_worker ls /research/index.json >/dev/null 2>&1 && echo "PASS" || echo "FAIL: worker mount"
  ```

- [ ] **P2.5 — Start straitsagent and openclaw with new mounts.**
  ```bash
  docker compose up -d straitsagent openclaw
  docker compose exec straitsagent ls /research/index.json >/dev/null 2>&1 && echo "PASS: agent" || echo "FAIL: agent"
  docker exec openclaw ls /research/index.json >/dev/null 2>&1 && echo "PASS: openclaw" || echo "FAIL: openclaw"
  ```

- [ ] **P2.6 — Run a research write test.** Trigger a lightweight research job and verify output lands on the new path:
  ```bash
  wmill job run --script-path u/admin/health_check.py --args '{}' --wait 2>&1 | tail -5
  ```
  Then confirm a new `.md` file appeared at `/srv/shared/research/health/` with today's date.
  ```bash
  ls -t /srv/shared/research/health/*.md | head -1 | xargs stat -c '%n %y'
  ```
  Success: file timestamp is after the P2.4 recreate time. If this fails, halt — do not proceed to Phase 3.

### Phase 3 — Secrets consolidation

- [ ] **P3.1 — Create locked-down secrets directory.**
  ```bash
  install -d -m 700 /root/secrets
  stat -c '%a %n' /root/secrets | grep -q '^700' && echo "PASS" || echo "FAIL"
  ```

- [ ] **P3.2 — Move secrets to /root/secrets/.**
  ```bash
  mv /root/agent.env /root/secrets/agent.env
  mv /root/affection.env /root/secrets/affection.env
  mv /root/openclaw.env /root/secrets/openclaw.env
  mv /root/shared/keys.md /root/secrets/keys.md
  mv /root/shared/windmill-sa-key.json /root/secrets/windmill-sa-key.json
  ```
  Verify all 5 files exist at new paths with correct perms (600):
  ```bash
  stat -c '%a %n' /root/secrets/* | grep -v '^600' && echo "FAIL: perm mismatch" || echo "PASS: all 600"
  ```

- [ ] **P3.3 — Handle root .env (compose auto-read).** Compose auto-reads `.env` from the project
  directory (`/root/`). Move the file to `/root/secrets/` and create a symlink so compose continues
  to find it:
  ```bash
  mv /root/.env /root/secrets/.env
  ln -s /root/secrets/.env /root/.env
  test -L /root/.env && test -f /root/.env && echo "PASS: symlink" || echo "FAIL: symlink"
  ```

- [ ] **P3.4 — Update compose env_file paths.** In `/root/docker-compose.yml`:
  - `straitsagent`: `env_file: [ agent.env ]` → `env_file: [ /root/secrets/agent.env ]`
  - `affectionbot`: `env_file: [ affection.env ]` → `env_file: [ /root/secrets/affection.env ]`
  - `openclaw`: `env_file: [ openclaw.env ]` → `env_file: [ /root/secrets/openclaw.env ]`

- [ ] **P3.5 — Recreate services that use env_file.**
  ```bash
  docker compose up -d --force-recreate straitsagent affectionbot openclaw
  ```
  Wait for all to be `Up`. Check logs for startup errors:
  ```bash
  docker compose logs --tail 20 straitsagent affectionbot 2>&1 | grep -iE 'error|fail|panic' | grep -v "skill symlink\|last-good\|EROFS" && echo "FAIL: startup errors" || echo "PASS: clean startup"
  ```
  Success: no unexpected errors (skill symlink, last-good, EROFS are expected from openclaw — see Bugs 5-6 in the implementation log).

- [ ] **P3.6 — Verify secret perms from within openclaw (no traversal possible).**
  ```bash
  docker exec openclaw sh -c 'ls /root/secrets/ 2>&1' | grep -q "No such file" && echo "PASS: secrets not reachable" || echo "FAIL: secrets reachable"
  ```
  Success: openclaw cannot see `/root/secrets/` — it has no `/root` bind mount.

- [ ] **P3.7 — Verify env vars still loaded.** Confirm each service still has its required env vars:
  ```bash
  docker exec openclaw sh -c 'env | grep -E "OPENAI_API_KEY|TELEGRAM_BOT_TOKEN|OPENCLAW_RO_DSN" | wc -l' | grep -q '3' && echo "PASS: openclaw env" || echo "FAIL: openclaw env"
  docker compose exec straitsagent sh -c 'env | grep -E "TELEGRAM_BOT_TOKEN|OPENROUTER_API_KEY" | wc -l' | grep -qE '[12]' && echo "PASS: straitsagent env" || echo "FAIL: straitsagent env"
  ```

### Phase 4 — Docs relocation

- [ ] **P4.1 — Stop openclaw (holds /docs mount).**
  ```bash
  docker compose stop openclaw
  ```

- [ ] **P4.2 — Move docs and update mount.**
  ```bash
  mv /root/docs /srv/shared/docs
  ls /srv/shared/docs/ROADMAP.md && echo "PASS: moved" || echo "FAIL: move"
  ```
  In `/root/docker-compose.yml`: openclaw mount → `/srv/shared/docs:/docs:ro`

- [ ] **P4.3 — Start openclaw and verify.**
  ```bash
  docker compose up -d openclaw
  docker exec openclaw ls /docs/ROADMAP.md >/dev/null 2>&1 && echo "PASS" || echo "FAIL"
  ```

### Phase 5 — Documentation updates

- [ ] **P5.1 — Update CLAUDE.md.** In the Key Paths table (lines 67-90):
  - `/root/research/` → `/srv/shared/research/`
  - `/root/shared/keys.md` → `/root/secrets/keys.md`
  - `/root/shared/windmill-sa-key.json` → `/root/secrets/windmill-sa-key.json`
  - `/root/docs/` → `/srv/shared/docs/`
  - Add `/root/secrets/` entry (mode 700, all credentials)
  - Update the Credentials section (line 97-102) paths

- [ ] **P5.2 — Update AGENTS.md.** Repo layout table:
  - Research → `/srv/shared/research/`
  - Docs references → `/srv/shared/docs/`
  - Secrets → `/root/secrets/` (replace `/root/shared/keys.md` line)

- [ ] **P5.3 — Update ROADMAP.md.** Filesystem table (lines 350-360): update all relocated paths.

- [ ] **P5.4 — Update OPERATIONS.md.** Credential restore section (line 58, 22): update `shared/keys.md` → `secrets/keys.md`.

- [ ] **P5.5 — Update README.md.** Filesystem table (lines 38-42): update relocated paths.

- [ ] **P5.6 — Fix docstring in portfolio_rationalization.py.** Line 11:
  `/root/research/portfolio/` → `/srv/shared/research/portfolio/`

### Phase 6 — Final verification

- [ ] **P6.1 — All services healthy.** `docker compose ps` — all 9 core services `Up`.

- [ ] **P6.2 — All mounts correct.** Run mount audit from the verification script below.

- [ ] **P6.3 — Research end-to-end write test.** Trigger a second health_check job and verify output at `/srv/shared/research/health/`.

---

## Locked Oracle Tests (G1)

```bash
# LOCKED ORACLE — copy verbatim, do not modify assertions

# O1: /root/secrets exists with mode 700
test "$(stat -c '%a' /root/secrets)" = "700"

# O2: All 7 secret files exist in /root/secrets/ and are mode 600
for f in .env agent.env affection.env openclaw.env keys.md windmill-sa-key.json; do
  test -f "/root/secrets/$f" || { echo "MISSING: /root/secrets/$f"; exit 1; }
  test "$(stat -c '%a' "/root/secrets/$f")" = "600" || { echo "PERM: /root/secrets/$f"; exit 1; }
done
echo "PASS: /root/secrets/* all 600"

# O3: /root/.env is a symlink pointing to /root/secrets/.env
test -L /root/.env && test "$(readlink /root/.env)" = "/root/secrets/.env"

# O4: Research is at /srv/shared/research/ (not /root/research)
test -f /srv/shared/research/index.json
! test -d /root/research 2>/dev/null

# O5: Docs are at /srv/shared/docs/ (not /root/docs)
test -f /srv/shared/docs/ROADMAP.md
! test -d /root/docs 2>/dev/null

# O6: All three research bind mounts point to /srv/shared/research
test "$(docker inspect windmill_worker --format '{{range .Mounts}}{{if eq .Destination "/research"}}{{.Source}}{{end}}{{end}}' 2>/dev/null || docker compose config 2>/dev/null | grep -A1 '/research' | tail -1 | xargs)" = "/srv/shared/research"
docker compose config 2>/dev/null | grep '/srv/shared/research:/research' | wc -l | grep -q '3'

# O7: openclaw docs mount points to /srv/shared/docs
docker compose config 2>/dev/null | grep '/srv/shared/docs:/docs'

# O8: env_file paths use /root/secrets/
docker compose config 2>/dev/null | grep 'env_file' | grep '/root/secrets/' | wc -l | grep -q '3'

# O9: openclaw cannot reach /root/secrets (no /root bind mount)
docker exec openclaw sh -c 'test -d /root/secrets 2>/dev/null' && exit 1 || true

# O10: keys.md no longer at /root/shared/
! test -f /root/shared/keys.md 2>/dev/null
! test -f /root/shared/windmill-sa-key.json 2>/dev/null
```

## RED-proof requirement (G2)

The RED state is **pre-relocation**: `/srv/shared/research/` does not exist, `/root/secrets/`
does not exist, old paths are still in place. Run the LOCKED ORACLE and Verification Script before
starting any moves — every check fails (wrong paths, missing dirs). Paste that failing run. Then
execute and paste the GREEN run.

## Asserting Verification Script (G4)

```bash
#!/bin/bash
fail=0

echo "=== 1. Secrets directory locked down ==="
test "$(stat -c '%a' /root/secrets)" = "700" && echo "  PASS: /root/secrets 700" || { echo "  FAIL: secrets perm"; fail=1; }

echo "=== 2. All secret files present + 600 ==="
for f in .env agent.env affection.env openclaw.env keys.md windmill-sa-key.json; do
  if test -f "/root/secrets/$f" && test "$(stat -c '%a' "/root/secrets/$f")" = "600"; then
    echo "  PASS: /root/secrets/$f 600"
  else
    echo "  FAIL: /root/secrets/$f"
    fail=1
  fi
done

echo "=== 3. Root .env is symlink ==="
test -L /root/.env && echo "  PASS: symlink" || { echo "  FAIL: not symlink"; fail=1; }

echo "=== 4. Research at new location ==="
test -f /srv/shared/research/index.json && echo "  PASS: research exists" || { echo "  FAIL: research missing"; fail=1; }
test -d /root/research 2>/dev/null && { echo "  FAIL: /root/research still exists"; fail=1; } || echo "  PASS: old research gone"

echo "=== 5. Docs at new location ==="
test -f /srv/shared/docs/ROADMAP.md && echo "  PASS: docs exist" || { echo "  FAIL: docs missing"; fail=1; }
test -d /root/docs 2>/dev/null && { echo "  FAIL: /root/docs still exists"; fail=1; } || echo "  PASS: old docs gone"

echo "=== 6. Compose mounts use new paths ==="
docker compose config 2>/dev/null | grep -q '/srv/shared/research:/research' && echo "  PASS: research mount" || { echo "  FAIL: research mount"; fail=1; }
docker compose config 2>/dev/null | grep -q '/srv/shared/docs:/docs' && echo "  PASS: docs mount" || { echo "  FAIL: docs mount"; fail=1; }

echo "=== 7. Compose env_file uses /root/secrets/ ==="
count=$(docker compose config 2>/dev/null | grep 'env_file' | grep -c '/root/secrets/')
test "$count" -ge 3 && echo "  PASS: $count env_file(s) to /root/secrets/" || { echo "  FAIL: env_file count=$count"; fail=1; }

echo "=== 8. openclaw cannot reach secrets ==="
docker exec openclaw sh -c 'test -d /root/secrets 2>/dev/null && exit 0 || exit 1' 2>/dev/null && { echo "  FAIL: openclaw can see secrets"; fail=1; } || echo "  PASS: secrets unreachable"

echo "=== 9. Services healthy ==="
down=$(docker compose ps --format json 2>/dev/null | python3 -c "import sys,json; [print(l['Service']) for l in (json.loads(line) for line in sys.stdin) if 'Health' in l and l['Health'] not in ('healthy','')]" | wc -l)
test "$down" -eq 0 && echo "  PASS: all services healthy" || { echo "  FAIL: $down unhealthy"; fail=1; }

echo "=== 10. openclaw reads research from new path ==="
docker exec openclaw ls /research/index.json >/dev/null 2>&1 && echo "  PASS: openclaw" || { echo "  FAIL: openclaw research"; fail=1; }

echo "=== 11. straitsagent reads research from new path ==="
docker compose exec straitsagent ls /research/index.json >/dev/null 2>&1 && echo "  PASS: straitsagent" || { echo "  FAIL: straitsagent research"; fail=1; }

echo "=== 12. Research write test (canary) ==="
docker compose exec windmill_worker touch /research/.relocation-canary 2>/dev/null && \
docker compose exec windmill_worker rm /research/.relocation-canary 2>/dev/null && \
echo "  PASS: research rw from worker" || { echo "  FAIL: research write"; fail=1; }

[ $fail -eq 0 ] && echo "PASS" || exit 1
```

## Acceptance Gate

- [ ] Backup tarball exists before any moves
- [ ] Research moved to `/srv/shared/research/`; `/root/research/` gone; all 3 compose mounts updated
- [ ] Secrets consolidated under `/root/secrets/` (mode 700); all 6 files at 600; `/root/.env` is symlink
- [ ] `/root/shared/keys.md` and `/root/shared/windmill-sa-key.json` no longer exist at old paths
- [ ] Docs moved to `/srv/shared/docs/`; `/root/docs/` gone; openclaw mount updated
- [ ] 3 compose `env_file:` paths updated to `/root/secrets/`
- [ ] All 9 core services healthy after relocation
- [ ] openclaw cannot reach `/root/secrets/` (no bind mount to `/root`)
- [ ] RED run pasted (pre-relocation, all checks fail) then GREEN run (post-relocation, all pass)
- [ ] LOCKED ORACLE block passes verbatim (G1) — 10/10 assertions
- [ ] Asserting Verification Script output ends in `PASS` (G4) — 12/12 checks
- [ ] CLAUDE.md, AGENTS.md, ROADMAP.md, OPERATIONS.md, README.md path references updated
- [ ] `portfolio_rationalization.py` docstring line 11 fixed

## Execution

1. Set Status: executing, commit.
2. Paste the RED run (LOCKED ORACLE + verify script — all fail on old paths).
3. Work Phases 1-6 top to bottom; tick each `- [ ]` only when its success criteria are met.
4. Run LOCKED ORACLE (must pass verbatim) then Asserting Verification Script (must end in `PASS`).
5. Editor updates CLAUDE.md, AGENTS.md, ROADMAP.md, OPERATIONS.md, README.md paths.
6. Reviewer flips Status: done per the Acceptance Gate.

Satisfy all five gates in `docs/EXECUTOR_CONTRACT.md`; do not modify the `# LOCKED ORACLE` block;
never `wmill sync push` (Hard Rule 9 — use `wmill script push <path>` only if script edits are
pushed); STOP on any deviation. If a service won't start after relocation, halt and report — do not
revert silently.
