"""The user-visible pipeline has one stable stage taxonomy end to end."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from pipeline_stages import PIPELINE_STAGE_SEQUENCE, stage_title  # noqa: E402
from run_completion_pipeline import completion_stage_sequence  # noqa: E402


def test_independent_post_visual_work_has_its_own_visible_stage() -> None:
    expected = {
        "transition_direction", "elevenlabs_voiceover", "background_music", "ajil_alignment", "opening_trim",
        "build_timeline", "motion_director", "sfx_plan", "render_baseline", "qc_baseline", "sfx_acquire", "polish_audio", "qc_polished",
        "git_commit_push", "publish_telegram",
    }
    assert expected <= set(PIPELINE_STAGE_SEQUENCE)
    assert len(PIPELINE_STAGE_SEQUENCE) == len(set(PIPELINE_STAGE_SEQUENCE))


def test_titles_use_the_global_count_for_visual_and_render_stages() -> None:
    total = len(PIPELINE_STAGE_SEQUENCE)
    assert stage_title("body_images") == f"step 15/{total} · Body Images"
    assert stage_title("transition_direction") == f"step 16/{total} · Transition Direction"
    assert stage_title("render_baseline") == f"step 26/{total} · Render Baseline"


def test_completion_stage_sequence_gates_motion_without_changing_legacy_workflow() -> None:
    dynamic = completion_stage_sequence(
        motion_enabled=True, sfx_enabled=True, sfx_plan_enabled=True,
        publish=False, telegram_low_size=True, commit=False,
    )
    legacy = completion_stage_sequence(
        motion_enabled=False, sfx_enabled=True, sfx_plan_enabled=True,
        publish=False, telegram_low_size=True, commit=False,
    )
    assert dynamic == ["build_timeline", "motion_director", "sfx_plan", "render_baseline", "qc_baseline", "sfx_acquire", "polish_audio", "qc_polished"]
    assert legacy == [stage for stage in dynamic if stage != "motion_director"]
    planner_off = completion_stage_sequence(
        motion_enabled=False, sfx_enabled=True, sfx_plan_enabled=False,
        publish=False, telegram_low_size=True, commit=False,
    )
    assert "sfx_plan" not in planner_off and "sfx_acquire" in planner_off
