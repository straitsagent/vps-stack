# Requirements:
# pytz>=2024.1
# requests>=2.31
# openai>=1.0
# psycopg2-binary>=2.9

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


WM_BASE      = "http://windmill_server:8000"
WM_WORKSPACE = "admins"


def _dispatch_formatter(formatter_name: str, md_path: str,
                        telegram_bot_token: str, telegram_owner_id: str,
                        portfolio_db: dict, wm_token: str = "") -> str:
    """Dispatch a Telegram formatter script fire-and-forget. Returns job_id or ''."""
    import urllib.request as _ulr, json as _json
    token = wm_token or os.environ.get("WM_TOKEN", "")
    if not token:
        log.warning(f"[Dispatch] No WM_TOKEN — cannot dispatch {formatter_name}")
        return ""
    url = f"{WM_BASE}/api/w/{WM_WORKSPACE}/jobs/run/p/u/admin/{formatter_name}"
    args = {
        "md_path": md_path,
        "telegram_bot_token": telegram_bot_token,
        "telegram_owner_id": telegram_owner_id,
        "portfolio_db": portfolio_db,
    }
    try:
        data = _json.dumps(args).encode()
        req = _ulr.Request(url, data=data, headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        })
        resp = _ulr.urlopen(req, timeout=10)
        job_id = resp.read().decode().strip().strip('"')
        log.info(f"[Dispatch] {formatter_name} dispatched job_id={job_id}")
        return job_id
    except Exception as e:
        log.warning(f"[Dispatch] Failed to dispatch {formatter_name}: {e}")
        return ""


def _build_health_narrative(rows: list, ok_count: int, total: int,
                             llm_rows: list, total_cost: float,
                             now_sgt: datetime) -> str:
    """Generate a ≥500-word narrative description of the health check results."""
    date_str = now_sgt.strftime("%A, %-d %B %Y at %-I:%M %p SGT")
    failed = [r for r in rows if r.get("status") != "OK"]
    ok_rows = [r for r in rows if r.get("status") == "OK"]

    paras = []

    # Overview paragraph
    overview_status = "all automated workflows are operating within expected parameters" if not failed else \
        f"{len(failed)} of {total} automated workflows require attention"
    paras.append(
        f"This automated health check was executed on {date_str}. "
        f"The monitoring system checks each scheduled workflow against its expected run interval and "
        f"confirms that completed jobs returned successful results. At the time of this report, "
        f"{overview_status}. The portfolio automation stack spans {total} core scheduled workflows "
        f"covering market data ingestion, portfolio reporting, news monitoring, and system monitoring. "
        f"A workflow is marked OK when its most recent completed job finished successfully and ran "
        f"within the configured maximum-age window. STALE indicates the last successful run was "
        f"outside the expected window; FAILED indicates the most recent job returned an error result."
    )

    # Per-schedule detail paragraphs
    for row in rows:
        label = row.get("label", "Unknown")
        status = row.get("status", "?")
        age_str = row.get("age_str", "unknown")
        error = row.get("error", "")
        if status == "OK":
            paras.append(
                f"{label}: status OK. Last completed run was {age_str}. "
                f"The workflow completed successfully within its configured monitoring window. "
                f"No errors were recorded in the most recent completed job. This schedule "
                f"is operating normally and no manual intervention is required at this time."
            )
        else:
            detail = f" The reported error was: {error}." if error else ""
            paras.append(
                f"{label}: status {status}.{detail} "
                f"The most recent detected run was {age_str}. "
                f"This schedule is currently outside its expected run window or returned an error. "
                f"Recommended action: open the Windmill UI, navigate to this schedule, and inspect "
                f"the most recent completed and failed jobs for stack traces or dependency errors. "
                f"Common causes include temporary API unavailability, credential expiry, or "
                f"network connectivity issues with external data providers."
            )

    # LLM cost paragraph
    if llm_rows:
        cost_str = f"${total_cost:.4f}"
        job_names = ", ".join(r.get("label", "?") for r in llm_rows)
        paras.append(
            f"LLM API usage in the past 24 hours was recorded for the following workflows: "
            f"{job_names}. The aggregate estimated API cost across all LLM-enabled workflows "
            f"for this period was {cost_str}. Token consumption is tracked per job run to "
            f"allow cost monitoring and budget management. If token usage appears abnormally "
            f"high, inspect the prompt construction in the affected workflow for unexpected "
            f"token inflation from oversized context or runaway retries."
        )
    else:
        paras.append(
            f"No LLM API token usage was recorded in the past 24 hours across the monitored "
            f"workflows. This is expected on weekends or days when no LLM-enabled workflows ran. "
            f"Token usage is tracked for billing monitoring and typically reflects Deepseek API "
            f"calls made by the YouTube monitor and portfolio review workflows."
        )

    # Summary paragraph
    if not failed:
        paras.append(
            f"Overall assessment: the automation stack is fully operational. "
            f"All {total} monitored workflows are running on schedule and returning clean results. "
            f"No manual intervention is required. The next scheduled health check will run in "
            f"approximately 24 hours. If any workflow begins failing before then, a separate "
            f"error alert will be triggered via the Windmill error notification system."
        )
    else:
        paras.append(
            f"Overall assessment: {len(failed)} workflow(s) require immediate attention. "
            f"The affected workflows are: {', '.join(r.get('label', '?') for r in failed)}. "
            f"Please investigate as soon as possible to prevent data gaps. The portfolio "
            f"intelligence system depends on timely execution of all scheduled workflows for "
            f"accurate reporting. Extended downtime in any single workflow may cause stale "
            f"data to propagate into portfolio emails and rationalization scores."
        )

    return "\n\n".join(paras)


def _diagnose_failure(label: str, path: str, status: str, error: str,
                      age_str: str, deepseek_key: str) -> dict:
    """Call Deepseek to diagnose a STALE/FAILED schedule. Returns {root_cause, remediation}."""
    import requests as _req, re as _re
    if not deepseek_key:
        return {
            "root_cause": error or f"Schedule is {status}",
            "remediation": "Check Windmill job logs for details",
        }
    system_msg = (
        "You are a DevOps engineer diagnosing a failed automation system. "
        "Respond ONLY with a JSON object with exactly two keys: "
        '"root_cause" (one sentence, ≤20 words) and "remediation" (one sentence, ≤25 words). '
        "No preamble, no markdown."
    )
    user_msg = (
        f"Script: {label} ({path})\n"
        f"Status: {status}\n"
        f"Error: {error}\n"
        f"Last successful run: {age_str}\n"
        "Diagnose the most likely root cause and the single most important fix."
    )
    try:
        r = _req.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {deepseek_key}",
                     "Content-Type": "application/json"},
            json={"model": "deepseek-chat",
                  "messages": [{"role": "system", "content": system_msg},
                                {"role": "user",   "content": user_msg}],
                  "temperature": 0.1, "max_tokens": 100},
            timeout=15,
        )
        r.raise_for_status()
        raw = r.json()["choices"][0]["message"]["content"].strip()
        m = _re.search(r"\{.*\}", raw, _re.DOTALL)
        if m:
            return json.loads(m.group())
        return {"root_cause": raw[:120], "remediation": "See Windmill job logs"}
    except Exception as exc:
        log.warning(f"[Diagnose] {label}: Deepseek call failed ({exc}) — using raw error")
        return {
            "root_cause": error or f"Schedule is {status}",
            "remediation": "Check Windmill job logs for stack trace",
        }


def _collect_24h_reports(now: datetime, research_root: str = "/research") -> list:
    """Scan /research subdirs for .md files written in the last 26h.
    Returns [{type, path, mtime, front_matter, narrative, word_count}]."""
    import os as _os
    cutoff = now - timedelta(hours=26)
    subdir_types = {
        "macro": "macro", "portfolio": "portfolio", "youtube": "youtube",
        "news": "news", "health": "health",
    }
    reports = []
    for subdir, type_name in subdir_types.items():
        dir_path = _os.path.join(research_root, subdir)
        if not _os.path.isdir(dir_path):
            continue
        for fname in sorted(_os.listdir(dir_path)):
            if not fname.endswith(".md"):
                continue
            fpath = _os.path.join(dir_path, fname)
            mtime_ts = _os.path.getmtime(fpath)
            mtime = datetime.fromtimestamp(mtime_ts, tz=timezone.utc)
            if mtime < cutoff:
                continue
            front_matter = {}
            narrative = ""
            try:
                with open(fpath) as f:
                    raw = f.read()
                if raw.startswith("```json\n"):
                    end = raw.index("\n```\n", 8)
                    front_matter = json.loads(raw[8:end])
                    rest = raw[end + 5:]
                    if "<!-- DETAIL -->" in rest:
                        narrative = rest[:rest.index("<!-- DETAIL -->")].strip()
                    else:
                        narrative = rest.strip()
            except Exception as ex:
                log.warning(f"[Collect] Failed to parse {fpath}: {ex}")
            reports.append({
                "type": type_name,
                "path": fpath,
                "mtime": mtime_ts,
                "front_matter": front_matter,
                "narrative": narrative,
                "word_count": len(narrative.split()),
            })
    return reports


SPEC_RULES = {
    "macro": [
        lambda fm: (bool(fm.get("indicators")), "indicators missing from front-matter"),
        lambda fm: (
            isinstance(fm.get("indicators", {}).get("yahoo"), dict) and
            len(fm.get("indicators", {}).get("yahoo", {})) >= 12,
            "indicators.yahoo must have ≥12 symbols"
        ),
        lambda fm: (
            isinstance(fm.get("indicators", {}).get("fred"), dict) and
            len(fm.get("indicators", {}).get("fred", {})) >= 13,
            "indicators.fred must have 13 series"
        ),
        lambda fm: (bool(fm.get("news_headlines")), "news_headlines missing or empty"),
    ],
    "portfolio": [
        lambda fm: (fm.get("total_value") is not None, "total_value missing"),
        lambda fm: (fm.get("total_pnl") is not None, "total_pnl missing"),
        lambda fm: (fm.get("total_pnl_pct") is not None, "total_pnl_pct missing"),
    ],
    "youtube": [
        lambda fm: (
            bool(fm.get("videos") or fm.get("video_count")),
            "videos/video_count missing or empty"
        ),
    ],
}


def _spec_check(report: dict) -> dict:
    """Validate a report dict against its per-type front-matter schema contract."""
    type_name = report.get("type", "")
    fm = report.get("front_matter", {})
    rules = SPEC_RULES.get(type_name, [])
    violations = []
    for rule in rules:
        try:
            ok, msg = rule(fm)
            if not ok:
                violations.append(msg)
        except Exception as ex:
            violations.append(f"Rule error: {ex}")
    return {
        "output": type_name,
        "pass": len(violations) == 0,
        "violations": violations,
    }


def _synthesise_daily_digest(reports: list, xai_key: str, deepseek_key: str) -> str:
    """Call Grok-4 (fallback Deepseek) to produce a holistic 700-1000 word daily brief."""
    import openai as _oai
    sections = []
    for r in reports:
        narrative = r.get("narrative", "")[:2000]
        if narrative:
            sections.append(f"=== {r.get('type', 'unknown').upper()} ===\n{narrative}")
    if not sections:
        return ""
    context = "\n\n".join(sections)
    system_msg = (
        "You are the chief of staff for an investor. Below is everything the personal "
        "intelligence system produced in the last 24 hours — macro research, portfolio "
        "AM/PM updates, weekly review and rationalization (if present), YouTube channel "
        "summaries, and the news digest.\n\n"
        "Write a single coherent executive daily brief of 700–1000 words divided into "
        "numbered sections with clear headings. Use bullet points within sections for "
        "conciseness. Include an executive summary paragraph at the start and a conclusion "
        "paragraph at the end. Synthesise the cross-cutting themes: what changed, what "
        "matters most today, where sources agree or conflict, and what warrants attention. "
        "End with a complete sentence."
    )
    user_msg = f"Content produced in the last 24 hours:\n\n{context}"
    msgs = [{"role": "system", "content": system_msg}, {"role": "user", "content": user_msg}]
    if xai_key:
        try:
            client = _oai.OpenAI(api_key=xai_key, base_url="https://api.x.ai/v1")
            resp = client.chat.completions.create(
                model="grok-4",
                messages=msgs,
                temperature=0.3,
                max_tokens=1500,
            )
            return resp.choices[0].message.content.strip()
        except Exception as exc:
            log.warning(f"[Digest] Grok-4 failed ({exc}), falling back to Deepseek")
    if deepseek_key:
        try:
            client = _oai.OpenAI(api_key=deepseek_key, base_url="https://api.deepseek.com")
            resp = client.chat.completions.create(
                model="deepseek-chat",
                messages=msgs,
                temperature=0.3,
                max_tokens=1500,
            )
            return resp.choices[0].message.content.strip()
        except Exception as exc:
            log.warning(f"[Digest] Deepseek fallback also failed: {exc}")
    return ""


def _query_telegram_outbox_24h(portfolio_db: dict) -> list:
    """Query telegram_outbox for sends in the last 24 hours.
    Returns list of dicts: {script_name, delivered, word_count, error, sent_at}.
    Returns [] if portfolio_db is empty or query fails."""
    try:
        import psycopg2
        conn = psycopg2.connect(**{k: v for k, v in portfolio_db.items()
                                    if k in ("host", "port", "dbname", "user", "password")})
        cur = conn.cursor()
        cur.execute(
            "SELECT script_name, delivered, word_count, error, sent_at::text "
            "FROM telegram_outbox "
            "WHERE sent_at >= now() - interval '24 hours' "
            "ORDER BY sent_at DESC"
        )
        rows = [
            {"script_name": r[0], "delivered": r[1], "word_count": r[2],
             "error": r[3], "sent_at": r[4]}
            for r in cur.fetchall()
        ]
        conn.close()
        return rows
    except Exception as e:
        log.info(f"[OutboxAudit] Could not query telegram_outbox: {e}")
        return []


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


# ── Factored I/O seams (enable artifact-level testing of main()) ─────────────

def _send_email(gmail_smtp: dict, recipient_email: str, subject: str, html: str) -> None:
    """Send an HTML email via SMTP. Factored from main() to allow test interception."""
    if not gmail_smtp:
        return
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


def _build_front_matter(tg_date: str, ok_count: int, total: int, fm_rows: list,
                        token_usage: list, outbox_rows: list, diagnoses: list,
                        spec_checks: list, content_inventory: list, digest: str) -> dict:
    """Assemble the canonical front-matter dict (single source for email + Telegram)."""
    return {
        "tg_date":           tg_date,
        "ok_count":          ok_count,
        "total":             total,
        "rows":              fm_rows,
        "token_usage":       token_usage,
        "outbox_rows":       outbox_rows,
        "diagnoses":         diagnoses,
        "spec_checks":       spec_checks,
        "content_inventory": content_inventory,
        "digest":            digest,
    }


def _build_md_content(front_matter: dict, narrative: str) -> str:
    """Render the canonical .md string from front_matter + narrative (pure function)."""
    return (
        f"```json\n{json.dumps(front_matter, indent=2)}\n```\n\n"
        f"{narrative}\n\n"
        "<!-- DETAIL -->\n"
    )


def _write_canonical_md(md_content: str, path: str) -> None:
    """Write the canonical .md to disk. Factored from main() to allow test interception."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(md_content)
    log.info(f"[md] Written {path}")


# ─────────────────────────────────────────────────────────────────────────────

def build_html(rows, now_sgt, ok_count, total, llm_rows, total_prompt, total_completion,
               total_cost, sent_subjects, extra_categories,
               digest="", spec_checks=None, diagnoses=None):
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

    # ── Daily Brief (digest) ─────────────────────────────────────────────────
    digest_section = ""
    if digest:
        digest_html = digest.replace("\n\n", "</p><p style='margin:8px 0'>").replace("\n", "<br>")
        digest_section = f"""
      <h3 style="margin:28px 0 8px;font-size:12px;color:{GRAY};letter-spacing:0.08em;text-transform:uppercase">
        Daily Brief
      </h3>
      <div style="font-size:14px;line-height:1.6;color:#1c2024;background:#f9f9f9;padding:14px 16px;border-left:3px solid #4a90d9;border-radius:3px">
        <p style="margin:0">{digest_html}</p>
      </div>"""

    # ── Spec Check Failures ──────────────────────────────────────────────────
    spec_section = ""
    failing = [s for s in (spec_checks or []) if not s.get("pass")]
    if failing:
        spec_rows_html = ""
        for s in failing:
            for v in s.get("violations", []):
                spec_rows_html += f"""
          <tr style="border-bottom:1px solid #fff3cd">
            <td style="padding:4px 12px 4px 0;font-size:13px;color:{ORANGE}">⚠️</td>
            <td style="padding:4px 12px;font-size:13px;color:{GRAY}">{s['output']}</td>
            <td style="padding:4px 0;font-size:13px">{v}</td>
          </tr>"""
        spec_section = f"""
      <h3 style="margin:28px 0 8px;font-size:12px;color:{GRAY};letter-spacing:0.08em;text-transform:uppercase">
        Spec Check Failures ({len(failing)} output{'s' if len(failing) > 1 else ''})
      </h3>
      <table style="border-collapse:collapse">{spec_rows_html}
      </table>"""

    # ── AI Diagnoses ─────────────────────────────────────────────────────────
    diag_section = ""
    if diagnoses:
        diag_html = ""
        for d in diagnoses:
            diag_html += f"""
        <div style="margin-bottom:12px">
          <span style="font-size:13px;font-weight:bold">{d['label']}</span><br>
          <span style="font-size:13px;color:{GRAY}">Cause:</span>
          <span style="font-size:13px"> {d.get('root_cause','')}</span><br>
          <span style="font-size:13px;color:{GRAY}">Fix:</span>
          <span style="font-size:13px"> {d.get('remediation','')}</span>
        </div>"""
        diag_section = f"""
      <h3 style="margin:28px 0 8px;font-size:12px;color:{GRAY};letter-spacing:0.08em;text-transform:uppercase">
        AI Diagnoses
      </h3>
      <div style="font-size:14px">{diag_html}</div>"""

    return f"""
<html><body style="font-family:Arial,sans-serif;max-width:760px;margin:0 auto;color:#1c2024;padding:16px">
  <h2 style="margin-bottom:2px">Automation Health — {date_str}</h2>
  <p style="color:{GRAY};margin:0 0 4px;font-size:14px">{time_str}</p>
  <p style="font-size:16px;font-weight:bold;color:{summary_color};margin:0 0 20px">{summary_text}</p>
  {digest_section}

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
  {spec_section}
  {diag_section}
  {sent_section}
  {llm_section}
</body></html>"""


def main(gmail_smtp: dict = {}, recipient_email: str = "", telegram_bot_token: str = "", telegram_owner_id: str = "", portfolio_db: dict = {}, wm_token: str = "", deepseek_key: str = "", xai_key: str = ""):
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
    diagnoses = []

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
            d = _diagnose_failure(label, spath, "STALE", f"API error: {e}", "unknown", deepseek_key)
            diagnoses.append({"label": label, **d})
            continue

        if not jobs:
            rows.append({"label": label, "status": "STALE", "error": "No runs found",
                         "email_match": sched["email_match"], "email_count": email_count,
                         "email_expect": sched["email_expect"]})
            d = _diagnose_failure(label, spath, "STALE", "No runs found", "never", deepseek_key)
            diagnoses.append({"label": label, **d})
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
            d = _diagnose_failure(label, spath, "FAILED", error_msg, age_str, deepseek_key)
            diagnoses.append({"label": label, **d})
            continue

        if age_h > max_age_h:
            rows.append({**base_row, "status": "STALE", "error": f"No run in last {max_age_h}h"})
            d = _diagnose_failure(label, spath, "STALE", f"No run in last {max_age_h}h", age_str, deepseek_key)
            diagnoses.append({"label": label, **d})
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

    # ── Content engine (runs unconditionally — used by email + .md + Telegram) ─
    content_reports = []
    spec_checks = []
    content_inventory = []
    digest = ""
    try:
        content_reports = _collect_24h_reports(now_sgt)
        spec_checks = [_spec_check(r) for r in content_reports]
        failing_specs = [s for s in spec_checks if not s["pass"]]
        if failing_specs:
            log.warning(f"[SpecCheck] {len(failing_specs)} spec failure(s): "
                         + "; ".join(f"{s['output']}:{s['violations']}" for s in failing_specs))
        content_inventory = [{"type": r["type"], "path": r["path"],
                               "word_count": r["word_count"]} for r in content_reports]
    except Exception as exc:
        log.warning(f"[ContentEngine] Collect/spec failed: {exc}")
    if xai_key or deepseek_key:
        try:
            digest = _synthesise_daily_digest(content_reports, xai_key, deepseek_key)
            if digest:
                log.info(f"[Digest] {len(digest.split())} words synthesised")
        except Exception as exc:
            log.warning(f"[Digest] Synthesis failed: {exc}")

    # ── Build token_usage + shared front-matter (single source for email + Telegram) ─
    token_usage = [
        {
            "job": row_llm.get("label", "?"),
            "model": "deepseek-chat",
            "tokens": row_llm.get("prompt", 0) + row_llm.get("completion", 0),
            "cost_usd": row_llm.get("cost", 0.0),
        }
        for row_llm in llm_rows
    ]
    fm_rows = [
        {"label": r["label"], "status": r["status"],
         "age_str": r.get("age_str", ""), "error": r.get("error", "") or ""}
        for r in rows
    ]
    # Query telegram_outbox for last 24h formatter sends — surfaces delivery failures,
    # word-count violations, and BELOW_MIN_WORDS flags from the youtube formatter.
    outbox_rows = _query_telegram_outbox_24h(portfolio_db) if portfolio_db else []
    if outbox_rows:
        log.info(f"[OutboxAudit] {len(outbox_rows)} telegram_outbox rows in last 24h")
        failures = [r for r in outbox_rows if not r.get("delivered") or r.get("error")]
        if failures:
            log.warning(f"[OutboxAudit] {len(failures)} formatter issue(s): "
                         + "; ".join(f"{r['script_name']}:{r.get('error','undelivered')}"
                                     for r in failures))

    front_matter = _build_front_matter(
        tg_date=now_sgt.strftime("%-d %b"),
        ok_count=ok_count, total=total,
        fm_rows=fm_rows, token_usage=token_usage,
        outbox_rows=outbox_rows, diagnoses=diagnoses,
        spec_checks=spec_checks, content_inventory=content_inventory,
        digest=digest,
    )

    # ── Build HTML email from single source (front_matter drives shared fields) ─
    subject = f"Health Check — {now_sgt.strftime('%-d %b %Y')} | {ok_count}/{total} OK"
    html = build_html(rows, now_sgt, ok_count, total, llm_rows, total_prompt, total_completion,
                      total_cost, sent_subjects, EXTRA_CATEGORIES,
                      digest=front_matter["digest"],
                      spec_checks=front_matter["spec_checks"],
                      diagnoses=front_matter["diagnoses"])

    _send_email(gmail_smtp, recipient_email, subject, html)

    log.info(f"Status: {ok_count}/{total} OK")
    log.info(f"Sent emails found in outbox: {len(sent_subjects)}")
    if total_prompt or total_completion:
        log.info(f"Tokens: {total_prompt:,} prompt + {total_completion:,} completion · est. ${total_cost:.4f}")

    # ── Write canonical .md and dispatch Telegram formatter ─────────────────
    if telegram_bot_token and telegram_owner_id:
        narrative = _build_health_narrative(rows, ok_count, total, llm_rows, total_cost, now_sgt)
        md_path = f"/research/health/{now_sgt.strftime('%Y-%m-%d_%H%M')}.md"
        md_content = _build_md_content(front_matter, narrative)
        _write_canonical_md(md_content, md_path)

        _dispatch_formatter(
            "health_check_telegram", md_path,
            telegram_bot_token, telegram_owner_id,
            portfolio_db, wm_token or token,
        )

    return {
        "ok_count":   ok_count,
        "total":      total,
        "rows":       rows,
        "llm_rows":   llm_rows,
        "total_cost": round(total_cost, 4),
    }
