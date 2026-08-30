#!/usr/bin/env python3
"""Align a full narration track to visual beats using local Whisper word timestamps.

Example:
    python scripts/align_beats.py \
      videos/001_brain_replays_embarrassing_moments

Outputs:
    <video>/timing/BEAT_TIMINGS.json
    <video>/timing/BEAT_TIMINGS.md

The script intentionally does not modify image or audio assets.
"""

from __future__ import annotations

import argparse
import difflib
import json
import mimetypes
import os
import re
import shutil
import subprocess
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_FILE = REPO_ROOT / ".env"


BEAT_RE = re.compile(
    r"^### Beat\s+(\d+)\s*$"
    r".*?^Narration:\s*$\n"
    r"(.*?)"
    r"(?=\n\n^Visual:\s*$)",
    re.MULTILINE | re.DOTALL,
)


@dataclass
class WordStamp:
    text: str
    token: str
    start: float
    end: float


def normalize_token(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = value.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    value = value.lower()
    value = re.sub(r"[^a-z0-9']+", "", value)
    value = value.strip("'")
    return value


def tokenize_expected(text: str) -> list[str]:
    tokens: list[str] = []
    for raw in re.findall(r"[A-Za-z0-9]+(?:['’][A-Za-z0-9]+)?", text):
        token = normalize_token(raw)
        if token:
            tokens.append(token)
    return tokens


def parse_beats(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    beats = []
    for match in BEAT_RE.finditer(text):
        beat_id = int(match.group(1))
        narration = " ".join(match.group(2).strip().split())
        beats.append(
            {
                "beat_id": beat_id,
                "narration": narration,
                "tokens": tokenize_expected(narration),
            }
        )

    if not beats:
        raise ValueError(f"No beats could be parsed from {path}")

    ids = [b["beat_id"] for b in beats]
    expected_ids = list(range(1, max(ids) + 1))
    if ids != expected_ids:
        raise ValueError(f"Beat IDs must be sequential. Found: {ids}")

    return beats


def find_audio(video_dir: Path, explicit: Path | None) -> Path:
    if explicit:
        audio = explicit.expanduser().resolve()
        if not audio.exists():
            raise FileNotFoundError(f"Audio file not found: {audio}")
        return audio

    audio_dir = video_dir / "assets" / "audio"
    for name in ("narration.wav", "narration.mp3", "narration.m4a", "narration.flac"):
        candidate = audio_dir / name
        if candidate.exists():
            return candidate

    raise FileNotFoundError(
        "No narration audio found. Expected one of: "
        "assets/audio/narration.wav, narration.mp3, narration.m4a, narration.flac"
    )


def ffprobe_duration(audio: Path) -> float | None:
    if not shutil.which("ffprobe"):
        return None

    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(audio),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return float(result.stdout.strip())
    except Exception:
        return None


def load_root_env() -> None:
    env_file = Path(os.getenv("YT_ENV_FILE", str(DEFAULT_ENV_FILE))).expanduser()
    if env_file.exists():
        load_dotenv(env_file, override=False)


def env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return float(raw)


def _coerce_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _word_stamps_from_raw_words(rows: Any) -> list[WordStamp]:
    if not isinstance(rows, list):
        return []

    words: list[WordStamp] = []
    for row in rows:
        if not isinstance(row, dict):
            continue

        text = str(row.get("word") or row.get("text") or "").strip()
        token = normalize_token(text)
        start = _coerce_float(row.get("start"))
        end = _coerce_float(row.get("end"))

        if not token or start is None or end is None or end < start:
            continue

        words.append(WordStamp(text=text, token=token, start=start, end=end))

    return words


def _word_stamps_from_segments(rows: Any) -> list[WordStamp]:
    """Fallback for providers that return only segment timestamps."""

    if not isinstance(rows, list):
        return []

    words: list[WordStamp] = []
    for row in rows:
        if not isinstance(row, dict):
            continue

        start = _coerce_float(row.get("start"))
        end = _coerce_float(row.get("end"))
        text = str(row.get("text") or "").strip()

        if start is None or end is None or end <= start or not text:
            continue

        raw_tokens = re.findall(r"[A-Za-z0-9]+(?:['’][A-Za-z0-9]+)?", text)
        normalized = [(raw, normalize_token(raw)) for raw in raw_tokens]
        normalized = [(raw, token) for raw, token in normalized if token]
        if not normalized:
            continue

        duration = end - start
        count = len(normalized)
        for index, (raw, token) in enumerate(normalized):
            word_start = start + duration * (index / count)
            word_end = start + duration * ((index + 1) / count)
            words.append(
                WordStamp(
                    text=raw,
                    token=token,
                    start=word_start,
                    end=word_end,
                )
            )

    return words


def transcribe_ajil(
    audio: Path,
    *,
    base_url: str,
    auth_token: str,
    auth_header_name: str,
    language: str,
    timeout_sec: float,
) -> tuple[list[WordStamp], str, float, dict[str, Any]]:
    url = base_url.rstrip("/") + "/v1/audio/transcriptions"
    headers: dict[str, str] = {}
    if auth_token.strip():
        headers[auth_header_name] = auth_token.strip()

    params: dict[str, str] = {}
    if language.strip():
        params["language"] = language.strip()

    content_type = mimetypes.guess_type(audio.name)[0] or "application/octet-stream"

    with audio.open("rb") as handle:
        response = httpx.post(
            url,
            headers=headers,
            params=params,
            files={"file": (audio.name, handle, content_type)},
            timeout=timeout_sec,
        )

    try:
        body = response.json()
    except Exception as exc:
        raise RuntimeError(
            f"Ajil returned non-JSON response (HTTP {response.status_code}): "
            f"{response.text[:500]}"
        ) from exc

    if response.status_code >= 400:
        raise RuntimeError(
            f"Ajil STT failed (HTTP {response.status_code}): "
            + json.dumps(body, ensure_ascii=False)[:1200]
        )

    if not isinstance(body, dict) or not body.get("ok", False):
        raise RuntimeError(
            "Ajil STT returned an unsuccessful payload: "
            + json.dumps(body, ensure_ascii=False)[:1200]
        )

    provider_payload = body.get("payload")
    if not isinstance(provider_payload, dict):
        raise RuntimeError("Ajil STT response did not contain a payload object.")

    raw = provider_payload.get("raw")
    if not isinstance(raw, dict):
        raw = {}

    transcript = str(provider_payload.get("text") or raw.get("text") or "").strip()
    if not transcript:
        raise RuntimeError("Ajil STT response did not contain transcript text.")

    words = _word_stamps_from_raw_words(raw.get("words"))
    timestamp_source = "word"

    if not words:
        words = _word_stamps_from_segments(raw.get("segments"))
        timestamp_source = "segment_interpolated"

    if not words:
        raise RuntimeError(
            "Ajil returned no usable timestamps. Set root .env values "
            "UAG_GROQ_STT_RESPONSE_FORMAT=verbose_json and "
            "UAG_GROQ_STT_TIMESTAMP_GRANULARITIES=word,segment."
        )

    duration = (
        _coerce_float(raw.get("duration"))
        or ffprobe_duration(audio)
        or max(word.end for word in words)
    )

    metadata = {
        "backend": "ajil",
        "provider": str(body.get("provider") or "groq"),
        "model": str(provider_payload.get("model_used") or body.get("model") or ""),
        "fallback_used": bool(provider_payload.get("fallback_used", False)),
        "timestamp_source": timestamp_source,
        "ajil_base_url": base_url.rstrip("/"),
    }

    return words, transcript, float(duration), metadata


def transcribe_local(
    audio: Path,
    model_name: str,
    device: str,
    compute_type: str,
    language: str,
) -> tuple[list[WordStamp], str, float, dict[str, Any]]:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "Local STT backend requires faster-whisper. Install it with: "
            "python -m pip install -r requirements-alignment.txt"
        ) from exc

    model = WhisperModel(model_name, device=device, compute_type=compute_type)

    segments, info = model.transcribe(
        str(audio),
        language=language or "en",
        beam_size=5,
        word_timestamps=True,
        vad_filter=True,
        condition_on_previous_text=True,
    )

    words: list[WordStamp] = []
    transcript_parts: list[str] = []
    last_end = 0.0

    for segment in segments:
        transcript_parts.append(segment.text.strip())
        last_end = max(last_end, float(segment.end or 0.0))
        if not segment.words:
            continue

        for word in segment.words:
            token = normalize_token(word.word)
            if not token:
                continue
            words.append(
                WordStamp(
                    text=word.word.strip(),
                    token=token,
                    start=float(word.start),
                    end=float(word.end),
                )
            )

    if not words:
        raise RuntimeError("Whisper returned no timestamped words.")

    duration = ffprobe_duration(audio) or last_end or words[-1].end
    transcript = " ".join(part for part in transcript_parts if part).strip()
    metadata = {
        "backend": "local",
        "provider": "faster-whisper",
        "model": model_name,
        "fallback_used": False,
        "timestamp_source": "word",
        "device": device,
        "compute_type": compute_type,
    }
    return words, transcript, duration, metadata


def build_expected_index(beats: list[dict]) -> tuple[list[str], list[tuple[int, int]]]:
    all_tokens: list[str] = []
    ranges: list[tuple[int, int]] = []

    for beat in beats:
        start = len(all_tokens)
        all_tokens.extend(beat["tokens"])
        end = len(all_tokens)
        ranges.append((start, end))

    return all_tokens, ranges


def exact_token_mapping(expected: list[str], observed: list[str]) -> dict[int, int]:
    matcher = difflib.SequenceMatcher(
        a=expected,
        b=observed,
        autojunk=False,
    )

    mapping: dict[int, int] = {}
    for block in matcher.get_matching_blocks():
        for offset in range(block.size):
            mapping[block.a + offset] = block.b + offset
    return mapping


def nearest_mapped(
    mapping: dict[int, int],
    start: int,
    end: int,
) -> list[tuple[int, int]]:
    return sorted(
        ((expected_i, observed_i) for expected_i, observed_i in mapping.items() if start <= expected_i < end),
        key=lambda item: item[0],
    )


def fmt_time(seconds: float) -> str:
    total_ms = round(seconds * 1000)
    minutes, rem = divmod(total_ms, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{minutes:02d}:{secs:02d}.{millis:03d}"


def align_beats(
    beats: list[dict],
    words: list[WordStamp],
    duration: float,
) -> list[dict]:
    expected_tokens, beat_ranges = build_expected_index(beats)
    observed_tokens = [w.token for w in words]
    mapping = exact_token_mapping(expected_tokens, observed_tokens)

    aligned: list[dict] = []

    for beat, (start_idx, end_idx) in zip(beats, beat_ranges):
        mapped = nearest_mapped(mapping, start_idx, end_idx)

        if mapped:
            first_word = words[mapped[0][1]]
            last_word = words[mapped[-1][1]]
            speech_start = first_word.start
            speech_end = last_word.end
            confidence = len(mapped) / max(1, end_idx - start_idx)
        else:
            # Fallback should rarely be needed for synthetic narration.
            fraction_start = start_idx / max(1, len(expected_tokens))
            fraction_end = end_idx / max(1, len(expected_tokens))
            speech_start = duration * fraction_start
            speech_end = duration * fraction_end
            confidence = 0.0

        aligned.append(
            {
                "beat_id": beat["beat_id"],
                "narration": beat["narration"],
                "speech_start": round(speech_start, 3),
                "speech_end": round(speech_end, 3),
                "match_confidence": round(confidence, 3),
            }
        )

    # Convert phrase timings into a continuous image timeline.
    for i, beat in enumerate(aligned):
        display_start = 0.0 if i == 0 else beat["speech_start"]
        if i + 1 < len(aligned):
            display_end = aligned[i + 1]["speech_start"]
        else:
            display_end = duration

        if display_end < display_start:
            display_end = max(display_start, beat["speech_end"])

        beat["display_start"] = round(display_start, 3)
        beat["display_end"] = round(display_end, 3)
        beat["display_duration"] = round(display_end - display_start, 3)

    return aligned


def write_outputs(
    video_dir: Path,
    audio: Path,
    stt_metadata: dict[str, Any],
    transcript: str,
    duration: float,
    aligned: list[dict],
) -> tuple[Path, Path]:
    timing_dir = video_dir / "timing"
    timing_dir.mkdir(parents=True, exist_ok=True)

    json_path = timing_dir / "BEAT_TIMINGS.json"
    md_path = timing_dir / "BEAT_TIMINGS.md"

    payload = {
        "audio": str(audio.relative_to(video_dir)) if audio.is_relative_to(video_dir) else str(audio),
        "audio_duration_seconds": round(duration, 3),
        "stt": stt_metadata,
        "transcript": transcript,
        "beats": aligned,
    }
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    lines = [
        "# Beat Timings",
        "",
        f"Audio: `{payload['audio']}`",
        f"Duration: **{fmt_time(duration)}**",
        f"STT backend: {stt_metadata.get('backend', '')}",
        f"Provider: {stt_metadata.get('provider', '')}",
        f"Model: {stt_metadata.get('model', '')}",
        f"Timestamp source: {stt_metadata.get('timestamp_source', '')}",
        "",
        "| Beat | Display | Duration | Speech | Match | Narration |",
        "|---:|---|---:|---|---:|---|",
    ]

    for beat in aligned:
        narration_for_table = beat["narration"].replace("|", "\\|")
        lines.append(
            "| "
            f"{beat['beat_id']:02d} | "
            f"{fmt_time(beat['display_start'])} → {fmt_time(beat['display_end'])} | "
            f"{beat['display_duration']:.3f}s | "
            f"{fmt_time(beat['speech_start'])} → {fmt_time(beat['speech_end'])} | "
            f"{beat['match_confidence']:.0%} | "
            f"{narration_for_table} |"
        )

    low = [b for b in aligned if b["match_confidence"] < 0.75]
    lines += [
        "",
        "## QC",
        "",
        "- Low-confidence beats (<75% token match): " + (", ".join(f"{b['beat_id']:02d}" for b in low) if low else "none"),
        "- Review the generated timing table once before using it for the final render.",
        "- `display_start/display_end` are continuous edit timings; `speech_start/speech_end` are the matched spoken phrase timings.",
        "- Word timestamps are preferred. Segment-interpolated timestamps require extra QC.",
        "",
    ]

    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


def main() -> None:
    load_root_env()

    parser = argparse.ArgumentParser(description="Align narration audio to VISUAL_BEATS.md.")
    parser.add_argument("video_dir", type=Path)
    parser.add_argument("--audio", type=Path, default=None)

    parser.add_argument(
        "--backend",
        choices=("ajil", "local"),
        default=os.getenv("YT_STT_BACKEND", "ajil"),
    )
    parser.add_argument(
        "--language",
        default=os.getenv("YT_STT_LANGUAGE", "en"),
    )

    parser.add_argument(
        "--ajil-base-url",
        default=os.getenv("YT_AJIL_BASE_URL", "http://127.0.0.1:8080"),
    )
    parser.add_argument(
        "--ajil-token",
        default=os.getenv("YT_AJIL_AUTH_TOKEN") or os.getenv("UAG_AUTH_TOKEN", ""),
    )
    parser.add_argument(
        "--ajil-auth-header",
        default=os.getenv("YT_AJIL_AUTH_HEADER_NAME")
        or os.getenv("UAG_AUTH_HEADER_NAME", "x-api-token"),
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=env_float("YT_STT_TIMEOUT_SEC", 120.0),
    )

    parser.add_argument(
        "--model",
        default=os.getenv("YT_LOCAL_WHISPER_MODEL", "small.en"),
    )
    parser.add_argument(
        "--device",
        default=os.getenv("YT_LOCAL_WHISPER_DEVICE", "cpu"),
    )
    parser.add_argument(
        "--compute-type",
        default=os.getenv("YT_LOCAL_WHISPER_COMPUTE_TYPE", "int8"),
    )
    args = parser.parse_args()

    video_dir = args.video_dir.expanduser().resolve()
    beats_path = video_dir / "VISUAL_BEATS.md"

    beats = parse_beats(beats_path)
    audio = find_audio(video_dir, args.audio)

    print(f"Video: {video_dir}")
    print(f"Audio: {audio}")
    print(f"Beats: {len(beats)}")
    print(f"STT backend: {args.backend}")

    if args.backend == "ajil":
        print(f"Ajil: {args.ajil_base_url}")
        words, transcript, duration, stt_metadata = transcribe_ajil(
            audio,
            base_url=args.ajil_base_url,
            auth_token=args.ajil_token,
            auth_header_name=args.ajil_auth_header,
            language=args.language,
            timeout_sec=args.timeout,
        )
    else:
        print(f"Local Whisper model: {args.model}")
        words, transcript, duration, stt_metadata = transcribe_local(
            audio,
            model_name=args.model,
            device=args.device,
            compute_type=args.compute_type,
            language=args.language,
        )

    aligned = align_beats(beats, words, duration)
    json_path, md_path = write_outputs(
        video_dir,
        audio,
        stt_metadata,
        transcript,
        duration,
        aligned,
    )

    low = [b for b in aligned if b["match_confidence"] < 0.75]

    print(f"Created: {json_path}")
    print(f"Created: {md_path}")
    print(f"Audio duration: {duration:.3f}s")
    print(f"Timestamp source: {stt_metadata.get('timestamp_source')}")
    if low:
        print("WARNING: Low-confidence beats:", ", ".join(str(b["beat_id"]) for b in low))
    else:
        print("Alignment QC: all beats >= 75% token match.")

if __name__ == "__main__":
    main()
