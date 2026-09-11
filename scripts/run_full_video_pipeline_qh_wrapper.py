#!/usr/bin/env python3
"""Q Station end to end: visual stages, then narration → timing → trim → mix → render.

This wrapper only sequences real stages. Every step either produces its real artifact or the
run stops with a non-zero exit code — there is no synthetic narration, no proportional
"timing", and no placeholder music anywhere in this file. A stage that cannot run is a
pipeline failure to fix, not a gap to fill with something that merely renders.

Stage order (§57):

    run_question_harvest_pipeline.py   script → images → Flow clips
    run_elevenlabs_voiceover.py        one continuous narration track (§66)
    run_pixabay_music.py               background track (needs only narration + brief)
    align_beats.py                     Ajil word timestamps → BEAT_TIMINGS + OPENING_TIMING
    trim_opening_clips.py              cut the Flow sources to the measured boundaries (§67)
    run_completion_pipeline.py         timeline → render → QC → publish
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

#: STT results are only usable for sync when they carry real per-word timestamps.
ACCEPTED_STT_BACKENDS = ("ajil", "local")
MUSIC_SUFFIXES = {".mp3", ".wav", ".m4a", ".ogg", ".flac"}


def mark_wrapper_stage(project: Path, stage: str, status: str, **details: object) -> None:
    """Persist wrapper-owned stages so the Studio can observe them in real time."""
    path = project / "pipeline" / "WRAPPER_RUNTIME_STATE.json"
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {"schema_version": 1, "events": []}
    now = datetime.now(timezone.utc).isoformat()
    events = state.setdefault("events", [])
    if status != "RUNNING" and events and events[-1].get("stage") == stage and events[-1].get("status") == "RUNNING":
        events[-1].update({"status": status, "ended_at": now, **details})
    else:
        events.append({"stage": stage, "status": status, "started_at": now, **details})
    state.update({"status": status, "updated_at": now})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def music_is_usable(directory: Path) -> bool:
    return directory.is_dir() and any(path.is_file() and path.suffix.lower() in MUSIC_SUFFIXES and path.stat().st_size >= 64 * 1024 for path in directory.iterdir())


def file_is_usable(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


def run(command: list[str]) -> None:
    print(f"$ {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def report_reused(notifier, stage: str, artifact: str) -> None:
    """Append a reuse result to the prior phase instead of creating a new log entry."""
    from pipeline_stages import stage_title

    title = stage_title(stage)
    notifier.stage_reused(title, ["↻ Reused existing artifact", f"📄 {artifact}"])


def run_owned_stage(command: list[str], notifier, stage: str, artifact: Path | None = None, project: Path | None = None) -> None:
    """Run a child that has no notifier of its own as one mutable Telegram stage."""
    from pipeline_notifier import format_duration
    from pipeline_stages import stage_title

    title = stage_title(stage)
    message = notifier.stage_started(title)
    started = time.perf_counter()
    try:
        run(command)
    except subprocess.CalledProcessError as exc:
        notifier.failure(title, time.perf_counter() - started, f"{stage} exited with code {exc.returncode}")
        raise
    lines = ["✅ Stage complete", f"⏱ Duration: {format_duration(time.perf_counter() - started)}"]
    if artifact is not None and artifact.exists():
        try:
            shown = artifact.relative_to(project) if project is not None else artifact
        except ValueError:
            shown = artifact
        lines.append(f"📄 Saved: {shown}")
    notifier.stage_update(message, title, lines)


def word_timing_is_usable(project: Path) -> bool:
    """True only when BEAT_TIMINGS.json carries real per-word timestamps.

    The old wrapper wrote ``backend: "ajil"`` onto proportional timings so this check would
    pass. Nothing writes that file here except align_beats.py, so the check means what it says.
    """
    timing = project / "timing" / "BEAT_TIMINGS.json"
    opening = project / "timing" / "OPENING_TIMING.json"
    if not timing.is_file() or not opening.is_file():
        return False
    try:
        stt = (json.loads(timing.read_text(encoding="utf-8")).get("stt") or {})
    except (OSError, ValueError):
        return False
    return stt.get("backend") in ACCEPTED_STT_BACKENDS and stt.get("timestamp_source") == "word"


def opening_speed_tolerance(project: Path, creative_brief: Path) -> float:
    """Standing trim rule default: silent opening clips may slow up to 10% to sync."""
    for source in (Path(creative_brief), project / "launch" / "CREATIVE_BRIEF.json"):
        try:
            candidate = (json.loads(source.read_text(encoding="utf-8")).get("_qh") or {}).get("opening_speed_tolerance")
        except (OSError, ValueError):
            continue
        if candidate is not None and str(candidate) != "":
            try:
                value = float(candidate)
            except (TypeError, ValueError):
                continue
            if 0 <= value <= 0.5:
                return value
    try:
        defaults = json.loads((ROOT / "projects" / "q_station" / "PROJECT.json").read_text(encoding="utf-8")).get("defaults") or {}
        if defaults.get("opening_speed_tolerance") is not None:
            return float(defaults["opening_speed_tolerance"])
    except (OSError, ValueError):
        pass
    try:
        return float(os.getenv("YT_QUESTION_HARVEST_OPENING_SPEED_TOLERANCE", "0.1"))
    except ValueError:
        return 0.1


def qh_overrides(creative_brief: Path) -> list[str]:
    """Model/duration overrides the panel stored in the brief, as CLI flags."""
    try:
        brief = json.loads(Path(creative_brief).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"warn: could not read {creative_brief}: {exc}", flush=True)
        return []
    advanced = brief.get("_qh") or {}
    mapping = {
        "gemini_image_model": "--gemini-model",
        "flow_video_model": "--flow-model",
        "flow_resolution": "--flow-resolution",
        "opening_a_source_seconds": "--opening-a-seconds",
        "opening_b_source_seconds": "--opening-b-seconds",
        "world_style_policy": "--world-style-policy",
        "world_style_id": "--world-style-id",
        "world_style_hint": "--world-style-hint",
        "chatgpt_fallback_mode": "--chatgpt-fallback-mode",
        "min_duration_seconds": "--min-duration-seconds",
        "max_duration_seconds": "--max-duration-seconds",
        "opening_speed_tolerance": "--opening-speed-tolerance",
    }
    flags: list[str] = []
    for key, flag in mapping.items():
        if advanced.get(key):
            flags += [flag, str(advanced[key])]
    character = advanced.get("character")
    if isinstance(character, dict):
        mode = str(character.get("mode") or "auto")
        flags += ["--character-mode", mode]
        if mode == "manual" and character.get("character_id"):
            flags += ["--character-id", str(character["character_id"])]
    return flags


def apply_render_preferences(profile_path: Path, creative_brief: Path) -> None:
    try:
        brief = json.loads(Path(creative_brief).read_text(encoding="utf-8"))
        wanted = bool((brief.get("_qh") or {}).get("show_subtitles", False))
        word_highlight = bool((brief.get("_subtitle") or {}).get("word_highlight", True))
        style = brief.get("_subtitle") if isinstance(brief.get("_subtitle"), dict) else {}
    except (OSError, ValueError):
        brief, wanted, word_highlight, style = {}, False, True, {}
    from run_full_video_pipeline import apply_motion_preferences, apply_subtitle_style

    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    subtitles = profile.setdefault("subtitles", {})
    subtitles["enabled"] = wanted
    if not isinstance(subtitles.get("word_highlight"), dict):
        subtitles["word_highlight"] = {}
    subtitles["word_highlight"]["enabled"] = word_highlight
    apply_subtitle_style(subtitles, style)
    profile_path.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")
    # Reuse the canonical profile validator/writer so direct and QH runs cannot drift.
    apply_motion_preferences(profile_path, brief)


def write_pending_state(project: Path, absent: str, reason: str) -> Path:
    """Record why the episode is parked, for the panel and the watcher to read."""
    from datetime import datetime, timezone

    path = project / "pipeline" / "FLOW_PENDING_STATE.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "WAITING_FOR_FLOW",
                "missing_clips": [name.strip() for name in absent.split(",") if name.strip()],
                "reason": reason,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def clear_pending_state(project: Path) -> None:
    path = project / "pipeline" / "FLOW_PENDING_STATE.json"
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Q Station end-to-end pipeline")
    parser.add_argument("--topic", required=True)
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--content-project", default="q_station")
    parser.add_argument("--creative-brief", type=Path, required=True)
    parser.add_argument("--voice-profile", type=Path, required=True)
    parser.add_argument("--aspect-ratio", default="9:16")
    parser.add_argument("--regenerate-beats", default="", help="Comma-separated beat IDs to revise, including their continuity downstream.")
    parser.add_argument("--beat-feedback-json", type=Path, help="Operator feedback JSON passed into revised beat prompts.")
    parser.add_argument("--music-provider", default=None, help="Legacy single music provider.")
    parser.add_argument("--music-providers", default=None, help="Comma-separated music provider priority.")
    parser.add_argument("--publish", action="store_true", help="Publish the finished render.")
    parser.add_argument("--telegram-low-size", action=argparse.BooleanOptionalAction, default=True, help="Send a compressed Telegram copy (default: enabled).")
    parser.add_argument("--telegram-original", action="store_true", help="Also send the polished original to Telegram.")
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Commit and push the finished artifacts after both QC gates pass (§76, §111).",
    )
    parser.add_argument(
        "--resource-budget",
        type=float,
        default=float(os.getenv("YT_RENDER_RESOURCE_BUDGET", "0.8")),
        help="Share of the machine the render may use (default 0.8).",
    )
    args = parser.parse_args()

    from content_projects import video_slug

    project = ROOT / "videos" / f"{args.video_id}_{video_slug(args.topic)}"
    python = sys.executable
    from pipeline_notifier import PipelineNotifier
    notifier = PipelineNotifier(args.video_id, args.topic)

    from flow_gate import blocked_only_on_flow, clips_ready, missing_clips

    # 1. Visual stages: script, plans, world keyframe, book spread, body images, Flow clips.
    #    A Flow outage is Google's, not this episode's: when it is the only failure, the
    #    stages that need no video clip still run, and the trim and render wait instead of
    #    the whole episode being thrown away.
    flow_pending_reason = ""
    try:
        run(
            [
                python, "-u", "scripts/run_question_harvest_pipeline.py",
                "--topic", args.topic,
                "--video-id", args.video_id,
                "--content-project", args.content_project,
                "--creative-brief", str(args.creative_brief),
                "--voice-profile", str(args.voice_profile),
                "--aspect-ratio", args.aspect_ratio,
            ]
            + qh_overrides(args.creative_brief)
            + (["--regenerate-beats", args.regenerate_beats] if args.regenerate_beats else [])
            + (["--beat-feedback-json", str(args.beat_feedback_json)] if args.beat_feedback_json else [])
        )
    except subprocess.CalledProcessError:
        only_flow, reason = blocked_only_on_flow(project)
        if not only_flow:
            raise
        flow_pending_reason = reason
        print(
            "FLOW PENDING: the visual stages are complete except the Flow clips "
            f"({reason}). Continuing with narration, timing and music; the trim and render "
            "wait for the clips.",
            flush=True,
        )

    # 2. One continuous narration track (§66).
    narration = project / "assets" / "audio" / "narration.mp3"
    if file_is_usable(narration):
        print(f"narration reuse: {narration}", flush=True)
        mark_wrapper_stage(project, "elevenlabs_voiceover", "REUSED", artifact=str(narration.relative_to(project)))
        report_reused(notifier, "elevenlabs_voiceover", str(narration.relative_to(project)))
    else:
        mark_wrapper_stage(project, "elevenlabs_voiceover", "RUNNING")
        try:
            run([python, "scripts/run_elevenlabs_voiceover.py", "--video-id", args.video_id, "--project", str(project), "--profile", str(args.voice_profile)])
        except subprocess.CalledProcessError as exc:
            mark_wrapper_stage(project, "elevenlabs_voiceover", "FAILED", returncode=exc.returncode)
            raise
        if not file_is_usable(narration):
            mark_wrapper_stage(project, "elevenlabs_voiceover", "FAILED_VALIDATION", message="Narration command returned without a usable artifact.")
            raise RuntimeError(f"Narration is missing or empty: {narration}")
        mark_wrapper_stage(project, "elevenlabs_voiceover", "DONE", artifact=str(narration.relative_to(project)))

    # 3. Background music. It needs only the narration and the brief, so it runs before the
    #    timing: when alignment is blocked by its STT provider, the episode should still gain
    #    its music instead of every resume stopping at the same step with nothing to show.
    music_dir = project / "assets" / "music"
    if music_is_usable(music_dir):
        print("music reuse", flush=True)
        mark_wrapper_stage(project, "background_music", "REUSED", artifact=str(music_dir.relative_to(project)))
        report_reused(notifier, "background_music", str(music_dir.relative_to(project)))
    else:
        mark_wrapper_stage(project, "background_music", "RUNNING")
        try:
            run([python, "scripts/run_pixabay_music.py", "--video-id", args.video_id, "--project", str(project), "--providers", args.music_providers or args.music_provider or "mixkit"])
        except subprocess.CalledProcessError as exc:
            mark_wrapper_stage(project, "background_music", "FAILED", returncode=exc.returncode)
            raise
        if not music_is_usable(music_dir):
            mark_wrapper_stage(project, "background_music", "FAILED_VALIDATION", message="Music command returned without a usable audio file.")
            raise RuntimeError(f"Background music is missing or unusable: {music_dir}")
        mark_wrapper_stage(project, "background_music", "DONE")

    # 4. Real word timestamps, and the measured opening boundaries derived from them. Both
    #    accepted backends measure real words; only invented timing is refused (§67).
    if word_timing_is_usable(project):
        print("timing reuse: word-level timestamps already present", flush=True)
        mark_wrapper_stage(project, "ajil_alignment", "REUSED", artifact="timing/BEAT_TIMINGS.json")
        report_reused(notifier, "ajil_alignment", "timing/BEAT_TIMINGS.json")
    else:
        mark_wrapper_stage(project, "ajil_alignment", "RUNNING")
        try:
            run_owned_stage([python, "scripts/align_beats.py", str(project), "--fallback-backend", "none"], notifier, "ajil_alignment", project / "timing" / "BEAT_TIMINGS.json", project)
        except subprocess.CalledProcessError as exc:
            mark_wrapper_stage(project, "ajil_alignment", "FAILED", returncode=exc.returncode)
            raise
        if not word_timing_is_usable(project):
            mark_wrapper_stage(project, "ajil_alignment", "FAILED_VALIDATION", message="Alignment produced no accepted word-level timestamps.")
            print(
                "FAILED_VALIDATION: alignment did not produce word-level timestamps plus "
                "OPENING_TIMING.json, so the opening clips cannot be trimmed truthfully.",
                file=sys.stderr,
                flush=True,
            )
            return 2
        mark_wrapper_stage(project, "ajil_alignment", "DONE", artifact="timing/BEAT_TIMINGS.json")

    # 5. Everything past here needs the Flow sources. Park the run rather than render an
    #    episode without its opening, and let the watcher resume when Flow answers again.
    if not clips_ready(project):
        absent = ", ".join(path.name for path in missing_clips(project))
        write_pending_state(project, absent, flow_pending_reason)
        print(
            f"QH PIPELINE PARKED: waiting for Flow clips ({absent}). "
            "Narration, timing and music are done; resume to finish the render.",
            flush=True,
        )
        print("FLOW_CLIPS_PENDING", flush=True)
        return 4

    # 6. Cut the Flow sources to the measured narration boundaries (§67).
    clear_pending_state(project)
    trim_outputs = [project / "assets/opening/question_spark_trimmed.mp4", project / "assets/opening/book_transition_trimmed.mp4", project / "timing/OPENING_TRIM_REPORT.json"]
    if all(path.is_file() and path.stat().st_size > 0 for path in trim_outputs):
        print("opening trim reuse", flush=True)
        mark_wrapper_stage(project, "opening_trim", "REUSED", artifact="timing/OPENING_TRIM_REPORT.json")
        report_reused(notifier, "opening_trim", "timing/OPENING_TRIM_REPORT.json")
    else:
        mark_wrapper_stage(project, "opening_trim", "RUNNING")
        try:
            tolerance = opening_speed_tolerance(project, args.creative_brief)
            run_owned_stage([python, "scripts/trim_opening_clips.py", str(project), "--max-rate-adjust", f"{tolerance:.4f}"], notifier, "opening_trim", project / "timing/OPENING_TRIM_REPORT.json", project)
        except subprocess.CalledProcessError as exc:
            mark_wrapper_stage(project, "opening_trim", "FAILED", returncode=exc.returncode)
            raise
        if not all(file_is_usable(path) for path in trim_outputs):
            mark_wrapper_stage(project, "opening_trim", "FAILED_VALIDATION", message="Trim command returned without every required output.")
            raise RuntimeError("Opening trim did not produce both clips and its report.")
        mark_wrapper_stage(project, "opening_trim", "DONE", artifact="timing/OPENING_TRIM_REPORT.json")

    # 7. Render profiles, then timeline → render → QC → publish.
    from run_full_video_pipeline import ensure_audio_mix_profile, ensure_render_profile

    ensure_audio_mix_profile(project)
    apply_render_preferences(ensure_render_profile(project, args.aspect_ratio), args.creative_brief)

    completion = [
        python, "scripts/run_completion_pipeline.py", str(project),
        "--resource-budget", f"{args.resource_budget:.3f}",
    ]
    # The panel freezes non-secret SFX settings in the creative brief. Completion owns the
    # stages because it owns the final timeline/baseline/QC boundary.
    try:
        sfx_enabled = bool((json.loads(args.creative_brief.read_text(encoding="utf-8")).get("_sfx") or {}).get("enabled"))
    except (OSError, ValueError):
        sfx_enabled = False
    if sfx_enabled:
        completion += ["--sfx-config", str(args.creative_brief)]
    completion += ["--motion-config", str(args.creative_brief)]
    if args.publish:
        completion.append("--publish")
        completion.append("--telegram-low-size" if args.telegram_low_size else "--no-telegram-low-size")
        if args.telegram_original:
            completion.append("--telegram-original")
    if args.commit:
        completion.append("--commit")
    run(completion)

    print("FULL QH PIPELINE: PASS", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
