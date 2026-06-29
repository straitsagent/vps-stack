import html as html_mod
import json
import os
import smtplib
import urllib.parse
import feedparser
import requests
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from openai import OpenAI
from typing import TypedDict
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
RAPIDAPI_HOST = "youtube-transcribe-fastest-youtube-transcriber.p.rapidapi.com"


WM_BASE_DISPATCH  = os.environ.get("WM_BASE_URL", "http://windmill_server:8000")
WM_WORKSPACE_DISPATCH = "admins"

TRANSCRIPT_MAX_CHARS = 8000
MAX_STATE_IDS = 1000
MAX_ATTEMPTS = 3
WM_BASE_URL = os.environ.get("WM_BASE_URL", "http://windmill_server:8000")
STATE_VAR = "u/admin/youtube_processed_state"

ARTIFACT_MARKERS: dict[str, list[str]] = {
    "YouTube Monitor": ["channel", "transcript"],
}

# ── State-based deduplication ────────────────────────────────────────────────

def _wm_headers() -> dict:
    token = os.environ.get("WM_TOKEN", "")
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def load_state() -> tuple[set, dict]:
    """Returns (processed_ids, attempt_counts). Handles legacy flat-list format."""
    try:
        resp = requests.get(
            f"{WM_BASE_URL}/api/w/admins/variables/get_value/{STATE_VAR}",
            headers=_wm_headers(), timeout=10,
        )
        if resp.status_code == 200:
            data = json.loads(resp.json())
            if isinstance(data, list):
                return set(data), {}
            elif isinstance(data, dict):
                return set(data.get("processed", [])), data.get("attempts", {})
    except Exception as e:
        log.warning(f"Warning: Could not load state: {e}")
    return set(), {}


def save_state(processed_ids: set, attempt_counts: dict):
    combined = list(processed_ids)
    if len(combined) > MAX_STATE_IDS:
        combined = combined[-MAX_STATE_IDS:]
    try:
        requests.post(
            f"{WM_BASE_URL}/api/w/admins/variables/update/{STATE_VAR}",
            headers=_wm_headers(), timeout=10,
            json={"value": json.dumps({"processed": combined, "attempts": attempt_counts})},
        )
    except Exception as e:
        log.warning(f"Warning: Could not save state: {e}")


# ── RSS ──────────────────────────────────────────────────────────────────────

def extract_video_id(entry) -> str | None:
    if hasattr(entry, "yt_videoid") and entry.yt_videoid:
        return entry.yt_videoid
    entry_id = entry.get("id", "")
    if entry_id.startswith("yt:video:"):
        return entry_id.replace("yt:video:", "")
    link = entry.get("link", "")
    if "v=" in link:
        return link.split("v=")[1].split("&")[0]
    return None


def fetch_fresh_videos(feeds: list, processed_ids: set, cutoff: datetime) -> list:
    fresh = []
    for feed_info in feeds:
        try:
            parsed = feedparser.parse(
                feed_info["rss_url"],
                request_headers={"User-Agent": "Mozilla/5.0"},
            )
            for entry in parsed.entries:
                video_id = extract_video_id(entry)
                if not video_id or video_id in processed_ids:
                    continue
                pub_time = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    pub_time = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                if pub_time and pub_time < cutoff:
                    continue
                fresh.append({
                    "video_id": video_id,
                    "channel_name": feed_info["channel_name"],
                    "title": entry.get("title", "Untitled").strip(),
                    "watch_url": f"https://www.youtube.com/watch?v={video_id}",
                    "published_at": pub_time,
                })
        except Exception as e:
            log.warning(f"Warning: RSS fetch failed for {feed_info['channel_name']}: {e}")

    fresh.sort(
        key=lambda x: x["published_at"] or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return fresh


# ── Transcript ───────────────────────────────────────────────────────────────

def get_transcript(video_id: str, watch_url: str, rapidapi_key: str) -> str | None:
    try:
        encoded_url = urllib.parse.quote(watch_url, safe="")
        url = f"https://{RAPIDAPI_HOST}/transcript?url={encoded_url}&video_id={video_id}&lang=en"
        resp = requests.get(
            url,
            headers={
                "x-rapidapi-host": RAPIDAPI_HOST,
                "x-rapidapi-key": rapidapi_key,
                "Content-Type": "application/json",
            },
            timeout=30,
        )
        data = resp.json()
        if data.get("status") == "success":
            return data["data"]["text"][:TRANSCRIPT_MAX_CHARS]
    except Exception as e:
        log.warning(f"Warning: Transcript failed for {video_id}: {e}")
    return None


# ── Summarise ────────────────────────────────────────────────────────────────

def summarize(client: OpenAI, title: str, transcript: str) -> tuple[str, int, int]:
    prompt = (
        "Summarise the following YouTube video transcript in 4-6 sentences. "
        "Cover the main topic, key points, and any notable conclusions or "
        "recommendations. Be concise and factual.\n\n"
        f"Title: {title}\n\n{transcript}"
    )
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=400,
        )
        usage = response.usage
        return (
            response.choices[0].message.content.strip(),
            usage.prompt_tokens if usage else 0,
            usage.completion_tokens if usage else 0,
        )
    except Exception as e:
        return f"(Summary unavailable: {e})", 0, 0


# ── Email ────────────────────────────────────────────────────────────────────

def build_email_html(videos: list, synthesis: str, prompt_tokens: int, completion_tokens: int) -> str:
    now_sgt = datetime.now(SGT).strftime("%d %b %Y, %H:%M SGT")
    summarised = [v for v in videos if v.get("summary")]
    bare = [v for v in videos if not v.get("summary")]
    n_summarised = len(summarised)
    n_bare = len(bare)
    est_cost = (prompt_tokens / 1_000_000) * 0.14 + (completion_tokens / 1_000_000) * 0.28

    counts = f'{n_summarised} summarised'
    if n_bare:
        counts += f', {n_bare} no transcript'

    S = '<html><body style="font-family:Arial,sans-serif;max-width:680px;margin:0 auto;color:#333;padding:20px;">'
    S += f'<h2 style="color:#2c3e50;border-bottom:2px solid #c0392b;padding-bottom:8px;">YouTube Digest — {now_sgt}</h2>'
    S += (
        f'<p style="color:#aaa;font-size:11px;margin:0 0 20px;">'
        f'deepseek-chat · {counts} · '
        f'{prompt_tokens:,} prompt + {completion_tokens:,} completion tokens · '
        f'est. ${est_cost:.4f}</p>'
    )

    if synthesis:
        _paras = [p.strip() for p in synthesis.split("\n\n") if p.strip()]
        S += '<div style="margin:0 0 24px;padding:16px 18px;background:#f7f9fb;border-left:4px solid #2c3e50;">'
        S += '<p style="margin:0 0 10px;font-size:13px;font-weight:bold;color:#2c3e50;text-transform:uppercase;letter-spacing:0.5px;">Daily Synthesis</p>'
        for _p in _paras:
            S += f'<p style="margin:0 0 10px;font-size:13px;color:#444;line-height:1.6;">{html_mod.escape(_p)}</p>'
        S += '</div>'

    for v in summarised:
        pub_sgt = v["published_at"].astimezone(SGT).strftime("%H:%M SGT") if v["published_at"] else ""
        S += '<div style="margin-bottom:24px;padding:14px 16px;border-left:3px solid #c0392b;background:#fafafa;">'
        S += f'<p style="margin:0 0 3px;font-size:11px;color:#888;text-transform:uppercase;letter-spacing:0.5px;">{html_mod.escape(v["channel_name"])}</p>'
        S += f'<p style="margin:0 0 4px;font-size:14px;font-weight:bold;"><a href="{v["watch_url"]}" style="color:#2c3e50;text-decoration:none;">{html_mod.escape(v["title"])}</a></p>'
        if pub_sgt:
            S += f'<p style="margin:0 0 4px;font-size:11px;color:#aaa;">Published: {pub_sgt}</p>'
        S += f'<p style="margin:0 0 8px;font-size:11px;"><a href="{v["watch_url"]}" style="color:#c0392b;text-decoration:none;">{v["watch_url"]}</a></p>'
        S += f'<p style="margin:0;font-size:13px;color:#555;line-height:1.6;">{html_mod.escape(v["summary"])}</p>'
        S += '</div>'

    if bare:
        S += '<p style="font-size:12px;color:#aaa;margin:20px 0 8px;text-transform:uppercase;letter-spacing:0.5px;">No transcript available</p>'
        for v in bare:
            pub_sgt = v["published_at"].astimezone(SGT).strftime("%H:%M SGT") if v["published_at"] else ""
            S += '<div style="margin-bottom:12px;padding:10px 14px;border-left:3px solid #ccc;background:#fafafa;">'
            S += f'<p style="margin:0 0 2px;font-size:11px;color:#aaa;text-transform:uppercase;letter-spacing:0.5px;">{html_mod.escape(v["channel_name"])}</p>'
            S += f'<p style="margin:0 0 3px;font-size:13px;font-weight:bold;"><a href="{v["watch_url"]}" style="color:#2c3e50;text-decoration:none;">{html_mod.escape(v["title"])}</a></p>'
            if pub_sgt:
                S += f'<p style="margin:0 0 3px;font-size:11px;color:#aaa;">Published: {pub_sgt}</p>'
            S += f'<p style="margin:0;font-size:11px;"><a href="{v["watch_url"]}" style="color:#aaa;text-decoration:none;">{v["watch_url"]}</a></p>'
            S += '</div>'

    S += '<hr style="margin-top:30px;border:none;border-top:1px solid #eee;">'
    S += '<p style="color:#bbb;font-size:11px;">Windmill · straitsagent@gmail.com</p>'
    S += '</body></html>'
    return S


# ── 24h synthesis ────────────────────────────────────────────────────────────

_SYNTHESIS_PROMPT = (
    "You are a financial media analyst. Below are YouTube video summaries published in the last "
    "24 hours across investment-focused channels. Write a comprehensive 600-700 word digest covering: "
    "(1) the main investment themes and market narratives discussed, (2) specific stocks, sectors, "
    "or macro trends highlighted across videos, (3) key takeaways and what is most actionable for "
    "an equity portfolio weighted heavily to US and Hong Kong tech. Be specific — name the stocks, "
    "quote the arguments, and assess whether the collective signal is bullish, bearish, or mixed. "
    "No preamble, no bullet points, no headers — continuous analytical prose only.\n\nVideos:\n{videos}"
)


def _collect_24h_videos(md_dir: str, current_videos: list) -> list:
    """Return deduplicated list of all videos from .md files in md_dir modified in last 24h,
    merged with current_videos (the just-processed batch not yet written to disk)."""
    import re as _re
    cutoff = datetime.now(SGT).timestamp() - 86400
    seen_urls: set = set()
    all_videos: list = []
    for v in current_videos:
        url = v.get("watch_url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            all_videos.append(v)
    if os.path.isdir(md_dir):
        for fname in sorted(os.listdir(md_dir)):
            if not fname.endswith(".md"):
                continue
            fpath = os.path.join(md_dir, fname)
            try:
                if os.path.getmtime(fpath) < cutoff:
                    continue
                content = open(fpath).read()
                fm_match = _re.search(r"```json\s*\n([\s\S]*?)\n```", content)
                if not fm_match:
                    continue
                fm = json.loads(fm_match.group(1))
                for v in fm.get("videos", []):
                    url = v.get("watch_url", "")
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        all_videos.append(v)
            except Exception:
                continue
    return all_videos


def _synthesise_24h(videos: list, deepseek_key: str) -> str:
    """Generate ≥500-word 24h YouTube digest via Deepseek. Returns empty string on failure."""
    summarised = [v for v in videos if v.get("summary") and "[No transcript" not in v.get("summary", "")]
    if not summarised:
        return ""
    video_lines = []
    for v in summarised:
        title   = v.get("title", "Untitled")
        channel = v.get("channel_name", "")
        summary = v.get("summary", "").strip()
        video_lines.append(f"**{title}** ({channel})\n{summary}")
    prompt = _SYNTHESIS_PROMPT.format(videos="\n\n".join(video_lines))
    try:
        client = OpenAI(api_key=deepseek_key, base_url="https://api.deepseek.com")
        r = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=1400,
        )
        return r.choices[0].message.content.strip()
    except Exception as e:
        log.warning(f"[Synthesise24h] Deepseek synthesis failed: {e}")
        return ""


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


def _send_email(smtp_resource: dict, recipient_email: str, subject: str, html: str) -> None:
    username = smtp_resource["username"]
    password = smtp_resource["password"]
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = username
    msg["To"] = recipient_email
    msg.attach(MIMEText(html, "html"))
    with smtplib.SMTP(smtp_resource["host"], smtp_resource["port"]) as server:
        server.starttls()
        server.login(username, password)
        server.sendmail(username, [recipient_email], msg.as_string())
    log.info(f"Sent: {subject}")


def _write_canonical_md(content: str, path: str) -> None:
    with open(path, "w") as f:
        f.write(content)


def main(
    smtp_resource: smtp,
    deepseek_key: str,
    rapidapi_key: str,
    youtube_feeds: str,
    recipient_email: str = "",
    telegram_bot_token: str = "",
    telegram_owner_id: str = "",
    portfolio_db: dict = {},
    wm_token: str = "",
):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    feeds = json.loads(youtube_feeds)

    log.info(f"Loaded {len(feeds)} channels")

    log.info("Loading dedup state...")
    processed_ids, attempt_counts = load_state()
    log.info(f"  {len(processed_ids)} processed, {len(attempt_counts)} pending retry")

    log.info("Scanning RSS feeds...")
    fresh_videos = fetch_fresh_videos(feeds, processed_ids, cutoff)
    log.info(f"  {len(fresh_videos)} fresh videos found")

    if not fresh_videos:
        log.warning("Nothing new — skipping email.")
        return {"status": "no_new_videos", "channels_checked": len(feeds)}

    client = OpenAI(api_key=deepseek_key, base_url="https://api.deepseek.com")
    total_prompt_tokens = 0
    total_completion_tokens = 0

    results = []
    newly_processed_ids = []
    for v in fresh_videos:
        log.info(f"  [{v['channel_name']}] {v['title'][:60]}")
        transcript = get_transcript(v["video_id"], v["watch_url"], rapidapi_key)
        if transcript:
            summary, pt, ct = summarize(client, v["title"], transcript)
            total_prompt_tokens += pt
            total_completion_tokens += ct
            results.append({**v, "summary": summary})
            newly_processed_ids.append(v["video_id"])
            attempt_counts.pop(v["video_id"], None)
        else:
            attempts = attempt_counts.get(v["video_id"], 0) + 1
            attempt_counts[v["video_id"]] = attempts
            log.info(f"    No transcript (attempt {attempts}/{MAX_ATTEMPTS})")
            if attempts >= MAX_ATTEMPTS:
                results.append({**v, "summary": None})
                newly_processed_ids.append(v["video_id"])
                attempt_counts.pop(v["video_id"], None)
                log.info(f"    Max attempts reached — including as bare link")

    log.info("Saving dedup state...")
    save_state(processed_ids | set(newly_processed_ids), attempt_counts)

    if not results:
        log.info("No results to email (all pending retry).")
        return {"status": "pending_retry", "channels_checked": len(feeds), "retrying": len(attempt_counts)}

    now_sgt = datetime.now(SGT).strftime("%d %b %Y, %H:%M SGT")
    n_summarised = sum(1 for v in results if v.get("summary"))
    n_bare = len(results) - n_summarised

    est_cost = (total_prompt_tokens / 1_000_000) * 0.14 + (total_completion_tokens / 1_000_000) * 0.28
    log.info(f"Deepseek: {total_prompt_tokens:,} prompt + {total_completion_tokens:,} completion tokens · est. ${est_cost:.4f}")

    # ── Write canonical .md + dispatch idea_extractor ────────────────────────
    import os as _os
    _os.makedirs("/research/youtube", exist_ok=True)
    run_time = datetime.now(SGT)
    date_str = run_time.strftime("%-d %b")
    md_path = f"/research/youtube/{run_time.strftime('%Y-%m-%d_%H%M')}.md"

    # Build video list with summaries for front-matter
    fm_videos = []
    for v in results:
        fm_videos.append({
            "title":        v["title"],
            "watch_url":    v["watch_url"],
            "channel_name": v["channel_name"],
            "summary":      v.get("summary") or f"[No transcript available — bare link: {v['watch_url']}]",
        })

    front_matter = {
        "date_str":    date_str,
        "n_summarised": n_summarised,
        "videos":      fm_videos,
    }
    # Build per-video detail sections (go below <!-- DETAIL --> in archive)
    detail_sections = []
    for v in results:
        detail_sections.append(
            f"**[{v['title']}]({v['watch_url']})** — {v['channel_name']}\n\n"
            + (v.get("summary") or "_No transcript available_")
        )
    detail_block = "\n\n---\n\n".join(detail_sections)

    # Collect all 24h videos and synthesise into ≥500-word narrative
    log.info("[Synthesise24h] Collecting last-24h YouTube .md reports...")
    all_24h_videos = _collect_24h_videos("/research/youtube", fm_videos)
    log.info(f"[Synthesise24h] {len(all_24h_videos)} unique videos in last 24h")
    synthesis = _synthesise_24h(all_24h_videos, deepseek_key)
    if synthesis:
        log.info(f"[Synthesise24h] Synthesis generated ({len(synthesis.split())} words)")
    else:
        log.warning("[Synthesise24h] No synthesis generated — falling back to per-video summaries")
        synthesis = detail_block

    md_content = (
        f"```json\n{json.dumps(front_matter, indent=2)}\n```\n\n"
        f"{synthesis}\n\n"
        "<!-- DETAIL -->\n\n"
        f"{detail_block}\n"
    )
    _write_canonical_md(md_content, md_path)
    log.info(f"[md] Written {md_path}")

    # ── Send email (renders the .md synthesis + per-video list) ──────────────
    log.info("Sending email...")
    html = build_email_html(results, synthesis, total_prompt_tokens, total_completion_tokens)
    subject = f"YouTube Digest — {now_sgt} ({n_summarised} new)" + (f" + {n_bare} no transcript" if n_bare else "")
    _send_email(smtp_resource, recipient_email, subject, html)

    if portfolio_db and wm_token:
        _dispatch_idea_extractor(
            md_path, "youtube", portfolio_db, deepseek_key, wm_token,
        )

    return {
        "status": "sent",
        "channels_checked": len(feeds),
        "new_videos": n_summarised,
        "bare_link_videos": n_bare,
        "prompt_tokens": total_prompt_tokens,
        "completion_tokens": total_completion_tokens,
        "est_cost_usd": round(est_cost, 6),
    }
