import imaplib
import email
import re
import smtplib
from email.header import decode_header
from email.utils import parsedate_to_datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone
from typing import TypedDict
from openai import OpenAI


class smtp(TypedDict):
    host: str
    port: int
    username: str
    password: str
    tls_implicit: bool


def decode_str(s):
    if not s:
        return ""
    parts = decode_header(s)
    result = []
    for part, charset in parts:
        if isinstance(part, bytes):
            result.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            result.append(str(part))
    return "".join(result)


def get_body(msg):
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain":
                try:
                    body = part.get_payload(decode=True).decode(
                        part.get_content_charset() or "utf-8", errors="replace"
                    )
                    break
                except Exception:
                    pass
            elif ct == "text/html" and not body:
                try:
                    html = part.get_payload(decode=True).decode(
                        part.get_content_charset() or "utf-8", errors="replace"
                    )
                    body = re.sub(r"<[^>]+>", " ", html)
                    body = re.sub(r"\s+", " ", body).strip()
                except Exception:
                    pass
    else:
        try:
            body = msg.get_payload(decode=True).decode(
                msg.get_content_charset() or "utf-8", errors="replace"
            )
        except Exception:
            pass
    return body[:2000]


def main(
    smtp_resource: smtp,
    deepseek_key: str,
    recipient_email: str = "",
    hours_back: int = 24,
):
    username = smtp_resource["username"]
    password = smtp_resource["password"]

    # --- Fetch emails via IMAP ---
    imap = imaplib.IMAP4_SSL("imap.gmail.com", 993)
    imap.login(username, password)
    imap.select("INBOX")

    # SINCE is date-only — search a day wider, then filter by exact timestamp
    since_date = (datetime.now(timezone.utc) - timedelta(hours=hours_back + 24)).strftime("%d-%b-%Y")
    _, nums = imap.search(None, f"(SINCE {since_date})")

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    emails = []

    for num in nums[0].split():
        _, data = imap.fetch(num, "(RFC822)")
        msg = email.message_from_bytes(data[0][1])

        date_str = msg.get("Date", "")
        try:
            msg_date = parsedate_to_datetime(date_str)
            if msg_date.tzinfo is None:
                msg_date = msg_date.replace(tzinfo=timezone.utc)
            if msg_date < cutoff:
                continue
        except Exception:
            continue

        emails.append({
            "from": decode_str(msg.get("From", "")),
            "subject": decode_str(msg.get("Subject", "(no subject)")),
            "time": msg_date.strftime("%H:%M"),
            "body": get_body(msg),
        })

    imap.logout()

    if not emails:
        return {"status": "no emails", "count": 0}

    # --- Summarise with Deepseek ---
    emails_text = "\n\n".join([
        f"From: {e['from']}\nSubject: {e['subject']}\nTime: {e['time']}\n{e['body']}"
        for e in emails
    ])

    client = OpenAI(api_key=deepseek_key, base_url="https://api.deepseek.com")

    prompt = f"""You are helping the owner review their inbox.

{len(emails)} emails received in the last {hours_back} hours:

{emails_text}

Write a concise inbox summary with these sections:
1. **Overview** — total count, key senders, main themes
2. **Action Required** — emails needing a reply or decision (bullet list, be specific)
3. **FYI** — newsletters, notifications, no action needed (one line each)
4. **Quick Hits** — any other notable items

Be direct and professional. Skip obvious spam."""

    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1000,
    )
    summary = response.choices[0].message.content

    # --- Send summary email ---
    today = datetime.now().strftime("%d %b %Y")
    html_summary = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", summary)
    html_summary = html_summary.replace("\n", "<br>")

    html_body = f"""<html><body style="font-family:Arial,sans-serif;max-width:650px;margin:auto;color:#333;">
<h2 style="color:#1a1a2e;border-bottom:2px solid #eee;padding-bottom:8px;">Inbox Summary — {today}</h2>
<p style="color:#888;font-size:13px;">{len(emails)} emails · last {hours_back}h</p>
<div style="line-height:1.7;font-size:14px;">{html_summary}</div>
<hr style="margin-top:30px;border:none;border-top:1px solid #eee;">
<p style="color:#bbb;font-size:11px;">Windmill · straitsagent@gmail.com</p>
</body></html>"""

    out = MIMEMultipart("alternative")
    out["Subject"] = f"Inbox Summary — {today} | {len(emails)} messages"
    out["From"] = username
    out["To"] = recipient_email
    out.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP(smtp_resource["host"], smtp_resource["port"]) as server:
        server.starttls()
        server.login(username, password)
        server.sendmail(username, recipient_email, out.as_string())

    return {"status": "sent", "emails_summarised": len(emails), "recipient": recipient_email}
