# VPS Automation Stack

**Owner:** ${OWNER_NAME}  
**Platform:** Windmill at `http://<YOUR_VPS_IP>:8080`  
**Server:** Contabo VPS, Ubuntu 24.04, root@<YOUR_VPS_IP>

Personal automation stack delivering daily intelligence and productivity workflows to Gmail and Telegram, orchestrated through Windmill.

---

## Architecture

- **Windmill** is the only orchestration platform. All workflows are scheduled and run here.
- **Email** is the delivery layer. All workflow outputs go to Gmail — no dashboards.
- **PostgreSQL** is the data layer. Portfolio positions, price history, FX rates, and agent state live in a local Postgres container (`portfolio_postgres`).
- **Telegram Agent** (`straitsagent`) is the interactive layer. FastAPI service answering portfolio, research, and digest queries via Telegram bot.

---

## Services

| Service | Port | Notes |
|---|---|---|
| Windmill | 8080 | Primary orchestration — 17 scheduled workflows |
| PostgreSQL | 5432 (internal) | Portfolio Intelligence System — 29 tables |
| Telegram Agent | 8001 (internal) | FastAPI, Caddy reverse proxy, Telegram webhook |
| n8n | 80/443 | Kept running, not actively used |

---

## Key Paths

| Path | Purpose |
|---|---|
| `/root/docker-compose.yml` | Full service stack (Windmill, Postgres, Agent, Caddy) |
| `/root/windmill/u/admin/` | Windmill scripts — git source of truth |
| `/root/agent/` | Telegram agent service (FastAPI) |
| `/root/portfolio/schema.sql` | Full DB schema — 29 tables |
| `/root/portfolio/seed.sql` | 33 seed positions |
| `/root/shared/keys.md` | All API keys (chmod 600, never commit) |
| `/root/shared/override_log.md` | Manual intervention log |
| `/root/research/` | Workflow output files (news, portfolio, youtube, earnings) |

---

## Documentation

| File | Purpose |
|---|---|
| [CLAUDE.md](CLAUDE.md) | Claude Code session context — read this first |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Full workflow build status, Windmill resources, Telegram agent inventory |
| [docs/WORKFLOW_ARCHITECTURE.md](docs/WORKFLOW_ARCHITECTURE.md) | Per-workflow pseudocode specs |
| [docs/earnings_report_standards.md](docs/earnings_report_standards.md) | 6 mandatory standards for earnings analysis reports |
| [docs/design/2026-06-13_portfolio-rationalization-framework.md](docs/design/2026-06-13_portfolio-rationalization-framework.md) | Portfolio rationalization design (v1.2) — 5-factor scoring, 4 scenarios |
| [docs/design/2026-06-15_portfolio-candidate-eval-framework.md](docs/design/2026-06-15_portfolio-candidate-eval-framework.md) | Portfolio candidate evaluation design (v1.1) — 3-gate ADD/WATCH/PASS verdict |

---

## Quick Start (Claude Code Sessions)

```
Read CLAUDE.md and docs/ROADMAP.md in /root/. We are working on [Phase X / workflow name]. Begin.
```
