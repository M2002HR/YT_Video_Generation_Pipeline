"""Caption, branding, sound, and preview-parity contracts for Shorts V2 (P09)."""
from __future__ import annotations

import math
import re
from copy import deepcopy
from pathlib import PurePosixPath
from typing import Any, Mapping, Sequence

from .contracts import ContractError, canonical_json_hash, resolve_precedence, stable_id

HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
CAPTION_MODES = frozenset({"phrase", "one_word", "manual", "off"})


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ContractError(f"{name} must be finite")
    return float(value)


def _clean_display(tokens: Sequence[str]) -> str:
    text = " ".join(tokens)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"\s+([’'])\s+", r"\1", text)
    return " ".join(text.split())


def build_caption_plan(
    *, words: Sequence[Mapping[str, Any]], mode: str, enabled: bool, max_words: int,
    style: Mapping[str, Any], manual_locks: Mapping[str, Any],
    emphasis_word_ids: Sequence[str], manual_groups: Sequence[Sequence[str]] | None = None,
) -> dict[str, Any]:
    if mode not in CAPTION_MODES or enabled != (mode != "off"):
        raise ContractError("caption enabled/mode state is inconsistent")
    if isinstance(max_words, bool) or not isinstance(max_words, int) or not 1 <= max_words <= 12:
        raise ContractError("caption max_words must be in 1..12")
    normalized, seen = [], set()
    for raw in words:
        if not isinstance(raw, Mapping) or not {"word_id", "canonical_text", "start", "end"} <= set(raw):
            raise ContractError("captions require canonical observed word timing")
        word_id = stable_id(raw.get("word_id"), "word_id")
        text = str(raw.get("canonical_text") or "").strip()
        start, end = _finite(raw.get("start"), "word.start"), _finite(raw.get("end"), "word.end")
        if word_id in seen or not text or end <= start:
            raise ContractError("caption words must be unique, non-empty, and positive")
        if re.search(r"<break|\[[^]]+\]", text, flags=re.IGNORECASE):
            raise ContractError("performance markup cannot enter canonical captions")
        seen.add(word_id)
        normalized.append({"word_id": word_id, "canonical_text": text, "start": start, "end": end})
    emphasized = list(dict.fromkeys(str(item) for item in emphasis_word_ids))
    if any(item not in seen for item in emphasized):
        raise ContractError("caption emphasis references an unknown word")
    if not enabled:
        return {
            "schema_version": 1, "enabled": False, "mode": "off", "cues": [],
            "style": {}, "manual_locks": dict(manual_locks), "burn_in_required": False,
            "caption_hash": canonical_json_hash({"enabled": False}),
        }
    allowed_style = {"font", "size", "color", "outline", "position"}
    if set(style) != allowed_style:
        raise ContractError("caption style has missing or unknown fields")
    if not str(style.get("font") or "").strip() or not HEX_COLOR.fullmatch(str(style.get("color") or "")):
        raise ContractError("caption font/color is invalid")
    if _finite(style.get("size"), "caption.size") <= 0 or _finite(style.get("outline"), "caption.outline") < 0:
        raise ContractError("caption size/outline is invalid")
    if style.get("position") not in {"top", "middle", "bottom"}:
        raise ContractError("caption position is invalid")
    groups: list[list[str]]
    if mode == "one_word":
        groups = [[item["word_id"]] for item in normalized]
    elif mode == "manual":
        groups = [list(group) for group in (manual_groups or [])]
        flattened = [word_id for group in groups for word_id in group]
        if flattened != [item["word_id"] for item in normalized] or any(not group or len(group) > max_words for group in groups):
            raise ContractError("manual caption groups must cover canonical words once in order")
    else:
        groups = [[item["word_id"] for item in normalized[index:index + max_words]] for index in range(0, len(normalized), max_words)]
    by_id = {item["word_id"]: item for item in normalized}
    cues = []
    for index, group in enumerate(groups):
        tokens = [by_id[word_id]["canonical_text"] for word_id in group]
        cues.append({
            "cue_id": f"caption.{index:04d}", "word_ids": group, "text": _clean_display(tokens),
            "start": by_id[group[0]]["start"], "end": by_id[group[-1]]["end"],
            "emphasis_word_ids": [item for item in emphasized if item in group],
        })
    result = {
        "schema_version": 1, "enabled": True, "mode": mode, "cues": cues,
        "style": dict(style), "manual_locks": dict(manual_locks), "burn_in_required": True,
        "text_source": "canonical_observed_words",
    }
    result["caption_hash"] = canonical_json_hash(result)
    return result


def build_layout_constraints(
    *, width: int, height: int, preset: str, ai: Mapping[str, Any],
    user: Mapping[str, Any], manual_locks: Mapping[str, Any],
) -> dict[str, Any]:
    if width <= 0 or height <= 0 or preset != "vertical_safe_v1":
        raise ContractError("unsupported layout dimensions or preset")
    allowed = {"subtitle_y", "title_y", "watermark_x", "watermark_y"}
    if not set(ai) <= allowed or not set(user) <= allowed or not set(manual_locks) <= allowed:
        raise ContractError("layout contains an unknown field")
    defaults = {"subtitle_y": .82, "title_y": .12, "watermark_x": .94, "watermark_y": .06}
    locked = {key for key, value in manual_locks.items() if value}
    effective = resolve_precedence(defaults=defaults, ai=ai, user=user, locked_fields=locked)
    if any(not 0 <= _finite(value, f"layout.{key}") <= 1 for key, value in effective.items()):
        raise ContractError("layout normalized coordinates must be in 0..1")
    return {
        "schema_version": 1, "preset": preset, "resolution": [width, height],
        "effective": effective, "manual_locks": dict(manual_locks),
        "safe_area": {"left": .05, "right": .95, "top": .04, "bottom": .94},
        "layout_hash": canonical_json_hash({"resolution": [width, height], "preset": preset, "effective": effective}),
    }


def build_overlay_plan(
    *, title: str | None, title_range: Sequence[int] | None,
    watermark: str | None, watermark_range: Sequence[int] | None,
    total_frames: int, already_branded: bool,
) -> dict[str, Any]:
    if total_frames <= 0:
        raise ContractError("overlay plan requires a positive master clock")
    if already_branded and (title or watermark):
        raise ContractError("already branded media cannot receive duplicate title/watermark")
    overlays = []
    for kind, text, frame_range in (("title", title, title_range), ("watermark", watermark, watermark_range)):
        if not text:
            if frame_range is not None:
                raise ContractError(f"{kind} range exists without text")
            continue
        if not isinstance(frame_range, (list, tuple)) or len(frame_range) != 2:
            raise ContractError(f"{kind} requires an explicit frame range")
        start, end = frame_range
        if any(isinstance(item, bool) or not isinstance(item, int) for item in (start, end)) or not 0 <= start < end <= total_frames:
            raise ContractError(f"{kind} frame range is invalid")
        overlays.append({"overlay_id": f"overlay.{kind}", "kind": kind, "text": str(text), "start_frame": start, "end_frame": end})
    result = {"schema_version": 1, "already_branded_input": already_branded, "overlays": overlays}
    result["overlay_hash"] = canonical_json_hash(result)
    return result


def _media_file(value: Mapping[str, Any], name: str) -> dict[str, Any]:
    required = {"path", "sha256", "license", "source", "duration_seconds"}
    if set(value) != required or not re.fullmatch(r"[a-f0-9]{64}", str(value.get("sha256") or "")):
        raise ContractError(f"{name} selection is incomplete")
    path = PurePosixPath(str(value.get("path") or ""))
    if path.is_absolute() or ".." in path.parts:
        raise ContractError(f"{name} path is unsafe")
    if _finite(value.get("duration_seconds"), f"{name}.duration_seconds") <= 0:
        raise ContractError(f"{name} duration is invalid")
    return dict(value)


def build_sound_plan(
    *, narration_gain_db: float, music: Mapping[str, Any] | None,
    sfx_enabled: bool, sfx_cues: Sequence[Mapping[str, Any]], music_driven: bool,
    rhythm_events: Sequence[Mapping[str, Any]], music_features: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    gain = _finite(narration_gain_db, "narration_gain_db")
    if not -24 <= gain <= 12 or not isinstance(sfx_enabled, bool) or not isinstance(music_driven, bool):
        raise ContractError("sound settings are out of range")
    selected_music = _media_file(music, "music") if music is not None else None
    if music_driven and (selected_music is None or not music_features):
        raise ContractError("music-driven edit requires selected music and extracted features")
    cues = []
    if not sfx_enabled and sfx_cues:
        raise ContractError("sfx_enabled=false forbids SFX cues/acquisition")
    for raw in sfx_cues:
        if set(raw) != {"cue_id", "start", "gain_db", "required", "media"}:
            raise ContractError("SFX cue has missing or unknown fields")
        cue_id = stable_id(raw.get("cue_id"), "cue_id")
        start = _finite(raw.get("start"), "sfx.start")
        cue_gain = _finite(raw.get("gain_db"), "sfx.gain_db")
        if start < 0 or not -36 <= cue_gain <= 6 or not isinstance(raw.get("required"), bool):
            raise ContractError("SFX cue timing/gain is invalid")
        cues.append({**dict(raw), "cue_id": cue_id, "media": _media_file(raw["media"], "sfx")})
    result = {
        "schema_version": 1, "narration_gain_db": gain, "music": selected_music,
        "music_driven": music_driven, "music_features": deepcopy(music_features) if music_driven else None,
        "sfx_enabled": sfx_enabled, "sfx_cues": cues,
        "sfx_status": "planned" if sfx_enabled else "disabled_no_hidden_effect",
        "provider_calls": {"tts": 0, "image": 0, "flow": 0, "sfx": len(cues) if sfx_enabled else 0},
        "video_stream_policy": "reuse", "edit_invalidation": "rhythm_and_edit" if music_driven else "none_music_follows_edit",
        "rhythm_event_ids": [item.get("event_id") for item in rhythm_events],
    }
    result["sound_hash"] = canonical_json_hash(result)
    return result


def compile_presentation(
    timeline: Mapping[str, Any], *, caption_plan: Mapping[str, Any],
    layout_constraints: Mapping[str, Any], overlay_plan: Mapping[str, Any],
    sound_plan: Mapping[str, Any],
) -> dict[str, Any]:
    if not re.fullmatch(r"[a-f0-9]{64}", str(timeline.get("compile_hash") or "")):
        raise ContractError("presentation requires a deterministic source compile")
    resolution = timeline.get("resolution") or {}
    if layout_constraints.get("resolution") != [resolution.get("width"), resolution.get("height")]:
        raise ContractError("layout resolution disagrees with compiled timeline")
    parity = {
        "clock": timeline.get("clock"), "total_frames": timeline.get("total_frames"),
        "segments": timeline.get("segments"), "transitions": timeline.get("transitions"),
        "caption_hash": caption_plan.get("caption_hash"), "layout_hash": layout_constraints.get("layout_hash"),
        "overlay_hash": overlay_plan.get("overlay_hash"), "sound_hash": sound_plan.get("sound_hash"),
    }
    parity_hash = canonical_json_hash(parity)
    result = {
        "schema_version": 1, "video_source_compile_hash": timeline["compile_hash"],
        "caption_plan": deepcopy(dict(caption_plan)), "layout_constraints": deepcopy(dict(layout_constraints)),
        "overlay_plan": deepcopy(dict(overlay_plan)), "sound_plan": deepcopy(dict(sound_plan)),
        "preview": {"parity_hash": parity_hash, "audio_required": True, "seekable": True, "byte_range_required": True, "quality_role": "proxy"},
        "final": {"parity_hash": parity_hash, "audio_required": True, "quality_role": "accepted_candidate"},
    }
    result["presentation_hash"] = canonical_json_hash(result)
    return result
