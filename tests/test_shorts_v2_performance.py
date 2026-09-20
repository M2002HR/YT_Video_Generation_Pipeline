from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from shorts_v2.canonical_text import freeze_canonical_text
from shorts_v2.contracts import ContractError
from shorts_v2.elevenlabs_adapter import CapabilityProbe
from shorts_v2.performance import build_tts_execution_request, compile_voice


def document():
    return freeze_canonical_text([
        {"unit_id": "unit.hook", "text": "You think that's 12.5% safer. It isn't."},
        {"unit_id": "unit.body", "text": "You still can't stop the fall."},
    ])


def word_id(doc, text: str, occurrence: int = 1) -> str:
    matches = [token.word_id for token in doc.tokens if token.spoken and token.text.casefold() == text.casefold()]
    return matches[occurrence - 1]


def plan(doc, model: str, events: list[dict]) -> dict:
    return {
        "schema_version": 1, "model_family": model, "canonical_text_hash": doc.text_sha256,
        "spoken_text_mutation_allowed": False, "events": events,
        "global_direction": {"emotion": "urgent curiosity", "cadence": "conversational contrast", "hook_intensity": .8, "body_intensity": .45},
        "take_policy": {"candidate_count": 1, "manual_selection": False, "acceptance": "technical"},
    }


def event(doc, *, event_id="vp.pause", kind="pause", impl="audio_tag", value="short pause", required=False):
    return {
        "event_id": event_id, "word_id": word_id(doc, "It"), "position": "before", "kind": kind,
        "intent": "hold the contrast", "implementation_type": impl, "value": value,
        "calibration_status": "documented_not_calibrated", "required": required,
    }


def test_t04_v3_uses_typed_allowed_tags_without_ssml_or_word_mutation() -> None:
    doc = document()
    compiled = compile_voice(plan(doc, "eleven_v3", [event(doc)]), document=doc, tts_model="eleven_v3")
    assert "[short pause]" in compiled.tts_input and "<break" not in compiled.tts_input
    assert [row["canonical_text"] for row in compiled.token_map] == [token.text for token in doc.tokens if token.spoken]
    assert compiled.take_policy == {"candidate_count": 1, "manual_selection": False, "acceptance": "technical"}


def test_t05_v2_uses_bounded_break_and_never_v3_tags() -> None:
    doc = document()
    pause = event(doc, impl="break", value='<break time="0.2s" />')
    emphasis = event(doc, event_id="vp.emphasis", kind="emphasis", impl="capitalization", value="canonical_word")
    compiled = compile_voice(plan(doc, "eleven_multilingual_v2", [pause, emphasis]), document=doc, tts_model="eleven_multilingual_v2")
    assert '<break time="0.2s" />' in compiled.tts_input and "[short pause]" not in compiled.tts_input
    assert "IT" in compiled.tts_input
    bad = event(doc, impl="break", value='<break time="9s" />')
    with pytest.raises(ContractError, match="0.05..1.5"):
        compile_voice(plan(doc, "eleven_multilingual_v2", [bad]), document=doc, tts_model="eleven_multilingual_v2")


def test_t06_numbers_percent_contraction_negation_and_repeated_word_ids_survive() -> None:
    doc = document()
    compiled = compile_voice(plan(doc, "eleven_v3", []), document=doc, tts_model="eleven_v3")
    canonical = [row["canonical_text"] for row in compiled.token_map]
    assert "12.5%" in canonical and "that's" in canonical and "isn't" in canonical and "can't" in canonical
    you = [row for row in compiled.token_map if row["canonical_text"] == "You"]
    assert len(you) == 2 and you[0]["word_id"] != you[1]["word_id"]


def test_t30_optional_unsupported_nonverbal_is_not_spoken_or_captioned() -> None:
    doc = document()
    laugh = event(doc, kind="nonverbal", impl="audio_tag", value="laughs")
    compiled = compile_voice(plan(doc, "eleven_multilingual_v2", [laugh]), document=doc, tts_model="eleven_multilingual_v2")
    assert "laugh" not in compiled.tts_input.casefold()
    assert compiled.unfulfilled_intents[0]["event_id"] == "vp.pause"
    laugh["required"] = True
    with pytest.raises(ContractError, match="required performance event"):
        compile_voice(plan(doc, "eleven_multilingual_v2", [laugh]), document=doc, tts_model="eleven_multilingual_v2")


def test_unknown_markup_and_stale_or_mutating_plan_fail_closed() -> None:
    doc = document()
    with pytest.raises(ContractError, match="unknown or unbounded"):
        compile_voice(plan(doc, "eleven_v3", [event(doc, value="execute shell")]), document=doc, tts_model="eleven_v3")
    stale = plan(doc, "eleven_v3", []); stale["canonical_text_hash"] = "0" * 64
    with pytest.raises(ContractError, match="stale"):
        compile_voice(stale, document=doc, tts_model="eleven_v3")
    mutating = plan(doc, "eleven_v3", []); mutating["spoken_text_mutation_allowed"] = True
    with pytest.raises(ContractError, match="cannot mutate"):
        compile_voice(mutating, document=doc, tts_model="eleven_v3")


def test_t08_t09_compiler_joins_adapter_and_fingerprint_excludes_inactive_v2_values_for_v3() -> None:
    doc = document()
    compiled = compile_voice(plan(doc, "eleven_v3", []), document=doc, tts_model="eleven_v3")
    probe = CapabilityProbe("Eleven v3", "Liam - Energetic, Social Media Creator", frozenset({"stability"}), frozenset(), False, "contenteditable", "2026-09-20T10:00:00Z")
    first = build_tts_execution_request(compiled, voice_id=None, voice_label=probe.observed_voice, requested_settings={"stability_mode": "Natural", "speed": .9}, probe=probe)
    second = build_tts_execution_request(compiled, voice_id=None, voice_label=probe.observed_voice, requested_settings={"stability_mode": "Natural", "speed": 1.1}, probe=probe)
    assert first["tts_effective_hash"] == second["tts_effective_hash"]
    assert first["inactive_settings"]["speed"] == .9 and second["inactive_settings"]["speed"] == 1.1


def test_t29_t31_normal_path_needs_no_calibration_or_take_selection() -> None:
    doc = document()
    uncalibrated = event(doc); uncalibrated["calibration_status"] = "documented_not_calibrated"
    compiled = compile_voice(plan(doc, "eleven_v3", [uncalibrated]), document=doc, tts_model="eleven_v3")
    assert compiled.implemented_event_ids == ("vp.pause",)
    bad = plan(doc, "eleven_v3", []); bad["take_policy"]["candidate_count"] = 2
    with pytest.raises(ContractError, match="one take"):
        compile_voice(bad, document=doc, tts_model="eleven_v3")
