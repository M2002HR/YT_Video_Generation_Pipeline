"""Deterministic final-thumbnail compositor.

Gemini generates artwork only.  This module owns every readable glyph, the brand mark,
and the normalized layout record so a final PNG is reproducible without a provider call.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageOps

FONT_CANDIDATES = (
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    Path("/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"),
)

def resolve_font(font_id: str = "dejavu_sans_bold") -> tuple[Path, str]:
    if font_id != "dejavu_sans_bold":
        raise ValueError("Unknown thumbnail font.")
    for path in FONT_CANDIDATES:
        if path.is_file():
            return path, hashlib.sha256(path.read_bytes()).hexdigest()
    raise RuntimeError("Thumbnail font DejaVu Sans Bold is not installed; install a licensed font before Release.")

def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width: int, stroke: int, max_lines: int) -> list[str]:
    words = text.split()
    lines: list[str] = []; current = ""
    for word in words:
        trial = word if not current else current + " " + word
        box = draw.textbbox((0, 0), trial, font=font, stroke_width=stroke)
        if not current and box[2] - box[0] > width:
            raise ValueError("Thumbnail text contains a word that cannot fit the selected box.")
        if current and box[2] - box[0] > width:
            lines.append(current); current = word
        else: current = trial
    if current: lines.append(current)
    if len(lines) > max_lines:
        raise ValueError("Thumbnail text does not fit the selected line limit; revise it explicitly.")
    return lines

def compose(artwork: Path, output: Path, text: str, settings: dict[str, Any], layout_id: str) -> dict[str, Any]:
    """Render text and a small channel mark. Returns exact bounds used for QC."""
    font_path, font_hash = resolve_font(settings["font_id"])
    with Image.open(artwork) as opened:
        image = opened.convert("RGBA")
    width, height = image.size
    if width < 720 or height < 1280:
        raise RuntimeError("Thumbnail artwork is below the minimum usable native size.")
    draw = ImageDraw.Draw(image)
    if settings["case_mode"] == "uppercase": text = text.upper()
    elif settings["case_mode"] == "sentence_case": text = text[:1].upper() + text[1:]
    margin = int(width * settings["safe_margin"])
    coords = settings.get("coordinates")
    if coords:
        x, y, box_w, box_h = (int(coords["x"] * width), int(coords["y"] * height), int(coords["width"] * width), int(coords["height"] * height))
    else:
        box_w = int(width * settings["text_box_width"]); box_h = int(height * .32)
        x = margin if layout_id in {"character_right", "discovery_focus"} else width - margin - box_w
        if settings["text_position"] == "top": y = margin
        elif settings["text_position"] == "bottom": y = height - margin - box_h
        else: y = int(height * .07) if layout_id in {"character_left", "character_right"} else int(height * .60)
        if settings["text_position"] == "left": x = margin
        if settings["text_position"] == "right": x = width - margin - box_w
    if min(x, y, box_w, box_h) < 0 or x + box_w > width or y + box_h > height:
        raise ValueError("Thumbnail text coordinates leave the image bounds.")
    stroke = max(1, int(width * settings["outline_width"]))
    chosen: tuple[ImageFont.FreeTypeFont, list[str], int] | None = None
    for point in range(int(width * settings["text_max_scale"]), int(width * settings["text_min_scale"]) - 1, -2):
        font = ImageFont.truetype(str(font_path), point)
        # A large preferred font may need three lines; keep trying smaller sizes before
        # declaring the operator's text impossible.  The old immediate exception made
        # ordinary four-word headlines fail even though they fit at the readable floor.
        try:
            lines = _wrap(draw, text, font, box_w - stroke * 4, stroke, settings["max_lines"])
        except ValueError:
            continue
        boxes = [draw.textbbox((0, 0), line, font=font, stroke_width=stroke) for line in lines]
        line_h = max(box[3] - box[1] for box in boxes)
        total = line_h * len(lines) + int(point * settings["line_spacing"]) * max(0, len(lines) - 1) + stroke * 2
        if total <= box_h:
            chosen = font, lines, line_h; break
    if not chosen: raise ValueError("Thumbnail text cannot fit without dropping below the readable size.")
    font, lines, line_h = chosen
    spacing = int(font.size * settings["line_spacing"])
    text_h = line_h * len(lines) + spacing * max(0, len(lines) - 1)
    top = y + max(0, (box_h - text_h) // 2)
    if settings["text_background"]:
        draw.rounded_rectangle((x - stroke * 2, top - stroke * 2, x + box_w + stroke * 2, top + text_h + stroke * 2), radius=stroke * 3, fill=(0, 0, 0, 150))
    bounds = [width, height, 0, 0]
    for index, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font, stroke_width=stroke)
        line_w = bbox[2] - bbox[0]
        tx = x + max(0, (box_w - line_w) // 2); ty = top + index * (line_h + spacing)
        if settings["shadow"]: draw.text((tx + stroke, ty + stroke), line, font=font, fill=(0, 0, 0, 210), stroke_width=stroke, stroke_fill=(0, 0, 0, 210))
        draw.text((tx, ty), line, font=font, fill=settings["text_fill"], stroke_width=stroke, stroke_fill=settings["text_outline"])
        rendered = draw.textbbox((tx, ty), line, font=font, stroke_width=stroke)
        bounds = [min(bounds[0], rendered[0]), min(bounds[1], rendered[1]), max(bounds[2], rendered[2]), max(bounds[3], rendered[3])]
    if settings["badge_enabled"]:
        size = max(20, int(min(width, height) * settings["badge_scale"])); pad = margin
        bx = pad if "left" in settings["badge_position"] else width - pad - size
        by = pad if "top" in settings["badge_position"] else height - pad - size
        draw.rounded_rectangle((bx, by, bx + size, by + size), radius=max(4, size // 6), fill=(16, 24, 39, 220), outline=(255, 209, 102, 255), width=max(1, size // 18))
        draw.text((bx + size // 2, by + size // 2), "Q", anchor="mm", font=ImageFont.truetype(str(font_path), max(12, size * 2 // 3)), fill="white")
    output.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(output, "PNG", optimize=True)
    preview = output.with_name("preview_small.jpg")
    ImageOps.contain(image.convert("RGB"), (270, 480)).save(preview, "JPEG", quality=86)
    return {"font_id": settings["font_id"], "font_sha256": font_hash, "text": text, "text_bounds": {"x": bounds[0], "y": bounds[1], "width": bounds[2]-bounds[0], "height": bounds[3]-bounds[1]}, "canvas": {"width": width, "height": height}, "layout_id": layout_id, "preview": preview.name}

def comparison_sheet(candidates: list[dict[str, Any]], output: Path) -> None:
    tiles = []
    for item in candidates:
        path = Path(item["final_path"])
        with Image.open(path) as image: tiles.append(ImageOps.contain(image.convert("RGB"), (270, 480)))
    if not tiles: return
    sheet = Image.new("RGB", (270 * len(tiles), 520), "#111827")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.truetype(str(resolve_font()[0]), 20)
    for index, tile in enumerate(tiles):
        sheet.paste(tile, (index * 270, 0)); draw.text((index * 270 + 10, 486), str(candidates[index]["candidate_id"]), font=font, fill="white")
    output.parent.mkdir(parents=True, exist_ok=True); sheet.save(output, "JPEG", quality=88)
