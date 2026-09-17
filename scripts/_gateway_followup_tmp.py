# Additional focused patches and current-contract test updates; uses base script helpers.
P = 'scripts/run_q_station_pipeline.py'
G = 'scripts/gateway_contracts.py'
edit(G, '    return " ".join(str(part).strip() for part in [*plan.get("body", []), plan.get("optional_closing", "")] if str(part).strip())', '    if "body" not in plan:\n        return str(plan.get("full_narration") or "")\n    return " ".join(str(part).strip() for part in [*plan.get("body", []), plan.get("optional_closing", "")] if str(part).strip())')
write(G, read(G) + '''

def read_cache(path: Any) -> dict[str, Any]:
    """A truncated cache is a cache miss, never permission to reuse an artifact."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}
''')
edit(P, 'cached = load_json(cache_path) if cache_path.is_file() else {}', 'cached = visuals.read_cache(cache_path)', count=2)
edit(P, 'saved_direction = load_json(direction_cache_path) if direction_cache_path.is_file() else {}', 'saved_direction = visuals.read_cache(direction_cache_path)')
edit(P, '    expected_uploads = build_flow_uploads(clip="A", character_sheet=(character or _coerce_character_context(content_project)).sheet_path) if clip == "A" else build_flow_uploads(clip="B", entry_frame=book_spread, world_keyframe=world_keyframe)\n    current_refs = [{"role": role, "sha256": sha256_file(path)} for role, path in expected_uploads]\n    recorded_refs = stored_receipt.get("references")\n    refs_match = recorded_refs is None or [{"role": item.get("role"), "sha256": item.get("sha256")} for item in recorded_refs] == current_refs', '''    recorded_refs = stored_receipt.get("references")
    refs_match = recorded_refs is None and (clip == "A" or not visuals.requirements(presentation.entry_frame_prompt))
    if isinstance(recorded_refs, list):
        expected_uploads = build_flow_uploads(clip="A", character_sheet=(character or _coerce_character_context(content_project)).sheet_path) if clip == "A" else build_flow_uploads(clip="B", entry_frame=book_spread, world_keyframe=world_keyframe)
        refs_match = (all(path.is_file() for _, path in expected_uploads)
                      and all(isinstance(item, dict) for item in recorded_refs)
                      and [{"role": item.get("role"), "sha256": item.get("sha256")} for item in recorded_refs]
                      == [{"role": role, "sha256": sha256_file(path)} for role, path in expected_uploads])''')
edit(P, '    if clip == "B" and visuals.requirements(presentation.entry_frame_prompt):\n        entry_receipt =', '''    if clip == "B":
        try:
            visuals.validate_entry_duration(presentation, float(source_seconds))
        except ValueError as exc:
            raise StageFailure(stage, "FAILED_VALIDATION", str(exc)) from exc
    if clip == "B" and visuals.requirements(presentation.entry_frame_prompt):
        entry_receipt =''')
edit(P, '        data = load_json(entry_receipt) if entry_receipt.is_file() else {}\n        if (book_spread is None or data.get("output_sha256") != sha256_file(book_spread)', '        data = visuals.read_cache(entry_receipt)\n        if (book_spread is None or not valid_image(book_spread) or data.get("output_sha256") != sha256_file(book_spread)\n                or receipt_status(project, book_spread, entry_receipt)["status"] != "verified"')
edit(P, '            world_style_anchor = stage_world_style_anchor(runner, project, content_project, world_style_plan)', '''            if presentation.min_entry_seconds:
                source_plan_path = project / "timing/OPENING_SOURCE_PLAN.json"
                if not args.use_opening_source_plan or not source_plan_path.is_file():
                    raise StageFailure("opening_source_plan", "FAILED_VALIDATION", "This gateway requires real narration alignment. Use the full wrapper or --use-opening-source-plan before requesting visual media.")
                source_plan = load_json(source_plan_path)
                try:
                    visuals.validate_entry_duration(presentation, float(source_plan["clips"]["B"]["target_seconds"]))
                except (KeyError, TypeError, ValueError) as exc:
                    raise StageFailure("opening_source_plan", "FAILED_VALIDATION", str(exc)) from exc
            world_style_anchor = stage_world_style_anchor(runner, project, content_project, world_style_plan)''')
edit(P, '        if len(existing_beats) == len(visual_units) and existing_slices == visual_units:', '        if (len(existing_beats) == len(visual_units) and existing_slices == visual_units\n                and existing.get("layout_policy") == visuals.WORLD_LAYOUT):')
edit(P, '    beats = data["beats"]\n    save_json(target, data)', '    beats = data["beats"]\n    data["layout_policy"] = visuals.WORLD_LAYOUT\n    save_json(target, data)')

# Current assertions replace old product-specific assumptions, not operational coverage.
C = 'tests/test_q_station_characters.py'
edit(C, 'test_registry_declares_exactly_three_character_packs', 'test_registry_declares_exactly_four_character_packs')
edit(C, '        "red_horned_everyman", "moss_cloaked_crone", "sea_captain"\n', '        "red_horned_everyman", "moss_cloaked_crone", "sea_captain", "newton_scholar"\n')
replace_function(C, 'expected_available_ids', '''def expected_available_ids() -> tuple[str, ...]:
    ready = ["red_horned_everyman", "moss_cloaked_crone"]
    for identifier in ("sea_captain", "newton_scholar"):
        sheet = ROOT / f"projects/q_station/characters/{identifier}/refs/character_sheet.png"
        if operator_reference_error(sheet) is None:
            ready.append(identifier)
    return tuple(ready)
''')
C = 'tests/test_sea_captain_integration.py'
edit(C, 'assert profile.entry_frame_character_presence == "ownership_cue"', 'assert profile.entry_frame_character_presence == "acting_host"')
edit(C, 'The captain steadies the eyepiece toward the viewer.', 'The captain places the small eyepiece beside his visible eye.')
edit(C, 'The same eyepiece with one blue-cuffed hand at the edge.', 'Oblique view: small end at the eye, wide objective toward the subject.')
edit(C, 'return SimpleNamespace(job_id="offline-fixture", generation_receipt={"quality_check": {"passed": True}})', '''check = qstation.visuals.enforce_review({"passed": True, "description": "Temporary fixture, no real model review.", "violations": [],
            "contract_checks": {key: {"passed": True, "evidence": "Fixture acceptance only."} for key in qstation.visuals.requirements(prompt)}}, prompt)
        return SimpleNamespace(job_id="offline-fixture", generation_receipt={"quality_check": check})''')
replace_function(C, 'test_legacy_book_and_crone_mapping_are_unchanged', '''def test_legacy_book_and_crone_mapping_are_unchanged(run):
    registry = load_character_registry(ROOT / "projects/q_station/characters/registry.json")
    assert registry.auto_fallback_character_id == "red_horned_everyman"
    assert registry.legacy_default_character_id == "red_horned_everyman"
    assert registry.get("red_horned_everyman").presentation.id == "red_door_portal"
    assert registry.get("moss_cloaked_crone").presentation.id == "orb_portal"
    assert presentation_for_project(run).id == "book_portal"  # historical, not a new-run default
    assert not (run / "creative/PRESENTATION_RESOLUTION.json").exists()
''')
C = 'tests/test_presentation_profiles.py'
text = read(C)
text = text.replace('registry.get("red_horned_everyman").presentation.id == "book_portal"', 'registry.get("red_horned_everyman").presentation.id == "red_door_portal"')
write(C, text)
write('tests/test_episode_frame_contract.py', '''from __future__ import annotations
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from run_q_station_pipeline import episode_frame_contract

@pytest.mark.parametrize("legacy_frame", ["deckled-paper border", "painted card and inner window", "manuscript border", "circular telescope mask"])
def test_frame_contract_replaces_enclosing_layout_but_not_the_medium(legacy_frame):
    prompt = episode_frame_contract({"frame_language": legacy_frame, "medium": "ink", "reserve_subtitle_space": False})
    assert "[VISUAL_CONTRACT:topic_world_v2]" in prompt
    assert "full usable height" in prompt
    assert "Preserve this recurring frame language" not in prompt
    assert f"image: {legacy_frame}" not in prompt
    assert "rendering textures" in prompt

def test_frame_contract_has_full_bleed_default():
    assert "entire 9:16 canvas" in episode_frame_contract({})

def test_frame_contract_does_not_reserve_space_when_disabled():
    assert "Do not reserve a lower caption field" in episode_frame_contract({"reserve_subtitle_space": False})

def test_frame_contract_keeps_optional_caption_field_small_and_unprinted():
    result = episode_frame_contract({"reserve_subtitle_space": True})
    assert "bottom 8-10%" in result and "No printed text" in result
''')
