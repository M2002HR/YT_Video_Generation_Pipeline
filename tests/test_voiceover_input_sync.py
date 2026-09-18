"""Regressions: narration audio must always speak the current pipeline script.

Covers the 039 incident where voiceover/VOICEOVER_INPUT.txt froze on the first
script version while SCRIPT_FINAL.md (and the beats) moved on, so the run kept
reusing stale audio until alignment failed.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_elevenlabs_voiceover as voiceover


OLD_TEXT = "Surrounded by water, how could thirst still be your first big problem?"
NEW_TEXT = "If food is everywhere, why can the same few meals still fail you?"


def make_project(tmp_path: Path, *, script: str, snapshot: str | None) -> Path:
    project = tmp_path / "videos/099_probe"
    project.mkdir(parents=True)
    (project / "SCRIPT_FINAL.md").write_text(script + "\n", encoding="utf-8")
    if snapshot is not None:
        voice_dir = project / "voiceover"
        voice_dir.mkdir(parents=True)
        (voice_dir / "VOICEOVER_INPUT.txt").write_text(snapshot + "\n", encoding="utf-8")
    return project


def test_missing_snapshot_is_created_from_canonical_script(tmp_path: Path) -> None:
    project = make_project(tmp_path, script=NEW_TEXT, snapshot=None)
    path, text = voiceover.narration_input(project)
    assert text == NEW_TEXT
    assert path.name == "VOICEOVER_INPUT.txt"
    sidecar = json.loads((project / "voiceover/VOICEOVER_INPUT.source.json").read_text())
    assert sidecar["operator_customized"] is False
    assert sidecar["script_sha256"] == voiceover.digest(NEW_TEXT)


def test_stale_pipeline_snapshot_refreshes_from_script(tmp_path: Path) -> None:
    project = make_project(tmp_path, script=NEW_TEXT, snapshot=OLD_TEXT)
    # Legacy snapshot without sidecar, canonical script is newer: pipeline moved on.
    os.utime(project / "voiceover/VOICEOVER_INPUT.txt", (1_000_000, 1_000_000))
    os.utime(project / "SCRIPT_FINAL.md", (2_000_000, 2_000_000))
    _, text = voiceover.narration_input(project)
    assert text == NEW_TEXT
    assert (project / "voiceover/VOICEOVER_INPUT.txt").read_text().strip() == NEW_TEXT


def test_operator_customization_is_respected_not_overwritten(tmp_path: Path) -> None:
    project = make_project(tmp_path, script=NEW_TEXT, snapshot=NEW_TEXT)
    voiceover.narration_input(project)  # writes sidecar
    customized = "Operator intro line. " + NEW_TEXT
    (project / "voiceover/VOICEOVER_INPUT.txt").write_text(customized + "\n", encoding="utf-8")
    _, text = voiceover.narration_input(project)
    assert text == customized
    sidecar = json.loads((project / "voiceover/VOICEOVER_INPUT.source.json").read_text())
    assert sidecar["operator_customized"] is True


def test_missing_inputs_fail_clearly(tmp_path: Path) -> None:
    project = tmp_path / "videos/099_empty"
    project.mkdir(parents=True)
    with pytest.raises(RuntimeError, match="No voiceover input"):
        voiceover.narration_input(project)


def _receipt(project: Path, text: str, settings: dict, output: str = "assets/audio/narration.mp3") -> None:
    voice_dir = project / "voiceover"
    voice_dir.mkdir(parents=True, exist_ok=True)
    (project / output).parent.mkdir(parents=True, exist_ok=True)
    (project / output).write_bytes(b"ID3" + b"audio" * 1000)
    (voice_dir / "VOICE_PROFILE.json").write_text(json.dumps({
        "provider": "ElevenLabs web UI", "settings": settings,
        "input_sha256": voiceover.digest(text), "output": output,
    }), encoding="utf-8")


SETTINGS = {"voice": "marv", "model": "Eleven Multilingual v2", "speed": 0.98}


def test_receipt_gate_accepts_matching_audio_and_settings(tmp_path: Path) -> None:
    project = make_project(tmp_path, script=NEW_TEXT, snapshot=NEW_TEXT)
    _receipt(project, NEW_TEXT, dict(SETTINGS))
    assert voiceover.narration_receipt_matches(project, NEW_TEXT, dict(SETTINGS)) is True


def test_receipt_gate_rejects_stale_text(tmp_path: Path) -> None:
    project = make_project(tmp_path, script=NEW_TEXT, snapshot=OLD_TEXT)
    _receipt(project, OLD_TEXT, dict(SETTINGS))
    assert voiceover.narration_receipt_matches(project, NEW_TEXT, dict(SETTINGS)) is False


def test_receipt_gate_rejects_changed_settings(tmp_path: Path) -> None:
    project = make_project(tmp_path, script=NEW_TEXT, snapshot=NEW_TEXT)
    _receipt(project, NEW_TEXT, dict(SETTINGS))
    changed = dict(SETTINGS, speed=1.1)
    assert voiceover.narration_receipt_matches(project, NEW_TEXT, changed) is False


def test_receipt_gate_rejects_missing_receipt_or_audio(tmp_path: Path) -> None:
    project = make_project(tmp_path, script=NEW_TEXT, snapshot=NEW_TEXT)
    assert voiceover.narration_receipt_matches(project, NEW_TEXT, dict(SETTINGS)) is False
    _receipt(project, NEW_TEXT, dict(SETTINGS))
    (project / "assets/audio/narration.mp3").unlink()
    assert voiceover.narration_receipt_matches(project, NEW_TEXT, dict(SETTINGS)) is False


def test_pipeline_synced_change_is_recognized_for_state_reset(tmp_path: Path) -> None:
    project = make_project(tmp_path, script=NEW_TEXT, snapshot=OLD_TEXT)
    os.utime(project / "voiceover/VOICEOVER_INPUT.txt", (1_000_000, 1_000_000))
    os.utime(project / "SCRIPT_FINAL.md", (2_000_000, 2_000_000))
    _, text = voiceover.narration_input(project)
    assert voiceover._input_change_is_pipeline_synced(project, text) is True
    assert voiceover._input_change_is_pipeline_synced(project, "something else") is False


def test_settings_from_profile_matches_cli_semantics() -> None:
    profile = {"voice": "marv", "model": "m", "speed": 0.98, "speaker_boost": False}
    direct = voiceover.settings_from_profile(profile).supplied()
    assert direct == {"voice": "marv", "model": "m", "speed": 0.98, "speaker_boost": False}
    overridden = voiceover.settings_from_profile(profile, {"speed": 1.1, "speaker_boost": "true"}).supplied()
    assert overridden["speed"] == 1.1 and overridden["speaker_boost"] is True
