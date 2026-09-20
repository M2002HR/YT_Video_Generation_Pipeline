from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from shorts_v2.canonical_text import freeze_canonical_text
from shorts_v2.contracts import (
    ContractError,
    canonical_json_hash,
    normalize_engine_settings,
    resolve_precedence,
    validate_artifact_envelope,
)


def request(model: str = "eleven_v3") -> dict:
    return {
        "_shorts_v2": {
            "editing_engine": "shorts_v2",
            "voice": {"tts_model": model, "voice_id": "voice_mark"},
        }
    }


def test_missing_engine_marker_is_frozen_legacy() -> None:
    assert normalize_engine_settings({"_motion": {"enabled": True}}) == {
        "schema_version": 1,
        "editing_engine": "legacy",
    }


@pytest.mark.parametrize(
    ("model", "execution"),
    [("eleven_v3", "expressive_v3"), ("eleven_multilingual_v2", "optimized_v2")],
)
def test_voice_model_is_independent_from_engine_and_qc(model: str, execution: str) -> None:
    raw = request(model)
    normalized = normalize_engine_settings(raw)
    assert normalized["editing_engine"] == "shorts_v2"
    assert normalized["voice"]["execution_mode"] == execution
    assert normalized["quality"]["media_review"] == "off"
    assert normalized["quality"]["editing_observation"] == "auto_once"


def test_no_silent_voice_model_or_transport_fallback() -> None:
    with pytest.raises(ContractError, match="automatic, unknown, or fallback"):
        normalize_engine_settings({"_shorts_v2": {"editing_engine": "shorts_v2", "voice": {"tts_model": "auto", "voice_id": "voice_mark"}}})
    raw = request()
    raw["_shorts_v2"]["voice"]["transport"] = "api"
    with pytest.raises(ContractError, match="elevenlabs_web"):
        normalize_engine_settings(raw)


def test_model_execution_mismatch_is_rejected() -> None:
    raw = request("eleven_v3")
    raw["_shorts_v2"]["voice"]["execution_mode"] = "optimized_v2"
    with pytest.raises(ContractError, match="requires execution_mode"):
        normalize_engine_settings(raw)


def test_qc_off_applies_to_every_visual_and_cannot_hide_corrections() -> None:
    raw = request()
    raw["_shorts_v2"]["quality"] = {"media_review": "off", "media_auto_corrections": 1}
    with pytest.raises(ContractError, match="requires media_auto_corrections=0"):
        normalize_engine_settings(raw)
    raw["_shorts_v2"]["quality"] = {"media_review": "off", "media_review_scope": "body_only"}
    with pytest.raises(ContractError, match="all_visual_assets"):
        normalize_engine_settings(raw)


def test_technical_validation_cannot_be_disabled() -> None:
    raw = request()
    raw["_shorts_v2"]["quality"] = {"technical_validation": False}
    with pytest.raises(ContractError, match="cannot be disabled"):
        normalize_engine_settings(raw)


def test_non_finite_and_unknown_fields_are_rejected() -> None:
    raw = request()
    raw["_shorts_v2"]["locks"] = {"scale": math.nan}
    with pytest.raises(ContractError, match="non-finite"):
        normalize_engine_settings(raw)
    raw = request()
    raw["_shorts_v2"]["surprise"] = True
    with pytest.raises(ContractError, match="unknown field"):
        normalize_engine_settings(raw)


def test_manual_lock_precedence_requires_a_user_value() -> None:
    assert resolve_precedence(defaults={"tone": "neutral"}, ai={"tone": "bright"}, profile={"tone": "dry"}, user={"tone": "warm"}, locked_fields={"tone"})["tone"] == "warm"
    with pytest.raises(ContractError, match="no explicit user value"):
        resolve_precedence(defaults={"tone": "neutral"}, locked_fields={"tone"})


def test_canonical_tokens_preserve_contractions_decimals_percent_and_negation() -> None:
    document = freeze_canonical_text([
        {"unit_id": "hook", "text": "It isn't minus 2.5%—really."},
        {"unit_id": "proof", "text": "That's the proof."},
    ])
    spoken = [token.text for token in document.tokens if token.spoken]
    assert spoken == ["It", "isn't", "minus", "2.5%", "really", "That's", "the", "proof"]
    assert len({token.word_id for token in document.tokens}) == len(document.tokens)
    assert document.units[1]["start"] == len(document.units[0]["text"]) + 1


def test_duplicate_or_invalid_unit_ids_fail() -> None:
    with pytest.raises(ContractError, match="duplicate unit_id"):
        freeze_canonical_text([{"unit_id": "unit", "text": "One"}, {"unit_id": "unit", "text": "Two"}])
    with pytest.raises(ContractError, match="must match"):
        freeze_canonical_text([{"unit_id": "12", "text": "One"}])


def test_artifact_envelope_is_strict_and_hash_is_canonical() -> None:
    payload = {
        "schema_version": 1,
        "design_version": "2.2",
        "editing_engine": "shorts_v2",
        "episode_id": "episode-001",
        "revision_id": "revision-001",
        "artifact_type": "voice-resolution",
        "producer_stage": "voice-resolution",
        "producer_version": "1",
        "input_fingerprint": "a" * 64,
        "created_at": "2026-09-20T00:00:00Z",
        "provenance": {"kind": "fixture", "observed": False},
    }
    assert validate_artifact_envelope(payload).episode_id == "episode-001"
    assert canonical_json_hash({"b": 2, "a": 1}) == canonical_json_hash({"a": 1, "b": 2})
    with pytest.raises(ContractError, match="unknown"):
        validate_artifact_envelope({**payload, "extra": True})
