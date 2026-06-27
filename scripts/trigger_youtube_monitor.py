#!/usr/bin/env python3
"""Trigger youtube_monitor with fully resolved args from Windmill."""
import json, urllib.request, os

WM_BASE = "http://localhost:8080"
WORKSPACE = "admins"

def wm_headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

def get_var(token, path):
    url = f"{WM_BASE}/api/w/{WORKSPACE}/variables/get_value/{path.replace('/', '%2F')}"
    req = urllib.request.Request(url, headers=wm_headers(token))
    with urllib.request.urlopen(req) as r:
        val = json.loads(r.read().decode())
    return val

def get_resource(token, path):
    url = f"{WM_BASE}/api/w/{WORKSPACE}/resources/get/{path.replace('/', '%2F')}"
    req = urllib.request.Request(url, headers=wm_headers(token))
    with urllib.request.urlopen(req) as r:
        res = json.loads(r.read().decode())
    return res["value"]

def main():
    # Read WM_TOKEN from agent.env
    token = None
    with open("/root/agent.env") as f:
        for line in f:
            if line.startswith("WM_TOKEN="):
                token = line.split("=", 1)[1].strip()
                break
    if not token:
        raise RuntimeError("WM_TOKEN not found in agent.env")

    print("Fetching variables...")
    youtube_feeds_raw = get_var(token, "u/admin/youtube_feeds")
    # youtube_feeds is stored as a JSON string containing the list
    if isinstance(youtube_feeds_raw, str):
        youtube_feeds_str = youtube_feeds_raw
    else:
        youtube_feeds_str = json.dumps(youtube_feeds_raw)

    args = {
        "smtp_resource":      get_resource(token, "u/admin/gmail_smtp"),
        "deepseek_key":       get_var(token, "u/admin/deepseek_key"),
        "rapidapi_key":       get_var(token, "u/admin/rapidapi_key"),
        "youtube_feeds":      youtube_feeds_str,
        "recipient_email":    get_var(token, "u/admin/recipient_email"),
        "telegram_bot_token": get_var(token, "u/admin/telegram_bot_token"),
        "telegram_owner_id":  get_var(token, "u/admin/telegram_owner_id"),
        "portfolio_db":       get_resource(token, "u/admin/portfolio_db"),
        "wm_token":           get_var(token, "u/admin/wm_token"),
    }

    print(f"Triggering youtube_monitor with {len(json.loads(youtube_feeds_str))} channels...")
    payload = json.dumps({"args": args}).encode()
    url = f"{WM_BASE}/api/w/{WORKSPACE}/jobs/run/p/u/admin/youtube_monitor"
    req = urllib.request.Request(url, data=payload, headers=wm_headers(token), method="POST")
    with urllib.request.urlopen(req) as r:
        job_id = r.read().decode().strip('"')
    print(f"Job ID: {job_id}")
    return job_id

if __name__ == "__main__":
    main()
