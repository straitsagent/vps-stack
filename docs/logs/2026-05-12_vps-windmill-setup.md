# Implementation Log — VPS Baseline: Windmill Install + Project Setup
**Date:** 2026-05-12 (initial install); project structure finalised 2026-05-27
**Commits:** Reconstructed from session transcripts — no git commits in this session (pre-GitOps; GitOps established 2026-06-03)
**Files changed:** `/etc/docker/daemon.json` (created), `docker-compose.yml`, `CLAUDE.md` (initial), `docs/ROADMAP.md` (initial)

---

## Plan Completed

Installed Windmill on a fresh Contabo VPS (Ubuntu 24.04) via Docker Compose. Resolved a Docker image-pull failure caused by broken IPv6 routing on the VPS. Connected the wmill CLI to the Windmill workspace. Established the project baseline — CLAUDE.md, ROADMAP.md, and folder structure — during a follow-up session on 2026-05-27.

---

## All Tasks Performed

1. SSHed into fresh Contabo VPS as root
2. Installed Docker and Docker Compose
3. Pulled Windmill `docker-compose.yml` from the Windmill docs
4. Ran `docker compose up -d` — failed immediately with a network error (see Bug 1)
5. Diagnosed IPv6 routing failure via the source IP in the error message
6. Disabled IPv6 in Docker daemon: created `/etc/docker/daemon.json` with `{"ipv6": false}`
7. Restarted Docker: `systemctl restart docker`
8. Re-ran `docker compose up -d` — succeeded; Windmill accessible at `http://<VPS_IP>:8080`
9. Created Windmill admin workspace (`admins`)
10. Installed wmill CLI, ran `wmill workspace add` to connect to the local instance
11. Verified login token and workspace connection with `wmill workspace list`
12. (2026-05-27) Worked through project INSTRUCTIONS.md to establish the folder structure and conventions
13. (2026-05-27) Created initial CLAUDE.md with VPS environment, key paths, architecture principles, and hard rules
14. (2026-05-27) Created initial `docs/ROADMAP.md` with Phase 0 checklist and workflow build queue
15. (2026-05-27) Authenticated gcloud CLI as straitsagent@gmail.com
16. (2026-05-27) Added `windmill/` as the scripts directory — not yet synced to git (GitOps established Jun 3)

---

## Bugs Encountered

**Bug 1 — Docker compose failed with IPv6 connection reset**

Symptom: `docker compose up -d` exited immediately with:
```
failed to copy: read tcp [2605:a142:2293:3703::1]:47372->[2606:50c0:8001::154]:443: read: connection reset by peer
```

Root cause: Docker was attempting to pull the Windmill image from GitHub Container Registry (`ghcr.io`). On this Contabo VPS, the DNS resolver returned an IPv6 address for `ghcr.io`. The VPS had IPv6 enabled but the outbound IPv6 routing was broken — packets were sent from the VPS's IPv6 address but the connection was immediately reset at the remote end. Docker does not fall back to IPv4 if an IPv6 address is returned first.

Fix: Disabled IPv6 in the Docker daemon by creating `/etc/docker/daemon.json`:
```json
{"ipv6": false}
```
Then `systemctl restart docker`. With IPv6 disabled, Docker resolved `ghcr.io` to an IPv4 address and the pull succeeded.

Note: This setting is now permanent — all subsequent Docker operations on this VPS run IPv4-only. Documented in CLAUDE.md under "Running Services".

---

## Lessons Learned

1. On Contabo (and some other budget VPS providers), IPv6 is enabled but outbound routing is broken. Always disable IPv6 in Docker on a fresh Contabo VPS before attempting any image pull.
2. The source IP in Docker's TCP error message is the VPS's own IPv6 address — this is the reliable diagnostic signal. If you see a `[hexadecimal:...]` source IP in a Docker network error, the issue is IPv6 routing, not a credentials or firewall problem.
3. Setting `{"ipv6": false}` in `/etc/docker/daemon.json` is a one-line fix with no downside for a single-tenant VPS running purely IPv4 services.
4. Establish the GitOps workflow (git + wmill CLI) at project start, not after the first workflow is built. Scripts written directly in the Windmill UI before GitOps was set up were harder to track and version.
