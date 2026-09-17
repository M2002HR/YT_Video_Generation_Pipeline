from __future__ import annotations

import inspect
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_q_station_pipeline as qs
from character_assets import operator_reference_error
from character_runtime import (
    CharacterRegistryError,
    CharacterSelectionError,
    load_character_registry,
    resolve_character,
)
from content_projects import list_content_projects, load_content_project, resolve_project_id
from video_control_panel import Handler, character_catalog_entries, pipeline_command


def expected_available_ids() -> tuple[str, ...]:
    bundled = ("red_horned_everyman", "moss_cloaked_crone")
    sheet = ROOT / "projects/q_station/characters/sea_captain/refs/character_sheet.png"
    return bundled + (("sea_captain",) if operator_reference_error(sheet) is None else ())


@pytest.fixture
def registry():
    return load_character_registry(ROOT / "projects/q_station/characters/registry.json")


def copied_registry(tmp_path: Path) -> Path:
    target = tmp_path / "characters"
    shutil.copytree(ROOT / "projects/q_station/characters", target)
    shutil.copytree(ROOT / "projects/q_station/presentation_profiles", tmp_path / "presentation_profiles")
    return target / "registry.json"


def test_registry_declares_exactly_three_character_packs(registry) -> None:
    raw = json.loads((ROOT / "projects/q_station/characters/registry.json").read_text())
    assert {item["id"] for item in raw["characters"]} == {
        "red_horned_everyman", "moss_cloaked_crone", "sea_captain"
    }
    assert registry.auto_fallback_character_id == "red_horned_everyman"
    assert registry.legacy_default_character_id == "red_horned_everyman"
    assert registry.enabled_ids() == expected_available_ids()
    assert registry.get("red_horned_everyman").reference_mode == "IDENTITY_ONLY"
    assert registry.get("moss_cloaked_crone").presentation.id == "orb_portal"


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
def test_missing_bundled_character_files_fail(tmp_path: Path, missing: str) -> None:
    path = copied_registry(tmp_path)
    (path.parent / "red_horned_everyman" / missing).unlink()
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
    config_path = path.parent / "moss_cloaked_crone/character.json"
    config = json.loads(config_path.read_text())
    config["enabled"] = False
    config_path.write_text(json.dumps(config))
    loaded = load_character_registry(path)
    with pytest.raises(CharacterSelectionError):
        resolve_character(loaded, requested_mode="manual", requested_character_id="moss_cloaked_crone")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [("reference_mode", "SCENE", "reference_mode"), ("environment_policy", "fixed_home", "environment_policy")],
)
def test_invalid_character_policies_fail(tmp_path: Path, field: str, value: str, message: str) -> None:
    path = copied_registry(tmp_path)
    config_path = path.parent / "red_horned_everyman/character.json"
    config = json.loads(config_path.read_text())
    if field == "reference_mode":
        config["references"][field] = value
    else:
        config[field] = value
    config_path.write_text(json.dumps(config))
    with pytest.raises(CharacterRegistryError, match=message):
        load_character_registry(path)


@pytest.mark.parametrize("character_id", ["red_horned_everyman", "moss_cloaked_crone"])
def test_manual_selection_is_exact(registry, character_id: str) -> None:
    result = resolve_character(registry, requested_mode="manual", requested_character_id=character_id)
    assert result.resolved_character_id == character_id
    assert result.source == "manual"


def test_invalid_manual_is_never_replaced(registry) -> None:
    with pytest.raises(CharacterSelectionError):
        resolve_character(registry, requested_mode="manual", requested_character_id="unknown")


def test_auto_valid_and_invalid_fallback(registry) -> None:
    valid = resolve_character(
        registry,
        requested_mode="auto",
        run_auto_selector=lambda: {"character_id": "moss_cloaked_crone", "confidence": "high", "reason": "Best fit."},
    )
    assert (valid.resolved_character_id, valid.source) == ("moss_cloaked_crone", "auto")
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


def test_pre_character_compatibility_resolution_uses_red_host(registry) -> None:
    result = resolve_character(registry, requested_mode="auto", is_legacy_run=True, run_auto_selector=lambda: {})
    assert (result.resolved_character_id, result.source) == ("red_horned_everyman", "legacy_default")


def test_only_q_station_resolves_as_a_content_project() -> None:
    retired = "_".join(("question", "harvest"))
    assert resolve_project_id("q_station") == "q_station"
    assert resolve_project_id(retired) == retired
    with pytest.raises(RuntimeError):
        load_content_project(retired)
    assert [project.project_id for project in list_content_projects()] == ["q_station"]


def test_character_catalog_is_server_driven_and_safe() -> None:
    entries = character_catalog_entries("q_station")
    assert {item["id"] for item in entries} == set(expected_available_ids())
    assert all("path" not in item and "sheet" not in item for item in entries)


def test_character_catalog_endpoint_is_canonical() -> None:
    captured = {}
    handler = Handler.__new__(Handler)
    handler.path = "/api/character-catalog?content_project=q_station"
    handler.send_json = lambda status, payload: captured.update(status=int(status), payload=payload)
    handler.do_GET()
    assert captured["status"] == 200
    assert captured["payload"]["content_project"] == "q_station"
    assert {item["id"] for item in captured["payload"]["characters"]} == set(expected_available_ids())


def test_q_station_uses_its_canonical_wrapper() -> None:
    base = {
        "project": "videos/999_test",
        "creative_brief": "x",
        "voice_profile": "y",
        "topic": "t",
        "video_id": "999",
        "content_project": "q_station",
    }
    command = pipeline_command(base)
    assert "scripts/run_full_video_pipeline_q_station_wrapper.py" in command


def test_writers_receive_story_context_while_world_style_stays_character_agnostic() -> None:
    assert {"character", "opening_concept"} <= set(inspect.signature(qs.stage_script).parameters)
    assert {"character", "opening_concept"} <= set(inspect.signature(qs.stage_retention).parameters)
    assert "character" not in inspect.signature(qs.stage_world_style_director).parameters


def test_body_reference_is_conditional(registry) -> None:
    character = registry.get("red_horned_everyman")
    image = character.sheet_path
    present = qs._beat_reference_stack(character, {"hero_present": True}, image, image, None)
    absent = qs._beat_reference_stack(None, {"hero_present": False}, image, image, None)
    assert [ref.role for ref in present][0] == "character_sheet"
    assert "character_sheet" not in [ref.role for ref in absent]


def test_active_prompts_enforce_stage_isolation() -> None:
    prompts = ROOT / "projects/q_station/prompts/pipeline"
    stage3 = (prompts / "03_episode_director.md").read_text()
    stage8 = (prompts / "08_opening_video_prompt_writer.md").read_text()
    stage6 = (prompts / "06_world_keyframe_prompt_writer.md").read_text()
    stage9 = (prompts / "09_entry_transition_video_prompt_writer.md").read_text()
    assert "{{CHARACTER_CONTEXT}}" in stage3 and "free semantic description" in stage3
    assert "topic_visual_link" in stage3 and "opening_visual_proof" in stage3
    assert "opening_visual_proof" in stage8 and "first 1–2 seconds" in stage8
    assert "no recurring host" in stage6.lower()
    assert "{{CHARACTER_CONTEXT}}" not in stage9 and "{{EPISODE_PLAN}}" not in stage9
    assert "first_frame" in stage9 and "last_frame" in stage9
