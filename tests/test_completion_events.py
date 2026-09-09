from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import run_completion_pipeline as completion


def test_stage_is_persisted_running_before_the_child_finishes(tmp_path: Path, monkeypatch) -> None:
    state_path = tmp_path / "state.json"
    state = {"status": "RUNNING", "events": []}
    observed = {}
    artifact = tmp_path / "result.json"

    def run(*args, **kwargs):
        observed.update(json.loads(state_path.read_text()))
        artifact.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(completion.subprocess, "run", run)
    completion.execute("build_timeline", ["tool"], state, state_path, artifact=artifact, video=tmp_path)

    assert observed["events"][0]["status"] == "RUNNING"
    saved = json.loads(state_path.read_text())
    assert len(saved["events"]) == 1
    assert saved["events"][0]["status"] == "DONE"


def test_failed_stage_updates_the_same_event(tmp_path: Path, monkeypatch) -> None:
    state_path = tmp_path / "state.json"
    state = {"status": "RUNNING", "events": []}
    monkeypatch.setattr(completion.subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(subprocess.CalledProcessError(7, ["tool"])))
    try:
        completion.execute("render_baseline", ["tool"], state, state_path)
    except subprocess.CalledProcessError:
        pass
    saved = json.loads(state_path.read_text())
    assert saved["status"] == "FAILED"
    assert len(saved["events"]) == 1
    assert saved["events"][0]["status"] == "FAILED"
    assert saved["events"][0]["returncode"] == 7


def test_success_without_the_required_artifact_fails_validation(
    tmp_path: Path, monkeypatch
) -> None:
    state_path = tmp_path / "state.json"
    state = {"status": "RUNNING", "events": []}
    monkeypatch.setattr(completion.subprocess, "run", lambda *args, **kwargs: None)

    with pytest.raises(RuntimeError, match="did not produce"):
        completion.execute(
            "render_baseline",
            ["tool"],
            state,
            state_path,
            artifact=tmp_path / "missing.mp4",
            video=tmp_path,
        )

    saved = json.loads(state_path.read_text())
    assert saved["status"] == "FAILED"
    assert len(saved["events"]) == 1
    assert saved["events"][0]["status"] == "FAILED_VALIDATION"
