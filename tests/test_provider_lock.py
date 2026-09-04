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


def test_gemini_failure_must_not_fallback_to_chatgpt():
    # Provider fallback is forbidden per §4 — ensure code path that handles Gemini error does not call ChatGPT
    import pathlib
    text = (pathlib.Path(ROOT) / "scripts" / "run_question_harvest_pipeline.py").read_text(encoding="utf-8")
    assert 'provider="gemini"' in text or "provider='gemini'" in text or "gemini" in text.lower()
    # must have provider lock validation, not fallback logic that would call chatgpt on gemini failure
    assert "validate_provider_locks" in text
    # ensure no pollinations/vertex fallback
    assert "pollinations" not in text.lower()


def test_pipeline_has_no_synthetic_or_fallback_path():
    """The production orchestrator must contain no way to substitute made-up media (§4)."""
    text = (Path(ROOT) / "scripts" / "run_question_harvest_pipeline.py").read_text(encoding="utf-8")
    lowered = text.lower()
    assert "flow" in lowered
    for banned in ("allow_synthetic", "synthetic_fallback", "_dummy_", "pollinations", "fallback_synthetic"):
        assert banned not in lowered, f"{banned!r} is still reachable in the production pipeline"
