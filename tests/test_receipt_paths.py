"""A project-level asset must not crash the receipt writer.

The book design sheet is shared by every episode, so it is written into the content
project's preset directory rather than the episode directory. ``relative_to(project)``
raises for it, which failed the stage *after* the image had already been paid for.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from run_question_harvest_pipeline import _receipt_path  # noqa: E402


def test_an_episode_asset_is_relative_to_the_episode() -> None:
    project = ROOT / "videos" / "010_demo"
    assert _receipt_path(project, project / "references" / "world_keyframe.png") == (
        "references/world_keyframe.png"
    )


def test_a_shared_asset_is_relative_to_the_repository() -> None:
    project = ROOT / "videos" / "010_demo"
    shared = ROOT / "projects" / "question_harvest" / "visual_presets" / "001_home_world" / "book_design_sheet.png"
    assert _receipt_path(project, shared) == (
        "projects/question_harvest/visual_presets/001_home_world/book_design_sheet.png"
    )


def test_a_path_outside_both_is_returned_whole() -> None:
    outside = Path("/tmp/somewhere/else.png")
    assert _receipt_path(ROOT / "videos" / "010_demo", outside) == "/tmp/somewhere/else.png"
