# VPS Resource Audit — 2026-06-10

**Host:** Contabo VPS, <YOUR_VPS_IP>  
**OS:** Ubuntu 24.04  
**Uptime at time of audit:** 35 days  
**Audited by:** Claude Code

---

## Hardware

| Resource | Spec |
|---|---|
| CPU | AMD EPYC Processor (with IBPB), 8 vCPUs |
| RAM | 24 GB |
| Swap | None configured |
| Disk | 193 GB SSD (`/dev/sda1`) |

---

## Running Containers (13 total)

| Container | Image | Status | Uptime |
|---|---|---|---|
| `root-straitsagent-1` | `root-straitsagent` | Running | ~5 min (freshly restarted) |
| `root-windmill_server-1` | `windmill` | Running | 2 weeks |
| `root-windmill_worker-1/2/3` | `windmill` | Running | 2 days |
| `root-windmill_worker_native-1` | `windmill` | Running | 2 weeks |
| `root-windmill_extra-1` | `windmill-extra` | Running | 2 weeks |
| `root-db-1` | `postgres:16` (Windmill DB) | Running, healthy | 2 weeks |
| `root-portfolio_postgres-1` | `postgres:16` (Portfolio DB) | Running, healthy | 6 days |
| `root-dind-1` | `docker:dind` | Running, healthy | 2 weeks |
| `root-caddy-1` | `windmill caddy-l4` | Running | ~5 min |
| `n8n-caddy-1` | `caddy:2` | Running | ~5 min |
| `n8n-n8n-1` | `n8nio/n8n:stable` | Running | 4 weeks |

---

## CPU

| Metric | Value |
|---|---|
| Load average (1m / 5m / 15m) | 2.33 / 1.75 / 1.59 |
| Host idle | 76.6% |
| Active usage | ~23% across 8 cores |

**Per-container CPU at snapshot:**

| Container | CPU % |
|---|---|
| `root-db-1` (Windmill Postgres) | 26.4% — elevated; consistent with Windmill logging + job state writes |
| `root-windmill_worker-1` | 6.2% |
| `root-windmill_worker-3` | 6.0% |
| `root-windmill_worker-2` | 5.6% |
| `root-windmill_worker_native-1` | 4.1% |
| `root-windmill_server-1` | 3.0% |
| `root-straitsagent-1` | 0.6% |
| `n8n-n8n-1` | 0.5% |
| `n8n-caddy-1` | 0.2% |
| `root-dind-1` | 0.1% |
| All others | <0.1% each |

**Assessment:** Comfortable. 76% idle headroom on 8 cores. Windmill workers hold ~22% collectively as steady-state polling overhead — this is normal, not active job execution.

---

## RAM

| Metric | Value |
|---|---|
| Total | 24 GB |
| Used | 3.3 GB |
| Buff/cache | 3.2 GB |
| **Available** | **~20 GB (83% free)** |
| Swap | None |

**Per-container RAM:**

| Container | RAM Used |
|---|---|
| `root-db-1` (Windmill Postgres) | 609 MB |
| `n8n-n8n-1` | 294 MB |
| `root-dind-1` | 230 MB |
| `root-windmill_server-1` | 260 MB |
| `root-windmill_extra-1` | 63 MB |
| `root-straitsagent-1` | 44 MB |
| `root-windmill_worker_native-1` | 38 MB |
| `root-windmill_worker-2` | 36 MB |
| `root-windmill_worker-1/3` | ~33 MB each |
| `root-portfolio_postgres-1` | 30 MB |
| `root-caddy-1` | 11 MB |
| `n8n-caddy-1` | 11 MB |
| **Total (containers)** | **~1.7 GB** |

Note: Windmill workers are capped at `2 GiB` each (configured memory limit).

**Assessment:** Very healthy. 20 GB available. No swap is a minor risk — an OOM event has no safety net — but current usage is far below the threshold where this matters.

---

## Disk

| Metric | Value |
|---|---|
| Total | 193 GB |
| Used | 34 GB (18%) |
| **Free** | **160 GB (82%)** |

**Breakdown:**

| Item | Size |
|---|---|
| Docker images (14 images, 10 active) | 21.7 GB |
| Docker build cache | 1.4 GB |
| `root_worker_dependency_cache` volume (pip/npm packages) | 618 MB |
| `root_lsp_cache` volume (language server cache) | 248 MB |
| `root_db_data` volume (Windmill Postgres data) | 86 MB |
| `root_portfolio_db_data` volume (Portfolio Postgres data) | 47 MB |
| `root_worker_logs` volume | 1.2 MB |
| `root_caddy_data` volume | 20 KB |
| `root_windmill_index` volume | 4 KB |
| `root_baileys_auth` volume (orphan — safe to remove) | 168 KB |
| Windmill scripts (`/root/windmill/`) | 1.5 MB |
| Agent code (`/root/agent/`) | 100 KB |
| Research files (`/root/research/`) | 100 KB |

**Windmill Postgres DB size:** 30 MB  
**Portfolio Postgres DB size:** 47 MB (table breakdown below)

**Portfolio DB tables:**

| Table | Size |
|---|---|
| `research_reports` | 240 KB |
| `fundamental_data` | 112 KB |
| `price_history` | 80 KB |
| `agent_pending_jobs` | 64 KB |
| `agent_conversation_history` | 48 KB |
| `fx_rates` | 48 KB |
| `portfolio_positions` | 48 KB |
| `agent_audit_log` | 32 KB |
| `agent_draft_queue` | 32 KB |
| `agent_contact_rules` | 24 KB |
| `agent_pending_confirmations` | 24 KB |

**Assessment:** No concern. 160 GB free. Portfolio DB is tiny; Windmill DB is small. The 21 GB of Docker images dominates — this grows slowly as images are updated and old layers accumulate, but is manageable.

---

## Network

Cumulative since last boot (35 days):

| Interface | RX | TX |
|---|---|---|
| `eth0` (host) | 19.6 GB | 2.6 GB |

The Windmill worker and native worker containers show the highest lifetime network I/O (~8–15 GB each) — this reflects pulling Python packages, fetching RSS/API data in scripts, and Windmill internal RPC. Normal for a workflow platform running daily scripts.

---

## Observations and Flags

### ⚠️ No swap configured
If a workload causes RAM to spike beyond 24 GB, the Linux OOM killer will terminate processes with no warning. Current usage (3.3 GB) is well below the threshold, but worth monitoring if heavier workloads are added (e.g. large in-memory research jobs, vector embeddings).

### 🔍 `root-db-1` CPU elevated at snapshot
Windmill's internal Postgres consistently shows 20–30% CPU in snapshots. This is expected behaviour — Windmill writes job logs, execution state, and worker heartbeats continuously. Not a problem, but worth noting as the baseline so anomalies stand out.

### 📦 `root_baileys_auth` volume is an orphan
The Baileys bridge was removed (2026-06-10) but its Docker volume remains. Safe to delete:
```bash
docker volume rm root_baileys_auth
```

### 💤 n8n is running idle
`n8n-n8n-1` uses 294 MB RAM and ~0.5% CPU continuously despite not being actively used. Not causing any resource pressure at current levels, but represents avoidable overhead.

---

## Headroom Summary

| Resource | Used | Available | Assessment |
|---|---|---|---|
| CPU (8 vCPUs) | ~23% | ~77% | ✅ Comfortable — room for several more workers or workflows |
| RAM (24 GB) | 3.3 GB | ~20 GB | ✅ Very healthy — could run 5–6× current load |
| Disk (193 GB) | 34 GB | 160 GB | ✅ No concern |
| Swap | 0 | 0 | ⚠️ None — OOM has no safety net |
