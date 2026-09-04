#!/usr/bin/env python3
"""Deterministic book spread compositor for Question Harvest (§37).

Writes ``videos/<id>/references/book_spread_frame.png`` — the Start frame Clip B opens
on, and the image the camera pushes into.

Two properties matter and both are enforced here rather than hoped for:

* **The right page is the episode's world keyframe and nothing else.**  The only
  transform applied is a centred, deterministic fit into the page box, and the exact
  box and transform are written into the returned metadata so a receipt can prove it.
* **Nothing readable is ever drawn.**  The left page carries abstract stroke marks.  No
  font is loaded and no glyph is rendered anywhere in this module, so the spread cannot
  invent words or facts.

There is no synthetic book: a missing template is a hard failure, because a drawn
stand-in would put media in the pipeline that no canonical asset backs (§4).
"""
from __future__ import annotations
import argparse
import hashlib
import json
import random
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageOps

ROOT = Path(__file__).resolve().parents[1]

#: Page geometry as fractions of the canvas, per template camera angle.  ``001`` is the
#: straight-on spread; the others shift or inset the pages to match their template art.
PAGE_LAYOUTS: dict[str, dict[str, float]] = {
    "001": {"margin": 0.06, "top": 0.22, "bottom": 0.78, "pad": 0.0204, "y_shift": 0.0, "right_inset": 0.0},
    "002": {"margin": 0.06, "top": 0.22, "bottom": 0.78, "pad": 0.0204, "y_shift": 0.0104, "right_inset": 0.0},
    "003": {"margin": 0.06, "top": 0.22, "bottom": 0.78, "pad": 0.0204, "y_shift": 0.0, "right_inset": 0.04},
}

CANVAS_SIZES = {"9:16": (1080, 1920), "16:9": (1920, 1080)}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def generate_pseudo_writing(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], seed: int) -> None:
    """Draw abstract line-like marks that are not readable in any language (§36).

    Strokes and dots only — never a glyph — so the page can never be read as a claim.
    """
    rnd = random.Random(seed)
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    lines = rnd.randint(8, 14)
    line_spacing = h / (lines + 1)
    for i in range(lines):
        y = int(y0 + line_spacing * (i + 1))
        segments = rnd.randint(2, 4)
        x = x0 + rnd.randint(4, 10)
        seg_w = (w - 16) // max(segments, 1)
        for _ in range(segments):
            length = seg_w - rnd.randint(5, 15)
            thickness = rnd.choice([1, 1, 2])
            x_end = min(x + length, x1 - 8)
            y_jitter = rnd.randint(-2, 2)
            draw.line([(x, y + y_jitter), (x_end, y + y_jitter)], fill=(60, 60, 60), width=thickness)
            if rnd.random() < 0.15:
                draw.ellipse([x_end + 1, y - 2, x_end + 3, y], fill=(90, 90, 90))
            x = x_end + rnd.randint(6, 12)
            if x >= x1 - 10:
                break


def page_boxes(
    template_id: str,
    canvas_w: int,
    canvas_h: int,
    *,
    layout: dict[str, float] | None = None,
) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int]]:
    """``(left_box, right_box)`` in pixels for a template, deterministically."""
    spec = dict(layout or PAGE_LAYOUTS.get(template_id) or PAGE_LAYOUTS["001"])
    margin = int(canvas_w * spec["margin"])
    pad = int(canvas_w * spec["pad"])
    top = int(canvas_h * spec["top"])
    bottom = int(canvas_h * spec["bottom"])
    shift = int(canvas_h * spec["y_shift"])
    centre = canvas_w // 2
    gutter = 10
    left = (margin + pad, top + pad + shift, centre - gutter, bottom - pad + shift)
    right = (centre + gutter, top + pad + shift, canvas_w - margin - pad, bottom - pad + shift)
    inset = int((right[2] - right[0]) * spec["right_inset"])
    if inset:
        right = (right[0] + inset // 2, right[1], right[2] - inset // 2, right[3])
    return left, right


def fit_world_into_page(world: Image.Image, box: tuple[int, int, int, int]) -> Image.Image:
    """Centred, deterministic fit of the world keyframe into the page box.

    ``ImageOps.fit`` is the whole transform: no filtering, no recolouring, no overlay.
    The page therefore shows the keyframe itself, which is what lets Clip B's push-in
    land in the same world the body images were generated in.
    """
    width, height = box[2] - box[0], box[3] - box[1]
    return ImageOps.fit(world, (width, height), method=Image.LANCZOS, centering=(0.5, 0.5))


def compose(
    *,
    world_keyframe: Path,
    output: Path,
    template_id: str = "001",
    seed: int = 0,
    aspect_ratio: str = "9:16",
    template_path: Path | None = None,
) -> dict[str, Any]:
    """Composite the world keyframe onto a canonical blank book template.

    Returns the metadata a receipt needs to prove where the right page came from.
    """
    world_keyframe = Path(world_keyframe)
    if not world_keyframe.is_file():
        raise FileNotFoundError(f"World keyframe missing: {world_keyframe}")
    if template_path is None or not Path(template_path).is_file():
        raise FileNotFoundError(
            "A canonical blank book template is required; the compositor never draws a "
            f"stand-in book. Missing: {template_path}"
        )
    template_path = Path(template_path)
    if aspect_ratio not in CANVAS_SIZES:
        raise ValueError(f"Unsupported aspect {aspect_ratio}")
    canvas_w, canvas_h = CANVAS_SIZES[aspect_ratio]

    template = Image.open(template_path).convert("RGB")
    template = ImageOps.fit(template, (canvas_w, canvas_h), method=Image.LANCZOS)

    world = Image.open(world_keyframe).convert("RGB")
    left_box, right_box = page_boxes(template_id, canvas_w, canvas_h)
    world_fitted = fit_world_into_page(world, right_box)
    template.paste(world_fitted, (right_box[0], right_box[1]))

    draw = ImageDraw.Draw(template)
    generate_pseudo_writing(draw, left_box, seed=seed + 1000)
    ornament_box = (left_box[0] + 10, left_box[3] - 30, left_box[0] + 40, left_box[3] - 10)
    draw.ellipse(ornament_box, fill=(180, 160, 130), outline=(150, 120, 90))

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    template.save(output, "PNG")

    page_w, page_h = right_box[2] - right_box[0], right_box[3] - right_box[1]
    kept = min(world.width / world.height, page_w / page_h) / max(
        world.width / world.height, page_w / page_h
    )
    return {
        "output": str(output),
        "sha256": sha256(output),
        "template_id": template_id,
        "template_path": str(template_path),
        "template_sha256": sha256(template_path),
        "seed": seed,
        "aspect_ratio": aspect_ratio,
        "canvas": f"{canvas_w}x{canvas_h}",
        "world_keyframe": str(world_keyframe),
        "world_keyframe_sha256": sha256(world_keyframe),
        "world_keyframe_dimensions": [world.width, world.height],
        "left_page_box": list(left_box),
        "right_page_box": list(right_box),
        "world_transform": "ImageOps.fit centering=(0.5,0.5) LANCZOS",
        "world_kept_fraction": round(kept, 4),
        "readable_text_drawn": False,
        "book_spread_frame": str(output),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compose deterministic book spread frame (§37)")
    parser.add_argument("--world-keyframe", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--template-id", default="001")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--aspect-ratio", choices=("16:9", "9:16"), default="9:16")
    parser.add_argument("--template", type=Path, required=True, help="Canonical blank book template PNG")
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
