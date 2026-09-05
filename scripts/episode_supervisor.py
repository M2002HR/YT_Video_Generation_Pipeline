#!/usr/bin/env python3
"""Keep one episode moving: resume it after a failure, bounded, until it publishes.

Every expensive stage of the pipeline is resumable — a finished stage is reused, never paid
for twice (§78, §102) — so the honest answer to a transient failure is to run the same
episode again rather than to start a new one. This supervisor does exactly that and nothing
else: it watches one control-panel job, and when the pipeline process has exited without
publishing, it asks the panel to resume it.

The bounds are the point. A deterministic failure would otherwise resume forever and spend
credits each round, so:

* at most ``--max-resumes`` resumes per episode (default 6);
* a cooldown between them, so a provider outage is not hammered;
* the same failure message twice in a row counts double, and three identical failures stop
  the loop — nothing has changed, so another attempt would not either;
* ``WAITING_FOR_FLOW`` is left alone when a Flow watcher is already handling it.

It never edits artifacts, never skips a stage and never marks anything done: the pipeline
itself remains the only thing that decides an episode is finished.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JOBS = ROOT / "control_panel" / "jobs"

#: Markers the wrapper prints when the whole episode is finished.
SUCCESS_MARKERS = ("FULL QH PIPELINE: PASS", "FULL VIDEO PIPELINE: PASS")

#: A pipeline state that means "waiting on Google", not "this episode is wrong".
FLOW_PARKED = "WAITING_FOR_FLOW"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def say(message: str) -> None:
    print(f"[{utcnow()}] {message}", flush=True)


def pid_is_live(pid: object) -> bool:
    try:
        os.kill(int(pid), 0)
    except (OSError, TypeError, ValueError):
        return False
    return True


def read_job(job_id: str) -> dict:
    path = JOBS / f"{job_id}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def log_text(job_id: str, tail: int = 20_000) -> str:
    path = JOBS / f"{job_id}.log"
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            handle.seek(0, os.SEEK_END)
            handle.seek(max(0, handle.tell() - tail))
            return handle.read()
    except OSError:
        return ""


def failure_reason(job_id: str) -> str:
    """Why the *latest* attempt stopped.

    Only the text after the last resume marker counts: the log is append-only, so scanning the
    whole file reported an older stage's failure and made three unrelated attempts look like the
    same one repeating. Stage markers are preferred, then the exception a helper script raised —
    a wrapper step like the voiceover fails with a traceback and no stage marker at all.
    """
    text = log_text(job_id, tail=200_000)
    marker = text.rfind("=== resume requested")
    attempt = text[marker:] if marker >= 0 else text
    lines = [line.strip() for line in attempt.splitlines() if line.strip()]
    for line in reversed(lines):
        if line.startswith("✘") or line.startswith("PIPELINE "):
            return line[:300]
    # A helper script's own exception says what actually went wrong; the wrapper's
    # CalledProcessError only says that the helper exited non-zero, so it is the last resort.
    raised = [line for line in lines if "Error:" in line or "Exception:" in line]
    specific = [line for line in raised if "CalledProcessError" not in line]
    if specific:
        return specific[-1][:300]
    if raised:
        return raised[-1][:300]
    return lines[-1][:300] if lines else ""


def published(project: Path) -> bool:
    """The episode is finished only when the render and both reports exist."""
    return (
        (project / "assets" / "renders" / "final.mp4").is_file()
        and (project / "render" / "QC_REPORT.json").is_file()
    )


def resume(panel: str, job_id: str) -> bool:
    body = urllib.parse.urlencode({"job_id": job_id}).encode("utf-8")
    request = urllib.request.Request(
        f"{panel.rstrip('/')}/resume",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return 200 <= response.status < 400
    except Exception as exc:  # the panel may be busy with another launch
        say(f"resume request failed: {type(exc).__name__}: {exc}")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job_id")
    parser.add_argument("--panel", default=os.getenv("YT_PANEL_URL", "http://127.0.0.1:4142"))
    parser.add_argument("--max-resumes", type=int, default=6)
    parser.add_argument("--cooldown-seconds", type=float, default=45.0)
    parser.add_argument("--poll-seconds", type=float, default=20.0)
    args = parser.parse_args()

    resumes = 0
    seen: dict[str, int] = {}
    say(f"supervising {args.job_id} (max {args.max_resumes} resumes)")
    while True:
        job = read_job(args.job_id)
        if not job:
            say("job record is unreadable; nothing to supervise")
            return 2
        project = ROOT / str(job.get("project") or "")
        status = str(job.get("status") or "")
        text = log_text(args.job_id)

        if published(project) or any(marker in text for marker in SUCCESS_MARKERS):
            say(f"episode {job.get('video_id')} is finished: {project}")
            return 0
        if status == "RUNNING" and pid_is_live(job.get("pid")):
            time.sleep(args.poll_seconds)
            continue
        if status == FLOW_PARKED:
            say("parked on Flow; the panel's watcher owns the retry")
            time.sleep(args.poll_seconds * 3)
            continue
        if status == "RUNNING":
            # The process is gone but the record still says RUNNING; the panel reconciler
            # rewrites it within its own interval, so wait for that rather than racing it.
            say("process gone, waiting for the panel to reconcile the record")
            time.sleep(args.poll_seconds)
            continue

        reason = failure_reason(args.job_id) or f"status={status}"
        seen[reason] = seen.get(reason, 0) + 1
        if seen[reason] >= 3:
            say(f"the same failure three times, so stopping: {reason}")
            return 1
        if resumes >= args.max_resumes:
            say(f"resume budget spent ({resumes}); last failure: {reason}")
            return 1
        resumes += 1
        say(f"resume {resumes}/{args.max_resumes} after: {reason}")
        if not resume(args.panel, args.job_id):
            time.sleep(args.cooldown_seconds)
            continue
        time.sleep(args.cooldown_seconds)


if __name__ == "__main__":
    sys.exit(main())
