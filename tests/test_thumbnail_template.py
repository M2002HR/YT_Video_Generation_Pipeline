"""Regressions: predictable thumbnail template with a reserved headline band."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from release_settings import THUMBNAIL_DEFAULTS, normalize_release_settings
from thumbnail_compositor import text_box_geometry
from thumbnail_runtime import LAYOUT_TEMPLATES, artwork_prompt, final_review_prompt, local_plan


def base_settings(**overrides):
    settings = dict(THUMBNAIL_DEFAULTS)
    settings["candidate_text_overrides"] = {}
    settings.update(overrides)
    return settings


def sample_character():
    return {
        "display_name": "Curious Sea Captain",
        "appearance": "big-hatted cartoon captain",
        "behavior": "observes first",
        "negative_constraints": "no villain",
    }


def sample_metadata():
    return {"title": "Same Meals Can Fall Short #shorts", "thumbnail_overlay_text": "Same Meals Fall Short"}


def sample_context():
    return {"narration": "Calories give your body energy. Health also needs vitamins."}


def test_geometry_is_top_band_for_character_layouts() -> None:
    band = text_box_geometry(base_settings(), "character_left")
    assert band["width"] == 0.82 and band["height"] == 0.32
    assert abs(band["x"] - 0.09) < 1e-9 and abs(band["y"] - 0.05) < 1e-9
    assert band["y"] + band["height"] <= 0.40
    top = text_box_geometry(base_settings(text_position="top"), "contrast_split")
    assert abs(top["y"] - 0.035) < 1e-9 and top["y"] + top["height"] <= 0.40
    bottom = text_box_geometry(base_settings(text_position="bottom"), "character_left")
    assert bottom["y"] + bottom["height"] <= 1.0
    # Headline box is canvas-centered for every layout (stable, not side-anchored).
    for layout in ("character_left", "character_right", "contrast_split", "discovery_focus"):
        box = text_box_geometry(base_settings(), layout)
        assert abs((box["x"] + box["width"] / 2) - 0.5) < 1e-9
    left = text_box_geometry(base_settings(text_position="left"), "character_left")
    assert abs(left["x"] - 0.055) < 1e-9


def test_every_layout_has_a_placement_template() -> None:
    for layout in ("character_left", "character_right", "contrast_split", "discovery_focus"):
        template = LAYOUT_TEMPLATES[layout]
        assert template["host"] and template["scene"]


def test_plan_carries_band_and_template_per_layout() -> None:
    settings = base_settings(count=4)
    plans = local_plan(sample_metadata(), sample_context(), settings, sample_character())
    assert [plan["layout_id"] for plan in plans] == [
        "character_left", "character_right", "contrast_split", "discovery_focus"]
    for plan in plans:
        assert "COMPOSITION TEMPLATE" in plan["composition_template"]
        assert plan["layout_id"] in plan["composition_template"]
        assert "text_region" in plan and "frame fractions" in plan["text_region"]


def test_artwork_prompt_reserves_band_and_keeps_head_below() -> None:
    settings = base_settings(count=1)
    plan = local_plan(sample_metadata(), sample_context(), settings, sample_character())[0]
    prompt = artwork_prompt(plan, sample_character(), [], "")
    assert "COMPOSITION TEMPLATE (character_left)" in prompt
    assert "y 0.00-0.50" in prompt
    assert "BELOW" in prompt
    assert "no face, eyes, mouth" in prompt
    assert "artificially emptied" in prompt


def test_final_review_rejects_headline_over_face() -> None:
    prompt = final_review_prompt(
        {"headline": "Same Meals Fall Short", "evidence_anchor": "meals"},
        {"title": "Same Meals Can Fall Short #shorts"},
    )
    assert "overlapping the host's face" in prompt


def test_rendered_lines_share_one_ink_center(tmp_path) -> None:
    """Unequal line widths must still land on a single canvas center (039 case)."""
    from PIL import Image

    from thumbnail_compositor import compose

    artwork = tmp_path / "artwork.png"
    Image.new("RGB", (1080, 1920), (90, 110, 140)).save(artwork)
    out = tmp_path / "final.png"
    compose(artwork, out, "Can This Diet Last?", base_settings(), "character_left")
    image = Image.open(out).convert("RGB")
    width, height = image.size
    pixels = image.load()
    rows: dict[int, list[int]] = {}
    for y in range(int(height * 0.45)):
        xs = [x for x in range(width) if all(v > 195 for v in pixels[x, y])]
        if len(xs) > width * 0.02:
            rows[y] = xs
    lines: list[list[int]] = []
    current: list[int] | None = None
    previous: int | None = None
    for y in sorted(rows):
        if previous is not None and y - previous > 14:
            assert current is not None
            lines.append(current)
            current = []
        if current is None:
            current = []
        current.append(y)
        previous = y
    assert current
    lines.append(current)
    assert len(lines) == 3
    for line_rows in lines:
        xs = [x for y in line_rows for x in rows[y]]
        center = (min(xs) + max(xs)) / 2
        assert abs(center - width / 2) <= width * 0.02, (center, width / 2)


def test_send_master_video_defaults_on_and_validates() -> None:
    assert normalize_release_settings({})["thumbnail"]["send_master_video"] is True
    assert normalize_release_settings({"thumbnail": {"send_master_video": False}})["thumbnail"]["send_master_video"] is False
    try:
        normalize_release_settings({"thumbnail": {"send_master_video": "yes"}})
    except ValueError:
        pass
    else:
        raise AssertionError("non-bool send_master_video must be rejected")
