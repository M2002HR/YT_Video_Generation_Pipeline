#!/usr/bin/env python3
"""Per-project episode history and the anti-repetition rules built on it (§35, T5.6).

``projects/<id>/VIDEOS.json`` is the durable record of what each episode already used:
its opening activity and location, its camera pattern, which book template and which world
style. The episode director reads the last few entries so a new episode does not open the
same way as the previous one, and the plan it returns is checked against them.

Legacy registries listed bare directory names. Those entries are preserved and upgraded to
``{"video_id": ...}`` in place, so an old project keeps working without a migration step.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]

#: The traits §35 asks to vary between consecutive episodes.
HISTORY_KEYS = (
    "opening_activity",
    "opening_location",
    "camera_pattern",
    "book_template_id",
    "world_style_id",
)

#: How many previous episodes a trait must stay away from.
DEFAULT_LOOKBACK = 4


class EpisodeHistoryError(ValueError):
    """The registry is not in a shape this module can safely write to."""


def registry_path(project_id: str) -> Path:
    return ROOT / "projects" / str(project_id) / "VIDEOS.json"


def _normalize_entry(entry: Any) -> dict[str, Any]:
    if isinstance(entry, dict):
        return dict(entry)
    return {"video_id": str(entry)}


def load_registry(project_id: str) -> dict[str, Any]:
    path = registry_path(project_id)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("videos"), list):
        raise EpisodeHistoryError(f"{path} does not hold a video list.")
    payload["videos"] = [_normalize_entry(entry) for entry in payload["videos"]]
    return payload


def save_registry(project_id: str, payload: dict[str, Any]) -> Path:
    path = registry_path(project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _sort_key(entry: dict[str, Any]) -> tuple[int, str]:
    identifier = str(entry.get("video_id") or "")
    head = identifier.split("_", 1)[0]
    return (int(head) if head.isdigit() else 10**9, identifier)


def record_traits(project_id: str, video_id: str, traits: dict[str, Any]) -> Path:
    """Upsert one episode's anti-repetition traits. Re-running changes nothing new."""
    payload = load_registry(project_id)
    recorded = {key: traits.get(key) for key in HISTORY_KEYS if traits.get(key) is not None}
    entry = {"video_id": str(video_id), **recorded, "updated_at": datetime.now(timezone.utc).isoformat()}
    videos = [item for item in payload["videos"] if str(item.get("video_id")) != str(video_id)]
    existing = next(
        (item for item in payload["videos"] if str(item.get("video_id")) == str(video_id)), None
    )
    if existing is not None:
        merged = {**existing, **entry}
        # A trait already on record is not dropped by a later partial update.
        entry = merged
    videos.append(entry)
    payload["videos"] = sorted(videos, key=_sort_key)
    return save_registry(project_id, payload)


def recent(project_id: str, limit: int = DEFAULT_LOOKBACK) -> list[dict[str, Any]]:
    """The traits of the last ``limit`` episodes, newest last. Missing registry → ``[]``."""
    try:
        payload = load_registry(project_id)
    except (OSError, ValueError):
        return []
    entries = payload["videos"][-max(0, limit):]
    return [
        {
            "video_id": entry.get("video_id"),
            **{key: entry[key] for key in HISTORY_KEYS if entry.get(key) is not None},
        }
        for entry in entries
    ]


def _comparable(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def used_values(history: Sequence[dict[str, Any]], key: str) -> list[str]:
    """Every non-empty value a trait took in ``history``, in order."""
    values = []
    for entry in history:
        text = _comparable(entry.get(key))
        if text:
            values.append(text)
    return values


def repeated_traits(plan: dict[str, Any], history: Sequence[dict[str, Any]]) -> dict[str, str]:
    """Traits in ``plan`` that a recent episode already used (§35).

    ``book_template_id`` and ``world_style_id`` are deliberately excluded: reusing a book
    template is expected, and world-style reuse is a decision the style director owns.
    """
    varying = ("opening_activity", "opening_location", "camera_pattern")
    repeats: dict[str, str] = {}
    for key in varying:
        value = _comparable(plan.get(key))
        if value and value in used_values(history, key):
            repeats[key] = str(plan.get(key))
    return repeats


def avoidance_note(history: Sequence[dict[str, Any]]) -> str:
    """A short instruction listing what the last episodes used, for the director prompt."""
    if not history:
        return "No previous episodes are on record, so any opening is available."
    lines = [
        f"The last {len(history)} episode(s) used these, and none may be repeated:",
    ]
    for key in ("opening_activity", "opening_location", "camera_pattern"):
        values = used_values(history, key)
        if values:
            lines.append(f"- {key}: {', '.join(sorted(set(values)))}")
    return "\n".join(lines)


def traits_from_plans(
    episode_plan: dict[str, Any],
    world_style_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Collect the recordable traits out of the stage artifacts."""
    style = world_style_plan or {}
    return {
        "opening_activity": episode_plan.get("opening_activity"),
        "opening_location": episode_plan.get("opening_location"),
        "camera_pattern": episode_plan.get("camera_pattern"),
        "book_template_id": episode_plan.get("book_template_id"),
        "world_style_id": style.get("style_id") or style.get("reuse_of"),
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Show a content project's episode history.")
    parser.add_argument("project_id")
    parser.add_argument("--limit", type=int, default=DEFAULT_LOOKBACK)
    args = parser.parse_args()
    history = recent(args.project_id, args.limit)
    print(json.dumps(history, ensure_ascii=False, indent=2))
    print(avoidance_note(history))


if __name__ == "__main__":
    main()
