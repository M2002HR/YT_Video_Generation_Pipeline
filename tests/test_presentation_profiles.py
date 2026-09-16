from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import run_question_harvest_pipeline as qh
from character_runtime import load_character_registry
from content_projects import load_content_project
from flow_gate import clip_paths
from presentation_runtime import PresentationProfileError, presentation_for_project
from run_graph import affected_nodes, graph_for


@pytest.fixture
def registry():
    return load_character_registry(ROOT / "projects/q_station/characters/registry.json")


def freeze_presentation(project: Path, profile) -> None:
    path = project / "creative/PRESENTATION_RESOLUTION.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile.to_resolution()), encoding="utf-8")
    launch = project / "launch/LAUNCH_REQUEST.json"
    launch.parent.mkdir(parents=True, exist_ok=True)
    launch.write_text(json.dumps({"content_project": "q_station"}), encoding="utf-8")


def test_crone_pack_owns_canonical_sheet_and_orb_profile(registry) -> None:
    crone = registry.get("moss_cloaked_crone")
    assert crone.sheet_path == ROOT / "projects/q_station/characters/moss_cloaked_crone/refs/character_sheet.jpg"
    assert crone.sheet_sha256 == "674cfe2e1f5d8aae8e9b72b58a4a833f4623ab377e8cff3e7c996198854830fb"
    assert crone.presentation.id == "orb_portal"
    assert crone.presentation.entry_frame_character_presence == "ownership_cue"
    assert registry.get("red_horned_everyman").presentation.id == "book_portal"


def test_crone_resolution_freezes_presentation_once(tmp_path: Path) -> None:
    project = tmp_path / "run"
    (project / "launch").mkdir(parents=True)
    launch = {"character": {"mode": "manual", "character_id": "moss_cloaked_crone"}}
    class State:
        def mark(self, *args, **kwargs): pass
    class Runner:
        state = State()
        def json(self, *args, **kwargs): raise AssertionError("manual selection must not call Auto")
    resolution, character = qh.stage_character_resolution(
        Runner(), project, load_content_project("q_station"), "topic", "brief", None, launch,
        is_legacy_run=False,
    )
    frozen = json.loads((project / "creative/PRESENTATION_RESOLUTION.json").read_text())
    assert resolution.resolved_character_id == "moss_cloaked_crone"
    assert character.presentation.id == frozen["profile_id"] == "orb_portal"
    assert frozen["artifacts"]["entry_frame"] == "references/orb_entry_frame.png"


def test_script_contract_is_profile_specific(registry) -> None:
    crone = registry.get("moss_cloaked_crone")
    body = [f"This clear body idea number {number} reveals another cause." for number in range(1, 10)]
    parts = ["Why does this happen?", "Her orb opens the hidden world.", *body, "Look again.", "Like and subscribe."]
    plan = {
        "opening_question_spark": parts[0], "entry_transition": parts[1], "body": body,
        "optional_closing": parts[-2], "cta": parts[-1], "full_narration": " ".join(parts),
    }
    assert qh.validate_script_plan("test", plan, qh.DurationTarget(30, 40), crone.presentation)["entry_transition"]
    wrong = dict(plan); wrong["book_transition"] = wrong.pop("entry_transition")
    with pytest.raises(qh.StageFailure, match="entry_transition"):
        qh.validate_script_plan("test", wrong, qh.DurationTarget(30, 40), crone.presentation)


def test_orb_artifact_contract_reaches_gate_and_graph(tmp_path: Path, registry) -> None:
    profile = registry.get("moss_cloaked_crone").presentation
    freeze_presentation(tmp_path, profile)
    assert [path.name for path in clip_paths(tmp_path)] == ["question_intro_source.mp4", "orb_transition_source.mp4"]
    graph = graph_for(tmp_path, include_disabled=True)
    nodes = {node["id"]: node for node in graph["nodes"]}
    episode_inputs = {edge["source"] for edge in graph["edges"] if edge["target"] == "episode_director"}
    assert episode_inputs == {"retention_edit", "character_resolution", "opening_concept"}
    assert nodes["book_cover"]["title"] == "Topic-styled orb frame"
    assert nodes["book_cover"]["artifacts"][0]["path"] == "references/orb_entry_frame.png"
    affected = affected_nodes(graph, ["world_style_director"])
    assert {"world_style_anchor", "book_cover", "flow_clip_b", "opening_trim", "build_timeline"} <= affected


def test_manual_character_revision_graph_previews_destination_profile(tmp_path: Path) -> None:
    launch = tmp_path / "launch/LAUNCH_REQUEST.json"
    launch.parent.mkdir(parents=True)
    launch.write_text(json.dumps({"content_project": "q_station"}), encoding="utf-8")
    graph = graph_for(tmp_path, include_disabled=True, settings={
        "content_project": "q_station",
        "qh": {"character": {"mode": "manual", "character_id": "moss_cloaked_crone"}},
    })
    nodes = {node["id"]: node for node in graph["nodes"]}
    assert nodes["book_cover"]["title"] == "Topic-styled orb frame"
    assert nodes["flow_clip_b"]["artifacts"][0]["path"] == "assets/opening/orb_transition_source.mp4"


def test_historical_run_without_presentation_resolution_defaults_to_book(tmp_path: Path) -> None:
    launch = tmp_path / "launch/LAUNCH_REQUEST.json"
    launch.parent.mkdir(parents=True)
    launch.write_text(json.dumps({"content_project": "q_station"}), encoding="utf-8")
    assert presentation_for_project(tmp_path).id == "book_portal"
    assert [path.name for path in clip_paths(tmp_path)] == ["question_spark_source.mp4", "book_transition_source.mp4"]


def test_persisted_profile_version_drift_fails_loudly(tmp_path: Path, registry) -> None:
    profile = registry.get("moss_cloaked_crone").presentation
    payload = profile.to_resolution(); payload["profile_version"] = 999
    freeze_presentation(tmp_path, profile)
    (tmp_path / "creative/PRESENTATION_RESOLUTION.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(PresentationProfileError, match="version"):
        presentation_for_project(tmp_path)


def test_orb_entry_frame_uses_identity_style_and_crone_sheet(tmp_path: Path, registry, monkeypatch) -> None:
    project = tmp_path / "run"
    (project / "launch").mkdir(parents=True)
    (project / "creative").mkdir(parents=True)
    (project / "launch/LAUNCH_REQUEST.json").write_text(json.dumps({"image_generation": {"model": "nano_banana_2"}}))
    (project / "creative/WORLD_STYLE_PLAN.json").write_text(json.dumps({"palette_summary": "ochre ink"}))
    crone = registry.get("moss_cloaked_crone")
    identity = project / "orb.png"; identity.write_bytes(b"identity")
    style = project / "style.png"; style.write_bytes(b"style")
    captured = {}
    class State:
        def done(self, stage): return False
    class Runner:
        state = State()
        def stage_start(self, stage): return 0
        def stage_done(self, *args, **kwargs): pass
        def text(self, stage, prompt): return "Topic motifs arranged in the orb with the crone's moss sleeve and raven clearly guiding the reveal."
        def stage_reused(self, *args): pass
    def reusable(runner, project, stage, target, receipt, prompt, model, refs):
        captured["roles"] = [ref.role for ref in refs]
        captured["prompt"] = prompt
        return True
    monkeypatch.setattr(qh, "reusable_image", reusable)
    qh.stage_entry_frame(Runner(), project, load_content_project("q_station"), "topic", style, identity, {"entry_variant": "raven_leads"}, crone)
    assert captured["roles"] == ["entry_identity", "style_reference", "character_sheet"]
    assert "ownership and agency" in captured["prompt"]
