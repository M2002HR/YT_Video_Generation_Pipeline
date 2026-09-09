"""Optional developer overlays for inspecting Motion Director evidence and camera paths."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


def _rectangle(box: dict[str, float], width: int, height: int) -> tuple[int, int, int, int]:
    return (
        round((box["x"] - box["w"] / 2) * width), round((box["y"] - box["h"] / 2) * height),
        round((box["x"] + box["w"] / 2) * width), round((box["y"] + box["h"] / 2) * height),
    )


def render_debug_overlays(video_dir: Path, context: dict[str, Any], inventory: dict[str, Any], compiled: dict[str, Any]) -> list[Path]:
    """Write one annotated JPEG per image beat; production frames are untouched."""
    destination = video_dir / "motion" / "debug"
    destination.mkdir(parents=True, exist_ok=True)
    ctx = {str(item["beat_id"]): item for item in context["beats"]}
    inv = {str(item["beat_id"]): item for item in inventory["beats"]}
    outputs: list[Path] = []
    for beat in compiled["beats"]:
        key = str(beat["beat_id"])
        with Image.open(video_dir / ctx[key]["media"]) as source:
            image = source.convert("RGB")
        image.thumbnail((1080, 1080))
        draw = ImageDraw.Draw(image); width, height = image.size
        for target in inv[key]["targets"]:
            draw.rectangle(_rectangle(target["bbox"], width, height), outline=(0, 240, 110), width=max(2, width // 400))
            box = _rectangle(target["bbox"], width, height)
            draw.text((box[0] + 4, max(0, box[1] - 16)), f"{target['target_id']} · {target.get('label', '')}", fill=(0, 240, 110), font=ImageFont.load_default())
        for index, shot in enumerate(beat["micro_shots"]):
            for state_name, color in (("start", (60, 150, 255)), ("end", (255, 180, 40))):
                state = shot["compiled_camera"][state_name]
                draw.rectangle(_rectangle({"x": state["center_x"], "y": state["center_y"], "w": state["width"], "h": state["height"]}, width, height), outline=color, width=max(2, width // 500))
            draw.text((8, 8 + index * 16), f"{shot['shot_id']} {shot['motion']['type']} {shot['start']:.2f}-{shot['end']:.2f}", fill=(255, 255, 255), stroke_width=2, stroke_fill=(0, 0, 0), font=ImageFont.load_default())
        output = destination / f"beat_{int(beat['beat_id']):03d}_targets.jpg"
        image.save(output, quality=88)
        outputs.append(output)
    return outputs
