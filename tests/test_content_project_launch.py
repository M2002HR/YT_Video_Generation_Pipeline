from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from content_projects import load_content_project, resolve_pipeline_prompt, validate_content_project, video_slug
from video_control_panel import Handler, form_text


def test_question_project_is_complete_and_has_world_design_stage() -> None:
    project = load_content_project("world_behind_the_question")
    preset = validate_content_project(project)
    assert project.config["status"] == "production_ready"
    assert preset.name == "001_library_seeker"
    assert resolve_pipeline_prompt(project, project.config["world_design_prompt"]).name == "00_world_designer.md"
    assert (preset / "style_anchor.png").stat().st_size > 10_000
    assert (preset / "character_anchor.png").stat().st_size > 10_000


def test_panel_exposes_project_and_editorial_inputs() -> None:
    page = Handler.page(Handler.__new__(Handler))
    assert "world_behind_the_question" in page
    assert "value='world_behind_the_question' selected" in page
    for field in ("working_title", "audience", "narrative_angle", "must_include", "must_avoid", "source_notes"):
        assert f"name={field}" in page


def test_panel_form_text_is_bounded() -> None:
    assert form_text({"topic": ["  A question?  "]}, "topic", 20) == "A question?"


def test_video_slug_is_identical_for_every_runner_edge_case() -> None:
    assert video_slug("Why   time?? feels FAST") == "why_time_feels_fast"
    assert video_slug("چرا زمان سریع می‌گذرد؟") == "video"
