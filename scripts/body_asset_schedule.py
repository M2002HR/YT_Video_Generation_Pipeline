"""Independent body-image scheduling for Q Station episodes.

Narration alignment remains semantic (one row per spoken unit), while this module
creates the denser physical image manifest used by generation and the timeline.
Keeping those concerns separate prevents an image-density change from corrupting
Ajil's measured speech boundaries.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any


SCHEMA_VERSION = 1
DEFAULT_TARGET_IMAGES = 30
MAX_TARGET_IMAGES = 120

_ROLES = (
    "establishing context",
    "causal mechanism detail",
    "subject/action close-up",
    "contrast or consequence",
    "spatial context shift",
    "symbolic explanatory detail",
)


def target_image_count(body_seconds: float, semantic_count: int, configured: Any = None) -> int:
    """Return an explicit, bounded operational target — never an artistic ceiling."""
    try:
        requested = int(configured)
    except (TypeError, ValueError):
        requested = 0
    if requested:
        if not semantic_count <= requested <= MAX_TARGET_IMAGES:
            raise ValueError(
                f"body_image_target must be between {semantic_count} and {MAX_TARGET_IMAGES}."
            )
        return requested
    # About one new source image per second, with a 30-image baseline for short-form.
    return min(MAX_TARGET_IMAGES, max(DEFAULT_TARGET_IMAGES, semantic_count, math.ceil(body_seconds)))


def _allocation(beats: list[dict[str, Any]], target: int) -> list[int]:
    """Give every spoken unit an image, then distribute the remainder by text weight."""
    base = [1 for _ in beats]
    remaining = target - len(base)
    if remaining <= 0:
        return base
    weights = [max(1, len(str(beat.get("narration_slice") or "").split())) for beat in beats]
    total = sum(weights)
    shares = [remaining * weight / total for weight in weights]
    extras = [math.floor(share) for share in shares]
    for index in sorted(range(len(beats)), key=lambda item: (shares[item] - extras[item], weights[item]), reverse=True)[:remaining - sum(extras)]:
        extras[index] += 1
    return [item + extra for item, extra in zip(base, extras)]


def build_schedule(visual_plan: dict[str, Any], body_seconds: float, configured_target: Any = None) -> dict[str, Any]:
    beats = [dict(item) for item in (visual_plan.get("beats") or []) if isinstance(item, dict)]
    ids = [item.get("beat_id") for item in beats]
    if not beats or ids != list(range(1, len(beats) + 1)):
        raise ValueError("A contiguous semantic VISUAL_PLAN is required before scheduling body assets.")
    target = target_image_count(body_seconds, len(beats), configured_target)
    allocations = _allocation(beats, target)
    assets: list[dict[str, Any]] = []
    asset_id = 1
    for semantic, count in zip(beats, allocations):
        for local_index in range(count):
            role = _ROLES[local_index % len(_ROLES)]
            variant = (
                f"Independent visual asset {local_index + 1} of {count} for this spoken unit: "
                f"{role}. Create a genuinely new composition; do not duplicate or merely crop another asset."
            )
            assets.append({
                **semantic,
                "beat_id": asset_id,
                "asset_id": f"body_asset_{asset_id:03d}",
                "semantic_beat_id": int(semantic["beat_id"]),
                "asset_index_in_semantic_beat": local_index + 1,
                "assets_in_semantic_beat": count,
                "asset_role": role,
                "asset_instruction": variant,
                "visual": f"{str(semantic.get('visual') or '').strip()}\n\n{variant}",
            })
            asset_id += 1
    return {
        "schema_version": SCHEMA_VERSION,
        "semantic_beat_count": len(beats),
        "target_image_count": target,
        "assets": assets,
    }


def valid_schedule(payload: Any, visual_plan: dict[str, Any]) -> bool:
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        return False
    semantic = [item for item in (visual_plan.get("beats") or []) if isinstance(item, dict)]
    assets = payload.get("assets")
    if not isinstance(assets, list) or not semantic or payload.get("semantic_beat_count") != len(semantic):
        return False
    if [item.get("beat_id") for item in assets if isinstance(item, dict)] != list(range(1, len(assets) + 1)):
        return False
    expected_slices = {int(item["beat_id"]): str(item.get("narration_slice") or "").strip() for item in semantic}
    grouped: dict[int, int] = defaultdict(int)
    for item in assets:
        if not isinstance(item, dict):
            return False
        try:
            semantic_id = int(item["semantic_beat_id"])
        except (KeyError, TypeError, ValueError):
            return False
        if expected_slices.get(semantic_id) != str(item.get("narration_slice") or "").strip():
            return False
        grouped[semantic_id] += 1
    return set(grouped) == set(expected_slices) and len(assets) == payload.get("target_image_count")


def assets_for(project, visual_plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Read the durable schedule, safely falling back for historical completed runs."""
    import json

    path = project / "creative" / "BODY_ASSET_SCHEDULE.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        payload = None
    if valid_schedule(payload, visual_plan):
        return [dict(item) for item in payload["assets"]]
    return [dict(item) for item in (visual_plan.get("beats") or []) if isinstance(item, dict)]
