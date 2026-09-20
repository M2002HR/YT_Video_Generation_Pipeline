from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from shorts_v2.contracts import ContractError
from shorts_v2.creative import (
    PROMPTS, build_character_performance_context, build_creative_prompt, load_character_profiles, semantic_history,
    select_hook_tournament, validate_evidence_pack, validate_hook_reviews,
    validate_six_hooks, validate_story_and_script,
)


@pytest.fixture
def evidence() -> dict:
    return validate_evidence_pack({
        "schema_version": 1, "topic": "What if Earth gravity were cut in half?",
        "sources": [{
            "source_id": "src.nasa.gravity", "kind": "retrieved", "title": "Gravity reference",
            "url": "https://science.nasa.gov/universe/gravity/", "retrieved_at": "2026-09-20T10:00:00Z",
            "excerpt": "Mass attracts mass.", "scope": "introductory gravity explanation",
            "qualification": "The episode is a hypothetical sudden change, not an observed event.",
            "verification_status": "verified",
        }],
        "claims": [{
            "claim_id": "claim.half_weight", "text": "At the surface, the same person would weigh about half as much under the stated assumption.",
            "mode": "hypothetical", "importance": "central", "source_ids": ["src.nasa.gravity"],
            "scope": "surface weight in the simplified thought experiment",
            "qualification": "This assumes surface gravitational acceleration alone is halved.",
            "verification_status": "verified",
        }],
    })


def hook(index: int, model: str = "eleven_multilingual_v2") -> dict:
    mechanisms = ["consequence first", "expectation reversal", "scale contradiction", "failed action", "silent reveal", "countdown consequence"]
    return {
        "hook_id": f"hook.{index}", "dramatic_mechanism": mechanisms[index], "narrative_role": "open the gravity thought experiment",
        "scenario_signature": f"scenario-{index}", "frame_zero_interrupt": f"object-{index} rises unexpectedly",
        "first_300ms_read": "the host and one rising object", "first_second_event": "one object rises from the host's hand",
        "spoken_hook": "Your body didn't get stronger. Gravity just got weaker.",
        "character_burst": "brief disbelief caused by the rising object",
        "vocal_burst": "a sharp controlled realization caused by the result",
        "stakes": "ordinary movement becomes unexpectedly dangerous", "curiosity_gap": "what happens after the first jump",
        "claim_ids": ["claim.half_weight"], "truth_anchor": "the stated half-gravity thought experiment",
        "claim_mode": "hypothetical", "payoff_debt": "explain why lower weight does not make movement consequence-free",
        "answer_point": "after the causal comparison", "escalation_1_3s": "the host's next step carries farther",
        "first_new_information": "weight changes while mass remains", "gateway_handoff": "the rising object becomes the portal subject",
        "presentation_feasibility": "one readable event fits every gateway",
        "voice_feasibility": {"tts_model": model, "essential_effect": "", "effect_supported": True, "fallback_performance": "controlled surprise"},
        "history_signature": {"visual": f"rising-{index}", "reaction": f"reaction-{index}", "voice": f"voice-{index}", "syntax": f"syntax-{index}", "handoff": f"handoff-{index}"},
    }


def reviews(bad_first: bool = False) -> list[dict]:
    output = []
    for index in range(6):
        gates = {"topic_grounded": True, "truthful": True, "payoff_funded": True, "readable": True, "voice_feasible": True}
        reasons = []
        if index == 0 and bad_first:
            gates["topic_grounded"] = False
            reasons = ["The scream has no narrative cause in the gravity event."]
        output.append({
            "hook_id": f"hook.{index}", "gates": gates,
            "scores": {"immediacy": 5 - index % 2, "specificity": 4, "curiosity": 4, "clarity": 4, "character_fit": 4},
            "rejection_reasons": reasons, "reviewer_rationale": "Gates assessed before editorial scoring.",
        })
    return output


def test_t27_four_versioned_profiles_have_baseline_burst_avoid_and_two_voice_bindings() -> None:
    payload = load_character_profiles()
    assert payload["profile_version"] == "shorts-v2.2-creative-r1" and len(payload["characters"]) == 4
    for profile in payload["characters"].values():
        assert profile["baseline_demeanor"] and profile["hook_burst_range"] and profile["avoid"]
        assert set(profile["voice_bindings"]) == {"eleven_v3", "eleven_multilingual_v2"}
        assert all(item["calibration"] == "documented_not_calibrated" for item in profile["voice_bindings"].values())
    context = build_character_performance_context(
        "red_horned_everyman", topic="gravity", tts_model="eleven_multilingual_v2",
        fixed_identity={"sheet_sha256": "a" * 64, "appearance": "fixed canonical appearance"},
    )
    assert context["behavior_override_scope"] == "shorts_v2_only"
    assert context["fixed_identity"]["sheet_sha256"] == "a" * 64
    assert context["selected_voice_binding"]["tts_model"] == "eleven_multilingual_v2"


def test_t24_six_distinct_hooks_and_order_independent_tournament(evidence: dict) -> None:
    hooks = validate_six_hooks([hook(i) for i in range(6)], evidence=evidence, tts_model="eleven_multilingual_v2")
    assessment, winner = reviews(), select_hook_tournament(hooks, reviews())
    random.Random(44).shuffle(hooks); random.Random(91).shuffle(assessment)
    assert select_hook_tournament(hooks, assessment)["selected_hook_id"] == winner["selected_hook_id"] == "hook.0"
    duplicate = [hook(i) for i in range(6)]; duplicate[5]["scenario_signature"] = duplicate[0]["scenario_signature"]
    with pytest.raises(ContractError, match="semantically distinct"):
        validate_six_hooks(duplicate, evidence=evidence, tts_model="eleven_multilingual_v2")


def test_t25_unrelated_scream_loses_hard_gate_despite_maximum_score(evidence: dict) -> None:
    hooks = validate_six_hooks([hook(i) for i in range(6)], evidence=evidence, tts_model="eleven_multilingual_v2")
    assessment = reviews(True); assessment[0]["scores"] = {key: 5 for key in assessment[0]["scores"]}
    assert validate_hook_reviews(hooks, assessment)[0]["eligible"] is False
    assert select_hook_tournament(hooks, assessment)["selected_hook_id"] != "hook.0"


def test_t28_v2_rejects_essential_unsupported_effect_without_fallback(evidence: dict) -> None:
    values = [hook(i) for i in range(6)]
    values[2]["voice_feasibility"] = {"tts_model": "eleven_multilingual_v2", "essential_effect": "precisely controlled wicked scream", "effect_supported": False, "fallback_performance": ""}
    with pytest.raises(ContractError, match="unsupported v2 vocal effect"):
        validate_six_hooks(values, evidence=evidence, tts_model="eleven_multilingual_v2")
    values[2]["voice_feasibility"]["fallback_performance"] = "visual alarm plus achievable emphatic delivery"
    assert validate_six_hooks(values, evidence=evidence, tts_model="eleven_multilingual_v2")


def script(evidence: dict) -> dict:
    qualification = evidence["claims"][0]["qualification"]
    return {
        "schema_version": 1,
        "story_blueprint": {"question": "What changes first?", "misconception": "Half gravity means effortless control.", "clue": "Weight falls but mass remains.", "causal_chain": ["surface acceleration is halved", "weight falls while inertia remains"], "result": "A jump carries farther and is harder to correct.", "payoff": "Lower weight does not remove inertia, so movement still has consequences.", "ending": "The easy jump is the trap.", "claim_ids": ["claim.half_weight"]},
        "script_core": [
            {"unit_id": "unit.hook", "text": "Your weight drops, but your mass doesn't.", "claim_ids": ["claim.half_weight"], "qualifiers": [qualification]},
            {"unit_id": "unit.payoff", "text": "So the jump carries farther, and stopping it is still your problem.", "claim_ids": ["claim.half_weight"], "qualifiers": []},
        ],
        "cta": {"intent": "ask viewers to suggest the next topic", "text": "Suggest the next impossible question in the comments."},
        "reviews": {
            "retention_edit": {"status": "pass", "reasons": ["Every unit advances the causal chain."], "preserved_qualifiers": True},
            "spoken_naturalness": {"status": "pass", "reasons": ["Short conversational clauses."], "preserved_qualifiers": True},
            "factual_script": {"status": "pass", "reasons": ["Mass and weight remain distinct."], "preserved_qualifiers": True},
        },
    }


def test_t26_payoff_cta_separation_and_qualification_preservation(evidence: dict) -> None:
    selected, value = hook(0), script(evidence)
    valid = validate_story_and_script(value, evidence=evidence, selected_hook=selected)
    assert valid["full_narration"].endswith(valid["cta"]["text"]) and valid["script_core_hash"] != valid["cta_hash"]
    value = script(evidence); value["script_core"][0]["qualifiers"] = []
    with pytest.raises(ContractError, match="erased a scientific qualification"):
        validate_story_and_script(value, evidence=evidence, selected_hook=selected)
    value = script(evidence); value["story_blueprint"]["payoff"] = selected["payoff_debt"]
    with pytest.raises(ContractError, match="answer the debt"):
        validate_story_and_script(value, evidence=evidence, selected_hook=selected)


def test_t26_evidence_rejects_fake_retrieval_and_background_only_central_claim() -> None:
    raw = {"schema_version": 1, "topic": "x", "sources": [{"source_id": "src.x", "kind": "retrieved", "title": "x", "url": "", "retrieved_at": "", "excerpt": "x", "scope": "x", "qualification": "x", "verification_status": "verified"}], "claims": [{"claim_id": "claim.x", "text": "x", "mode": "real", "importance": "central", "source_ids": ["src.x"], "scope": "x", "qualification": "x", "verification_status": "verified"}]}
    with pytest.raises(ContractError, match="URL and retrieval time"):
        validate_evidence_pack(raw)
    raw["sources"][0].update(kind="conservative_background", title="Conservative background note")
    with pytest.raises(ContractError, match="background-only"):
        validate_evidence_pack(raw)


def test_prompt_package_has_contract_examples_and_strict_context() -> None:
    assert len(PROMPTS) == 10
    for prompt_id, spec in PROMPTS.items():
        rendered = build_creative_prompt(prompt_id, {name: {"fixture": name} for name in spec.required_context})
        assert spec.version == "shorts-v2.2-p04-r1" and "OUTPUT_CONTRACT:" in rendered and "untrusted data" in rendered
        assert spec.few_shot and spec.failing_fixture
        with pytest.raises(ContractError, match="missing context"):
            build_creative_prompt(prompt_id, {})


def test_t65_history_dedupes_aliases_weights_outcome_and_preserves_ab_claims() -> None:
    rows = [
        {"video_id": "045", "outcome": "planned", "character_id": "sea_captain"},
        {"video_id": "045_elephant", "outcome": "published", "character_id": "sea_captain"},
        {"video_id": "046_test", "outcome": "failed", "character_id": "newton_scholar"},
        {"video_id": "047_variant_a", "outcome": "completed", "character_id": "sea_captain", "experiment_family": "exp.gravity", "claim_ids": ["claim.half_weight"]},
    ]
    result = semantic_history(rows, current_episode_id="047_variant_b", character_id="sea_captain", experiment_family="exp.gravity")
    assert [row["canonical_episode_id"] for row in result].count("45") == 1
    assert next(row for row in result if row["canonical_episode_id"] == "45")["outcome"] == "published"
    assert next(row for row in result if row["canonical_episode_id"] == "46")["history_weight"] < .2
    assert next(row for row in result if row["canonical_episode_id"] == "47")["allow_same_claim_for_ab"] is True
