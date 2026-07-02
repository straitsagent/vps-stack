# Operations

**Purpose:** Operational runbooks for the VPS stack — credential recovery, Windmill procedures, Docker rebuilds.

---

## Windmill Credential Recovery

If `$res:u/admin/gmail_smtp` or `$var:u/admin/deepseek_key` are accidentally deleted or wiped:

```bash
# Recreate gmail_smtp resource
curl -s -X POST "http://<YOUR_VPS_IP>:8080/api/w/admins/resources/create" \
  -H "Authorization: Bearer <YOUR_WINDMILL_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"path":"u/admin/gmail_smtp","resource_type":"smtp","value":{"host":"smtp.gmail.com","port":587,"username":"straitsagent@gmail.com","password":"<Gmail App Password from keys.md>","tls_implicit":false}}'

# Recreate deepseek_key variable
cd /root/windmill && wmill variable add "<Deepseek key from keys.md>" u/admin/deepseek_key --plain-secrets
```

Credentials come from `/root/secrets/keys.md` (chmod 600).

---

## Schedule YAML: Push Args to Windmill

The PostToolUse autopush hook fires on `.py` edits only, not `.schedule.yaml`. After editing a schedule YAML, push args manually:

```bash
WM_TOKEN=$(grep "WM_TOKEN" /root/agent.env | cut -d= -f2 | tr -d ' ')
curl -s -X POST "http://localhost:8080/api/w/admins/schedules/update/u%2Fadmin%2F<schedule_path>" \
  -H "Authorization: Bearer $WM_TOKEN" -H "Content-Type: application/json" \
  -d '<full_args_json>'
# To create a new schedule (not update): use /schedules/create with "path" in the body
```

---

## Pull Changes from Windmill UI

```bash
cd /root/windmill && wmill sync pull --yes
```

---

---

## Google Drive Backup (Automated)

A daily backup of non-git assets runs via systemd timer at 04:00 SGT (`drive-backup.timer`).
Git-tracked files (windmill, docs, scripts, agent, hermes, openclaw, docker-compose, etc.) are
**not** backed up here — they are recoverable from the git remote. The backup covers only what
git does not.

**What's backed up** (each to its own subfolder under the dated folder):
- `portfolio_db.sql.gz` — PostgreSQL dump of the `portfolio` database (live price_history/positions/fx_rates)
- `secrets/` — all credential/env files (gitignored by design)
- `research/` — runtime LLM output artifacts (not committed)
- `config/` — rclone.conf, drive-backup.service/timer, Claude settings + commands
- `hermes_state/` — the `root_hermes_state` Docker volume: Hermes' authoritative `/workspace/.env`,
  `config.yaml`, self-authored skills, cron jobs, and memory. Read from the host at
  `/var/lib/docker/volumes/root_hermes_state/_data`. Caches excluded (`.cache`, `.npm`, `audio_cache`,
  `node_modules`, and `skills/.hub` — the 32.5M regenerable skills-hub catalog cache).

**Auth:** rclone remote `gdrive-oauth` uses an OAuth token (rclone's built-in app) in
`/root/.config/rclone/rclone.conf`. The refresh token auto-renews; it only breaks if access is
revoked in the Google account. (A service-account approach was tried 2026-06-29 but fails —
service accounts have no personal-Drive storage quota.) See `shared/override_log.md` for history.

**Files are synced directly (no tarball).** Directories are mirrored with `rclone copy`.

**Location:** Google Drive → `<date>/` (no `vps-backup/` prefix)
**Retention:** 7 days (older dated folders auto-purged)

### Manual run

```bash
sudo bash /root/scripts/drive-backup.sh
```

### Verify latest backup

```bash
rclone lsf gdrive-oauth:$(date +%Y-%m-%d)/
```

### Restore from backup

```bash
# List available dated backups
rclone lsf gdrive-oauth: --dirs-only

# Restore the portfolio DB
TMP=$(mktemp -d)
rclone copy "gdrive-oauth:YYYY-MM-DD/portfolio_db.sql.gz" "$TMP/"
gunzip < "$TMP/portfolio_db.sql.gz" | docker exec -i root-portfolio_postgres-1 psql -U portfolio_user -d portfolio

# Restore a directory (e.g. secrets, research, or hermes_state)
rclone copy "gdrive-oauth:YYYY-MM-DD/secrets/"      /root/secrets/
rclone copy "gdrive-oauth:YYYY-MM-DD/hermes_state/" /var/lib/docker/volumes/root_hermes_state/_data/
```

### Timer management

```bash
# Check next trigger
systemctl list-timers --all | grep drive-backup

# Disable temporarily
systemctl stop drive-backup.timer
systemctl disable drive-backup.timer

# Re-enable
systemctl enable drive-backup.timer
systemctl start drive-backup.timer
```

---

## Hermes: Config & Env (read before editing)

Hermes' configuration has two layers and a security guard that commonly cause confusion.

**Env vars — two sources, `/workspace/.env` wins:**
- `/root/secrets/hermes.env` is injected as container env via `env_file:` in compose. It is a
  **fallback** — it fills in keys not otherwise set.
- `/workspace/.env` (inside the persistent `root_hermes_state` volume) is loaded by hermes-agent
  with `override=True` (`hermes_cli/env_loader.py`), so **it is the authoritative source** — its
  values win, and Hermes maintains it directly. It persists across restarts/recreates/rebuilds
  (it's in the volume, not the image) and is captured by the daily backup (`hermes_state/`).
- To change env durably: edit `/workspace/.env` (authoritative), and keep `hermes.env` in sync as
  the fallback. Plain env-var changes need a gateway restart to take effect (see below).

**`config.yaml` is guarded from agent self-modification (by design):**
- `/workspace/config.yaml` is the active config. The agent's **file-patch/write tools are refused**
  write access to it (`tools/file_tools.py::_check_sensitive_path`) so a prompt-injected agent
  cannot disable its own exec-approval. This is intentional — do not weaken it.
- Sanctioned ways to change config: `hermes config set <key> <value>` (CLI, works), or a human
  edits the file directly. The error "Refusing to write to Hermes config file" is this guard, not a bug.

**Restarting the gateway** (Hermes runs as a Docker container, NOT a systemd `--user` service):
```bash
docker compose -f /root/docker-compose.yml up -d --force-recreate hermes   # re-reads env_file
# or, to just restart without re-reading env_file:
docker compose -f /root/docker-compose.yml restart hermes
```

---

## Hermes: Nudge Inbox (send an advisory notification)

Full schema/contract: `docs/HERMES-PROTOCOL.md` §3. This is the quick how-to.

**Send one:**
```bash
python3 scripts/nudge-hermes.py \
  --source claude-code \
  --category general \
  --subject "Short subject line" \
  --urgency whenever \
  --body-file /path/to/body.md \
  --evidence "plan=docs/plans/2026-07-02_hermes-nudge-inbox.md"
```
`--category` must be `general` or `research-published` (the two currently documented in
`HERMES-PROTOCOL.md`'s "Known categories" table — extending the taxonomy is a doc change there, not a
code change). `--urgency` is one of `whenever`/`soon`/`now`. `--evidence` is repeatable, `TYPE=REF`.
Prints the written path on success; exits 1 with a message on stderr if any field is invalid.

**Check what's live vs. already read:**
```bash
ls /root/docs/hermes/inbox/            # unprocessed — Hermes hasn't consumed these yet
ls /root/docs/hermes/inbox/processed/  # already read and moved by Hermes (or by hand during verification)
```

**Nothing pushes to Hermes.** A nudge sitting in `inbox/` is invisible until Hermes' own self-authored
cron job polls the directory (§4 of the protocol doc) — there is no interrupt/webhook. As of 2026-07-02,
Hermes has not yet self-authored that polling job; see `docs/HERMES-PROTOCOL.md` §4 for the message to
send it.

---

## OpenClaw: Multi-Provider LLM Setup

OpenClaw (`@StraitsClawBot`) uses a 3-provider fallback chain to avoid OpenAI
rate limits. Config at `/root/openclaw/config/openclaw.json` (mounted `:ro`).

**Fallback order:** `openai/gpt-5.4-mini` → `openai/gpt-5.4` → `xai/grok-4.3` →
`deepseek/deepseek-chat`.

**API keys** are in `/root/secrets/openclaw.env` (chmod 600):
- `OPENAI_API_KEY` (primary, baked in image)
- `XAI_API_KEY` (xAI Grok, baked in image)
- `DEEPSEEK_API_KEY` (Deepseek via custom `models.providers` config)

**After key/config changes:**
```bash
docker compose up -d --force-recreate openclaw
```

**Deepseek provider** is configured as a custom provider in `openclaw.json`
(`models.providers.deepseek`). No plugin install is needed; the config uses
the bundled `openai-completions` API transport against `api.deepseek.com`.

**Recovery** (if `/workspace` volume is wiped): key/config changes are safe on
the bind-mounted `/root/openclaw/config/` and `/root/secrets/openclaw.env`.
Just recreate the container. The gateway auto-detects the custom provider.

---

## Docker: Rebuild Agent Container

After agent code changes in `/root/agent/`:

```bash
cd /root && docker compose up -d straitsagent
# Run tests:
docker exec root-straitsagent-1 python -m pytest tests/ -v
```
