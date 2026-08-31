#!/usr/bin/env python3
"""Persistently schedule a panel launch five minutes after ChatGPT's reset."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

from pipeline_notifier import PipelineNotifier


ROOT = Path(__file__).resolve().parents[1]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("time must include a timezone")
    return parsed.astimezone(timezone.utc)


def main() -> None:
    parser = argparse.ArgumentParser(description="Schedule a paused image pipeline resume.")
    parser.add_argument("project", type=Path)
    parser.add_argument("--reset-at", help="UTC ISO reset time; initializes a pause record for a legacy failure.")
    parser.add_argument("--ordak-job-id")
    parser.add_argument("--beat-id", type=int)
    parser.add_argument("--message")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-notify", action="store_true", help="Used by boot reconciliation; avoids duplicate Telegram messages.")
    args = parser.parse_args()
    project = args.project.resolve()
    if ROOT not in project.parents:
        raise SystemExit("project must be inside this workspace")
    launch_path = project / "launch" / "LAUNCH_REQUEST.json"
    if not launch_path.is_file():
        raise SystemExit("launch request is required for scheduled resume")
    pause_path = project / "pipeline" / "IMAGE_LIMIT_SCHEDULE.json"
    if pause_path.is_file():
        pause = json.loads(pause_path.read_text(encoding="utf-8"))
    else:
        if not args.reset_at or not args.ordak_job_id or args.beat_id is None or not args.message:
            raise SystemExit("an existing pause record or reset-at, ordak-job-id, beat-id, and message is required")
        reset_at = parse_time(args.reset_at)
        pause = {"schema_version": 1, "status": "SCHEDULED", "reason": "chatgpt_image_generation_limit", "video_id": project.name.split("_", 1)[0], "beat_id": args.beat_id, "ordak_job_id": args.ordak_job_id, "limit_message": args.message, "detected_at": now(), "reset_at": reset_at.isoformat(), "resume_at": (reset_at + timedelta(minutes=5)).isoformat(), "buffer_minutes": 5}
    if pause.get("status") == "SCHEDULED" and pause.get("systemd_unit"):
        active = subprocess.run(["systemctl", "is-active", "--quiet", f"{pause['systemd_unit']}.timer"], check=False).returncode == 0
        if active:
            print(json.dumps({"status": "ALREADY_SCHEDULED", "unit": pause["systemd_unit"], "resume_at": pause["resume_at"]}))
            return
        # Transient systemd units do not survive a host reboot. Keep the
        # durable pause record as the source of truth and recreate its timer.
        pause.pop("systemd_unit", None)
    if pause.get("reason") != "chatgpt_image_generation_limit":
        raise SystemExit("refusing to schedule a pause with an unknown reason")
    resume_at = parse_time(str(pause["resume_at"]))
    launch = json.loads(launch_path.read_text(encoding="utf-8"))
    job_id = str(launch["job_id"])
    unit = f"yt-video-resume-{job_id.replace('-', '')[:20]}"
    calendar = resume_at.strftime("%Y-%m-%d %H:%M:%S UTC")
    command = ["systemd-run", f"--unit={unit}", f"--on-calendar={calendar}", "--timer-property=Persistent=true", "--collect", sys.executable, str(ROOT / "scripts" / "run_scheduled_resume.py"), str(project)]
    if args.dry_run:
        print(json.dumps({"command": command, "resume_at": resume_at.isoformat()}, indent=2))
        return
    subprocess.run(command, cwd=ROOT, check=True)
    pause.update({"status": "SCHEDULED", "systemd_unit": unit, "scheduler": "systemd-run persistent timer", "scheduled_at": now(), "timer_calendar_utc": calendar})
    write_json(pause_path, pause)
    job_path = ROOT / "control_panel" / "jobs" / f"{job_id}.json"
    job = json.loads(job_path.read_text(encoding="utf-8")) if job_path.is_file() else launch.copy()
    job.update({"status": "SCHEDULED", "scheduled_resume_at": resume_at.isoformat(), "image_limit_schedule": pause})
    job.pop("pid", None)
    write_json(job_path, job)
    launch.update({"status": "SCHEDULED", "scheduled_resume_at": resume_at.isoformat(), "image_limit_schedule": pause})
    write_json(launch_path, launch)
    load_dotenv(ROOT / ".env", override=False)
    if not args.no_notify:
        PipelineNotifier(str(launch.get("video_id") or pause.get("video_id") or "?"), str(launch.get("topic") or "")).send("Image-limit resume scheduled", ["⏸️ ChatGPT image-generation limit reached.", f"🕐 Reset: {parse_time(str(pause['reset_at'])).astimezone().strftime('%Y-%m-%d %H:%M %Z')}", f"▶️ Resume: {resume_at.astimezone().strftime('%Y-%m-%d %H:%M %Z')} (5-minute buffer).", f"📍 Paused at beat {int(pause['beat_id']):03d}."])
    print(json.dumps({"status": "SCHEDULED", "unit": unit, "resume_at": resume_at.isoformat()}))


if __name__ == "__main__":
    main()
