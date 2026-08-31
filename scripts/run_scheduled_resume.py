#!/usr/bin/env python3
"""Resume one panel launch after a durable image-limit pause."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a previously scheduled panel launch.")
    parser.add_argument("project", type=Path)
    args = parser.parse_args()
    project = args.project.resolve()
    if ROOT not in project.parents or not (project / "launch" / "LAUNCH_REQUEST.json").is_file():
        raise SystemExit("project must be a launched video inside this workspace")
    pause_path = project / "pipeline" / "IMAGE_LIMIT_SCHEDULE.json"
    pause = json.loads(pause_path.read_text(encoding="utf-8"))
    if pause.get("status") != "SCHEDULED":
        print("Scheduled resume skipped: pause is no longer pending.")
        return
    resume_at = datetime.fromisoformat(str(pause["resume_at"]).replace("Z", "+00:00"))
    if resume_at.tzinfo is None or resume_at.astimezone(timezone.utc) > datetime.now(timezone.utc):
        raise SystemExit("Refusing an early resume before the stored safe time.")
    launch_path = project / "launch" / "LAUNCH_REQUEST.json"
    launch = json.loads(launch_path.read_text(encoding="utf-8"))
    job_path = ROOT / "control_panel" / "jobs" / f"{launch['job_id']}.json"
    job = json.loads(job_path.read_text(encoding="utf-8")) if job_path.is_file() else launch.copy()
    pause.update({"status": "RESUMING", "resume_started_at": now()})
    job.update({"status": "RUNNING", "pid": os.getpid(), "resumed_at": now(), "image_limit_schedule": pause})
    write_json(pause_path, pause); write_json(launch_path, {**launch, "status": "RUNNING", "resumed_at": now()}); write_json(job_path, job)
    log_path = ROOT / "control_panel" / "jobs" / f"{launch['job_id']}.log"
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"\n=== Scheduled image-limit resume at {now()} ===\n")
        result = subprocess.run(list(launch["command"]), cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=False)
    pause = json.loads(pause_path.read_text(encoding="utf-8"))
    job = json.loads(job_path.read_text(encoding="utf-8"))
    # A new limit can be encountered during the resumed run. Its scheduler has
    # already replaced the pause state and job state; never overwrite it.
    if pause.get("status") == "SCHEDULED":
        print("Resume encountered a new image limit; next resume remains scheduled.")
        return
    job.update({"status": "DONE" if result.returncode == 0 else "FAILED", "completed_at": now(), "resume_returncode": result.returncode})
    write_json(job_path, job)
    write_json(launch_path, {**launch, "status": job["status"], "completed_at": job["completed_at"]})
    pause.update({"status": "RESUMED", "resume_finished_at": now(), "resume_returncode": result.returncode})
    write_json(pause_path, pause)
    if result.returncode:
        raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
