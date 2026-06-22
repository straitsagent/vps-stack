#!/usr/bin/env python3
"""
Host-level deadman switch for the Windmill health check.
Runs at 08:30 SGT (30 min after the brief). If Windmill is unreachable or
the health_check_daily job did not succeed recently, fires a Telegram alert
DIRECTLY — no Windmill dependency.

Reads from /root/agent.env: WM_TOKEN, TELEGRAM_BOT_TOKEN, TELEGRAM_OWNER_ID
"""
import os
import sys
import json
import logging
from datetime import datetime, timezone, timedelta

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
log = logging.getLogger(__name__)

WINDMILL_BASE = "http://localhost:8080"
WORKSPACE     = "admins"
SCHEDULE_PATH = "u/admin/health_check_daily"
MAX_AGE_MIN   = 90  # alert if newest success job is older than this


def _load_env(path: str = "/root/agent.env") -> dict:
    env = {}
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    env[k.strip()] = v.strip()
    except FileNotFoundError:
        log.error(f"agent.env not found at {path}")
    return env


def _fetch_recent_jobs(wm_token: str) -> tuple[bool, list]:
    """Return (api_ok, jobs_list). api_ok=False means the API was unreachable."""
    import urllib.request
    import urllib.parse
    url = (
        f"{WINDMILL_BASE}/api/w/{WORKSPACE}/jobs/completed/list"
        f"?schedule_path={urllib.parse.quote(SCHEDULE_PATH)}&per_page=1"
    )
    try:
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {wm_token}"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            jobs = json.loads(resp.read())
        return True, jobs
    except Exception as exc:
        log.warning(f"[Deadman] API call failed: {exc}")
        return False, []


def _should_alert(api_ok: bool, jobs: list, now: datetime) -> tuple[bool, str]:
    """
    Pure decision function — unit-testable with no I/O.
    Returns (should_alert: bool, reason: str).
    """
    if not api_ok:
        return True, "Windmill API unreachable from host — stack may be down."

    if not jobs:
        return True, "Health check has never run — no completed jobs found."

    job = jobs[0]
    if not job.get("success"):
        return True, f"Health check last run FAILED (job_id={job.get('id', '?')})."

    started_at_str = job.get("started_at", "")
    try:
        started_at = datetime.fromisoformat(started_at_str.replace("Z", "+00:00"))
        age_min = (now - started_at).total_seconds() / 60
        if age_min > MAX_AGE_MIN:
            return True, (
                f"Health check last succeeded {int(age_min)}m ago "
                f"(threshold: {MAX_AGE_MIN}m) — may have missed the 08:00 run."
            )
    except Exception as exc:
        log.warning(f"[Deadman] Could not parse started_at '{started_at_str}': {exc}")
        return True, "Health check job timestamp unparseable — cannot verify recency."

    return False, ""


def _send_telegram_alert(bot_token: str, owner_id: str, reason: str) -> None:
    import urllib.request
    text = f"⚠️ *Health Check Deadman Alert*\n\n{reason}"
    payload = json.dumps({"chat_id": owner_id, "text": text, "parse_mode": "Markdown"}).encode()
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        result = json.loads(resp.read())
    if not result.get("ok"):
        log.error(f"[Deadman] Telegram API error: {result}")
    else:
        log.info("[Deadman] Telegram alert sent.")


def main():
    env = _load_env()
    wm_token   = env.get("WM_TOKEN", "")
    bot_token  = env.get("TELEGRAM_BOT_TOKEN", "")
    owner_id   = env.get("TELEGRAM_OWNER_ID", "")

    if not wm_token:
        log.error("[Deadman] WM_TOKEN not found in agent.env — cannot check Windmill.")
        sys.exit(1)

    api_ok, jobs = _fetch_recent_jobs(wm_token)
    now = datetime.now(timezone.utc)
    should_alert, reason = _should_alert(api_ok, jobs, now)

    if should_alert:
        log.warning(f"[Deadman] Alerting: {reason}")
        if bot_token and owner_id:
            try:
                _send_telegram_alert(bot_token, owner_id, reason)
            except Exception as exc:
                log.error(f"[Deadman] Telegram send failed: {exc}")
        else:
            log.error("[Deadman] TELEGRAM_BOT_TOKEN / TELEGRAM_OWNER_ID missing — cannot alert.")
        sys.exit(2)
    else:
        log.info("[Deadman] Health check is recent and healthy — no alert needed.")
        sys.exit(0)


if __name__ == "__main__":
    main()
