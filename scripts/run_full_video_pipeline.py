#!/usr/bin/env python3
"""One resumable command from topic to Telegram-ready finished video."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pipeline_notifier import PipelineNotifier
from content_projects import DEFAULT_CONTENT_PROJECT, load_content_project, validate_content_project, video_slug


ROOT = Path(__file__).resolve().parents[1]


class PipelinePausedForImageLimit(RuntimeError):
    """Signal that the visual child stopped intentionally at a ChatGPT limit."""


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(stage: str, command: list[str], state: dict[str, Any], path: Path, *, retries: int = 0, notifier: PipelineNotifier | None = None, image_limit_pause_path: Path | None = None) -> None:
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
            if image_limit_pause_path is not None and image_limit_pause_path.is_file():
                try:
                    pause = json.loads(image_limit_pause_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    pause = {}
                if exc.returncode == 75 and pause.get("status") == "SCHEDULED" and pause.get("reason") == "chatgpt_image_generation_limit":
                    event.update({"status": "PAUSED_FOR_IMAGE_LIMIT", "ended_at": stamp(), "elapsed_seconds": round(time.perf_counter() - started, 3), "returncode": exc.returncode, "resume_at": pause.get("resume_at")})
                    state["events"].append(event)
                    state["status"] = "SCHEDULED"
                    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
                    raise PipelinePausedForImageLimit(str(pause.get("resume_at") or "image-limit pause")) from exc
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


def valid_music_artifact(path: Path) -> bool:
    """Never reuse a truncated/HTML-disguised download as background audio."""
    if not path.is_file() or path.stat().st_size < 64 * 1024:
        return False
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
        return result.returncode == 0 and float(result.stdout.strip()) >= 10
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return False


def valid_timing_artifact(path: Path) -> bool:
    """Only reuse real STT word timings; never publish estimated subtitles."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        stt = payload.get("stt")
    except (OSError, json.JSONDecodeError):
        return False
    return (
        isinstance(stt, dict)
        and stt.get("backend") in {"ajil", "local"}
        and stt.get("timestamp_source") == "word"
        and not bool(stt.get("fallback_used", False))
    )


def passed_visual_report(path: Path, content_project: str, topic: str, aspect_ratio: str, preset: str, creative_brief_sha256: str) -> bool:
    """Only reuse visual output that belongs to this exact successful launch."""
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return bool(report.get("passed")) and report.get("content_project") == content_project and report.get("topic") == topic and report.get("aspect_ratio") == aspect_ratio and report.get("preset") == preset and report.get("creative_brief_sha256") == creative_brief_sha256


def publish_git_artifacts(project: Path, state_path: Path, state: dict[str, Any], *, notifier: PipelineNotifier | None = None) -> None:
    """Publish only this video's durable artifacts after Telegram succeeds."""
    started_at, started = stamp(), time.perf_counter()
    state.update({"status": "FINALIZING", "git_publish_started_at": started_at})
    state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    command = [sys.executable, "scripts/commit_video_artifacts.py", str(project), "--full-state", str(state_path), "--started-at", str(started)]
    last_error: Exception | None = None
    for attempt in range(1, 5):
        try:
            subprocess.run(command, cwd=ROOT, check=True)
            # The publication helper writes the final state before its second
            # scoped commit, so refresh this in-memory copy for notifications.
            state.clear()
            state.update(json.loads(state_path.read_text(encoding="utf-8")))
            if notifier is not None:
                notifier.stage_complete("Git commit and push", time.perf_counter() - started)
            return
        except subprocess.CalledProcessError as exc:
            last_error = exc
            if attempt == 4:
                break
            delay = min(30, 2 ** attempt)
            print(f"git commit/push failed; retrying in {delay}s ({attempt + 1}/4).", flush=True)
            time.sleep(delay)
    raise RuntimeError(f"Automatic Git publication failed after 4 attempts: {last_error}")


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
    parser.add_argument("--content-project", default=DEFAULT_CONTENT_PROJECT)
    parser.add_argument("--preset", default=None)
    parser.add_argument("--voice-profile", type=Path, required=True)
    parser.add_argument("--creative-brief", type=Path, default=None)
    parser.add_argument("--music-provider", choices=("mixkit", "pixabay"), default="mixkit")
    parser.add_argument("--dry-run", action="store_true", help="Validate the launch configuration and print its durable stage plan without browser/media work.")
    args = parser.parse_args()
    content_project = load_content_project(args.content_project)
    preset = args.preset or content_project.default_visual_preset
    validate_content_project(content_project, preset)
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
    creative_brief = args.creative_brief.expanduser().resolve() if args.creative_brief else None
    creative_payload: dict[str, Any] = {}
    if creative_brief is not None:
        try:
            payload = json.loads(creative_brief.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SystemExit(f"Creative brief is unreadable: {creative_brief}") from exc
        if not isinstance(payload, dict):
            raise SystemExit("Creative brief must be a JSON object.")
        creative_payload = {str(key): str(value).strip() for key, value in payload.items() if isinstance(value, str) and value.strip()}
    creative_brief_sha256 = hashlib.sha256(json.dumps(creative_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    project = ROOT / "videos" / f"{args.video_id}_{video_slug(args.topic)}"
    if args.dry_run:
        visual_stages = ["script_draft", "retention_edit"]
        if content_project.config.get("world_design_prompt"):
            visual_stages.append("episode_world_design")
        visual_stages.extend(["visual_beats", "beat_prompts_and_images"])
        print(json.dumps({"status": "DRY_RUN_PASS", "project": str(project), "content_project": content_project.project_id, "preset": preset, "duration_min_seconds": duration_min, "duration_max_seconds": duration_max, "aspect_ratio": args.aspect_ratio, "music_provider": args.music_provider, "voice_profile": str(profile), "creative_brief": str(creative_brief) if creative_brief else None, "stages": [*visual_stages, "voiceover", "timing", "music", "completion", "telegram_publish", "git_commit_push"]}, indent=2))
        return
    state_path = project / "pipeline" / "FULL_PIPELINE_RUNTIME_STATE.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state: dict[str, Any] = {"schema_version": 5, "content_project": content_project.project_id, "preset": preset, "topic": args.topic, "video_id": args.video_id, "duration_min_seconds": duration_min, "duration_max_seconds": duration_max, "aspect_ratio": args.aspect_ratio, "creative_brief_sha256": creative_brief_sha256, "started_at": stamp(), "status": "RUNNING", "events": []}
    state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    notifier = PipelineNotifier(args.video_id, args.topic)
    notifier.send("Full pipeline started", ["🚀 Resumable workflow active", f"⏱ Target range: {duration_min:g}–{duration_max:g}s"])
    py = sys.executable
    # Visual generation persists each accepted prompt/image, so rerunning the
    # stage is safe and resumes at the first incomplete beat after a transient
    # browser/UI failure.
    visual_report = project / "visual_pipeline" / "VISUAL_QC_REPORT.json"
    if visual_report.is_file() and passed_visual_report(visual_report, content_project.project_id, args.topic, args.aspect_ratio, preset, creative_brief_sha256):
        reuse("visuals", visual_report, state, state_path, notifier=notifier)
    else:
        visual_command = [py, "scripts/run_visual_pipeline.py", "--content-project", content_project.project_id, "--topic", args.topic, "--video-id", args.video_id, "--preset", preset, "--min-duration-seconds", str(duration_min), "--max-duration-seconds", str(duration_max), "--aspect-ratio", args.aspect_ratio]
        if creative_brief is not None:
            visual_command.extend(["--creative-brief", str(creative_brief)])
        try:
            run("visuals", visual_command, state, state_path, retries=3, notifier=notifier, image_limit_pause_path=project / "pipeline" / "IMAGE_LIMIT_SCHEDULE.json")
        except PipelinePausedForImageLimit:
            subprocess.run([py, "scripts/schedule_image_limit_resume.py", str(project)], cwd=ROOT, check=True)
            print("FULL VIDEO PIPELINE: PAUSED_FOR_IMAGE_LIMIT", flush=True)
            return
    run("voiceover", [py, "scripts/run_elevenlabs_voiceover.py", "--video-id", args.video_id, "--project", str(project), "--profile", str(args.voice_profile)], state, state_path, notifier=notifier)
    timing_file = project / "timing" / "BEAT_TIMINGS.json"
    if valid_timing_artifact(timing_file):
        reuse("timing", timing_file, state, state_path, notifier=notifier)
    else:
        # Respect YT_STT_BACKEND (Ajil by default). Forcing local small.en here
        # consumed substantial RAM/CPU and could disappear before recording an
        # event, leaving the panel looking stuck between ElevenLabs and music.
        run("timing", [py, "scripts/align_beats.py", str(project), "--fallback-backend", "none"], state, state_path, retries=1, notifier=notifier)
    music_file = next((path for path in (project / "assets" / "music").glob("*") if path.suffix.lower() in {".mp3", ".wav", ".m4a", ".ogg", ".flac"} and valid_music_artifact(path)), None)
    if music_file is not None:
        reuse("music", music_file, state, state_path, notifier=notifier)
    else:
        # The music runner has its own bounded UI timeouts, durable selected-URL
        # resume, audio validation, and verified local fallback. One outer retry
        # still covers process-level failures such as an interrupted interpreter.
        run("music", [py, "scripts/run_pixabay_music.py", "--video-id", args.video_id, "--project", str(project), "--provider", args.music_provider], state, state_path, retries=1, notifier=notifier)
    mix_profile = ensure_audio_mix_profile(project)
    reuse("audio_mix_profile", mix_profile, state, state_path, notifier=notifier)
    render_profile = ensure_render_profile(project, args.aspect_ratio)
    reuse("render_profile", render_profile, state, state_path, notifier=notifier)
    run("completion", [py, "scripts/run_completion_pipeline.py", str(project), "--publish"], state, state_path, notifier=notifier)
    publish_git_artifacts(project, state_path, state, notifier=notifier)
    notifier.send("Full pipeline complete", ["🏁 All requested stages passed", f"⏱ Total: {state['total_elapsed_seconds']:.1f}s"])
    print("FULL VIDEO PIPELINE: PASS")


if __name__ == "__main__":
    main()
