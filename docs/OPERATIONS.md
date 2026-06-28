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

A daily backup of the portfolio DB + uncommitted files runs via systemd timer at 04:00 SGT.

**What's backed up:**
- PostgreSQL dump of the `portfolio` database
- `research/` output artifacts
- Untracked Windmill files (new scripts, utils)
- Credential files (`.env`, `secrets/keys.md`, `secrets/windmill-sa-key.json`)
- rclone config

**Location:** Google Drive → `vps-backup/YYYY-MM-DD/`
**Retention:** 7 days (older folders auto-purged)

### Manual run

```bash
sudo bash /root/scripts/drive-backup.sh
```

### Verify latest backup

```bash
rclone ls gdrive-oauth:vps-backup/$(date +%Y-%m-%d)/
```

### Restore from backup

```bash
# List available backups
rclone lsf gdrive-oauth:vps-backup/

# Download a specific date's backup
TMP=$(mktemp -d)
rclone copy "gdrive-oauth:vps-backup/YYYY-MM-DD/uncommitted.tar.gz" "$TMP/"
rclone copy "gdrive-oauth:vps-backup/YYYY-MM-DD/portfolio_db.sql.gz" "$TMP/"
# Extract files
tar xzf "$TMP/uncommitted.tar.gz" -C /root
# Restore DB
gunzip < "$TMP/portfolio_db.sql.gz" | docker exec -i root-portfolio_postgres-1 psql -U portfolio_user -d portfolio
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
