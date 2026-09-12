"""Shared, deterministic handling for panel-uploaded subtitle fonts."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import struct
import uuid
from pathlib import Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def uploaded_font_source(root: Path, family: str) -> Path | None:
    """Resolve a catalogued upload by family after verifying its content hash."""
    folder = root / "control_panel" / "subtitle_fonts"
    try:
        catalog = json.loads((folder / "catalog.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    for item in catalog.get("fonts", []) if isinstance(catalog, dict) else []:
        if not isinstance(item, dict) or str(item.get("family") or "") != family:
            continue
        font_id = str(item.get("id") or "")
        extension = str(item.get("extension") or "").lower()
        expected = str(item.get("sha256") or "")
        if (
            not re.fullmatch(r"[a-f0-9]{32}", font_id)
            or extension not in {".ttf", ".otf"}
            or not re.fullmatch(r"[a-f0-9]{64}", expected)
        ):
            return None
        for candidate in (folder / "files" / f"{font_id}{extension}", folder / f"{font_id}{extension}"):
            try:
                if candidate.is_file() and _sha256(candidate) == expected:
                    return candidate
            except OSError:
                continue
        return None
    return None


def prepare_uploaded_fonts_dir(root: Path) -> Path | None:
    """Build a font-only libass directory, safely retaining legacy uploads in place."""
    folder = root / "control_panel" / "subtitle_fonts"
    try:
        catalog = json.loads((folder / "catalog.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    entries = catalog.get("fonts") if isinstance(catalog, dict) else None
    if not isinstance(entries, list):
        return None
    destination = folder / "files"
    copied = False
    for item in entries:
        if not isinstance(item, dict):
            continue
        family = str(item.get("family") or "")
        source = uploaded_font_source(root, family)
        if source is None:
            continue
        target = destination / source.name
        try:
            if target.is_file() and _sha256(target) == _sha256(source):
                copied = True
                continue
            destination.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
            try:
                shutil.copyfile(source, temporary)
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
            copied = True
        except OSError:
            continue
    return destination if copied and destination.is_dir() else None


def sfnt_vertical_metrics(path: Path) -> tuple[int, int, int]:
    """Read units-per-em, ascender and descender from a TTF/OTF SFNT safely."""
    data = path.read_bytes()
    if len(data) < 12:
        raise ValueError("Font has no valid SFNT header.")
    table_count = struct.unpack_from(">H", data, 4)[0]
    tables: dict[bytes, tuple[int, int]] = {}
    for index in range(table_count):
        record = 12 + index * 16
        if record + 16 > len(data):
            raise ValueError("Font has a truncated table directory.")
        tag, offset, length = struct.unpack_from(">4s4xII", data, record)
        if offset > len(data) or length > len(data) - offset:
            raise ValueError("Font table points outside the file.")
        tables[tag] = (offset, length)
    if b"head" not in tables or b"hhea" not in tables:
        raise ValueError("Font is missing required horizontal metrics.")
    head, head_length = tables[b"head"]
    hhea, hhea_length = tables[b"hhea"]
    if head_length < 20 or hhea_length < 8:
        raise ValueError("Font has truncated horizontal metrics.")
    units = struct.unpack_from(">H", data, head + 18)[0]
    ascender, descender = struct.unpack_from(">hh", data, hhea + 4)
    metric_height = ascender - descender
    if not 16 <= units <= 16384 or ascender <= 0 or descender > 0 or not 0.5 <= metric_height / units <= 4:
        raise ValueError("Font has unsupported vertical metrics.")
    return units, ascender, descender


def css_equivalent_ass_geometry(
    root: Path, family: str, requested_size: float, margin_v: int,
) -> tuple[float, int]:
    """Compensate libass's ascender/descender normalization for uploaded faces.

    Browsers scale CSS text directly by units-per-em. libass/VSFilter semantics
    normalize the same outline by the font's full ascender-to-descender height.
    Most fonts are close; display fonts can exceed 2x and otherwise render far
    smaller than the Studio preview. The margin correction keeps the visible
    glyph baseline at the same bottom inset as the browser preview.
    """
    source = uploaded_font_source(root, family)
    if source is None:
        return requested_size, margin_v
    units, ascender, descender = sfnt_vertical_metrics(source)
    metric_height = ascender - descender
    effective_size = requested_size * metric_height / units
    descender_in_requested_pixels = requested_size * (-descender) / metric_height
    effective_margin = max(0, round(margin_v - descender_in_requested_pixels))
    return effective_size, effective_margin
