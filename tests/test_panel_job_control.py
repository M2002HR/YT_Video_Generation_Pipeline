"""Every job must be stoppable and deletable, and a watcher must not block a launch.

A watcher spends most of its life asleep. Counting it as the active job would mean one
Flow outage stops the studio from starting anything else.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import video_control_panel as panel  # noqa: E402


@pytest.fixture()
def jobs_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "jobs"
    directory.mkdir()
    return directory


def write(jobs_dir: Path, job: dict) -> Path:
    path = jobs_dir / f"{job['job_id']}.json"
    path.write_text(json.dumps(job), encoding="utf-8")
    return path


def test_a_watcher_is_not_the_active_job(jobs_dir: Path, monkeypatch) -> None:
    monkeypatch.setattr(panel, "pid_is_live", lambda pid: True)
    write(jobs_dir, {"job_id": "w", "kind": "flow_watcher", "status": "RUNNING", "pid": 1234})
    assert panel.active_job(jobs_dir) is None


def test_a_running_episode_is_the_active_job(jobs_dir: Path, monkeypatch) -> None:
    monkeypatch.setattr(panel, "pid_is_live", lambda pid: True)
    write(jobs_dir, {"job_id": "e", "kind": "episode", "status": "RUNNING", "pid": 99, "video_id": "010"})
    assert (panel.active_job(jobs_dir) or {}).get("job_id") == "e"


def test_watchers_are_found_by_episode(jobs_dir: Path) -> None:
    write(jobs_dir, {"job_id": "w1", "kind": "flow_watcher", "status": "RUNNING", "video_id": "010"})
    write(jobs_dir, {"job_id": "w2", "kind": "flow_watcher", "status": "STOPPED", "video_id": "010"})
    write(jobs_dir, {"job_id": "w3", "kind": "flow_watcher", "status": "RUNNING", "video_id": "011"})
    assert [job["job_id"] for job in panel.watchers_for(jobs_dir, "010")] == ["w1"]


def test_no_video_id_matches_no_watcher(jobs_dir: Path) -> None:
    write(jobs_dir, {"job_id": "w1", "kind": "flow_watcher", "status": "RUNNING", "video_id": "010"})
    assert panel.watchers_for(jobs_dir, None) == []


def test_terminating_a_dead_job_reports_nothing_to_do(monkeypatch) -> None:
    monkeypatch.setattr(panel, "pid_is_live", lambda pid: False)
    assert panel.terminate_job({"pid": 4242}) is False


def test_terminating_signals_the_process_group(monkeypatch) -> None:
    signalled: list[tuple[int, int]] = []
    alive = {"value": True}

    monkeypatch.setattr(panel, "pid_is_live", lambda pid: alive["value"])
    monkeypatch.setattr(panel.os, "getpgid", lambda pid: 777)

    def fake_killpg(pgid: int, sig: int) -> None:
        signalled.append((pgid, sig))
        alive["value"] = False

    monkeypatch.setattr(panel.os, "killpg", fake_killpg)
    assert panel.terminate_job({"pid": 4242}) is True
    assert signalled and signalled[0][0] == 777


def test_only_a_live_job_is_stoppable(jobs_dir: Path, monkeypatch) -> None:
    monkeypatch.setattr(panel, "pid_is_live", lambda pid: pid == 1)
    monkeypatch.setattr(panel, "pipeline_state_of", lambda record: {})
    monkeypatch.setattr(panel, "flow_pending_of", lambda record: {})
    write(jobs_dir, {"job_id": "a", "kind": "episode", "status": "RUNNING", "pid": 1,
                     "video_id": "010", "project": "videos/010_x"})
    write(jobs_dir, {"job_id": "b", "kind": "episode", "status": "FAILED", "pid": 2,
                     "video_id": "009", "project": "videos/009_x"})
    records = {job["job_id"]: job for job in panel.job_records(jobs_dir)}
    assert records["a"]["_stoppable"] is True and records["a"]["_resumable"] is False
    assert records["b"]["_stoppable"] is False and records["b"]["_resumable"] is True


def test_a_watcher_is_never_resumable(jobs_dir: Path, monkeypatch) -> None:
    monkeypatch.setattr(panel, "pid_is_live", lambda pid: False)
    write(jobs_dir, {"job_id": "w", "kind": "flow_watcher", "status": "STOPPED",
                     "video_id": "010", "project": "videos/010_x"})
    record = panel.job_records(jobs_dir)[0]
    assert record["_resumable"] is False


def test_a_second_watcher_is_not_started_for_the_same_episode(jobs_dir: Path, monkeypatch) -> None:
    monkeypatch.setattr(panel, "pid_is_live", lambda pid: True)
    write(jobs_dir, {"job_id": "w", "kind": "flow_watcher", "status": "RUNNING",
                     "video_id": "010", "pid": 5})
    assert panel.flow_watcher_alive(jobs_dir, "010") is True
    assert panel.ensure_flow_watcher(jobs_dir, {"video_id": "010", "project": "videos/010_x"}) is None
