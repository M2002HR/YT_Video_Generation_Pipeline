#!/usr/bin/env python3
"""Render a video from TIMELINE.json using FFmpeg.

The first render intentionally stays simple and deterministic:
- one image per beat
- smooth center-only motion with no lateral pan/jitter
- hard cuts at beat boundaries
- narration as the master audio
- readable phrase subtitles

Example:
    python scripts/render_video.py \
      videos/001_brain_replays_embarrassing_moments
"""

from __future__ import annotations

import argparse
import json
import math
import os
import resource
import shlex
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

#: Share of the machine a render may use. The server this runs on has two vCPUs and 7 GB,
#: and an uncapped x264 makes SSH, VNC and the watchdog unresponsive for the whole render.
DEFAULT_RESOURCE_BUDGET = 0.8

#: Supersampling multiplies the working frame area, which is where render memory goes.
#: Above this many megapixels of intermediate frame the factor is reduced rather than
#: letting the render get OOM-killed halfway through.
MAX_SUPERSAMPLED_MEGAPIXELS = 12.0


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return data


def require_binary(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(
            f"{name} was not found in PATH. Install FFmpeg before rendering."
        )
    return path


def ffmpeg_has_ass_filter(ffmpeg: str) -> bool:
    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-filters"],
        capture_output=True,
        text=True,
        check=False,
    )
    text = (result.stdout or "") + "\n" + (result.stderr or "")
    return any(
        line.strip().split(maxsplit=2)[1:2] == ["ass"]
        for line in text.splitlines()
        if line.strip()
    )


#: A clip may fall this far short of its timeline slot before the render is a lie.
VIDEO_SLOT_TOLERANCE = 0.04


def cpu_count() -> int:
    """Schedulable CPUs, honouring cgroup/affinity limits rather than the host total."""
    try:
        return max(1, len(os.sched_getaffinity(0)))
    except AttributeError:
        return max(1, os.cpu_count() or 1)


def budgeted_threads(budget: float, *, cpus: int | None = None) -> int:
    """``round(cpus * budget)``, never zero and never more than the machine has."""
    total = cpus if cpus is not None else cpu_count()
    share = max(0.05, min(1.0, float(budget)))
    return max(1, min(total, round(total * share)))


def capped_supersample(requested: int, width: int, height: int) -> tuple[int, str]:
    """Reduce the supersample factor until the intermediate frame fits the memory budget."""
    factor = max(1, int(requested))
    pixels = width * height
    while factor > 1 and (pixels * factor * factor) / 1_000_000 > MAX_SUPERSAMPLED_MEGAPIXELS:
        factor -= 1
    if factor != max(1, int(requested)):
        return factor, (
            f"supersample reduced {requested}->{factor} to stay under "
            f"{MAX_SUPERSAMPLED_MEGAPIXELS:.0f} MP of intermediate frame"
        )
    return factor, ""


def child_peak_rss_mb() -> float:
    """Peak resident memory of the FFmpeg child, as the kernel measured it."""
    try:
        usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    except (ValueError, OSError):
        return 0.0
    return round(usage.ru_maxrss / 1024, 1)


def ionice_prefix() -> list[str]:
    """Best-effort idle I/O class, so a long render does not starve the rest of the box."""
    binary = shutil.which("ionice")
    if not binary:
        return []
    return [binary, "-c", "2", "-n", "7"]


def resolve_video_path(video_dir: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return video_dir / path


def escape_filter_path(path: Path) -> str:
    value = str(path.resolve())
    value = value.replace("\\", "\\\\")
    value = value.replace(":", r"\:")
    value = value.replace("'", r"\'")
    return value


def motion_filter(
    *,
    input_index: int,
    label: str,
    width: int,
    height: int,
    fps: int,
    duration: float,
    motion: str,
    strength: float,
    supersample: int,
) -> str:
    """Create smooth center-only motion.

    Lateral pan effects were removed because integer crop movement inside
    FFmpeg's zoompan can look like micro-jitter on illustrated stills.

    Zoom effects are rendered on a supersampled canvas and downscaled afterward,
    which greatly reduces rounding shimmer while keeping subtle motion.
    """

    frames = max(2, int(math.ceil(duration * fps)))
    strength = max(0.0, min(float(strength), 0.10))
    supersample = max(1, min(int(supersample), 4))

    if motion == "still" or strength <= 0:
        return (
            f"[{input_index}:v]"
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},"
            "setsar=1,"
            f"fps={fps},"
            f"trim=duration={duration:.6f},"
            "setpts=PTS-STARTPTS"
            f"[{label}]"
        )

    work_width = width * supersample
    work_height = height * supersample
    progress = f"min(on/{frames - 1},1)"

    if motion == "zoom_out":
        effective_strength = strength
        z = f"1+{effective_strength:.6f}*(1-{progress})"
    elif motion == "slow_zoom_in":
        effective_strength = strength * 0.60
        z = f"1+{effective_strength:.6f}*{progress}"
    elif motion == "slow_zoom_out":
        effective_strength = strength * 0.60
        z = f"1+{effective_strength:.6f}*(1-{progress})"
    else:
        effective_strength = strength
        z = f"1+{effective_strength:.6f}*{progress}"

    # Always keep the crop centered. No pan_x/pan_y animation.
    x = "iw/2-(iw/zoom/2)"
    y = "ih/2-(ih/zoom/2)"

    return (
        f"[{input_index}:v]"
        f"scale={work_width}:{work_height}:force_original_aspect_ratio=increase,"
        f"crop={work_width}:{work_height},"
        "setsar=1,"
        f"zoompan="
        f"z='{z}':"
        f"x='{x}':"
        f"y='{y}':"
        f"d=1:s={work_width}x{work_height}:fps={fps},"
        f"scale={width}:{height}:flags=lanczos,"
        f"trim=duration={duration:.6f},"
        "setpts=PTS-STARTPTS"
        f"[{label}]"
    )


def probe_video(ffprobe: str, path: Path) -> dict[str, Any]:
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type,width,height,r_frame_rate",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    return payload if isinstance(payload, dict) else {}


def main() -> None:
    parser = argparse.ArgumentParser(description="Render video timeline with FFmpeg.")
    parser.add_argument("video_dir", type=Path)
    parser.add_argument(
        "--timeline",
        type=Path,
        default=None,
        help="Defaults to <video>/timeline/TIMELINE.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Defaults to <video>/assets/renders/preview.mp4",
    )
    parser.add_argument(
        "--no-subtitles",
        action="store_true",
        help="Render without burning subtitles.",
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=None,
        help="Override the profile FFmpeg thread cap. A cap of 1 keeps a small server responsive.",
    )
    parser.add_argument(
        "--resource-budget",
        type=float,
        default=float(os.getenv("YT_RENDER_RESOURCE_BUDGET", str(DEFAULT_RESOURCE_BUDGET))),
        help=(
            "Share of the machine the render may use (default 0.8). Sets the thread caps from "
            "the schedulable CPU count unless --threads or the profile overrides them."
        ),
    )
    parser.add_argument(
        "--nice",
        type=int,
        default=int(os.getenv("YT_RENDER_NICE", "10")),
        help="Niceness for FFmpeg (0-19). Combined with idle I/O priority when ionice exists.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and print the FFmpeg command without running it.",
    )
    args = parser.parse_args()

    ffmpeg = require_binary("ffmpeg")
    ffprobe = require_binary("ffprobe")

    video_dir = args.video_dir.expanduser().resolve()
    timeline_path = (
        args.timeline.expanduser().resolve()
        if args.timeline
        else video_dir / "timeline" / "TIMELINE.json"
    )

    if not timeline_path.exists():
        raise FileNotFoundError(
            f"Timeline not found: {timeline_path}\n"
            "Build it first with: "
            f"python scripts/build_timeline.py {video_dir}"
        )

    timeline = load_json(timeline_path)

    profile_value = str(timeline.get("render_profile") or "render/RENDER_PROFILE.json")
    profile_path = resolve_video_path(video_dir, profile_value)
    profile = load_json(profile_path)

    resolution = timeline.get("resolution") or {}
    width = int(resolution.get("width", 1920))
    height = int(resolution.get("height", 1080))
    fps = int(timeline.get("fps", 30))
    duration = float(timeline["duration"])

    beats_value = timeline.get("beats")
    if not isinstance(beats_value, list) or not beats_value:
        raise ValueError("Timeline contains no beats.")

    beats = [dict(item) for item in beats_value if isinstance(item, dict)]
    if len(beats) != len(beats_value):
        raise ValueError("Timeline contains an invalid beat entry.")

    audio_path = resolve_video_path(video_dir, str(timeline["audio"]))
    if not audio_path.exists():
        raise FileNotFoundError(f"Narration audio not found: {audio_path}")

    # Mixed-media validation: check appropriate asset per media_type (§69)
    image_paths: list[Path] = []  # kept for backward compatibility but will hold mixed input paths
    for beat in beats:
        mt = str(beat.get("media_type") or "image").lower()
        if mt == "video":
            src = beat.get("source") or beat.get("image")
            if not src:
                raise ValueError(f"Video beat {beat.get('beat_id')} missing source")
            p = resolve_video_path(video_dir, str(src))
            if not p.exists():
                raise FileNotFoundError(f"Beat {beat['beat_id']} video not found: {p}")
            # A clip shorter than its slot silently shortens the concat and drifts the
            # narration against everything after it, so it fails here instead (§70).
            slot = float(beat["duration"])
            probed = probe_video(ffprobe, p).get("format") or {}
            actual = float(probed.get("duration") or 0.0)
            if actual + VIDEO_SLOT_TOLERANCE < slot:
                raise ValueError(
                    f"Beat {beat['beat_id']} needs {slot:.3f}s of video but {p.name} is only "
                    f"{actual:.3f}s. Re-generate or re-trim that clip: rendering it would drop "
                    f"{slot - actual:.3f}s and desynchronise the narration."
                )
            image_paths.append(p)  # reuse list for input order (actually mixed)
        else:
            src = beat.get("image") or beat.get("source")
            if not src:
                raise ValueError(f"Image beat {beat.get('beat_id')} missing image/source")
            p = resolve_video_path(video_dir, str(src))
            if not p.exists():
                raise FileNotFoundError(f"Beat {beat['beat_id']} image not found: {p}")
            image_paths.append(p)

    output_path = (
        args.output.expanduser().resolve()
        if args.output
        else video_dir / "assets" / "renders" / "preview.mp4"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    motion_cfg = profile.get("motion") if isinstance(profile.get("motion"), dict) else {}
    motion_enabled = bool(motion_cfg.get("enabled", True))
    motion_strength = float(motion_cfg.get("strength", 0.035))
    motion_supersample, supersample_note = capped_supersample(
        int(motion_cfg.get("supersample", 2)), width, height
    )
    if supersample_note:
        print(f"Resource budget: {supersample_note}")

    subtitle_cfg = (
        profile.get("subtitles")
        if isinstance(profile.get("subtitles"), dict)
        else {}
    )
    subtitles_enabled = bool(subtitle_cfg.get("enabled", True)) and not args.no_subtitles
    subtitle_path = video_dir / "timeline" / "SUBTITLES.ass"

    if subtitles_enabled:
        if not subtitle_path.exists():
            raise FileNotFoundError(
                f"Subtitle file not found: {subtitle_path}\n"
                "Rebuild the timeline first."
            )
        if not ffmpeg_has_ass_filter(ffmpeg):
            raise RuntimeError(
                "This FFmpeg build does not expose the 'ass' subtitle filter. "
                "Install an FFmpeg build with libass, or render with --no-subtitles."
            )

    video_cfg = profile.get("video") if isinstance(profile.get("video"), dict) else {}
    audio_cfg = profile.get("audio") if isinstance(profile.get("audio"), dict) else {}

    video_codec = str(video_cfg.get("codec", "libx264"))
    preset = str(video_cfg.get("preset", "medium"))
    crf = int(video_cfg.get("crf", 18))
    pixel_format = str(video_cfg.get("pixel_format", "yuv420p"))
    audio_codec = str(audio_cfg.get("codec", "aac"))
    audio_bitrate = str(audio_cfg.get("bitrate", "192k"))

    resource_cfg = (
        profile.get("resource_limits")
        if isinstance(profile.get("resource_limits"), dict)
        else {}
    )
    # Precedence: --threads (explicit) > profile ffmpeg_threads > the resource budget.
    budget_threads = budgeted_threads(args.resource_budget)
    if args.threads is not None:
        thread_cap = max(1, args.threads)
        thread_source = "--threads"
    elif "ffmpeg_threads" in resource_cfg:
        thread_cap = max(1, int(resource_cfg["ffmpeg_threads"]))
        thread_source = "render profile"
    else:
        thread_cap = budget_threads
        thread_source = f"{args.resource_budget:.2f} of {cpu_count()} CPU(s)"
    filter_threads = max(1, int(resource_cfg.get("filter_threads", thread_cap)))
    filter_complex_threads = max(
        1, int(resource_cfg.get("filter_complex_threads", filter_threads))
    )

    # These are deliberately global options. Without explicit caps, FFmpeg can
    # schedule filters and x264 across every vCPU, starving SSH/VNC on small
    # Ordak servers during a long render.
    command: list[str] = [
        ffmpeg,
        "-hide_banner",
        "-nostats",
        "-loglevel",
        "warning",
        "-y",
        "-threads",
        str(thread_cap),
        "-filter_threads",
        str(filter_threads),
        "-filter_complex_threads",
        str(filter_complex_threads),
    ]

    # Mixed-media inputs: image vs video (§69-70)
    # Build input list and remember which indices are video
    media_types: list[str] = []
    input_paths: list[Path] = []
    for beat in beats:
        mt = str(beat.get("media_type") or "image").lower()
        # legacy beats without media_type -> image
        if mt not in ("video", "image"):
            mt = "image"
        # resolve path: for video use source, for image use image/source
        if mt == "video":
            src = beat.get("source") or beat.get("image")
            if not src:
                raise ValueError(f"Video beat {beat.get('beat_id')} missing source")
            path = resolve_video_path(video_dir, str(src))
            # Flow sources may contain audio — we strip it, so mark as video
            media_types.append("video")
            input_paths.append(path)
        else:
            src = beat.get("image") or beat.get("source")
            path = resolve_video_path(video_dir, str(src))
            media_types.append("image")
            input_paths.append(path)

    for idx, (beat, path, mt) in enumerate(zip(beats, input_paths, media_types)):
        if not path.exists():
            raise FileNotFoundError(f"Beat {beat.get('beat_id')} {mt} not found: {path}")
        dur = float(beat["duration"])
        if mt == "image":
            command.extend(["-loop", "1", "-framerate", str(fps), "-t", f"{dur:.6f}", "-i", str(path)])
        else:
            # video: strip audio via -an (we also ensure later mapping ignores video audio), normalize via filter
            # use accurate seek if needed; for now, input as is and trim via filter if source longer than needed
            command.extend(["-i", str(path)])

    audio_input_index = len(input_paths)
    command.extend(["-i", str(audio_path)])

    filter_parts: list[str] = []
    labels: list[str] = []

    for index, (beat, mt) in enumerate(zip(beats, media_types)):
        label = f"v{index}"
        labels.append(f"[{label}]")
        dur = float(beat["duration"])
        if mt == "video":
            # Normalize video: scale+pad to target, set SAR, fps, format, trim/pad to exact duration
            # §70: normalize dimensions, SAR, pixel format, frame rate, strip Flow source audio
            # We trim to dur via -t on input already, but ensure filter outputs exactly dur
            # Use fps and scale filters
            filter_parts.append(
                f"[{index}:v]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1,fps={fps},format={pixel_format},trim=duration={dur:.6f},setpts=PTS-STARTPTS[{label}]"
            )
        else:
            motion = str(beat.get("motion") or "still") if motion_enabled else "still"
            strength = motion_strength if motion_enabled else 0.0
            filter_parts.append(
                motion_filter(
                    input_index=index,
                    label=label,
                    width=width,
                    height=height,
                    fps=fps,
                    duration=dur,
                    motion=motion,
                    strength=strength,
                    supersample=motion_supersample,
                )
            )

    concat_output = "vcat"
    filter_parts.append(
        "".join(labels)
        + f"concat=n={len(beats)}:v=1:a=0[{concat_output}]"
    )

    final_video_label = concat_output
    if subtitles_enabled:
        final_video_label = "vout"
        ass_path = escape_filter_path(subtitle_path)
        filter_parts.append(
            f"[{concat_output}]ass=filename='{ass_path}'[{final_video_label}]"
        )

    filter_complex = ";".join(filter_parts)

    command.extend(
        [
            "-filter_complex",
            filter_complex,
            "-map",
            f"[{final_video_label}]",
            "-map",
            f"{audio_input_index}:a:0",
            "-t",
            f"{duration:.6f}",
            "-c:v",
            video_codec,
            # ``-threads`` must appear in the output encoder option group;
            # the earlier global option only constrains decoder threads.
            "-threads",
            str(thread_cap),
            "-preset",
            preset,
            "-crf",
            str(crf),
            "-pix_fmt",
            pixel_format,
            "-c:a",
            audio_codec,
            "-b:a",
            audio_bitrate,
            "-movflags",
            "+faststart",
            "-shortest",
            str(output_path),
        ]
    )

    if video_codec == "libx264":
        # libx264 otherwise derives a separate look-ahead worker even when
        # FFmpeg's generic thread cap is set.
        insert_at = command.index("-c:a")
        command[insert_at:insert_at] = [
            "-x264-params",
            f"threads={thread_cap}:lookahead-threads=1",
        ]

    print(f"Timeline: {timeline_path}")
    print(f"Beats: {len(beats)}")
    print(f"Resolution: {width}x{height} @ {fps}fps")
    print(f"Duration target: {duration:.3f}s")
    nice_level = max(0, min(19, int(args.nice)))
    launcher: list[str] = ionice_prefix()
    if nice_level:
        launcher = [*launcher, "nice", "-n", str(nice_level)]
    command = [*launcher, *command] if launcher else command

    print(f"Subtitles: {'on' if subtitles_enabled else 'off'}")
    print(
        f"Resource caps: encoder={thread_cap}, filter={filter_threads}, "
        f"complex={filter_complex_threads} (from {thread_source})"
    )
    print(f"Scheduling: nice={nice_level}, io={'idle-ish' if ionice_prefix() else 'default'}")
    print(f"Supersample: {motion_supersample}")
    print(f"Output: {output_path}")

    if args.dry_run:
        print()
        print("FFmpeg command:")
        print(shlex.join(command))
        return

    started = time.perf_counter()
    subprocess.run(command, check=True)
    elapsed = time.perf_counter() - started

    probe = probe_video(ffprobe, output_path)
    actual_duration = float((probe.get("format") or {}).get("duration") or 0.0)
    drift = actual_duration - duration

    stats = {
        "schema_version": 1,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "output": str(output_path),
        "output_bytes": output_path.stat().st_size if output_path.exists() else 0,
        "target_duration_seconds": round(duration, 3),
        "actual_duration_seconds": round(actual_duration, 3),
        "duration_drift_seconds": round(drift, 3),
        "wall_seconds": round(elapsed, 3),
        "realtime_factor": round(elapsed / duration, 3) if duration else None,
        "beats": len(beats),
        "resolution": f"{width}x{height}",
        "fps": fps,
        "subtitles": subtitles_enabled,
        "resource_budget": round(float(args.resource_budget), 3),
        "cpus_available": cpu_count(),
        "threads": {
            "encoder": thread_cap,
            "filter": filter_threads,
            "filter_complex": filter_complex_threads,
            "source": thread_source,
        },
        "nice": nice_level,
        "ionice": bool(ionice_prefix()),
        "supersample": motion_supersample,
        "supersample_note": supersample_note,
        "peak_child_rss_mb": child_peak_rss_mb(),
    }
    stats_path = video_dir / "render" / "RENDER_STATS.json"
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print()
    print("Render complete.")
    print(f"Actual duration: {actual_duration:.3f}s")
    print(f"Duration drift: {drift:+.3f}s")
    print(f"Wall time: {elapsed:.1f}s ({stats['realtime_factor']}x realtime)")
    print(f"Peak child RSS: {stats['peak_child_rss_mb']} MB")
    print(f"Stats: {stats_path}")
    print(f"File: {output_path}")

    if abs(drift) > 0.10:
        print("WARNING: render duration drift exceeds 100ms; inspect before final export.")


if __name__ == "__main__":
    main()
