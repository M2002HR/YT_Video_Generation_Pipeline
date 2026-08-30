#!/usr/bin/env python3
"""Run one real three-beat ChatGPT/Ordak continuity smoke chain.

This is deliberately a small parent-owned acceptance runner: every image is
generated through the local Ordak HTTP API and each following beat references
only accepted prior output plus the two canonical anchors.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path

from dotenv import load_dotenv
from PIL import Image

from run_visual_pipeline import OrdakClient, ROOT, Settings


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inspect(path: Path, previous: str | None) -> dict[str, object]:
    if not path.is_file() or path.stat().st_size < 10_000:
        raise RuntimeError(f"Generated smoke artifact is missing or too small: {path}")
    with Image.open(path) as image:
        image.verify()
    with Image.open(path) as image:
        width, height = image.size
    sha = digest(path)
    if not 1.60 <= width / height <= 1.90:
        raise RuntimeError(f"Generated smoke artifact is not landscape: {width}x{height}")
    if previous and sha == previous:
        raise RuntimeError("A continuity beat duplicated its previous accepted image.")
    return {"path": str(path), "bytes": path.stat().st_size, "width": width, "height": height, "sha256": sha}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    load_dotenv(ROOT / os.getenv("YT_ENV_FILE", ".env"), override=False)
    settings = Settings(
        os.getenv("YT_ORDAK_BASE_URL", "http://127.0.0.1:8000").rstrip("/"),
        int(os.getenv("YT_ORDAK_JOB_WAIT_TIMEOUT_SECONDS", "900")),
        float(os.getenv("YT_ORDAK_JOB_POLL_INTERVAL_SECONDS", "2")),
    )
    destination = ROOT / "videos" / "_ordak_continuity_smokes" / args.run_id
    destination.mkdir(parents=True, exist_ok=True)
    preset = ROOT / "visual_presets" / "001_cinematic_storybook_green_hoodie"
    style, character = preset / "style_anchor.png", preset / "character_anchor.png"
    prompts = [
        "Create exactly one standalone cinematic storybook 16:9 landscape image. The recognizable green-hoodie protagonist waits at a quiet lakeside dawn. Use the first reference for style and the second for character. No text, no collage, no grid.",
        "Create exactly one standalone cinematic storybook 16:9 landscape image. Continue the same green-hoodie protagonist walking from the lakeside toward a sunlit forest path. Use the first reference for style, second for character, and third only for immediate scene continuity. No text, no collage, no grid.",
        "Create exactly one standalone cinematic storybook 16:9 landscape image. Continue the same green-hoodie protagonist arriving at a small wooden bridge in the forest, with a visibly new composition. Use the first reference for style, second for character, and third only for immediate scene continuity. No text, no collage, no grid.",
    ]
    client = OrdakClient(settings)
    previous_path: Path | None = None
    previous_sha: str | None = None
    records: list[dict[str, object]] = []
    try:
        client.readiness()
        for index, prompt in enumerate(prompts, start=1):
            references = [style, character] + ([previous_path] if previous_path else [])
            job = client.image(prompt, references, beat_id=index)
            artifacts = list(job.get("output_images") or [])
            if len(artifacts) != 1:
                raise RuntimeError(f"Smoke beat {index} returned {len(artifacts)} artifacts, expected one.")
            target = destination / f"beat_{index:03d}.png"
            temporary = target.with_suffix(".download")
            client.download(str(artifacts[0]), temporary)
            shutil.move(temporary, target)
            metadata = inspect(target, previous_sha)
            records.append({"beat": index, "job_id": job["job_id"], "references": [str(item.relative_to(ROOT)) for item in references], **metadata})
            previous_path, previous_sha = target, str(metadata["sha256"])
    finally:
        client.close()
    report = {"passed": len(records) == 3, "run_id": args.run_id, "beats": records}
    (destination / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
