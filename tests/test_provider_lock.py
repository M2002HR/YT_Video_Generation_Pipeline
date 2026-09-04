from __future__ import annotations
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from content_projects import load_content_project, validate_provider_locks


def test_question_harvest_provider_locks_are_gemini_flow():
    proj = load_content_project("question_harvest")
    assert proj.get_provider("image") == "gemini"
    assert proj.get_provider("video") == "flow"
    # should not raise
    validate_provider_locks(proj)


def test_question_harvest_image_provider_chatgpt_rejected():
    proj = load_content_project("question_harvest")
    with pytest.raises(RuntimeError, match="LOCKED.*gemini"):
        validate_provider_locks(proj, image_provider="chatgpt")


def test_question_harvest_video_provider_gemini_rejected():
    proj = load_content_project("question_harvest")
    with pytest.raises(RuntimeError, match="LOCKED.*flow"):
        validate_provider_locks(proj, video_provider="gemini")


class ProviderSpy:
    """Records every provider call and fails the ones a test asks it to fail."""

    def __init__(self, fail_provider: str | None = None, error_code: str = "response_timeout") -> None:
        self.calls: list[tuple[str, str]] = []
        self.fail_provider = fail_provider
        self.error_code = error_code

    def run(self, question, *, provider, mode, **kwargs):
        from ordak_jobs import OrdakJobError

        self.calls.append((provider, mode))
        if provider == self.fail_provider:
            raise OrdakJobError(f"{provider} failed", error_code=self.error_code)
        raise AssertionError(f"unexpected call to {provider}/{mode}")

    def download(self, *args, **kwargs):
        raise AssertionError("nothing should be downloaded after a provider failure")

    @property
    def providers(self) -> list[str]:
        return [provider for provider, _mode in self.calls]


def _resume_workspace(tmp_path):
    import json

    project = tmp_path / "videos" / "902_lock"
    (project / "pipeline").mkdir(parents=True)
    (project / "launch").mkdir(parents=True)
    (project / "launch" / "LAUNCH_REQUEST.json").write_text(
        json.dumps({"image_generation": {"model": "nano_banana_pro"}}), encoding="utf-8"
    )
    return project


def test_a_gemini_failure_never_reaches_another_image_provider(tmp_path):
    """§93: no provider fallback — the stage fails, it does not shop around."""
    import run_question_harvest_pipeline as qh

    project = _resume_workspace(tmp_path)
    spy = ProviderSpy(fail_provider="gemini")
    runner = qh.Runner(spy, None, qh.QHState(project, "902_lock", "topic"))

    with pytest.raises(qh.StageFailure) as excinfo:
        qh.stage_world_keyframe(
            runner,
            project,
            load_content_project("question_harvest"),
            "a keyframe prompt",
            project / "references" / "world_style_anchor.png",
        )

    assert spy.providers == ["gemini"], f"another provider was contacted: {spy.calls}"
    assert "gemini/image_generate failed" in excinfo.value.message


def test_a_flow_failure_never_reaches_another_video_provider(tmp_path):
    import run_question_harvest_pipeline as qh

    project = _resume_workspace(tmp_path)
    spy = ProviderSpy(fail_provider="flow", error_code="flow_credits_exhausted")
    runner = qh.Runner(spy, None, qh.QHState(project, "902_lock", "topic"))

    with pytest.raises(qh.StageFailure) as excinfo:
        qh.stage_flow_clip(
            runner,
            project,
            load_content_project("question_harvest"),
            "A",
            "a clip prompt",
            book_spread=None,
            world_keyframe=None,
            model="gemini_omni_1_1_flash",
            resolution="720p",
            aspect_ratio="9:16",
            source_seconds=5,
        )

    assert spy.providers == ["flow"], f"another provider was contacted: {spy.calls}"
    assert excinfo.value.state == "PAUSED_CREDITS"


def test_the_orchestrator_has_no_alternate_image_or_video_backend():
    """A grep guard against a backend creeping back in beside the locked providers."""
    text = (Path(ROOT) / "scripts" / "run_question_harvest_pipeline.py").read_text(encoding="utf-8")
    assert "validate_provider_locks" in text
    for banned in ("pollinations", "stability.ai", "replicate.com", "openai.com/v1/images", "vertexai"):
        assert banned not in text.lower(), f"{banned!r} appeared beside the locked providers"


def test_pipeline_has_no_synthetic_or_fallback_path():
    """The production orchestrator must contain no way to substitute made-up media (§4)."""
    text = (Path(ROOT) / "scripts" / "run_question_harvest_pipeline.py").read_text(encoding="utf-8")
    lowered = text.lower()
    assert "flow" in lowered
    for banned in ("allow_synthetic", "synthetic_fallback", "_dummy_", "pollinations", "fallback_synthetic"):
        assert banned not in lowered, f"{banned!r} is still reachable in the production pipeline"
