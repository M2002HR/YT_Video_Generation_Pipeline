from __future__ import annotations
import ast
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from content_projects import load_content_project, validate_provider_locks


def test_q_station_provider_locks_are_chatgpt_flow():
    proj = load_content_project("q_station")
    assert proj.get_provider("image") == "chatgpt"
    assert proj.get_provider("video") == "flow"
    # should not raise
    validate_provider_locks(proj)


def test_q_station_image_provider_gemini_rejected():
    proj = load_content_project("q_station")
    with pytest.raises(RuntimeError, match="LOCKED.*chatgpt"):
        validate_provider_locks(proj, image_provider="gemini")


def test_q_station_video_provider_gemini_rejected():
    proj = load_content_project("q_station")
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


def test_a_chatgpt_failure_never_reaches_another_image_provider(tmp_path, monkeypatch):
    """§93: no provider fallback — the stage fails, it does not shop around."""
    import run_q_station_pipeline as qstation

    project = _resume_workspace(tmp_path)
    spy = ProviderSpy(fail_provider="chatgpt")
    monkeypatch.setattr(qstation.Runner, "json", lambda *a, **k: {"hero_present": False})
    runner = qstation.Runner(spy, None, qstation.QStationState(project, "902_lock", "topic"))

    with pytest.raises(qstation.StageFailure) as excinfo:
        qstation.stage_world_keyframe(
            runner,
            project,
            load_content_project("q_station"),
            "a keyframe prompt",
            project / "references" / "world_style_anchor.png",
        )

    assert spy.providers == ["chatgpt"], f"another provider was contacted: {spy.calls}"
    assert "chatgpt/image_generate failed" in excinfo.value.message


def test_a_flow_failure_never_reaches_another_video_provider(tmp_path):
    import run_q_station_pipeline as qstation

    project = _resume_workspace(tmp_path)
    spy = ProviderSpy(fail_provider="flow", error_code="flow_credits_exhausted")
    runner = qstation.Runner(spy, None, qstation.QStationState(project, "902_lock", "topic"))

    with pytest.raises(qstation.StageFailure) as excinfo:
        qstation.stage_flow_clip(
            runner,
            project,
            load_content_project("q_station"),
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
    text = (Path(ROOT) / "scripts" / "run_q_station_pipeline.py").read_text(encoding="utf-8")
    assert "validate_provider_locks" in text
    for banned in ("pollinations", "stability.ai", "replicate.com", "openai.com/v1/images", "vertexai"):
        assert banned not in text.lower(), f"{banned!r} appeared beside the locked providers"


def test_every_static_image_generation_call_is_chatgpt() -> None:
    """No script may reintroduce a direct Gemini image-generation call."""
    violations = []
    for path in sorted((Path(ROOT) / "scripts").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                values = {
                    keyword.arg: keyword.value.value
                    for keyword in node.keywords
                    if keyword.arg and isinstance(keyword.value, ast.Constant)
                }
                if values.get("mode") == "image_generate" and values.get("provider") != "chatgpt":
                    violations.append(f"{path.name}:{node.lineno}:{values.get('provider')!r}")
                if values.get("mode") == "image_generate" and values.get("provider") == "chatgpt":
                    if values.get("chatgpt_chat") not in {"project", None}:
                        violations.append(f"{path.name}:{node.lineno}:scope={values.get('chatgpt_chat')!r}")
            if isinstance(node, ast.Dict):
                values = {
                    key.value: value.value
                    for key, value in zip(node.keys, node.values)
                    if isinstance(key, ast.Constant) and isinstance(value, ast.Constant)
                }
                if values.get("mode") == "image_generate" and values.get("provider") != "chatgpt":
                    violations.append(f"{path.name}:{node.lineno}:{values.get('provider')!r}")
                if values.get("mode") == "image_generate" and values.get("provider") == "chatgpt":
                    if values.get("chatgpt_chat") != "project":
                        violations.append(f"{path.name}:{node.lineno}:scope={values.get('chatgpt_chat')!r}")
    assert violations == []


def test_ordak_scope_defaults_separate_text_from_image() -> None:
    from ordak_jobs import OrdakJobs

    assert OrdakJobs.default_chatgpt_scope("chatgpt", "chat", None) == "temporary"
    assert OrdakJobs.default_chatgpt_scope("chatgpt", "image_generate", None) == "project"


def test_every_static_chatgpt_text_call_uses_temporary_chat() -> None:
    """Text calls must never inherit the project-scoped image conversation."""
    violations = []
    for path in sorted((Path(ROOT) / "scripts").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                values = {
                    keyword.arg: keyword.value.value
                    for keyword in node.keywords
                    if keyword.arg and isinstance(keyword.value, ast.Constant)
                }
                if values.get("provider") == "chatgpt" and values.get("mode") == "chat":
                    if values.get("chatgpt_chat") != "temporary":
                        violations.append(f"{path.name}:{node.lineno}")
            if isinstance(node, ast.Dict):
                values = {
                    key.value: value.value
                    for key, value in zip(node.keys, node.values)
                    if isinstance(key, ast.Constant) and isinstance(value, ast.Constant)
                }
                if values.get("mode") == "chat" and values.get("chatgpt_chat") != "temporary":
                    # Direct /api/chatgpt/respond payloads have no provider field.
                    parent_text = path.read_text(encoding="utf-8")
                    if "/api/chatgpt/respond" in parent_text:
                        violations.append(f"{path.name}:{node.lineno}")
    assert violations == []


def test_pipeline_has_no_synthetic_or_fallback_path():
    """The production orchestrator must contain no way to substitute made-up media (§4)."""
    text = (Path(ROOT) / "scripts" / "run_q_station_pipeline.py").read_text(encoding="utf-8")
    lowered = text.lower()
    assert "flow" in lowered
    for banned in ("allow_synthetic", "synthetic_fallback", "_dummy_", "pollinations", "fallback_synthetic"):
        assert banned not in lowered, f"{banned!r} is still reachable in the production pipeline"
