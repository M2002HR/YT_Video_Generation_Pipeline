"""Exercise shipped topic-first stages with provider spies; no network or paid media."""
from __future__ import annotations

import copy
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import opening_runtime as opening
import episode_history as history
import run_question_harvest_pipeline as qh
from character_runtime import load_character_registry
from content_projects import load_content_project, validate_content_project
from run_graph import graph_for, affected_nodes, regeneration_plan
from video_control_panel import config_revision_skips_qh_visual_stages


class State:
    def __init__(self):
        self.completed = set()
    def done(self, stage):
        return stage in self.completed
    def mark(self, stage, status, **kwargs):
        if status in {"DONE", "REUSED"}:
            self.completed.add(stage)


class Spy:
    def __init__(self, responses=()):
        self.responses = list(responses)
        self.state = State()
        self.prompts = []
        self.text_responses = []
    def stage_start(self, stage):
        return 0.0
    def stage_done(self, stage, *args, **kwargs):
        self.state.completed.add(stage)
    def stage_reused(self, stage, *args, **kwargs):
        self.state.completed.add(stage)
    def json(self, stage, prompt, **kwargs):
        assert len(prompt) <= opening.PROMPT_LIMIT
        assert "{{" not in prompt
        self.prompts.append((stage, prompt))
        if not self.responses:
            raise AssertionError("Unexpected provider call at " + stage)
        return copy.deepcopy(self.responses.pop(0))
    def text(self, stage, prompt, **kwargs):
        assert len(prompt) <= opening.PROMPT_LIMIT
        assert "{{" not in prompt
        self.prompts.append((stage, prompt))
        return self.text_responses.pop(0) if self.text_responses else "A concise production prompt preserving the visible event and configured entry."


@pytest.fixture
def registry():
    return load_character_registry(ROOT / "projects/q_station/characters/registry.json")


@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "ROOT", tmp_path)
    reg = tmp_path / "projects/q_station/VIDEOS.json"
    reg.parent.mkdir(parents=True)
    reg.write_text(json.dumps({"videos": []}))
    folder = tmp_path / "videos/099_test"
    (folder / "launch").mkdir(parents=True)
    (folder / "creative").mkdir()
    (folder / "references").mkdir()
    (folder / "launch/CREATIVE_BRIEF.json").write_text(json.dumps({"audience": "curious adults", "source_notes": "Memory can replay patterns without ongoing sound."}))
    (folder / "launch/LAUNCH_REQUEST.json").write_text(json.dumps({"content_project": "q_station"}))
    return folder


def candidates(variant="desk_reach"):
    result = []
    for index, (expectation, conflict) in enumerate([
        ("Stopping the speaker stops the rhythm", "The silent speaker stops but the tapping hand continues"),
        ("A new task replaces the tune", "A different movement accidentally reproduces the old rhythm"),
        ("The final note ends the pattern", "An expected last note remains absent as the host anticipates it"),
    ], 1):
        result.append({
            "id": f"c{index}", "hook_line": "The music stopped. Why does the pattern keep going?",
            "viewer_expectation": expectation, "visible_contradiction": conflict,
            "frame_zero": "A silent speaker beside a hand still tapping a rhythm.",
            "character_action": "The host tests whether stopping the speaker stops the rhythm.",
            "reaction": "One restrained skeptical glance at the still-moving hand.",
            "activity": f"Testing an involuntary rhythm using comparison {index}",
            "location": "A quiet room with one speaker", "topic_link": "Sound has stopped but its remembered pattern continues.",
            "factual_anchor": "Memory can replay a sound pattern without external sound.",
            "payoff": "Distinguish external sound from involuntary musical imagery.",
            "claim_mode": "conservative", "entry_variant": variant,
            "entry_bridge": {"a_end": "Host places the closed book in frame.", "b_start": "Closed top-down book without hands.", "reveal": "The recurring rhythm becomes a memory pattern.", "world_entry": "Sound patterns recur beside a silent speaker in an abstract memory diagram."},
            "novelty": {"action_family": f"test_{index}", "tension_family": f"expectation_{index}", "prop_family": "speaker", "reveal_family": f"comparison_{index}"},
        })
    return {"candidates": result}


def reviews():
    return {"reviews": [{"id": f"c{index}", "scores": {key: 4 for key in opening.CRITERIA}, "blocking_issues": [], "reason": "Concrete discrepancy, supported promise, and a feasible entry."} for index in range(1,4)]}


def narration(entry_key="book_transition"):
    body = [f"Memory keeps a sound pattern active in this example {i}." for i in range(1,8)]
    # 30-40 seconds requires 9-13 beats, so use nine shorter units.
    body = [f"Memory can replay a familiar pattern number {i}." for i in range(1,10)]
    plan = {"opening_question_spark": "The music stopped. Why does the pattern keep going?",
            entry_key: "Memory can replay sound without a speaker.", "body": body,
            "optional_closing": "The pattern kept moving.", "cta": "Which question should we explore next?"}
    plan["full_narration"] = " ".join([plan["opening_question_spark"], plan[entry_key], *body, plan["optional_closing"], plan["cta"]])
    return plan


def make_concept(run, registry, character_id="red_horned_everyman"):
    char = registry.get(character_id)
    variant = char.presentation.entry_variants[0]
    spy = Spy([candidates(variant), reviews()])
    concept = qh.stage_opening_concept(spy, run, load_content_project("q_station"), "earworms", qh.DurationTarget(30,40), char)
    return spy, concept, char


def direction(concept):
    return {"concept_id": concept["concept_id"], "opening_activity": "testing the persistent rhythm", "opening_location": "quiet listening room", "topic_visual_link": "The continuing motion makes the remembered rhythm visible", "link_type": "metaphor", "opening_visual_proof": "A silent speaker and continuing finger tap", "entry_variant": concept["selected"]["entry_variant"], "entry_bridge": concept["selected"]["entry_bridge"], "opening_actions": ["Stop speaker", "Notice continuing rhythm", "Reveal configured entry"], "camera_pattern": "slow_push_in", "hero_presence_mode": "opener_only", "closing_mode": "stay_in_world"}


def story_review():
    return {"checks": {key: True for key in opening.REVIEW_CHECKS}, "issues": []}


def test_project_preflight_includes_new_prompt_contracts():
    project = load_content_project("q_station")
    validate_content_project(project)
    for name in ("00_opening_concept_director.md", "00_opening_candidate_reviewer.md", "03_opening_story_reviewer.md"):
        assert (project.root / "prompts/pipeline" / name).is_file()


@pytest.mark.parametrize("cid", ["red_horned_everyman", "moss_cloaked_crone"])
def test_candidates_are_independently_reviewed_and_frozen(run, registry, cid):
    spy, concept, char = make_concept(run, registry, cid)
    assert concept["policy_version"] == 2
    assert len(spy.prompts) == 2
    assert char.id in spy.prompts[0][1]
    assert json.dumps(char.behavior, ensure_ascii=False) in spy.prompts[0][1]
    assert concept["selected"]["entry_variant"] in char.presentation.entry_variants
    assert (run / "creative/OPENING_CANDIDATES.json").is_file()
    history.record_traits("q_station", "100", {"opening_activity": "another episode"})
    assert qh.stage_opening_concept(spy, run, load_content_project("q_station"), "earworms", qh.DurationTarget(30,40), char) == concept
    assert len(spy.prompts) == 2


def test_changed_editorial_inputs_require_cascade_before_spending(run, registry):
    spy, _, char = make_concept(run, registry)
    with pytest.raises(qh.StageFailure, match="Revise"):
        qh.stage_opening_concept(spy, run, load_content_project("q_station"), "a different topic", qh.DurationTarget(30,40), char)
    assert len(spy.prompts) == 2


def test_cosmetic_or_cta_changes_do_not_invalidate_selected_opening(run, registry):
    spy, concept, char = make_concept(run, registry)
    path = run / "launch/CREATIVE_BRIEF.json"
    raw = json.loads(path.read_text());raw["_subtitle"] = {"font_size": 100};raw["_qh"] = {"cta_hint": "Ask for comments"}
    path.write_text(json.dumps(raw))
    assert qh.stage_opening_concept(spy, run, load_content_project("q_station"), "earworms", qh.DurationTarget(30,40), char) == concept


def test_candidate_reviewer_cannot_pass_malformed_scores():
    proposals = opening.validate_candidates(candidates(), ("desk_reach",))
    raw = reviews();raw["reviews"][0]["scores"]["honesty"] = True
    with pytest.raises(opening.OpeningContractError, match="integer"):
        opening.select_candidate(raw, proposals, [])


def test_candidate_reviewer_reason_has_no_character_limit():
    proposals = opening.validate_candidates(candidates(), ("desk_reach",))
    raw = reviews()
    raw["reviews"][0]["reason"] = "Detailed evidence. " * 100
    selected, decisions = opening.select_candidate(raw, proposals, [])
    assert selected["id"] == "c1"
    assert len(decisions[0]["reason"]) > 500


def test_no_usable_candidate_causes_bounded_redesign(run, registry):
    rejected = reviews()
    for row in rejected["reviews"]:
        row["blocking_issues"] = ["The visible setup does not make the question understandable."]
    spy = Spy([candidates(), rejected, candidates(), reviews()])
    value = qh.stage_opening_concept(spy, run, load_content_project("q_station"), "earworms", qh.DurationTarget(30,40), registry.get("red_horned_everyman"))
    assert value["selected"]["id"] == "c1"
    assert len(spy.prompts) == 4
    assert "Previous design failure" in spy.prompts[2][1]


def test_exhausted_text_corrections_stop_before_media(run, registry):
    rejected = reviews()
    for row in rejected["reviews"]:
        row["scores"]["honesty"] = 0
    spy = Spy([candidates(), rejected] * opening.MAX_ATTEMPTS)
    with pytest.raises(qh.StageFailure, match="bounded text-only"):
        qh.stage_opening_concept(spy, run, load_content_project("q_station"), "earworms", qh.DurationTarget(30,40), registry.get("red_horned_everyman"))
    assert len(spy.prompts) == 2 * opening.MAX_ATTEMPTS
    assert not (run / "creative/OPENING_CONCEPT.json").exists()


def test_candidate_count_unique_mechanisms_and_entry_variant():
    raw = candidates();raw["candidates"] = raw["candidates"][:2]
    with pytest.raises(opening.OpeningContractError, match="exactly 3"):
        opening.validate_candidates(raw)
    raw = candidates();raw["candidates"][1]["novelty"] = raw["candidates"][0]["novelty"]
    with pytest.raises(opening.OpeningContractError, match="dramatic mechanism"):
        opening.validate_candidates(raw)
    with pytest.raises(opening.OpeningContractError, match="Unsupported entry"):
        opening.validate_candidates(candidates(), ("sleeve_reveal",))


def test_repeated_brand_or_camera_is_not_a_hard_collision():
    candidate = candidates()["candidates"][0]
    evidence = opening.repetition_evidence(candidate, [{"video_id": "old", "camera_pattern": "slow_push_in", "entry_variant": "desk_reach", "opening_signature": {"action_family": "test_1"}, "situation_summary": "A different consequence with a different answer"}])
    assert evidence and not evidence[0]["hard_collision"]


def test_same_premise_with_different_location_is_rejected():
    candidate = candidates()["candidates"][0]
    evidence = opening.repetition_evidence(candidate, [{"video_id": "old", "opening_location": "another room", "situation_summary": candidate["visible_contradiction"]}])
    assert evidence[0]["hard_collision"]


def test_sorting_paraphrases_are_flagged_for_semantic_review():
    candidate = {"activity": "arranging tools after work", "visible_contradiction": "A new supported discrepancy", "novelty": {"action_family": "organise_tools"}}
    evidence = opening.repetition_evidence(candidate, [{"video_id": "029", "opening_activity": "sorting tools after work"}])
    assert evidence[0]["activity_similarity"] > .5
    assert evidence[0]["hard_collision"] is False


def test_history_keeps_new_traits_and_excludes_self(run):
    history.record_traits("q_station", "098", {"opening_activity": "sorting tools", "character_id": "red", "opening_signature": {"action_family": "sort"}})
    history.record_traits("q_station", "099", {"opening_activity": "self", "character_id": "red"})
    rows = history.opening_history("q_station", "099_test", "red")
    assert len(rows) == 1 and rows[0]["opening_signature"]["action_family"] == "sort"
    assert history.recent("q_station", 0) == []


def test_registry_read_modify_write_is_atomic_across_threads(run):
    with ThreadPoolExecutor(max_workers=4) as workers:
        list(workers.map(lambda n: history.record_traits("q_station", str(n), {"opening_activity": str(n)}), range(20)))
    assert len(history.load_registry("q_station")["videos"]) == 20


def test_brief_filters_unrelated_payload_but_never_drops_source_constraints():
    raw = {"must_avoid": "No invented probabilities", "source_notes": "a source", "_branding": {"font": "ignored"}}
    result = opening.narrative_brief(raw, "topic", qh.DurationTarget(40,60))
    assert result["must_avoid"] == raw["must_avoid"] and "_branding" not in result
    with pytest.raises(opening.OpeningContractError):
        opening.narrative_brief({"source_notes": "x"*2501}, "t", qh.DurationTarget(40,60))


@pytest.mark.parametrize("cid", ["red_horned_everyman", "moss_cloaked_crone"])
def test_narration_receives_real_story_context_and_stable_segment_key(run, registry, cid):
    _, concept, char = make_concept(run, registry, cid)
    plan = narration(char.presentation.segment_key)
    spy = Spy([plan, plan])
    content = load_content_project("q_station")
    draft = qh.stage_script(spy, run, content, "brief", qh.DurationTarget(30,40), char.presentation, character=char, opening_concept=concept)
    core = qh.stage_retention(spy, run, content, "brief", draft, qh.DurationTarget(30,40), char.presentation, character=char, opening_concept=concept)
    assert char.id in spy.prompts[0][1] and concept["concept_id"] in spy.prompts[1][1]
    assert char.presentation.segment_key in core
    assert "Choose one **ordinary home-world activity**" not in spy.prompts[0][1]
    assert qh.stage_script(spy, run, content, "brief", qh.DurationTarget(30,40), char.presentation, character=char, opening_concept=concept) == draft


def test_direction_review_is_persisted_and_cta_only_revision_reuses_it(run, registry):
    _, concept, char = make_concept(run, registry)
    spy = Spy([direction(concept), story_review()])
    plan = narration()
    content = load_content_project("q_station")
    first = qh.stage_episode_director(spy, run, content, "earworms", "brief", plan, char, opening_concept=concept)
    plan["cta"] = "A new CTA is unrelated to the opening."
    assert qh.stage_episode_director(spy, run, content, "earworms", "brief", plan, char, opening_concept=concept) == first
    assert json.loads((run/"creative/OPENING_REVIEW.json").read_text())["passed"]
    plan["body"][0] = "Changed factual body"
    with pytest.raises(qh.StageFailure, match="stale"):
        qh.stage_episode_director(spy, run, content, "earworms", "brief", plan, char, opening_concept=concept)


def test_bad_staging_receives_specific_bounded_correction(run, registry):
    _, concept, char = make_concept(run, registry)
    first = direction(concept);first["opening_actions"] *= 2
    spy = Spy([first, direction(concept), story_review()])
    qh.stage_episode_director(spy, run, load_content_project("q_station"), "earworms", "brief", narration(), char, opening_concept=concept)
    assert "one to three" in spy.prompts[1][1]


def test_false_payoff_cannot_pass_story_review():
    response = story_review();response["checks"]["hook_paid_off"] = False;response["issues"] = ["The body does not answer the hook."]
    with pytest.raises(opening.OpeningContractError, match="does not answer"):
        opening.validate_review(response)


def test_measured_window_reaches_both_flow_prompt_writers(run, registry):
    _, concept, char = make_concept(run, registry)
    (run/"timing").mkdir()
    (run/"timing/OPENING_SOURCE_PLAN.json").write_text(json.dumps({"clips":{"A":{"target_seconds":3.3},"B":{"target_seconds":2.9}}}))
    spy = Spy()
    for clip, seconds in [("A",6),("B",4)]:
        qh.stage_flow_prompt(spy, run, load_content_project("q_station"), clip, "spoken text", direction(concept), {}, "host-free subject world", "earworms", seconds, character=char, require_source_contract=True)
    assert "3.3" in spy.prompts[0][1] and "2.9" in spy.prompts[1][1]
    assert "SHARED" not in spy.prompts[1][1]
    assert char.appearance_full not in spy.prompts[1][1]
    assert "The recurring rhythm becomes a memory pattern." in spy.prompts[1][1]
    # Same source duration, changed real trim window: cannot reuse the old pacing prompt.
    timing = run/"timing/OPENING_SOURCE_PLAN.json"
    timing.write_text(json.dumps({"clips":{"A":{"target_seconds":4.1}}}))
    qh.stage_flow_prompt(spy, run, load_content_project("q_station"), "A", "spoken text", direction(concept), {}, "host-free subject world", "earworms", 6, character=char, require_source_contract=True)
    assert len(spy.prompts) == 3 and "4.1" in spy.prompts[-1][1]


def test_keyframe_receives_subject_discovery_but_not_host_identity(run, registry):
    _, concept, char = make_concept(run, registry)
    spy = Spy()
    qh.stage_world_keyframe_prompt(spy, run, load_content_project("q_station"), narration(), {})
    assert concept["selected"]["entry_bridge"]["world_entry"] in spy.prompts[0][1]
    assert char.appearance_full not in spy.prompts[0][1]
    assert "no recurring host" in spy.prompts[0][1].lower()


def test_new_stage_reaches_panel_dag_and_cta_remains_isolated(run):
    graph = graph_for(run, include_disabled=True)
    downstream = affected_nodes(graph, ["opening_concept"])
    assert {"script_draft","retention_edit","episode_director","flow_prompt_b","elevenlabs_voiceover","render_baseline"} <= downstream
    cta = affected_nodes(graph, ["call_to_action"])
    assert not {"opening_concept","episode_director","world_style_anchor"} & cta
    assert not config_revision_skips_qh_visual_stages({"kind":"config","roots":["opening_concept"]})
    assert ("book_cover_design", "flow_prompt_b") in {(e["source"],e["target"]) for e in graph["edges"]}


def test_retry_labels_map_to_real_parent_stage():
    assert qh.Runner._fallback_stage("opening_concept_selection_2_json1") == "opening_concept"
    assert qh.Runner._fallback_stage("episode_director_story_review_1_json2") == "episode_director"


def test_budget_and_unfilled_tokens_fail_before_provider():
    with pytest.raises(opening.OpeningContractError, match="Unfilled"):
        opening.fill_prompt("{{MISSING}}")
    with pytest.raises(opening.OpeningContractError, match="exceeds"):
        opening.fill_prompt("x"*19001)


def test_history_budget_keeps_sources_and_latest_context():
    rows = [{"video_id": str(i), "opening_activity": "x"*1600} for i in range(20)]
    source = "critical source detail " * 150
    prompt, used = opening.fill_history_prompt("SOURCE={{SOURCE}}\nHISTORY={{RECENT_OPENINGS}}", SOURCE=source, RECENT_OPENINGS=rows)
    assert source in prompt and len(prompt) <= opening.PROMPT_LIMIT
    assert len(used) < len(rows) and used[-1]["video_id"] == "19"
    with pytest.raises(opening.OpeningContractError, match="Mandatory"):
        opening.fill_history_prompt("{{SOURCE}} {{RECENT_OPENINGS}}", SOURCE="x"*19001, RECENT_OPENINGS=rows)


def test_deployment_preflight_validates_shipped_contracts():
    from check_opening_setup import check
    rows = check()
    assert any("red_horned_everyman: book_portal" in row for row in rows)
    assert any("moss_cloaked_crone: orb_portal" in row for row in rows)


def test_final_director_seam_is_used_for_book_cover_direction(run, registry):
    _, concept, char = make_concept(run, registry)
    plan = direction(concept)
    plan["entry_bridge"]["b_start"] = "The reviewed top-down cover fills the frame without hands."
    (run / "creative/EPISODE_PLAN.json").write_text(json.dumps(plan))
    assert qh.load_entry_story_context(run)["entry_bridge"]["b_start"] == plan["entry_bridge"]["b_start"]


def test_prompt_reuse_tracks_changed_final_entry_direction(run, registry):
    _, concept, char = make_concept(run, registry)
    spy = Spy()
    direction_file = char.presentation.artifacts.path(run, "entry_direction")
    direction_file.write_text("First closed cover design")
    def generate():
        return qh.stage_flow_prompt(spy, run, load_content_project("q_station"), "B", "spoken entry", direction(concept), {}, "subject world", "earworms", 4, character=char)
    generate()
    generate()
    assert len(spy.prompts) == 1
    direction_file.write_text("Corrected closed cover design")
    generate()
    assert len(spy.prompts) == 2
    assert "Corrected closed cover design" in spy.prompts[-1][1]


def test_new_direction_requires_review_artifact_in_graph(run):
    from run_graph import qh_node_specs
    assert "creative/OPENING_REVIEW.json" in qh_node_specs(run)["episode_director"].artifacts
