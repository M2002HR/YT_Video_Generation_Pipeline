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

from pipeline_notifier import PipelineNotifier


ROOT = Path(__file__).resolve().parents[1]


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(stage: str, command: list[str], state: dict[str, Any], path: Path, *, retries: int = 0, notifier: PipelineNotifier | None = None) -> None:
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
                if notifier is not None:
                    notifier.failure(stage.replace("_", " ").title(), time.perf_counter() - started, f"Stage failed after {attempt} attempt(s).")
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
        if notifier is not None:
            notifier.stage_complete(stage.replace("_", " ").title(), float(event["elapsed_seconds"]))
        return


def reuse(stage: str, artifact: Path, state: dict[str, Any], path: Path, *, notifier: PipelineNotifier | None = None) -> None:
    """Record an already validated artifact so a full run can resume offline."""
    event = {"stage": stage, "status": "REUSED", "artifact": str(artifact.relative_to(ROOT)), "ended_at": stamp(), "elapsed_seconds": 0.0}
    state["events"].append(event)
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    if notifier is not None:
        notifier.stage_complete(stage.replace("_", " ").title(), 0.0, artifact=str(artifact.relative_to(ROOT)))


def ensure_audio_mix_profile(project: Path) -> Path:
    """Create the conservative music-only profile required by completion."""
    profile = project / "audio_mix" / "AUDIO_MIX_PROFILE.json"
    if profile.is_file():
        return profile
    music_dir = project / "assets" / "music"
    tracks = sorted(path for path in music_dir.glob("*") if path.is_file() and path.suffix.lower() in {".mp3", ".wav", ".m4a", ".ogg", ".flac"})
    if not tracks:
        raise FileNotFoundError("A downloaded background-music file is required before creating AUDIO_MIX_PROFILE.json.")
    profile.parent.mkdir(parents=True, exist_ok=True)
    profile.write_text(json.dumps({
        "schema_version": 1,
        "baseline_video": "assets/renders/final.mp4",
        "output_video": "assets/renders/polished.mp4",
        "music": {"enabled": True, "file": str(tracks[0].relative_to(project)), "gain_db": -20.0, "loop": True, "fade_in_sec": 0.8, "fade_out_sec": 1.4, "ducking": {"enabled": True, "threshold": 0.025, "ratio": 8.0, "attack_ms": 18, "release_ms": 320}},
        "sfx": {"enabled": False, "events": []},
        "loudness": {"enabled": True, "integrated_lufs": -14.0, "true_peak_db": -1.5, "lra": 11.0},
    }, indent=2) + "\n", encoding="utf-8")
    return profile


def ensure_render_profile(project: Path, aspect_ratio: str) -> Path:
    """Create the versioned, resource-capped render defaults for a new video."""
    profile = project / "render" / "RENDER_PROFILE.json"
    width, height = (1920, 1080) if aspect_ratio == "16:9" else (1080, 1920)
    if profile.is_file():
        existing = json.loads(profile.read_text(encoding="utf-8"))
        resolution = existing.get("resolution", {})
        existing_dimensions = (resolution.get("width"), resolution.get("height"))
        # Never silently render a resumed project in a different orientation.
        # Legacy landscape profiles omitted ``aspect_ratio`` but have the
        # canonical 1920x1080 dimensions, so they remain resume-compatible.
        if existing_dimensions != (width, height):
            raise RuntimeError(
                f"Existing render profile is {existing_dimensions[0]}x{existing_dimensions[1]}, "
                f"but this launch requests {aspect_ratio} ({width}x{height}). "
                "Use a new video ID for a different frame format."
            )
        return profile
    profile.parent.mkdir(parents=True, exist_ok=True)
    profile.write_text(json.dumps({
        "schema_version": 1,
        "aspect_ratio": aspect_ratio,
        "resolution": {"width": width, "height": height},
        "fps": 30,
        "video": {"codec": "libx264", "preset": "medium", "crf": 18, "pixel_format": "yuv420p"},
        "audio": {"codec": "aac", "bitrate": "192k"},
        # The server has two vCPUs.  Use the full CPU ceiling, never more,
        # while niceness keeps the interactive services schedulable.
        "resource_limits": {"ffmpeg_threads": 2, "filter_threads": 2, "filter_complex_threads": 2},
        "motion": {"enabled": True, "strength": 0.035, "supersample": 2, "cycle": ["zoom_in", "still", "zoom_out", "slow_zoom_in"]},
        "subtitles": {"enabled": True, "font_name": "DejaVu Sans", "font_size": 56, "bold": True, "margin_v": 90, "outline": 3, "shadow": 0, "max_words_per_cue": 6, "max_chars_per_line": 34, "max_lines": 2},
    }, indent=2) + "\n", encoding="utf-8")
    return profile


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a new topic through visuals, voice, edit, music, QC and Telegram.")
    parser.add_argument("--topic", required=True)
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--duration-seconds", type=float, default=None, help="Legacy fixed-duration shorthand.")
    parser.add_argument("--min-duration-seconds", type=float, default=None)
    parser.add_argument("--max-duration-seconds", type=float, default=None)
    parser.add_argument("--aspect-ratio", choices=("16:9", "9:16"), default="16:9")
    parser.add_argument("--preset", default="001_cinematic_storybook_green_hoodie")
    parser.add_argument("--voice-profile", type=Path, required=True)
    parser.add_argument("--music-provider", choices=("mixkit", "pixabay"), default="mixkit")
    parser.add_argument("--dry-run", action="store_true", help="Validate the launch configuration and print its durable stage plan without browser/media work.")
    args = parser.parse_args()
    if args.duration_seconds is not None and (args.min_duration_seconds is not None or args.max_duration_seconds is not None):
        raise SystemExit("Use either --duration-seconds or a min/max duration range, not both.")
    duration_min = args.min_duration_seconds if args.min_duration_seconds is not None else args.duration_seconds
    duration_max = args.max_duration_seconds if args.max_duration_seconds is not None else args.duration_seconds
    if duration_min is None or duration_max is None or not 15 <= duration_min <= duration_max <= 300:
        raise SystemExit("duration range must be within 15..300 seconds and minimum must not exceed maximum")
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
        print(json.dumps({"status": "DRY_RUN_PASS", "project": str(project), "duration_min_seconds": duration_min, "duration_max_seconds": duration_max, "aspect_ratio": args.aspect_ratio, "music_provider": args.music_provider, "voice_profile": str(profile), "stages": ["visuals", "voiceover", "timing", "music", "completion", "telegram_publish"]}, indent=2))
        return
    state_path = project / "pipeline" / "FULL_PIPELINE_RUNTIME_STATE.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state: dict[str, Any] = {"schema_version": 3, "topic": args.topic, "video_id": args.video_id, "duration_min_seconds": duration_min, "duration_max_seconds": duration_max, "aspect_ratio": args.aspect_ratio, "started_at": stamp(), "status": "RUNNING", "events": []}
    state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    notifier = PipelineNotifier(args.video_id, args.topic)
    notifier.send("Full pipeline started", ["🚀 Resumable workflow active", f"⏱ Target range: {duration_min:g}–{duration_max:g}s"])
    py = sys.executable
    # Visual generation persists each accepted prompt/image, so rerunning the
    # stage is safe and resumes at the first incomplete beat after a transient
    # browser/UI failure.
    visual_report = project / "visual_pipeline" / "VISUAL_QC_REPORT.json"
    if visual_report.is_file():
        reuse("visuals", visual_report, state, state_path, notifier=notifier)
    else:
        run("visuals", [py, "scripts/run_visual_pipeline.py", "--topic", args.topic, "--video-id", args.video_id, "--preset", args.preset, "--min-duration-seconds", str(duration_min), "--max-duration-seconds", str(duration_max), "--aspect-ratio", args.aspect_ratio], state, state_path, retries=3, notifier=notifier)
    run("voiceover", [py, "scripts/run_elevenlabs_voiceover.py", "--video-id", args.video_id, "--project", str(project), "--profile", str(args.voice_profile)], state, state_path, notifier=notifier)
    timing_file = project / "timing" / "BEAT_TIMINGS.json"
    if timing_file.is_file():
        reuse("timing", timing_file, state, state_path, notifier=notifier)
    else:
        run("timing", [py, "scripts/align_beats.py", str(project), "--backend", "local"], state, state_path, notifier=notifier)
    music_file = next((path for path in (project / "assets" / "music").glob("*") if path.is_file() and path.suffix.lower() in {".mp3", ".wav", ".m4a", ".ogg", ".flac"}), None)
    if music_file is not None:
        reuse("music", music_file, state, state_path, notifier=notifier)
    else:
        run("music", [py, "scripts/run_pixabay_music.py", "--video-id", args.video_id, "--project", str(project), "--provider", args.music_provider], state, state_path, notifier=notifier)
    mix_profile = ensure_audio_mix_profile(project)
    reuse("audio_mix_profile", mix_profile, state, state_path, notifier=notifier)
    render_profile = ensure_render_profile(project, args.aspect_ratio)
    reuse("render_profile", render_profile, state, state_path, notifier=notifier)
    run("completion", [py, "scripts/run_completion_pipeline.py", str(project), "--publish"], state, state_path, notifier=notifier)
    state.update({"status": "DONE", "completed_at": stamp(), "total_elapsed_seconds": round(sum(float(item.get("elapsed_seconds", 0)) for item in state["events"]), 3)})
    state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    notifier.send("Full pipeline complete", ["🏁 All requested stages passed", f"⏱ Total: {state['total_elapsed_seconds']:.1f}s"])
    print("FULL VIDEO PIPELINE: PASS")


if __name__ == "__main__":
    main()
