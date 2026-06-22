import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
log = logging.getLogger(__name__)


def _deepseek_diagnose(path: str, error: str, deepseek_key: str) -> str:
    """Return a 1-line root-cause diagnosis from Deepseek, or '' on failure."""
    if not deepseek_key:
        return ""
    try:
        import requests
        r = requests.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {deepseek_key}",
                     "Content-Type": "application/json"},
            json={
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system",
                     "content": ("You are a DevOps engineer. Respond with a single sentence "
                                 "stating the most likely root cause. No preamble.")},
                    {"role": "user",
                     "content": f"Script: {path}\nError: {error[:300]}"},
                ],
                "temperature": 0.1,
                "max_tokens": 60,
            },
            timeout=10,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        log.warning(f"[ErrorAlert] Deepseek diagnosis failed: {exc}")
        return ""


def _send_telegram(bot_token: str, owner_id: str, path: str,
                   job_id: str, error: str, diagnosis: str) -> None:
    """Fire Telegram alert. Best-effort — never raises."""
    if not bot_token or not owner_id:
        return
    try:
        import requests
        diag_line = f"\n\n🔍 *Diagnosis:* {diagnosis}" if diagnosis else ""
        text = (
            f"🚨 *Windmill job failed*\n\n"
            f"*Script:* `{path}`\n"
            f"*Job ID:* `{job_id}`\n"
            f"*Error:* {error[:200]}"
            f"{diag_line}"
        )
        requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": owner_id, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        ).raise_for_status()
        log.info(f"[ErrorAlert] Telegram alert sent for {path}")
    except Exception as exc:
        log.warning(f"[ErrorAlert] Telegram send failed: {exc}")


def main(
    smtp_resource: dict,
    path: str,
    job_id: str,
    error: str,
    recipient_email: str = "",
    email: str = "",
    schedule_path: str = "",
    started_at: str = "",
    workspace_id: str = "",
    telegram_bot_token: str = "",
    telegram_owner_id: str = "",
    deepseek_key: str = "",
):
    triggered_by = schedule_path if schedule_path else (email or "manual")

    body = f"""A Windmill job has failed.

Script/Flow: {path}
Job ID:      {job_id}
Triggered by:{triggered_by}
Started at:  {started_at}
Workspace:   {workspace_id}

Error:
{error}

View job in Windmill: job ID {job_id}, workspace {workspace_id}
"""

    msg = MIMEMultipart()
    msg["Subject"] = f"[Windmill] FAILED: {path}"
    msg["From"] = smtp_resource["username"]
    msg["To"] = recipient_email
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP(smtp_resource["host"], smtp_resource["port"]) as server:
        server.starttls()
        server.login(smtp_resource["username"], smtp_resource["password"])
        server.send_message(msg)

    log.info(f"[ErrorAlert] Email sent for {path}")

    # Telegram + Deepseek diagnosis — best-effort, must not block email delivery
    diagnosis = _deepseek_diagnose(path, error, deepseek_key)
    _send_telegram(telegram_bot_token, telegram_owner_id, path, job_id, error, diagnosis)

    return {"alerted": True, "job_id": job_id, "path": path}
