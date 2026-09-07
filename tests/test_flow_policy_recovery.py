"""Flow policy rejection must rewind only the media inputs Flow actually sees."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import run_question_harvest_pipeline as qh  # noqa: E402


class NoProvider:
    """The recovery coordinator is tested without making browser/provider calls."""


def make_runner(tmp_path: Path) -> qh.Runner:
    project = tmp_path / "episode"
    return qh.Runner(NoProvider(), None, qh.QHState(project, "test", "topic"))


def policy_failure() -> qh.StageFailure:
    return qh.StageFailure(
        "flow_clip_b",
        "FAILED_VALIDATION",
        "flow/video_generate failed: Flow rejected the generation for policy reasons. "
        "Flow UI: This request did not follow our content policy.",
        error_code="flow_policy_violation",
    )


def call_recovery(runner: qh.Runner, project: Path) -> Path:
    return qh.stage_flow_clip_with_policy_recovery(
        runner, project, object(), "B", "original prompt",
        book_spread=project / "references" / "book_spread_frame.png",
        world_keyframe=project / "references" / "world_keyframe.png",
        world_keyframe_prompt="original keyframe prompt",
        world_style_anchor=project / "references" / "world_style_anchor.png",
        episode_plan={"book_template_id": "003"},
        model="gemini_omni_1_1_flash", resolution="720p", aspect_ratio="9:16", source_seconds=4,
    )


def test_policy_rejection_rewrites_prompt_and_regenerates_both_flow_frames(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = make_runner(tmp_path)
    project = runner.state.project
    attempts: list[str] = []
    repairs: list[tuple[str, int]] = []
    frames: list[tuple[str, bool]] = []
    covers: list[tuple[str, bool]] = []

    def fake_clip(*args, **kwargs):  # noqa: ANN002, ANN003
        attempts.append(args[4])
        if len(attempts) < 3:
            raise policy_failure()
        return project / "assets" / "opening" / "book_transition_source.mp4"

    def fake_repair(_runner, _project, _clip, prompt, _evidence, attempt):
        repairs.append((prompt, attempt))
        return f"safe prompt {attempt}"

    def fake_keyframe(_runner, _project, _content, prompt, _anchor, *, force=False):
        frames.append((prompt, force))
        return project / "references" / f"safe_world_{len(frames)}.png"

    def fake_cover(_runner, _project, _content, topic, anchor, *, force=False):
        covers.append((topic, force))
        return anchor.with_name(f"safe_book_{len(covers)}.png")

    monkeypatch.setattr(qh, "stage_flow_clip", fake_clip)
    monkeypatch.setattr(qh, "stage_flow_policy_repair_prompt", fake_repair)
    monkeypatch.setattr(qh, "stage_world_keyframe", fake_keyframe)
    monkeypatch.setattr(qh, "stage_topic_book_cover", fake_cover)

    result = call_recovery(runner, project)

    assert result.name == "book_transition_source.mp4"
    assert attempts == ["original prompt", "safe prompt 1", "safe prompt 2"]
    assert repairs == [("original prompt", 1), ("safe prompt 1", 2)]
    assert len(frames) == 2 and all(force for _, force in frames)
    assert all("FLOW POLICY-SAFE FRAME REVISION" in prompt for prompt, _ in frames)
    assert covers == [("topic", True), ("topic", True)]
    assert runner.state.done("flow_policy_recovery_b")


def test_non_policy_flow_failure_is_not_retried_or_rewritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = make_runner(tmp_path)
    project = runner.state.project
    calls = 0

    def fake_clip(*args, **kwargs):  # noqa: ANN002, ANN003
        nonlocal calls
        calls += 1
        raise qh.StageFailure("flow_clip_b", "FAILED", "Flow timed out", error_code="flow_generation_timeout")

    monkeypatch.setattr(qh, "stage_flow_clip", fake_clip)
    with pytest.raises(qh.StageFailure, match="timed out"):
        call_recovery(runner, project)
    assert calls == 1


def test_third_policy_rejection_stops_without_a_fourth_credit_spend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = make_runner(tmp_path)
    project = runner.state.project
    calls = 0

    def fake_clip(*args, **kwargs):  # noqa: ANN002, ANN003
        nonlocal calls
        calls += 1
        raise policy_failure()

    monkeypatch.setattr(qh, "stage_flow_clip", fake_clip)
    monkeypatch.setattr(qh, "stage_flow_policy_repair_prompt", lambda *args: "safe")
    monkeypatch.setattr(qh, "stage_world_keyframe", lambda *args, **kwargs: project / "safe.png")
    monkeypatch.setattr(qh, "stage_topic_book_cover", lambda *args, **kwargs: project / "safe-book.png")

    with pytest.raises(qh.StageFailure, match="after 3 policy-safe attempt"):
        call_recovery(runner, project)
    assert calls == qh.FLOW_POLICY_RETRY_LIMIT
