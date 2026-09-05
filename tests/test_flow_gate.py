"""A Flow outage must be told apart from a broken episode.

When Flow is unavailable the rest of the episode can still be produced. When a stage failed
for any other reason, waiting would hide a real fault — so the distinction has to be exact.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from flow_gate import blocked_only_on_flow, clips_ready, missing_clips  # noqa: E402


def write_state(project: Path, stages: dict) -> None:
    path = project / "pipeline" / "QH_RUNTIME_STATE.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema_version": 2, "stages": stages}), encoding="utf-8")


def make_clip(project: Path, name: str) -> None:
    path = project / "assets" / "opening" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"0" * 64)


def test_both_clips_missing_is_reported(tmp_path: Path) -> None:
    assert clips_ready(tmp_path) is False
    assert [path.name for path in missing_clips(tmp_path)] == [
        "question_spark_source.mp4", "book_transition_source.mp4",
    ]


def test_one_clip_present_is_still_not_ready(tmp_path: Path) -> None:
    make_clip(tmp_path, "question_spark_source.mp4")
    assert clips_ready(tmp_path) is False
    assert [path.name for path in missing_clips(tmp_path)] == ["book_transition_source.mp4"]


def test_an_empty_clip_file_does_not_count(tmp_path: Path) -> None:
    make_clip(tmp_path, "question_spark_source.mp4")
    (tmp_path / "assets" / "opening" / "book_transition_source.mp4").write_bytes(b"")
    assert clips_ready(tmp_path) is False


def test_both_clips_present_is_ready(tmp_path: Path) -> None:
    make_clip(tmp_path, "question_spark_source.mp4")
    make_clip(tmp_path, "book_transition_source.mp4")
    assert clips_ready(tmp_path) is True
    assert missing_clips(tmp_path) == []


def test_a_region_block_is_a_flow_only_block(tmp_path: Path) -> None:
    write_state(tmp_path, {
        "script_draft": {"status": "DONE"},
        "body_images": {"status": "DONE"},
        "flow_clip_a": {"status": "FAILED",
                        "message": "flow/video_generate failed: Google Flow is not available in this country."},
    })
    blocked, reason = blocked_only_on_flow(tmp_path)
    assert blocked is True
    assert "not available in this country" in reason


def test_high_demand_also_counts_as_an_outage(tmp_path: Path) -> None:
    write_state(tmp_path, {"flow_clip_b": {"status": "FAILED", "message": "Flow is experiencing high demand"}})
    assert blocked_only_on_flow(tmp_path)[0] is True


def test_a_flow_failure_that_is_not_an_outage_must_not_be_waited_out(tmp_path: Path) -> None:
    write_state(tmp_path, {
        "flow_clip_a": {"status": "FAILED",
                        "message": "flow reference policy violation: style_sheet refused"},
    })
    blocked, reason = blocked_only_on_flow(tmp_path)
    assert blocked is False
    assert "not a Flow outage" in reason


def test_another_failed_stage_makes_it_a_real_failure(tmp_path: Path) -> None:
    write_state(tmp_path, {
        "flow_clip_a": {"status": "FAILED", "message": "Google Flow is not available in this country"},
        "beat_image_003": {"status": "FAILED_VALIDATION", "message": "aspect_mismatch"},
    })
    blocked, reason = blocked_only_on_flow(tmp_path)
    assert blocked is False
    assert "beat_image_003" in reason


def test_no_failures_is_not_a_flow_block(tmp_path: Path) -> None:
    write_state(tmp_path, {"script_draft": {"status": "DONE"}})
    assert blocked_only_on_flow(tmp_path) == (False, "no failed stage recorded")


def test_a_missing_state_file_is_not_a_flow_block(tmp_path: Path) -> None:
    assert blocked_only_on_flow(tmp_path)[0] is False
