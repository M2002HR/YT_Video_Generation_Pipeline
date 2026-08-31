#!/usr/bin/env python3
"""One resumable command from topic to Telegram-ready finished video."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(stage: str, command: list[str], state: dict[str, Any], path: Path, *, retries: int = 0) -> None:
    """Run a resumable stage with bounded retries and durable attempt records."""
    for attempt in range(1, retries + 2):
        started = time.perf_counter()
        event: dict[str, Any] = {
            "stage": stage,
            "attempt": attempt,
            "started_at": stamp(),
            "command": command,
        }
        try:
            subprocess.run(command, cwd=ROOT, check=True)
        except subprocess.CalledProcessError as exc:
            event.update({"status": "FAILED", "ended_at": stamp(), "elapsed_seconds": round(time.perf_counter() - started, 3), "returncode": exc.returncode})
            state["events"].append(event)
            if attempt > retries:
                state["status"] = "FAILED"
                path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
                raise
            delay = min(60, 5 * (2 ** (attempt - 1)))
            event["next_retry_delay_seconds"] = delay
            path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
            print(f"{stage} failed; resuming safely in {delay}s (attempt {attempt + 1}/{retries + 1}).", flush=True)
            time.sleep(delay)
            continue
        event.update({"status": "DONE", "ended_at": stamp(), "elapsed_seconds": round(time.perf_counter() - started, 3)})
        state["events"].append(event)
        path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        return


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a new topic through visuals, voice, edit, music, QC and Telegram.")
    parser.add_argument("--topic", required=True)
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--duration-seconds", type=float, required=True)
    parser.add_argument("--preset", default="001_cinematic_storybook_green_hoodie")
    parser.add_argument("--voice-profile", type=Path, required=True)
    parser.add_argument("--music-provider", choices=("mixkit", "pixabay"), default="mixkit")
    parser.add_argument("--dry-run", action="store_true", help="Validate the launch configuration and print its durable stage plan without browser/media work.")
    args = parser.parse_args()
    if not 15 <= args.duration_seconds <= 300:
        raise SystemExit("duration must be between 15 and 300 seconds")
    profile = args.voice_profile.expanduser().resolve()
    if not profile.is_file():
        raise SystemExit(f"Voice profile not found: {profile}")
    try:
        voice_settings = json.loads(profile.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Voice profile is not valid JSON: {profile}") from exc
    required_voice_fields = {"voice", "model", "speed", "stability", "similarity", "style"}
    missing_voice_fields = sorted(name for name in required_voice_fields if name not in voice_settings)
    if missing_voice_fields:
        raise SystemExit("Voice profile missing: " + ", ".join(missing_voice_fields))
    safe_topic = "".join(c.lower() if c.isalnum() else "_" for c in args.topic).strip("_")
    project = ROOT / "videos" / f"{args.video_id}_{safe_topic}"
    if args.dry_run:
        print(json.dumps({"status": "DRY_RUN_PASS", "project": str(project), "duration_seconds": args.duration_seconds, "music_provider": args.music_provider, "voice_profile": str(profile), "stages": ["visuals", "voiceover", "timing", "music", "completion", "telegram_publish"]}, indent=2))
        return
    state_path = project / "pipeline" / "FULL_PIPELINE_RUNTIME_STATE.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state: dict[str, Any] = {"schema_version": 1, "topic": args.topic, "video_id": args.video_id, "duration_seconds": args.duration_seconds, "started_at": stamp(), "status": "RUNNING", "events": []}
    state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    py = sys.executable
    # Visual generation persists each accepted prompt/image, so rerunning the
    # stage is safe and resumes at the first incomplete beat after a transient
    # browser/UI failure.
    run("visuals", [py, "scripts/run_visual_pipeline.py", "--topic", args.topic, "--video-id", args.video_id, "--preset", args.preset, "--duration-seconds", str(args.duration_seconds)], state, state_path, retries=3)
    run("voiceover", [py, "scripts/run_elevenlabs_voiceover.py", "--video-id", args.video_id, "--project", str(project), "--profile", str(args.voice_profile)], state, state_path)
    run("timing", [py, "scripts/align_beats.py", str(project), "--backend", "local"], state, state_path)
    run("music", [py, "scripts/run_pixabay_music.py", "--video-id", args.video_id, "--project", str(project), "--provider", args.music_provider], state, state_path)
    run("completion", [py, "scripts/run_completion_pipeline.py", str(project), "--publish"], state, state_path)
    state.update({"status": "DONE", "completed_at": stamp(), "total_elapsed_seconds": round(sum(float(item.get("elapsed_seconds", 0)) for item in state["events"]), 3)})
    state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    print("FULL VIDEO PIPELINE: PASS")


if __name__ == "__main__":
    main()
