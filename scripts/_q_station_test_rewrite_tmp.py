#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SELF = Path(__file__)


def write(path: str, content: str) -> None:
    (ROOT / path).write_text(content, encoding="utf-8")


def main() -> None:
    write(
        "tests/test_q_station_only_repository.py",
        '''from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _retired_identifiers() -> tuple[str, ...]:
    return (
        "_".join(("question", "harvest")),
        "_".join(("world", "behind", "the", "question")),
        "_".join(("farmer", "host")),
    )


def test_only_q_station_project_and_three_hosts_remain() -> None:
    project_dirs = sorted(p.name for p in (ROOT / "projects").iterdir() if p.is_dir() and not p.is_symlink())
    assert project_dirs == ["q_station"]
    project = json.loads((ROOT / "projects/q_station/PROJECT.json").read_text())
    assert project["project_id"] == "q_station"
    assert project.get("aliases") == []
    registry = json.loads((ROOT / "projects/q_station/characters/registry.json").read_text())
    expected = {"red_horned_everyman", "moss_cloaked_crone", "sea_captain"}
    assert {item["id"] for item in registry["characters"]} == expected
    assert registry["auto_fallback_character_id"] == "red_horned_everyman"
    assert registry["legacy_default_character_id"] == "red_horned_everyman"
    assert {p.name for p in (ROOT / "projects/q_station/characters").iterdir() if p.is_dir()} == expected


def test_only_audited_q_station_runs_remain() -> None:
    expected = {
        "026_black_swan_meaning_by_nassim_talib", "027_video",
        "028_what_will_happen_if_you_sleep_less_than_5_hours_a_day",
        "029_why_a_song_gets_stuck_in_your_head", "030_8_of_the_strangest_ocean_creatures",
        "031_wwhy_does_seeing_someone_yawn_make_you_yawn_too",
        "032_why_does_seeing_someone_yawn_make_you_yawn_too",
        "033_the_ancient_computer_found_in_a_shipwreck", "034_what_if_every_human_vanished_tomorrow",
        "035_what_if_every_human_vanished_tomorrow", "037_why_are_humans_ashamed_of_being_naked",
    }
    assert {p.name for p in (ROOT / "videos").iterdir()} == expected


def test_retired_ids_are_absent_from_tracked_paths_and_text() -> None:
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split(chr(0))
    tracked = [item for item in tracked if item]
    banned = _retired_identifiers()
    for rel in tracked:
        lowered = rel.lower()
        assert all(token not in lowered for token in banned), rel
        path = ROOT / rel
        if not path.is_file():
            continue
        raw = path.read_bytes()
        if bytes([0]) in raw[:8192]:
            continue
        try:
            text = raw.decode("utf-8").lower()
        except UnicodeDecodeError:
            continue
        assert all(token not in text for token in banned), rel


def test_pre_registry_host_sheet_is_gone() -> None:
    preset = ROOT / "projects/q_station/visual_presets/001_home_world"
    assert not (preset / "character_sheet.png").exists()
    assert not (preset / "source").exists()
''',
    )

    write(
        "tests/test_content_project_launch.py",
        '''from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from content_projects import (
    list_content_projects,
    load_content_project,
    resolve_project_id,
    validate_content_project,
    video_slug,
)
from video_control_panel import Handler, form_text


def test_q_station_is_the_only_complete_content_project() -> None:
    project = load_content_project("q_station")
    preset = validate_content_project(project)
    assert project.config["status"] == "production_ready"
    assert project.project_id == "q_station"
    assert project.aliases == ()
    assert preset.name == "001_home_world"
    assert [item.project_id for item in list_content_projects()] == ["q_station"]


def test_retired_project_ids_do_not_resolve() -> None:
    retired = (
        "_".join(("question", "harvest")),
        "_".join(("world", "behind", "the", "question")),
    )
    for project_id in retired:
        assert resolve_project_id(project_id) == project_id
        with pytest.raises(RuntimeError, match="Unknown content project"):
            load_content_project(project_id)


def test_panel_exposes_q_station_and_editorial_inputs() -> None:
    page = Handler.page(Handler.__new__(Handler))
    assert "q_station" in page
    assert "value='q_station' selected" in page
    for field in ("working_title", "audience", "narrative_angle", "must_include", "must_avoid", "source_notes"):
        assert f"name={field}" in page
    for field in ("hero_presence_mode", "world_style_policy", "gemini_image_model", "flow_video_model", "flow_resolution", "opening_a_seconds", "opening_b_seconds"):
        assert f"name={field}" in page
    assert "name=world_style_id" in page
    assert "name=world_style_hint" in page
    for locked in ("ChatGPT", "Gemini", "Google Flow"):
        assert locked in page
    assert page.count("disabled") >= 5


def test_panel_form_text_is_bounded() -> None:
    assert form_text({"topic": ["  A question?  "]}, "topic", 20) == "A question?"


def test_video_slug_is_identical_for_every_runner_edge_case() -> None:
    assert video_slug("Why   time?? feels FAST") == "why_time_feels_fast"
    assert video_slug("چرا زمان سریع می‌گذرد؟") == "video"
''',
    )

    write(
        "tests/test_q_station_characters.py",
        '''from __future__ import annotations

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
''',
    )

    SELF.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
