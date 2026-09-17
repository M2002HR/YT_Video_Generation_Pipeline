"""Exercise the actual shared pipeline with temporary artwork and provider spies."""
from __future__ import annotations

import copy
import json
import shutil
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from captain_test_support import setup_registry, write_sheet
from character_runtime import load_character_registry
from content_projects import load_content_project
from flow_gate import clip_paths
from flow_reference_policy import build_flow_uploads
from presentation_runtime import presentation_for_project
from run_graph import graph_for, affected_nodes, invalidation_paths
import check_character_setup
import episode_history as history
import opening_runtime as opening
import run_question_harvest_pipeline as qh


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
        self.images = []
    def stage_start(self, stage): return 0.0
    def stage_done(self, stage, *args, **kwargs): self.state.completed.add(stage)
    def stage_reused(self, stage, *args, **kwargs): self.state.completed.add(stage)
    def json(self, stage, prompt, **kwargs):
        assert len(prompt) <= opening.PROMPT_LIMIT
        assert "{{" not in prompt
        self.prompts.append((stage, prompt))
        assert self.responses, f"Unexpected provider call: {stage}"
        return copy.deepcopy(self.responses.pop(0))
    def text(self, stage, prompt, **kwargs):
        assert len(prompt) <= opening.PROMPT_LIMIT
        assert "{{" not in prompt
        self.prompts.append((stage, prompt))
        return "Preserve the visible comparison and the captain's blue cuff at the spyglass eyepiece, then reveal the topic world."
    def image(self, stage, prompt, refs, *, model, destination):
        self.images.append((stage, prompt, refs))
        write_sheet(destination)
        return SimpleNamespace(job_id="offline-fixture", generation_receipt={"quality_check": {"passed": True}})


@pytest.fixture
def captain(tmp_path):
    path, sheet = setup_registry(tmp_path, installed=True)
    registry = load_character_registry(path)
    return registry.get("sea_captain")


@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "ROOT", tmp_path)
    registry = tmp_path / "projects/q_station/VIDEOS.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(json.dumps({"videos": []}))
    folder = tmp_path / "videos/099_captain"
    for subdir in ("launch", "creative", "references", "timing"):
        (folder / subdir).mkdir(parents=True)
    (folder / "launch/LAUNCH_REQUEST.json").write_text(json.dumps({
        "content_project": "q_station", "topic": "a visible comparison",
        "image_generation": {"model": "nano_banana_2"},
    }))
    (folder / "launch/CREATIVE_BRIEF.json").write_text(json.dumps({
        "audience": "curious adults", "source_notes": "Use the supplied comparison; do not invent evidence.",
    }))
    return folder


def proposals(captain, topic):
    rows = []
    conflicts = ["Two seemingly similar objects behave differently.",
                 "A visible consequence remains after the apparent cause stops.",
                 "A changed viewpoint exposes a misleading first impression."]
    for index, conflict in enumerate(conflicts, 1):
        rows.append({
            "id": f"c{index}", "hook_line": "Why does this result differ from what we expected?",
            "viewer_expectation": "The first impression seems sufficient.",
            "visible_contradiction": conflict, "frame_zero": conflict,
            "character_action": "Observe the discrepancy and invite a closer look.",
            "reaction": "A small skeptical glance.", "activity": f"Inspecting evidence by mechanism {index}",
            "location": "A simple setting chosen for the question", "topic_link": f"Explain {topic} using this discrepancy.",
            "factual_anchor": "Preserve the supplied source qualifications.",
            "payoff": f"Explain the observed difference in {topic}.", "claim_mode": "hypothetical",
            "entry_variant": captain.presentation.entry_variants[index - 1],
            "entry_bridge": {"a_end": "The captain steadies the eyepiece toward the viewer.",
                             "b_start": "The same eyepiece with one blue-cuffed hand at the edge.",
                             "reveal": "A topic-specific comparison becomes visible through the lens.",
                             "world_entry": "The subject's two contrasting outcomes are visible without a host."},
            "novelty": {"action_family": f"mechanism_{index}", "tension_family": f"tension_{index}",
                        "prop_family": f"evidence_{index}", "reveal_family": f"discovery_{index}"},
        })
    return {"candidates": rows}


def assessments():
    return {"reviews": [{"id": f"c{i}", "scores": {key: 4 if i == 2 else 3 for key in opening.CRITERIA},
                         "blocking_issues": [], "reason": "A readable hypothetical with a feasible entry and defined payoff."}
                        for i in (1, 2, 3)]}


def freeze(run, captain):
    path = run / "creative/PRESENTATION_RESOLUTION.json"
    path.write_text(json.dumps(captain.presentation.to_resolution()))


def test_profile_and_catalog_are_data_driven(captain):
    assert captain.environment_policy == "dynamic"
    assert captain.environment_affinities == ()
    assert captain.reference_mode == "IDENTITY_ONLY"
    profile = captain.presentation
    assert profile.id == "spyglass_portal" and profile.entry_kind == "spyglass"
    assert profile.segment_key == "entry_transition"
    assert profile.entry_frame_character_presence == "ownership_cue"
    assert len(set(profile.entry_variants)) == 6
    assert all(variant in profile.episode_rules for variant in profile.entry_variants)
    assert not profile.identity_required_at_preflight
    assert not profile.identity_sheet_path.exists()
    assert "ship" not in captain.selection_summary()["environment_affinities"]


@pytest.mark.parametrize("topic", ["floating metal", "memory", "electricity", "history", "everyday perception"])
def test_arbitrary_topics_use_independent_selector_and_frozen_history(run, captain, topic):
    spy = Spy([proposals(captain, topic), assessments()])
    project = load_content_project("q_station")
    concept = qh.stage_opening_concept(spy, run, project, topic, qh.DurationTarget(30, 40), captain)
    assert concept["selected"]["id"] == "c2"  # reviewer, not candidate order/self-rating
    assert len(spy.prompts) == 2
    assert captain.id in spy.prompts[0][1] and topic in spy.prompts[0][1]
    assert "spyglass_portal" in spy.prompts[0][1]
    assert json.dumps(captain.behavior, ensure_ascii=False) in spy.prompts[0][1]
    assert (run / "creative/OPENING_CANDIDATES.json").is_file()
    frozen = (run / "creative/OPENING_CONCEPT.json").read_bytes()
    history.record_traits("q_station", "100", {"opening_activity": "another episode completed"})
    assert qh.stage_opening_concept(spy, run, project, topic, qh.DurationTarget(30, 40), captain) == concept
    assert len(spy.prompts) == 2
    assert (run / "creative/OPENING_CONCEPT.json").read_bytes() == frozen
    assert not spy.images


def test_unsupported_entry_variant_is_rejected(captain):
    raw = proposals(captain, "test")
    raw["candidates"][0]["entry_variant"] = "raven_leads"
    with pytest.raises(opening.OpeningContractError, match="Unsupported entry"):
        opening.validate_candidates(raw, captain.presentation.entry_variants)


def test_story_rejection_stops_before_media(run, captain):
    rejected = assessments()
    for row in rejected["reviews"]: row["scores"]["honesty"] = 0
    spy = Spy([proposals(captain, "test"), rejected] * opening.MAX_ATTEMPTS)
    with pytest.raises(qh.StageFailure, match="bounded text-only"):
        qh.stage_opening_concept(spy, run, load_content_project("q_station"), "test", qh.DurationTarget(30, 40), captain)
    assert not spy.images
    assert not (run / "creative/OPENING_CONCEPT.json").exists()


def test_manual_resolution_freezes_captain_and_spyglass(run, captain):
    content = replace(load_content_project("q_station"), root=captain.sheet_path.parents[3])
    spy = Spy()
    launch = {"character": {"mode": "manual", "character_id": "sea_captain"}}
    first, context = qh.stage_character_resolution(spy, run, content, "topic", "brief", None, launch, is_legacy_run=False)
    frozen = (run / "creative/PRESENTATION_RESOLUTION.json").read_bytes()
    assert context.id == first.resolved_character_id == "sea_captain"
    assert json.loads(frozen)["profile_id"] == "spyglass_portal"
    resumed, _ = qh.stage_character_resolution(spy, run, content, "topic", "brief", None, launch, is_legacy_run=False)
    assert resumed.resolved_character_id == "sea_captain"
    assert (run / "creative/PRESENTATION_RESOLUTION.json").read_bytes() == frozen
    assert not spy.prompts


def test_entry_contract_reaches_graph_gate_and_invalidation(run, captain):
    freeze(run, captain)
    assert presentation_for_project(run).id == "spyglass_portal"
    assert [p.name for p in clip_paths(run)] == ["question_intro_source.mp4", "spyglass_transition_source.mp4"]
    graph = graph_for(run, include_disabled=True)
    nodes = {n["id"]: n for n in graph["nodes"]}
    assert nodes["book_cover"]["title"] == "Topic-styled spyglass frame"
    assert nodes["book_cover"]["artifacts"][0]["path"] == "references/spyglass_entry_frame.png"
    assert nodes["flow_clip_b"]["artifacts"][0]["path"] == "assets/opening/spyglass_transition_source.mp4"
    assert {"opening_concept", "script_draft", "flow_clip_a", "flow_clip_b", "opening_trim", "build_timeline"} <= affected_nodes(graph, ["character_resolution"])
    assert {"book_cover", "flow_clip_b", "opening_trim", "build_timeline"} <= affected_nodes(graph, ["world_style_director"])
    assert "opening_concept" not in affected_nodes(graph, ["call_to_action"])
    entry = captain.presentation.artifacts.path(run, "entry_frame")
    entry.write_bytes(b"owned episode artifact")
    assert "references/spyglass_entry_frame.png" in invalidation_paths(run, ["book_cover"])
    assert str(captain.sheet_path) not in invalidation_paths(run, ["character_resolution", "book_design_sheet"])


def test_legacy_book_and_crone_mapping_are_unchanged(run):
    registry = load_character_registry(ROOT / "projects/q_station/characters/registry.json")
    assert registry.auto_fallback_character_id == "red_horned_everyman"
    assert registry.legacy_default_character_id == "farmer_host"
    for identifier in ("farmer_host", "red_horned_everyman"):
        assert registry.get(identifier).presentation.id == "book_portal"
    assert registry.get("moss_cloaked_crone").presentation.id == "orb_portal"
    assert presentation_for_project(run).id == "book_portal"
    assert not (run / "creative/PRESENTATION_RESOLUTION.json").exists()


def test_script_uses_existing_entry_segment_and_closing_beat_contract(captain):
    body = [f"This clear example explains a different part number {n}." for n in range(1, 10)]
    plan = {"opening_question_spark": "Why do these two things behave differently?",
            "entry_transition": "The difference appears when we compare their shapes.",
            "body": body, "optional_closing": "Now the difference makes sense.", "cta": "Which question should we explore next?"}
    plan["full_narration"] = " ".join([plan["opening_question_spark"], plan["entry_transition"], *body, plan["optional_closing"], plan["cta"]])
    assert qh.validate_script_plan("test", plan, qh.DurationTarget(30, 40), captain.presentation)["entry_transition"]
    wrong = dict(plan); wrong["book_transition"] = wrong.pop("entry_transition")
    with pytest.raises(qh.StageFailure, match="entry_transition"):
        qh.validate_script_plan("test", wrong, qh.DurationTarget(30, 40), captain.presentation)


def test_entry_frame_receives_three_references_but_flow_only_two(run, captain, monkeypatch):
    profile = captain.presentation
    (run / "creative/WORLD_STYLE_PLAN.json").write_text(json.dumps({"medium": "graphite", "palette_summary": "cool gray"}))
    style = write_sheet(run / "references/world_style_anchor.png")
    identity = write_sheet(profile.identity_sheet_path)
    captured = {}
    def reusable(runner, project, stage, target, receipt, prompt, model, refs):
        captured.update(prompt=prompt, roles=[ref.role for ref in refs], paths=[ref.path for ref in refs])
        write_sheet(target)
        return True
    monkeypatch.setattr(qh, "reusable_image", reusable)
    target = qh.stage_entry_frame(Spy(), run, load_content_project("q_station"), "a comparison", style, identity,
                                  {"entry_variant": "two_object_compare"}, captain)
    assert captured["roles"] == ["entry_identity", "style_reference", "character_sheet"]
    assert captured["paths"][-1] == captain.sheet_path
    assert "ownership and agency" in captured["prompt"]
    world = write_sheet(run / "references/world_keyframe.png")
    assert [role for role, _ in build_flow_uploads(clip="A", character_sheet=captain.sheet_path)] == ["character_sheet"]
    b = build_flow_uploads(clip="B", entry_frame=target, world_keyframe=world)
    assert b == [("first_frame", target), ("last_frame", world)]


def test_identity_generation_is_lazy_and_receipt_verified(run, captain, monkeypatch, tmp_path):
    monkeypatch.setattr(qh, "ROOT", tmp_path)
    profile = captain.presentation
    assert not profile.identity_sheet_path.exists()
    spy = Spy()
    first = qh.stage_entry_identity(spy, run, load_content_project("q_station"), profile)
    assert first == profile.identity_sheet_path and first.is_file()
    receipt = first.with_suffix(first.suffix + ".receipt.json")
    assert receipt.is_file() and len(spy.images) == 1
    assert qh.stage_entry_identity(spy, run, load_content_project("q_station"), profile) == first
    assert len(spy.images) == 1
    receipt.unlink()
    qh.stage_entry_identity(spy, run, load_content_project("q_station"), profile)
    assert len(spy.images) == 2  # Bare pixels are not silently accepted as a paid-stage receipt.


def test_flow_prompts_receive_profile_and_measured_durations(run, captain):
    (run / "timing/OPENING_SOURCE_PLAN.json").write_text(json.dumps({"clips": {
        "A": {"target_seconds": 4.25}, "B": {"target_seconds": 3.15},
    }}))
    spy = Spy()
    for clip, source_seconds, measured in (("A", 6, "4.25"), ("B", 4, "3.15")):
        qh.stage_flow_prompt(spy, run, load_content_project("q_station"), clip,
                             "The visible comparison gives a useful clue.", {"entry_variant": "two_object_compare"},
                             {"medium": "graphite"}, "A host-free comparison of the subject.", "comparison", source_seconds,
                             character=captain, require_source_contract=True)
        assert measured in spy.prompts[-1][1]
        path = captain.presentation.artifacts.path(run, "question_prompt" if clip == "A" else "entry_prompt")
        contract = json.loads(path.with_suffix(path.suffix + ".inputs.json").read_text())
        assert contract["source_seconds"] == source_seconds
        assert contract["target_seconds"] == float(measured)
    assert "spyglass" in spy.prompts[1][1]
    assert "brass" in spy.prompts[1][1]


def test_world_endpoint_does_not_receive_character_or_entry_identity(run, monkeypatch):
    captured = {}
    def reusable(runner, project, stage, target, receipt, prompt, model, refs):
        captured["roles"] = [ref.role for ref in refs]
        return True
    monkeypatch.setattr(qh, "reusable_image", reusable)
    style = write_sheet(run / "references/world_style_anchor.png")
    qh.stage_world_keyframe(Spy(), run, load_content_project("q_station"), "Host-free subject world.", style)
    assert captured["roles"] == ["style_reference"]


def test_character_preflight_is_read_only(captain, monkeypatch, capsys):
    content = replace(load_content_project("q_station"), root=captain.sheet_path.parents[3])
    monkeypatch.setattr(check_character_setup, "load_content_project", lambda _: content)
    before = sorted(p for p in content.root.rglob("*") if p.is_file())
    assert check_character_setup.main(["--character", "sea_captain"]) == 0
    output = capsys.readouterr().out
    assert "READY:" in output and "spyglass_portal" in output
    assert "No providers called" in output
    assert sorted(p for p in content.root.rglob("*") if p.is_file()) == before
    captain.sheet_path.unlink()
    assert check_character_setup.main(["--character", "sea_captain"]) == 1
    assert "Install" in capsys.readouterr().out


def test_body_character_references_follow_hero_presence(run, captain):
    style = write_sheet(run / "references/world_style_anchor.png")
    world = write_sheet(run / "references/world_keyframe.png")
    present = qh._beat_reference_stack(captain, {"hero_present": True}, style, world, None)
    absent = qh._beat_reference_stack(None, {"hero_present": False}, style, world, None)
    assert any(ref.role == "character_sheet" and ref.path == captain.sheet_path for ref in present)
    assert all(ref.role != "character_sheet" for ref in absent)
