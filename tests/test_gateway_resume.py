from __future__ import annotations
import copy
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from opening_runtime import fingerprint
from gateway_resume import retains_approved_concept


def fixture(profile):
    frozen = {"policy_version": 2, "brief": {"topic": "example", "duration_seconds": [40,60]},
              "character": {"id": "fixture_host", "tone": ["calm"], "behavior": "old", "negative_constraints": "old"},
              "presentation": {"profile_id": profile, "entry_segment_key": "entry_transition", "script_rules": "old", "episode_rules": "old", "entry_frame_character_presence": "ownership_cue"},
              "writer_sha256": "writer", "reviewer_sha256": "reviewer", "language_policy_version": 1}
    old_hash = fingerprint(frozen)
    current = copy.deepcopy(frozen)
    current["gateway_inputs_version"] = 1
    current["character"]["behavior"] = "Current acting prose."
    current["presentation"].update(script_rules="Current geometry rules", entry_frame_character_presence="acting_host", motion_contract="", min_entry_seconds=0, min_entry_words=0)
    selected = {"id": "candidate", "payoff": "Original approved factual payoff."}
    concept = {"input_fingerprint": old_hash, "concept_id": fingerprint({"input": old_hash, "selected": selected})[:20], "selected": selected,
               "character_id": "fixture_host", "presentation_id": profile}
    frozen.update(input_fingerprint=old_hash, history=[])
    return frozen, current, concept


@pytest.mark.parametrize("profile", ["book_portal", "orb_portal", "spyglass_portal"])
def test_only_verified_old_prose_changes_are_compatible(profile):
    frozen, current, concept = fixture(profile)
    before = copy.deepcopy(frozen)
    assert retains_approved_concept(frozen, current, concept)
    assert frozen == before


@pytest.mark.parametrize("field", ["brief", "character", "presentation", "writer_sha256", "reviewer_sha256", "language_policy_version"])
def test_real_input_changes_are_never_waived(field):
    frozen, current, concept = fixture("book_portal")
    current[field] = {"changed": True}
    assert not retains_approved_concept(frozen, current, concept)


@pytest.mark.parametrize("target", ["context_hash", "concept_hash", "selected", "new_context", "character_id", "profile_id"])
def test_unverifiable_or_new_artifacts_are_not_legacy(target):
    frozen, current, concept = fixture("spyglass_portal")
    if target == "context_hash": frozen["input_fingerprint"] = "bad"
    elif target == "concept_hash": concept["concept_id"] = "bad"
    elif target == "selected": concept["selected"]["payoff"] = "Changed payoff"
    elif target == "new_context": frozen["gateway_inputs_version"] = 1
    elif target == "character_id": concept["character_id"] = "another_host"
    elif target == "profile_id": concept["presentation_id"] = "red_door_portal"
    assert not retains_approved_concept(frozen, current, concept)


def test_brand_new_door_cannot_claim_pre_rollout_status():
    assert not retains_approved_concept(*fixture("red_door_portal"))
