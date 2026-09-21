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


def test_timeline_reuse_rejects_an_old_missing_closing_beat(tmp_path: Path) -> None:
    (tmp_path / "timeline").mkdir()
    (tmp_path / "timing").mkdir()
    (tmp_path / "timeline/TIMELINE.json").write_text(json.dumps({
        "duration": 20, "beats": [
            {"beat_id": 1, "media_type": "image", "narration": "Body sentence."},
        ],
    }), encoding="utf-8")
    (tmp_path / "timing/BEAT_TIMINGS.json").write_text(json.dumps({
        "audio_duration_seconds": 20, "beats": [
            {"beat_id": 1, "narration": "Body sentence."},
            {"beat_id": 2, "narration": "Closing sentence."},
        ],
    }), encoding="utf-8")
    assert completion.timeline_matches_current_timing(tmp_path) is False


def test_timeline_reuse_rejects_a_legacy_seven_image_timeline_after_density_upgrade(tmp_path: Path) -> None:
    (tmp_path / "timeline").mkdir()
    (tmp_path / "timing").mkdir()
    (tmp_path / "creative").mkdir()
    (tmp_path / "timeline/TIMELINE.json").write_text(json.dumps({
        "duration": 20, "beats": [
            {"beat_id": 1, "media_type": "image", "narration": "Body sentence."},
        ],
    }), encoding="utf-8")
    (tmp_path / "timing/BEAT_TIMINGS.json").write_text(json.dumps({
        "audio_duration_seconds": 20, "beats": [
            {"beat_id": 1, "narration": "Body sentence."},
        ],
    }), encoding="utf-8")
    (tmp_path / "creative/BODY_ASSET_SCHEDULE.json").write_text(json.dumps({
        "schema_version": 1,
        "assets": [
            {"beat_id": 1, "semantic_beat_id": 1},
            {"beat_id": 2, "semantic_beat_id": 1},
        ],
    }), encoding="utf-8")
    assert completion.timeline_matches_current_timing(tmp_path) is False


def test_final_step_leaves_top_status_running_until_finalized(tmp_path: Path, monkeypatch) -> None:
    """Every per-stage step (including the last git_commit_push) leaves RUNNING."""
    state_path = tmp_path / "state.json"
    state = {"status": "RUNNING", "events": []}
    monkeypatch.setattr(completion.subprocess, "run", lambda *args, **kwargs: None)
    completion.execute("git_commit_push", ["tool"], state, state_path)
    saved = json.loads(state_path.read_text())
    assert saved["events"][-1]["status"] == "DONE"
    assert saved["status"] == "RUNNING"


def test_mark_finalization_done_flips_fully_passed_state(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({
        "schema_version": 1, "status": "RUNNING",
        "events": [{"stage": "git_commit_push", "status": "DONE"}],
    }), encoding="utf-8")
    final = completion.mark_finalization_done(state_path)
    assert final["status"] == "DONE"
    assert final["completed_at"]
    assert json.loads(state_path.read_text())["status"] == "DONE"
