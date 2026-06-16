import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
log = logging.getLogger(__name__)


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

    return {"alerted": True, "job_id": job_id, "path": path}
