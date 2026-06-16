"""
Async polling loop — checks running Windmill jobs every 5s and pushes results via Telegram.
"""
import asyncio
import json

import db
import telegram as meta
from config import ASYNC_POLL_INTERVAL
from tools import format_research_result
from windmill_client import poll_job_result


def _format_earnings_result(result: dict) -> str:
    """Read the report file written by earnings_analysis and return its content."""
    file_path = result.get("file_path", "")
    if file_path:
        try:
            with open(file_path) as fh:
                return fh.read()
        except OSError:
            pass
    ticker = result.get("ticker", "?")
    atype = result.get("analysis_type", "pre")
    label = "Pre-earnings briefing" if atype == "pre" else "Post-earnings analysis"
    return f"✅ {label} for {ticker} complete. Report saved to {file_path or 'unknown path'}."


async def _check_job(job: dict):
    job_id = job["job_id"]
    phone = job["wa_phone"]
    tool_name = job["tool_name"]

    try:
        result = await poll_job_result(job_id)
    except RuntimeError as e:
        await db.update_job_status(job_id, "failed", error_message=str(e))
        await meta.send_message(phone, f"❌ {tool_name} job failed: {e}")
        return
    except Exception as e:
        print(f"[poller] error polling {job_id}: {e}")
        return

    if result is None:
        return  # still running

    await db.update_job_status(job_id, "completed")

    if tool_name == "research":
        file_path = result.get("file_path", "")
        if file_path:
            try:
                with open(file_path) as fh:
                    text = fh.read()
            except OSError:
                text = format_research_result(result)
        else:
            text = format_research_result(result)
    elif tool_name == "earnings_analysis":
        text = _format_earnings_result(result)
    else:
        text = f"✅ {tool_name} completed.\n{json.dumps(result, default=str)[:500]}"

    MAX_MSG = 4000
    if len(text) <= MAX_MSG:
        await meta.send_message(phone, text)
    else:
        chunks = [text[i:i+MAX_MSG] for i in range(0, len(text), MAX_MSG)]
        for chunk in chunks:
            await meta.send_message(phone, chunk)
    await db.update_job_status(job_id, "delivered")


async def polling_loop():
    print("[poller] started")
    while True:
        try:
            jobs = await db.get_running_jobs()
            if jobs:
                await asyncio.gather(*[_check_job(j) for j in jobs], return_exceptions=True)
        except Exception as e:
            print(f"[poller] loop error: {e}")
        await asyncio.sleep(ASYNC_POLL_INTERVAL)
