# Implementation Log — YouTube Channel Monitor (Workflow 1.2)
**Date:** 2026-06-03 (initial build, evening session); improvements 2026-06-09
**Commits:** `<youtube_monitor initial>`, `<youtube url/token header>`, `<docs update>` (Jun 3); `6eb04f9`, `ea45b09`, `ac57bf`, `3366676`, `34f1b79` (Jun 9)
**Files changed:** `windmill/u/admin/youtube_monitor.py`, `windmill/u/admin/youtube_monitor.script.yaml`, `CLAUDE.md`, `docs/ROADMAP.md`

---

## Plan Completed

Built Workflow 1.2 — a YouTube channel monitor that scans 37 RSS feeds, retrieves transcripts via the RapidAPI YouTube transcript API, summarises each video with Deepseek deepseek-chat, and emails a batched digest. Deduplication via Windmill state variable. Scheduled initially hourly, later changed to 6-hourly. Retry logic added in the Jun 9 session after discovering transcripts can take 30-60 minutes to become available post-upload.

---

## All Tasks Performed

**Jun 3 — Initial build:**
1. User provided a Google Sheets/Drive spreadsheet containing YouTube RSS feed URLs for 37 channels
2. Stored feed list as Windmill variable `u/admin/youtube_feeds` (newline-delimited RSS URLs)
3. Built `youtube_monitor.py` — polls each RSS feed, checks for videos published within the lookback window, fetches transcripts via RapidAPI, summarises with Deepseek, emails digest
4. Implemented deduplication via Windmill state variable `youtube_processed_state` — flat list of processed video IDs
5. Added YouTube video URL and token cost header to digest email
6. Scheduled as hourly cron (`0 * * * *` SGT); lookback window set to 65 minutes to overlap the hourly boundary
7. Updated CLAUDE.md and ROADMAP.md: 1.2 live, variables logged

**Jun 9 — Reliability hardening:**
8. Changed schedule from hourly to 6-hourly (`0 0 */6 * * *` SGT) — reduces email volume for the user
9. Extended lookback window from 65 minutes to 6h5min to match new schedule interval (see Bug 1)
10. Extended lookback further to 24 hours to handle transcript availability delay (see Bug 2)
11. Changed processed-state logic: only mark a video as processed on successful transcript retrieval (see Bug 2)
12. Added retry counter to state dict — up to 3 attempts per video (~18h at 6h intervals); after 3 failures, include a bare YouTube URL in the digest (see Bug 3)
13. Upgraded state format from flat list to `{processed: [...], attempts: {video_id: count}}` dict with backward-compatible read (handles old flat-list state gracefully)
14. Updated docs: schedule, lookback window, retry logic all reflected in ROADMAP.md

---

## Bugs Encountered

**Bug 1 — 65-minute lookback window dropped videos after schedule change to 6-hourly**

Symptom: After changing the schedule from hourly to 6-hourly, the monitor silently skipped any video published more than 65 minutes before the job fired. A video published 2 hours before the run would never be seen — not in the current run (outside the 65-minute window) and not in a future run (the RSS feed would still list it but the window had passed).

Root cause: The lookback window was designed for an hourly schedule with a small overlap buffer. When the schedule interval was increased to 6 hours, the lookback window was not updated to match. The window and schedule interval must always be: `lookback > schedule_interval` to guarantee no gaps.

Fix: Extended lookback to 6h5min immediately after changing the schedule. Later extended further to 24h for transcript availability reasons (see Bug 2). The rule is: lookback window must always exceed the schedule interval.

---

**Bug 2 — Videos with unavailable transcripts were permanently skipped**

Symptom: New videos (particularly from channels that upload and process transcripts slowly) appeared in the RSS feed but never showed up in the digest. Investigation confirmed the videos existed but their transcripts returned a 404 or empty response from RapidAPI.

Root cause: The state variable recorded a video as processed on any fetch attempt — success or failure. YouTube transcripts typically take 15-60 minutes to become available after a video is published. A video published just before the hourly job fired would be attempted once, fail (transcript not yet ready), be marked as processed, and never retried.

Fix: Changed the state update logic to only mark a video as processed when a transcript is successfully retrieved and summarised. Failed fetches leave the video in an unprocessed state for subsequent runs. Also extended lookback to 24h to ensure videos remain eligible for retry across multiple run intervals even if the transcript takes longer than usual to appear.

---

**Bug 3 — No retry cap meant perpetually failing videos could accumulate in state**

Symptom: After fixing Bug 2, videos that had no transcript available (e.g. live streams, auto-captioning disabled, foreign-language videos) would be retried on every run indefinitely. The state variable would grow unboundedly, and the user would never know a video existed since it never appeared in the digest.

Root cause: The retry logic had no upper bound. A video that would never get a transcript (not just delayed, but genuinely unavailable) would be attempted forever. There was also no fallback — if a transcript is unavailable after reasonable retries, the user should still be able to find the video.

Fix: Added a retry counter in the state dict per video ID. After 3 failed attempts (~18h at 6h intervals), the video is included in the digest as a bare YouTube URL with a note that the transcript was unavailable. State format upgraded from flat list `[video_id, ...]` to `{"processed": [...], "attempts": {"video_id": count}}`. The read path handles old flat-list state for backward compatibility — any existing state is treated as a list of fully-processed IDs with zero failed attempts.

---

## Lessons Learned

1. When changing a schedule interval, the lookback window must be updated simultaneously. The invariant is: `lookback > schedule_interval`. These two values are coupled — changing one without the other silently drops content.
2. Processed/deduplication state must only be written on success, never on attempt. Writing state on attempt is a common pattern that turns transient failures (service unavailable, processing delay) into permanent skips.
3. Retry logic always needs an upper bound plus a fallback action. Open-ended retries cause unbounded state growth and leave the user with no visibility into permanently failing items. A capped retry with a degraded-mode output (bare URL) is better than either indefinite retry or permanent silence.
4. State schema migrations in long-running workflows need backward-compatible reads. The flat-list → dict upgrade would have crashed on first run if the read path didn't handle both formats. Always write migration-safe state readers when evolving state schemas.
5. External API availability windows (transcripts, article text, data feeds) are a schedule design input. A workflow that depends on post-processing of recently published content needs a lookback window and retry interval calibrated to the upstream processing delay — not just the schedule interval.
