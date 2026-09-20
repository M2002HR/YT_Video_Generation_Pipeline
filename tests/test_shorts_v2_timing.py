from __future__ import annotations

import struct
import sys
import wave
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from shorts_v2.canonical_text import freeze_canonical_text
from shorts_v2.contracts import ContractError
from shorts_v2.performance import compile_voice
from shorts_v2.timing import build_narration_timing, build_rhythm_map, pacing_report, probe_audio


def doc():
    return freeze_canonical_text([
        {"unit_id": "unit.hook", "text": "No, half the weight isn't half the danger."},
        {"unit_id": "unit.payoff", "text": "Your mass still resists the stop."},
    ])


def performance(document, model="eleven_v3"):
    first = next(token.word_id for token in document.tokens if token.spoken)
    return {
        "schema_version": 1, "model_family": model, "canonical_text_hash": document.text_sha256,
        "spoken_text_mutation_allowed": False,
        "events": [{"event_id": "vp.gasp", "word_id": first, "position": "before", "kind": "nonverbal", "intent": "topic-caused alarm", "implementation_type": "audio_tag", "value": "sighs", "calibration_status": "documented_not_calibrated", "required": False}],
        "global_direction": {"emotion": "alarm then clarity", "cadence": "fast contrast", "hook_intensity": .8, "body_intensity": .4},
        "take_policy": {"candidate_count": 1, "manual_selection": False, "acceptance": "technical"},
    }


def observations(document, *, method="measured_word", first_start=.4):
    output, cursor = [], first_start
    for token in (item for item in document.tokens if item.spoken):
        output.append({"word_id": token.word_id, "observed_tokens": [token.text], "start": cursor, "end": cursor + .2, "confidence": .95, "method": method})
        cursor += .25
    return output


def timing(document, *, method="measured_word"):
    compiled = compile_voice(performance(document), document=document, tts_model="eleven_v3")
    return build_narration_timing(
        document=document, token_map=compiled.token_map, observations=observations(document, method=method),
        audio={"path": "/fixture/narration.wav", "sha256": "a" * 64, "duration_seconds": 4.0, "codec": "pcm"},
        performance_events=performance(document)["events"],
        event_windows=[{"performance_event_id": "vp.gasp", "start": .05, "end": .35, "label": "possible breath or gasp", "evidence": "candidate_event_window", "confidence": .4}],
    )


def test_t32_alignment_requires_only_canonical_audio_token_map_not_visuals() -> None:
    document = doc(); result = timing(document)
    assert result["audio_authoritative"] is True and result["coverage"] == 1.0
    assert "visual" not in result and result["caption_source"] == "canonical_words_only"
    assert result["words"][0]["word_id"] == next(token.word_id for token in document.tokens if token.spoken)


def test_t33_interpolation_is_never_relabeled_measured_and_critical_confidence_fails() -> None:
    document = doc(); result = timing(document, method="segment_interpolated")
    assert {word["method"] for word in result["words"]} == {"segment_interpolated"}
    compiled = compile_voice(performance(document), document=document, tts_model="eleven_v3")
    low = observations(document); low[0]["confidence"] = .5
    with pytest.raises(ContractError, match="critical alignment confidence"):
        build_narration_timing(document=document, token_map=compiled.token_map, observations=low, audio={"sha256": "a" * 64, "duration_seconds": 4.0}, performance_events=[])


def test_t34_leading_nonverbal_audio_is_preserved_and_not_claimed_observed() -> None:
    result = timing(doc())
    assert result["leading_audio_seconds"] == .4
    assert result["leading_audio_policy"].startswith("preserve")
    gasp = result["nonverbal_events"][0]
    assert gasp["observed"] is False and gasp["semantic_verification"] == "unverified"
    assert "gasp" not in [word["canonical_text"] for word in result["words"]]


def test_t35_probe_real_audio_and_pacing_use_actual_duration(tmp_path: Path) -> None:
    audio = tmp_path / "narration.wav"
    with wave.open(str(audio), "wb") as stream:
        stream.setnchannels(1); stream.setsampwidth(2); stream.setframerate(8000)
        stream.writeframes(struct.pack("<h", 0) * 16000)
    observed = probe_audio(audio)
    assert observed["duration_seconds"] == pytest.approx(2.0)
    report = pacing_report({"audio": observed, "coverage": 1.0}, minimum_seconds=2.5, maximum_seconds=4)
    assert report["status"] == "too_short" and report["hidden_audio_retime"] is False
    too_long = pacing_report({"audio": {**observed, "duration_seconds": 5}, "coverage": 1.0}, minimum_seconds=2.5, maximum_seconds=4)
    assert too_long["status"] == "too_long" and "regenerate_and_realign" in too_long["action"]


def test_t36_t45_word_ids_stay_stable_across_voice_changes_but_audio_hash_changes_timing() -> None:
    document = doc(); v3 = timing(document)
    v2plan = performance(document, "eleven_multilingual_v2"); v2plan["events"] = []
    v2 = compile_voice(v2plan, document=document, tts_model="eleven_multilingual_v2")
    other = build_narration_timing(document=document, token_map=v2.token_map, observations=observations(document, first_start=.1), audio={"sha256": "b" * 64, "duration_seconds": 4.0}, performance_events=[])
    assert [word["word_id"] for word in v3["words"]] == [word["word_id"] for word in other["words"]]
    assert v3["timing_hash"] != other["timing_hash"]


def test_rhythm_map_has_measured_bounds_and_one_primary_focus() -> None:
    document = doc(); aligned = timing(document)
    ids = [word["word_id"] for word in aligned["words"]]
    base = {"performance_event_ids": [], "time_evidence": "measured_word", "primary_attention": "narration meaning", "supporting_layers": ["caption", "camera"], "purpose": "advance information"}
    events = [
        {**base, "event_id": "rhythm.hook", "word_ids": ids[:3], "role": "hook_peak"},
        {**base, "event_id": "rhythm.payoff", "word_ids": ids[3:], "role": "payoff"},
    ]
    rhythm = build_rhythm_map(timing=aligned, performance_events=performance(document)["events"], events=events)
    assert rhythm["music_policy"] == "music_follows_edit"
    assert rhythm["events"][0]["start"] == aligned["words"][0]["start"]
    overlap = [events[0], {**events[1], "word_ids": ids[2:]}]
    with pytest.raises(ContractError, match="primary attention overlap"):
        build_rhythm_map(timing=aligned, performance_events=[], events=overlap)


def test_incomplete_or_mismatched_alignment_never_fabricates_timestamps() -> None:
    document = doc(); compiled = compile_voice(performance(document), document=document, tts_model="eleven_v3")
    with pytest.raises(ContractError, match="coverage is incomplete"):
        build_narration_timing(document=document, token_map=compiled.token_map, observations=observations(document)[:-1], audio={"sha256": "a" * 64, "duration_seconds": 4.0})
    wrong = observations(document); wrong[2]["observed_tokens"] = ["different"]
    with pytest.raises(ContractError, match="text mismatch"):
        build_narration_timing(document=document, token_map=compiled.token_map, observations=wrong, audio={"sha256": "a" * 64, "duration_seconds": 4.0})
