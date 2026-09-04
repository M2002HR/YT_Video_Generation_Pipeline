"""The panel's single-page API: status, incremental log tail, and resume (T9.1/T9.2)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

SPEC = importlib.util.spec_from_file_location("video_control_panel", SCRIPTS / "video_control_panel.py")
assert SPEC and SPEC.loader
panel = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = panel
SPEC.loader.exec_module(panel)


def _record(project: str = "videos/901_panel", **extra) -> dict:
    record = {
        "job_id": "11111111-2222-3333-4444-555555555555",
        "video_id": "901",
        "content_project": "question_harvest",
        "topic": "why panels matter",
        "project": project,
        "creative_brief": f"{project}/launch/CREATIVE_BRIEF.json",
        "voice_profile": f"{project}/voiceover/REQUESTED_VOICE_PROFILE.json",
        "aspect_ratio": "9:16",
        "music_provider": "pixabay",
        "status": "FAILED",
    }
    record.update(extra)
    return record


def test_launch_and_resume_build_the_same_command() -> None:
    """A resume that differs from the launch would produce a different episode (§78)."""
    record = _record()
    command = panel.pipeline_command(record)
    assert command[:3] == [sys.executable, "-u", "scripts/run_full_video_pipeline_qh_wrapper.py"]
    assert "--publish" in command
    assert "--commit" not in command
    assert panel.pipeline_command(record) == command, "the builder must be deterministic"


def test_the_commit_flag_is_carried_into_the_command() -> None:
    assert "--commit" in panel.pipeline_command(_record(commit_artifacts=True))


def test_the_music_provider_survives_into_a_resume() -> None:
    command = panel.pipeline_command(_record())
    assert command[command.index("--music-provider") + 1] == "pixabay"


def test_a_non_question_harvest_project_uses_the_generic_pipeline() -> None:
    command = panel.pipeline_command(
        _record(content_project="world_behind_the_question", duration_min_seconds=30, duration_max_seconds=45)
    )
    assert "scripts/run_full_video_pipeline.py" in command
    assert command[command.index("--min-duration-seconds") + 1] == "30"


def test_provider_status_reports_unreachable_rather_than_healthy(monkeypatch: pytest.MonkeyPatch) -> None:
    """A panel that shows green while Ordak is down would invite a doomed launch."""
    monkeypatch.setattr(panel, "ORDAK_BASE_URL", "http://127.0.0.1:1")
    status = panel.provider_status()
    assert status["reachable"] is False
    assert status["chrome_running"] is None
    assert set(status["providers"]) == set(panel.PROVIDERS)
    assert all(entry["logged_in"] is None for entry in status["providers"].values())


def test_pipeline_state_is_read_from_the_orchestrator_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(panel, "ROOT", tmp_path)
    project = tmp_path / "videos" / "901_panel"
    (project / "pipeline").mkdir(parents=True)
    (project / "pipeline" / "QH_RUNTIME_STATE.json").write_text(
        json.dumps(
            {
                "pipeline_state": "RUNNING",
                "stages": {
                    "script": {"status": "DONE"},
                    "world_keyframe": {"status": "REUSED"},
                    "flow_clip_a": {"status": "RUNNING"},
                    "flow_clip_b": {"status": "PENDING"},
                },
            }
        ),
        encoding="utf-8",
    )

    state = panel.pipeline_state_of({"project": "videos/901_panel"})
    assert state == {"pipeline_state": "RUNNING", "stage_count": 4, "done": 2, "running": "flow_clip_a"}


def test_a_project_without_state_reports_nothing_rather_than_guessing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(panel, "ROOT", tmp_path)
    assert panel.pipeline_state_of({"project": "videos/does_not_exist"}) == {}
    assert panel.pipeline_state_of({}) == {}


def test_job_records_marks_finished_runs_resumable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(panel, "ROOT", tmp_path)
    jobs = tmp_path / "control_panel" / "jobs"
    jobs.mkdir(parents=True)
    (jobs / "a.json").write_text(json.dumps(_record(status="FAILED")), encoding="utf-8")
    (jobs / "b.json").write_text(json.dumps(_record(status="RUNNING")), encoding="utf-8")
    (jobs / "c.json").write_text("{not json", encoding="utf-8")

    records = panel.job_records(jobs)
    assert len(records) == 2, "an unreadable record is skipped, not fatal"
    by_status = {record["status"]: record["_resumable"] for record in records}
    assert by_status == {"FAILED": True, "RUNNING": False}


class _Handler(panel.Handler):
    """Only log_tail is exercised, so the socket machinery is deliberately not built."""

    def __init__(self, jobs_dir: Path) -> None:  # noqa: D107 - test double
        self._jobs_dir = jobs_dir

    @property
    def jobs_dir(self) -> Path:
        return self._jobs_dir


def test_the_log_tail_is_incremental(tmp_path: Path) -> None:
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    job_id = "11111111-2222-3333-4444-555555555555"
    log = jobs / f"{job_id}.log"
    log.write_text("first line\n", encoding="utf-8")
    handler = _Handler(jobs)

    first = handler.log_tail(job_id, 0)
    assert first["text"] == "first line\n" and first["offset"] == log.stat().st_size

    with log.open("a", encoding="utf-8") as handle:
        handle.write("second line\n")
    second = handler.log_tail(job_id, first["offset"])
    assert second["text"] == "second line\n", "only the new bytes come back"
    assert handler.log_tail(job_id, second["offset"])["text"] == ""


def test_a_missing_log_reports_waiting(tmp_path: Path) -> None:
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    tail = _Handler(jobs).log_tail("11111111-2222-3333-4444-555555555555", 0)
    assert tail == {"offset": 0, "text": "", "waiting": True}


def test_a_far_behind_reader_gets_the_tail_not_the_whole_file(tmp_path: Path) -> None:
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    job_id = "11111111-2222-3333-4444-555555555555"
    (jobs / f"{job_id}.log").write_text("x" * 500_000, encoding="utf-8")
    tail = _Handler(jobs).log_tail(job_id, 0)
    assert len(tail["text"]) == 200_000
    assert tail["offset"] == 500_000
