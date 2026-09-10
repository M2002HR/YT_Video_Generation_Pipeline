#!/usr/bin/env python3
"""Trim the two Flow opening clips to the *measured* narration boundaries (§67).

The single source of truth is `timing/OPENING_TIMING.json`, which `align_beats.py` derives
from real word timestamps:

    Clip A (question spark)  -> 0 .. spark_end
    Clip B (book transition) -> spark_end .. transition_end

Flow is asked for clips one second longer than the planned segment so there is headroom for
a narration that runs slightly long. If the narration overruns the source by more than the
configured rate tolerance, that is a planning failure: the script refuses to clamp and
exits non-zero so the pipeline can replan. Within the tolerance (default 10%), the silent
opening video is rate-adjusted (slowed down) to land exactly on the measured boundary —
Flow audio is discarded here (§68), so this changes no voice, only the silent picture.

Sources : assets/opening/question_spark_source.mp4, assets/opening/book_transition_source.mp4
Outputs : assets/opening/question_spark_trimmed.mp4, assets/opening/book_transition_trimmed.mp4

Flow audio is discarded here (§68) — the narration track is the only audio in the render.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

#: How far the trimmed file may sit from its target before we call it a defect.
MAX_TRIM_DRIFT_SECONDS = 0.12

#: How far the *sum* of the two clips may sit from the measured transition end. This is the
#: figure the timeline enforces (build_timeline.py), and it is tighter than the per-clip
#: tolerance: ffmpeg cuts on whole frames, so each clip lands up to a frame from its request
#: and the two errors add. Without closing the loop on the total, a pair that passed here was
#: rejected there with "re-run trim_opening_clips.py", which on its own changed nothing.
MAX_OPENING_TOTAL_DRIFT_SECONDS = 0.04

#: A trim shorter than this cannot be a real shot.
MIN_TARGET_SECONDS = 0.5

#: Standing rule: a silent opening clip may be rate-adjusted (slowed down) by up to this
#: fraction so its duration lands on the measured narration boundary. Beyond it the run
#: fails and the pipeline replans (longer Flow clip or shorter narration segment).
DEFAULT_MAX_RATE_ADJUST = 0.10


class TrimError(RuntimeError):
    """A trim that cannot be performed truthfully."""


def ffprobe_duration(path: Path) -> float:
    output = subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(path),
        ],
        text=True,
        timeout=30,
    )
    return float(output.strip())


def read_targets(video_dir: Path) -> tuple[float, float, dict]:
    """Return ``(clip_a_seconds, clip_b_seconds, timing)`` from the measured timing file."""
    timing_path = video_dir / "timing" / "OPENING_TIMING.json"
    if not timing_path.is_file():
        raise TrimError(
            f"{timing_path} is missing. Run align_beats.py first: opening trims are cut to "
            "measured word timings, never to an estimate."
        )
    timing = json.loads(timing_path.read_text(encoding="utf-8"))
    try:
        spark_end = float(timing["spark_end"])
        transition_end = float(timing["transition_end"])
    except (KeyError, TypeError, ValueError) as exc:
        raise TrimError(f"OPENING_TIMING.json lacks usable boundaries: {exc}") from exc

    clip_a = spark_end
    clip_b = transition_end - spark_end
    for name, value in (("Clip A", clip_a), ("Clip B", clip_b)):
        if value < MIN_TARGET_SECONDS:
            raise TrimError(
                f"{name} target is {value:.3f}s, which is too short to be real narration. "
                "Check the alignment before rendering."
            )
    return clip_a, clip_b, timing


def resolve_max_rate_adjust(cli_value: float | None, video_dir: Path) -> float:
    """Set precedence: CLI flag > launch brief > project defaults > env > built-in 0.10."""
    if cli_value is not None:
        value = float(cli_value)
        if not 0 <= value <= 0.5:
            raise TrimError(f"--max-rate-adjust {value} is outside the accepted 0..0.5 range.")
        return value
    brief_path = video_dir / "launch" / "CREATIVE_BRIEF.json"
    try:
        brief = json.loads(brief_path.read_text(encoding="utf-8"))
        candidate = (brief.get("_qh") or {}).get("opening_speed_tolerance")
        if candidate is not None and str(candidate) != "":
            value = float(candidate)
            if not 0 <= value <= 0.5:
                raise TrimError(f"opening_speed_tolerance {candidate!r} is outside 0..0.5.")
            return value
    except (OSError, ValueError) as exc:
        if isinstance(exc, TrimError):
            raise
    launch_path = video_dir / "launch" / "LAUNCH_REQUEST.json"
    try:
        launch = json.loads(launch_path.read_text(encoding="utf-8"))
        candidate = (launch.get("video_generation") or {}).get("opening_speed_tolerance")
        if candidate is not None and str(candidate) != "":
            value = float(candidate)
            if not 0 <= value <= 0.5:
                raise TrimError(f"opening_speed_tolerance {candidate!r} is outside 0..0.5.")
            return value
    except (OSError, ValueError) as exc:
        if isinstance(exc, TrimError):
            raise
    try:
        root = Path(__file__).resolve().parents[1]
        project_id: str | None = None
        try:
            launch = json.loads((video_dir / "launch" / "LAUNCH_REQUEST.json").read_text(encoding="utf-8"))
            project_id = str(launch.get("content_project") or "")
        except (OSError, ValueError):
            project_id = None
        candidates = []
        if project_id:
            candidates.append(root / "projects" / project_id / "PROJECT.json")
        candidates.append(root / "projects" / "q_station" / "PROJECT.json")
        for candidate_path in candidates:
            try:
                defaults = json.loads(candidate_path.read_text(encoding="utf-8")).get("defaults") or {}
            except (OSError, ValueError):
                continue
            if defaults.get("opening_speed_tolerance") is not None:
                return float(defaults["opening_speed_tolerance"])
    except (OSError, ValueError):
        pass
    env_candidate = os.getenv("YT_QUESTION_HARVEST_OPENING_SPEED_TOLERANCE")
    if env_candidate is not None and str(env_candidate).strip() != "":
        try:
            return float(env_candidate)
        except ValueError:
            pass
    return DEFAULT_MAX_RATE_ADJUST


def trim(source: Path, destination: Path, target: float, max_rate_adjust: float) -> tuple[float, float, bool]:
    """Cut ``source`` to ``target`` seconds without audio.

    Returns ``(actual_duration, speed_factor, rate_adjusted)``. When the narration needs
    up to ``max_rate_adjust`` more than the source holds, the silent video is slowed down
    (``setpts``) instead of failing; anything beyond that is still a planning failure.
    """
    if not source.is_file():
        raise TrimError(f"Source clip missing: {source}")
    source_duration = ffprobe_duration(source)
    if target <= source_duration + 0.05:
        destination.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(source),
                "-t",
                f"{target:.3f}",
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                str(destination),
            ],
            check=True,
            capture_output=True,
        )
        return ffprobe_duration(destination), 1.0, False
    if target <= source_duration * (1 + max_rate_adjust) + 1e-9:
        factor = target / source_duration
        destination.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(source),
                "-vf",
                f"setpts={factor:.6f}*PTS,fps=24",
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                str(destination),
            ],
            check=True,
            capture_output=True,
        )
        return ffprobe_duration(destination), round(factor, 6), True
    raise TrimError(
        f"{source.name} is {source_duration:.3f}s but the narration needs "
        f"{target:.3f}s (overrun {(target - source_duration):.3f}s > "
        f"allowed {max_rate_adjust * 100:.1f}%). Regenerate a longer clip or "
        "shorten that narration segment."
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Trim Flow opening clips to measured narration boundaries."
    )
    parser.add_argument("video_dir", type=Path)
    parser.add_argument(
        "--max-rate-adjust",
        type=float,
        default=None,
        help="Max fraction a silent opening clip may be slowed to meet narration (default 0.10).",
    )
    args = parser.parse_args()

    video_dir = Path(args.video_dir).resolve()
    max_rate_adjust = resolve_max_rate_adjust(args.max_rate_adjust, video_dir)
    clip_a_target, clip_b_target, timing = read_targets(video_dir)

    opening = video_dir / "assets" / "opening"
    jobs = [
        ("Clip A", opening / "question_spark_source.mp4", opening / "question_spark_trimmed.mp4", clip_a_target),
        ("Clip B", opening / "book_transition_source.mp4", opening / "book_transition_trimmed.mp4", clip_b_target),
    ]

    print(
        f"Opening trims for {video_dir.name}: "
        f"A {clip_a_target:.3f}s (0 → spark_end), "
        f"B {clip_b_target:.3f}s (spark_end → transition_end)",
        flush=True,
    )

    def cut(label: str, source: Path, destination: Path, target: float) -> dict:
        actual, speed_factor, rate_adjusted = trim(source, destination, target, max_rate_adjust)
        drift = actual - target
        extra = f", rate x{speed_factor:.4f}" if rate_adjusted else ""
        print(
            f"  {label}: {destination.name} {actual:.3f}s "
            f"(target {target:.3f}s, drift {drift:+.3f}s{extra})",
            flush=True,
        )
        if abs(drift) > MAX_TRIM_DRIFT_SECONDS:
            raise TrimError(
                f"{label} trimmed to {actual:.3f}s but {target:.3f}s was requested "
                f"(drift {drift:+.3f}s > {MAX_TRIM_DRIFT_SECONDS}s). The render would drift "
                "against the narration."
            )
        return {
            "label": label,
            "path": str(destination),
            "target": round(target, 3),
            "actual": round(actual, 3),
            "speed_factor": speed_factor,
            "rate_adjusted": rate_adjusted,
        }

    results = [cut(label, source, destination, target) for label, source, destination, target in jobs]

    # The boundary that matters is where the narration says the transition ends, so the total
    # is corrected rather than merely reported: Clip B absorbs the frame-rounding of both cuts.
    # One frame of shot length is invisible; a total that misses the boundary is not, and the
    # timeline refuses it.
    total_target = clip_a_target + clip_b_target
    label_b, source_b, destination_b, _ = jobs[1]
    for attempt in range(3):
        drift = sum(item["actual"] for item in results) - total_target
        if abs(drift) <= MAX_OPENING_TOTAL_DRIFT_SECONDS:
            break
        adjusted = max(MIN_TARGET_SECONDS, results[1]["target"] - drift)
        print(
            f"  correcting {label_b} by {-drift:+.3f}s "
            f"(opening total drift {drift:+.3f}s > {MAX_OPENING_TOTAL_DRIFT_SECONDS}s)",
            flush=True,
        )
        results[1] = cut(label_b, source_b, destination_b, adjusted)
    else:
        drift = sum(item["actual"] for item in results) - total_target
        raise TrimError(
            f"The opening clips total {sum(item['actual'] for item in results):.3f}s but the "
            f"narration puts the transition end at {total_target:.3f}s "
            f"(drift {drift:+.3f}s). The clips cannot be cut to that boundary."
        )

    report = {
        "spark_end": timing.get("spark_end"),
        "transition_end": timing.get("transition_end"),
        "max_rate_adjust": max_rate_adjust,
        "clips": results,
        "opening_total_seconds": round(sum(item["actual"] for item in results), 3),
        "opening_total_target_seconds": round(clip_a_target + clip_b_target, 3),
        "opening_total_drift_seconds": round(
            sum(item["actual"] for item in results) - (clip_a_target + clip_b_target), 3
        ),
    }
    (video_dir / "timing" / "OPENING_TRIM_REPORT.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Opening total: {report['opening_total_seconds']:.3f}s", flush=True)
    print("TRIM DONE", flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except TrimError as exc:
        print(f"FAILED_VALIDATION: {exc}", file=sys.stderr, flush=True)
        sys.exit(2)
