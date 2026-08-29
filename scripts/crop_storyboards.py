#!/usr/bin/env python3
"""Crop 2x2 storyboard sheets into per-beat images.

Usage:
    python scripts/crop_storyboards.py \
      videos/001_brain_replays_embarrassing_moments

The script:
- reads VISUAL_BEATS.md to determine the expected beat count
- expects raw sheets named sheet_01.png, sheet_02.png, ...
- crops each sheet into top-left, top-right, bottom-left, bottom-right
- writes beat_01.png, beat_02.png, ... to assets/cropped_beats/
- ignores unused quadrants after the final beat
"""

from __future__ import annotations

import argparse
import math
import re
from pathlib import Path

from PIL import Image

BEAT_RE = re.compile(r"^### Beat\s+(\d+)\s*$", re.MULTILINE)


def count_beats(visual_beats_path: Path) -> int:
    if not visual_beats_path.exists():
        raise FileNotFoundError(f"Missing visual beats file: {visual_beats_path}")

    text = visual_beats_path.read_text(encoding="utf-8")
    beats = [int(match) for match in BEAT_RE.findall(text)]
    if not beats:
        raise ValueError(f"No beats found in {visual_beats_path}")

    expected = list(range(1, max(beats) + 1))
    if beats != expected:
        raise ValueError(
            "Beat numbering must be sequential starting at 1. "
            f"Found: {beats}"
        )

    return len(beats)


def crop_sheet(sheet_path: Path) -> list[Image.Image]:
    with Image.open(sheet_path) as image:
        image = image.convert("RGB")
        width, height = image.size

        if width < 2 or height < 2:
            raise ValueError(f"Image is too small to crop: {sheet_path}")

        mid_x = width // 2
        mid_y = height // 2

        boxes = [
            (0, 0, mid_x, mid_y),          # top-left
            (mid_x, 0, width, mid_y),      # top-right
            (0, mid_y, mid_x, height),     # bottom-left
            (mid_x, mid_y, width, height), # bottom-right
        ]

        return [image.crop(box).copy() for box in boxes]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Crop 2x2 storyboard sheets into individual beat images."
    )
    parser.add_argument(
        "video_dir",
        type=Path,
        help="Path to a video directory containing VISUAL_BEATS.md and assets/.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing beat images.",
    )
    args = parser.parse_args()

    video_dir = args.video_dir.resolve()
    visual_beats_path = video_dir / "VISUAL_BEATS.md"
    raw_dir = video_dir / "assets" / "raw_storyboards"
    output_dir = video_dir / "assets" / "cropped_beats"

    beat_count = count_beats(visual_beats_path)
    sheet_count = math.ceil(beat_count / 4)

    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Video directory: {video_dir}")
    print(f"Expected beats: {beat_count}")
    print(f"Expected sheets: {sheet_count}")

    beat_number = 1

    for sheet_number in range(1, sheet_count + 1):
        sheet_path = raw_dir / f"sheet_{sheet_number:02d}.png"
        if not sheet_path.exists():
            raise FileNotFoundError(
                f"Missing storyboard sheet: {sheet_path}\n"
                "Use exact names such as sheet_01.png, sheet_02.png, ..."
            )

        crops = crop_sheet(sheet_path)

        for crop in crops:
            if beat_number > beat_count:
                break

            output_path = output_dir / f"beat_{beat_number:02d}.png"

            if output_path.exists() and not args.overwrite:
                raise FileExistsError(
                    f"Output already exists: {output_path}\n"
                    "Run again with --overwrite if replacement is intended."
                )

            crop.save(output_path, format="PNG", optimize=True)
            print(f"Created {output_path.name}")
            beat_number += 1

    print(f"Done. Created {beat_count} cropped beat images in {output_dir}")


if __name__ == "__main__":
    main()
