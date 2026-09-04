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
import re
import subprocess
import textwrap
from pathlib import Path
from typing import Any


#: How far the rendered opening may sit from the measured narration boundary (§67 step 8).
OPENING_ALIGNMENT_TOLERANCE = 0.05


def ffprobe_seconds(path: Path) -> float:
    """Real duration of a media file. A missing probe is a hard error, never a guess."""
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


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return data


def find_beat_image(
    video_dir: Path,
    beat_id: int,
    *,
    allow_missing: bool = False,
) -> Path:
    raw_dir = video_dir / "assets" / "raw_beats"
    stems = (f"beat_{beat_id:02d}", f"beat_{beat_id:03d}")
    extensions = (".png", ".jpg", ".jpeg", ".webp")

    for stem in stems:
        for ext in extensions:
            candidate = raw_dir / f"{stem}{ext}"
            if candidate.exists():
                return candidate

    if allow_missing:
        return raw_dir / f"beat_{beat_id:02d}.png"

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
    start_at: float = 0.0,
) -> tuple[list[float], list[dict[str, Any]]]:
    """Create one continuous, non-overlapping image timeline.

    Pauses belong to the current beat. If STT word timestamps overlap across a
    beat boundary, use the midpoint of the overlap instead of cutting one phrase
    completely early or late.

    ``start_at`` is where the image section begins on the narration timeline. For a
    mixed-media episode that is the measured end of the book transition, so the body
    images keep their real spoken positions instead of being rescaled into a window.
    """

    if not beats:
        raise ValueError("Timing file contains no beats.")

    boundaries = [round(float(start_at), 3)]
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


def caption_token(value: str) -> str:
    """The comparable form of a word: letters and digits only, lowercased."""
    return re.sub(r"[^a-z0-9']+", "", str(value).lower())


def load_word_timings(video_dir: Path) -> list[dict[str, Any]]:
    """Measured per-word timings, or ``[]`` when the aligner did not write any."""
    path = Path(video_dir) / "timing" / "WORD_TIMINGS.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    words = payload.get("words") or []
    return [
        {
            "token": caption_token(word.get("token") or word.get("text") or ""),
            "start": float(word.get("start") or 0.0),
            "end": float(word.get("end") or 0.0),
        }
        for word in words
        if caption_token(word.get("token") or word.get("text") or "")
    ]


def _match_chunk_words(
    chunk: list[str],
    words: list[dict[str, Any]],
    cursor: int,
    *,
    lookahead: int = 12,
) -> tuple[tuple[float, float] | None, int]:
    """Find the spoken span of ``chunk`` starting near ``cursor`` in ``words``.

    Returns the measured ``(start, end)`` and the new cursor. A chunk whose words cannot be
    located returns ``None`` so the caller can fall back for that chunk alone rather than
    abandoning real timings for the whole beat.
    """
    tokens = [caption_token(word) for word in chunk]
    tokens = [token for token in tokens if token]
    if not tokens:
        return None, cursor
    for offset in range(0, lookahead + 1):
        begin = cursor + offset
        if begin >= len(words):
            break
        matched: list[dict[str, Any]] = []
        index = begin
        for token in tokens:
            # Tolerate a word the transcriber dropped: skip at most one observed word
            # per expected token before giving up on this alignment.
            found = None
            for probe in range(index, min(index + 2, len(words))):
                if words[probe]["token"] == token:
                    found = probe
                    break
            if found is None:
                matched = []
                break
            matched.append(words[found])
            index = found + 1
        if matched:
            return (matched[0]["start"], matched[-1]["end"]), index
    return None, cursor


def build_subtitle_cues(
    beats: list[dict[str, Any]],
    subtitle_cfg: dict[str, Any],
    word_timings: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    max_words = int(subtitle_cfg.get("max_words_per_cue", 6))
    max_chars = int(subtitle_cfg.get("max_chars_per_line", 34))
    max_lines = int(subtitle_cfg.get("max_lines", 2))
    words = list(word_timings or [])
    word_cursor = 0

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
            measured = None
            if words:
                measured, word_cursor = _match_chunk_words(chunk, words, word_cursor)

            if measured is not None:
                cue_start, cue_end = measured
                timing_source = "word"
            else:
                cue_start = cursor
                cue_end = (
                    speech_end
                    if index == len(chunks) - 1
                    else cursor + speech_duration * (weight / total_weight)
                )
                timing_source = "proportional"

            plain = " ".join(chunk)
            cues.append(
                {
                    "beat_id": int(beat["beat_id"]),
                    "start": round(cue_start, 3),
                    "end": round(cue_end, 3),
                    "text": plain,
                    "ass_text": wrap_caption(plain, max_chars, max_lines),
                    "timing_source": timing_source,
                }
            )
            cursor = cue_end

    return cues


def normalize_subtitle_cue_boundaries(
    cues: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Ensure subtitle cues never overlap on screen.

    STT providers can return slightly overlapping word ranges around semantic
    boundaries. Preserve both cues but split the overlap at its midpoint.
    """

    if not cues:
        return cues, []

    normalized = [dict(cue) for cue in cues]
    adjustments: list[dict[str, Any]] = []

    for index in range(1, len(normalized)):
        previous = normalized[index - 1]
        current = normalized[index]

        previous_end = float(previous["end"])
        current_start = float(current["start"])

        if current_start >= previous_end:
            continue

        boundary = (previous_end + current_start) / 2.0
        previous["end"] = round(boundary, 3)
        current["start"] = round(boundary, 3)

        adjustments.append(
            {
                "previous_beat": int(previous["beat_id"]),
                "current_beat": int(current["beat_id"]),
                "previous_end": round(previous_end, 3),
                "current_start": round(current_start, 3),
                "overlap_seconds": round(previous_end - current_start, 3),
                "chosen_boundary": round(boundary, 3),
            }
        )

    return normalized, adjustments


def ass_timestamp(seconds: float) -> str:
    centiseconds = max(0, round(seconds * 100))
    hours, rem = divmod(centiseconds, 360000)
    minutes, rem = divmod(rem, 6000)
    secs, cs = divmod(rem, 100)
    return f"{hours:d}:{minutes:02d}:{secs:02d}.{cs:02d}"


def escape_ass_text(value: str) -> str:
    return value.replace("{", r"\{").replace("}", r"\}")


#: Share of the frame height the platform UI covers at the bottom of a vertical short.
#: Captions inside that band get hidden behind the progress bar and the action buttons.
PORTRAIT_BOTTOM_SAFE_FRACTION = 0.12
LANDSCAPE_BOTTOM_SAFE_FRACTION = 0.08


def subtitle_margin_v(subtitle_cfg: dict[str, Any], height: int) -> int:
    """Bottom margin in pixels, respecting an explicit value and the safe area otherwise.

    The old fixed 90px sat inside the Shorts UI band on a 1920-tall frame, which put the
    last line of every caption behind the seek bar.
    """
    configured = subtitle_cfg.get("margin_v")
    if configured is not None:
        return max(0, int(configured))
    fraction = (
        PORTRAIT_BOTTOM_SAFE_FRACTION if height >= 1.2 * 1080 else LANDSCAPE_BOTTOM_SAFE_FRACTION
    )
    return max(48, round(height * fraction))


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
    margin_v = subtitle_margin_v(subtitle_cfg, height)
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


def detect_mixed_media(video_dir: Path) -> bool:
    """Detect Question Harvest mixed-media mode: presence of trimmed opening clips."""
    # QH stores trimmed clips as question_spark_trimmed.mp4 / book_transition_trimmed.mp4
    # Legacy stores only raw_beats
    for cand in [
        video_dir / "assets" / "opening" / "question_spark_trimmed.mp4",
        video_dir / "assets" / "opening" / "book_transition_trimmed.mp4",
        video_dir / "references" / "world_keyframe.png",
    ]:
        if cand.is_file():
            return True
    # also check PROJECT.md content project
    try:
        pm = (video_dir / "PROJECT.md").read_text(encoding="utf-8")
        if "question_harvest" in pm:
            return True
    except Exception:
        pass
    return False


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
    parser.add_argument(
        "--mixed-media",
        action="store_true",
        help="Force mixed-media mode (video+image). Auto-detected for question_harvest.",
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

    is_mixed = args.mixed_media or detect_mixed_media(video_dir)

    # For mixed-media (Question Harvest) the two Flow clips are real video beats whose
    # boundaries were measured from the narration, not estimated (§67).
    opening_timing: dict[str, Any] = {}
    if is_mixed:
        opening_path = video_dir / "timing" / "OPENING_TIMING.json"
        if not opening_path.is_file():
            raise FileNotFoundError(
                f"{opening_path} is missing. A mixed-media timeline needs the measured "
                "opening boundaries; run align_beats.py first."
            )
        opening_timing = load_json(opening_path)

    video_entries: list[dict[str, Any]] = []
    video_total = 0.0
    if is_mixed:
        # Only the trimmed clips are render sources (§67-70). The untrimmed source is one
        # second longer by design, so substituting it would desynchronise the whole episode.
        opening_a = video_dir / "assets" / "opening" / "question_spark_trimmed.mp4"
        opening_b = video_dir / "assets" / "opening" / "book_transition_trimmed.mp4"
        for idx, (path, name) in enumerate([(opening_a, "opening_a"), (opening_b, "opening_b")]):
            if not path.is_file():
                if args.skip_asset_validation:
                    print(f"WARN mixed-media: missing {path}, skipped", flush=True)
                    continue
                raise FileNotFoundError(
                    f"{path} is missing. Run trim_opening_clips.py — the untrimmed source runs "
                    "one second long on purpose and must not be rendered."
                )
            if True:
                dur = ffprobe_seconds(path)
                video_entries.append({
                    "media_type": "video",
                    "source": relative_to_video(path, video_dir),
                    "start": round(video_total, 3),
                    "end": round(video_total + dur, 3),
                    "duration": round(dur, 3),
                    "beat_id": f"video_{name}",
                    "motion": "still",  # video has its own motion
                })
                video_total += dur

    body_start = float(opening_timing.get("transition_end") or 0.0) if is_mixed else 0.0
    boundaries, adjustments = compute_display_boundaries(beats, audio_duration, start_at=body_start)

    motion_cfg = profile.get("motion") if isinstance(profile.get("motion"), dict) else {}
    motion_cycle = motion_cfg.get("cycle") or ["zoom_in"]
    if not isinstance(motion_cycle, list) or not motion_cycle:
        motion_cycle = ["zoom_in"]

    timeline_beats: list[dict[str, Any]] = []

    # Add video entries first (mixed-media: Clip A, Clip B before body images)
    if is_mixed and video_entries:
        # The narration is one continuous track, so a body beat's STT timings are already its
        # real position in the finished video. Rescaling them into the "remaining" window —
        # which is what this used to do — moved every image off its own sentence. The images
        # therefore keep their measured boundaries, and the only thing checked is that the two
        # clips really end where the narration says the book transition ends (§67 step 8).
        drift = abs(video_total - body_start)
        if drift > OPENING_ALIGNMENT_TOLERANCE:
            raise ValueError(
                f"The opening clips total {video_total:.3f}s but the narration puts the end of "
                f"the book transition at {body_start:.3f}s (drift {drift:+.3f}s > "
                f"{OPENING_ALIGNMENT_TOLERANCE}s). Re-run trim_opening_clips.py: rendering this "
                "would push every body image off its own sentence."
            )
        for index, beat in enumerate(beats):
            beat_id = int(beat["beat_id"])
            image_path = find_beat_image(
                video_dir,
                beat_id,
                allow_missing=args.skip_asset_validation,
            )
            start = max(float(boundaries[index]), video_total)
            end = min(float(boundaries[index + 1]), audio_duration)
            if end <= start:
                continue
            timeline_beats.append(
                {
                    "beat_id": beat_id,
                    "media_type": "image",
                    "image": relative_to_video(image_path, video_dir),
                    "source": relative_to_video(image_path, video_dir),
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
        # Prepend video entries (they already have start/end)
        timeline_beats = video_entries + timeline_beats
    else:
        for index, beat in enumerate(beats):
            beat_id = int(beat["beat_id"])
            image_path = find_beat_image(
                video_dir,
                beat_id,
                allow_missing=args.skip_asset_validation,
            )

            start = float(boundaries[index])
            end = float(boundaries[index + 1])
            if end <= start:
                raise ValueError(f"Non-positive timeline duration for Beat {beat_id}")

            timeline_beats.append(
                {
                    "beat_id": beat_id,
                    "media_type": "image",  # explicit for legacy compat (§69)
                    "image": relative_to_video(image_path, video_dir),
                    "source": relative_to_video(image_path, video_dir),
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
    word_timings = load_word_timings(video_dir)
    cues = build_subtitle_cues(beats, subtitle_cfg, word_timings)
    cues, subtitle_adjustments = normalize_subtitle_cue_boundaries(cues)
    proportional_cues = [
        index for index, cue in enumerate(cues) if cue.get("timing_source") != "word"
    ]

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
            "subtitle_overlap_adjustments": subtitle_adjustments,
            "subtitle_word_timings_available": bool(word_timings),
            "subtitle_cues_from_measured_words": len(cues) - len(proportional_cues),
            "subtitle_cues_estimated": len(proportional_cues),
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
    if subtitle_adjustments:
        print(f"Subtitle overlap repairs: {len(subtitle_adjustments)}")
    else:
        print("Subtitle QC: no overlapping cues.")

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
