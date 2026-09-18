"""Regressions: ChatGPT image chats are always fresh; beat images keep one renderer.

- Fresh ChatGPT generations each get their own temporary chat; corrections go
  to a fresh normal (non-temp) chat — never the long-lived project conversation.
- Beat images lock to the first accepted renderer for the whole episode instead
  of alternating one-by-one.
"""
from __future__ import annotations

import json
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


def passed_result():
    return SimpleNamespace(
        job_id="t", status="completed", answer=None, output_images=["one.png"],
        generation_receipt={
            "requested_model": "nano_banana_2", "model_verified": True,
            "actual_model_label": "Nano Banana 2", "notes": ["artifact_source=download"],
            "quality_check": {
                "passed": True, "description": "ok", "violations": [],
                "blocking_violations": [], "regressions": [],
            },
        },
        elapsed_seconds=1.0,
    )


def make_runner(tmp_path: Path, *, policy: str = "0", alternate: bool = True):
    runner = object.__new__(qstation.Runner)
    runner.image_qc_correction_policy = policy
    runner.image_provider_alternation = alternate
    runner._beat_image_provider = None
    runner.state = SimpleNamespace(project=tmp_path / "videos/099_probe")
    runner.notifier = None
    runner.stage_messages = {}
    calls: list[tuple[str, str]] = []

    def fake_attempt(_stage, _prompt, _references, *, model, destination, provider="gemini",
                     chatgpt_chat="project", **kwargs):
        calls.append((provider, chatgpt_chat))
        picture(destination, len(calls))
        return passed_result()

    runner._image_attempt = fake_attempt
    return runner, calls


def test_fresh_gemini_image_keeps_project_scope(tmp_path: Path) -> None:
    runner, calls = make_runner(tmp_path, policy="disabled")
    target = tmp_path / "out.png"
    runner.image("book_cover", "scene", [], model="nano_banana_2", destination=target,
                 skip_content_qc=True)
    assert target.is_file()
    assert calls == [("gemini", "project")]


def test_correction_goes_to_fresh_normal_chat_not_temp(tmp_path: Path) -> None:
    runner, calls = make_runner(tmp_path, policy="1")
    real_attempt = runner._image_attempt

    def flaky(_stage, _prompt, _refs, *, model, destination, provider="gemini", chatgpt_chat="project", **kw):
        calls.append((provider, chatgpt_chat))
        if len(calls) == 1:
            raise qstation.StageFailure("probe", "FAILED_DOWNLOAD", "boom")
        picture(destination, 2)
        return passed_result()

    runner._image_attempt = flaky
    target = tmp_path / "out.png"
    runner.image("world_keyframe", "scene", [], model="nano_banana_2", destination=target)
    assert [provider for provider, _ in calls] == ["gemini", "chatgpt"]
    assert calls[1][1] == "fresh"
    assert target.is_file()


def test_sticky_chatgpt_fresh_attempt_uses_temporary_chat(tmp_path: Path) -> None:
    runner, calls = make_runner(tmp_path, policy="disabled")
    runner._beat_image_provider = "chatgpt"
    target = tmp_path / "beat_005.png"
    runner.image("beat_image_005", "scene", [], model="nano_banana_2", destination=target)
    assert calls == [("chatgpt", "temporary")]
    assert target.is_file()


def test_gemini_attempts_keep_project_scope(tmp_path: Path) -> None:
    runner, calls = make_runner(tmp_path, policy="disabled")
    target = tmp_path / "out.png"
    runner.image("world_keyframe", "scene", [], model="nano_banana_2", destination=target,
                 skip_content_qc=True)
    assert calls == [("gemini", "project")]


def test_beat_images_lock_to_first_accepted_provider(tmp_path: Path) -> None:
    runner, calls = make_runner(tmp_path, policy="1")

    def flaky(_stage, _prompt, _refs, *, model, destination, provider="gemini", chatgpt_chat="project", **kw):
        calls.append((provider, chatgpt_chat))
        if len(calls) == 1:
            raise qstation.StageFailure("probe", "FAILED_DOWNLOAD", "boom")
        picture(destination, len(calls))
        return passed_result()

    runner._image_attempt = flaky
    first = tmp_path / "beat_001.png"
    runner.image("beat_image_001", "scene", [], model="nano_banana_2", destination=first)
    assert runner._beat_image_provider == "chatgpt"
    stored = json.loads((tmp_path / "videos/099_probe/creative/BEAT_IMAGE_PROVIDER.json").read_text())
    assert stored["provider"] == "chatgpt"
    calls.clear()
    second = tmp_path / "beat_002.png"
    runner.image("beat_image_002", "scene", [], model="nano_banana_2", destination=second)
    assert calls[0][0] == "chatgpt"
    assert calls[0][1] == "temporary"
    assert second.is_file()


def test_beat_stickiness_survives_across_runner_instances(tmp_path: Path) -> None:
    project = tmp_path / "videos/099_probe"
    (project / "creative").mkdir(parents=True)
    (project / "creative/BEAT_IMAGE_PROVIDER.json").write_text(
        json.dumps({"schema_version": 1, "provider": "chatgpt"}))
    runner, calls = make_runner(tmp_path, policy="0")
    target = tmp_path / "beat_009.png"
    runner.image("beat_image_009", "scene", [], model="nano_banana_2", destination=target)
    assert calls[0] == ("chatgpt", "temporary")


def test_beat_stickiness_falls_back_to_other_provider_on_failure(tmp_path: Path) -> None:
    runner, calls = make_runner(tmp_path, policy="0")
    runner._beat_image_provider = "chatgpt"

    def flaky(_stage, _prompt, _refs, *, model, destination, provider="gemini", chatgpt_chat="project", **kw):
        calls.append((provider, chatgpt_chat))
        if provider == "chatgpt":
            raise qstation.StageFailure("probe", "FAILED_DOWNLOAD", "boom")
        picture(destination, 7)
        return passed_result()

    runner._image_attempt = flaky
    target = tmp_path / "beat_003.png"
    runner.image("beat_image_003", "scene", [], model="nano_banana_2", destination=target)
    assert [provider for provider, _ in calls] == ["chatgpt", "gemini"]
    assert target.is_file()


def test_non_beat_stages_keep_historical_alternation(tmp_path: Path) -> None:
    runner, calls = make_runner(tmp_path, policy="1")

    def flaky(_stage, _prompt, _refs, *, model, destination, provider="gemini", chatgpt_chat="project", **kw):
        calls.append((provider, chatgpt_chat))
        if len(calls) == 1:
            raise qstation.StageFailure("probe", "FAILED_DOWNLOAD", "boom")
        picture(destination, 3)
        return passed_result()

    runner._image_attempt = flaky
    target = tmp_path / "cover.png"
    runner.image("book_cover", "scene", [], model="nano_banana_2", destination=target)
    assert [provider for provider, _ in calls] == ["gemini", "chatgpt"]
    assert runner._beat_image_provider is None


def test_load_beat_provider_scans_old_receipts(tmp_path: Path) -> None:
    project = tmp_path / "videos/099_probe"
    receipts = project / "pipeline/provider_receipts"
    receipts.mkdir(parents=True)
    (receipts / "gemini_beat_001.json").write_text(json.dumps({
        "qc_selected_attempt": 2,
        "quality_iterations": [
            {"attempt": 1, "provider": "gemini"},
            {"attempt": 2, "provider": "chatgpt"},
        ],
    }))
    assert qstation._load_beat_image_provider(project) == "chatgpt"
    assert qstation._load_beat_image_provider(tmp_path / "videos/099_empty") is None
