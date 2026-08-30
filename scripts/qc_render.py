#!/usr/bin/env python3
"""Validate a rendered video against TIMELINE.json and RENDER_PROFILE.json.

Example:
    python scripts/qc_render.py \
      videos/001_brain_replays_embarrassing_moments \
      --input videos/001_brain_replays_embarrassing_moments/assets/renders/final.mp4 \
      --decode

Creates:
    <video>/render/QC_REPORT.json
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
from fractions import Fraction
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
        raise RuntimeError(f"{name} was not found in PATH.")
    return path


def resolve_video_path(video_dir: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return video_dir / path


def parse_fps(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        return float(Fraction(value))
    except (ValueError, ZeroDivisionError):
        return 0.0


def ffprobe(ffprobe_bin: str, path: Path) -> dict[str, Any]:
    result = subprocess.run(
        [
            ffprobe_bin,
            "-v",
            "error",
            "-show_entries",
            (
                "format=duration,size,bit_rate:"
                "stream=index,codec_type,codec_name,width,height,"
                "r_frame_rate,pix_fmt,sample_rate,channels"
            ),
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    if not isinstance(payload, dict):
        raise RuntimeError("ffprobe returned an invalid payload.")
    return payload


def check(
    name: str,
    ok: bool,
    *,
    expected: Any = None,
    actual: Any = None,
    detail: str = "",
) -> dict[str, Any]:
    return {
        "name": name,
        "ok": bool(ok),
        "expected": expected,
        "actual": actual,
        "detail": detail,
    }


def codec_expectation(encoder: str) -> str:
    mapping = {
        "libx264": "h264",
        "libx265": "hevc",
        "libvpx-vp9": "vp9",
        "libaom-av1": "av1",
    }
    return mapping.get(encoder, encoder)


def decode_check(ffmpeg_bin: str, path: Path) -> tuple[bool, str]:
    result = subprocess.run(
        [
            ffmpeg_bin,
            "-v",
            "error",
            "-i",
            str(path),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    stderr = (result.stderr or "").strip()
    return result.returncode == 0, stderr


def main() -> None:
    parser = argparse.ArgumentParser(description="QC a rendered video.")
    parser.add_argument("video_dir", type=Path)
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="Defaults to <video>/assets/renders/final.mp4, then preview.mp4.",
    )
    parser.add_argument(
        "--decode",
        action="store_true",
        help="Decode the full video/audio streams to catch corrupt frames/packets.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help=(
            "Optional QC report path. By default final.mp4 writes QC_REPORT.json; "
            "other render variants write QC_REPORT_<stem>.json."
        ),
    )
    parser.add_argument(
        "--duration-tolerance",
        type=float,
        default=0.12,
        help="Allowed absolute duration drift in seconds.",
    )
    args = parser.parse_args()

    ffprobe_bin = require_binary("ffprobe")
    ffmpeg_bin = require_binary("ffmpeg") if args.decode else ""

    video_dir = args.video_dir.expanduser().resolve()
    timeline_path = video_dir / "timeline" / "TIMELINE.json"
    timeline = load_json(timeline_path)

    profile_path = resolve_video_path(
        video_dir,
        str(timeline.get("render_profile") or "render/RENDER_PROFILE.json"),
    )
    profile = load_json(profile_path)

    if args.input:
        render_path = args.input.expanduser().resolve()
    else:
        final_path = video_dir / "assets" / "renders" / "final.mp4"
        preview_path = video_dir / "assets" / "renders" / "preview.mp4"
        render_path = final_path if final_path.exists() else preview_path

    if not render_path.exists():
        raise FileNotFoundError(f"Rendered video not found: {render_path}")

    probe = ffprobe(ffprobe_bin, render_path)
    streams = probe.get("streams") if isinstance(probe.get("streams"), list) else []
    video_streams = [
        stream for stream in streams
        if isinstance(stream, dict) and stream.get("codec_type") == "video"
    ]
    audio_streams = [
        stream for stream in streams
        if isinstance(stream, dict) and stream.get("codec_type") == "audio"
    ]

    expected_resolution = timeline.get("resolution") or {}
    expected_width = int(expected_resolution.get("width", 1920))
    expected_height = int(expected_resolution.get("height", 1080))
    expected_fps = float(timeline.get("fps", 30))
    expected_duration = float(timeline["duration"])

    video_cfg = profile.get("video") if isinstance(profile.get("video"), dict) else {}
    audio_cfg = profile.get("audio") if isinstance(profile.get("audio"), dict) else {}

    expected_video_codec = codec_expectation(str(video_cfg.get("codec", "libx264")))
    expected_audio_codec = str(audio_cfg.get("codec", "aac"))
    expected_pix_fmt = str(video_cfg.get("pixel_format", "yuv420p"))

    checks: list[dict[str, Any]] = []

    checks.append(
        check(
            "video_stream_count",
            len(video_streams) == 1,
            expected=1,
            actual=len(video_streams),
        )
    )
    checks.append(
        check(
            "audio_stream_count",
            len(audio_streams) == 1,
            expected=1,
            actual=len(audio_streams),
        )
    )

    primary_video = video_streams[0] if video_streams else {}
    primary_audio = audio_streams[0] if audio_streams else {}

    width = int(primary_video.get("width") or 0)
    height = int(primary_video.get("height") or 0)
    actual_fps = parse_fps(str(primary_video.get("r_frame_rate") or ""))
    actual_duration = float((probe.get("format") or {}).get("duration") or 0.0)
    duration_drift = actual_duration - expected_duration

    checks.extend(
        [
            check(
                "resolution",
                width == expected_width and height == expected_height,
                expected=f"{expected_width}x{expected_height}",
                actual=f"{width}x{height}",
            ),
            check(
                "fps",
                math.isclose(actual_fps, expected_fps, abs_tol=0.01),
                expected=expected_fps,
                actual=round(actual_fps, 6),
            ),
            check(
                "duration",
                abs(duration_drift) <= args.duration_tolerance,
                expected=expected_duration,
                actual=round(actual_duration, 3),
                detail=f"drift={duration_drift:+.3f}s",
            ),
            check(
                "video_codec",
                str(primary_video.get("codec_name") or "") == expected_video_codec,
                expected=expected_video_codec,
                actual=str(primary_video.get("codec_name") or ""),
            ),
            check(
                "pixel_format",
                str(primary_video.get("pix_fmt") or "") == expected_pix_fmt,
                expected=expected_pix_fmt,
                actual=str(primary_video.get("pix_fmt") or ""),
            ),
            check(
                "audio_codec",
                str(primary_audio.get("codec_name") or "") == expected_audio_codec,
                expected=expected_audio_codec,
                actual=str(primary_audio.get("codec_name") or ""),
            ),
            check(
                "file_nonempty",
                int((probe.get("format") or {}).get("size") or 0) > 0,
                expected=">0 bytes",
                actual=int((probe.get("format") or {}).get("size") or 0),
            ),
        ]
    )

    decode_result: dict[str, Any] | None = None
    if args.decode:
        decode_ok, decode_stderr = decode_check(ffmpeg_bin, render_path)
        decode_result = {
            "ok": decode_ok,
            "stderr": decode_stderr,
        }
        checks.append(
            check(
                "full_decode",
                decode_ok,
                expected="no decode errors",
                actual="ok" if decode_ok else "failed",
                detail=decode_stderr[:1200],
            )
        )

    passed = all(item["ok"] for item in checks)

    try:
        render_label = str(render_path.relative_to(video_dir))
    except ValueError:
        render_label = str(render_path)

    report = {
        "schema_version": 1,
        "input": render_label,
        "timeline": "timeline/TIMELINE.json",
        "render_profile": str(profile_path.relative_to(video_dir)),
        "passed": passed,
        "checks": checks,
        "decode": decode_result,
    }

    if args.report:
        report_path = args.report.expanduser().resolve()
    else:
        report_name = (
            "QC_REPORT.json"
            if render_path.name == "final.mp4"
            else f"QC_REPORT_{render_path.stem}.json"
        )
        report_path = video_dir / "render" / report_name

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(f"QC input: {render_path}")
    for item in checks:
        status = "PASS" if item["ok"] else "FAIL"
        detail = f" ({item['detail']})" if item.get("detail") else ""
        print(
            f"[{status}] {item['name']}: "
            f"expected={item['expected']} actual={item['actual']}{detail}"
        )

    print(f"Report: {report_path}")
    print("QC RESULT:", "PASS" if passed else "FAIL")

    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
