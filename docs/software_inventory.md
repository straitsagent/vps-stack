# Installed Software Inventory
**Last updated:** 2026-06-09
**Server:** Contabo VPS (Ubuntu 24.04)

## 1. Core System & Infrastructure
| Software | Version | Purpose |
| :--- | :--- | :--- |
| **Ubuntu** | 24.04 LTS | Operating System |
| **Systemd** | 255 | System and Service Manager |
| **UFW** | 0.36.2 | Uncomplicated Firewall (Inactive by policy) |
| **Docker** | 29.4.2 | Container runtime |
| **Docker Compose** | v5.1.3 | Container orchestration |

## 2. Runtimes & Languages
| Software | Version | Purpose |
| :--- | :--- | :--- |
| **Python** | 3.12.3 | Primary script language (Windmill/Local) |
| **Node.js** | v22.22.2 | JavaScript runtime |
| **npm** | 10.9.7 | Node package manager |

## 3. Applications & Automation
| Software | Version | Status | Purpose |
| :--- | :--- | :--- | :--- |
| **Windmill** | Latest (Docker) | Running (8080) | Primary Orchestration Platform |
| **n8n** | Latest (Docker) | Running (80/443) | Secondary Automation (Legacy) |
| **PostgreSQL** | 16 (Docker) | Running (Internal) | Portfolio Data Layer |
| **Caddy** | Latest (Docker) | Running | Reverse Proxy for n8n |

## 4. Development & CLI Tools
| Software | Version | Purpose |
| :--- | :--- | :--- |
| **Aider** | 0.86.2 | AI pair programming CLI (Installed 2026-06-09 via pipx) |
| **Git** | 2.43.0 | Version control |
| **Tmux** | 3.4 | Terminal multiplexer (Persistent sessions: `gw` for Gemini Workspace, `cr` for Claude Remote) |
| **Pipx** | 1.4.3 | Isolated Python tool manager (Installed 2026-06-09) |
| **gcloud SDK** | 571.0.0 | Google Cloud CLI (Authenticated as straitsagent@gmail.com) |
| **Windmill CLI** | latest | `wmill` CLI for script synchronization |

## 5. Maintenance History
*   **2026-06-09:** Installed `pipx` and `aider-chat`. Configured `OPENROUTER_API_KEY` in `/root/.bashrc`.
*   **2026-06-09:** Conducted full codebase audit and documented in `/root/docs/audit/`.
*   **2026-06-03:** Initial setup of Windmill, PostgreSQL, and Portfolio seed data.
