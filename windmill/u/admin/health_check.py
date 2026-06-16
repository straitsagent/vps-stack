# Requirements:
# pytz>=2024.1

import os, json, smtplib, imaplib, urllib.request, urllib.parse
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.header import decode_header
from email.utils import parsedate_to_datetime
import pytz
import logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
log = logging.getLogger(__name__)


WORKSPACE   = "admins"
WM_BASE_URL = os.environ.get("WM_BASE_URL", "http://windmill_server:8000")
IMAP_HOST   = "imap.gmail.com"
GREEN  = "#1a7f37"
RED    = "#cf222e"
GRAY   = "#666"
ORANGE = "#e36209"

# email_match: keywords that ALL must appear in subject to count as sent by this schedule
# email_expect: expected count in 24h. None = variable (no flag if 0)
SCHEDULES = [
    {"path": "u/admin/morning_news_digest",             "label": "Morning News Digest",         "max_age_h": 26, "has_llm": True,  "llm_aggregate": False, "weekday_only": False, "email_match": ["Morning Digest"],           "email_expect": 1},
    {"path": "u/admin/portfolio_price_fetcher_daily",   "label": "Portfolio Price Fetcher (AM)", "max_age_h": 26, "has_llm": False, "llm_aggregate": False, "weekday_only": True,  "email_match": None,                         "email_expect": None},
    {"path": "u/admin/portfolio_email_daily",           "label": "Portfolio Email (AM)",         "max_age_h": 26, "has_llm": False, "llm_aggregate": False, "weekday_only": True,  "email_match": ["Portfolio", "US Close"],     "email_expect": 1},
    {"path": "u/admin/portfolio_price_fetcher_evening", "label": "Portfolio Price Fetcher (PM)", "max_age_h": 26, "has_llm": False, "llm_aggregate": False, "weekday_only": True,  "email_match": None,                         "email_expect": None},
    {"path": "u/admin/portfolio_email_evening",         "label": "Portfolio Email (PM)",         "max_age_h": 26, "has_llm": False, "llm_aggregate": False, "weekday_only": True,  "email_match": ["Portfolio", "Asia Close"],   "email_expect": 1},
    {"path": "u/admin/youtube_monitor_hourly",          "label": "YouTube Monitor (hourly)",     "max_age_h": 2,  "has_llm": True,  "llm_aggregate": True,  "weekday_only": False, "email_match": ["YouTube Digest"],            "email_expect": None},
]

# Additional sent-mail categories shown in the Sent Mail summary (not tied to a schedule)
EXTRA_CATEGORIES = [
    {"label": "Health Check",   "keywords": ["Health Check"]},
    {"label": "Windmill Error", "keywords": ["Windmill Error"]},
]


def wmill_get(path, token):
    url = f"{WM_BASE_URL}/api/{path}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def fmt_age(delta):
    secs = int(delta.total_seconds())
    if secs < 3600:
        return f"{secs // 60}m ago"
    h = secs // 3600
    m = (secs % 3600) // 60
    return f"{h}h {m}m ago" if m else f"{h}h ago"


def decode_subject(raw_subject):
    parts = decode_header(raw_subject or "")
    result = ""
    for part, enc in parts:
        if isinstance(part, bytes):
            result += part.decode(enc or "utf-8", errors="replace")
        else:
            result += part
    return result


def fetch_sent_subjects(gmail_smtp, hours=25):
    """Return list of email subjects sent in the last N hours from Gmail Sent folder."""
    conn = imaplib.IMAP4_SSL(IMAP_HOST)
    try:
        conn.login(gmail_smtp["username"], gmail_smtp["password"])
        # Try standard Gmail sent folder; fall back to "Sent"
        for folder in ('"[Gmail]/Sent Mail"', "Sent"):
            status, _ = conn.select(folder, readonly=True)
            if status == "OK":
                break

        cutoff_utc = datetime.now(timezone.utc) - timedelta(hours=hours)
        since_str = cutoff_utc.strftime("%d-%b-%Y")
        _, msg_ids = conn.search(None, f"SINCE {since_str}")

        subjects = []
        if not msg_ids or not msg_ids[0]:
            return subjects

        for mid in msg_ids[0].split():
            _, data = conn.fetch(mid, "(RFC822.HEADER)")
            if not data or not data[0]:
                continue
            raw = data[0][1] if isinstance(data[0], tuple) else data[0]
            import email as email_lib
            msg = email_lib.message_from_bytes(raw)

            # Filter precisely to cutoff by parsing Date header
            try:
                sent_at = parsedate_to_datetime(msg.get("Date", ""))
                if sent_at.tzinfo is None:
                    sent_at = sent_at.replace(tzinfo=timezone.utc)
                if sent_at < cutoff_utc:
                    continue
            except Exception:
                pass  # include if date unparseable

            subjects.append(decode_subject(msg.get("Subject", "")))

        return subjects
    finally:
        try:
            conn.logout()
        except Exception as _exc:
            log.warning("Suppressed: %s", _exc)


def count_matching(subjects, keywords):
    """Count subjects where ALL keywords appear (case-insensitive)."""
    return sum(1 for s in subjects if all(kw.lower() in s.lower() for kw in keywords))


def build_html(rows, now_sgt, ok_count, total, llm_rows, total_prompt, total_completion,
               total_cost, sent_subjects, extra_categories):
    date_str = now_sgt.strftime("%A, %-d %B %Y")
    time_str = now_sgt.strftime("%-I:%M %p SGT")
    all_ok = ok_count == total
    summary_color = GREEN if all_ok else RED
    summary_text = (f"All {total} OK" if all_ok
                    else f"{total - ok_count} issue{'s' if (total - ok_count) > 1 else ''}")

    # ── Status table ─────────────────────────────────────────────────────────
    table_rows = ""
    for row in rows:
        if row["status"] == "OK":
            icon, status_html = "✅", f'<span style="color:{GREEN}">OK</span>'
        elif row["status"] == "FAILED":
            icon, status_html = "❌", f'<span style="color:{RED}">FAILED</span>'
        else:
            icon, status_html = "⚠️", f'<span style="color:{ORANGE}">STALE</span>'

        error_html = (f'<br><span style="color:{GRAY};font-size:11px">{row["error"]}</span>'
                      if row.get("error") else "")

        # Email column
        ec = row.get("email_count")
        ee = row.get("email_expect")
        yt_label = row.get("yt_sent_label", "")
        if row.get("email_match") is None:
            email_cell = f'<span style="color:{GRAY}">—</span>'
        elif yt_label:
            email_cell = f'<span style="color:{GRAY}">{yt_label}</span>'
        elif ec is not None and ee is not None:
            if row["status"] == "OK" and ec < ee:
                email_cell = f'<span style="color:{RED}">⚠ {ec} sent</span>'
            else:
                check = "✅" if ec >= ee else ""
                email_cell = f'{check} <span style="color:{GRAY}">{ec} sent</span>'
        else:
            email_cell = f'<span style="color:{GRAY}">—</span>'

        table_rows += f"""
        <tr style="border-bottom:1px solid #f0f0f0">
          <td style="padding:7px 10px;font-size:15px">{icon}</td>
          <td style="padding:7px 12px;font-size:14px">{row['label']}{error_html}</td>
          <td style="padding:7px 12px;font-size:14px;color:{GRAY};white-space:nowrap">{row.get('last_run','—')}</td>
          <td style="padding:7px 12px;font-size:14px">{status_html}</td>
          <td style="padding:7px 12px;font-size:14px;color:{GRAY};white-space:nowrap">{row.get('age_str','—')}</td>
          <td style="padding:7px 12px;font-size:14px;white-space:nowrap">{email_cell}</td>
        </tr>"""

    # ── Token usage section ──────────────────────────────────────────────────
    llm_section = ""
    if llm_rows:
        llm_rows_html = ""
        for r in llm_rows:
            extra = f' <span style="color:{GRAY};font-size:11px">({r["sent_runs"]} of {r["total_runs"]} runs sent emails)</span>' if "sent_runs" in r else ""
            llm_rows_html += f"""
          <tr>
            <td style="padding:3px 20px 3px 0;font-size:13px;color:{GRAY}">{r['label']}{extra}</td>
            <td style="padding:3px 16px;font-size:13px">{r['prompt']:,} prompt + {r['completion']:,} completion</td>
            <td style="padding:3px 0;font-size:13px;color:{GRAY}">est. ${r['cost']:.4f}</td>
          </tr>"""
        llm_section = f"""
      <h3 style="margin:28px 0 8px;font-size:12px;color:{GRAY};letter-spacing:0.08em;text-transform:uppercase">
        Token Usage — Last 24h
      </h3>
      <table style="border-collapse:collapse;font-family:monospace">
        {llm_rows_html}
        <tr style="border-top:1px solid #e0e0e0">
          <td style="padding:7px 20px 3px 0;font-size:13px;font-weight:bold">TOTAL</td>
          <td style="padding:7px 16px;font-size:13px;font-weight:bold">{total_prompt:,} prompt + {total_completion:,} completion</td>
          <td style="padding:7px 0;font-size:13px;font-weight:bold">est. ${total_cost:.4f}</td>
        </tr>
      </table>"""

    # ── Sent mail section ────────────────────────────────────────────────────
    sent_rows_html = ""
    sent_total = 0
    for row in rows:
        if row.get("email_match") is None:
            continue
        ec = row.get("email_count", 0)
        sent_total += ec
        ee = row.get("email_expect")
        ok_status = row["status"] == "OK"
        if ee is not None and ok_status and ec < ee:
            flag = f'<span style="color:{RED}"> ⚠ expected {ee}</span>'
        else:
            flag = ""
        yt_detail = f' <span style="color:{GRAY};font-size:11px">({row["yt_sent_label"]})</span>' if row.get("yt_sent_label") else ""
        sent_rows_html += f"""
          <tr style="border-bottom:1px solid #f5f5f5">
            <td style="padding:5px 20px 5px 0;font-size:13px;color:{GRAY}">{row['label']}{yt_detail}</td>
            <td style="padding:5px 0;font-size:13px;font-weight:bold">{ec}</td>
            <td style="padding:5px 0 5px 16px;font-size:13px">{flag}</td>
          </tr>"""

    for cat in extra_categories:
        ec = count_matching(sent_subjects, cat["keywords"])
        sent_total += ec
        sent_rows_html += f"""
          <tr style="border-bottom:1px solid #f5f5f5">
            <td style="padding:5px 20px 5px 0;font-size:13px;color:{GRAY}">{cat['label']}</td>
            <td style="padding:5px 0;font-size:13px;font-weight:bold">{ec}</td>
            <td style="padding:5px 0 5px 16px;font-size:13px"></td>
          </tr>"""

    sent_section = f"""
      <h3 style="margin:28px 0 8px;font-size:12px;color:{GRAY};letter-spacing:0.08em;text-transform:uppercase">
        Sent Mail — Last 25h (Gmail Outbox)
      </h3>
      <table style="border-collapse:collapse">
        {sent_rows_html}
        <tr style="border-top:1px solid #e0e0e0">
          <td style="padding:7px 20px 3px 0;font-size:13px;font-weight:bold">TOTAL</td>
          <td style="padding:7px 0;font-size:13px;font-weight:bold">{sent_total}</td>
          <td></td>
        </tr>
      </table>"""

    return f"""
<html><body style="font-family:Arial,sans-serif;max-width:760px;margin:0 auto;color:#1c2024;padding:16px">
  <h2 style="margin-bottom:2px">Automation Health — {date_str}</h2>
  <p style="color:{GRAY};margin:0 0 4px;font-size:14px">{time_str}</p>
  <p style="font-size:16px;font-weight:bold;color:{summary_color};margin:0 0 20px">{summary_text}</p>

  <table style="border-collapse:collapse;width:100%">
    <thead>
      <tr style="border-bottom:2px solid #e0e0e0">
        <th style="padding:6px 10px;text-align:left;font-size:11px;color:{GRAY}"></th>
        <th style="padding:6px 12px;text-align:left;font-size:11px;color:{GRAY};text-transform:uppercase;letter-spacing:0.05em">Schedule</th>
        <th style="padding:6px 12px;text-align:left;font-size:11px;color:{GRAY};text-transform:uppercase;letter-spacing:0.05em">Last Run (SGT)</th>
        <th style="padding:6px 12px;text-align:left;font-size:11px;color:{GRAY};text-transform:uppercase;letter-spacing:0.05em">Status</th>
        <th style="padding:6px 12px;text-align:left;font-size:11px;color:{GRAY};text-transform:uppercase;letter-spacing:0.05em">Age</th>
        <th style="padding:6px 12px;text-align:left;font-size:11px;color:{GRAY};text-transform:uppercase;letter-spacing:0.05em">Email</th>
      </tr>
    </thead>
    <tbody>{table_rows}
      <tr><td colspan="6" style="padding:4px 12px;font-size:11px;color:{GRAY}">† previous day</td></tr>
    </tbody>
  </table>
  {sent_section}
  {llm_section}
</body></html>"""


def main(gmail_smtp: dict = {}, recipient_email: str = ""):
    sgt = pytz.timezone("Asia/Singapore")
    now_sgt = datetime.now(sgt)
    now_utc = datetime.now(timezone.utc)
    is_weekend_or_monday = now_sgt.weekday() in (5, 6, 0)

    token = os.environ.get("WM_TOKEN", "")

    # ── Fetch Gmail Sent folder ──────────────────────────────────────────────
    sent_subjects = []
    if gmail_smtp:
        log.info("Fetching Gmail Sent folder...")
        try:
            sent_subjects = fetch_sent_subjects(gmail_smtp, hours=25)
            log.info(f"Found {len(sent_subjects)} sent emails in last 25h")
        except Exception as e:
            log.info(f"IMAP fetch failed: {e}")

    # ── Check each schedule ──────────────────────────────────────────────────
    rows = []
    ok_count = 0
    llm_rows = []
    total_prompt = total_completion = 0
    total_cost = 0.0

    for sched in SCHEDULES:
        spath = sched["path"]
        label = sched["label"]
        max_age_h = sched["max_age_h"]
        if sched["weekday_only"] and is_weekend_or_monday:
            max_age_h = 72

        # Sent email count for this schedule
        email_count = (count_matching(sent_subjects, sched["email_match"])
                       if sched["email_match"] else None)

        try:
            jobs = wmill_get(
                f"w/{WORKSPACE}/jobs/completed/list"
                f"?schedule_path={urllib.parse.quote(spath)}&per_page=1",
                token
            )
        except Exception as e:
            rows.append({"label": label, "status": "STALE", "error": f"API error: {e}",
                         "email_match": sched["email_match"], "email_count": email_count,
                         "email_expect": sched["email_expect"]})
            continue

        if not jobs:
            rows.append({"label": label, "status": "STALE", "error": "No runs found",
                         "email_match": sched["email_match"], "email_count": email_count,
                         "email_expect": sched["email_expect"]})
            continue

        job = jobs[0]
        started_utc = datetime.fromisoformat(job["started_at"].replace("Z", "+00:00"))
        age = now_utc - started_utc
        age_h = age.total_seconds() / 3600
        age_str = fmt_age(age)

        started_sgt = started_utc.astimezone(sgt)
        last_run_str = started_sgt.strftime("%-I:%M %p")
        if started_sgt.date() < now_sgt.date():
            last_run_str += "†"

        base_row = {
            "label": label, "last_run": last_run_str, "age_str": age_str,
            "email_match": sched["email_match"], "email_count": email_count,
            "email_expect": sched["email_expect"],
        }

        if not job["success"]:
            error_msg = ""
            try:
                error_msg = str((job.get("result") or {}).get("error", {}).get("message", ""))[:80]
            except Exception as _exc:
                log.warning("Suppressed: %s", _exc)
            rows.append({**base_row, "status": "FAILED", "error": error_msg})
            continue

        if age_h > max_age_h:
            rows.append({**base_row, "status": "STALE", "error": f"No run in last {max_age_h}h"})
            continue

        ok_count += 1
        rows.append({**base_row, "status": "OK", "error": ""})

        # ── Token + YouTube digest count ──────────────────────────────────────
        if sched["has_llm"]:
            try:
                if sched["llm_aggregate"]:
                    all_jobs = wmill_get(
                        f"w/{WORKSPACE}/jobs/completed/list"
                        f"?schedule_path={urllib.parse.quote(spath)}&per_page=30",
                        token
                    )
                    cutoff = now_utc - timedelta(hours=24)
                    pt = ct = 0
                    cost = 0.0
                    total_runs = 0
                    for j in all_jobs:
                        j_start = datetime.fromisoformat(j["started_at"].replace("Z", "+00:00"))
                        if j_start < cutoff:
                            break
                        total_runs += 1
                        # completed/list omits result — fetch individually for token data.
                        # Skip fast jobs (< 2s): they exited early with no videos.
                        if j["success"] and j.get("duration_ms", 0) > 2000:
                            try:
                                full = wmill_get(f"w/{WORKSPACE}/jobs_u/get/{j['id']}", token)
                                r = full.get("result") or {}
                                if isinstance(r, dict) and "prompt_tokens" in r:
                                    pt += r.get("prompt_tokens", 0)
                                    ct += r.get("completion_tokens", 0)
                                    cost += r.get("est_cost_usd", 0.0)
                            except Exception as ex:
                                log.info(f"Could not fetch YouTube job result {j['id']}: {ex}")
                    # Gmail Sent count is the authoritative "emails sent" figure
                    sent_count = email_count or 0
                    rows[-1]["yt_sent_label"] = f"{sent_count} of {total_runs} hourly runs sent emails"
                    if pt or ct:
                        llm_rows.append({"label": label, "prompt": pt, "completion": ct,
                                         "cost": cost, "sent_runs": sent_count, "total_runs": total_runs})
                        total_prompt += pt
                        total_completion += ct
                        total_cost += cost
                else:
                    full = wmill_get(f"w/{WORKSPACE}/jobs_u/get/{job['id']}", token)
                    r = full.get("result") or {}
                    pt = r.get("prompt_tokens", 0)
                    ct = r.get("completion_tokens", 0)
                    cost = r.get("est_cost_usd", 0.0)
                    if pt or ct:
                        llm_rows.append({"label": label, "prompt": pt, "completion": ct, "cost": cost})
                        total_prompt += pt
                        total_completion += ct
                        total_cost += cost
            except Exception as e:
                log.info(f"Token fetch failed for {label}: {e}")

    total = len(SCHEDULES)
    subject = f"Health Check — {now_sgt.strftime('%-d %b %Y')} | {ok_count}/{total} OK"
    html = build_html(rows, now_sgt, ok_count, total, llm_rows, total_prompt, total_completion,
                      total_cost, sent_subjects, EXTRA_CATEGORIES)

    if gmail_smtp:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = gmail_smtp["username"]
        msg["To"] = recipient_email
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP(gmail_smtp["host"], gmail_smtp["port"]) as server:
            server.starttls()
            server.login(gmail_smtp["username"], gmail_smtp["password"])
            server.send_message(msg)

        log.info(f"Sent: {subject}")

    log.info(f"Status: {ok_count}/{total} OK")
    log.info(f"Sent emails found in outbox: {len(sent_subjects)}")
    if total_prompt or total_completion:
        log.info(f"Tokens: {total_prompt:,} prompt + {total_completion:,} completion · est. ${total_cost:.4f}")

    return {
        "ok_count":   ok_count,
        "total":      total,
        "rows":       rows,
        "llm_rows":   llm_rows,
        "total_cost": round(total_cost, 4),
    }
