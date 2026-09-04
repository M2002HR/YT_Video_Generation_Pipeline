"""The model contract is transmitted, verified, and never silently downgraded (T6.1).

These tests exercise the shipped functions.  A test that only restates a constant
(``assert "720p" != "360p"``) proves nothing about the pipeline, so there are none here:
each case either builds a real request payload or drives a real guard to its decision.
The DOM-level verification behaviour is covered in
``services/ordak/tests/test_flow_settings_verification.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from content_projects import normalize_flow_model, normalize_gemini_model
from ordak_jobs import Generation, OrdakJobError
from run_question_harvest_pipeline import (
    StageFailure,
    require_verified_image_model,
    require_verified_video_model,
)


def test_gemini_model_normalization_accepts_both_spellings_and_nothing_else() -> None:
    assert normalize_gemini_model("nano_banana_pro") == "nano_banana_pro"
    assert normalize_gemini_model("Nano Banana Pro") == "nano_banana_pro"
    assert normalize_gemini_model("nano_banana_2") == "nano_banana_2"
    assert normalize_gemini_model("Nano Banana 2") == "nano_banana_2"
    with pytest.raises(ValueError):
        normalize_gemini_model("unknown_model")


def test_flow_model_normalization_accepts_the_catalogue_and_rejects_auto() -> None:
    assert normalize_flow_model("gemini_omni_1_1_flash") == "gemini_omni_1_1_flash"
    assert normalize_flow_model("Gemini Omni 1.1 Flash") == "gemini_omni_1_1_flash"
    assert normalize_flow_model("Veo 3.1 Quality") == "veo_3_1_quality"
    for vague in ("Auto", "Best available", "default"):
        with pytest.raises(ValueError):
            normalize_flow_model(vague)


def test_the_generation_contract_is_transmitted_not_inferred() -> None:
    """Every paid parameter must reach the worker explicitly (§5, §18-21)."""
    generation = Generation(
        model="gemini_omni_1_1_flash",
        resolution="720p",
        aspect_ratio="9:16",
        duration_seconds=4,
    )
    form = generation.as_form()
    assert form == {
        "model": "gemini_omni_1_1_flash",
        "aspect_ratio": "9:16",
        "duration_seconds": "4",
        "resolution": "720p",
    }
    assert generation.as_json() == {
        "model": "gemini_omni_1_1_flash",
        "aspect_ratio": "9:16",
        "duration_seconds": 4,
        "resolution": "720p",
    }
    assert "prompt" not in form and "question" not in form, "the model never rides in the prompt"


def test_an_empty_contract_sends_nothing_rather_than_a_default() -> None:
    assert Generation().as_form() == {}
    assert Generation().as_json() is None


def test_an_unverified_image_model_stops_the_stage() -> None:
    with pytest.raises(StageFailure) as excinfo:
        require_verified_image_model(
            "world_keyframe",
            "nano_banana_pro",
            {"model_verified": False, "actual_model_label": None},
        )
    assert excinfo.value.state == "FAILED_MODEL_SELECTION"


def test_a_verified_pro_receipt_passes() -> None:
    require_verified_image_model(
        "world_keyframe",
        "nano_banana_pro",
        {
            "model_verified": True,
            "actual_model_label": "Nano Banana Pro",
            "pro_regeneration_used": True,
        },
    )


def test_a_verified_label_without_the_pro_path_is_still_refused_for_pro() -> None:
    """Selecting Pro is not the same as having generated through the Pro path (§6)."""
    with pytest.raises(StageFailure) as excinfo:
        require_verified_image_model(
            "world_keyframe",
            "nano_banana_pro",
            {
                "model_verified": True,
                "actual_model_label": "Nano Banana Pro",
                "pro_regeneration_used": False,
            },
        )
    assert excinfo.value.state == "FAILED_MODEL_SELECTION"


def test_nano_banana_2_does_not_need_a_pro_regeneration() -> None:
    require_verified_image_model(
        "beat_03",
        "nano_banana_2",
        {"model_verified": True, "actual_model_label": "Nano Banana 2", "pro_regeneration_used": False},
    )


def test_a_missing_receipt_is_treated_as_unverified() -> None:
    for empty in (None, {}):
        with pytest.raises(StageFailure):
            require_verified_image_model("world_keyframe", "nano_banana_2", empty)
        with pytest.raises(StageFailure):
            require_verified_video_model("flow_clip_a", "gemini_omni_1_1_flash", empty)


def test_an_unverified_flow_model_stops_the_stage() -> None:
    with pytest.raises(StageFailure) as excinfo:
        require_verified_video_model(
            "flow_clip_b",
            "gemini_omni_1_1_flash",
            {"model_verified": False, "actual_model_label": "Veo 3.1 - Fast"},
        )
    assert excinfo.value.state == "FAILED_MODEL_SELECTION"


@pytest.mark.parametrize(
    "error_code,expected",
    [
        ("model_not_available", "FAILED_MODEL_SELECTION"),
        ("model_selection_failed", "FAILED_MODEL_SELECTION"),
        ("model_feature_incompatible", "FAILED_MODEL_COMPATIBILITY"),
        ("flow_credits_exhausted", "PAUSED_CREDITS"),
        ("flow_login_required", "PAUSED_LOGIN_REQUIRED"),
    ],
)
def test_provider_model_errors_map_to_terminal_pipeline_states(
    error_code: str, expected: str
) -> None:
    """A model failure must never look retryable, or the pipeline would spend again."""
    error = OrdakJobError("nope", error_code=error_code)
    assert error.pipeline_state == expected
    assert error.retryable is False
