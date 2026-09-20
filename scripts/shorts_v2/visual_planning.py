"""Audio-timed shot, independent asset, opening, and QC-off contracts (P07)."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from .contracts import ContractError, canonical_json_hash, stable_id

SHOT_FIELDS = frozenset({
    "shot_id", "display_order", "unit_ids", "word_span_ids", "role", "new_information",
    "focus", "scene_group", "asset_requirements", "reading_complexity", "timing_constraints",
    "cut_reason", "manual_locks",
})
ASSET_FIELDS = frozenset({
    "asset_id", "role", "media_type", "subject", "action", "state", "composition", "medium",
    "identity_reference", "scene_group", "reference_roles", "generator", "shot_ids",
    "reuse_reason", "manual_locks",
})
REFERENCE_ROLES = frozenset({"style", "identity", "composition", "temporal_state"})
IMAGE_GENERATORS = frozenset({"chatgpt_image"})
BODY_VIDEO_GENERATORS = frozenset({"flow_body_video"})


def _text(value: Any, name: str) -> str:
    result = " ".join(str(value or "").split())
    if not result:
        raise ContractError(f"{name} must be non-empty")
    return result


def validate_shot_plan(value: Mapping[str, Any], *, timing: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {"schema_version", "preset", "shots"}:
        raise ContractError("shot plan has missing or unknown fields")
    if value.get("schema_version") != 1:
        raise ContractError("unsupported shot plan schema")
    words = {item["word_id"]: item for item in timing.get("words", [])}
    if not words:
        raise ContractError("shot planning requires real narration timing")
    preset = value.get("preset")
    if not isinstance(preset, Mapping) or set(preset) != {"simple_seconds", "complex_seconds", "detail_seconds", "economic_asset_ceiling"}:
        raise ContractError("shot rhythm preset is incomplete")
    if preset.get("economic_asset_ceiling") is not None:
        raise ContractError("an economic image ceiling is forbidden")
    shots, seen, orders = [], set(), set()
    prior_start = -1.0
    for raw in value.get("shots") or []:
        if not isinstance(raw, Mapping) or set(raw) != SHOT_FIELDS:
            raise ContractError("shot has missing or unknown fields")
        shot_id = stable_id(raw.get("shot_id"), "shot_id")
        if shot_id in seen:
            raise ContractError(f"duplicate shot_id {shot_id}")
        seen.add(shot_id)
        order = raw.get("display_order")
        if isinstance(order, bool) or not isinstance(order, int) or order < 0 or order in orders:
            raise ContractError("shot display_order must be a unique non-negative integer")
        orders.add(order)
        unit_ids, span = raw.get("unit_ids"), raw.get("word_span_ids")
        if not isinstance(unit_ids, list) or not unit_ids or not isinstance(span, list) or not span or any(word_id not in words for word_id in span):
            raise ContractError(f"shot {shot_id} has incomplete units or unknown word span")
        if not set(unit_ids) <= {words[word_id]["unit_id"] for word_id in span}:
            raise ContractError(f"shot {shot_id} unit projection disagrees with word span")
        start, end = min(words[word_id]["start"] for word_id in span), max(words[word_id]["end"] for word_id in span)
        if start < prior_start:
            raise ContractError("shot schedule must follow display order and real audio")
        prior_start = start
        requirements = raw.get("asset_requirements")
        if not isinstance(requirements, list) or not requirements or not all(str(item).strip() for item in requirements):
            raise ContractError(f"shot {shot_id} requires explicit asset requirements")
        if raw.get("reading_complexity") not in {"simple", "complex", "detail"}:
            raise ContractError(f"shot {shot_id} has invalid reading complexity")
        for field in ("role", "new_information", "focus", "scene_group", "cut_reason"):
            _text(raw.get(field), f"shot.{shot_id}.{field}")
        if not isinstance(raw.get("timing_constraints"), Mapping) or not isinstance(raw.get("manual_locks"), Mapping):
            raise ContractError(f"shot {shot_id} timing/locks must be objects")
        shots.append({**dict(raw), "start": start, "end": end, "duration": end - start})
    if not shots:
        raise ContractError("shot plan cannot be empty")
    shots.sort(key=lambda item: item["display_order"])
    return {
        "schema_version": 1, "timing_hash": timing.get("timing_hash"), "preset": dict(preset),
        "shots": shots, "shot_schedule_hash": canonical_json_hash({"timing": timing.get("timing_hash"), "shots": shots}),
    }


def _validate_references(value: Any, asset_id: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ContractError(f"asset {asset_id} reference_roles must be a list")
    output, roles = [], set()
    for raw in value:
        if not isinstance(raw, Mapping) or set(raw) != {"role", "sha256", "source_id"}:
            raise ContractError(f"asset {asset_id} reference has missing/unknown fields")
        role = str(raw.get("role") or "")
        if role not in REFERENCE_ROLES or role in roles:
            raise ContractError(f"asset {asset_id} reference roles must be separate and unique")
        roles.add(role)
        if not re.fullmatch(r"[a-f0-9]{64}", str(raw.get("sha256") or "")):
            raise ContractError(f"asset {asset_id} reference requires a real SHA-256")
        stable_id(raw.get("source_id"), "source_id")
        output.append(dict(raw))
    return output


def build_asset_manifest(
    assets: Sequence[Mapping[str, Any]], *, shot_plan: Mapping[str, Any],
    body_video_capabilities: Mapping[str, bool] | None = None,
) -> dict[str, Any]:
    shot_ids = {item["shot_id"] for item in shot_plan.get("shots", [])}
    capabilities = dict(body_video_capabilities or {})
    output, seen = [], set()
    for raw in assets:
        if not isinstance(raw, Mapping) or set(raw) != ASSET_FIELDS:
            raise ContractError("asset spec has missing or unknown fields")
        asset_id = stable_id(raw.get("asset_id"), "asset_id")
        if asset_id in seen:
            raise ContractError(f"duplicate asset_id {asset_id}")
        seen.add(asset_id)
        media_type, generator = raw.get("media_type"), raw.get("generator")
        if media_type == "image" and generator not in IMAGE_GENERATORS:
            raise ContractError(f"asset {asset_id} has unsupported image generator")
        if media_type == "body_video":
            if generator not in BODY_VIDEO_GENERATORS or not capabilities.get(str(raw.get("role") or asset_id), False):
                raise ContractError(f"asset {asset_id} body video role lacks explicit capability")
        elif media_type != "image":
            raise ContractError(f"asset {asset_id} has invalid media_type")
        linked = raw.get("shot_ids")
        if not isinstance(linked, list) or not linked or any(shot_id not in shot_ids for shot_id in linked):
            raise ContractError(f"asset {asset_id} has unknown/empty shot ownership")
        refs = _validate_references(raw.get("reference_roles"), asset_id)
        for field in ("subject", "action", "state", "composition", "medium", "identity_reference", "scene_group"):
            _text(raw.get(field), f"asset.{asset_id}.{field}")
        if not isinstance(raw.get("manual_locks"), Mapping):
            raise ContractError(f"asset {asset_id} manual_locks must be an object")
        semantic = {key: raw[key] for key in ("role", "media_type", "subject", "action", "state", "composition", "medium", "identity_reference", "scene_group", "generator", "manual_locks")}
        semantic["reference_roles"] = refs
        output.append({**dict(raw), "reference_roles": refs, "asset_spec_hash": canonical_json_hash(semantic)})
    if not output:
        raise ContractError("asset manifest cannot be empty")
    return {
        "schema_version": 1, "assets": output,
        "asset_count": len(output), "economic_asset_ceiling": None,
        "manifest_hash": canonical_json_hash([{"asset_id": item["asset_id"], "asset_spec_hash": item["asset_spec_hash"]} for item in output]),
    }


def asset_prompt(asset: Mapping[str, Any], *, claim: str, camera: str, focus: str, forbidden_changes: Sequence[str]) -> str:
    """Build a scoped first-attempt prompt; overlay text remains compositor-owned."""
    references = ", ".join(f"{item['role']}:{item['source_id']}@{item['sha256']}" for item in asset.get("reference_roles", [])) or "none"
    forbidden = "; ".join(str(item) for item in forbidden_changes)
    return (
        "Create one technically decodable 9:16 full-bleed topic-world image. The scene must continue to every edge. "
        "Never inherit a page, book spread, lens rim, portal border, UI panel, or blank subtitle footer from a reference. "
        "Do not render captions, numbers, labels, or other overlay text; the compositor owns them.\n"
        f"CLAIM: {claim}\nSUBJECT: {asset['subject']}\nACTION_STATE: {asset['action']} / {asset['state']}\n"
        f"COMPOSITION: {asset['composition']}\nMEDIUM: {asset['medium']}\nCAMERA: {camera}\nFOCUS: {focus}\n"
        f"REFERENCES_BY_ROLE: {references}\nFORBIDDEN_CHANGES: {forbidden}"
    )


def generation_batches(manifest: Mapping[str, Any], *, batch_size: int = 12) -> list[list[dict[str, Any]]]:
    if not 1 <= batch_size <= 24:
        raise ContractError("asset batch_size must be in 1..24 for bounded provider context")
    assets = list(manifest.get("assets", []))
    return [assets[index:index + batch_size] for index in range(0, len(assets), batch_size)]


def accept_asset_result(
    asset: Mapping[str, Any], result: Mapping[str, Any], *, review_policy: Mapping[str, Any],
) -> dict[str, Any]:
    """Accept one technically valid owned result; QC-off never ranks aesthetics."""
    required = {"attempt_id", "provider_result_id", "file_sha256", "decoded", "width", "height", "candidate_count", "technical_retries"}
    if not isinstance(result, Mapping) or set(result) != required:
        raise ContractError("asset result receipt has missing or unknown fields")
    stable_id(result.get("attempt_id"), "attempt_id")
    if not str(result.get("provider_result_id") or "").strip() or not re.fullmatch(r"[a-f0-9]{64}", str(result.get("file_sha256") or "")):
        raise ContractError("asset result lacks provider identity or content hash")
    if result.get("decoded") is not True or any(isinstance(result.get(key), bool) or not isinstance(result.get(key), int) or result[key] <= 0 for key in ("width", "height")):
        raise ContractError("asset result failed technical decode/dimension validation")
    if review_policy.get("media_review") == "off" and result.get("candidate_count") != 1:
        raise ContractError("QC off permits exactly one candidate per normal asset request")
    retries = result.get("technical_retries")
    if isinstance(retries, bool) or not isinstance(retries, int) or not 0 <= retries <= 2:
        raise ContractError("technical retries must be bounded and explicit")
    return {
        "asset_id": asset["asset_id"], "asset_spec_hash": asset["asset_spec_hash"],
        "attempt_id": result["attempt_id"], "provider_result_id": result["provider_result_id"],
        "file_sha256": result["file_sha256"], "dimensions": [result["width"], result["height"]],
        "status": "usable", "technical_validation": "passed",
        "content_review": "not_requested" if review_policy.get("media_review") == "off" else "requested",
        "aesthetic_ranking": None, "technical_retries": retries,
        "provenance": {"observed": True, "kind": "provider_result_receipt"},
    }


def media_policy(quality: Mapping[str, Any], *, visual_scope: Sequence[str]) -> dict[str, Any]:
    scopes = sorted(set(str(item) for item in visual_scope))
    if not {"body_assets", "entry_assets", "reference_assets"} <= set(scopes):
        raise ContractError("visual review policy must explicitly cover body, entry, and reference assets")
    review = str(quality.get("media_review") or "off")
    observation = str(quality.get("editing_observation") or "auto_once")
    if review not in {"off", "report", "strict"} or observation not in {"auto_once", "off"}:
        raise ContractError("invalid media review/observation policy")
    if review == "off" and (quality.get("media_auto_corrections", 0) != 0 or quality.get("human_approval_required", False)):
        raise ContractError("QC off forbids correction loops and human gates")
    return {
        "schema_version": 1, "scope": scopes, "media_review": review,
        "review_calls": 0 if review == "off" else 1,
        "content_correction_attempts": 0 if review == "off" else int(quality.get("media_auto_corrections", 0)),
        "human_approval_required": False if review == "off" else bool(quality.get("human_approval_required", False)),
        "review_status": "not_requested" if review == "off" else "requested",
        "editing_observation": observation, "observation_uploads_per_asset": 1 if observation == "auto_once" else 0,
        "observation_can_regenerate": False,
    }


def validate_observation(value: Mapping[str, Any], *, asset_id: str) -> dict[str, Any]:
    allowed = {"asset_id", "width", "height", "targets", "evidence_type", "status"}
    if not isinstance(value, Mapping) or set(value) != allowed or value.get("asset_id") != asset_id:
        raise ContractError("asset observation has missing, unknown, or mismatched fields")
    if any(key in value for key in ("verdict", "score", "regenerate", "approval")):
        raise ContractError("observation cannot contain aesthetic verdict or regeneration")
    if value.get("status") not in {"observed", "safe_geometry_fallback"} or value.get("evidence_type") not in {"pixel_geometry", "metadata_only", "fallback"}:
        raise ContractError("asset observation status/evidence is invalid")
    if not isinstance(value.get("targets"), list):
        raise ContractError("asset observation targets must be a list")
    return {**dict(value), "content_review": "not_performed", "can_regenerate": False}


def diff_asset_manifests(previous: Mapping[str, Any], current: Mapping[str, Any]) -> dict[str, list[str]]:
    old = {item["asset_id"]: item["asset_spec_hash"] for item in previous.get("assets", [])}
    new = {item["asset_id"]: item["asset_spec_hash"] for item in current.get("assets", [])}
    return {
        "reused": sorted(asset_id for asset_id in new if old.get(asset_id) == new[asset_id]),
        "generate": sorted(asset_id for asset_id in new if old.get(asset_id) != new[asset_id]),
        "retired": sorted(set(old) - set(new)),
    }


def build_opening_plan(
    *, character_id: str, registry_path: Path, timing: Mapping[str, Any],
    question_end_word_id: str, entry_end_word_id: str, supported_source_seconds: Sequence[int],
    preferred_a: int, preferred_b: int, speed_tolerance: float,
) -> dict[str, Any]:
    """Resolve character→gateway from the registry and plan sources from real timing."""
    from character_runtime import load_character_registry
    from flow_reference_policy import clip_a_roles, clip_b_roles
    from plan_opening_sources import choose_source_seconds

    character = load_character_registry(registry_path).get(character_id)
    profile = character.presentation
    words = {item["word_id"]: item for item in timing.get("words", [])}
    if question_end_word_id not in words or entry_end_word_id not in words:
        raise ContractError("opening boundaries must reference measured narration words")
    question_end = float(words[question_end_word_id]["end"])
    transition_end = float(words[entry_end_word_id]["end"])
    entry_seconds = transition_end - question_end
    ordered = list(words)
    question_index, entry_index = ordered.index(question_end_word_id), ordered.index(entry_end_word_id)
    entry_words = entry_index - question_index
    if transition_end <= question_end or entry_seconds + 1e-9 < profile.min_entry_seconds or entry_words < profile.min_entry_words:
        raise ContractError(f"gateway {profile.id} narration violates its frozen timing/word contract")
    candidates = tuple(int(item) for item in supported_source_seconds)
    if not candidates or preferred_a not in candidates or preferred_b not in candidates:
        raise ContractError("opening source capabilities/preferences are incomplete")
    clips = {
        "A": {**choose_source_seconds(question_end, preferred_a, candidates, speed_tolerance), "reference_roles": clip_a_roles(has_character_sheet=True), "native_audio": "muted"},
        "B": {**choose_source_seconds(entry_seconds, preferred_b, candidates, speed_tolerance), "reference_roles": clip_b_roles(), "native_audio": "muted"},
    }
    return {
        "schema_version": 1, "character_id": character.id, "presentation_id": profile.id,
        "profile_version": profile.version, "entry_kind": profile.entry_kind,
        "entry_frame_character_presence": profile.entry_frame_character_presence,
        "motion_contract": profile.motion_contract or None,
        "min_entry_seconds": profile.min_entry_seconds, "min_entry_words": profile.min_entry_words,
        "question_end_word_id": question_end_word_id, "entry_end_word_id": entry_end_word_id,
        "measured_question_seconds": question_end, "measured_entry_seconds": entry_seconds,
        "clips": clips, "flow_voice_policy": "elevenlabs_authoritative_native_flow_audio_muted",
        "lip_sync_claim": "not_available", "prompt_contract": profile.prompt_context(),
        "handoff_requirement": "first body shot must add strong new information and match opening energy",
        "review_status": "not_requested",
    }
