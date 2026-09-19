#!/usr/bin/env python3
"""Q Station end to end: visual stages, then narration → timing → trim → mix → render.

This wrapper only sequences real stages. Every step either produces its real artifact or the
run stops with a non-zero exit code — there is no synthetic narration, no proportional
"timing", and no placeholder music anywhere in this file. A stage that cannot run is a
pipeline failure to fix, not a gap to fill with something that merely renders.

Stage order (§57):

    run_q_station_pipeline.py   script → images (Flow deferred)
    run_elevenlabs_voiceover.py        one continuous narration track (§66)
    run_pixabay_music.py               background track (needs only narration + brief)
    align_beats.py                     Ajil word timestamps → OPENING_TIMING
    plan_opening_sources.py            select supported Flow durations from real timings
    run_q_station_pipeline.py   Flow clips using the selected source contract
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

_ACTIVE_NOTIFIER = None
_ACTIVE_PROJECT: Path | None = None

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
    message = notifier.stage_started(title, key=stage)
    started = time.perf_counter()
    try:
        run(command)
    except subprocess.CalledProcessError as exc:
        notifier.stage_failure(message, title, time.perf_counter() - started, f"{stage} exited with code {exc.returncode}")
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
        payload = json.loads(timing.read_text(encoding="utf-8"))
        stt = payload.get("stt") or {}
        from align_beats import parse_beats
        expected = parse_beats(project / "VISUAL_BEATS.md")
        actual = payload.get("beats") or []
    except (OSError, ValueError):
        return False
    same_beats = [
        (item.get("beat_id"), " ".join(str(item.get("narration") or "").split()))
        for item in actual if isinstance(item, dict)
    ] == [
        (item["beat_id"], " ".join(item["narration"].split())) for item in expected
    ]
    return same_beats and stt.get("backend") in ACCEPTED_STT_BACKENDS and stt.get("timestamp_source") == "word"


def opening_speed_tolerance(project: Path, creative_brief: Path) -> float:
    """Standing trim rule default: silent opening clips may slow up to 10% to sync."""
    for source in (Path(creative_brief), project / "launch" / "CREATIVE_BRIEF.json"):
        try:
            candidate = (json.loads(source.read_text(encoding="utf-8")).get("_q_station") or {}).get("opening_speed_tolerance")
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
        return float(os.getenv("YT_Q_STATION_OPENING_SPEED_TOLERANCE", "0.1"))
    except ValueError:
        return 0.1


def q_station_overrides(creative_brief: Path) -> list[str]:
    """Model/duration overrides the panel stored in the brief, as CLI flags."""
    try:
        brief = json.loads(Path(creative_brief).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"warn: could not read {creative_brief}: {exc}", flush=True)
        return []
    advanced = brief.get("_q_station") or {}
    mapping = {
        "gemini_image_model": "--gemini-model",
        "image_qc_correction_policy": "--image-qc-correction-policy",
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
    if bool(advanced.get("beat_image_qc_disabled", False)):
        flags.append("--disable-beat-image-qc")
    character = advanced.get("character")
    if isinstance(character, dict):
        mode = str(character.get("mode") or "auto")
        flags += ["--character-mode", mode]
        if mode == "manual" and character.get("character_id"):
            flags += ["--character-id", str(character["character_id"])]
    return flags


def apply_render_preferences(profile_path: Path, creative_brief: Path, topic: str = "") -> None:
    try:
        brief = json.loads(Path(creative_brief).read_text(encoding="utf-8"))
        wanted = bool((brief.get("_q_station") or {}).get("show_subtitles", False))
        word_highlight = bool((brief.get("_subtitle") or {}).get("word_highlight", True))
        style = brief.get("_subtitle") if isinstance(brief.get("_subtitle"), dict) else {}
    except (OSError, ValueError):
        brief, wanted, word_highlight, style = {}, False, True, {}
    from run_full_video_pipeline import apply_branding_preferences, apply_motion_preferences, apply_subtitle_style

    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    subtitles = profile.setdefault("subtitles", {})
    subtitles["enabled"] = wanted
    if not isinstance(subtitles.get("word_highlight"), dict):
        subtitles["word_highlight"] = {}
    subtitles["word_highlight"]["enabled"] = word_highlight
    apply_subtitle_style(subtitles, style)
    profile_path.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")
    # Reuse the canonical profile validator/writer so direct and QStation runs cannot drift.
    apply_motion_preferences(profile_path, brief)
    # Same branding freeze as the direct launch path: without this a regenerated
    # profile keeps title.enabled=true with no text and render_video refuses it.
    apply_branding_preferences(profile_path, brief, topic)


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


def clear_opening_trim_outputs(project: Path) -> None:
    """A changed narration/source plan makes every old trim unsafe to reuse."""
    from presentation_runtime import presentation_for_project

    presentation = presentation_for_project(project)
    for path in (
        presentation.artifacts.path(project, "question_trimmed"),
        presentation.artifacts.path(project, "entry_trimmed"),
        project / "timing" / "OPENING_TRIM_REPORT.json",
    ):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def _ffprobe_seconds(path: Path) -> float | None:
    """Measured source duration, or None when the file is not a real video."""
    try:
        output = subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)],
            text=True,
            timeout=30,
        )
        value = float(output.strip())
    except (subprocess.SubprocessError, ValueError, OSError):
        return None
    return value if value > 0.2 else None


def _opening_targets(project: Path) -> tuple[float | None, float | None]:
    """Measured (clip_a_target, clip_b_target) from OPENING_TIMING.json."""
    try:
        timing = json.loads((project / "timing" / "OPENING_TIMING.json").read_text(encoding="utf-8"))
        spark_end = float(timing["spark_end"])
        transition_end = float(timing["transition_end"])
    except (OSError, ValueError, KeyError, TypeError):
        return None, None
    if not transition_end > spark_end:
        return None, None
    return spark_end, transition_end - spark_end


def _flow_source_satisfies(source: Path, target: float, tolerance: float) -> bool:
    """Whether an existing silent source can still be trimmed to a new target.

    Mirrors plan_opening_sources.choose_source_seconds (capability) and
    trim_opening_clips.trim (rate adjust): a longer source is harmless, and a
    slightly shorter one is allowed only within the configured slow-down.
    """
    duration = _ffprobe_seconds(source)
    if duration is None:
        return False
    return target <= duration + 0.05 or target <= duration * (1 + tolerance) + 1e-9


def restore_reusable_flow_sources(project: Path, tolerance: float) -> list[str]:
    """Restore archived Flow sources that still satisfy the new narration timing.

    A narration/voice revision archives the opening clips via the DAG cascade,
    but the silent sources do not depend on voice words — only on whether their
    measured duration still reaches the new trim boundary. Each clip is judged
    independently: a sufficient archived source is copied back with its receipt
    and prompt audit files so the normal reuse path accepts it; an insufficient
    one is left absent so only that clip is regenerated via Flow.
    """
    from presentation_runtime import presentation_for_project

    try:
        presentation = presentation_for_project(project)
    except Exception as exc:
        print(f"warn: cannot resolve presentation for Flow reuse check: {exc}", flush=True)
        return []
    target_a, target_b = _opening_targets(project)
    if target_a is None or target_b is None:
        return []
    restored: list[str] = []
    for clip, field, target in (("A", "question_source", target_a), ("B", "entry_source", target_b)):
        current = presentation.artifacts.path(project, field)
        if current.is_file() and _flow_source_satisfies(current, target, tolerance):
            continue
        # Most recent archived source first; an older contract is still fine when
        # its duration reaches the new target within tolerance.
        candidates = sorted(
            (project / "pipeline" / "revisions").glob("*/previous"),
            key=lambda path: path.stat().st_mtime_ns if path.exists() else 0,
            reverse=True,
        )
        for previous in candidates:
            try:
                relative = current.relative_to(project)
            except ValueError:
                break
            archived = previous / relative
            if not archived.is_file() or not _flow_source_satisfies(archived, target, tolerance):
                continue
            try:
                import shutil

                current.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(archived, current)
                # Keep the audit trail consistent so stage_flow_clip reuse accepts
                # the restored source instead of treating it as unverified.
                receipt_name = "flow_opening_a" if clip == "A" else "flow_opening_b"
                for extra in (
                    Path("pipeline") / "provider_receipts" / f"{receipt_name}.json",
                    Path(presentation.artifacts.question_prompt if clip == "A" else presentation.artifacts.entry_prompt),
                    Path(f"{presentation.artifacts.question_prompt if clip == 'A' else presentation.artifacts.entry_prompt}.inputs.json"),
                ):
                    src, dst = previous / extra, project / extra
                    if src.is_file():
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src, dst)
            except OSError as exc:
                print(f"warn: could not restore archived Flow clip {clip}: {exc}", flush=True)
                continue
            duration = _ffprobe_seconds(current)
            print(
                f"↻ Flow clip {clip} restored for new target {target:.3f}s "
                f"(archived source {duration:.2f}s).",
                flush=True,
            )
            restored.append(clip)
            break
        else:
            print(
                f"Flow clip {clip} needs regeneration: no current or archived source "
                f"reaches new target {target:.3f}s within {tolerance * 100:.1f}% tolerance.",
                flush=True,
            )
    return restored


def main() -> int:
    parser = argparse.ArgumentParser(description="Q Station end-to-end pipeline")
    parser.add_argument("--topic", required=True)
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--content-project", default="q_station")
    parser.add_argument("--creative-brief", type=Path, required=True)
    parser.add_argument("--voice-profile", type=Path, required=True)
    parser.add_argument("--aspect-ratio", default="9:16")
    parser.add_argument("--regenerate-beats", default="", help="Comma-separated beat IDs to revise, including their continuity downstream.")
    parser.add_argument("--preserve-downstream-beats", action="store_true", help="Regenerate only the explicitly selected beat images; keep later continuity images unchanged.")
    parser.add_argument("--beat-feedback-json", type=Path, help="Operator feedback JSON passed into revised beat prompts.")
    parser.add_argument("--chatgpt-revision-feedback-json", type=Path, help="One-shot ChatGPT review requests for existing beat images before Gemini regeneration.")
    parser.add_argument(
        "--skip-visual-stages",
        action="store_true",
        help="Reuse locked visual assets for a render/audio/publish-only config revision.",
    )
    parser.add_argument("--music-provider", default=None, help="Legacy single music provider.")
    parser.add_argument("--music-providers", default=None, help="Comma-separated music provider priority.")
    parser.add_argument("--music-file", type=Path, default=None, help="Frozen operator-uploaded music; bypasses provider search.")
    parser.add_argument("--music-file-sha256", default="", help="Integrity hash for --music-file.")
    parser.add_argument("--music-source-provider", default="operator_upload")
    parser.add_argument("--music-source-origin", default="upload")
    parser.add_argument("--music-source-url", default="")
    parser.add_argument("--music-source-license", default="")
    parser.add_argument("--music-source-name", default="")
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
    from pipeline_notifier import PipelineNotifier, format_duration
    from pipeline_stages import stage_title
    notifier = PipelineNotifier(
        args.video_id, args.topic,
        state_path=project / "pipeline" / "TELEGRAM_NOTIFICATION_STATE.json",
    )
    global _ACTIVE_NOTIFIER, _ACTIVE_PROJECT
    _ACTIVE_NOTIFIER, _ACTIVE_PROJECT = notifier, project
    if args.regenerate_beats:
        notifier.send(
            "Revision started",
            [
                f"🛠 Beat image(s): {args.regenerate_beats}",
                f"🧭 Policy: {'isolated — other beat images preserved' if args.preserve_downstream_beats else 'continuity cascade'}",
                "↻ Valid unaffected stages will be reused",
            ],
        )
    elif args.skip_visual_stages:
        notifier.send(
            "Render-only revision started",
            ["🔒 Visual generation is locked", "↻ Existing images and opening media will not be sent to providers"],
        )
    else:
        notifier.send("Pipeline started", ["🚀 Q Station workflow active", f"🎯 {args.topic}"])

    from flow_gate import blocked_only_on_flow, clips_ready, missing_clips

    # 1. Prepare every visual artifact that does not depend on the measured narration.
    #    Flow is intentionally deferred: its source-duration contract is selected only after
    #    ElevenLabs audio has real word timestamps.
    flow_pending_reason = ""
    if args.skip_visual_stages:
        # A subtitle/render/audio/publish config revision must be incapable of making a
        # Gemini or Flow request.  This is stronger than cache reuse: an isolated image
        # revision can intentionally leave downstream receipt fingerprints stale.
        print("↻ visual stages locked — render-only revision; no image or Flow provider calls", flush=True)
        mark_wrapper_stage(project, "visual_generation", "REUSED", reason="render-only configuration revision")
    else:
        try:
            run(
                [
                    python, "-u", "scripts/run_q_station_pipeline.py",
                    "--topic", args.topic,
                    "--video-id", args.video_id,
                    "--content-project", args.content_project,
                    "--creative-brief", str(args.creative_brief),
                    "--voice-profile", str(args.voice_profile),
                    "--aspect-ratio", args.aspect_ratio,
                ]
                + q_station_overrides(args.creative_brief)
                + ["--defer-flow-clips"]
                + (["--regenerate-beats", args.regenerate_beats] if args.regenerate_beats else [])
                + (["--preserve-downstream-beats"] if args.preserve_downstream_beats else [])
                + (["--beat-feedback-json", str(args.beat_feedback_json)] if args.beat_feedback_json else [])
                + (["--chatgpt-revision-feedback-json", str(args.chatgpt_revision_feedback_json)] if args.chatgpt_revision_feedback_json else [])
            )
        except subprocess.CalledProcessError:
            only_flow, reason = blocked_only_on_flow(project)
            if not only_flow:
                raise
            flow_pending_reason = reason
            # --defer-flow-clips never contacts Flow, but retain this guard for a partially
            # upgraded run whose state was produced by an earlier wrapper.
            flow_pending_reason = reason

    # 2. One continuous narration track (§66). Reuse is allowed only when the
    # stored audio was made from exactly the current script text and voice
    # settings; a bare usable file is never enough, otherwise a script revision
    # would silently keep speaking stale words while beats move on.
    from run_elevenlabs_voiceover import narration_input, narration_receipt_matches, settings_from_profile
    narration = project / "assets" / "audio" / "narration.mp3"
    narration_matches = False
    try:
        _, narration_text = narration_input(project)
        voice_profile_payload: dict = {}
        if args.voice_profile:
            loaded = json.loads(Path(args.voice_profile).read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                voice_profile_payload = loaded
        narration_matches = file_is_usable(narration) and narration_receipt_matches(
            project, narration_text, settings_from_profile(voice_profile_payload).supplied()
        )
    except (OSError, ValueError, RuntimeError):
        narration_matches = False
    if narration_matches:
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
            notifier.failure(stage_title("elevenlabs_voiceover"), 0, "Narration command returned without a usable artifact.")
            raise RuntimeError(f"Narration is missing or empty: {narration}")
        mark_wrapper_stage(project, "elevenlabs_voiceover", "DONE", artifact=str(narration.relative_to(project)))

    # 3. Background music. It needs only the narration and the brief, so it runs before the
    #    timing: when alignment is blocked by its STT provider, the episode should still gain
    #    its music instead of every resume stopping at the same step with nothing to show.
    music_dir = project / "assets" / "music"
    operator_music: Path | None = None
    if args.music_file is not None:
        from operator_music import audio_duration, install_operator_music
        operator_music = install_operator_music(
            project, args.music_file, args.music_file_sha256, audio_duration(narration), {
                "provider": args.music_source_provider, "origin": args.music_source_origin,
                "source_url": args.music_source_url or None, "license": args.music_source_license or None,
                "original_name": args.music_source_name or args.music_file.name,
            }
        )
        print(f"operator music installed: {operator_music}", flush=True)
    if operator_music is not None or music_is_usable(music_dir):
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
            notifier.failure(stage_title("background_music"), 0, "Music command returned without a usable audio file.")
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
            notifier.failure(stage_title("ajil_alignment"), 0, "Alignment produced no accepted word-level timestamps plus OPENING_TIMING.json.")
            print(
                "FAILED_VALIDATION: alignment did not produce word-level timestamps plus "
                "OPENING_TIMING.json, so the opening clips cannot be trimmed truthfully.",
                file=sys.stderr,
                flush=True,
            )
            return 2
        mark_wrapper_stage(project, "ajil_alignment", "DONE", artifact="timing/BEAT_TIMINGS.json")

    # 5. Convert the measured opening boundaries into supported Flow durations, then create
    #    both clips under that durable contract.  The preferred launch durations remain a
    #    tie-breaker in the planner; they never override an incapable source length.
    #
    #    Planning is local (no provider cost) so it always runs — even for a
    #    render-only revision where a new narration changed the measured boundaries.
    #    Image generation stays locked under --skip-visual-stages; only the Flow
    #    opening clips may be (re)built below, and the QStation runner itself reuses
    #    every sufficient source (receipt duration + prompt + references) so only the
    #    clips that truly need it spend Flow credits.
    plan_path = project / "timing" / "OPENING_SOURCE_PLAN.json"
    mark_wrapper_stage(project, "opening_source_plan", "RUNNING")
    try:
        run_owned_stage(
            [python, "scripts/plan_opening_sources.py", str(project)],
            notifier,
            "opening_source_plan",
            plan_path,
            project,
        )
    except subprocess.CalledProcessError as exc:
        mark_wrapper_stage(project, "opening_source_plan", "FAILED", returncode=exc.returncode)
        raise
    try:
        source_plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        mark_wrapper_stage(project, "opening_source_plan", "FAILED_VALIDATION", message=str(exc))
        raise RuntimeError("Opening-source planner returned without a usable plan.") from exc
    plan_status = str(source_plan.get("status") or "")
    if plan_status == "REUSED":
        mark_wrapper_stage(project, "opening_source_plan", "REUSED", artifact="timing/OPENING_SOURCE_PLAN.json")
    else:
        # A new timing fingerprint or selected source length invalidates only rendered
        # opening derivatives. Source clips are independently checked against their
        # requested-length receipts by the QStation runner below.
        clear_opening_trim_outputs(project)
        mark_wrapper_stage(project, "opening_source_plan", "DONE", artifact="timing/OPENING_SOURCE_PLAN.json")
    if args.skip_visual_stages:
        # A narration/voice revision archives the opening clips via the DAG cascade,
        # but the silent sources only care about duration. Restore per-clip archived
        # sources that still reach the new trim boundary so they are reused instead
        # of being rebuilt; clips that cannot reach it stay absent for regeneration.
        print("↻ visual stages locked — checking archived Flow sources against new narration timing; no image provider calls", flush=True)
        try:
            tolerance = opening_speed_tolerance(project, args.creative_brief)
        except Exception:
            tolerance = 0.1
        try:
            restore_reusable_flow_sources(project, tolerance)
        except Exception as exc:
            print(f"warn: Flow source reuse check failed ({type(exc).__name__}: {exc}); continuing to regeneration check.", flush=True)
        if clips_ready(project):
            print("↻ existing Flow sources satisfy the new timing; skipping Flow regeneration", flush=True)
        else:
            # Only the insufficient clips need Flow. Body images were not invalidated
            # by an audio-only revision, so this reuses them and spends Flow credits
            # solely on the missing/insufficient opening sources.
            print("↻ some Flow sources cannot reach the new timing; regenerating only those via Flow (images reused)", flush=True)
            try:
                run(
                    [
                        python, "-u", "scripts/run_q_station_pipeline.py",
                        "--topic", args.topic,
                        "--video-id", args.video_id,
                        "--content-project", args.content_project,
                        "--creative-brief", str(args.creative_brief),
                        "--voice-profile", str(args.voice_profile),
                        "--aspect-ratio", args.aspect_ratio,
                        "--use-opening-source-plan",
                    ]
                    + q_station_overrides(args.creative_brief)
                    + (["--regenerate-beats", args.regenerate_beats] if args.regenerate_beats else [])
                    + (["--preserve-downstream-beats"] if args.preserve_downstream_beats else [])
                    + (["--beat-feedback-json", str(args.beat_feedback_json)] if args.beat_feedback_json else [])
                    + (["--chatgpt-revision-feedback-json", str(args.chatgpt_revision_feedback_json)] if args.chatgpt_revision_feedback_json else [])
                )
            except subprocess.CalledProcessError:
                only_flow, reason = blocked_only_on_flow(project)
                if not only_flow:
                    raise
                flow_pending_reason = reason
    else:
        try:
            run(
                [
                    python, "-u", "scripts/run_q_station_pipeline.py",
                    "--topic", args.topic,
                    "--video-id", args.video_id,
                    "--content-project", args.content_project,
                    "--creative-brief", str(args.creative_brief),
                    "--voice-profile", str(args.voice_profile),
                    "--aspect-ratio", args.aspect_ratio,
                    "--use-opening-source-plan",
                ]
                + q_station_overrides(args.creative_brief)
                + (["--regenerate-beats", args.regenerate_beats] if args.regenerate_beats else [])
                + (["--preserve-downstream-beats"] if args.preserve_downstream_beats else [])
                + (["--beat-feedback-json", str(args.beat_feedback_json)] if args.beat_feedback_json else [])
                + (["--chatgpt-revision-feedback-json", str(args.chatgpt_revision_feedback_json)] if args.chatgpt_revision_feedback_json else [])
            )
        except subprocess.CalledProcessError:
            only_flow, reason = blocked_only_on_flow(project)
            if not only_flow:
                raise
            flow_pending_reason = reason

    # 6. Everything past here needs the Flow sources. Park the run rather than render an
    #    episode without its opening, and let the watcher resume when Flow answers again.
    if not clips_ready(project):
        absent = ", ".join(path.name for path in missing_clips(project))
        write_pending_state(project, absent, flow_pending_reason)
        print(
            f"QStation PIPELINE PARKED: waiting for Flow clips ({absent}). "
            "Narration, timing and music are done; resume to finish the render.",
            flush=True,
        )
        print("FLOW_CLIPS_PENDING", flush=True)
        notifier.send(
            "Waiting for Flow",
            [
                "⏸️ Render is parked; completed work remains reusable",
                f"🎬 Missing: {absent}",
                "▶ Resume after Flow produces the required clips",
            ],
        )
        return 4

    # 7. Cut the Flow sources to the measured narration boundaries (§67).
    clear_pending_state(project)
    from presentation_runtime import presentation_for_project
    presentation = presentation_for_project(project)
    trim_outputs = [
        presentation.artifacts.path(project, "question_trimmed"),
        presentation.artifacts.path(project, "entry_trimmed"),
        project / "timing/OPENING_TRIM_REPORT.json",
    ]
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

    # 8. Render profiles, then timeline → render → QC → publish.
    from run_full_video_pipeline import ensure_audio_mix_profile, ensure_render_profile

    try:
        brief_payload = json.loads(args.creative_brief.read_text(encoding="utf-8"))
        audio_settings = brief_payload.get("_audio") if isinstance(brief_payload.get("_audio"), dict) else {}
        narration_gain_db = float(audio_settings.get("narration_gain_db", 0))
    except (OSError, ValueError, TypeError):
        narration_gain_db = 0.0
    mix_artifact = project / "audio_mix/AUDIO_MIX_PROFILE.json"
    mix_started = time.perf_counter()
    mix_message = notifier.stage_started(stage_title("audio_mix_profile"), key="audio_mix_profile")
    mark_wrapper_stage(project, "audio_mix_profile", "RUNNING")
    try:
        ensure_audio_mix_profile(project, narration_gain_db)
    except Exception as exc:
        mark_wrapper_stage(project, "audio_mix_profile", "FAILED", error=f"{type(exc).__name__}: {exc}"[:800])
        notifier.stage_failure(mix_message, stage_title("audio_mix_profile"), time.perf_counter() - mix_started, str(exc))
        raise
    mark_wrapper_stage(project, "audio_mix_profile", "DONE", artifact=str(mix_artifact.relative_to(project)))
    notifier.stage_update(mix_message, stage_title("audio_mix_profile"), ["✅ Stage complete", f"⏱ Duration: {format_duration(time.perf_counter() - mix_started)}", "📄 Saved: audio_mix/AUDIO_MIX_PROFILE.json"])

    render_artifact = project / "render/RENDER_PROFILE.json"
    render_started = time.perf_counter()
    render_message = notifier.stage_started(stage_title("render_profile"), key="render_profile")
    mark_wrapper_stage(project, "render_profile", "RUNNING")
    try:
        apply_render_preferences(ensure_render_profile(project, args.aspect_ratio), args.creative_brief, args.topic)
    except Exception as exc:
        mark_wrapper_stage(project, "render_profile", "FAILED", error=f"{type(exc).__name__}: {exc}"[:800])
        notifier.stage_failure(render_message, stage_title("render_profile"), time.perf_counter() - render_started, str(exc))
        raise
    mark_wrapper_stage(project, "render_profile", "DONE", artifact=str(render_artifact.relative_to(project)))
    notifier.stage_update(render_message, stage_title("render_profile"), ["✅ Stage complete", f"⏱ Duration: {format_duration(time.perf_counter() - render_started)}", "📄 Saved: render/RENDER_PROFILE.json"])

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

    notifier.send(
        "Pipeline complete",
        ["✅ All enabled stages passed", "📦 Final Telegram delivery completed" if args.publish else "📦 Delivery was not requested"],
    )
    print("FULL QStation PIPELINE: PASS", flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        if _ACTIVE_NOTIFIER is not None:
            from pipeline_notifier import safe_detail
            _ACTIVE_NOTIFIER.send("Pipeline failed", ["❌ The workflow stopped", safe_detail(f"{type(exc).__name__}: {exc}"), "↻ Completed stages remain reusable; fix the cause and resume."])
        if _ACTIVE_PROJECT is not None:
            state_path = _ACTIVE_PROJECT / "pipeline/WRAPPER_RUNTIME_STATE.json"
            try:
                payload = json.loads(state_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                payload = {"schema_version": 1, "events": []}
            payload.update({"status": "FAILED", "failed_at": datetime.now(timezone.utc).isoformat(), "error": f"{type(exc).__name__}: {exc}"[:1000]})
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        raise
