"""Audio-authoritative alignment, pacing gate, and rhythm contracts (P06)."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import wave
from pathlib import Path
from typing import Any, Mapping, Sequence

from .canonical_text import CanonicalDocument
from .contracts import ContractError, canonical_json_hash, stable_id

METHODS = frozenset({"measured_word", "segment_interpolated"})
RHYTHM_ROLES = frozenset({"hook_peak", "clue", "contrast", "consequence", "proof", "pause", "payoff", "cta"})
CRITICAL_RE = re.compile(r"(?:\d|%|\b(?:not|no|never|isn't|can't|won't|without)\b)", re.IGNORECASE)


def probe_audio(path: Path) -> dict[str, Any]:
    """Read real media duration; no script-derived duration fallback exists."""
    path = path.resolve()
    if not path.is_file() or path.stat().st_size <= 0:
        raise ContractError("narration audio is missing or empty")
    if path.suffix.casefold() == ".wav":
        try:
            with wave.open(str(path), "rb") as stream:
                duration = stream.getnframes() / stream.getframerate()
                channels, rate = stream.getnchannels(), stream.getframerate()
        except (wave.Error, EOFError) as exc:
            raise ContractError("narration WAV cannot be decoded") from exc
        codec = "pcm"
    else:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_name,channels,sample_rate", "-of", "json", str(path)],
            text=True, capture_output=True, check=False,
        )
        if result.returncode:
            raise ContractError(f"narration audio ffprobe failed: {result.stderr.strip()}")
        try:
            payload = json.loads(result.stdout)
            duration = float(payload["format"]["duration"])
            stream = next(item for item in payload.get("streams", []) if item.get("codec_name"))
            codec, channels, rate = str(stream["codec_name"]), int(stream.get("channels") or 0), int(stream.get("sample_rate") or 0)
        except (KeyError, StopIteration, TypeError, ValueError) as exc:
            raise ContractError("narration audio metadata is incomplete") from exc
    if not 0 < duration < 3600:
        raise ContractError("narration audio duration is invalid")
    return {
        "path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "duration_seconds": duration, "codec": codec, "channels": channels, "sample_rate": rate,
    }


def _normalized_tokens(values: Sequence[Any]) -> str:
    return "".join(re.sub(r"[^a-z0-9%]+", "", str(value).casefold()) for value in values)


def build_narration_timing(
    *, document: CanonicalDocument, token_map: Sequence[Mapping[str, Any]],
    observations: Sequence[Mapping[str, Any]], audio: Mapping[str, Any],
    performance_events: Sequence[Mapping[str, Any]] = (), event_windows: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Bind backend observations to stable canonical IDs and real audio metadata."""
    if not re.fullmatch(r"[a-f0-9]{64}", str(audio.get("sha256") or "")) or not isinstance(audio.get("duration_seconds"), (int, float)):
        raise ContractError("timing requires probed audio hash and duration")
    duration = float(audio["duration_seconds"])
    canonical = [token for token in document.tokens if token.spoken]
    map_by_id = {str(item.get("word_id")): item for item in token_map}
    if set(map_by_id) != {token.word_id for token in canonical}:
        raise ContractError("voice token map does not cover canonical spoken words exactly")
    if len(observations) != len(canonical):
        raise ContractError("alignment coverage is incomplete; bounded backend retry is required")
    words: list[dict[str, Any]] = []
    prior_end = 0.0
    for token, raw in zip(canonical, observations, strict=True):
        if not isinstance(raw, Mapping) or set(raw) != {"word_id", "observed_tokens", "start", "end", "confidence", "method"}:
            raise ContractError("alignment observation has missing or unknown fields")
        if raw["word_id"] != token.word_id:
            raise ContractError("alignment word identity/order mismatch")
        observed = raw["observed_tokens"]
        if not isinstance(observed, list) or not observed:
            raise ContractError(f"alignment {token.word_id} has no observed token evidence")
        if _normalized_tokens(observed) != _normalized_tokens([token.text]):
            raise ContractError(f"alignment text mismatch at {token.word_id}")
        start, end, confidence = raw["start"], raw["end"], raw["confidence"]
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in (start, end, confidence)):
            raise ContractError("alignment timing/confidence must be numeric")
        start, end, confidence = float(start), float(end), float(confidence)
        if start < prior_end - .001 or not start <= end <= duration + .001 or not 0 <= confidence <= 1:
            raise ContractError("alignment contains overlap, reversal, or out-of-audio timing")
        method = str(raw["method"])
        if method not in METHODS:
            raise ContractError("alignment method must distinguish measured_word from segment_interpolated")
        critical = token.occurrence <= 12 or bool(CRITICAL_RE.search(token.text))
        threshold = .82 if critical else .65
        if confidence < threshold:
            raise ContractError(f"critical alignment confidence failed at {token.word_id}" if critical else f"alignment confidence failed at {token.word_id}")
        words.append({
            "word_id": token.word_id, "unit_id": token.unit_id, "canonical_text": token.text,
            "canonical_start": token.start, "canonical_end": token.end, "observed_tokens": list(observed),
            "start": start, "end": end, "confidence": confidence, "method": method,
        })
        prior_end = end
    event_by_id = {str(item.get("event_id")): item for item in performance_events}
    nonverbal: list[dict[str, Any]] = []
    for raw in event_windows:
        if not isinstance(raw, Mapping) or set(raw) != {"performance_event_id", "start", "end", "label", "evidence", "confidence"}:
            raise ContractError("nonverbal event window has missing or unknown fields")
        event_id = str(raw["performance_event_id"])
        if event_id not in event_by_id:
            raise ContractError(f"nonverbal window references unknown event {event_id}")
        start, end = float(raw["start"]), float(raw["end"])
        if not 0 <= start <= end <= duration:
            raise ContractError("nonverbal event window lies outside audio")
        evidence = str(raw["evidence"])
        if evidence not in {"candidate_event_window", "nonsemantic_audio_analysis", "human_verified"}:
            raise ContractError("nonverbal event evidence is invalid")
        verified = evidence == "human_verified"
        nonverbal.append({**dict(raw), "observed": verified, "semantic_verification": "verified" if verified else "unverified"})
    first_start = words[0]["start"]
    return {
        "schema_version": 1, "canonical_text_hash": document.text_sha256,
        "audio": dict(audio), "audio_authoritative": True, "words": words,
        "coverage": 1.0, "leading_audio_seconds": first_start,
        "leading_audio_policy": "preserve_unless_separately_proven_disposable",
        "nonverbal_events": nonverbal, "caption_source": "canonical_words_only",
        "timing_hash": canonical_json_hash({"audio_sha256": audio["sha256"], "words": words, "events": nonverbal}),
    }


def pacing_report(timing: Mapping[str, Any], *, minimum_seconds: float, maximum_seconds: float) -> dict[str, Any]:
    if not 0 < minimum_seconds <= maximum_seconds:
        raise ContractError("duration target is invalid")
    duration = float(timing.get("audio", {}).get("duration_seconds") or 0)
    if duration <= 0 or timing.get("coverage") != 1.0:
        raise ContractError("pacing gate requires valid complete audio timing")
    status = "within_target" if minimum_seconds <= duration <= maximum_seconds else ("too_short" if duration < minimum_seconds else "too_long")
    action = {
        "within_target": "continue_without_artistic_gate",
        "too_short": "continue_if_technically_complete_or_user_revise_later",
        "too_long": "bounded_canonical_rewrite_or_supported_voice_setting_then_regenerate_and_realign",
    }[status]
    return {
        "schema_version": 1, "actual_audio_seconds": duration,
        "requested_range_seconds": [minimum_seconds, maximum_seconds], "status": status,
        "action": action, "hidden_audio_retime": False, "original_audio_preserved": True,
    }


def build_rhythm_map(
    *, timing: Mapping[str, Any], performance_events: Sequence[Mapping[str, Any]],
    events: Sequence[Mapping[str, Any]], music_driven: bool = False,
    music_features: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    words = {item["word_id"]: item for item in timing.get("words", [])}
    performance_ids = {str(item.get("event_id")) for item in performance_events}
    output: list[dict[str, Any]] = []
    primary_ranges: list[tuple[float, float, str]] = []
    seen: set[str] = set()
    required = {"event_id", "word_ids", "performance_event_ids", "role", "time_evidence", "primary_attention", "supporting_layers", "purpose"}
    for raw in events:
        if not isinstance(raw, Mapping) or set(raw) != required:
            raise ContractError("rhythm event has missing or unknown fields")
        event_id = stable_id(raw.get("event_id"), "event_id")
        if event_id in seen:
            raise ContractError(f"duplicate rhythm event {event_id}")
        seen.add(event_id)
        word_ids = raw.get("word_ids")
        if not isinstance(word_ids, list) or not word_ids or any(word_id not in words for word_id in word_ids):
            raise ContractError(f"rhythm event {event_id} has unknown/empty word span")
        pids = raw.get("performance_event_ids")
        if not isinstance(pids, list) or any(pid not in performance_ids for pid in pids):
            raise ContractError(f"rhythm event {event_id} has unknown performance event")
        if raw.get("role") not in RHYTHM_ROLES or raw.get("time_evidence") not in {"measured_word", "segment_interpolated", "mixed"}:
            raise ContractError(f"rhythm event {event_id} has invalid role/evidence")
        if not isinstance(raw.get("supporting_layers"), list) or not str(raw.get("primary_attention") or "").strip() or not str(raw.get("purpose") or "").strip():
            raise ContractError(f"rhythm event {event_id} has incomplete attention intent")
        start, end = min(words[word_id]["start"] for word_id in word_ids), max(words[word_id]["end"] for word_id in word_ids)
        for other_start, other_end, other_id in primary_ranges:
            if start < other_end and end > other_start:
                raise ContractError(f"primary attention overlap between {other_id} and {event_id}")
        primary_ranges.append((start, end, event_id))
        output.append({**dict(raw), "start": start, "end": end})
    if music_driven and not music_features:
        raise ContractError("music-driven rhythm requires pre-edit music features")
    return {
        "schema_version": 1, "timing_hash": timing.get("timing_hash"), "events": output,
        "music_driven": music_driven,
        "music_policy": "features_influence_rhythm_before_edit" if music_driven else "music_follows_edit",
        "music_features": dict(music_features or {}) if music_driven else None,
        "rhythm_hash": canonical_json_hash({"timing_hash": timing.get("timing_hash"), "events": output, "music_driven": music_driven, "music_features": music_features if music_driven else None}),
    }
