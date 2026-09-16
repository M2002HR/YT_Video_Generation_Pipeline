"""Shared, strict contract for the post-render Release and thumbnail package.

The browser gets this schema from the control panel; the worker normalizes the exact
same payload again before it can spend a provider credit.  Keep binary assets and
filesystem paths out of this contract.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from typing import Any

LAYOUTS = ("character_left", "character_right", "contrast_split", "discovery_focus")
BRAND_PROFILES = ("q_station_v1",)

THUMBNAIL_DEFAULTS: dict[str, Any] = {
    "count_mode": "fixed", "count": 3, "auto_min": 2, "auto_max": 4,
    "concept_count": "auto", "diversity": "high", "layout_mode": "auto",
    "allowed_layouts": list(LAYOUTS), "tension": "strong", "brand_profile": "q_station_v1",
    "aspect_ratio": "9:16", "image_model": "inherit_episode", "quality": "native",
    "image_fallback": "off",
    "thumbnail_note": "", "must_include": "", "must_avoid": "",
    "text_mode": "auto", "manual_text": "", "candidate_text_overrides": {},
    "text_renderer": "local", "font_id": "dejavu_sans_bold", "case_mode": "auto",
    "text_fill": "#FFFFFF", "text_outline": "#111827", "outline_width": 0.012,
    "shadow": True, "text_background": False, "line_spacing": 0.04,
    "text_position": "auto", "text_box_width": 0.82, "safe_margin": 0.055,
    # A 9:16 native 2160px canvas needs a lower floor than a 1080px preview: this
    # still yields a 65px font while allowing ordinary four-to-six word headlines to wrap.
    "text_min_scale": 0.03, "text_max_scale": 0.115, "max_words": 6,
    "max_characters": 40, "max_lines": 2, "coordinates": None,
    "badge_enabled": True, "badge_asset_id": "q_station_mark", "badge_position": "bottom_right", "badge_scale": 0.07,
    "reference_mode": "master", "reference_timestamps": [], "max_references": 5,
    "corrections_per_candidate": 1, "max_image_generations": 6,
    "review_preset": "balanced", "review_enabled": True, "export_format": "png", "jpeg_quality": 90,
    "preview_small": True, "comparison_sheet": True, "send_previews": True,
    "send_comparison_sheet": True, "send_report_json": True, "send_raw_artwork": False,
    "delivery_mode": "all_final_candidates", "resend": False,
}

RELEASE_DEFAULTS: dict[str, Any] = {
    "generate_metadata": True, "generate_thumbnail": True, "create_upload_guide": True,
    "send_telegram": True, "force": False, "metadata_note": "", "thumbnail_note": "", "title_override": "",
    "thumbnail": THUMBNAIL_DEFAULTS,
}

def _integer(value: Any, name: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"Release setting {name} must be an integer between {low} and {high}.")
    return value

def _number(value: Any, name: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= float(value) <= high:
        raise ValueError(f"Release setting {name} must be a finite number between {low} and {high}.")
    return round(float(value), 4)

def _enum(value: Any, name: str, allowed: tuple[str, ...]) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(f"Release setting {name} must be one of: {', '.join(allowed)}.")
    return value

def _text(value: Any, name: str, limit: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"Release setting {name} must be text.")
    value = value.strip()
    if len(value) > limit:
        raise ValueError(f"Release setting {name} is too long.")
    return value

def normalize_release_settings(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Release settings must be an object.")
    unknown = set(value) - set(RELEASE_DEFAULTS)
    if unknown:
        raise ValueError("Unknown Release setting(s): " + ", ".join(sorted(unknown)))
    result = copy.deepcopy(RELEASE_DEFAULTS)
    for name in ("generate_metadata", "generate_thumbnail", "create_upload_guide", "send_telegram", "force"):
        if name in value and not isinstance(value[name], bool):
            raise ValueError(f"Release setting {name} must be on or off.")
        result[name] = bool(value.get(name, result[name]))
    result["metadata_note"] = _text(value.get("metadata_note", ""), "metadata_note", 2000)
    result["thumbnail_note"] = _text(value.get("thumbnail_note", ""), "thumbnail_note", 2000)
    result["title_override"] = _text(value.get("title_override", ""), "title_override", 100)
    supplied = value.get("thumbnail", {})
    # Compatibility for the original Release endpoint while making the nested contract authoritative.
    if "thumbnail_note" in value:
        if not isinstance(supplied, dict):
            raise ValueError("Release setting thumbnail must be an object.")
        supplied = {**supplied, "thumbnail_note": value["thumbnail_note"]}
    if not isinstance(supplied, dict):
        raise ValueError("Release setting thumbnail must be an object.")
    unknown_thumbnail = set(supplied) - set(THUMBNAIL_DEFAULTS)
    if unknown_thumbnail:
        raise ValueError("Unknown thumbnail setting(s): " + ", ".join(sorted(unknown_thumbnail)))
    thumb = copy.deepcopy(THUMBNAIL_DEFAULTS); thumb.update(supplied)
    thumb["count_mode"] = _enum(thumb["count_mode"], "thumbnail.count_mode", ("fixed", "auto"))
    thumb["count"] = _integer(thumb["count"], "thumbnail.count", 1, 6)
    thumb["auto_min"] = _integer(thumb["auto_min"], "thumbnail.auto_min", 1, 6)
    thumb["auto_max"] = _integer(thumb["auto_max"], "thumbnail.auto_max", 1, 6)
    if thumb["auto_min"] > thumb["auto_max"]:
        raise ValueError("Release setting thumbnail.auto_min cannot exceed auto_max.")
    if thumb["concept_count"] != "auto": thumb["concept_count"] = _integer(thumb["concept_count"], "thumbnail.concept_count", thumb["count"] if thumb["count_mode"] == "fixed" else thumb["auto_min"], 12)
    for name, allowed in {"diversity": ("low", "medium", "high"), "layout_mode": ("auto", *LAYOUTS), "tension": ("restrained", "strong", "dramatic"), "brand_profile": BRAND_PROFILES, "aspect_ratio": ("9:16",), "image_model": ("inherit_episode",), "quality": ("native",), "image_fallback": ("off", "chatgpt_on_gemini_failure"), "text_mode": ("auto", "manual", "candidate_overrides"), "text_renderer": ("local",), "font_id": ("dejavu_sans_bold",), "case_mode": ("auto", "uppercase", "sentence_case"), "text_position": ("auto", "top", "bottom", "left", "right"), "badge_asset_id": ("q_station_mark",), "badge_position": ("top_left", "top_right", "bottom_left", "bottom_right"), "reference_mode": ("master", "timestamps"), "review_preset": ("balanced", "clarity_first", "brand_first"), "export_format": ("png", "jpeg", "both"), "delivery_mode": ("all_final_candidates",)}.items():
        thumb[name] = _enum(thumb[name], f"thumbnail.{name}", tuple(allowed))
    layouts = thumb["allowed_layouts"]
    if not isinstance(layouts, list) or not layouts or any(item not in LAYOUTS for item in layouts):
        raise ValueError("Release setting thumbnail.allowed_layouts must be a non-empty supported layout list.")
    thumb["allowed_layouts"] = list(dict.fromkeys(layouts))
    for name, limit in (("thumbnail_note", 2000), ("must_include", 500), ("must_avoid", 500), ("manual_text", 40)):
        thumb[name] = _text(thumb[name], f"thumbnail.{name}", limit)
    if thumb["text_mode"] == "manual" and not thumb["manual_text"]:
        raise ValueError("Release setting thumbnail.manual_text is required in manual text mode.")
    if not isinstance(thumb["candidate_text_overrides"], dict): raise ValueError("Release setting thumbnail.candidate_text_overrides must be an object.")
    thumb["candidate_text_overrides"] = {str(k): _text(v, "thumbnail.candidate_text_overrides", 40) for k, v in thumb["candidate_text_overrides"].items()}
    for name, low, high in (("max_words", 2, 6), ("max_characters", 8, 40), ("max_lines", 1, 3), ("corrections_per_candidate", 0, 2), ("max_image_generations", 1, 18), ("max_references", 3, 5), ("jpeg_quality", 40, 100)):
        thumb[name] = _integer(thumb[name], f"thumbnail.{name}", low, high)
    desired = thumb["count"] if thumb["count_mode"] == "fixed" else thumb["auto_max"]
    if thumb["max_image_generations"] < desired:
        raise ValueError("Release setting thumbnail.max_image_generations must cover the requested candidate count.")
    for name, low, high in (("outline_width", 0, .04), ("line_spacing", 0, .2), ("text_box_width", .3, .95), ("safe_margin", .02, .2), ("text_min_scale", .03, .12), ("text_max_scale", .04, .2), ("badge_scale", .03, .18)):
        thumb[name] = _number(thumb[name], f"thumbnail.{name}", low, high)
    if thumb["text_min_scale"] > thumb["text_max_scale"]: raise ValueError("Release setting thumbnail text minimum cannot exceed maximum.")
    for name in ("shadow", "text_background", "badge_enabled", "preview_small", "comparison_sheet", "send_previews", "send_comparison_sheet", "send_report_json", "send_raw_artwork", "resend", "review_enabled"):
        if not isinstance(thumb[name], bool): raise ValueError(f"Release setting thumbnail.{name} must be on or off.")
    for name in ("text_fill", "text_outline"):
        if not isinstance(thumb[name], str) or not __import__("re").fullmatch(r"#[0-9A-Fa-f]{6}", thumb[name]): raise ValueError(f"Release setting thumbnail.{name} must be a hex color.")
    timestamps = thumb["reference_timestamps"]
    if not isinstance(timestamps, list) or len(timestamps) > 3 or any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or x < 0 for x in timestamps): raise ValueError("Release setting thumbnail.reference_timestamps must contain up to three non-negative finite times.")
    thumb["reference_timestamps"] = [round(float(x), 3) for x in timestamps]
    if thumb["reference_mode"] == "timestamps" and not timestamps: raise ValueError("Release setting thumbnail.reference_timestamps is required for timestamp references.")
    coords = thumb["coordinates"]
    if coords is not None:
        if not isinstance(coords, dict) or set(coords) != {"x", "y", "width", "height"}: raise ValueError("Release setting thumbnail.coordinates must have x, y, width and height.")
        coords = {k: _number(v, f"thumbnail.coordinates.{k}", 0, 1) for k, v in coords.items()}
        if coords["width"] <= 0 or coords["height"] <= 0 or coords["x"] + coords["width"] > 1 or coords["y"] + coords["height"] > 1: raise ValueError("Release setting thumbnail.coordinates must stay inside the image.")
        thumb["coordinates"] = coords
    result["thumbnail"] = thumb
    # Keep legacy field as a harmless read-only compatibility alias in persisted request files.
    result["thumbnail_note"] = thumb["thumbnail_note"]
    if not any(result[k] for k in ("generate_metadata", "generate_thumbnail", "create_upload_guide", "send_telegram")):
        raise ValueError("Choose at least one Release step.")
    return result

def settings_fingerprint(settings: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(settings, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

def public_schema() -> dict[str, Any]:
    """A compact UI contract; validation remains server-side."""
    return {"schema_version": 2, "defaults": copy.deepcopy(RELEASE_DEFAULTS), "capabilities": {"aspect_ratios": ["9:16"], "layouts": list(LAYOUTS), "brand_profiles": list(BRAND_PROFILES), "fonts": [{"id": "dejavu_sans_bold", "name": "DejaVu Sans Bold", "fallback": "DejaVu Sans"}], "delivery_mode": "all_final_candidates", "max_candidates": 6, "max_concepts": 12}}
