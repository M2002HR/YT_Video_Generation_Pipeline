#!/usr/bin/env python3
"""Render a video from TIMELINE.json using FFmpeg.

The first render intentionally stays simple and deterministic:
- one image per beat
- subtle Ken Burns style motion
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
) -> str:
    frames = max(2, int(math.ceil(duration * fps)))
    progress = f"min(on/{frames - 1},1)"
    strength = max(0.0, min(float(strength), 0.15))

    if motion == "zoom_out":
        z = f"1+{strength:.6f}*(1-{progress})"
        x = "iw/2-(iw/zoom/2)"
        y = "ih/2-(ih/zoom/2)"
    elif motion == "pan_right":
        z = f"1+{strength:.6f}"
        x = f"(iw-iw/zoom)*{progress}"
        y = "ih/2-(ih/zoom/2)"
    elif motion == "pan_left":
        z = f"1+{strength:.6f}"
        x = f"(iw-iw/zoom)*(1-{progress})"
        y = "ih/2-(ih/zoom/2)"
    elif motion == "pan_down":
        z = f"1+{strength:.6f}"
        x = "iw/2-(iw/zoom/2)"
        y = f"(ih-ih/zoom)*{progress}"
    elif motion == "pan_up":
        z = f"1+{strength:.6f}"
        x = "iw/2-(iw/zoom/2)"
        y = f"(ih-ih/zoom)*(1-{progress})"
    else:
        z = f"1+{strength:.6f}*{progress}"
        x = "iw/2-(iw/zoom/2)"
        y = "ih/2-(ih/zoom/2)"

    return (
        f"[{input_index}:v]"
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},"
        "setsar=1,"
        f"zoompan="
        f"z='{z}':"
        f"x='{x}':"
        f"y='{y}':"
        f"d=1:s={width}x{height}:fps={fps},"
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

    image_paths: list[Path] = []
    for beat in beats:
        image_path = resolve_video_path(video_dir, str(beat["image"]))
        if not image_path.exists():
            raise FileNotFoundError(
                f"Beat {beat['beat_id']} image not found: {image_path}"
            )
        image_paths.append(image_path)

    output_path = (
        args.output.expanduser().resolve()
        if args.output
        else video_dir / "assets" / "renders" / "preview.mp4"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    motion_cfg = profile.get("motion") if isinstance(profile.get("motion"), dict) else {}
    motion_enabled = bool(motion_cfg.get("enabled", True))
    motion_strength = float(motion_cfg.get("strength", 0.045))

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

    command: list[str] = [ffmpeg, "-hide_banner", "-y"]

    for beat, image_path in zip(beats, image_paths):
        beat_duration = float(beat["duration"])
        command.extend(
            [
                "-loop",
                "1",
                "-framerate",
                str(fps),
                "-t",
                f"{beat_duration:.6f}",
                "-i",
                str(image_path),
            ]
        )

    audio_input_index = len(image_paths)
    command.extend(["-i", str(audio_path)])

    filter_parts: list[str] = []
    labels: list[str] = []

    for index, beat in enumerate(beats):
        label = f"v{index}"
        labels.append(f"[{label}]")

        motion = str(beat.get("motion") or "zoom_in") if motion_enabled else "still"
        strength = motion_strength if motion_enabled else 0.0

        filter_parts.append(
            motion_filter(
                input_index=index,
                label=label,
                width=width,
                height=height,
                fps=fps,
                duration=float(beat["duration"]),
                motion=motion,
                strength=strength,
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

    print(f"Timeline: {timeline_path}")
    print(f"Beats: {len(beats)}")
    print(f"Resolution: {width}x{height} @ {fps}fps")
    print(f"Duration target: {duration:.3f}s")
    print(f"Subtitles: {'on' if subtitles_enabled else 'off'}")
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
