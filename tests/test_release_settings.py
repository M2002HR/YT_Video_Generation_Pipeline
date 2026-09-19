from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from release_settings import RELEASE_DEFAULTS, normalize_release_settings, public_schema  # noqa: E402


def test_release_schema_defaults_are_the_single_shared_snapshot() -> None:
    schema = public_schema()
    assert schema["schema_version"] == 2
    assert schema["defaults"] == RELEASE_DEFAULTS
    assert schema["defaults"]["thumbnail"]["delivery_mode"] == "all_final_candidates"


def test_release_thumbnail_contract_is_strict_before_provider_work() -> None:
    with pytest.raises(ValueError, match="integer"):
        normalize_release_settings({"thumbnail": {"count": True}})
    with pytest.raises(ValueError, match="Unknown thumbnail"):
        normalize_release_settings({"thumbnail": {"filesystem_path": "../../secret"}})
    assert normalize_release_settings({"thumbnail": {"count": 6, "max_image_generations": 5}})["thumbnail"]["max_image_generations"] == 6
    settings = normalize_release_settings({"thumbnail": {"coordinates": {"x": .9, "y": 0, "width": .2, "height": .2}}})
    assert settings["thumbnail"]["coordinates"] is None


def test_legacy_thumbnail_note_round_trips_into_nested_contract() -> None:
    settings = normalize_release_settings({"thumbnail_note": "Show the real consequence."})
    assert settings["thumbnail"]["thumbnail_note"] == "Show the real consequence."
    assert settings["thumbnail_note"] == "Show the real consequence."


def test_thumbnail_review_bypass_is_a_typed_release_setting() -> None:
    settings = normalize_release_settings({"thumbnail": {"review_enabled": False}})
    assert settings["thumbnail"]["review_enabled"] is False
    with pytest.raises(ValueError, match="on or off"):
        normalize_release_settings({"thumbnail": {"review_enabled": "false"}})


def test_thumbnail_headline_modes_are_validated() -> None:
    assert normalize_release_settings({})["thumbnail"]["text_mode"] == "auto"
    assert normalize_release_settings({"thumbnail": {"text_mode": "video_title"}})["thumbnail"]["text_mode"] == "video_title"
    manual = normalize_release_settings({"thumbnail": {"text_mode": "manual", "manual_text": "Exact Manual Headline"}})
    assert manual["thumbnail"]["manual_text"] == "Exact Manual Headline"
    with pytest.raises(ValueError, match="manual_text"):
        normalize_release_settings({"thumbnail": {"text_mode": "manual", "manual_text": ""}})


def test_release_thumbnail_provider_is_chatgpt_only_and_legacy_settings_migrate() -> None:
    settings = normalize_release_settings({"thumbnail": {"image_fallback": "chatgpt_on_gemini_failure"}})
    assert settings["thumbnail"]["image_model"] == "chatgpt"
    assert settings["thumbnail"]["image_fallback"] == "none"
    assert settings["thumbnail"]["font_id"] == "quicky_story"
    assert settings["thumbnail"]["layout_mode"] == "stacked_brand"
    with pytest.raises(ValueError, match="image_fallback"):
        normalize_release_settings({"thumbnail": {"image_fallback": "off"}})
