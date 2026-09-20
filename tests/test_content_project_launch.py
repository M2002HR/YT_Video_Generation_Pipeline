from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from content_projects import (
    list_content_projects,
    load_content_project,
    resolve_project_id,
    validate_content_project,
    video_slug,
)
from video_control_panel import Handler, form_text


def test_q_station_is_the_only_complete_content_project() -> None:
    project = load_content_project("q_station")
    preset = validate_content_project(project)
    assert project.config["status"] == "production_ready"
    assert project.project_id == "q_station"
    assert project.aliases == ()
    assert preset.name == "001_home_world"
    assert [item.project_id for item in list_content_projects()] == ["q_station"]


def test_retired_project_ids_do_not_resolve() -> None:
    retired = (
        "_".join(("question", "harvest")),
        "_".join(("world", "behind", "the", "question")),
    )
    for project_id in retired:
        assert resolve_project_id(project_id) == project_id
        with pytest.raises(RuntimeError, match="Unknown content project"):
            load_content_project(project_id)


def test_panel_exposes_q_station_and_editorial_inputs() -> None:
    page = Handler.page(Handler.__new__(Handler))
    assert "q_station" in page
    assert "value='q_station' selected" in page
    for field in ("working_title", "audience", "narrative_angle", "must_include", "must_avoid", "source_notes"):
        assert f"name={field}" in page
    for field in ("hero_presence_mode", "world_style_policy", "flow_video_model", "flow_resolution", "opening_a_seconds", "opening_b_seconds"):
        assert f"name={field}" in page
    assert "name=gemini_image_model" in page
    assert "name=image_provider" in page
    assert "ChatGPT · project chat · Extra High" in page
    assert "name=world_style_id" in page
    assert "name=world_style_hint" in page
    for locked in ("ChatGPT", "Gemini", "Google Flow"):
        assert locked in page
    assert page.count("disabled") >= 5


def test_panel_form_text_is_bounded() -> None:
    assert form_text({"topic": ["  A question?  "]}, "topic", 20) == "A question?"


def test_video_slug_is_identical_for_every_runner_edge_case() -> None:
    assert video_slug("Why   time?? feels FAST") == "why_time_feels_fast"
    assert video_slug("چرا زمان سریع می‌گذرد؟") == "video"
