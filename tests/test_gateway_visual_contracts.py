"""Gateway integration regressions: real pipeline functions, no paid providers."""
from __future__ import annotations

import copy
import json
import os
import shutil
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import gateway_contracts as contracts
import image_artifacts
import run_q_station_pipeline as pipeline
from character_runtime import CharacterSelectionError, load_character_registry, resolve_character
from content_projects import load_content_project
from flow_reference_policy import build_flow_uploads
from plan_opening_sources import OpeningSourcePlanError, build_plan
from presentation_runtime import PresentationProfileError, load_presentation_profile, presentation_for_project
from run_graph import graph_for, affected_nodes


def save(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def pixels(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.effect_noise((288, 512), 85).convert("RGB").save(path)
    return path


def approval(prompt: str):
    return contracts.enforce_review({
        "passed": True, "description": "Unit-test fixture; not a real visual review.", "violations": [],
        "contract_checks": {key: {"passed": True, "evidence": "Temporary test evidence."} for key in contracts.requirements(prompt)},
    }, prompt)


class State:
    def __init__(self): self.completed = set()
    def done(self, stage): return stage in self.completed
    def mark(self, stage, status, **kwargs):
        if status in {"DONE", "REUSED"}: self.completed.add(stage)


class Spy:
    def __init__(self, responses=()):
        self.state = State()
        self.responses = list(responses)
        self.prompts = []
        self.videos = []
    def stage_start(self, stage): return 0.0
    def stage_done(self, stage, *args, **kwargs): self.state.completed.add(stage)
    def stage_reused(self, stage, *args, **kwargs): self.state.completed.add(stage)
    def text(self, stage, prompt, **kwargs):
        assert len(prompt) <= 19000 and "{{" not in prompt
        self.prompts.append((stage, prompt))
        return "A readable topic clue appears through the correctly oriented gateway in the established scene."
    def json(self, stage, prompt, **kwargs):
        assert len(prompt) <= 19000 and "{{" not in prompt
        self.prompts.append((stage, prompt))
        return copy.deepcopy(self.responses.pop(0))
    def image_qc_disabled_for(self, stage): return False
    def video(self, stage, prompt, references, **kwargs):
        self.videos.append((stage, prompt, references))
        kwargs["destination"].parent.mkdir(parents=True, exist_ok=True)
        kwargs["destination"].write_bytes(b"offline video fixture, never a production receipt")
        return SimpleNamespace(job_id="fixture", elapsed_seconds=0.0, generation_receipt={"model_verified": True, "actual_duration_seconds": kwargs["duration_seconds"]})


@pytest.fixture
def environment(tmp_path, monkeypatch):
    source = ROOT / "projects/q_station"
    root = tmp_path / "projects/q_station"
    for directory in ("characters", "presentation_profiles", "prompts"):
        shutil.copytree(source / directory, root / directory)
    preset = root / "visual_presets/001_home_world"
    preset.mkdir(parents=True)
    shutil.copy(source / "visual_presets/001_home_world/README.md", preset / "README.md")
    pixels(root / "characters/newton_scholar/refs/character_sheet.png")
    pixels(root / "characters/sea_captain/refs/character_sheet.png")
    content = replace(load_content_project("q_station"), root=root)
    registry = load_character_registry(root / "characters/registry.json")
    run = tmp_path / "videos/999_fixture"
    for sub in ("creative", "launch", "references", "timing", "beats"):
        (run / sub).mkdir(parents=True)
    save(run / "launch/LAUNCH_REQUEST.json", {"content_project": "q_station", "image_generation": {"model": "nano_banana_2"}})
    save(run / "launch/CREATIVE_BRIEF.json", {"_q_station": {}})
    save(run / "creative/WORLD_STYLE_PLAN.json", {"medium": "ink", "frame_language": "old illustrated page border"})
    monkeypatch.setattr(pipeline, "ROOT", tmp_path)
    monkeypatch.setattr(image_artifacts, "ROOT", tmp_path)
    return content, registry, run


def camera(surface="wall", transition="follow_through"):
    return {"surface": surface, "transition": transition,
            "attention_cue": "The leaf moves slightly and he looks toward it.",
            "opening_action": "The hinged leaf opens away from his route.",
            "crossing_action": "He steps through and moves aside; for a hatch he uses supported steps.",
            "camera_path": "Follow alongside, then move through the opening without roll.",
            "world_reveal": "The subject-world mechanism continues beyond the aperture."}


def test_four_mappings_and_operator_installation(environment):
    content, registry, run = environment
    expected = {"red_horned_everyman": "red_door_portal", "moss_cloaked_crone": "orb_portal",
                "sea_captain": "spyglass_portal", "newton_scholar": "book_portal"}
    assert {key: registry.get(key).presentation.id for key in registry.enabled_ids()} == expected
    assert registry.get("newton_scholar").sheet_path.name == "character_sheet.png"
    assert registry.get("sea_captain").presentation.identity_sheet_path.name == "spyglass_design_sheet_v2.png"
    assert registry.get("red_horned_everyman").presentation.entry_frame_character_presence == "acting_host"
    assert not (ROOT / "projects/q_station/characters/newton_scholar/refs/character_sheet.png").exists()


def test_newton_unavailable_is_isolated_and_hot_reloadable(environment):
    content, registry, run = environment
    path = registry.get("newton_scholar").sheet_path
    path.unlink()
    config = content.root / "characters/registry.json"
    unavailable = load_character_registry(config)
    assert "newton_scholar" not in unavailable.enabled_ids()
    assert unavailable.get("red_horned_everyman").presentation.id == "red_door_portal"
    with pytest.raises(CharacterSelectionError):
        unavailable.get("newton_scholar")
    path.write_bytes(b"not a png")
    assert "newton_scholar" not in load_character_registry(config).enabled_ids()
    pixels(path)
    os.utime(path, (1, 1))  # Old upload mtime must not hide the newly installed sheet.
    assert "newton_scholar" in load_character_registry(config).enabled_ids()


@pytest.mark.parametrize("identifier,profile", [("newton_scholar", "book_portal"), ("red_horned_everyman", "red_door_portal")])
def test_new_manual_selection_freezes_matching_presentation(environment, identifier, profile):
    content, registry, run = environment
    spy = Spy()
    launch = {"character": {"mode": "manual", "character_id": identifier}}
    result, context = pipeline.stage_character_resolution(spy, run, content, "question", "brief", None, launch, is_legacy_run=False)
    frozen = (run / "creative/PRESENTATION_RESOLUTION.json").read_bytes()
    assert context.presentation.id == profile
    assert result.resolved_character_id == identifier
    _, resumed = pipeline.stage_character_resolution(spy, run, content, "question", "brief", None, launch, is_legacy_run=False)
    assert resumed.presentation.id == profile and not spy.prompts
    assert (run / "creative/PRESENTATION_RESOLUTION.json").read_bytes() == frozen


def test_newton_auto_can_be_selected_once(environment):
    content, registry, run = environment
    called = []
    first = resolve_character(registry, requested_mode="auto", requested_character_id=None, run_auto_selector=lambda: called.append(1) or {"character_id": "newton_scholar", "confidence": "high", "reason": "Question benefits from comparison and evidence."})
    second = resolve_character(registry, requested_mode="auto", requested_character_id=None, persisted=first.to_state(), run_auto_selector=lambda: pytest.fail("Auto repeated"))
    assert first.resolved_character_id == second.resolved_character_id == "newton_scholar" and called == [1]


def test_old_red_book_resolution_wins_over_new_registry(environment):
    content, registry, run = environment
    book = load_presentation_profile(content.root / "presentation_profiles/book_portal/profile.json")
    save(run / "creative/PRESENTATION_RESOLUTION.json", book.to_resolution())
    saved = (run / "creative/PRESENTATION_RESOLUTION.json").read_bytes()
    launch = {"character": {"mode": "manual", "character_id": "red_horned_everyman"},
              "character_resolution": {"requested_mode": "manual", "resolved_character_id": "red_horned_everyman", "resolution_source": "manual"}}
    _, context = pipeline.stage_character_resolution(Spy(), run, content, "old question", "brief", None, launch, is_legacy_run=False)
    assert context.presentation.segment_key == "book_transition"
    assert context.presentation.id == "book_portal"
    assert (run / "creative/PRESENTATION_RESOLUTION.json").read_bytes() == saved


def test_corrupt_frozen_presentation_never_silently_becomes_book(environment):
    content, registry, run = environment
    (run / "creative/PRESENTATION_RESOLUTION.json").write_text("{bad")
    with pytest.raises(PresentationProfileError, match="Invalid saved presentation"):
        presentation_for_project(run, content)


@pytest.mark.parametrize("transition", contracts.DOOR_TRANSITIONS)
@pytest.mark.parametrize("surface", ["wall", "floor", "freestanding", "other"])
def test_camera_plan_has_one_coherent_supported_mode(environment, transition, surface):
    _, registry, _ = environment
    profile = registry.get("red_horned_everyman").presentation
    episode = {"entry_variant": "floor_hatch" if surface == "floor" else "wrong_wall", "entry_camera": camera(surface, transition)}
    assert contracts.validate_entry_camera(episode, profile) is episode


@pytest.mark.parametrize("broken", [{}, {"entry_camera": {}}, {"entry_camera": {**camera(), "transition": "spin_and_teleport"}}, {"entry_variant": "floor_hatch", "entry_camera": camera("wall")}])
def test_invalid_door_motion_plan_fails_before_media(environment, broken):
    _, registry, _ = environment
    with pytest.raises(ValueError):
        contracts.validate_entry_camera(broken, registry.get("red_horned_everyman").presentation)


@pytest.mark.parametrize("seconds", [0, -1, float("nan"), 4.999])
def test_door_timing_rejects_unreadable_or_invalid_duration(environment, seconds):
    _, registry, _ = environment
    with pytest.raises(ValueError):
        contracts.validate_entry_duration(registry.get("red_horned_everyman").presentation, seconds)


def test_measured_source_planner_refuses_too_short_door_segment(environment):
    content, registry, run = environment
    save(run / "creative/PRESENTATION_RESOLUTION.json", registry.get("red_horned_everyman").presentation.to_resolution())
    save(run / "timing/OPENING_TIMING.json", {"spark_end": 4.0, "transition_end": 8.0})
    with pytest.raises(OpeningSourcePlanError, match="at least 5s"):
        build_plan(run)
    save(run / "timing/OPENING_TIMING.json", {"spark_end": 4.0, "transition_end": 9.4})
    assert build_plan(run)["clips"]["B"]["selected_source_seconds"] >= 5


@pytest.mark.parametrize("identifier", ["red_horned_everyman", "sea_captain"])
def test_entry_start_frame_bakes_actor_and_destination_into_gemini_only(environment, monkeypatch, identifier):
    content, registry, run = environment
    character = registry.get(identifier)
    style = pixels(run / "references/world_style_anchor.png")
    world = pixels(run / "references/world_keyframe.png")
    identity = pixels(character.presentation.identity_sheet_path)
    captured = {}
    def reuse(runner, project, stage, target, receipt, prompt, model, refs):
        captured.update(prompt=prompt, refs=refs)
        pixels(target)
        return True
    monkeypatch.setattr(pipeline, "reusable_image", reuse)
    episode = {"entry_variant": "wrong_wall", "entry_camera": camera()} if identifier == "red_horned_everyman" else {"entry_variant": "far_target"}
    target = pipeline.stage_entry_frame(Spy(), run, content, "specific topic", style, identity, episode, character)
    assert [r.role for r in captured["refs"]] == ["entry_identity", "style_reference", "character_sheet", "world_keyframe"]
    assert captured["refs"][2].path == character.sheet_path
    assert "old illustrated page border" not in captured["prompt"]
    assert contracts.requirements(captured["prompt"])
    assert build_flow_uploads(clip="B", entry_frame=target, world_keyframe=world) == [("first_frame", target), ("last_frame", world)]


def test_door_camera_and_trim_deadline_reach_actual_flow_prompt(environment):
    content, registry, run = environment
    red = registry.get("red_horned_everyman")
    save(run / "timing/OPENING_SOURCE_PLAN.json", {"clips": {"B": {"target_seconds": 6.2}}})
    spy = Spy()
    episode = {"entry_variant": "floor_hatch", "entry_camera": camera("floor", "threshold_dissolve")}
    result = pipeline.stage_flow_prompt(spy, run, content, "B", "A concrete explanatory clue goes here.", episode,
        {"medium": "ink"}, "The host-free world", "topic", 8, character=red, require_source_contract=True)
    assert "threshold_dissolve" in result and "6.200s" in result
    assert "cross" in result and "BEFORE" in result
    assert "entry_camera" in spy.prompts[0][1]


def test_real_reversed_spyglass_warning_is_now_blocking():
    warning = "Spyglass orientation appears reversed relative to the requested eyepiece-facing-viewer direction: the broad objective-style end faces the viewer, while the narrower eyepiece end points away."
    check, _ = pipeline.assess_image_content_qc({"passed": True, "description": "Wrong-end telescope.", "violations": [warning]})
    assert check["passed"] is False and check["blocking_violations"] == [warning]


@pytest.mark.parametrize("contract", list(contracts.CONTRACTS))
def test_every_required_visual_contract_fails_closed_without_evidence(contract):
    prompt = f"[VISUAL_CONTRACT:{contract}]"
    verdict = contracts.enforce_review({"passed": True, "description": "Generic acceptance.", "violations": []}, prompt)
    check, _ = pipeline.assess_image_content_qc(verdict)
    assert check["passed"] is False
    assert not contracts.review_matches(check, prompt)
    assert contracts.review_matches(approval(prompt), prompt)


@pytest.mark.parametrize("bad", [{"passed": "true", "evidence": "Visible"}, {"passed": True, "evidence": ""}, {"passed": False, "evidence": "Large lens touches face."}])
def test_optical_checks_cannot_be_bypassed_by_truthy_values(bad):
    prompt = "[VISUAL_CONTRACT:spyglass_entry_v2]"
    check = approval(prompt)
    check["contract_checks"]["spyglass_entry_v2.small_end_at_eye"] = bad
    verdict, _ = pipeline.assess_image_content_qc(contracts.enforce_review(check, prompt))
    assert not verdict["passed"]


def test_pixel_reviewer_receives_optical_rubric_and_rejects_missing_checks(tmp_path):
    runner = pipeline.Runner.__new__(pipeline.Runner)
    prompts = []
    runner.json = lambda stage, prompt, **kwargs: prompts.append((prompt, kwargs)) or {"passed": True, "description": "A telescope.", "violations": []}
    with pytest.raises(pipeline.StageFailure, match="rejected output"):
        runner.validate_image_content("book_cover", "[VISUAL_CONTRACT:spyglass_entry_v2]", tmp_path / "candidate.png")
    assert "small_end_at_eye" in prompts[0][0]
    assert prompts[0][1]["references"][0].role == "candidate_output"


def test_layout_projection_preserves_media_without_mutating_legacy_plan():
    original = {"medium": "paper cut collage", "texture_family": "paper grain", "frame_language": "deckled page surrounding an inset", "reason": "Old border rationale", "reserve_subtitle_space": False}
    before = copy.deepcopy(original)
    projected = contracts.topic_style(original)
    assert original == before
    assert projected["medium"] == original["medium"] and projected["texture_family"] == "paper grain"
    assert projected["frame_language"] == contracts.WORLD_FRAME
    assert "reason" not in projected and "deckled page" not in json.dumps(projected)
    assert "book or doorway may be a genuine in-world subject" in contracts.WORLD_RULE


def test_world_script_excludes_gateway_choreography():
    plan = {"opening_question_spark": "Why?", "entry_transition": "He opens the door.", "book_transition": "The pages turn.", "body": ["The actual explanation."], "optional_closing": "The factual payoff.", "cta": "Subscribe."}
    assert contracts.factual_world_script(plan) == "The actual explanation. The factual payoff."


def test_body_identity_does_not_include_presentation_rules(environment):
    _, registry, _ = environment
    context = contracts.body_character_context(registry.get("red_horned_everyman"))
    assert "entry_camera" not in context and "door_crossing_v1" not in context
    assert "appearance" in context


def test_new_door_is_visible_to_graph_and_invalidation(environment):
    _, registry, run = environment
    save(run / "creative/PRESENTATION_RESOLUTION.json", registry.get("red_horned_everyman").presentation.to_resolution())
    graph = graph_for(run, include_disabled=True)
    nodes = {node["id"]: node for node in graph["nodes"]}
    assert nodes["book_cover"]["artifacts"][0]["path"] == "references/red_door_entry_frame.png"
    assert nodes["flow_clip_b"]["artifacts"][0]["path"] == "assets/opening/red_door_transition_source.mp4"
    assert {"opening_concept", "flow_clip_a", "flow_clip_b", "opening_trim", "build_timeline"} <= affected_nodes(graph, ["character_resolution"])


def test_profile_cache_notices_old_mtime_prompt_replacement(environment):
    content, registry, _ = environment
    path = content.root / "presentation_profiles/red_door_portal/profile.json"
    old = load_presentation_profile(path)
    prompt = path.parent / "prompts/entry_frame.md"
    prompt.write_text(prompt.read_text() + "\nNew evidence rule.\n")
    os.utime(prompt, (1, 1))
    assert load_presentation_profile(path).entry_frame_prompt != old.entry_frame_prompt


def test_corrupt_input_cache_is_not_reused(tmp_path):
    cache = tmp_path / "cache.json"
    cache.write_text("{broken")
    assert contracts.read_cache(cache) == {}


@pytest.mark.parametrize("identifier", ["red_horned_everyman", "sea_captain"])
def test_acting_entry_dependency_tracks_its_real_world_reference(environment, identifier):
    _, registry, run = environment
    save(run / "creative/PRESENTATION_RESOLUTION.json", registry.get(identifier).presentation.to_resolution())
    graph = graph_for(run, include_disabled=True)
    assert {"book_cover", "flow_clip_b", "opening_trim"} <= affected_nodes(graph, ["world_keyframe"])


def test_crone_does_not_gain_an_unneeded_world_frame_dependency(environment):
    _, registry, run = environment
    save(run / "creative/PRESENTATION_RESOLUTION.json", registry.get("moss_cloaked_crone").presentation.to_resolution())
    assert "book_cover" not in affected_nodes(graph_for(run, include_disabled=True), ["world_keyframe"])


def test_full_bleed_rule_is_enforced_at_actual_keyframe_entrypoint(environment, monkeypatch):
    content, _, run = environment
    style = pixels(run / "references/world_style_anchor.png")
    captured = {}
    def reuse(runner, project, stage, target, receipt, prompt, model, references):
        captured.update(prompt=prompt, references=references)
        pixels(target)
        return True
    monkeypatch.setattr(pipeline, "reusable_image", reuse)
    pipeline.stage_world_keyframe(Spy(), run, content, "Describe the actual subject.", style)
    assert "[VISUAL_CONTRACT:topic_world_v2]" in captured["prompt"]
    assert all(ref.role not in {"character_sheet", "entry_identity"} for ref in captured["references"])


def test_door_with_unreviewed_start_fails_before_flow_spend(environment):
    content, registry, run = environment
    character = registry.get("red_horned_everyman")
    first = pixels(character.presentation.artifacts.path(run, "entry_frame"))
    last = pixels(run / "references/world_keyframe.png")
    spy = Spy()
    with pytest.raises(pipeline.StageFailure, match="geometry acceptance"):
        pipeline.stage_flow_clip(spy, run, content, "B", "A measured crossing.", book_spread=first,
            world_keyframe=last, model="gemini_omni_1_1_flash", resolution="720p", aspect_ratio="9:16", source_seconds=8, character=character)
    assert spy.videos == []



def test_b_prompt_cache_reuses_identical_inputs_and_invalidates_camera_changes(environment):
    content, registry, run = environment
    red = registry.get("red_horned_everyman")
    save(run / "timing/OPENING_SOURCE_PLAN.json", {"clips": {"B": {"target_seconds": 6.2}}})
    spy = Spy()
    episode = {"entry_variant": "wrong_wall", "entry_camera": camera()}
    args = (spy, run, content, "B", "A factual clue accompanies the crossing.", episode,
            {"medium": "ink"}, "The host-free world", "topic", 8)
    first = pipeline.stage_flow_prompt(*args, character=red, require_source_contract=True)
    count = len(spy.prompts)
    assert pipeline.stage_flow_prompt(*args, character=red, require_source_contract=True) == first
    assert len(spy.prompts) == count
    episode["entry_camera"]["transition"] = "texture_takeover"
    updated = pipeline.stage_flow_prompt(*args, character=red, require_source_contract=True)
    assert len(spy.prompts) > count and "texture_takeover" in updated


def test_red_identity_behavior_does_not_assign_the_book(environment):
    _, registry, _ = environment
    behavior = registry.get("red_horned_everyman").behavior
    assert "His book is a fixed bridge" not in behavior
    assert "resolved presentation" in behavior


def test_visual_planner_has_no_entry_behavior_context(environment):
    content, registry, run = environment
    red = registry.get("red_horned_everyman")
    beat = {"beat_id": 1, "narration_slice": "A clear factual answer.", "visual_fingerprint": "distinct_subject", "hero_present": False}
    spy = Spy([{"beats": [beat]}])
    plan = {"opening_question_spark": "Why?", "entry_transition": "Gateway-only sentinel.",
            "body": [beat["narration_slice"]], "optional_closing": "", "cta": "Subscribe."}
    pipeline.stage_visual_plan(spy, run, content, plan, {"entry_camera": camera()}, {"medium": "ink"}, 20, red)
    prompt = spy.prompts[0][1]
    assert "Gateway-only sentinel" not in prompt
    assert "door_crossing_v1" not in prompt and "entry_camera" not in prompt
    assert "A clear factual answer." in prompt
