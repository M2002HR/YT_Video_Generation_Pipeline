from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from run_elevenlabs_voiceover import ElevenLabsUI
from shorts_v2.elevenlabs_adapter import (
    AdapterErrorCode,
    AttemptStateMachine,
    CapabilityProbe,
    ElevenLabsAdapterError,
    bind_new_result,
    build_execution_plan,
    result_snapshot,
    text_fingerprint,
    validate_download_candidate,
)


def probe_v2(**changes: object) -> CapabilityProbe:
    values = {
        "observed_model": "Eleven Multilingual v2",
        "observed_voice": "Mark",
        "numeric_controls": frozenset({"speed", "stability", "similarity", "style"}),
        "stability_modes": frozenset(),
        "speaker_boost_available": True,
        "editor_kind": "textarea",
        "observed_at": "2026-09-20T00:00:00Z",
    }
    values.update(changes)
    return CapabilityProbe(**values)


def probe_v3(**changes: object) -> CapabilityProbe:
    values = {
        "observed_model": "Eleven v3",
        "observed_voice": "Mark",
        "numeric_controls": frozenset(),
        "stability_modes": frozenset({"creative", "natural", "robust"}),
        "speaker_boost_available": False,
        "editor_kind": "contenteditable",
        "observed_at": "2026-09-20T00:00:00Z",
    }
    values.update(changes)
    return CapabilityProbe(**values)


def test_v2_uses_only_observed_numeric_controls() -> None:
    plan = build_execution_plan({"model": "Eleven Multilingual v2", "speed": 1.05, "stability": .4, "similarity": .75, "style": 0, "speaker_boost": True}, probe_v2())
    assert plan.execution_mode == "optimized_v2"
    assert plan.numeric_settings == {"speed": 1.05, "stability": .4, "similarity": .75, "style": 0.0}
    assert plan.stability_mode is None


def test_v3_uses_modes_and_keeps_v2_sliders_inactive() -> None:
    plan = build_execution_plan({"model": "Eleven v3", "stability_mode": "Creative", "speed": .9, "similarity": .75, "speaker_boost": False}, probe_v3())
    assert plan.execution_mode == "expressive_v3"
    assert plan.stability_mode == "Creative"
    assert plan.numeric_settings == {}
    assert plan.inactive_settings["speed"] == .9
    assert plan.speaker_boost is None


def test_v3_categorical_modes_may_use_the_observed_native_stability_slider() -> None:
    observed = probe_v3(numeric_controls=frozenset({"stability"}), stability_modes=frozenset())
    plan = build_execution_plan({"model": "Eleven v3", "stability_mode": "Natural"}, observed)
    assert plan.numeric_settings == {"stability": .5}
    assert plan.inactive_settings["stability_mode_control"] == "categorical_numeric_slider"


@pytest.mark.parametrize(
    "probe",
    [
        probe_v2(numeric_controls=frozenset({"stability"})),
        probe_v2(observed_model="Unknown model"),
        probe_v3(stability_modes=frozenset()),
        probe_v3(editor_kind="missing"),
    ],
)
def test_ui_drift_or_identity_mismatch_fails_loudly(probe: CapabilityProbe) -> None:
    request = {"model": "Eleven v3", "stability_mode": "Natural"} if probe.observed_model == "Eleven v3" else {"model": "Eleven Multilingual v2", "speed": 1.0}
    with pytest.raises(ElevenLabsAdapterError):
        build_execution_plan(request, probe)


def test_old_result_and_download_are_not_fresh_acknowledgement() -> None:
    baseline = result_snapshot({"result_identities": ["old"], "downloads": [{}], "busy": False})
    assert bind_new_result(baseline, result_snapshot({"result_identities": ["old"], "busy": True})) is None
    with pytest.raises(ElevenLabsAdapterError) as caught:
        bind_new_result(baseline, result_snapshot({"result_identities": ["old"], "downloads": [{}], "busy": False}))
    assert caught.value.code is AdapterErrorCode.RESULT_IDENTITY_UNPROVEN


def test_exactly_one_new_result_is_bound_and_multiple_are_rejected() -> None:
    baseline = result_snapshot({"result_identities": ["old"]})
    assert bind_new_result(baseline, result_snapshot({"result_identities": ["old", "new"]})) == "new"
    with pytest.raises(ElevenLabsAdapterError, match="multiple new"):
        bind_new_result(baseline, result_snapshot({"result_identities": ["old", "new-a", "new-b"]}))


def test_download_must_belong_to_dedicated_attempt_and_be_complete(tmp_path: Path) -> None:
    attempt = tmp_path / "attempt"
    attempt.mkdir()
    audio = attempt / "voice.mp3"
    audio.write_bytes(b"ID3" + b"a" * 2000)
    now = time.time()
    os.utime(audio, (now, now))
    assert validate_download_candidate(audio, attempt_root=attempt, started_at=now).name == "voice.mp3"
    outside = tmp_path / "wrong.mp3"
    outside.write_bytes(b"ID3" + b"a" * 2000)
    with pytest.raises(ElevenLabsAdapterError, match="escaped"):
        validate_download_candidate(outside, attempt_root=attempt, started_at=now)
    partial = attempt / "voice.mp3.crdownload"
    partial.write_bytes(b"a" * 2000)
    with pytest.raises(ElevenLabsAdapterError) as caught:
        validate_download_candidate(partial, attempt_root=attempt, started_at=now)
    assert caught.value.code is AdapterErrorCode.PARTIAL_DOWNLOAD


def test_text_readback_hash_normalizes_only_line_endings() -> None:
    assert text_fingerprint("one\r\ntwo") == text_fingerprint("one\ntwo")
    assert text_fingerprint("one  two") != text_fingerprint("one two")


def test_state_machine_rejects_skipped_or_duplicate_submit_states() -> None:
    machine = AttemptStateMachine()
    machine.advance("OPEN")
    with pytest.raises(ElevenLabsAdapterError, match="invalid adapter transition"):
        machine.advance("SELECT_MODEL")


def test_numeric_slider_accepts_its_minimum_without_forced_increment() -> None:
    ui = object.__new__(ElevenLabsUI)
    values = iter((
        {"ok": True, "min": 0, "max": 1, "current": 0.2},
        {"ok": True, "value": 0},
    ))
    ui._json = lambda expression: next(values)  # type: ignore[method-assign]
    ui._focus_selector = lambda selector: {"ok": True}  # type: ignore[method-assign]
    pressed: list[str] = []
    ui._trusted_key = lambda key: pressed.append(key)  # type: ignore[method-assign]
    ui._trusted_keys = lambda key, count: pressed.extend([key] * count)  # type: ignore[method-assign]

    ui.apply_numeric_setting("Style Exaggeration", 0.0)

    assert pressed == ["Home"]
