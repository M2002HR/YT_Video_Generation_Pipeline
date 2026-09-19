"""Regressions for the project-wide ChatGPT image-provider lock."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_q_station_pipeline as qstation


def picture(path: Path, seed: int = 1) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    import random
    Image.frombytes("RGB", (576, 1024), random.Random(seed).randbytes(576 * 1024 * 3)).save(path)
    return path


def passed_result(check: dict | None = None):
    return SimpleNamespace(
        job_id="t", status="completed", answer=None, output_images=["one.png"],
        generation_receipt={
            "provider": "chatgpt", "requested_model": None, "model_verified": False,
            "actual_model_label": None, "notes": ["artifact_source=download", "chat_scope=project"],
            "quality_check": check or {
                "passed": True, "description": "ok", "violations": [],
                "blocking_violations": [], "regressions": [],
            },
        },
        elapsed_seconds=1.0,
    )


def make_runner(tmp_path: Path, *, policy: str = "0"):
    runner = object.__new__(qstation.Runner)
    runner.image_qc_correction_policy = policy
    runner.image_provider_alternation = True  # legacy flags must not weaken the lock
    runner._beat_image_provider = "gemini"  # stale records must also be ignored
    runner.state = SimpleNamespace(project=tmp_path / "videos/099_probe")
    runner.notifier = None
    runner.stage_messages = {}
    calls: list[tuple[str, str]] = []

    def fake_attempt(_stage, _prompt, _references, *, model, destination, provider="chatgpt",
                     chatgpt_chat="project", **kwargs):
        calls.append((provider, chatgpt_chat))
        picture(destination, len(calls))
        return passed_result()

    runner._image_attempt = fake_attempt
    return runner, calls


@pytest.mark.parametrize("stage", ["world_style_anchor", "world_keyframe", "book_cover", "beat_image_005"])
def test_every_image_stage_uses_chatgpt_project(stage: str, tmp_path: Path) -> None:
    runner, calls = make_runner(tmp_path, policy="disabled")
    target = tmp_path / f"{stage}.png"
    runner.image(stage, "scene", [], model="legacy-ignored", destination=target, skip_content_qc=True)
    assert target.is_file()
    assert calls == [("chatgpt", "project")]


def test_qc_correction_stays_in_chatgpt_project(tmp_path: Path) -> None:
    runner, calls = make_runner(tmp_path, policy="1")
    checks = [
        {"passed": True, "observations": ["tight crop"], "blocking_violations": [], "regressions": []},
        {"passed": True, "observations": [], "blocking_violations": [], "regressions": []},
    ]

    def attempt(_stage, _prompt, _refs, *, model, destination, provider="chatgpt", chatgpt_chat="project", **kw):
        calls.append((provider, chatgpt_chat))
        picture(destination, len(calls))
        return passed_result(checks[len(calls) - 1])

    runner._image_attempt = attempt
    runner.image("world_keyframe", "scene", [], model="legacy-ignored", destination=tmp_path / "out.png")
    assert calls == [("chatgpt", "project"), ("chatgpt", "project")]


def test_chatgpt_failure_never_falls_back_to_gemini(tmp_path: Path) -> None:
    runner, calls = make_runner(tmp_path, policy="2")

    def fail(_stage, _prompt, _refs, *, model, destination, provider="chatgpt", chatgpt_chat="project", **kw):
        calls.append((provider, chatgpt_chat))
        raise qstation.StageFailure("probe", "FAILED_DOWNLOAD", "boom")

    runner._image_attempt = fail
    with pytest.raises(qstation.StageFailure, match="boom"):
        runner.image("beat_image_003", "scene", [], model="legacy-ignored", destination=tmp_path / "out.png")
    assert calls == [("chatgpt", "project")]


def test_low_level_image_attempt_rejects_gemini(tmp_path: Path) -> None:
    runner = object.__new__(qstation.Runner)
    with pytest.raises(ValueError, match="locked to the ChatGPT"):
        runner._image_attempt(
            "world_keyframe", "scene", [], model="nano_banana_2",
            destination=tmp_path / "out.png", provider="gemini",
        )
