from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from plan_opening_sources import OpeningSourcePlanError, build_plan, choose_source_seconds  # noqa: E402
from run_graph import affected_nodes, graph_for  # noqa: E402


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_planner_uses_real_boundaries_and_supported_durations(tmp_path: Path) -> None:
    write_json(tmp_path / "timing/OPENING_TIMING.json", {"spark_end": 5.76, "transition_end": 12.0})
    write_json(tmp_path / "launch/CREATIVE_BRIEF.json", {"_q_station": {
        "flow_video_model": "gemini_omni_1_1_flash",
        "opening_a_source_seconds": 6,
        "opening_b_source_seconds": 4,
        "opening_speed_tolerance": 0.2,
    }})
    plan = build_plan(tmp_path)
    assert plan["clips"]["A"]["selected_source_seconds"] == 6
    assert plan["clips"]["B"]["selected_source_seconds"] == 6
    assert plan["clips"]["B"]["estimated_rate_adjusted"] is True
    assert plan["verified_source_seconds"] == [4, 6, 8, 10]


def test_planner_never_selects_an_unverified_five_second_duration(tmp_path: Path) -> None:
    write_json(tmp_path / "timing/OPENING_TIMING.json", {"spark_end": 4.7, "transition_end": 10.22})
    write_json(tmp_path / "launch/CREATIVE_BRIEF.json", {"_q_station": {
        "flow_video_model": "gemini_omni_1_1_flash",
        "opening_a_source_seconds": 4,
        "opening_b_source_seconds": 4,
        "opening_speed_tolerance": 0.2,
    }})
    plan = build_plan(tmp_path)
    assert plan["clips"]["A"]["selected_source_seconds"] == 4
    assert plan["clips"]["B"]["selected_source_seconds"] == 6


def test_unknown_model_stops_before_any_flow_request(tmp_path: Path) -> None:
    write_json(tmp_path / "timing/OPENING_TIMING.json", {"spark_end": 4.0, "transition_end": 8.0})
    write_json(tmp_path / "launch/CREATIVE_BRIEF.json", {"_q_station": {
        "flow_video_model": "veo_3_1_fast",
        "opening_a_source_seconds": 4,
        "opening_b_source_seconds": 4,
    }})
    with pytest.raises(OpeningSourcePlanError, match="No verified Flow duration capability"):
        build_plan(tmp_path)


def test_planner_refuses_a_target_no_supported_duration_can_truthfully_reach() -> None:
    with pytest.raises(OpeningSourcePlanError, match="longest supported source"):
        choose_source_seconds(10.0, 4, (3, 4, 6, 8), 0.2)


def test_zero_tolerance_remains_a_valid_strict_setting() -> None:
    plan = choose_source_seconds(4.0, 4, (3, 4, 6, 8), 0.0)
    assert plan["selected_source_seconds"] == 4
    assert plan["estimated_rate_adjusted"] is False


def test_opening_source_plan_invalidates_both_prompts_and_clips(tmp_path: Path) -> None:
    write_json(tmp_path / "launch/LAUNCH_REQUEST.json", {"content_project": "q_station"})
    graph = graph_for(tmp_path, include_disabled=True)
    affected = affected_nodes(graph, ["opening_source_plan"])
    assert {"flow_prompt_a", "flow_prompt_b", "flow_clip_a", "flow_clip_b", "opening_trim", "build_timeline"} <= affected
