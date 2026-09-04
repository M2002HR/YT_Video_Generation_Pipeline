#!/usr/bin/env python3
"""Generate the canonical Question Harvest character sheet with Gemini (§13, §47).

There is no synthetic fallback. This sheet is the recurring identity every episode is built
against, so a hand-drawn placeholder would silently redefine the character for every future
video. If Gemini cannot produce it, the right outcome is a non-zero exit and a real retry.

Output:
    projects/question_harvest/visual_presets/001_home_world/character_sheet.png
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from ordak_jobs import Generation, OrdakJobError, OrdakJobs, sha256_file  # noqa: E402

DEFAULT_OUTPUT = (
    ROOT / "projects" / "question_harvest" / "visual_presets" / "001_home_world" / "character_sheet.png"
)

CHARACTER_PROMPT = """Create a canonical character reference sheet for a YouTube educational cartoon.

CHARACTER — tall/slim simplified adult male cartoon, prominent brown/chestnut hair silhouette, beard/moustache/goatee, light moss/green sweater, dark blue overalls, rust/orange boots, simple bold linework, approachable hand-drawn educational cartoon language.

STYLE — clean dark outlines, warm rustic educational animation, simplified geometry, muted natural palette, readable silhouettes, no photorealism, no 3D CGI, no anime, no high-detail semi-realistic.

OUTPUT — exactly one image: 9:16 full-body turnaround (front, 3/4, side) on clean off-white background, centered, consistent proportions, same outfit in all views. No text, no watermark, no grid beyond light guide lines.
"""


def generate(output: Path, *, model: str, timeout: int) -> dict:
    """Ask Gemini for the sheet, download it, and prove it decodes as an image."""
    from PIL import Image

    with OrdakJobs() as jobs:
        jobs.require_ready(["gemini"])
        result = jobs.run(
            CHARACTER_PROMPT,
            provider="gemini",
            mode="image_generate",
            generation=Generation(model=model, quality="best", aspect_ratio="9:16"),
            timeout_seconds=timeout,
            on_log=lambda message: print(f"    [gemini] {message[:160]}", flush=True),
        )
        if not result.output_images:
            raise RuntimeError("Gemini completed the job but produced no image artifact.")
        output.parent.mkdir(parents=True, exist_ok=True)
        partial = output.with_suffix(output.suffix + ".download")
        jobs.download(result.output_images[0], partial)
        partial.replace(output)

    with Image.open(output) as image:
        image.verify()
    with Image.open(output) as image:
        width, height = image.size
    receipt = dict(result.generation_receipt or {})
    return {
        "output": str(output),
        "sha256": sha256_file(output),
        "provider": "gemini",
        "requested_model": model,
        "actual_model_label": receipt.get("actual_model_label"),
        "model_verified": bool(receipt.get("model_verified")),
        "size": f"{width}x{height}",
        "job_id": result.job_id,
        "elapsed_seconds": result.elapsed_seconds,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the canonical character sheet with Gemini")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--model", default="nano_banana_pro")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--force", action="store_true", help="Regenerate even if the file exists")
    args = parser.parse_args()

    if args.output.exists() and not args.force:
        print(f"Exists (use --force to regenerate): {args.output}")
        print(f"SHA256: {sha256_file(args.output)}")
        return 0

    try:
        meta = generate(args.output, model=args.model, timeout=args.timeout)
    except (OrdakJobError, RuntimeError, OSError) as exc:
        print(f"FAILED: the character sheet could not be generated: {exc}", file=sys.stderr, flush=True)
        print(
            "This sheet defines the recurring character, so no placeholder is written. "
            "Fix the Gemini session and run again.",
            file=sys.stderr,
            flush=True,
        )
        return 2
    print(json.dumps(meta, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
