from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from shorts_v2.contracts import ContractError
from shorts_v2.visual_planning import (
    accept_asset_result, asset_prompt, build_asset_manifest, build_opening_plan, diff_asset_manifests,
    generation_batches, media_policy, validate_observation, validate_shot_plan,
)


def fake_timing(count: int = 60, *, seconds_per_word: float = .5) -> dict:
    words = []
    for index in range(count):
        start = index * seconds_per_word
        words.append({"word_id": f"unit.one.w{index + 1:04d}", "unit_id": "unit.one", "canonical_text": f"word{index}", "start": start, "end": start + seconds_per_word * .8, "confidence": .95, "method": "measured_word"})
    return {"timing_hash": "a" * 64, "audio": {"duration_seconds": count * seconds_per_word}, "words": words}


def shot(index: int, word_ids: list[str]) -> dict:
    return {
        "shot_id": f"shot.{index:03d}", "display_order": index, "unit_ids": ["unit.one"],
        "word_span_ids": word_ids, "role": "explanation", "new_information": f"new causal detail {index}",
        "focus": f"subject state {index}", "scene_group": "scene.gravity", "asset_requirements": [f"asset.{index:03d}"],
        "reading_complexity": "simple", "timing_constraints": {"cut_on_word": word_ids[0]},
        "cut_reason": "new fact", "manual_locks": {},
    }


def shot_plan(count: int = 4) -> dict:
    timing = fake_timing(max(count, 4))
    return validate_shot_plan({
        "schema_version": 1,
        "preset": {"simple_seconds": [0.8, 1.4], "complex_seconds": [1.4, 2.4], "detail_seconds": [0.35, 0.6], "economic_asset_ceiling": None},
        "shots": [shot(index, [timing["words"][index]["word_id"]]) for index in range(count)],
    }, timing=timing)


def asset(index: int, shot_id: str, *, media_type="image", generator="chatgpt_image") -> dict:
    return {
        "asset_id": f"asset.{index:03d}", "role": "body_explanation", "media_type": media_type,
        "subject": f"person demonstrating state {index}", "action": "moving through the scene", "state": f"state {index}",
        "composition": "full-bleed vertical medium shot", "medium": "ink and paper collage",
        "identity_reference": "fixed host identity", "scene_group": "scene.gravity",
        "reference_roles": [
            {"role": "style", "sha256": "a" * 64, "source_id": "ref.style"},
            {"role": "identity", "sha256": "b" * 64, "source_id": "ref.identity"},
        ],
        "generator": generator, "shot_ids": [shot_id], "reuse_reason": "new precise image is artistically clearer", "manual_locks": {},
    }


def test_t37_one_unit_can_own_four_independent_images_and_sixty_have_no_cost_ceiling() -> None:
    timing = fake_timing(60)
    plan = validate_shot_plan({
        "schema_version": 1,
        "preset": {"simple_seconds": [0.8, 1.4], "complex_seconds": [1.4, 2.4], "detail_seconds": [0.35, 0.6], "economic_asset_ceiling": None},
        "shots": [shot(index, [timing["words"][index]["word_id"]]) for index in range(60)],
    }, timing=timing)
    manifest = build_asset_manifest([asset(index, f"shot.{index:03d}") for index in range(60)], shot_plan=plan)
    assert len({item["asset_id"] for item in manifest["assets"][:4]}) == 4
    assert {item["shot_ids"][0] for item in manifest["assets"][:4]} == {f"shot.{i:03d}" for i in range(4)}
    assert manifest["asset_count"] == 60 and manifest["economic_asset_ceiling"] is None
    assert [len(batch) for batch in generation_batches(manifest, batch_size=12)] == [12] * 5


def test_t38_t46_timing_or_order_changes_do_not_change_asset_semantic_hash() -> None:
    plan = shot_plan()
    first = build_asset_manifest([asset(i, f"shot.{i:03d}") for i in range(4)], shot_plan=plan)
    changed_plan = copy.deepcopy(plan); changed_plan["timing_hash"] = "b" * 64
    changed_plan["shots"][0]["start"] = 9.0; changed_plan["shots"][0]["display_order"] = 3
    second = build_asset_manifest([asset(i, f"shot.{i:03d}") for i in range(4)], shot_plan=changed_plan)
    assert diff_asset_manifests(first, second) == {"reused": [f"asset.{i:03d}" for i in range(4)], "generate": [], "retired": []}
    modified = copy.deepcopy(second); modified["assets"][2]["state"] = "scientifically different state"
    # Rebuild to derive a new semantic hash rather than trusting a mutated artifact.
    specs = [asset(i, f"shot.{i:03d}") for i in range(4)]; specs[2]["state"] = "scientifically different state"
    rebuilt = build_asset_manifest(specs, shot_plan=plan)
    assert diff_asset_manifests(first, rebuilt)["generate"] == ["asset.002"]


def test_t39_reference_roles_and_full_bleed_prompt_are_explicit() -> None:
    plan = shot_plan(1); spec = asset(0, "shot.000")
    manifest = build_asset_manifest([spec], shot_plan=plan)
    prompt = asset_prompt(manifest["assets"][0], claim="weight changes while mass remains", camera="eye-level", focus="the changed movement", forbidden_changes=["host identity", "scientific state"])
    for phrase in ("full-bleed", "Never inherit a page", "lens rim", "blank subtitle footer", "Do not render captions", "style:ref.style", "identity:ref.identity"):
        assert phrase in prompt
    duplicate = copy.deepcopy(spec); duplicate["reference_roles"][1]["role"] = "style"
    with pytest.raises(ContractError, match="separate and unique"):
        build_asset_manifest([duplicate], shot_plan=plan)


def test_t20_t21_qc_off_covers_all_visuals_and_creates_no_review_correction_or_gate() -> None:
    policy = media_policy({"media_review": "off", "media_auto_corrections": 0, "human_approval_required": False, "editing_observation": "auto_once"}, visual_scope=["body_assets", "entry_assets", "reference_assets"])
    assert policy["review_calls"] == policy["content_correction_attempts"] == 0
    assert policy["human_approval_required"] is False and policy["review_status"] == "not_requested"
    assert policy["observation_uploads_per_asset"] == 1 and policy["observation_can_regenerate"] is False
    planned = build_asset_manifest([asset(0, "shot.000")], shot_plan=shot_plan(1))["assets"][0]
    accepted = accept_asset_result(planned, {"attempt_id": "attempt.001", "provider_result_id": "provider-123", "file_sha256": "c" * 64, "decoded": True, "width": 1080, "height": 1920, "candidate_count": 1, "technical_retries": 0}, review_policy=policy)
    assert accepted["status"] == "usable" and accepted["content_review"] == "not_requested"
    assert accepted["aesthetic_ranking"] is None and accepted["provenance"]["observed"] is True


def test_t22_observation_is_geometry_only_or_zero_when_off() -> None:
    observed = validate_observation({"asset_id": "asset.000", "width": 1080, "height": 1920, "targets": [{"x": .5, "y": .4}], "evidence_type": "pixel_geometry", "status": "observed"}, asset_id="asset.000")
    assert observed["content_review"] == "not_performed" and observed["can_regenerate"] is False
    off = media_policy({"media_review": "off", "media_auto_corrections": 0, "human_approval_required": False, "editing_observation": "off"}, visual_scope=["body_assets", "entry_assets", "reference_assets"])
    assert off["observation_uploads_per_asset"] == 0


def test_body_video_requires_explicit_supported_role_capability() -> None:
    plan = shot_plan(1); video = asset(0, "shot.000", media_type="body_video", generator="flow_body_video")
    with pytest.raises(ContractError, match="lacks explicit capability"):
        build_asset_manifest([video], shot_plan=plan)
    assert build_asset_manifest([video], shot_plan=plan, body_video_capabilities={"body_explanation": True})["assets"][0]["media_type"] == "body_video"


def opening_timing() -> dict:
    return fake_timing(30, seconds_per_word=.5)


@pytest.mark.parametrize("character_id,presentation_id", [
    ("red_horned_everyman", "red_door_portal"),
    ("moss_cloaked_crone", "orb_portal"),
    ("sea_captain", "spyglass_portal"),
    ("newton_scholar", "book_portal"),
])
def test_t40_t66_all_character_gateway_mappings_use_real_timing_and_unreviewed_semantics(character_id: str, presentation_id: str) -> None:
    timing = opening_timing(); words = timing["words"]
    result = build_opening_plan(
        character_id=character_id, registry_path=ROOT / "projects/q_station/characters/registry.json",
        timing=timing, question_end_word_id=words[1]["word_id"], entry_end_word_id=words[15]["word_id"],
        supported_source_seconds=[4, 6, 8], preferred_a=4, preferred_b=8, speed_tolerance=.1,
    )
    assert result["presentation_id"] == presentation_id and result["review_status"] == "not_requested"
    assert result["clips"]["A"]["reference_roles"] == ["character_sheet"]
    assert result["clips"]["B"]["reference_roles"] == ["first_frame", "last_frame"]
    assert result["clips"]["A"]["native_audio"] == result["clips"]["B"]["native_audio"] == "muted"
    assert result["lip_sync_claim"] == "not_available"


def test_red_door_frozen_minimum_cannot_be_silently_shortened() -> None:
    timing = fake_timing(20, seconds_per_word=.25); words = timing["words"]
    with pytest.raises(ContractError, match="frozen timing/word contract"):
        build_opening_plan(character_id="red_horned_everyman", registry_path=ROOT / "projects/q_station/characters/registry.json", timing=timing, question_end_word_id=words[1]["word_id"], entry_end_word_id=words[14]["word_id"], supported_source_seconds=[4, 6, 8], preferred_a=4, preferred_b=6, speed_tolerance=.1)
