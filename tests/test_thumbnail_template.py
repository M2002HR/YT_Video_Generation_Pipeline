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
    assert abs(band["x"] - 0.125) < 1e-9 and abs(band["y"] - 0.05) < 1e-9
    assert band["y"] + band["height"] <= 0.40
    top = text_box_geometry(base_settings(text_position="top"), "contrast_split")
    assert abs(top["y"] - 0.035) < 1e-9 and top["y"] + top["height"] <= 0.40
    bottom = text_box_geometry(base_settings(text_position="bottom"), "character_left")
    assert bottom["y"] + bottom["height"] <= 1.0


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


def test_send_master_video_defaults_on_and_validates() -> None:
    assert normalize_release_settings({})["thumbnail"]["send_master_video"] is True
    assert normalize_release_settings({"thumbnail": {"send_master_video": False}})["thumbnail"]["send_master_video"] is False
    try:
        normalize_release_settings({"thumbnail": {"send_master_video": "yes"}})
    except ValueError:
        pass
    else:
        raise AssertionError("non-bool send_master_video must be rejected")
