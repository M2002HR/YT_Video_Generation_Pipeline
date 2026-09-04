#!/usr/bin/env python3
"""Question Harvest end to end: visual stages, then narration → timing → trim → mix → render.

This wrapper only sequences real stages. Every step either produces its real artifact or the
run stops with a non-zero exit code — there is no synthetic narration, no proportional
"timing", and no placeholder music anywhere in this file. A stage that cannot run is a
pipeline failure to fix, not a gap to fill with something that merely renders.

Stage order (§57):

    run_question_harvest_pipeline.py   script → images → Flow clips
    run_elevenlabs_voiceover.py        one continuous narration track (§66)
    align_beats.py                     Ajil word timestamps → BEAT_TIMINGS + OPENING_TIMING
    trim_opening_clips.py              cut the Flow sources to the measured boundaries (§67)
    run_pixabay_music.py               background track
    run_completion_pipeline.py         timeline → render → QC → publish
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

#: STT results are only usable for sync when they carry real per-word timestamps.
ACCEPTED_STT_BACKENDS = ("ajil", "local")


def run(command: list[str]) -> None:
    print(f"$ {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


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
    }
    flags: list[str] = []
    for key, flag in mapping.items():
        if advanced.get(key):
            flags += [flag, str(advanced[key])]
    return flags


def apply_subtitle_preference(profile_path: Path, creative_brief: Path) -> None:
    try:
        brief = json.loads(Path(creative_brief).read_text(encoding="utf-8"))
        wanted = bool((brief.get("_qh") or {}).get("show_subtitles", False))
    except (OSError, ValueError):
        wanted = False
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    profile.setdefault("subtitles", {})["enabled"] = wanted
    profile_path.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Question Harvest end-to-end pipeline")
    parser.add_argument("--topic", required=True)
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--content-project", default="question_harvest")
    parser.add_argument("--creative-brief", type=Path, required=True)
    parser.add_argument("--voice-profile", type=Path, required=True)
    parser.add_argument("--aspect-ratio", default="9:16")
    parser.add_argument("--music-provider", default="mixkit")
    parser.add_argument("--publish", action="store_true", help="Publish the finished render.")
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

    # 1. Visual stages: script, plans, world keyframe, book spread, Flow clips, body images.
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
    )

    # 2. One continuous narration track (§66).
    narration = project / "assets" / "audio" / "narration.mp3"
    if narration.is_file():
        print(f"narration reuse: {narration}", flush=True)
    else:
        run(
            [
                python, "scripts/run_elevenlabs_voiceover.py",
                "--video-id", args.video_id,
                "--project", str(project),
                "--profile", str(args.voice_profile),
            ]
        )

    # 3. Real word timestamps, and the measured opening boundaries derived from them.
    if word_timing_is_usable(project):
        print("timing reuse: word-level timestamps already present", flush=True)
    else:
        run([python, "scripts/align_beats.py", str(project), "--fallback-backend", "none"])
        if not word_timing_is_usable(project):
            print(
                "FAILED_VALIDATION: alignment did not produce word-level timestamps plus "
                "OPENING_TIMING.json, so the opening clips cannot be trimmed truthfully.",
                file=sys.stderr,
                flush=True,
            )
            return 2

    # 4. Cut the Flow sources to the measured narration boundaries (§67).
    run([python, "scripts/trim_opening_clips.py", str(project)])

    # 5. Background music.
    music_dir = project / "assets" / "music"
    if music_dir.is_dir() and any(music_dir.iterdir()):
        print("music reuse", flush=True)
    else:
        run(
            [
                python, "scripts/run_pixabay_music.py",
                "--video-id", args.video_id,
                "--project", str(project),
                "--provider", args.music_provider,
            ]
        )

    # 6. Render profiles, then timeline → render → QC → publish.
    from run_full_video_pipeline import ensure_audio_mix_profile, ensure_render_profile

    ensure_audio_mix_profile(project)
    apply_subtitle_preference(ensure_render_profile(project, args.aspect_ratio), args.creative_brief)

    completion = [
        python, "scripts/run_completion_pipeline.py", str(project),
        "--resource-budget", f"{args.resource_budget:.3f}",
    ]
    if args.publish:
        completion.append("--publish")
    if args.commit:
        completion.append("--commit")
    run(completion)

    print("FULL QH PIPELINE: PASS", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
