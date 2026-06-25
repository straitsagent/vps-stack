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

Credentials come from `/root/shared/keys.md` (chmod 600).

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

## Docker: Rebuild Agent Container

After agent code changes in `/root/agent/`:

```bash
cd /root && docker compose up -d straitsagent
# Run tests:
docker exec root-straitsagent-1 python -m pytest tests/ -v
```
