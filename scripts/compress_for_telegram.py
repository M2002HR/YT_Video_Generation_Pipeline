#!/usr/bin/env python3
"""Create a small, Telegram-friendly delivery copy of a passing final render."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path


def require_binary(name: str) -> str:
    binary = shutil.which(name)
    if not binary:
        raise RuntimeError(f"{name} was not found in PATH.")
    return binary


def probe(ffprobe: str, path: Path) -> dict:
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration,size:stream=codec_type,width,height", "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    )
    return json.loads(result.stdout)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compress a polished render for lightweight Telegram delivery.")
    parser.add_argument("video_dir", type=Path)
    parser.add_argument("--input", type=Path, default=None, help="Defaults to assets/renders/polished.mp4.")
    parser.add_argument("--output", type=Path, default=None, help="Defaults to assets/renders/telegram_low.mp4.")
    args = parser.parse_args()
    video_dir = args.video_dir.expanduser().resolve()
    source = args.input.expanduser().resolve() if args.input else video_dir / "assets" / "renders" / "polished.mp4"
    target = args.output.expanduser().resolve() if args.output else video_dir / "assets" / "renders" / "telegram_low.mp4"
    if not source.is_file() or source.stat().st_size == 0:
        raise FileNotFoundError(f"Compression input is missing or empty: {source}")
    ffmpeg, ffprobe = require_binary("ffmpeg"), require_binary("ffprobe")
    source_info = probe(ffprobe, source)
    source_duration = float((source_info.get("format") or {}).get("duration") or 0)
    if source_duration <= 0:
        raise RuntimeError("Compression input has no usable duration.")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp.mp4")
    temporary.unlink(missing_ok=True)
    # 480px on the short side is deliberately compact while preserving text and the
    # original aspect ratio. H.264/AAC maximizes Telegram client compatibility.
    command = [
        ffmpeg, "-y", "-v", "error", "-i", str(source),
        "-map", "0:v:0", "-map", "0:a:0?", "-vf", r"scale=trunc(iw*min(1\,480/min(iw\,ih))/2)*2:trunc(ih*min(1\,480/min(iw\,ih))/2)*2",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "30", "-maxrate", "700k", "-bufsize", "1400k",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-c:a", "aac", "-b:a", "64k", "-ac", "2",
        str(temporary),
    ]
    try:
        subprocess.run(command, check=True)
        info = probe(ffprobe, temporary)
        streams = info.get("streams") or []
        video = next((item for item in streams if item.get("codec_type") == "video"), None)
        duration = float((info.get("format") or {}).get("duration") or 0)
        if not video or int(video.get("width") or 0) <= 0 or int(video.get("height") or 0) <= 0:
            raise RuntimeError("Compressed file has no usable video stream.")
        if abs(duration - source_duration) > 0.25:
            raise RuntimeError(f"Compressed duration drift is too large: {duration - source_duration:+.3f}s")
        if temporary.stat().st_size >= source.stat().st_size:
            raise RuntimeError("Compressed file is not smaller than the source.")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    print(json.dumps({"status": "PASS", "input": str(source), "output": str(target), "input_bytes": source.stat().st_size, "output_bytes": target.stat().st_size, "reduction_percent": round(100 * (1 - target.stat().st_size / source.stat().st_size), 2)}, indent=2))


if __name__ == "__main__":
    main()
