"""Content-agnostic context construction for Motion Director V2."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from PIL import Image


def load_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {} if default is None else default


def image_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def timed_words(video_dir: Path) -> list[dict[str, Any]]:
    payload = load_json(video_dir / "timing" / "WORD_TIMINGS.json", {})
    words: list[dict[str, Any]] = []
    for index, item in enumerate(payload.get("words") or []):
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or item.get("token") or "").strip()
        try:
            start, end = float(item["start"]), float(item["end"])
        except (KeyError, TypeError, ValueError):
            continue
        words.append({"word_id": f"w_{index + 1:04d}", "text": text, "start": round(start, 3), "end": round(end, 3)})
    return words


def subtitle_safe_region(profile: dict[str, Any], *, width: int, height: int) -> dict[str, float]:
    subtitles = profile.get("subtitles") if isinstance(profile.get("subtitles"), dict) else {}
    if not subtitles.get("enabled", True):
        return {"enabled": False, "top": 1.0, "bottom": 1.0}
    font = max(8, int(subtitles.get("font_size", 56)))
    lines = max(1, int(subtitles.get("max_lines", 2)))
    outline = max(0.0, float(subtitles.get("outline", 3)))
    explicit = subtitles.get("margin_v")
    margin = int(explicit) if explicit is not None else max(48, round(height * (.075 if height >= width else .08)))
    block = font * lines * 1.28 + outline * 4
    top = max(.50, min(.95, 1.0 - (margin + block) / max(1, height)))
    return {"enabled": True, "top": round(top, 4), "bottom": 1.0, "margin_pixels": margin, "estimated_height_pixels": round(block)}


def visual_plan_by_id(video_dir: Path) -> dict[str, dict[str, Any]]:
    payload = load_json(video_dir / "creative" / "VISUAL_PLAN.json", {})
    return {str(item.get("beat_id")): item for item in payload.get("beats") or [] if isinstance(item, dict)}


def build_motion_context(video_dir: Path, timeline: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    profile_path = video_dir / str(timeline.get("render_profile") or "render/RENDER_PROFILE.json")
    profile = load_json(profile_path, {})
    resolution = timeline.get("resolution") or profile.get("resolution") or {}
    width, height = int(resolution.get("width", 1080)), int(resolution.get("height", 1920))
    words = timed_words(video_dir)
    visual = visual_plan_by_id(video_dir)
    beats: list[dict[str, Any]] = []
    for index, source in enumerate(timeline.get("beats") or []):
        start, end = float(source["start"]), float(source["end"])
        # Assign by midpoint so a real Ajil word straddling a beat boundary is never
        # silently lost from both neighboring contexts.
        beat_words = [word for word in words if start - .025 <= (word["start"] + word["end"]) / 2 < end + .025]
        media_value = source.get("image") or source.get("source")
        media_path = video_dir / str(media_value) if media_value else None
        entry = {
            "index": index,
            "beat_id": source.get("beat_id"),
            "media_type": str(source.get("media_type") or "image"),
            "start": start,
            "end": end,
            "duration": round(end - start, 3),
            "narration": str(source.get("narration") or "").strip(),
            "spoken_words": beat_words,
            "spoken_text_in_slot": " ".join(word["text"] for word in beat_words),
            "speech_start": source.get("speech_start"),
            "speech_end": source.get("speech_end"),
            "visual_description": visual.get(str(source.get("beat_id")), {}),
            "media": str(media_value or ""),
        }
        if media_path and media_path.is_file():
            entry["media_sha256"] = image_sha256(media_path)
            if entry["media_type"] == "image":
                try:
                    with Image.open(media_path) as image:
                        entry["media_width"], entry["media_height"] = image.size
                except OSError:
                    pass
        beats.append(entry)
    script = (video_dir / "SCRIPT_FINAL.md").read_text(encoding="utf-8") if (video_dir / "SCRIPT_FINAL.md").is_file() else ""
    visual_md = (video_dir / "VISUAL_BEATS.md").read_text(encoding="utf-8") if (video_dir / "VISUAL_BEATS.md").is_file() else ""
    return {
        "schema_version": 2,
        "episode": {
            "video_id": video_dir.name,
            "duration": float(timeline["duration"]),
            "aspect_ratio": str(profile.get("aspect_ratio") or f"{width}:{height}"),
            "width": width,
            "height": height,
            "fps": int(timeline.get("fps", profile.get("fps", 30))),
            "script": script[:18000],
            "visual_plan_markdown": visual_md[:18000],
            "subtitle_safe_region": subtitle_safe_region(profile, width=width, height=height),
            "settings": settings,
        },
        "words": words,
        "beats": beats,
    }


def compact_neighbor(beat: dict[str, Any] | None) -> dict[str, Any] | None:
    if beat is None:
        return None
    return {key: beat.get(key) for key in ("beat_id", "media_type", "start", "end", "narration", "spoken_text_in_slot", "visual_description")}


def slug_target_label(value: str) -> str:
    clean = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return clean[:42] or "subject"
