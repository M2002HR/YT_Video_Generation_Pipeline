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
    with pytest.raises(ValueError, match="cover"):
        normalize_release_settings({"thumbnail": {"count": 6, "max_image_generations": 5}})
    with pytest.raises(ValueError, match="coordinates"):
        normalize_release_settings({"thumbnail": {"coordinates": {"x": .9, "y": 0, "width": .2, "height": .2}}})


def test_legacy_thumbnail_note_round_trips_into_nested_contract() -> None:
    settings = normalize_release_settings({"thumbnail_note": "Show the real consequence."})
    assert settings["thumbnail"]["thumbnail_note"] == "Show the real consequence."
    assert settings["thumbnail_note"] == "Show the real consequence."


def test_thumbnail_review_bypass_is_a_typed_release_setting() -> None:
    settings = normalize_release_settings({"thumbnail": {"review_enabled": False}})
    assert settings["thumbnail"]["review_enabled"] is False
    with pytest.raises(ValueError, match="on or off"):
        normalize_release_settings({"thumbnail": {"review_enabled": "false"}})


def test_chatgpt_image_fallback_is_explicit_and_opt_in() -> None:
    settings = normalize_release_settings({"thumbnail": {"image_fallback": "chatgpt_on_gemini_failure"}})
    assert settings["thumbnail"]["image_fallback"] == "chatgpt_on_gemini_failure"
    with pytest.raises(ValueError, match="image_fallback"):
        normalize_release_settings({"thumbnail": {"image_fallback": "automatic"}})
