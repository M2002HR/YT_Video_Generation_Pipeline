#!/usr/bin/env python3
"""Build a deterministic video timeline from beat timing metadata.

The timeline is the render source of truth. It references local media assets but
contains only text/metadata, so it can be committed to Git.

Example:
    python scripts/build_timeline.py \
      videos/001_brain_replays_embarrassing_moments
"""

from __future__ import annotations

import argparse
import json
import textwrap
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return data


def find_beat_image(video_dir: Path, beat_id: int) -> Path:
    raw_dir = video_dir / "assets" / "raw_beats"
    stems = (f"beat_{beat_id:02d}", f"beat_{beat_id:03d}")
    extensions = (".png", ".jpg", ".jpeg", ".webp")

    for stem in stems:
        for ext in extensions:
            candidate = raw_dir / f"{stem}{ext}"
            if candidate.exists():
                return candidate

    expected = ", ".join(str(raw_dir / f"{stem}.png") for stem in stems)
    raise FileNotFoundError(f"Missing image for Beat {beat_id}: expected {expected}")


def relative_to_video(path: Path, video_dir: Path) -> str:
    try:
        return str(path.resolve().relative_to(video_dir.resolve()))
    except ValueError:
        return str(path.resolve())


def compute_display_boundaries(
    beats: list[dict[str, Any]],
    audio_duration: float,
) -> tuple[list[float], list[dict[str, Any]]]:
    """Create one continuous, non-overlapping image timeline.

    Pauses belong to the current beat. If STT word timestamps overlap across a
    beat boundary, use the midpoint of the overlap instead of cutting one phrase
    completely early or late.
    """

    if not beats:
        raise ValueError("Timing file contains no beats.")

    boundaries = [0.0]
    adjustments: list[dict[str, Any]] = []

    for index in range(len(beats) - 1):
        current = beats[index]
        following = beats[index + 1]

        current_end = float(current["speech_end"])
        next_start = float(following["speech_start"])

        if next_start >= current_end:
            boundary = next_start
            reason = "next_speech_start"
        else:
            boundary = (current_end + next_start) / 2.0
            reason = "overlap_midpoint"
            adjustments.append(
                {
                    "after_beat": int(current["beat_id"]),
                    "before_beat": int(following["beat_id"]),
                    "current_speech_end": round(current_end, 3),
                    "next_speech_start": round(next_start, 3),
                    "overlap_seconds": round(current_end - next_start, 3),
                    "chosen_boundary": round(boundary, 3),
                }
            )

        boundary = max(boundaries[-1], min(boundary, audio_duration))
        boundaries.append(round(boundary, 3))

    boundaries.append(round(audio_duration, 3))
    return boundaries, adjustments


def split_caption_chunks(
    text: str,
    *,
    max_words: int,
    max_chars_per_line: int,
    max_lines: int,
) -> list[list[str]]:
    words = text.split()
    if not words:
        return []

    max_chars = max(1, max_chars_per_line * max_lines)
    chunks: list[list[str]] = []
    current: list[str] = []

    for word in words:
        candidate = current + [word]
        candidate_text = " ".join(candidate)

        if current and (
            len(candidate) > max_words
            or len(candidate_text) > max_chars
        ):
            chunks.append(current)
            current = [word]
        else:
            current = candidate

    if current:
        chunks.append(current)

    return chunks


def wrap_caption(text: str, max_chars_per_line: int, max_lines: int) -> str:
    lines = textwrap.wrap(
        text,
        width=max_chars_per_line,
        break_long_words=False,
        break_on_hyphens=False,
    )

    if not lines:
        return ""

    if len(lines) > max_lines:
        kept = lines[: max_lines - 1]
        kept.append(" ".join(lines[max_lines - 1 :]))
        lines = kept

    return r"\N".join(lines)


def build_subtitle_cues(
    beats: list[dict[str, Any]],
    subtitle_cfg: dict[str, Any],
) -> list[dict[str, Any]]:
    max_words = int(subtitle_cfg.get("max_words_per_cue", 6))
    max_chars = int(subtitle_cfg.get("max_chars_per_line", 34))
    max_lines = int(subtitle_cfg.get("max_lines", 2))

    cues: list[dict[str, Any]] = []

    for beat in beats:
        speech_start = float(beat["speech_start"])
        speech_end = float(beat["speech_end"])
        narration = str(beat["narration"]).strip()

        chunks = split_caption_chunks(
            narration,
            max_words=max_words,
            max_chars_per_line=max_chars,
            max_lines=max_lines,
        )
        if not chunks:
            continue

        weights = [len(chunk) for chunk in chunks]
        total_weight = max(1, sum(weights))
        speech_duration = max(0.001, speech_end - speech_start)

        cursor = speech_start
        for index, (chunk, weight) in enumerate(zip(chunks, weights)):
            if index == len(chunks) - 1:
                cue_end = speech_end
            else:
                cue_end = cursor + speech_duration * (weight / total_weight)

            plain = " ".join(chunk)
            cues.append(
                {
                    "beat_id": int(beat["beat_id"]),
                    "start": round(cursor, 3),
                    "end": round(cue_end, 3),
                    "text": plain,
                    "ass_text": wrap_caption(plain, max_chars, max_lines),
                }
            )
            cursor = cue_end

    return cues


def ass_timestamp(seconds: float) -> str:
    centiseconds = max(0, round(seconds * 100))
    hours, rem = divmod(centiseconds, 360000)
    minutes, rem = divmod(rem, 6000)
    secs, cs = divmod(rem, 100)
    return f"{hours:d}:{minutes:02d}:{secs:02d}.{cs:02d}"


def escape_ass_text(value: str) -> str:
    return value.replace("{", r"\{").replace("}", r"\}")


def write_ass(
    path: Path,
    *,
    width: int,
    height: int,
    subtitle_cfg: dict[str, Any],
    cues: list[dict[str, Any]],
) -> None:
    font_name = str(subtitle_cfg.get("font_name", "DejaVu Sans"))
    font_size = int(subtitle_cfg.get("font_size", 56))
    bold = -1 if bool(subtitle_cfg.get("bold", True)) else 0
    margin_v = int(subtitle_cfg.get("margin_v", 90))
    outline = float(subtitle_cfg.get("outline", 3))
    shadow = float(subtitle_cfg.get("shadow", 0))

    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "ScaledBorderAndShadow: yes",
        "WrapStyle: 2",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Default,"
        f"{font_name},{font_size},"
        "&H00FFFFFF,&H000000FF,&H00000000,&H80000000,"
        f"{bold},0,0,0,100,100,0,0,1,{outline},{shadow},2,60,60,{margin_v},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    for cue in cues:
        text = escape_ass_text(str(cue["ass_text"]))
        lines.append(
            "Dialogue: 0,"
            f"{ass_timestamp(float(cue['start']))},"
            f"{ass_timestamp(float(cue['end']))},"
            f"Default,,0,0,0,,{text}"
        )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build render timeline from beat timings.")
    parser.add_argument("video_dir", type=Path)
    parser.add_argument(
        "--timing",
        type=Path,
        default=None,
        help="Optional timing JSON. Defaults to <video>/timing/BEAT_TIMINGS.json",
    )
    parser.add_argument(
        "--profile",
        type=Path,
        default=None,
        help="Optional render profile. Defaults to <video>/render/RENDER_PROFILE.json",
    )
    parser.add_argument(
        "--skip-asset-validation",
        action="store_true",
        help="Allow timeline metadata generation without local image/audio files.",
    )
    args = parser.parse_args()

    video_dir = args.video_dir.expanduser().resolve()
    timing_path = (
        args.timing.expanduser().resolve()
        if args.timing
        else video_dir / "timing" / "BEAT_TIMINGS.json"
    )
    profile_path = (
        args.profile.expanduser().resolve()
        if args.profile
        else video_dir / "render" / "RENDER_PROFILE.json"
    )

    timing = load_json(timing_path)
    profile = load_json(profile_path)

    raw_beats = timing.get("beats")
    if not isinstance(raw_beats, list) or not raw_beats:
        raise ValueError("BEAT_TIMINGS.json has no beats.")

    beats = [dict(item) for item in raw_beats if isinstance(item, dict)]
    ids = [int(item["beat_id"]) for item in beats]
    expected_ids = list(range(1, len(beats) + 1))
    if ids != expected_ids:
        raise ValueError(f"Beat IDs must be contiguous. Found: {ids}")

    audio_duration = float(timing["audio_duration_seconds"])
    audio_value = str(timing["audio"])
    audio_path = Path(audio_value)
    if not audio_path.is_absolute():
        audio_path = video_dir / audio_path

    if not args.skip_asset_validation and not audio_path.exists():
        raise FileNotFoundError(f"Narration audio not found: {audio_path}")

    boundaries, adjustments = compute_display_boundaries(beats, audio_duration)

    motion_cfg = profile.get("motion") if isinstance(profile.get("motion"), dict) else {}
    motion_cycle = motion_cfg.get("cycle") or ["zoom_in"]
    if not isinstance(motion_cycle, list) or not motion_cycle:
        motion_cycle = ["zoom_in"]

    timeline_beats: list[dict[str, Any]] = []

    for index, beat in enumerate(beats):
        beat_id = int(beat["beat_id"])
        image_path = find_beat_image(video_dir, beat_id)

        if args.skip_asset_validation and not image_path.exists():
            image_path = (
                video_dir / "assets" / "raw_beats" / f"beat_{beat_id:02d}.png"
            )

        start = float(boundaries[index])
        end = float(boundaries[index + 1])
        if end <= start:
            raise ValueError(f"Non-positive timeline duration for Beat {beat_id}")

        timeline_beats.append(
            {
                "beat_id": beat_id,
                "image": relative_to_video(image_path, video_dir),
                "start": round(start, 3),
                "end": round(end, 3),
                "duration": round(end - start, 3),
                "speech_start": round(float(beat["speech_start"]), 3),
                "speech_end": round(float(beat["speech_end"]), 3),
                "match_confidence": float(beat.get("match_confidence", 0.0)),
                "motion": str(motion_cycle[index % len(motion_cycle)]),
                "narration": str(beat["narration"]),
            }
        )

    subtitle_cfg = (
        profile.get("subtitles")
        if isinstance(profile.get("subtitles"), dict)
        else {}
    )
    cues = build_subtitle_cues(beats, subtitle_cfg)

    resolution = profile.get("resolution") or {}
    width = int(resolution.get("width", 1920))
    height = int(resolution.get("height", 1080))
    fps = int(profile.get("fps", 30))

    timeline_dir = video_dir / "timeline"
    timeline_dir.mkdir(parents=True, exist_ok=True)

    timeline_json = timeline_dir / "TIMELINE.json"
    subtitle_ass = timeline_dir / "SUBTITLES.ass"

    payload = {
        "schema_version": 1,
        "source_timing": relative_to_video(timing_path, video_dir),
        "render_profile": relative_to_video(profile_path, video_dir),
        "audio": relative_to_video(audio_path, video_dir),
        "duration": round(audio_duration, 3),
        "resolution": {"width": width, "height": height},
        "fps": fps,
        "beats": timeline_beats,
        "subtitles": cues,
        "qc": {
            "beat_count": len(timeline_beats),
            "low_confidence_beats": [
                int(beat["beat_id"])
                for beat in beats
                if float(beat.get("match_confidence", 0.0)) < 0.75
            ],
            "timestamp_overlap_adjustments": adjustments,
        },
    }

    timeline_json.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    if bool(subtitle_cfg.get("enabled", True)):
        write_ass(
            subtitle_ass,
            width=width,
            height=height,
            subtitle_cfg=subtitle_cfg,
            cues=cues,
        )

    print(f"Created: {timeline_json}")
    if bool(subtitle_cfg.get("enabled", True)):
        print(f"Created: {subtitle_ass}")
    print(f"Beats: {len(timeline_beats)}")
    print(f"Duration: {audio_duration:.3f}s")
    print(f"Subtitle cues: {len(cues)}")

    if adjustments:
        print("Adjusted overlapping STT boundaries:")
        for item in adjustments:
            print(
                "  "
                f"Beat {item['after_beat']} -> {item['before_beat']}: "
                f"{item['overlap_seconds']:.3f}s overlap, "
                f"boundary={item['chosen_boundary']:.3f}s"
            )
    else:
        print("Timeline QC: no overlapping STT boundaries.")


if __name__ == "__main__":
    main()
