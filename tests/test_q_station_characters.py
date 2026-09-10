from __future__ import annotations

import inspect
import json
import shutil
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_question_harvest_pipeline as qh
from character_runtime import (
    CharacterRegistryError,
    CharacterSelectionError,
    load_character_registry,
    resolve_character,
)
from content_projects import list_content_projects, load_content_project, resolve_project_id
from video_control_panel import Handler, character_catalog_entries, pipeline_command


@pytest.fixture
def registry():
    return load_character_registry(ROOT / "projects/q_station/characters/registry.json")


def copied_registry(tmp_path: Path) -> Path:
    target = tmp_path / "characters"
    shutil.copytree(ROOT / "projects/q_station/characters", target)
    return target / "registry.json"


def test_registry_loads_both_enabled_character_packs(registry) -> None:
    assert registry.enabled_ids() == ("farmer_host", "red_horned_everyman")
    assert registry.get("farmer_host").sheet_path.parent.name == "refs"
    assert registry.get("red_horned_everyman").reference_mode == "IDENTITY_ONLY"


def test_duplicate_character_ids_fail(tmp_path: Path) -> None:
    path = copied_registry(tmp_path)
    data = json.loads(path.read_text())
    data["characters"].append(dict(data["characters"][0]))
    path.write_text(json.dumps(data))
    with pytest.raises(CharacterRegistryError, match="Duplicate"):
        load_character_registry(path)


def test_malformed_registry_json_fails_clearly(tmp_path: Path) -> None:
    path = copied_registry(tmp_path)
    path.write_text("{broken")
    with pytest.raises(CharacterRegistryError, match="valid JSON"):
        load_character_registry(path)


@pytest.mark.parametrize("missing", ["character.json", "appearance.md", "refs/character_sheet.png"])
def test_missing_character_files_fail(tmp_path: Path, missing: str) -> None:
    path = copied_registry(tmp_path)
    (path.parent / "farmer_host" / missing).unlink()
    with pytest.raises(CharacterRegistryError, match="missing"):
        load_character_registry(path)


def test_registry_path_traversal_fails(tmp_path: Path) -> None:
    path = copied_registry(tmp_path)
    data = json.loads(path.read_text())
    data["characters"][0]["config"] = "../../outside.json"
    path.write_text(json.dumps(data))
    with pytest.raises(CharacterRegistryError, match="escapes"):
        load_character_registry(path)


def test_invalid_fallback_fails(tmp_path: Path) -> None:
    path = copied_registry(tmp_path)
    data = json.loads(path.read_text())
    data["auto_fallback_character_id"] = "missing"
    path.write_text(json.dumps(data))
    with pytest.raises(CharacterRegistryError, match="auto_fallback"):
        load_character_registry(path)


def test_disabled_character_cannot_be_selected(tmp_path: Path) -> None:
    path = copied_registry(tmp_path)
    farmer_config = path.parent / "farmer_host/character.json"
    config = json.loads(farmer_config.read_text())
    config["enabled"] = False
    farmer_config.write_text(json.dumps(config))
    data = json.loads(path.read_text())
    data["legacy_default_character_id"] = "red_horned_everyman"
    path.write_text(json.dumps(data))
    loaded = load_character_registry(path)
    with pytest.raises(CharacterSelectionError):
        resolve_character(loaded, requested_mode="manual", requested_character_id="farmer_host")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [("reference_mode", "SCENE", "reference_mode"), ("environment_policy", "fixed_home", "environment_policy")],
)
def test_invalid_character_policies_fail(tmp_path: Path, field: str, value: str, message: str) -> None:
    path = copied_registry(tmp_path)
    config_path = path.parent / "farmer_host/character.json"
    config = json.loads(config_path.read_text())
    if field == "reference_mode":
        config["references"][field] = value
    else:
        config[field] = value
    config_path.write_text(json.dumps(config))
    with pytest.raises(CharacterRegistryError, match=message):
        load_character_registry(path)


@pytest.mark.parametrize("character_id", ["farmer_host", "red_horned_everyman"])
def test_manual_selection_is_exact(registry, character_id: str) -> None:
    result = resolve_character(registry, requested_mode="manual", requested_character_id=character_id)
    assert result.resolved_character_id == character_id
    assert result.source == "manual"


def test_invalid_manual_is_never_replaced(registry) -> None:
    with pytest.raises(CharacterSelectionError):
        resolve_character(registry, requested_mode="manual", requested_character_id="unknown")


def test_auto_valid_and_invalid_fallback(registry) -> None:
    valid = resolve_character(
        registry, requested_mode="auto",
        run_auto_selector=lambda: {"character_id": "farmer_host", "confidence": "high", "reason": "Best fit."},
    )
    assert (valid.resolved_character_id, valid.source) == ("farmer_host", "auto")
    malformed = resolve_character(registry, requested_mode="auto", run_auto_selector=lambda: "not json")
    assert (malformed.resolved_character_id, malformed.source) == ("red_horned_everyman", "auto_fallback")


def test_persisted_resolution_is_reused_without_auto(registry) -> None:
    called = 0
    def selector():
        nonlocal called
        called += 1
        return {}
    result = resolve_character(
        registry,
        persisted={"requested_mode": "auto", "resolved_character_id": "red_horned_everyman", "resolution_source": "auto"},
        run_auto_selector=selector,
    )
    assert result.resolved_character_id == "red_horned_everyman"
    assert called == 0


def test_mocked_run_persists_auto_exactly_once(tmp_path: Path) -> None:
    project = tmp_path / "run"
    (project / "launch").mkdir(parents=True)
    launch = {"character": {"mode": "auto"}}
    class State:
        def mark(self, *args, **kwargs): pass
    class Runner:
        state = State()
        calls = 0
        def json(self, stage, prompt):
            self.calls += 1
            return {"character_id": "red_horned_everyman", "confidence": "high", "reason": "Broad topic fit."}
    runner = Runner()
    plan = {"full_narration": "A final script."}
    first, _ = qh.stage_character_resolution(
        runner, project, load_content_project("q_station"), "topic", "brief", plan, launch,
        is_legacy_run=False,
    )
    persisted = json.loads((project / "launch/LAUNCH_REQUEST.json").read_text())
    second, _ = qh.stage_character_resolution(
        runner, project, load_content_project("q_station"), "topic", "brief", plan, persisted,
        is_legacy_run=False,
    )
    assert first.resolved_character_id == second.resolved_character_id == "red_horned_everyman"
    assert runner.calls == 1


def test_legacy_pre_character_run_uses_farmer(registry) -> None:
    result = resolve_character(registry, requested_mode="auto", is_legacy_run=True, run_auto_selector=lambda: {})
    assert (result.resolved_character_id, result.source) == ("farmer_host", "legacy_default")


def test_legacy_resolution_preserves_historical_launch_manifest(tmp_path: Path) -> None:
    project = tmp_path / "run"
    launch_path = project / "launch/LAUNCH_REQUEST.json"
    launch_path.parent.mkdir(parents=True)
    original = {"schema_version": 4, "content_project": "question_harvest", "topic": "old run"}
    launch_path.write_text(json.dumps(original))

    class State:
        def mark(self, *args, **kwargs): pass

    class Runner:
        state = State()
        def json(self, *args, **kwargs):
            raise AssertionError("Auto must not run for a historical pre-character run")

    result, _ = qh.stage_character_resolution(
        Runner(), project, load_content_project("question_harvest"), "topic", "brief",
        {"full_narration": "Already finalized."}, dict(original), is_legacy_run=True,
    )
    assert (result.resolved_character_id, result.source) == ("farmer_host", "legacy_default")
    assert json.loads(launch_path.read_text()) == original
    persisted = json.loads((project / "creative/CHARACTER_RESOLUTION.json").read_text())
    assert persisted["resolved_character_id"] == "farmer_host"


def test_project_alias_is_canonical_and_not_listed_twice() -> None:
    assert resolve_project_id("question_harvest") == "q_station"
    assert load_content_project("question_harvest").project_id == "q_station"
    ids = [project.project_id for project in list_content_projects()]
    assert ids.count("q_station") == 1
    assert "question_harvest" not in ids


def test_character_catalog_is_server_driven_and_safe() -> None:
    entries = character_catalog_entries("question_harvest")
    assert {item["id"] for item in entries} == {"farmer_host", "red_horned_everyman"}
    assert all("path" not in item and "sheet" not in item for item in entries)


def test_character_catalog_endpoint_resolves_alias() -> None:
    captured = {}
    handler = Handler.__new__(Handler)
    handler.path = "/api/character-catalog?content_project=question_harvest"
    handler.send_json = lambda status, payload: captured.update(status=int(status), payload=payload)
    handler.do_GET()
    assert captured["status"] == 200
    assert captured["payload"]["content_project"] == "q_station"
    assert {item["id"] for item in captured["payload"]["characters"]} == {
        "farmer_host", "red_horned_everyman",
    }


def test_q_station_and_alias_use_bookworld_wrapper() -> None:
    base = {"project": "videos/999_test", "creative_brief": "x", "voice_profile": "y", "topic": "t", "video_id": "999"}
    for project_id in ("q_station", "question_harvest"):
        command = pipeline_command({**base, "content_project": project_id})
        assert "scripts/run_full_video_pipeline_qh_wrapper.py" in command


def test_stage_01_and_02_are_character_agnostic() -> None:
    assert "character" not in inspect.signature(qh.stage_script).parameters
    assert "character" not in inspect.signature(qh.stage_retention).parameters
    assert "character" not in inspect.signature(qh.stage_world_style_director).parameters


def test_opening_prompt_is_character_aware_but_video_two_is_character_isolated(
    registry, tmp_path: Path,
) -> None:
    captured = []

    class State:
        def done(self, stage): return False

    class Runner:
        state = State()
        def stage_start(self, stage): return 0.0
        def stage_done(self, *args, **kwargs): pass
        def text(self, stage, prompt):
            captured.append((stage, prompt))
            return "generated flow prompt"

    runner = Runner()
    content_project = load_content_project("q_station")
    red = registry.get("red_horned_everyman")
    farmer = registry.get("farmer_host")
    episode = {
        "opening_location": "bus stop",
        "opening_environment": "ordinary morning commute",
        "opening_activity": "checking an arrival board",
    }
    qh.stage_flow_prompt(
        runner, tmp_path / "a", content_project, "A", "question", episode, {}, "world", "topic", 6,
        character=red,
    )
    opening_input = captured[-1][1]
    assert red.display_name in opening_input and "Restrained, grounded physical acting." in opening_input
    assert "Farmer Host" not in opening_input

    for run_name, character in (("b1", farmer), ("b2", red)):
        qh.stage_flow_prompt(
            runner, tmp_path / run_name, content_project, "B", "transition", None,
            {"medium": "woodcut"}, "host-free world", "topic", 4, character=character,
        )
    assert captured[-2][1] == captured[-1][1]
    for forbidden in (
        farmer.display_name, red.display_name, "Warm, practical, approachable",
        "Restrained, grounded physical acting.", "opening_activity",
    ):
        assert forbidden not in captured[-1][1]


def test_world_keyframe_is_host_free_and_has_no_character_reference(registry, tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "run"
    (project / "launch").mkdir(parents=True)
    (project / "launch/LAUNCH_REQUEST.json").write_text(json.dumps({"image_generation": {"model": "nano_banana_2"}}))
    captured = {}
    monkeypatch.setattr(qh, "reusable_image", lambda runner, project, stage, target, receipt, prompt, model, references: captured.setdefault("roles", [r.role for r in references]) is not None)
    class Runner:
        def stage_reused(self, *args): pass
    qh.stage_world_keyframe(Runner(), project, load_content_project("q_station"), "no recurring host", registry.get("farmer_host").sheet_path)
    assert captured["roles"] == ["style_reference"]


def test_body_reference_is_conditional(registry) -> None:
    character = registry.get("red_horned_everyman")
    image = character.sheet_path
    present = qh._beat_reference_stack(character, {"hero_present": True}, image, image, None)
    absent = qh._beat_reference_stack(None, {"hero_present": False}, image, image, None)
    assert [ref.role for ref in present][0] == "character_sheet"
    assert "character_sheet" not in [ref.role for ref in absent]


def test_active_prompts_enforce_stage_isolation() -> None:
    prompts = ROOT / "projects/q_station/prompts/pipeline"
    transition_reference = (
        ROOT / "projects/q_station/prompts/reference/book_transition_reference_prompt.txt"
    ).read_text()
    stage3 = (prompts / "03_episode_director.md").read_text()
    stage6 = (prompts / "06_world_keyframe_prompt_writer.md").read_text()
    stage9 = (prompts / "09_book_transition_video_prompt_writer.md").read_text()
    assert "{{CHARACTER_CONTEXT}}" in stage3 and "free semantic description" in stage3
    assert "no recurring host" in stage6.lower()
    assert "{{CHARACTER_CONTEXT}}" not in stage9 and "{{EPISODE_PLAN}}" not in stage9
    assert "no recurring host" in stage9.lower() and "no farmer" not in stage9.lower()
    assert "no recurring host" in transition_reference.lower()
    assert "no farmer" not in transition_reference.lower()


def test_flow_clip_a_uses_selected_pack_and_clip_b_is_frames_only(registry, tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "run"
    captured = []
    class Runner:
        class State:
            def done(self, stage): return False
        state = State()
        def stage_start(self, stage): return 0.0
        def stage_done(self, *args, **kwargs): pass
        def video(self, stage, prompt, references, **kwargs):
            kwargs["destination"].parent.mkdir(parents=True, exist_ok=True)
            kwargs["destination"].write_bytes(b"video")
            captured.append([(ref.role, ref.path) for ref in references])
            return SimpleNamespace(generation_receipt={}, job_id="mock", elapsed_seconds=0.1)
    monkeypatch.setattr(qh, "ffprobe_duration", lambda path: 6.0)
    monkeypatch.setattr(qh, "require_verified_video_model", lambda *args: None)
    runner = Runner()
    farmer = registry.get("farmer_host")
    qh.stage_flow_clip(
        runner, project, load_content_project("q_station"), "A", "prompt",
        book_spread=None, world_keyframe=None, model="veo_3_1_fast", resolution="720p",
        aspect_ratio="9:16", source_seconds=6, character=farmer,
    )
    assert captured[-1] == [("character_sheet", farmer.sheet_path)]
    first = farmer.sheet_path
    last = registry.get("red_horned_everyman").sheet_path
    qh.stage_flow_clip(
        runner, project, load_content_project("q_station"), "B", "prompt",
        book_spread=first, world_keyframe=last, model="veo_3_1_fast", resolution="720p",
        aspect_ratio="9:16", source_seconds=4,
    )
    assert [role for role, _ in captured[-1]] == ["first_frame", "last_frame"]
    assert all(role != "character_sheet" for role, _ in captured[-1])
