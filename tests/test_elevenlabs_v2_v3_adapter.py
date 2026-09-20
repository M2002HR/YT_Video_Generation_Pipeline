from __future__ import annotations

import os
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from run_elevenlabs_voiceover import (
    ElevenLabsUI,
    State,
    VoiceSettings,
    bound_download_is_pending,
    find_download,
    recover_owned_download_after_interruption,
    stage_download_for_attempt,
)
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


def test_new_audio_player_identity_is_a_bindable_result() -> None:
    baseline = result_snapshot({"result_identities": []})
    assert bind_new_result(
        baseline,
        result_snapshot({"result_identities": ["audio-player:blob:https://elevenlabs.io/new-render"]}),
    ) == "audio-player:blob:https://elevenlabs.io/new-render"


def test_audio_player_download_rechecks_the_bound_blob_before_click() -> None:
    ui = object.__new__(ElevenLabsUI)
    checks: list[str] = []
    ui._json = lambda expression: checks.append(expression) or {"ok": True, "text": "Download Audio"}  # type: ignore[method-assign]
    ui._pointer_activate_selector = lambda selector: {"text": "Download Audio"}  # type: ignore[method-assign]

    result = ui.download_bound_result("audio-player:blob:https://elevenlabs.io/new-render")

    assert result["ok"] is True
    assert result["result_id"].startswith("audio-player:")
    assert any("bound audio player changed" in expression for expression in checks)


@pytest.mark.parametrize("reason", [
    "bound audio player has no enabled download control",
    "bound result has no enabled download control",
])
def test_bound_player_without_ready_download_is_retried_not_failed(reason: str) -> None:
    assert bound_download_is_pending({"ok": False, "reason": reason})
    assert not bound_download_is_pending({"ok": False, "reason": "bound audio player changed before download"})
    assert not bound_download_is_pending({"ok": True})


def test_download_routing_holds_the_browser_context_until_explicit_close(tmp_path: Path) -> None:
    ui = object.__new__(ElevenLabsUI)
    ui.tab = object()
    ui._download_context = None
    events: list[object] = []

    class DownloadContext:
        def __enter__(self) -> Path:
            events.append("enter")
            return tmp_path

        def __exit__(self, *args: object) -> None:
            events.append("exit")

    ui._download_to = lambda tab, directory: DownloadContext()  # type: ignore[method-assign]

    ui.configure_downloads(tmp_path / "attempt")
    assert events == ["enter"]
    ui.close_downloads()
    assert events == ["enter", "exit"]


def test_fresh_profile_download_is_staged_before_attempt_validation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    attempt = tmp_path / "attempt"
    attempt.mkdir()
    profile_downloads = tmp_path / "profile-downloads"
    profile_downloads.mkdir()
    audio = profile_downloads / "voice.mp3"
    audio.write_bytes(b"ID3" + b"a" * 2000)
    now = time.time()
    os.utime(audio, (now, now))
    monkeypatch.setattr("run_elevenlabs_voiceover.Path.home", lambda: tmp_path)

    assert find_download(attempt, now) is None  # profile fallback is intentionally /Downloads
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    fallback = downloads / "voice.mp3"
    audio.replace(fallback)
    assert find_download(attempt, now) == fallback
    staged = stage_download_for_attempt(fallback, attempt)
    assert staged.parent == attempt
    assert staged.is_file() and not fallback.exists()


def test_extensionless_elevenlabs_blob_download_is_identified_and_staged(tmp_path: Path) -> None:
    attempt = tmp_path / "attempt"
    attempt.mkdir()
    blob = attempt / "provider-uuid"
    blob.write_bytes(b"ID3" + b"a" * 2000)
    now = time.time()
    os.utime(blob, (now, now))

    assert find_download(attempt, now) == blob
    staged = stage_download_for_attempt(blob, attempt)
    assert staged.name == "provider-uuid.mp3"
    assert staged.is_file() and not blob.exists()


def test_completed_owned_blob_download_is_recovered_without_a_new_generation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / "videos/047_fixture"
    voiceover = project / "voiceover"
    text = "The exact narration bound to this browser attempt."
    settings = VoiceSettings("Mark", "Eleven v3", None, None, None, None, None, None, "MP3")
    state = State(voiceover / "ELEVENLABS_RUNTIME_STATE.json", video_id="047", input_path=voiceover / "VOICEOVER_INPUT.txt", text=text, settings=settings)
    attempt = "attempt-bound-download"
    downloads = voiceover / "downloads" / attempt
    downloads.mkdir(parents=True)
    blob = downloads / "provider-uuid"
    blob.write_bytes(b"ID3" + b"a" * 2000)
    now = time.time()
    os.utime(blob, (now, now))
    state.data.update({"active_attempt_id": attempt, "bound_result_id": "audio-player:blob:https://elevenlabs.io/bound", "download_requested_at": now})
    state.save()
    monkeypatch.setattr("run_elevenlabs_voiceover.verify_audio_decode", lambda path: {"duration_seconds": 1.0, "format_name": "mp3"})

    output = recover_owned_download_after_interruption(project, state, text, settings, project / "assets/audio")

    assert output == project / "assets/audio/narration.mp3"
    assert output.is_file()
    assert state.data["status"] == "DONE"
    profile = json.loads((voiceover / "VOICE_PROFILE.json").read_text())
    assert profile["result_id"] == "audio-player:blob:https://elevenlabs.io/bound"
    assert profile["recovered_after_interruption"] is True


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


def test_v3_contenteditable_recovery_retries_once_then_requires_exact_readback() -> None:
    ui = object.__new__(ElevenLabsUI)
    expected = "The narration that must replace stale text."
    observed = iter(("old narration" + expected, expected))
    ui._replace_contenteditable_text_once = lambda text: next(observed)  # type: ignore[method-assign]

    assert ui._set_contenteditable_text_with_recovery(expected) == expected


def test_v3_contenteditable_recovery_never_accepts_an_appended_narration() -> None:
    ui = object.__new__(ElevenLabsUI)
    expected = "The narration that must replace stale text."
    ui._replace_contenteditable_text_once = lambda text: "stale text" + text  # type: ignore[method-assign]

    with pytest.raises(ElevenLabsAdapterError) as caught:
        ui._set_contenteditable_text_with_recovery(expected)
    assert caught.value.code is AdapterErrorCode.TEXT_MISMATCH
    assert len(caught.value.evidence["observations"]) == 2


def test_v3_contenteditable_clear_is_required_before_trusted_insert() -> None:
    ui = object.__new__(ElevenLabsUI)
    ui.control_timeout_seconds = 1
    ui.poll_seconds = 0
    reads = iter(("stale narration", "", "new narration"))
    ui.read_text = lambda: next(reads)  # type: ignore[method-assign]
    activated: list[str] = []
    ui._activate_selector = lambda selector: activated.append(selector)  # type: ignore[method-assign]
    ui._json = lambda expression: {"ok": True}  # type: ignore[method-assign]
    inserted: list[str] = []
    ui._trusted_insert_text = lambda text: inserted.append(text)  # type: ignore[method-assign]

    assert ui._replace_contenteditable_text_once("new narration") == "new narration"
    assert activated == ['button[aria-label="Clear text"]']
    assert inserted == ["new narration"]


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
