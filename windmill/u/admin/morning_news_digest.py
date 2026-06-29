import html as html_mod
import imaplib
import email
import os
import re
import smtplib
import feedparser
import requests
from email.header import decode_header
from email.utils import parsedate_to_datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone
from typing import TypedDict
from openai import OpenAI
import logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
log = logging.getLogger(__name__)



class smtp(TypedDict):
    host: str
    port: int
    username: str
    password: str
    tls_implicit: bool


SGT = timezone(timedelta(hours=8))
HEADLINE_LIMIT = 5

WM_BASE_DISPATCH  = os.environ.get("WM_BASE_URL", "http://windmill_server:8000")
WM_WORKSPACE_DISPATCH = "admins"


def _dispatch_idea_extractor(md_path: str, source: str,
                              portfolio_db: dict, deepseek_key: str,
                              wm_token: str = "") -> str:
    """Dispatch idea_extractor fire-and-forget. Returns job_id or ''."""
    token = wm_token or os.environ.get("WM_TOKEN", "")
    if not token:
        log.warning("[Dispatch] No WM_TOKEN — cannot dispatch idea_extractor")
        return ""
    url = f"{WM_BASE_DISPATCH}/api/w/{WM_WORKSPACE_DISPATCH}/jobs/run/p/u/admin/idea_extractor"
    args = {
        "md_path": md_path,
        "source": source,
        "portfolio_db": portfolio_db,
        "deepseek_key": deepseek_key,
    }
    try:
        resp = requests.post(
            url, headers={"Authorization": f"Bearer {token}",
                          "Content-Type": "application/json"},
            json=args, timeout=10,
        )
        job_id = resp.text.strip().strip('"')
        log.info(f"[Dispatch] idea_extractor dispatched job_id={job_id}")
        return job_id
    except Exception as e:
        log.warning(f"[Dispatch] Failed to dispatch idea_extractor: {e}")
        return ""


# Section 1: key publication RSS feeds (48h cutoff)
HEADLINE_FEEDS = [
    ("Reuters",      "https://news.google.com/rss/search?q=site:reuters.com&hl=en&gl=SG&ceid=SG:en"),
    ("WSJ",          "https://news.google.com/rss/search?q=site:wsj.com&hl=en&gl=SG&ceid=SG:en"),
    ("Barron's",     "https://news.google.com/rss/search?q=site:barrons.com&hl=en&gl=SG&ceid=SG:en"),
    ("NYT World",    "https://rss.nytimes.com/services/xml/rss/nyt/World.xml"),
    ("NYT Business", "https://feeds.nytimes.com/nyt/rss/Business"),
    ("NYT Economy",  "https://rss.nytimes.com/services/xml/rss/nyt/Economy.xml"),
]

# Section 2: Google News keyword searches (48h cutoff)
GOOGLE_NEWS_FEEDS = [
    ("LNG Asia",                    "https://news.google.com/rss/search?q=LNG+Asia&hl=en&gl=SG&ceid=SG:en"),
    ("Infrastructure Finance APAC", "https://news.google.com/rss/search?q=infrastructure+finance+APAC&hl=en&gl=SG&ceid=SG:en"),
    ("Data Centre Singapore",       "https://news.google.com/rss/search?q=data+centre+Singapore&hl=en&gl=SG&ceid=SG:en"),
]

# Sections 3/4: key newsletter sender domains
KEY_DOMAINS = ["reuters.com", "interactive.wsj.com", "barrons.com", "nytimes.com", "marketwatchmail.com"]

DOMAIN_DISPLAY = {
    "reuters.com":        "Reuters",
    "interactive.wsj.com": "WSJ",
    "barrons.com":        "Barron's",
    "nytimes.com":        "NYT",
    "marketwatchmail.com": "MarketWatch",
}


# ── Helpers ─────────────────────────────────────────────────────────────────

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
                except Exception as _exc:
                    log.warning("Suppressed: %s", _exc)
            elif ct == "text/html" and not body:
                try:
                    html = part.get_payload(decode=True).decode(
                        part.get_content_charset() or "utf-8", errors="replace"
                    )
                    html = re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=re.DOTALL | re.IGNORECASE)
                    html = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
                    body = re.sub(r"<[^>]+>", " ", html)
                    body = re.sub(r"\s+", " ", body).strip()
                except Exception as _exc:
                    log.warning("Suppressed: %s", _exc)
    else:
        try:
            body = msg.get_payload(decode=True).decode(
                msg.get_content_charset() or "utf-8", errors="replace"
            )
        except Exception as _exc:
            log.warning("Suppressed: %s", _exc)
    return body[:3000]


_LINK_SKIP = ("unsubscribe", "optout", "opt-out", "track.", "click.", "open.", "pixel", "beacon", "mailto:", "tel:", "javascript:")
_LINK_SKIP_EXT = (".jpg", ".jpeg", ".png", ".gif", ".svg", ".ico", ".webp")

def get_links(msg):
    html = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                try:
                    html = part.get_payload(decode=True).decode(
                        part.get_content_charset() or "utf-8", errors="replace"
                    )
                    break
                except Exception as _exc:
                    log.warning("Suppressed: %s", _exc)
    elif msg.get_content_type() == "text/html":
        try:
            html = msg.get_payload(decode=True).decode(
                msg.get_content_charset() or "utf-8", errors="replace"
            )
        except Exception as _exc:
            log.warning("Suppressed: %s", _exc)
    if not html:
        return []
    links = []
    seen = set()
    for m in re.finditer(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.DOTALL | re.IGNORECASE):
        url = m.group(1).strip()
        title = re.sub(r"<[^>]+>", "", m.group(2))
        title = re.sub(r"\s+", " ", title).strip()
        url_lower = url.lower()
        if not url_lower.startswith("http"):
            continue
        if any(p in url_lower for p in _LINK_SKIP):
            continue
        if any(url_lower.endswith(ext) for ext in _LINK_SKIP_EXT):
            continue
        if len(title) < 10:
            continue
        if url in seen:
            continue
        seen.add(url)
        links.append({"title": title, "url": url})
        if len(links) >= 5:
            break
    return links


def sender_domain(from_str):
    m = re.search(r"@([\w.\-]+)", from_str)
    return m.group(1).lower() if m else ""


def is_key_source(from_str):
    domain = sender_domain(from_str)
    return any(kd in domain for kd in KEY_DOMAINS)


def domain_display_name(from_str):
    domain = sender_domain(from_str)
    for kd, name in DOMAIN_DISPLAY.items():
        if kd in domain:
            return name
    return domain


def clean_sender_name(from_str):
    m = re.match(r'^"?([^"<]+)"?\s*<', from_str)
    if m:
        name = m.group(1).strip().strip('"')
        if name:
            return name
    m = re.search(r"[\w.\-]+@[\w.\-]+", from_str)
    return m.group(0) if m else from_str



# ── Data fetching ────────────────────────────────────────────────────────────

def fetch_rss_headlines(cutoff_hours=48):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=cutoff_hours)
    results = {}
    for source, url in HEADLINE_FEEDS:
        items = []
        try:
            feed = feedparser.parse(url, request_headers={"User-Agent": "Mozilla/5.0"})
            for entry in feed.entries:
                if len(items) >= HEADLINE_LIMIT:
                    break
                pub_time = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    pub_time = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                if pub_time and pub_time < cutoff:
                    continue
                title = entry.get("title", "").strip()
                if not title:
                    continue
                items.append({
                    "title": title,
                    "link": entry.get("link", ""),
                    "pub_time": pub_time.astimezone(SGT).strftime("%H:%M") if pub_time else "",
                })
        except Exception as e:
            log.warning(f"Warning: RSS fetch failed for {source}: {e}")
        if items:
            results[source] = items
    return results


def fetch_google_news(cutoff_hours=48):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=cutoff_hours)
    results = {}
    for keyword, url in GOOGLE_NEWS_FEEDS:
        items = []
        seen = set()
        try:
            feed = feedparser.parse(url, request_headers={"User-Agent": "Mozilla/5.0"})
            for entry in feed.entries:
                if len(items) >= HEADLINE_LIMIT:
                    break
                pub_time = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    pub_time = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                if pub_time and pub_time < cutoff:
                    continue
                title = entry.get("title", "").strip()
                if not title or title in seen:
                    continue
                seen.add(title)
                items.append({
                    "title": title,
                    "link": entry.get("link", ""),
                    "pub_time": pub_time.astimezone(SGT).strftime("%H:%M") if pub_time else "",
                })
        except Exception as e:
            log.warning(f"Warning: Google News fetch failed for {keyword}: {e}")
        if items:
            results[keyword] = items
    return results


def fetch_inbox_emails(username, password, cutoff_hours=24):
    imap = imaplib.IMAP4_SSL("imap.gmail.com", 993)
    imap.login(username, password)
    imap.select("INBOX")

    # SINCE is date-only — fetch wider window, then filter precisely
    since_date = (datetime.now(timezone.utc) - timedelta(hours=cutoff_hours + 24)).strftime("%d-%b-%Y")
    _, nums = imap.search(None, f"(SINCE {since_date})")

    cutoff = datetime.now(timezone.utc) - timedelta(hours=cutoff_hours)
    key_emails = []
    other_emails = []

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

        from_raw = decode_str(msg.get("From", ""))
        subject = decode_str(msg.get("Subject", "(no subject)"))
        time_sgt = msg_date.astimezone(SGT).strftime("%H:%M")

        record = {
            "from": from_raw,
            "subject": subject,
            "time": time_sgt,
            "body": get_body(msg),
            "links": get_links(msg),
            "timestamp": msg_date,
        }

        if is_key_source(from_raw):
            record["source_name"] = domain_display_name(from_raw)
            key_emails.append(record)
        else:
            record["sender_name"] = clean_sender_name(from_raw)
            other_emails.append(record)

    imap.logout()
    key_emails.sort(key=lambda x: x["timestamp"], reverse=True)
    other_emails.sort(key=lambda x: x["timestamp"], reverse=True)
    return key_emails, other_emails


def summarize_newsletter(client, newsletter):
    prompt = f"""Summarise this newsletter in 3-5 sentences. Cover the key events, market moves, deals, and policy changes. Be direct and factual, no filler.

From: {newsletter['from']}
Subject: {newsletter['subject']}
Content: {newsletter['body']}"""

    try:
        response = client.chat.completions.create(
            model="deepseek-v4-flash",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=400,
        )
        summary = response.choices[0].message.content.strip()
        usage = response.usage
        prompt_tokens = usage.prompt_tokens if usage else 0
        completion_tokens = usage.completion_tokens if usage else 0
        return summary, prompt_tokens, completion_tokens
    except Exception as e:
        return f"(Summary unavailable: {e})", 0, 0


# ── HTML builder ─────────────────────────────────────────────────────────────

def section_header(n, title):
    return f'<h3 style="color:#2c3e50;margin:28px 0 10px;font-size:15px;">{n}. {title}</h3>'


def source_label(text):
    return f'<p style="color:#888;font-size:11px;margin:14px 0 4px;text-transform:uppercase;letter-spacing:0.5px;">{text}</p>'


def headline_row(item):
    t = f'<span style="color:#aaa;font-size:12px;">{item["pub_time"]} &nbsp;</span>' if item.get("pub_time") else ""
    return f'<div style="margin-bottom:5px;">{t}<a href="{item["link"]}" style="color:#2c3e50;text-decoration:none;font-size:13px;">{item["title"]}</a></div>'


def build_html(rss_headlines, google_news, key_emails, ai_summaries, other_emails, date_str, usage=None):
    S = '<html><body style="font-family:Arial,sans-serif;max-width:680px;margin:0 auto;color:#333;padding:20px;">'
    S += f'<h2 style="color:#2c3e50;border-bottom:2px solid #2980b9;padding-bottom:8px;">Morning Digest — {date_str}</h2>'

    if usage:
        cost = (usage["prompt_tokens"] / 1_000_000) * 0.14 + (usage["completion_tokens"] / 1_000_000) * 0.28
        S += (
            f'<p style="color:#aaa;font-size:11px;margin:0 0 20px;">'
            f'deepseek-v4-flash · {usage["calls"]} calls · '
            f'{usage["prompt_tokens"]:,} prompt + {usage["completion_tokens"]:,} completion tokens · '
            f'est. ${cost:.4f}</p>'
        )

    # 1. Key Headlines — RSS
    S += section_header(1, "Key Headlines")
    if rss_headlines:
        for source, items in rss_headlines.items():
            S += source_label(source)
            for item in items:
                S += headline_row(item)
    else:
        S += '<p style="color:#888;font-size:13px;">No RSS headlines fetched.</p>'

    # 2. Google News Alerts
    S += section_header(2, "Google News Alerts")
    if google_news:
        for keyword, items in google_news.items():
            S += source_label(keyword)
            for item in items:
                S += headline_row(item)
    else:
        S += '<p style="color:#888;font-size:13px;">No Google News results.</p>'

    # 3. Newsletter Summaries
    S += section_header(3, "Newsletter Summaries")
    if key_emails:
        for i, e in enumerate(key_emails):
            summary = ai_summaries.get(i, "(no summary)")
            links = e.get("links", [])
            S += '<div style="margin-bottom:16px;padding:12px 14px;border-left:3px solid #2980b9;background:#fafafa;">'
            S += f'<p style="margin:0 0 3px;font-size:11px;color:#888;text-transform:uppercase;letter-spacing:0.5px;">{e["source_name"]} · {e["time"]} SGT</p>'
            S += f'<p style="margin:0 0 8px;font-size:13px;font-weight:bold;color:#2c3e50;">{html_mod.escape(e["subject"])}</p>'
            S += f'<p style="margin:0 0 8px;font-size:13px;color:#555;line-height:1.6;">{html_mod.escape(summary)}</p>'
            if links:
                S += '<div style="margin-top:8px;padding-top:8px;border-top:1px solid #e8e8e8;">'
                for link in links:
                    S += f'<div style="margin-bottom:4px;font-size:12px;"><a href="{html_mod.escape(link["url"])}" style="color:#2980b9;text-decoration:none;">{html_mod.escape(link["title"])}</a></div>'
                S += '</div>'
            S += '</div>'
    else:
        S += '<p style="color:#888;font-size:13px;">No key source newsletters in the last 24 hours.</p>'

    # 4. Other Inbox Items
    S += section_header(4, "Other Inbox Items")
    if other_emails:
        for e in other_emails:
            S += f'<div style="margin-bottom:4px;font-size:13px;color:#555;">{e["time"]} SGT &nbsp;·&nbsp; <span style="color:#2c3e50;">{html_mod.escape(e["sender_name"])}</span> — {html_mod.escape(e["subject"])}</div>'
    else:
        S += '<p style="color:#888;font-size:13px;">No other emails.</p>'

    S += '<hr style="margin-top:30px;border:none;border-top:1px solid #eee;">'
    S += '<p style="color:#bbb;font-size:11px;">Windmill · straitsagent@gmail.com</p>'
    S += '</body></html>'
    return S


# ── Main ─────────────────────────────────────────────────────────────────────

def main(
    smtp_resource: smtp,
    deepseek_key: str,
    recipient_email: str = "",
    telegram_bot_token: str = "",
    telegram_owner_id: str = "",
    portfolio_db: dict = {},
    wm_token: str = "",
):
    date_str = datetime.now(SGT).strftime("%A, %d %B %Y")

    log.info("Fetching RSS headlines...")
    rss_headlines = fetch_rss_headlines(cutoff_hours=24)

    log.info("Fetching Google News...")
    google_news = fetch_google_news(cutoff_hours=24)

    log.info("Reading inbox...")
    username = smtp_resource["username"]
    password = smtp_resource["password"]
    key_emails, other_emails = fetch_inbox_emails(username, password, cutoff_hours=24)
    log.info(f"  {len(key_emails)} key newsletters, {len(other_emails)} other emails")

    log.info("Generating AI summaries...")
    client = OpenAI(api_key=deepseek_key, base_url="https://api.deepseek.com")
    ai_summaries = {}
    total_prompt_tokens = 0
    total_completion_tokens = 0
    for i, e in enumerate(key_emails):
        log.info(f"  [{i+1}/{len(key_emails)}] {e['subject'][:60]}")
        summary, pt, ct = summarize_newsletter(client, e)
        ai_summaries[i] = summary
        total_prompt_tokens += pt
        total_completion_tokens += ct

    n_calls = len(key_emails)
    est_cost = (total_prompt_tokens / 1_000_000) * 0.14 + (total_completion_tokens / 1_000_000) * 0.28
    log.info(f"API usage: {n_calls} calls · {total_prompt_tokens:,} prompt + {total_completion_tokens:,} completion tokens · est. ${est_cost:.4f}")
    usage = {"calls": n_calls, "prompt_tokens": total_prompt_tokens, "completion_tokens": total_completion_tokens}

    html = build_html(
        rss_headlines,
        google_news,
        key_emails,
        ai_summaries,
        other_emails,
        date_str,
        usage=usage,
    )

    recipients = [r.strip() for r in recipient_email.split(",") if r.strip()]
    subject = f"Morning Digest — {date_str}"
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = username
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP(smtp_resource["host"], smtp_resource["port"]) as server:
        server.starttls()
        server.login(username, password)
        server.sendmail(username, recipients, msg.as_string())

    log.info(f"Sent: {subject}")

    # ── Write markdown digest ──────────────────────────────────────────────
    import os as _os
    _os.makedirs("/research/news", exist_ok=True)
    iso_date = datetime.now(SGT).strftime("%Y-%m-%d")
    md_path = f"/research/news/{iso_date}.md"
    md = [f"# Morning Digest — {date_str}", ""]
    if rss_headlines:
        md.append("## Headlines")
        md.append("")
        for source, items in rss_headlines.items():
            md.append(f"**{source}**")
            for item in items:
                t = f" ({item['pub_time']})" if item.get("pub_time") else ""
                md.append(f"- [{item['title']}]({item['link']}){t}")
            md.append("")
    if google_news:
        md.append("## Industry News")
        md.append("")
        for keyword, items in google_news.items():
            md.append(f"**{keyword}**")
            for item in items:
                t = f" ({item['pub_time']})" if item.get("pub_time") else ""
                md.append(f"- [{item['title']}]({item['link']}){t}")
            md.append("")
    if key_emails:
        md.append("## Newsletter Summaries")
        md.append("")
        for i, e in enumerate(key_emails):
            summary = ai_summaries.get(i, "")
            if summary:
                md.append(f"**{e.get('source_name', '')} — {e['subject'][:80]}**")
                md.append("")
                md.append(summary)
                md.append("")
    with open(md_path, "w") as f:
        f.write("\n".join(md) + "\n")
    log.info(f"[md] Written {md_path}")

    if portfolio_db and wm_token:
        _dispatch_idea_extractor(
            md_path, "news", portfolio_db, deepseek_key, wm_token,
        )

    return {
        "status": "sent",
        "recipient": recipient_email,
        "rss_sources": len(rss_headlines),
        "google_news_keywords": len(google_news),
        "newsletters_summarised": len(key_emails),
        "other_inbox_items": len(other_emails),
        "api_calls": n_calls,
        "prompt_tokens": total_prompt_tokens,
        "completion_tokens": total_completion_tokens,
        "est_cost_usd": round(est_cost, 6),
    }
