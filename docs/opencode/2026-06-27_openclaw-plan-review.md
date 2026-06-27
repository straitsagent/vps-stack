# OpenClaw Secure Deployment — plan review

**To:** Claude Sonnet 4.6 (planner)
**From:** Deepseek V4 (opencode review session, 2026-06-27)
**Re:** `docs/plans/2026-06-27_openclaw-secure-deployment.md` (Status: approved, Risk: HIGH)
**Status:** review findings — blockers must be fixed before execution; suggestions welcome debate

## Context

Reviewed the approved HIGH-tier OpenClaw deployment plan against the live stack
(`docker-compose.yml`, `portfolio/schema.sql`, actual file perms, live DB relations)
and against `docs/EXECUTOR_CONTRACT.md` (the Five Gates). The plan's threat model
and network-split design are sound; the issues below are correctness bugs in the
shipped artifacts and contract gaps in the plan structure. Findings are ordered
by severity.

---

## Blockers (ship-stopping — fix before any executor starts)

### B1 — `financial_statements_placeholder` does not exist → GRANT aborts atomically
Plan line 58 lists `financial_statements_placeholder` in the `GRANT SELECT ON ... TO
openclaw_ro` allowlist. It does not exist — not in `portfolio/schema.sql`, not anywhere
under `/root`, and not as a live relation (the only `financial%` relation is
`financial_health_metrics`). Postgres executes a multi-table `GRANT` as a single
statement: if any relation is missing the whole statement errors with
`ERROR: relation "financial_statements_placeholder" does not exist` and **zero tables
are granted**. The verify script §5 would then fail on `SELECT count(*) FROM
research_reports` (permission denied) — correctly catching the bug, but the plan ships
a migration that cannot succeed as written.

**Fix:** delete `financial_statements_placeholder` from the grant list. The annual
financials are already covered by `income_statements`, `balance_sheets`,
`cashflow_statements`. The plan's own note "Verify exact table names against schema.sql
at apply time" is an executor-side guard, but this is a planner-side error in a frozen
allowlist — the allowlist should be correct in the plan, not deferred to apply time.

### B2 — Verify script §5 passes for the wrong reason (G3 / Hard Rule 20 #5)
`! psql "$OPENCLAW_RO_DSN" -tAc "INSERT INTO watchlist_ideas DEFAULT VALUES"` checks
only non-zero exit. `watchlist_ideas.ticker` and `.source` are `NOT NULL` with no
default (schema.sql lines 598-599, confirmed live), so `INSERT ... DEFAULT VALUES`
fails with a **NOT NULL constraint violation**, not `permission denied for table`.
`! psql` is true regardless of *why* it failed → the "read-only enforced" assertion
is satisfied by a schema constraint, not by the role privilege. This is exactly the
wrong-reason failure G2/G3 forbids and aligns with both Hard Rule 20 (#5 claim-not-evidence)
and the EXECUTOR_CONTRACT self-check question 1 (empty-artifact tautology).

**Fix:** assert the error *text*, not just exit code:
```bash
psql "$OPENCLAW_RO_DSN" -tAc "INSERT INTO watchlist_ideas DEFAULT VALUES" 2>&1 \
  | grep -q "permission denied for table watchlist_ideas" \
  && echo "PASS: INSERT denied by privilege" || { echo "FAIL: DB write scope"; fail=1; }
```
Same pattern for the `key_management` SELECT denial — assert `permission denied`,
not just failure.

---

## Contract gaps (Five Gates — planner-side)

### C1 — No `# LOCKED ORACLE` block for a HIGH-tier plan (G1)
EXECUTOR_CONTRACT.md G1: "for high-risk plans ... the planner authors the locked
assertions up front." This plan is self-declared HIGH but ships no `# LOCKED ORACLE`
block. The G4 verify script is not a substitute — G1 requires frozen, copy-verbatim
assertions that the reviewer diffs against the committed artifact. For an infra plan
the frozen oracle can be the exact `docker inspect --format` strings plus their
expected literal outputs (e.g. `1000:1000 ro=true priv=false caps=[ALL]`), presented
as a copy-verbatim block. This is the same planner-side G1 gap documented in
`docs/opencode/2026-06-26_planner-side-hardening-suggestions.md`; this plan inherits
it.

### C2 — No RED-before-GREEN step specified (G2)
The plan's `## Execution` section jumps straight to "run the verify script — must end
in PASS." For a deployment, the RED run is the pre-deployment state: each verify check
fails because the `openclaw` container doesn't exist yet. The executor should paste
that failing run *before* building, then the passing run after. The plan should call
this out explicitly so the executor doesn't skip straight to GREEN.

---

## Verify-script correctness (the script is the oracle — it must be right)

### V1 — §1 does not actually assert `cap_drop: [ALL]`
The `docker inspect --format` string prints `caps={{.HostConfig.CapDrop}}`, but the
`grep -q "1000:1000 ro=true priv=false"` pattern does **not** include `caps=`. So
CapDrop is printed but never asserted — an Acceptance Gate item ("cap_drop ALL") is
unchecked by the very script meant to prove it. Add `caps=[ALL]` (verify Docker's
exact rendering) to the grep pattern.

### V2 — §2 depends on `nc`/`getent` that a slim node image likely lacks
`getent hosts dind || nc -z -w2 dind 2375` — `getent` and `nc` are not in
`node:22-slim` by default. If both are absent, the command errors with "command not
found", `grep -q .` matches the stderr, and the check false-fails. Specify a
guaranteed-present probe in the plan (e.g. install `busybox`/`iproute2` in the image,
or use a node one-liner:
`node -e "require('net').createConnection({host:'dind',port:2375},()=>{process.exit(0)}).on('error',()=>process.exit(1))"`).
The probe's availability must be a build-time requirement, not an assumption.

### V3 — §3 "no host/secret access" is a tautology + incomplete pattern
Two problems:
- `cat /research/../shared/keys.md` resolves **inside the container** to `/shared/keys.md`,
  which is not a mount point → `cat` fails on a non-existent path, not on a security
  boundary. The test "passes" trivially. The real question is whether any bind mount
  exposes host `/root` content — assert against `mount` output (only `/research`,
  `/docs`, `/config` binds + tmpfs + `/workspace`), not against a path that was never
  mounted.
- `env | grep -iE "PORTFOLIO_DB_PASSWORD|WM_TOKEN|smtp"` checks only a fixed subset of
  host-secret names. It does not verify that `openclaw.env` injected *only* the
  intended vars (LLM key, telegram token, `OPENCLAW_RO_DSN`). Add the inverse: assert
  the full env var set equals the allowlist, or at minimum that no *extra* host
  secrets (`*_PASSWORD`, `WM_*`, `DATABASE_URL`, `SMTP_*`, `*SA_KEY*`) are present.

---

## Plan precision / hardening-detail issues

### P1 — Phase 0 `find` command is wrong and inconsistent with its own file list
`find /root -maxdepth 2 -name '*.env' -o -name 'keys.md'` — without parens, `-o`
binds tighter than the implicit AND, so it parses as
`(-maxdepth 2 -name '*.env') -o (-name 'keys.md')` and the `keys.md` branch is **not**
depth-limited (descends the whole `/root` tree). It also omits
`windmill-sa-key.json` (which the plan's own file list, line 45, includes) and cannot
reach `/opt/n8n/stack.env` (under `/opt`, not `/root`). The success check thus does
not verify the file list it sits next to. Fix:
```bash
find /root /opt/n8n -maxdepth 2 \( -name '*.env' -o -name 'keys.md' -o -name 'windmill-sa-key.json' \) | xargs stat -c '%a %n'
```
and assert every line is `600`. (Confirmed live: only `/root/affection.env` is 644;
the rest are already 600 — so Phase 0 perm work is a one-file change today.)

### P2 — `openclaw_ro_role.sql` is not idempotent and underspecifies the apply command
- `CREATE ROLE openclaw_ro ...` errors on re-run ("role already exists"). Every other
  migration in `schema.sql` uses `CREATE TABLE IF NOT EXISTS` / `ADD COLUMN IF NOT
  EXISTS` — the new file should match that convention via a
  `DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='openclaw_ro') THEN ...; END IF; END $$;`
  guard. Confirmed live: `openclaw_ro` does not yet exist, so first run works, but the
  repo's re-runnable convention should hold.
- `PASSWORD :'pw'` uses psql variable interpolation — the plan says "pw injected at
  apply time" but doesn't give the exact `psql` invocation. Without it, an executor may
  pass the password on the CLI (visible in `ps`/shell history). Spec the command, e.g.
  `psql -v pw="$(gpg --decrypt ...)" -f openclaw_ro_role.sql`, or state that the
  password is read from a `chmod 600` temp file.

### P3 — `read_only: true` + only `/tmp` tmpfs may prevent OpenClaw from booting
The plan hardens the rootfs to read-only and provides only `/tmp` (tmpfs) and
`/workspace` (volume) as writable. Node/OpenClaw commonly writes to `~/.npm`,
`~/.config`, a session/log dir, and `/run`. If any of those are needed at startup the
container will fail to boot and the executor will be tempted to drop `read_only: true`
— which **weakens a containment control** (G5: stop, don't weaken). The plan should
enumerate OpenClaw's required write paths up front and add the matching tmpfs mounts
(e.g. `/home/openclaw`, `/run`) so the executor is not guessing. Flag this as a
build-time verification item, not an afterthought.

### P4 — Named volume `openclaw_workspace` will be root-owned; user `1000:1000` can't write
Named volumes are created root-owned. With `user: "1000:1000"` the agent cannot write
to `/workspace` until perms are fixed in the Dockerfile (`RUN mkdir -p /workspace &&
chown 1000:1000 /workspace`) or via an init chown. Otherwise the sandbox's *only*
writable path is unwritable — the agent silently can't do anything. Add the chown to
the Dockerfile spec.

### P5 — `straitsagent` is a weaker template than the plan implies
Plan line 31 calls `straitsagent` "a ready isolation template (non-root, no published
port, `:ro` mounts)." Confirmed live: `straitsagent` is `user=agent`, `ro=false`
(no read-only rootfs), and has **no** `cap_drop`, `no-new-privileges`, `mem_limit`, or
`pids_limit` (compose lines 214-229). It is non-root + ro-mounts + no-port only. The
openclaw block is a real hardening *beyond* straitsagent, not a mirror of it. Recommend
rewording so an executor does not copy straitsagent's block expecting it to carry the
hardening — the plan's openclaw yaml is the actual spec.

### P6 — Do NOT "normalize" `mem_limit`/`pids_limit` to `deploy.resources`
The existing compose uses `deploy.resources.limits.memory` (line 78), but that key is
**ignored by `docker compose` (non-swarm)** — only `mem_limit`/`pids_limit` actually
enforce. The plan's `mem_limit: 1g` / `pids_limit: 256` is therefore *more correct*
than the file's prevailing style. An executor may "tidy" it to match the file and
silently drop the enforcement. Add an explicit note: these limits must stay in the
enforcing (v2) key form; converting to `deploy.resources` weakens the control (G5).

### P7 — Caddyfile path in "files to read" points at the wrong file
Plan line 9 lists `/opt/n8n/Caddyfile`. The live compose mounts `./Caddyfile`
(= `/root/Caddyfile`, compose line 264); both files exist on disk but only
`/root/Caddyfile` is in use. The executor should read `/root/Caddyfile` to confirm no
webhook route is needed (openclaw is polling, so no Caddy change is expected). Fix the
path in the plan's front-matter.

### P8 — Telegram owner-ID retrieval command is unspecified
"reuse the value behind `u/admin/telegram_owner_id`" — that's a Windmill variable
path. The executor needs the exact `wmill` command (e.g.
`wmill variable get u/admin/telegram_owner_id`), and since it lands in `openclaw.env`
it's sensitive. Spec the command and note it must not be echoed into the plan or a
commit message.

---

## Process observations (non-blocking)

### O1 — `Status: approved` but Phase 0 step 3 mandates an owner sign-off
Phase 0 item 3 (LLM provider/model) requires owner sign-off "before writing config."
So an executor will hit a mandatory STOP partway through an "approved" plan. That's a
deliberate sign-off gate, not a defect — but worth noting the plan is approved yet not
runnable end-to-end without a round-trip. Per AGENTS.md, the executor should surface
this at session start.

### O2 — Acceptance Gate item depends on authoring a *new* plan file
"Phase 2 relocation written as a separate `docs/plans/` file" is an acceptance-gate
item whose artifact is another plan document, not a verifiable runtime artifact.
Reasonable for tracking the follow-up, but it means close-out requires producing a
second plan. Flagging so the reviewer knows "done" includes a doc-deliverable, not
just a passing verify script.

---

## What the plan gets right (so it isn't re-litigated)

- The two-network split (`openclaw_egress` + `openclaw_db`, the latter `internal: true`,
  postgres gets `openclaw_db` as a second network) correctly keeps openclaw off
  `root_default` and away from the unauthenticated `dind:2375` escape vector. Confirmed
  `portfolio_postgres` is currently on `root_default` only.
- Threat model (treat container as always-compromised; containment, not trust) is the
  right framing for an indirect-prompt-injection surface.
- Read-only DB role with explicit allowlist + `statement_timeout = 15s` DoS guard is
  the correct shape; the allowlist is accurate **except** for B1.
- Owner-only Telegram polling (no inbound port, no Caddy route) minimizes exposure.
- `no Anthropic API` memory rule is respected.
