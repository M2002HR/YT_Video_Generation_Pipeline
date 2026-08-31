#!/usr/bin/env python3
"""Resume-safe, no-SFX completion path from timing data to Telegram publish."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def save(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def execute(name: str, command: list[str], state: dict[str, Any], path: Path) -> None:
    started_wall, started = now(), time.perf_counter()
    event: dict[str, Any] = {"stage": name, "started_at": started_wall, "command": command}
    try:
        subprocess.run(command, cwd=ROOT, check=True)
    except subprocess.CalledProcessError as exc:
        event.update({"status": "FAILED", "ended_at": now(), "elapsed_seconds": round(time.perf_counter() - started, 3), "returncode": exc.returncode})
        state["events"].append(event)
        state["status"] = "FAILED"
        save(path, state)
        raise
    event.update({"status": "DONE", "ended_at": now(), "elapsed_seconds": round(time.perf_counter() - started, 3)})
    state["events"].append(event)
    state["status"] = "RUNNING"
    save(path, state)


def main() -> None:
    parser = argparse.ArgumentParser(description="Complete a prepared video from beat timings through Telegram publication.")
    parser.add_argument("video_dir", type=Path)
    parser.add_argument("--publish", action="store_true", help="Send the passing polished output to Telegram.")
    parser.add_argument("--allow-sfx", action="store_true", help="Keep explicitly configured SFX; default is no SFX.")
    args = parser.parse_args()
    video = args.video_dir.expanduser().resolve()
    if not (video / "timing" / "BEAT_TIMINGS.json").is_file():
        raise FileNotFoundError("Beat timings are required before completion.")
    profile = video / "audio_mix" / "AUDIO_MIX_PROFILE.json"
    if not profile.is_file():
        raise FileNotFoundError("AUDIO_MIX_PROFILE.json is required before completion.")
    if not args.allow_sfx:
        data = json.loads(profile.read_text(encoding="utf-8"))
        data.setdefault("sfx", {})["enabled"] = False
        data["sfx"]["events"] = []
        profile.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    state_path = video / "pipeline" / "FINALIZATION_RUNTIME_STATE.json"
    state: dict[str, Any] = {"schema_version": 1, "video": video.name, "started_at": now(), "status": "RUNNING", "events": []}
    save(state_path, state)
    py = sys.executable
    execute("build_timeline", [py, "scripts/build_timeline.py", str(video)], state, state_path)
    baseline = video / "assets" / "renders" / "final.mp4"
    render_command = [py, "scripts/render_video.py", str(video), "--output", str(baseline)]
    # Inherited niceness keeps SSH, VNC and the watchdog schedulable even on a
    # two-vCPU server. It is configurable for stronger machines.
    nice_level = max(0, min(19, int(os.getenv("YT_RENDER_NICE", "10"))))
    if nice_level:
        render_command = ["nice", "-n", str(nice_level), *render_command]
    execute("render_baseline", render_command, state, state_path)
    execute("qc_baseline", [py, "scripts/qc_render.py", str(video), "--input", str(baseline), "--decode"], state, state_path)
    polished = video / "assets" / "renders" / "polished.mp4"
    execute("polish_audio", [py, "scripts/polish_audio.py", str(video), "--output", str(polished)], state, state_path)
    execute("qc_polished", [py, "scripts/qc_render.py", str(video), "--input", str(polished), "--decode"], state, state_path)
    if args.publish:
        execute("publish_telegram", [py, "scripts/publish_to_telegram.py", str(video), "--input", str(polished)], state, state_path)
    state["status"] = "DONE"
    state["completed_at"] = now()
    state["total_elapsed_seconds"] = round(sum(float(x.get("elapsed_seconds", 0)) for x in state["events"]), 3)
    save(state_path, state)
    print("COMPLETION PIPELINE: PASS")


if __name__ == "__main__":
    main()
