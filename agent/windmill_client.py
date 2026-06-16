import asyncio
import json
from typing import Any, Optional

import httpx
from config import WM_BASE_URL, WM_TOKEN, WM_WORKSPACE

HEADERS = {"Authorization": f"Bearer {WM_TOKEN}", "Content-Type": "application/json"}


async def run_job(script_path: str, args: dict) -> str:
    """Dispatch a Windmill job and return the job_id UUID."""
    url = f"{WM_BASE_URL}/api/w/{WM_WORKSPACE}/jobs/run/p/{script_path}"
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(url, headers=HEADERS, json=args)
        r.raise_for_status()
    return r.text.strip().strip('"')


async def poll_job_result(job_id: str) -> Optional[dict]:
    """
    Returns the job result dict if completed, None if still running,
    raises on permanent failure.
    """
    url = f"{WM_BASE_URL}/api/w/{WM_WORKSPACE}/jobs_u/completed/get_result_maybe/{job_id}"
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url, headers=HEADERS)
    if r.status_code == 404:
        return None  # still running
    r.raise_for_status()
    data = r.json()
    # Windmill wraps completed results in {"result": ...} or {"error": ...}
    if isinstance(data, dict):
        if "error" in data:
            raise RuntimeError(data["error"])
        if "result" in data:
            return data["result"]
        # already unwrapped
        return data
    return data


async def run_sync(script_path: str, args: dict, timeout: int = 60) -> Any:
    """Run a Windmill job and wait for its result (blocking, up to timeout seconds)."""
    job_id = await run_job(script_path, args)
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(3)
        result = await poll_job_result(job_id)
        if result is not None:
            return result
    raise TimeoutError(f"Job {job_id} did not complete within {timeout}s")
