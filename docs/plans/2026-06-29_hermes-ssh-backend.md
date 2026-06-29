---
Subject: Hermes SSH backend — sandbox VPS for unrestricted software installs
Date: 2026-06-29
Status: approved
Planner model: claude-sonnet-4-6
Risk tier: LOW-MEDIUM (Hermes container gets openssh-client; no change to sandbox boundary of main VPS)
Hard Rules in force: [7, 12, 13]
Files to read before executing: CLAUDE.md, hermes/Dockerfile, secrets/hermes.env, docs/ROADMAP.md (Part 7)
---

# Plan: Hermes SSH Backend

## Context

Hermes runs in a hardened container (`read_only` rootfs, `cap_drop: ALL`) which
prevents runtime package installs (`apt`, system-level). The hermes-agent framework
(v0.17.0) has a built-in SSH terminal backend (`tools/environments/ssh.py`) that
routes all of Hermes' terminal/file execution over an encrypted SSH connection to a
**separate, disposable sandbox VPS**. Verified against source: ControlMaster +
ControlPersist=300, CWD persistence, env carryover, tar-pipe file sync.

This gives Hermes full `sudo` on the sandbox while keeping the main VPS untouched.
If the sandbox is compromised or broken, it is rebuilt — not this machine.

## Security invariants (non-negotiable)

- The sandbox VPS must **never** have a route to the main VPS internal network.
- The SSH key used is a **dedicated ed25519 key** generated only for this purpose.
  The main VPS's own SSH keys are never shared with Hermes.
- The sandbox runs a restricted `hermes` user — optionally with `sudo` for installs.
- This plan does **not** weaken any of Hermes' existing container invariants
  (read_only rootfs, cap_drop ALL, no Docker socket, network isolation).
  The sandbox is a separate machine; the Hermes container spec does not change
  except adding `openssh-client`.

## Architecture

```
[Hermes container on main VPS]
  ↓ SSH (ControlMaster, ed25519 key in /workspace/.ssh/)
[Sandbox VPS — cheap, disposable, e.g. Hetzner CPX11 €3.29/mo]
  - hermes user (with sudo)
  - no firewall route back to main VPS
  - full apt install, npm, docker, whatever Hermes needs
```

## Files changed

| Action | Path | Change |
|--------|------|--------|
| Edit | `hermes/Dockerfile` | Add `openssh-client` to apt install |
| Edit | `/root/secrets/hermes.env` | Add 4 env vars (not committed to git) |
| Create | `/workspace/.ssh/id_hermes` + `.pub` | Dedicated SSH key pair (in hermes_state volume — persists across rebuilds) |
| Edit | `docs/ROADMAP.md` | Add SSH backend status |

## Prerequisites (user actions — executor cannot do these)

- [ ] **P1** Provision a sandbox VPS (Hetzner CPX11 recommended — €3.29/mo, 2 vCPU, 2GB RAM, 40GB SSD). Note the IP.
- [ ] **P2** Create a `hermes` user on the sandbox with sudo: `adduser hermes && usermod -aG sudo hermes`
- [ ] **P3** Confirm the sandbox has **no firewall rule or route** to the main VPS IP. If on the same Hetzner datacenter, use Hetzner Firewall to block main VPS IP on the sandbox.

## Checklist

### Part 1 — SSH key generation

- [ ] **S1.1** Generate a dedicated ed25519 key pair on the main VPS:
  ```bash
  mkdir -p /root/.ssh/hermes-sandbox
  ssh-keygen -t ed25519 -f /root/.ssh/hermes-sandbox/id_hermes -N "" -C "hermes-sandbox"
  ```
- [ ] **S1.2** Copy the public key to the sandbox:
  ```bash
  ssh-copy-id -i /root/.ssh/hermes-sandbox/id_hermes.pub hermes@<SANDBOX_IP>
  ```
- [ ] **S1.3** Copy the private key into the hermes_state volume (persists across rebuilds):
  ```bash
  docker exec hermes mkdir -p /workspace/.ssh
  docker cp /root/.ssh/hermes-sandbox/id_hermes hermes:/workspace/.ssh/id_hermes
  docker exec hermes chmod 600 /workspace/.ssh/id_hermes
  ```
- [ ] **S1.4** Verify key works from main VPS: `ssh -i /root/.ssh/hermes-sandbox/id_hermes hermes@<SANDBOX_IP> hostname`

### Part 2 — Dockerfile update

- [ ] **S2.1** Add `openssh-client` to `hermes/Dockerfile` apt install block.
- [ ] **S2.2** Rebuild: `docker compose -f /root/docker-compose.yml build hermes`
- [ ] **S2.3** Recreate: `docker compose -f /root/docker-compose.yml up -d --force-recreate hermes`
- [ ] **S2.4** Verify: `docker exec hermes ssh -V` → shows OpenSSH version.

### Part 3 — Configure SSH backend

- [ ] **S3.1** Add to `/root/secrets/hermes.env`:
  ```
  TERMINAL_ENV=ssh
  TERMINAL_SSH_HOST=<SANDBOX_IP>
  TERMINAL_SSH_USER=hermes
  TERMINAL_SSH_KEY=/workspace/.ssh/id_hermes
  ```
- [ ] **S3.2** Copy updated env into container and restart:
  ```bash
  docker cp /root/secrets/hermes.env hermes:/workspace/.env
  docker compose -f /root/docker-compose.yml up -d --force-recreate hermes
  ```

### Part 4 — Verify

- [ ] **S4.1** Run a command via Hermes that confirms it lands on the sandbox:
  ```bash
  docker exec hermes bash -c "TERMINAL_ENV=ssh TERMINAL_SSH_HOST=<IP> TERMINAL_SSH_USER=hermes TERMINAL_SSH_KEY=/workspace/.ssh/id_hermes hermes oneshot 'run hostname and uname -a'"
  ```
  Output must show sandbox hostname (not main VPS hostname).
- [ ] **S4.2** Confirm `apt install` works on sandbox via Hermes (e.g. `install cowsay`).
- [ ] **S4.3** Confirm main VPS filesystem is NOT accessible from Hermes SSH session.

## LOCKED ORACLE (G1)

```python
# LOCKED ORACLE — copy verbatim, do not modify assertions.
import subprocess

def run(cmd, **kw):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, **kw)
    return r.returncode, r.stdout + r.stderr

# O1: openssh-client installed in Hermes container
rc, out = run("docker exec hermes ssh -V")
assert rc == 0, f"ssh not found in hermes container: {out}"
assert "OpenSSH" in out, f"unexpected ssh -V output: {out}"
print(f"O1 PASS — {out.strip()}")

# O2: TERMINAL_ENV=ssh in hermes.env
rc, out = run("grep -q 'TERMINAL_ENV=ssh' /root/secrets/hermes.env")
assert rc == 0, "O2 FAIL — TERMINAL_ENV=ssh not found in hermes.env"
print("O2 PASS — TERMINAL_ENV=ssh set")

# O3: SSH key exists in hermes_state volume
rc, out = run("docker exec hermes test -f /workspace/.ssh/id_hermes")
assert rc == 0, "O3 FAIL — SSH key not found at /workspace/.ssh/id_hermes"
print("O3 PASS — SSH key present in hermes_state volume")

# O4: SSH connection reaches sandbox (not main VPS) — hostname must differ
import socket
main_hostname = socket.gethostname()
rc, out = run("docker exec hermes ssh -i /workspace/.ssh/id_hermes -o StrictHostKeyChecking=accept-new -o BatchMode=yes hermes@$(grep TERMINAL_SSH_HOST /root/secrets/hermes.env | cut -d= -f2) hostname")
assert rc == 0, f"O4 FAIL — SSH to sandbox failed: {out}"
sandbox_hostname = out.strip()
assert sandbox_hostname != main_hostname, f"O4 FAIL — sandbox hostname same as main VPS ({sandbox_hostname})"
print(f"O4 PASS — sandbox hostname '{sandbox_hostname}' != main VPS '{main_hostname}'")

print("\nLOCKED ORACLE: PASS")
```

## RED-proof requirement (G2)

Before S3.1 (adding `TERMINAL_ENV=ssh`), confirm O2 FAILs:
```bash
grep 'TERMINAL_ENV=ssh' /root/secrets/hermes.env  # must return nothing
```
Paste RED output. Then add config and paste GREEN.

## Asserting Verification Script (G4)

```bash
#!/bin/bash
fail=0

echo "=== O1: ssh binary in hermes container ==="
docker exec hermes ssh -V 2>&1 | grep -q "OpenSSH" && echo PASS || { echo FAIL; fail=1; }

echo "=== O2: TERMINAL_ENV=ssh in hermes.env ==="
grep -q "TERMINAL_ENV=ssh" /root/secrets/hermes.env && echo PASS || { echo FAIL; fail=1; }

echo "=== O3: SSH key in hermes_state volume ==="
docker exec hermes test -f /workspace/.ssh/id_hermes && echo PASS || { echo FAIL; fail=1; }

echo "=== O4: SSH connects to sandbox (not main VPS) ==="
SANDBOX_IP=$(grep TERMINAL_SSH_HOST /root/secrets/hermes.env | cut -d= -f2)
SANDBOX_HOST=$(docker exec hermes ssh -i /workspace/.ssh/id_hermes -o StrictHostKeyChecking=accept-new -o BatchMode=yes hermes@$SANDBOX_IP hostname 2>/dev/null)
MAIN_HOST=$(hostname)
[ -n "$SANDBOX_HOST" ] && [ "$SANDBOX_HOST" != "$MAIN_HOST" ] && echo "PASS ($SANDBOX_HOST)" || { echo "FAIL (got: $SANDBOX_HOST, main: $MAIN_HOST)"; fail=1; }

[ $fail -eq 0 ] && echo "PASS" || exit 1
```

## Acceptance Gate

- [ ] `openssh-client` in Hermes container (`ssh -V` works)
- [ ] `TERMINAL_ENV=ssh` + 3 other SSH vars in `hermes.env`
- [ ] SSH key in `/workspace/.ssh/id_hermes` (persists in hermes_state volume)
- [ ] O4: Hermes SSH session lands on sandbox, not main VPS
- [ ] `apt install` confirmed working on sandbox via Hermes
- [ ] LOCKED ORACLE PASS (verbatim, unmodified)
- [ ] Verify script ends `PASS`

## Execution

1. Complete user prerequisites P1–P3 first. Executor cannot provision the sandbox VPS.
2. Set Status: executing, commit.
3. Work checklist S1.1 → S4.3 top to bottom; tick each when success criteria met.
4. Paste RED oracle (before S3.1), then GREEN (after S3.2).
5. Run Asserting Verification Script — paste output, must end in `PASS`.
6. Set Status: done, commit.
Satisfy all five gates in `docs/EXECUTOR_CONTRACT.md`; do not modify `# LOCKED ORACLE` assertions; STOP on any deviation.
Do not redesign. If the plan is ambiguous or wrong, stop and report — do not improvise.
