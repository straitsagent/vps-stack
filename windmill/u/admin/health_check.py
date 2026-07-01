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
    # portfolio subdir contains files from multiple scripts; detect by filename prefix
    _portfolio_prefix_types = {
        "move_": "portfolio_move",
        "rationalization_": "portfolio_rationalization",
        "review_": "portfolio_review",
    }
    reports = []
    for subdir, base_type in subdir_types.items():
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
            # Narrow portfolio sub-type so SPEC_RULES["portfolio"] only fires on email files
            if base_type == "portfolio":
                type_name = next(
                    (t for pfx, t in _portfolio_prefix_types.items() if fname.startswith(pfx)),
                    "portfolio",
                )
            else:
                type_name = base_type
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
            isinstance(fm.get("indicators", {}).get("market"), dict) and
            len(fm.get("indicators", {}).get("market", {})) >= 12,
            "indicators.market must have ≥12 symbols"
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
    {"path": "u/admin/macro_research_daily",                  "label": "Macro Research",              "max_age_h": 26, "has_llm": True,  "llm_aggregate": False, "weekday_only": True,  "email_match": ["Macro Research"],           "email_expect": 1},
    {"path": "u/admin/portfolio_price_fetcher_daily",   "label": "Portfolio Price Fetcher (AM)", "max_age_h": 26, "has_llm": False, "llm_aggregate": False, "weekday_only": True,  "email_match": None,                         "email_expect": None},
    {"path": "u/admin/portfolio_email_daily",           "label": "Portfolio Email (AM)",         "max_age_h": 26, "has_llm": False, "llm_aggregate": False, "weekday_only": True,  "email_match": ["Portfolio", "US Close"],     "email_expect": 1},
    {"path": "u/admin/portfolio_price_fetcher_evening", "label": "Portfolio Price Fetcher (PM)", "max_age_h": 26, "has_llm": False, "llm_aggregate": False, "weekday_only": True,  "email_match": None,                         "email_expect": None},
    {"path": "u/admin/portfolio_email_evening",         "label": "Portfolio Email (PM)",         "max_age_h": 26, "has_llm": False, "llm_aggregate": False, "weekday_only": True,  "email_match": ["Portfolio", "Asia Close"],   "email_expect": 1},
    {"path": "u/admin/youtube_monitor_hourly",          "label": "YouTube Monitor (daily)",      "max_age_h": 26,  "has_llm": True,  "llm_aggregate": True,  "weekday_only": False, "email_match": ["YouTube Digest"],            "email_expect": None},
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
                        spec_checks: list, content_inventory: list) -> dict:
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
    }


def _build_md_content(fm: dict) -> str:
    """Render the canonical .md string — comprehensive deterministic report (pure function)."""
    sections = []
    sections.append(f"```json\n{json.dumps(fm, indent=2)}\n```\n")

    # Schedule Status
    sections.append("## Schedule Status")
    for row in fm.get("rows", []):
        icon = "✅" if row.get("status") == "OK" else ("❌" if row.get("status") == "FAILED" else "⚠️")
        sections.append(f"{icon} **{row['label']}**: {row['status']} — {row.get('age_str','?')}{' — ' + row['error'] if row.get('error') else ''}")
    sections.append(f"\n{sum(1 for r in fm.get('rows',[]) if r.get('status')=='OK')}/{len(fm.get('rows',[]))} OK\n")

    # System Resources
    sysd = fm.get("system", {})
    if sysd:
        sections.append("## System Resources")
        if isinstance(sysd.get("disk"), list):
            sections.append("### Disk")
            for m in sysd["disk"]:
                sections.append(f"- {m['mount']}: {m['pct_used']}% used ({m['used_gb']}/{m['total_gb']})")
        mem = sysd.get("memory", {})
        if mem and "error" not in mem:
            sections.append(f"### Memory\n- {mem.get('used_mib','?')}MiB used / {mem.get('total_mib','?')}MiB total ({mem.get('pct_available','?')}% available)")
        ld = sysd.get("load", {})
        if ld and "error" not in ld:
            sections.append(f"### Load\n- 1m: {ld.get('load_1m',0):.1f}  5m: {ld.get('load_5m',0):.1f}  15m: {ld.get('load_15m',0):.1f}  ({ld.get('cores',1)} cores)")
        dock = sysd.get("docker", {})
        if dock and "error" not in dock:
            sections.append(f"### Docker\n- {dock.get('running',0)} running / {dock.get('total',0)} total")

    # Backup Status
    bup = fm.get("backup", {})
    if bup:
        sections.append("## Backup Status")
        svc = bup.get("service", {})
        sections.append(f"- Result: {svc.get('Result','unknown')}")
        sections.append(f"- Timer active: {bup.get('timer_active',False)}")
        sections.append(f"- Last run: {svc.get('ExecMainExitTimestamp','unknown')}")

    # Token Usage
    tok = fm.get("token_usage", [])
    if tok:
        sections.append("## Token Usage — Last 24h")
        total_c = 0.0
        for t in tok:
            sections.append(f"- {t.get('job','?')} ({t.get('model','?')}): {t.get('tokens',0):,} tokens — ${t.get('cost_usd',0):.4f}")
            total_c += t.get('cost_usd', 0)
        sections.append(f"**Total cost: ${total_c:.4f}**")

    # Spec Checks
    sc = fm.get("spec_checks", [])
    failing = [s for s in sc if not s.get("pass")]
    if failing:
        sections.append("## Spec Check Failures")
        for s in failing:
            for v in s.get("violations", []):
                sections.append(f"- ⚠️ {s['output']}: {v}")
    elif sc:
        sections.append(f"## Spec Check Results\nAll {len(sc)} outputs passed ✅")

    # AI Diagnoses
    diag = fm.get("diagnoses", [])
    if diag:
        sections.append("## AI Diagnoses")
        for d in diag:
            sections.append(f"- **{d['label']}**: Cause: {d.get('root_cause','?')} — Fix: {d.get('remediation','?')}")

    sections.append("<!-- DETAIL -->")
    return "\n\n".join(sections) + "\n"


def _write_canonical_md(md_content: str, path: str) -> None:
    """Write the canonical .md to disk. Factored from main() to allow test interception."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(md_content)
    log.info(f"[md] Written {path}")


# ── Tier 0 — Production artifact verification ────────────────────────────────
# Checks actual delivered email bodies (not just subjects) for structural markers.
# Runs inside main() after schedule status collection. Non-blocking — failures
# surface as warnings in the health check report and are written to artifact_verification.

ARTIFACT_MARKERS: dict[str, list[str]] = {
    "Morning Digest":   ["Key Headlines", "Newsletter Summaries"],
    "Portfolio":        ["Total Value", "P&L"],
    "Macro Research":   ["VIX", "10Y"],
    "Weekly Review":    ["Week P&L", "Top Movers"],
    "Health Check":     ["Schedules", "Telegram Outbox", "System Resources", "Backup Status"],
    "Move Monitor":     ["triggered", "threshold"],
    "Analyst Alert":    ["upgrade", "downgrade", "target"],
    "YouTube Monitor":  ["channel", "transcript"],
    "Rationalization":  ["Score", "Scenario"],
}


def _fetch_sent_body(gmail_smtp: dict, subject_fragment: str, hours: int = 25) -> str | None:
    """Fetch the HTML body of the most-recent sent email matching subject_fragment.

    Extends fetch_sent_subjects — uses RFC822 fetch instead of headers-only.
    Returns the HTML body string, or None if no matching email is found.
    """
    import email as _email_lib
    conn = imaplib.IMAP4_SSL(IMAP_HOST)
    try:
        conn.login(gmail_smtp["username"], gmail_smtp["password"])
        for folder in ('"[Gmail]/Sent Mail"', "Sent"):
            status, _ = conn.select(folder, readonly=True)
            if status == "OK":
                break

        cutoff_utc = datetime.now(timezone.utc) - timedelta(hours=hours)
        since_str = cutoff_utc.strftime("%d-%b-%Y")
        _, msg_ids = conn.search(None, f"SINCE {since_str}")
        if not msg_ids or not msg_ids[0]:
            return None

        frag_lower = subject_fragment.lower()
        # Iterate in reverse (most recent first)
        for mid in reversed(msg_ids[0].split()):
            _, hdr_data = conn.fetch(mid, "(RFC822.HEADER)")
            if not hdr_data or not hdr_data[0]:
                continue
            raw_hdr = hdr_data[0][1] if isinstance(hdr_data[0], tuple) else hdr_data[0]
            hdr_msg = _email_lib.message_from_bytes(raw_hdr)
            subject = decode_subject(hdr_msg.get("Subject", ""))
            if frag_lower not in subject.lower():
                continue
            # Found — fetch full body
            _, body_data = conn.fetch(mid, "(RFC822)")
            if not body_data or not body_data[0]:
                return None
            raw_body = body_data[0][1] if isinstance(body_data[0], tuple) else body_data[0]
            full_msg = _email_lib.message_from_bytes(raw_body)
            # Extract HTML part
            if full_msg.is_multipart():
                for part in full_msg.walk():
                    if part.get_content_type() == "text/html":
                        payload = part.get_payload(decode=True)
                        if payload:
                            return payload.decode("utf-8", errors="replace")
            else:
                payload = full_msg.get_payload(decode=True)
                if payload:
                    return payload.decode("utf-8", errors="replace")
        return None
    except Exception as exc:
        log.warning(f"[Tier0] _fetch_sent_body({subject_fragment!r}): {exc}")
        return None
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def _artifact_body_check(body: str, required_markers: list[str]) -> dict:
    """Check body HTML for presence of required_markers. Pure function.

    Returns {"pass": bool, "missing": list[str], "found": list[str]}.
    """
    missing = [m for m in required_markers if m not in body]
    found   = [m for m in required_markers if m in body]
    return {"pass": len(missing) == 0, "missing": missing, "found": found}


def _write_artifact_verification(portfolio_db: dict, script_name: str, email_ok: bool,
                                  missing_sections: list[str], email_subject: str) -> None:
    """Write one row to artifact_verification table. Non-blocking on error."""
    if not portfolio_db:
        return
    try:
        import psycopg2
        conn = psycopg2.connect(**{k: v for k, v in portfolio_db.items() if k != "sslmode"})
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO artifact_verification
                   (script_name, email_ok, missing_sections, email_subject)
                   VALUES (%s, %s, %s, %s)""",
                (script_name, email_ok, missing_sections or [], email_subject),
            )
        conn.commit()
        conn.close()
    except Exception as exc:
        log.warning(f"[Tier0] artifact_verification write failed: {exc}")


# ─────────────────────────────────────────────────────────────────────────────

def build_html(rows, now_sgt, ok_count, total, llm_rows, total_prompt, total_completion,
               total_cost, sent_subjects, extra_categories,
               system_data=None, backup_data=None, spec_checks=None, diagnoses=None):
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

    # ── System Resources ──────────────────────────────────────────────────────
    system_section = ""
    if system_data:
        rows_sys = []
        if isinstance(system_data.get("disk"), list):
            for m in system_data["disk"]:
                pct = float(m.get("pct_used", 0))
                color = RED if pct >= 95 else (ORANGE if pct >= 85 else GREEN)
                rows_sys.append(f"""<tr style="border-bottom:1px solid #f5f5f5">
          <td style="padding:5px 12px;font-size:13px;color:{GRAY}">{m['mount']}</td>
          <td style="padding:5px 12px;font-size:13px;color:{color}">{m['pct_used']}%</td>
          <td style="padding:5px 12px;font-size:13px;color:{GRAY}">{m['used_gb']} / {m['total_gb']}</td>
        </tr>""")
        mem = system_data.get("memory", {})
        mem_pct_avail = mem.get("pct_available", 100)
        mem_color = RED if mem_pct_avail < 5 else (ORANGE if mem_pct_avail < 10 else GREEN)
        load = system_data.get("load", {})
        load_1m = load.get("load_1m", 0)
        cores = load.get("cores", 1)
        load_color = RED if load_1m > cores * 2 else (ORANGE if load_1m > cores else GREEN)
        sys_html = f"""<table style="border-collapse:collapse;margin-bottom:8px">{''.join(rows_sys)}
        </table>
        <table style="border-collapse:collapse">
          <tr style="border-bottom:1px solid #f5f5f5">
            <td style="padding:5px 12px;font-size:13px;color:{GRAY}">Memory</td>
            <td style="padding:5px 12px;font-size:13px;color:{mem_color}">{mem.get('used_mib','?')}MiB used / {mem.get('total_mib','?')}MiB total ({mem_pct_avail}% avail)</td>
          </tr>
          <tr style="border-bottom:1px solid #f5f5f5">
            <td style="padding:5px 12px;font-size:13px;color:{GRAY}">Load</td>
            <td style="padding:5px 12px;font-size:13px;color:{load_color}">1m:{load_1m:.1f} 5m:{load.get('load_5m',0):.1f} 15m:{load.get('load_15m',0):.1f} ({cores} cores)</td>
          </tr>
          <tr style="border-bottom:1px solid #f5f5f5">
            <td style="padding:5px 12px;font-size:13px;color:{GRAY}">Docker</td>
            <td style="padding:5px 12px;font-size:13px;color:{GREEN}">{system_data.get('docker',{}).get('running',0)} running / {system_data.get('docker',{}).get('total',0)} total</td>
          </tr>
          <tr>
            <td style="padding:5px 12px;font-size:13px;color:{GRAY}">Uptime</td>
            <td style="padding:5px 12px;font-size:13px;color:{GRAY}">{system_data.get('uptime',{}).get('uptime_formatted','?')}</td>
          </tr>
        </table>"""
        system_section = f"""
      <h3 style="margin:28px 0 8px;font-size:12px;color:{GRAY};letter-spacing:0.08em;text-transform:uppercase">
        System Resources
      </h3>
      {sys_html}"""

    # ── Backup Status ─────────────────────────────────────────────────────────
    backup_section = ""
    if backup_data:
        svc = backup_data.get("service", {})
        backup_result = svc.get("Result", "unknown")
        backup_status_color = RED if backup_result != "success" else GREEN
        backup_status_text = "OK" if backup_result == "success" else f"FAILED ({backup_result})"
        timer_active = backup_data.get("timer_active", False)
        timer_status_color = GREEN if timer_active else RED
        backup_section = f"""
      <h3 style="margin:28px 0 8px;font-size:12px;color:{GRAY};letter-spacing:0.08em;text-transform:uppercase">
        Drive Backup Status
      </h3>
      <table style="border-collapse:collapse">
        <tr style="border-bottom:1px solid #f5f5f5">
          <td style="padding:5px 12px;font-size:13px;color:{GRAY}">Service Result</td>
          <td style="padding:5px 12px;font-size:13px;color:{backup_status_color}">{backup_status_text}</td>
        </tr>
        <tr style="border-bottom:1px solid #f5f5f5">
          <td style="padding:5px 12px;font-size:13px;color:{GRAY}">Timer Active</td>
          <td style="padding:5px 12px;font-size:13px;color:{timer_status_color}">{'Yes' if timer_active else 'No'}</td>
        </tr>
        <tr>
          <td style="padding:5px 12px;font-size:13px;color:{GRAY}">Last Run</td>
          <td style="padding:5px 12px;font-size:13px;color:{GRAY}">{svc.get('ExecMainExitTimestamp','unknown')}</td>
        </tr>
      </table>"""

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
  {system_section}{backup_section}

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


SYS_METRICS_PATH = "/research/system/vps_health.json"
SYS_METRICS_MAX_AGE_MIN = 90


def _read_system_metrics() -> dict:
    """Read host system metrics from collector JSON, apply thresholds.
    Returns {"snapshot": dict|None, "alerts": list, "status": str}."""
    result = {"snapshot": None, "alerts": [], "status": "OK"}
    if not os.path.exists(SYS_METRICS_PATH):
        result["alerts"].append("CRIT: system metrics JSON missing")
        result["status"] = "CRIT"
        return result
    try:
        with open(SYS_METRICS_PATH) as f:
            data = json.load(f)
        result["snapshot"] = data
    except Exception as e:
        result["alerts"].append(f"CRIT: failed to parse system metrics JSON: {e}")
        result["status"] = "CRIT"
        return result

    # Staleness check
    try:
        collected = datetime.fromisoformat(data["collected_at"])
        age_min = (datetime.now(timezone.utc) - collected).total_seconds() / 60
        if age_min > SYS_METRICS_MAX_AGE_MIN:
            result["alerts"].append(f"WARN: system metrics stale ({age_min:.0f} min > {SYS_METRICS_MAX_AGE_MIN} max)")
            if result["status"] == "OK":
                result["status"] = "WARN"
    except Exception as e:
        result["alerts"].append(f"CRIT: cannot parse collected_at: {e}")
        result["status"] = "CRIT"

    # Disk thresholds
    disk = data.get("disk", [])
    if isinstance(disk, list):
        for m in disk:
            try:
                pct = float(m.get("pct_used", 0))
                if pct >= 95:
                    result["alerts"].append(f"CRIT: disk {m['mount']} at {pct}%")
                    result["status"] = "CRIT"
                elif pct >= 85:
                    result["alerts"].append(f"WARN: disk {m['mount']} at {pct}%")
                    if result["status"] == "OK":
                        result["status"] = "WARN"
            except (ValueError, KeyError):
                pass

    # Memory thresholds
    mem = data.get("memory", {})
    if "error" not in mem:
        try:
            pct_avail = float(mem.get("pct_available", 100))
            if pct_avail < 5:
                result["alerts"].append(f"CRIT: memory {pct_avail}% available")
                result["status"] = "CRIT"
            elif pct_avail < 10:
                result["alerts"].append(f"WARN: memory {pct_avail}% available")
                if result["status"] == "OK":
                    result["status"] = "WARN"
        except (ValueError, TypeError):
            pass

    # Load thresholds
    ld = data.get("load", {})
    if "error" not in ld:
        try:
            load_1m = float(ld.get("load_1m", 0))
            cores = int(ld.get("cores", 1))
            if load_1m > cores * 2:
                result["alerts"].append(f"CRIT: load 1m {load_1m:.1f} > {cores*2} (2× cores)")
                result["status"] = "CRIT"
            elif load_1m > cores:
                result["alerts"].append(f"WARN: load 1m {load_1m:.1f} > {cores} cores")
                if result["status"] == "OK":
                    result["status"] = "WARN"
        except (ValueError, TypeError):
            pass

    # Docker — flag containers not running/Up
    dock = data.get("docker", {})
    if "error" not in dock:
        containers = dock.get("containers", {})
        non_running = {n: s for n, s in containers.items()
                       if not s.startswith("Up")}
        if non_running:
            result["alerts"].append(f"WARN: {len(non_running)} container(s) not running: {non_running}")
            if result["status"] == "OK":
                result["status"] = "WARN"

    # Backup — flag failures / stale (> 48h)
    bup = data.get("backup", {})
    bup_svc = bup.get("service", {})
    if bup_svc.get("Result") and bup_svc["Result"] != "success":
        result["alerts"].append(f"CRIT: drive-backup failed ({bup_svc['Result']})")
        result["status"] = "CRIT"
    if not bup.get("timer_active"):
        result["alerts"].append("CRIT: drive-backup timer not active")
        result["status"] = "CRIT"

    return result


def main(gmail_smtp: dict = {}, recipient_email: str = "", portfolio_db: dict = {}, wm_token: str = "", deepseek_key: str = ""):
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

    # ── Read system metrics (host-collected) ──────────────────────────────────
    system_metrics = _read_system_metrics()

    front_matter = _build_front_matter(
        tg_date=now_sgt.strftime("%-d %b"),
        ok_count=ok_count, total=total,
        fm_rows=fm_rows, token_usage=token_usage,
        outbox_rows=outbox_rows, diagnoses=diagnoses,
        spec_checks=spec_checks, content_inventory=content_inventory,
    )
    front_matter["system"] = system_metrics.get("snapshot", {})
    front_matter["backup"] = system_metrics.get("snapshot", {}).get("backup", {})

    # ── Build HTML email from single source (front_matter drives shared fields) ─
    subject = f"Health Check — {now_sgt.strftime('%-d %b %Y')} | {ok_count}/{total} OK"
    html = build_html(rows, now_sgt, ok_count, total, llm_rows, total_prompt, total_completion,
                      total_cost, sent_subjects, EXTRA_CATEGORIES,
                      system_data=front_matter.get("system"),
                      backup_data=front_matter.get("backup"),
                      spec_checks=front_matter["spec_checks"],
                      diagnoses=front_matter["diagnoses"])

    _send_email(gmail_smtp, recipient_email, subject, html)

    log.info(f"Status: {ok_count}/{total} OK")
    log.info(f"Sent emails found in outbox: {len(sent_subjects)}")
    if total_prompt or total_completion:
        log.info(f"Tokens: {total_prompt:,} prompt + {total_completion:,} completion · est. ${total_cost:.4f}")

    # ── Tier 0 — production artifact verification ────────────────────────────
    # Fetch actual delivered email bodies and check for structural markers.
    # Non-blocking: failures are logged and written to DB but do not abort the run.
    if gmail_smtp:
        tier0_results = []
        for sched in SCHEDULES:
            if not sched.get("email_match"):
                continue  # schedule doesn't send email — skip
            label = sched["label"]
            # Match schedule label to ARTIFACT_MARKERS key via substring
            marker_key = next((k for k in ARTIFACT_MARKERS if k.lower() in label.lower()
                                or label.lower() in k.lower()), None)
            if not marker_key:
                continue
            try:
                kw = sched["email_match"][0] if sched["email_match"] else ""
                body = _fetch_sent_body(gmail_smtp, kw, hours=25)
                if body is None:
                    log.info(f"[Tier0] {label}: no email found in last 25h")
                    tier0_results.append({"label": label, "pass": None, "missing": [], "note": "no_email"})
                    _write_artifact_verification(portfolio_db, label, False, ["email_not_found"], kw)
                else:
                    check = _artifact_body_check(body, ARTIFACT_MARKERS[marker_key])
                    tier0_results.append({"label": label, **check})
                    if check["pass"]:
                        log.info(f"[Tier0] {label}: OK — all {len(check['found'])} markers present")
                    else:
                        log.warning(f"[Tier0] {label}: FAIL — missing markers: {check['missing']}")
                    _write_artifact_verification(portfolio_db, label, check["pass"],
                                                  check["missing"], kw)
            except Exception as t0_exc:
                log.warning(f"[Tier0] {label}: check failed: {t0_exc}")
        if tier0_results:
            passed = sum(1 for r in tier0_results if r.get("pass") is True)
            log.info(f"[Tier0] {passed}/{len(tier0_results)} scripts passed artifact body check")

    # ── Write canonical .md (comprehensive deterministic report) ──────────────
    md_path = f"/research/health/{now_sgt.strftime('%Y-%m-%d_%H%M')}.md"
    md_content = _build_md_content(front_matter)
    _write_canonical_md(md_content, md_path)

    return {
        "ok_count":   ok_count,
        "total":      total,
        "rows":       rows,
        "llm_rows":   llm_rows,
        "total_cost": round(total_cost, 4),
    }
