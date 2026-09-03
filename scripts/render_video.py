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
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any


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
    motion_supersample = int(motion_cfg.get("supersample", 2))

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
    configured_threads = int(resource_cfg.get("ffmpeg_threads", 1))
    thread_cap = max(1, args.threads if args.threads is not None else configured_threads)
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
    print(f"Subtitles: {'on' if subtitles_enabled else 'off'}")
    print(f"Resource caps: encoder={thread_cap}, filter={filter_threads}, complex={filter_complex_threads}")
    print(f"Output: {output_path}")

    if args.dry_run:
        print()
        print("FFmpeg command:")
        print(shlex.join(command))
        return

    subprocess.run(command, check=True)

    probe = probe_video(ffprobe, output_path)
    actual_duration = float((probe.get("format") or {}).get("duration") or 0.0)
    drift = actual_duration - duration

    print()
    print("Render complete.")
    print(f"Actual duration: {actual_duration:.3f}s")
    print(f"Duration drift: {drift:+.3f}s")
    print(f"File: {output_path}")

    if abs(drift) > 0.10:
        print("WARNING: render duration drift exceeds 100ms; inspect before final export.")


if __name__ == "__main__":
    main()
