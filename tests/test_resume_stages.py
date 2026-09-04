"""Restarting a run must never regenerate what was already paid for (§78, §102, T6.5).

Each expensive stage is called twice: once with the artifact and state already in place,
and once from scratch. The reuse path must not touch the provider at all — the Ordak client
here raises on any call, so a single stray request fails the test rather than quietly
spending credits.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_question_harvest_pipeline as qh
from run_question_harvest_pipeline import QHState, Runner


class ForbiddenJobs:
    """Any provider call is a test failure: a resumed stage must spend nothing."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def run(self, *args, **kwargs):  # noqa: ANN002, ANN003
        self.calls.append(str(kwargs.get("provider")))
        raise AssertionError(
            f"a resumed stage called {kwargs.get('provider')}/{kwargs.get('mode')}"
        )

    def download(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("a resumed stage downloaded an artifact again")


def _content_project():
    """The real project config — reuse logic must work against real prompt paths."""
    from content_projects import load_content_project

    return load_content_project("question_harvest")


def _png(path: Path, *, seed: int = 1) -> Path:
    """Detailed enough to clear the pipeline's minimum-size floor for a real image."""
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", f"testsrc2=s=1080x1920:r=24:d=1", "-frames:v", "1",
         "-vf", f"hue=h={seed * 37}", str(path)],
        check=True, capture_output=True, timeout=60,
    )
    assert path.stat().st_size >= qh.MIN_IMAGE_BYTES
    return path


def _mp4(path: Path, seconds: float = 1.6) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", f"testsrc2=s=1080x1920:r=24:d={seconds}", "-t", f"{seconds}",
         "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20", str(path)],
        check=True, capture_output=True, timeout=120,
    )
    assert path.stat().st_size >= qh.MIN_VIDEO_BYTES
    return path


def _receipt(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"provider": "test", "model_verified": True}), encoding="utf-8")
    return path


@pytest.fixture
def project(tmp_path: Path) -> Path:
    directory = tmp_path / "videos" / "901_resume"
    (directory / "pipeline").mkdir(parents=True)
    (directory / "launch").mkdir(parents=True)
    (directory / "launch" / "LAUNCH_REQUEST.json").write_text(
        json.dumps({"image_generation": {"model": "nano_banana_pro"}}), encoding="utf-8"
    )
    return directory


@pytest.fixture
def runner(project: Path) -> Runner:
    state = QHState(project, "901_resume", "resume topic")
    return Runner(ForbiddenJobs(), None, state)


def _mark_done(runner: Runner, stage: str) -> None:
    runner.state.mark(stage, qh.STATE_DONE)


def test_world_keyframe_is_reused_after_a_restart(runner: Runner, project: Path) -> None:
    target = _png(project / "references" / "world_keyframe.png")
    _receipt(project / "pipeline" / "provider_receipts" / "gemini_world_keyframe.json")
    _mark_done(runner, "world_keyframe")

    result = qh.stage_world_keyframe(
        runner, project, _content_project(), "a prompt", project / "references" / "anchor.png"
    )
    assert result == target
    assert runner.state.done("world_keyframe")


def test_world_keyframe_without_its_receipt_is_not_treated_as_done(
    runner: Runner, project: Path
) -> None:
    """An image with no receipt cannot be shown to have come from the right model."""
    _png(project / "references" / "world_keyframe.png")
    _mark_done(runner, "world_keyframe")

    with pytest.raises(AssertionError, match="called gemini"):
        qh.stage_world_keyframe(
            runner, project, _content_project(), "a prompt", project / "references" / "anchor.png"
        )


def test_world_style_anchor_is_reused_after_a_restart(runner: Runner, project: Path) -> None:
    target = _png(project / "references" / "world_style_anchor.png", seed=2)
    _mark_done(runner, "world_style_anchor")

    result = qh.stage_world_style_anchor(
        runner, project, _content_project(), {"decision": "new", "medium": "woodcut"}
    )
    assert result == target


def test_book_design_sheet_is_reused_when_the_canonical_asset_exists(
    runner: Runner, project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sheet = _png(tmp_path / "presets" / "book_design_sheet.png", seed=3)
    monkeypatch.setattr(qh, "book_design_sheet_path", lambda content_project: sheet)

    result = qh.stage_book_design_sheet(runner, project, _content_project())
    assert result == sheet
    assert runner.state.done("book_design_sheet")


def test_book_spread_is_reused_after_a_restart(runner: Runner, project: Path) -> None:
    target = _png(project / "references" / "book_spread_frame.png", seed=4)
    _mark_done(runner, "book_spread")

    result = qh.stage_book_spread(
        runner, project, project / "references" / "world_keyframe.png", {"book_template_id": "001"}
    )
    assert result == target


def test_book_spread_recomposes_when_the_frame_is_missing(
    runner: Runner, project: Path
) -> None:
    """The compositor is free (no credits), but it still must not be skipped silently."""
    world = _png(project / "references" / "world_keyframe.png", seed=5)
    result = qh.stage_book_spread(runner, project, world, {"book_template_id": "002"})
    assert result.is_file()
    assert (project / "creative" / "BOOK_SPREAD_META.json").is_file()


@pytest.mark.parametrize(
    "clip,filename,receipt_name",
    [("A", "question_spark_source.mp4", "flow_opening_a"),
     ("B", "book_transition_source.mp4", "flow_opening_b")],
)
def test_flow_clips_are_reused_after_a_restart(
    runner: Runner, project: Path, clip: str, filename: str, receipt_name: str
) -> None:
    target = _mp4(project / "assets" / "opening" / filename)
    _receipt(project / "pipeline" / "provider_receipts" / f"{receipt_name}.json")
    _mark_done(runner, f"flow_clip_{clip.lower()}")

    result = qh.stage_flow_clip(
        runner, project, _content_project(), clip, "a prompt",
        book_spread=None, world_keyframe=None,
        model="gemini_omni_1_1_flash", resolution="720p", aspect_ratio="9:16", source_seconds=5,
    )
    assert result == target


def test_a_flow_clip_without_its_receipt_is_not_treated_as_done(
    runner: Runner, project: Path
) -> None:
    _mp4(project / "assets" / "opening" / "question_spark_source.mp4")
    _mark_done(runner, "flow_clip_a")

    with pytest.raises(AssertionError, match="called flow"):
        qh.stage_flow_clip(
            runner, project, _content_project(), "A", "a prompt",
            book_spread=None, world_keyframe=None,
            model="gemini_omni_1_1_flash", resolution="720p", aspect_ratio="9:16", source_seconds=5,
        )


def test_body_images_already_on_disk_are_reused(runner: Runner, project: Path) -> None:
    for beat_id in (1, 2, 3):
        _png(project / "assets" / "raw_beats" / f"beat_{beat_id:03d}.png", seed=beat_id)
    visual_plan = {"beats": [{"beat_id": index} for index in (1, 2, 3)]}

    produced = qh.stage_body_images(
        runner, project, _content_project(), visual_plan,
        {"medium": "woodcut"},
        project / "references" / "world_style_anchor.png",
        project / "references" / "world_keyframe.png",
    )
    assert [path.name for path in produced] == ["beat_001.png", "beat_002.png", "beat_003.png"]
    for beat_id in (1, 2, 3):
        assert runner.state.done(f"beat_image_{beat_id:03d}")


def test_a_missing_body_image_is_regenerated_and_the_rest_are_not(
    runner: Runner, project: Path
) -> None:
    _png(project / "assets" / "raw_beats" / "beat_001.png", seed=1)
    _png(project / "assets" / "raw_beats" / "beat_003.png", seed=3)
    visual_plan = {"beats": [{"beat_id": index} for index in (1, 2, 3)]}

    with pytest.raises(AssertionError, match="called chatgpt|called gemini"):
        qh.stage_body_images(
            runner, project, _content_project(), visual_plan,
            {"medium": "woodcut"},
            project / "references" / "world_style_anchor.png",
            project / "references" / "world_keyframe.png",
        )
    assert runner.state.done("beat_image_001")
    assert not runner.state.done("beat_image_002")


def test_stage_state_survives_a_fresh_state_object(project: Path) -> None:
    """Resume works across processes because every transition is written to disk (§81)."""
    first = QHState(project, "901_resume", "topic")
    first.mark("world_keyframe", qh.STATE_DONE, sha256="abc")

    reloaded = QHState(project, "901_resume", "topic")
    assert reloaded.done("world_keyframe")
    assert reloaded.state["stages"]["world_keyframe"]["sha256"] == "abc"
    assert not reloaded.done("flow_clip_a")
