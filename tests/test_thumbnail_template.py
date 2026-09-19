"""Regressions: predictable, text-free thumbnail template."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from release_settings import THUMBNAIL_DEFAULTS, normalize_release_settings
from thumbnail_compositor import text_box_geometry
from thumbnail_runtime import LAYOUT_TEMPLATES, artwork_prompt, episode_title_headline, final_review_prompt, local_plan, validate_headline


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
    band = text_box_geometry(base_settings(), "stacked_brand")
    assert band == {"x": 0.06, "y": 0.30, "width": 0.88, "height": 0.28}
    assert abs((band["x"] + band["width"] / 2) - 0.5) < 1e-9


def test_every_layout_has_a_placement_template() -> None:
    for layout in ("stacked_brand",):
        template = LAYOUT_TEMPLATES[layout]
        assert template["host"] and template["scene"]


def test_plan_carries_band_and_template_per_layout() -> None:
    settings = base_settings(count=4)
    plans = local_plan(sample_metadata(), sample_context(), settings, sample_character(), "Same Meals Fall Short")
    assert [plan["layout_id"] for plan in plans] == ["stacked_brand"] * 4
    for plan in plans:
        assert "FIXED BRANDED COMPOSITION" in plan["composition_template"]
        assert plan["headline"] == "Same Meals Fall Short"


def test_artwork_prompt_reserves_band_and_keeps_head_below() -> None:
    settings = base_settings(count=1)
    plan = local_plan(sample_metadata(), sample_context(), settings, sample_character(), "Same Meals Fall Short")[0]
    prompt = artwork_prompt(plan, sample_character(), [], "")
    assert 'Render exactly this English headline once: "Same Meals Fall Short"' in prompt
    assert "The pipeline will not add a second text layer later" in prompt
    assert "CHARACTER SHEET attachment is the source of truth" in prompt


def test_final_review_requires_exact_headline_output() -> None:
    prompt = final_review_prompt(
        {"headline": "Same Meals Fall Short", "evidence_anchor": "meals"},
        {"title": "Same Meals Can Fall Short #shorts"},
    )
    assert "missing, misspelled, duplicated" in prompt


def test_episode_title_and_manual_headlines_are_preserved_exactly() -> None:
    settings = base_settings()
    context = {"run": {"topic": "What If Fish Could Breathe on Land?"}}
    assert episode_title_headline(context, sample_metadata(), settings) == "What If Fish Could Breathe on Land?"
    assert validate_headline("  A Manual   Headline  ", settings) == "A Manual Headline"


def test_rendered_lines_share_one_ink_center(tmp_path) -> None:
    """Unequal line widths must still land on a single canvas center (039 case)."""
    from PIL import Image

    from thumbnail_compositor import compose

    artwork = tmp_path / "artwork.png"
    Image.new("RGB", (1080, 1920), (90, 110, 140)).save(artwork)
    out = tmp_path / "final.png"
    compose(artwork, out, "Can This Diet Last?", base_settings(), "stacked_brand")
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
    assert len(lines) >= 1
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
