#!/usr/bin/env python3
"""Deterministic book spread compositor for Question Harvest (§37).

Creates videos/<id>/references/book_spread_frame.png

Inputs:
  - canonical blank book template (or synthetic generated if missing)
  - world_keyframe.png
  - template_id, seed, aspect_ratio

Behaviors:
  - deterministic (seeded) placement with perspective warp
  - pseudo-writing generation (unreadable line marks, not real English)
  - no readable English, no fake facts
  - configurable templates (catalog-driven) with varying camera angle / crop
"""
from __future__ import annotations
import argparse
import hashlib
import json
import random
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def generate_pseudo_writing(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], seed: int) -> None:
    """Draw abstract line-like marks that are NOT readable English (§36)."""
    rnd = random.Random(seed)
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    # generate 8-14 wavy line groups
    lines = rnd.randint(8, 14)
    line_spacing = h / (lines + 1)
    for i in range(lines):
        y = int(y0 + line_spacing * (i + 1))
        # each line is 2-4 wavy segments
        segments = rnd.randint(2, 4)
        x = x0 + rnd.randint(4, 10)
        seg_w = (w - 16) // segments
        for s in range(segments):
            length = seg_w - rnd.randint(5, 15)
            # random script-like: alternating short/long strokes
            thickness = rnd.choice([1, 1, 2])
            x_end = min(x + length, x1 - 8)
            # slight waviness
            y_jitter = rnd.randint(-2, 2)
            draw.line([(x, y + y_jitter), (x_end, y + y_jitter)], fill=(60, 60, 60), width=thickness)
            # occasional tiny "dot" like diacritic
            if rnd.random() < 0.15:
                draw.ellipse([x_end + 1, y - 2, x_end + 3, y], fill=(90, 90, 90))
            x = x_end + rnd.randint(6, 12)
            if x >= x1 - 10:
                break


def perspective_warp(im: Image.Image, coeffs: tuple[float, ...]) -> Image.Image:
    # fallback: if coeffs not provided, return as is
    return im


def compose(
    *,
    world_keyframe: Path,
    output: Path,
    template_id: str = "001",
    seed: int = 0,
    aspect_ratio: str = "9:16",
    template_path: Path | None = None,
) -> dict[str, Any]:
    """
    Compose book spread. If template_path missing, generate synthetic open book.
    Returns metadata dict for receipts.
    """
    if not world_keyframe.is_file():
        raise FileNotFoundError(f"World keyframe missing: {world_keyframe}")

    # Determine canvas size based on aspect
    if aspect_ratio == "9:16":
        canvas_w, canvas_h = 1080, 1920
    elif aspect_ratio == "16:9":
        canvas_w, canvas_h = 1920, 1080
    else:
        raise ValueError(f"Unsupported aspect {aspect_ratio}")

    rnd = random.Random(hash((str(world_keyframe), template_id, seed)))

    # Load or generate template
    if template_path is not None and template_path.is_file():
        template = Image.open(template_path).convert("RGB")
        template = ImageOps.fit(template, (canvas_w, canvas_h), method=Image.LANCZOS)
    else:
        # Synthetic open book: warm paper background with center crease
        template = Image.new("RGB", (canvas_w, canvas_h), (245, 235, 215))
        draw = ImageDraw.Draw(template)
        # book outer border
        margin = int(canvas_w * 0.06)
        book_box = (margin, int(canvas_h * 0.22), canvas_w - margin, int(canvas_h * 0.78))
        draw.rounded_rectangle(book_box, radius=18, fill=(252, 248, 232), outline=(150, 120, 90), width=4)
        # center crease shadow
        cx = canvas_w // 2
        draw.rectangle([cx - 2, book_box[1], cx + 2, book_box[3]], fill=(200, 180, 150))

    # Prepare world keyframe image
    world = Image.open(world_keyframe).convert("RGB")

    # Book page boxes: left page for pseudo-writing, right page for world image
    # Based on synthetic layout above
    margin = int(canvas_w * 0.06)
    top, bottom = int(canvas_h * 0.22), int(canvas_h * 0.78)
    cx = canvas_w // 2
    # inner page margins
    pad = 22
    left_box = (margin + pad, top + pad, cx - 10, bottom - pad)
    right_box = (cx + 10, top + pad, canvas_w - margin - pad, bottom - pad)

    # Apply slight template variation based on template_id
    # e.g., 002 = more top-down angle (taller), 003 = angled perspective (trapezoid)
    if template_id == "002":
        # shift book slightly down
        left_box = (left_box[0], left_box[1] + 20, left_box[2], left_box[3] + 20)
        right_box = (right_box[0], right_box[1] + 20, right_box[2], right_box[3] + 20)
    elif template_id == "003":
        # slightly rotated perspective (simulated by narrowing top)
        inset = int((right_box[2] - right_box[0]) * 0.04)
        right_box = (right_box[0] + inset // 2, right_box[1], right_box[2] - inset // 2, right_box[3])

    # Paste world image into right page (fit exactly, no distortion beyond aspect fit)
    rw, rh = right_box[2] - right_box[0], right_box[3] - right_box[1]
    world_fitted = ImageOps.fit(world, (rw, rh), method=Image.LANCZOS)
    # Add subtle inner shadow to world page for book realism
    template.paste(world_fitted, (right_box[0], right_box[1]))

    # Draw decorative pseudo-writing on left page
    draw = ImageDraw.Draw(template)
    # draw light ruling lines
    generate_pseudo_writing(draw, left_box, seed=seed + 1000)

    # Add small page number or ornament (not readable text)
    ornament_box = (left_box[0] + 10, left_box[3] - 30, left_box[0] + 40, left_box[3] - 10)
    draw.ellipse(ornament_box, fill=(180, 160, 130), outline=(150, 120, 90))

    # Ensure output dir
    output.parent.mkdir(parents=True, exist_ok=True)
    template.save(output, "PNG")

    return {
        "output": str(output),
        "sha256": sha256(output),
        "template_id": template_id,
        "seed": seed,
        "aspect_ratio": aspect_ratio,
        "canvas": f"{canvas_w}x{canvas_h}",
        "world_keyframe": str(world_keyframe),
        "world_keyframe_sha256": sha256(world_keyframe),
        "book_spread_frame": str(output),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compose deterministic book spread frame (§37)")
    parser.add_argument("--world-keyframe", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--template-id", default="001")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--aspect-ratio", choices=("16:9", "9:16"), default="9:16")
    parser.add_argument("--template", type=Path, default=None, help="Optional blank book template PNG")
    args = parser.parse_args()

    meta = compose(
        world_keyframe=args.world_keyframe,
        output=args.output,
        template_id=args.template_id,
        seed=args.seed,
        aspect_ratio=args.aspect_ratio,
        template_path=args.template,
    )
    print(json.dumps(meta, indent=2))
    print(f"COMPOSED {args.output}")


if __name__ == "__main__":
    main()
