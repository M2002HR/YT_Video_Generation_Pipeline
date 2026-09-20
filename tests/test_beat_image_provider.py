"""Regressions for the run-frozen ChatGPT/Gemini image-provider choice."""
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


def passed_result(check: dict | None = None, provider: str = "chatgpt"):
    return SimpleNamespace(
        job_id="t", status="completed", answer=None, output_images=["one.png"],
        generation_receipt={
            "provider": provider,
            "requested_model": "nano_banana_2" if provider == "gemini" else None,
            "model_verified": provider == "gemini",
            "actual_model_label": "Nano Banana 2" if provider == "gemini" else None,
            "notes": ["artifact_source=download", "chat_scope=project"],
            "quality_check": check or {
                "passed": True, "description": "ok", "violations": [],
                "blocking_violations": [], "regressions": [],
            },
        },
        elapsed_seconds=1.0,
    )


def make_runner(tmp_path: Path, *, policy: str = "0", provider: str = "chatgpt"):
    runner = object.__new__(qstation.Runner)
    runner.image_qc_correction_policy = policy
    runner.image_provider_alternation = True  # legacy flags must not weaken the lock
    runner._beat_image_provider = "gemini"  # stale records must also be ignored
    runner.image_provider = provider
    runner.image_model = "nano_banana_2" if provider == "gemini" else qstation.CHATGPT_IMAGE_MODEL
    runner.state = SimpleNamespace(project=tmp_path / "videos/099_probe")
    runner.notifier = None
    runner.stage_messages = {}
    calls: list[tuple[str, str]] = []

    def fake_attempt(_stage, _prompt, _references, *, model, destination, provider="chatgpt",
                     chatgpt_chat="project", **kwargs):
        calls.append((provider, chatgpt_chat))
        picture(destination, len(calls))
        return passed_result(provider=provider)

    runner._image_attempt = fake_attempt
    return runner, calls


@pytest.mark.parametrize("provider", ["chatgpt", "gemini"])
@pytest.mark.parametrize("stage", ["world_style_anchor", "world_keyframe", "book_cover", "beat_image_005"])
def test_every_image_stage_uses_one_selected_provider(stage: str, provider: str, tmp_path: Path) -> None:
    runner, calls = make_runner(tmp_path, policy="disabled", provider=provider)
    target = tmp_path / f"{stage}.png"
    runner.image(stage, "scene", [], model="legacy-ignored", destination=target, skip_content_qc=True)
    assert target.is_file()
    assert calls == [(provider, "project")]


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


def test_selected_gemini_failure_never_falls_back_to_chatgpt(tmp_path: Path) -> None:
    runner, calls = make_runner(tmp_path, policy="2", provider="gemini")

    def fail(_stage, _prompt, _refs, *, model, destination, provider="chatgpt", chatgpt_chat="project", **kw):
        calls.append((provider, chatgpt_chat))
        raise qstation.StageFailure("probe", "FAILED_DOWNLOAD", "boom")

    runner._image_attempt = fail
    with pytest.raises(qstation.StageFailure, match="boom"):
        runner.image("world_keyframe", "scene", [], model="nano_banana_2", destination=tmp_path / "out.png")
    assert calls == [("gemini", "project")]
