"""Anti-repetition: what an episode used is recorded, and the next one may not reuse it (§35, T5.6)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import episode_history as history
from episode_history import (
    HISTORY_KEYS,
    EpisodeHistoryError,
    avoidance_note,
    recent,
    record_traits,
    repeated_traits,
    traits_from_plans,
    used_values,
)


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(history, "ROOT", tmp_path)
    registry = tmp_path / "projects" / "question_harvest" / "VIDEOS.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(
        json.dumps({"schema_version": 1, "project_id": "question_harvest", "videos": []}),
        encoding="utf-8",
    )
    return "question_harvest"


def test_traits_are_recorded_and_read_back(project: str) -> None:
    record_traits(project, "010_kettle", {
        "opening_activity": "boiling a kettle",
        "opening_location": "a narrow kitchen",
        "camera_pattern": "slow push in",
        "book_template_id": "002",
        "world_style_id": "001_woodcut_charcoal",
    })

    entries = recent(project)
    assert len(entries) == 1
    assert entries[0]["opening_activity"] == "boiling a kettle"
    assert all(key in entries[0] for key in HISTORY_KEYS)


def test_recording_the_same_episode_twice_does_not_duplicate_it(project: str) -> None:
    record_traits(project, "010_kettle", {"opening_activity": "boiling a kettle"})
    record_traits(project, "010_kettle", {"opening_location": "a narrow kitchen"})

    entries = recent(project)
    assert len(entries) == 1
    assert entries[0]["opening_activity"] == "boiling a kettle", "an earlier trait survives"
    assert entries[0]["opening_location"] == "a narrow kitchen"


def test_history_is_ordered_by_video_number_and_limited(project: str) -> None:
    for index in (12, 9, 11, 10):
        record_traits(project, f"{index:03d}_episode", {"opening_activity": f"activity {index}"})

    assert [entry["video_id"] for entry in recent(project, limit=10)] == [
        "009_episode", "010_episode", "011_episode", "012_episode",
    ]
    assert [entry["video_id"] for entry in recent(project, limit=2)] == [
        "011_episode", "012_episode",
    ]


def test_a_legacy_string_registry_is_upgraded_in_place(project: str, tmp_path: Path) -> None:
    registry = tmp_path / "projects" / "question_harvest" / "VIDEOS.json"
    registry.write_text(
        json.dumps({"schema_version": 1, "project_id": "question_harvest",
                    "videos": ["008_old_episode"]}),
        encoding="utf-8",
    )
    record_traits(project, "009_new_episode", {"opening_activity": "folding laundry"})

    stored = json.loads(registry.read_text(encoding="utf-8"))["videos"]
    assert all(isinstance(entry, dict) for entry in stored)
    assert [entry["video_id"] for entry in stored] == ["008_old_episode", "009_new_episode"]


def test_a_missing_registry_yields_no_history_rather_than_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(history, "ROOT", tmp_path)
    assert recent("nonexistent_project") == []


def test_a_malformed_registry_is_refused_on_write(project: str, tmp_path: Path) -> None:
    registry = tmp_path / "projects" / "question_harvest" / "VIDEOS.json"
    registry.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
    with pytest.raises(EpisodeHistoryError):
        record_traits(project, "010_x", {"opening_activity": "a"})


def test_a_repeated_opening_is_detected_case_and_space_insensitively() -> None:
    past = [{"opening_activity": "Boiling  a Kettle", "opening_location": "a narrow kitchen"}]
    repeats = repeated_traits(
        {"opening_activity": "boiling a kettle", "opening_location": "a rooftop"}, past
    )
    assert repeats == {"opening_activity": "boiling a kettle"}


def test_a_fresh_opening_is_not_flagged() -> None:
    past = [{"opening_activity": "boiling a kettle", "camera_pattern": "slow push in"}]
    assert repeated_traits({"opening_activity": "folding laundry", "camera_pattern": "static"}, past) == {}


def test_reusing_a_book_template_or_world_style_is_allowed() -> None:
    """Those are deliberate reuse decisions, not repetition to be penalised."""
    past = [{"book_template_id": "002", "world_style_id": "001_woodcut_charcoal"}]
    assert repeated_traits({"book_template_id": "002", "world_style_id": "001_woodcut_charcoal"}, past) == {}


def test_used_values_skips_blanks() -> None:
    past = [{"opening_activity": "a"}, {"opening_activity": ""}, {}, {"opening_activity": "b"}]
    assert used_values(past, "opening_activity") == ["a", "b"]


def test_the_avoidance_note_names_what_must_not_repeat() -> None:
    note = avoidance_note([
        {"opening_activity": "boiling a kettle", "camera_pattern": "slow push in"},
        {"opening_activity": "folding laundry"},
    ])
    assert "boiling a kettle" in note and "folding laundry" in note
    assert "slow push in" in note
    assert "none may be repeated" in note


def test_the_note_is_explicit_when_there_is_no_history() -> None:
    assert "No previous episodes" in avoidance_note([])


def test_traits_are_collected_from_the_stage_artifacts() -> None:
    traits = traits_from_plans(
        {"opening_activity": "boiling a kettle", "opening_location": "a kitchen",
         "camera_pattern": "push in", "book_template_id": "003"},
        {"style_id": "002_ink_wash"},
    )
    assert traits == {
        "opening_activity": "boiling a kettle",
        "opening_location": "a kitchen",
        "camera_pattern": "push in",
        "book_template_id": "003",
        "world_style_id": "002_ink_wash",
    }


def test_a_reused_world_style_is_recorded_by_the_id_it_reuses() -> None:
    traits = traits_from_plans({"opening_activity": "a"}, {"decision": "reuse", "reuse_of": "001_woodcut"})
    assert traits["world_style_id"] == "001_woodcut"


class DirectorSpy:
    """Stands in for the ChatGPT stage: returns scripted plans and records the prompts."""

    def __init__(self, plans: list[dict]) -> None:
        self.plans = list(plans)
        self.prompts: list[str] = []
        self.state = _State()
        self.notifier = None

    def stage_start(self, stage: str) -> float:
        return 0.0

    def stage_done(self, stage: str, started: float, summary: str = "", **meta) -> None:
        self.state.marked.append(stage)

    def stage_reused(self, stage: str, summary: str = "") -> None:
        self.state.marked.append(f"reused:{stage}")

    def json(self, stage: str, prompt: str):
        self.prompts.append(prompt)
        return self.plans.pop(0)


class _State:
    def __init__(self) -> None:
        self.marked: list[str] = []

    def done(self, stage: str) -> bool:
        return False

    def mark(self, stage: str, status: str, **extra) -> None:
        self.marked.append(stage)


def _director_project(tmp_path: Path):
    from content_projects import load_content_project

    project = tmp_path / "videos" / "011_director"
    (project / "creative").mkdir(parents=True)
    return project, load_content_project("question_harvest")


def test_the_director_retries_once_when_it_repeats_a_recent_opening(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import run_question_harvest_pipeline as qh

    project, content_project = _director_project(tmp_path)
    monkeypatch.setattr(
        qh, "_recent_history", lambda *a, **k: [{"opening_activity": "boiling a kettle"}]
    )
    runner = DirectorSpy([
        {"opening_activity": "Boiling a kettle", "opening_location": "kitchen"},
        {"opening_activity": "folding laundry", "opening_location": "hallway"},
    ])

    plan = qh.stage_episode_director(runner, project, content_project, "why kettles sing", "brief", {"full_narration": "n"})

    assert plan["opening_activity"] == "folding laundry"
    assert len(runner.prompts) == 2
    assert "previous plan repeated" in runner.prompts[1]
    assert "boiling a kettle" in runner.prompts[0], "the note lists what to avoid up front"


def test_a_director_that_keeps_repeating_fails_the_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import run_question_harvest_pipeline as qh

    project, content_project = _director_project(tmp_path)
    monkeypatch.setattr(
        qh, "_recent_history", lambda *a, **k: [{"opening_activity": "boiling a kettle"}]
    )
    runner = DirectorSpy([
        {"opening_activity": "boiling a kettle"},
        {"opening_activity": "boiling a kettle"},
    ])

    with pytest.raises(qh.StageFailure) as excinfo:
        qh.stage_episode_director(runner, project, content_project, "topic", "brief", {"full_narration": "n"})
    assert excinfo.value.state == "FAILED_VALIDATION"
    assert "still repeats" in excinfo.value.message


def test_a_first_episode_is_accepted_without_a_correction_round(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import run_question_harvest_pipeline as qh

    project, content_project = _director_project(tmp_path)
    monkeypatch.setattr(qh, "_recent_history", lambda *a, **k: [])
    runner = DirectorSpy([{"opening_activity": "boiling a kettle"}])

    plan = qh.stage_episode_director(runner, project, content_project, "topic", "brief", {"full_narration": "n"})

    assert plan["opening_activity"] == "boiling a kettle"
    assert len(runner.prompts) == 1
    assert (project / "creative" / "EPISODE_PLAN.json").is_file()
