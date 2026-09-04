#!/usr/bin/env python3
"""Publish and reuse world styles through ``world_styles/CATALOG.json``.

The catalog is what makes "reuse an existing style" possible at all: the director is shown
it, the panel lists it, and a later episode can be pinned to one of its entries. Reading it
without ever writing to it would mean every episode invents a style and none of them is ever
offered again, so a newly created style is registered here as soon as its anchor exists.

Registration is idempotent: a style_id already in the catalog is left alone, which keeps a
resumed run from duplicating an entry.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


class WorldStyleCatalogError(RuntimeError):
    """The catalog could not be read or the style could not be published."""


def catalog_path(project_id: str) -> Path:
    return ROOT / "projects" / project_id / "world_styles" / "CATALOG.json"


def load_catalog(project_id: str) -> dict[str, Any]:
    path = catalog_path(project_id)
    if not path.is_file():
        return {"schema_version": 1, "styles": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise WorldStyleCatalogError(f"{path} is not readable JSON: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("styles"), list):
        raise WorldStyleCatalogError(f"{path} has no styles list.")
    return data


def save_catalog(project_id: str, data: dict[str, Any]) -> Path:
    path = catalog_path(project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def style_ids(project_id: str) -> list[str]:
    return [str(entry.get("style_id")) for entry in load_catalog(project_id)["styles"] if entry.get("style_id")]


def _next_directory_name(project_id: str, style_id: str) -> str:
    """``004_ink_wash_vintage`` — the ordinal continues the existing directories."""
    root = catalog_path(project_id).parent
    ordinals = []
    if root.is_dir():
        for child in root.iterdir():
            match = re.match(r"^(\d+)_", child.name)
            if child.is_dir() and match:
                ordinals.append(int(match.group(1)))
    slug = re.sub(r"[^a-z0-9]+", "_", style_id.lower()).strip("_")[:40] or "style"
    return f"{max(ordinals, default=0) + 1:03d}_{slug}"


def display_name_for(style_id: str, plan: dict[str, Any]) -> str:
    explicit = str(plan.get("display_name") or "").strip()
    if explicit:
        return explicit
    return style_id.replace("_", " ").strip().title()


def publish_style(project_id: str, plan: dict[str, Any], anchor: Path) -> dict[str, Any]:
    """Register a newly created style and copy its anchor into the catalog directory.

    Returns the catalog entry, whether it was just written or already present.
    """
    style_id = str(plan.get("style_id") or "").strip()
    if not style_id:
        raise WorldStyleCatalogError("The style plan has no style_id to publish.")
    if not anchor.is_file() or anchor.stat().st_size == 0:
        raise WorldStyleCatalogError(f"The style anchor is missing or empty: {anchor}")

    data = load_catalog(project_id)
    for entry in data["styles"]:
        if str(entry.get("style_id")) == style_id:
            return entry

    directory = _next_directory_name(project_id, style_id)
    target_dir = catalog_path(project_id).parent / directory
    target_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(str(anchor), str(target_dir / "style_anchor.png"))
    (target_dir / "STYLE_PLAN.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    entry = {
        "style_id": style_id,
        "display_name": display_name_for(style_id, plan),
        "medium_family": str(plan.get("medium") or "").strip() or None,
        "texture_family": str(plan.get("texture_family") or "").strip() or None,
        "palette_summary": str(plan.get("palette_summary") or "").strip() or None,
        "status": "ready",
        "path": directory,
        "anchor": f"{directory}/style_anchor.png",
        "usage_count": 1,
    }
    data["styles"].append(entry)
    save_catalog(project_id, data)
    return entry


def record_reuse(project_id: str, style_id: str) -> int:
    """Count one more use of a catalogued style; returns the new count."""
    data = load_catalog(project_id)
    for entry in data["styles"]:
        if str(entry.get("style_id")) == style_id:
            entry["usage_count"] = int(entry.get("usage_count") or 0) + 1
            save_catalog(project_id, data)
            return int(entry["usage_count"])
    raise WorldStyleCatalogError(f"Cannot record reuse of unknown style {style_id!r}.")
