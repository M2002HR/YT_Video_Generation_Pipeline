"""Dependency-aware revision planning and atomic version promotion (P10)."""
from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .artifacts import ArtifactResolver, atomic_write_json
from .contracts import ContractError, canonical_json_hash, stable_id

HASH = re.compile(r"^[a-f0-9]{64}$")
REQUEST_FIELDS = frozenset({
    "episode_id", "base_revision_id", "base_config_hash", "base_manifest_hash",
    "scope", "target_ids", "patch_or_feedback", "lock_policy", "execution_policy",
})


class RevisionConflict(ContractError):
    status_code = 409


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _validate_request(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != REQUEST_FIELDS:
        raise ContractError("revision request has missing or unknown fields")
    episode_id = stable_id(value.get("episode_id"), "episode_id")
    base_revision_id = stable_id(value.get("base_revision_id"), "base_revision_id")
    for name in ("base_config_hash", "base_manifest_hash"):
        if not HASH.fullmatch(str(value.get(name) or "")):
            raise ContractError(f"{name} must be a SHA-256 digest")
    targets = value.get("target_ids")
    if not isinstance(targets, list) or len(set(targets)) != len(targets):
        raise ContractError("target_ids must be a unique list")
    for target in targets:
        stable_id(target, "target_id")
    if not isinstance(value.get("patch_or_feedback"), Mapping):
        raise ContractError("patch_or_feedback must be a typed object")
    if value.get("lock_policy") not in {"preserve_or_conflict", "explicit_override"}:
        raise ContractError("unsupported revision lock_policy")
    if value.get("execution_policy") not in {"execute_affected_only", "preview_only"}:
        raise ContractError("unsupported revision execution_policy")
    return {**deepcopy(dict(value)), "episode_id": episode_id, "base_revision_id": base_revision_id, "target_ids": list(targets)}


_PLANS: dict[str, dict[str, Any]] = {
    "caption_style": {"affected": ["caption_plan", "layout", "presentation_compile", "render_preview", "render_final", "technical_qc", "accept_version"], "reused": ["script", "tts", "timing", "images", "flow", "video_segments"], "calls": {}},
    "branding": {"affected": ["overlay_plan", "layout", "presentation_compile", "render_preview", "render_final", "technical_qc", "accept_version"], "reused": ["script", "tts", "timing", "images", "flow", "video_segments"], "calls": {}},
    "narration_gain": {"affected": ["sound_plan", "audio_mix", "mux", "technical_qc", "accept_version"], "reused": ["tts", "timing", "video_stream", "images", "flow"], "calls": {}},
    "music": {"affected": ["music_selection", "sound_plan", "audio_mix", "mux", "technical_qc", "accept_version"], "reused": ["tts", "images", "shot_plan", "edit_cuts", "video_stream"], "conditional": ["rhythm_and_edit_if_music_driven"], "calls": {}},
    "sfx": {"affected": ["sfx_selection", "sound_plan", "audio_mix", "mux", "technical_qc", "accept_version"], "reused": ["tts", "timing", "images", "video_stream"], "calls": {}},
    "motion": {"affected": ["target_edit_geometry", "compiled_timeline", "consuming_segment", "render_preview", "render_final", "technical_qc"], "reused": ["source_image", "narration_audio", "other_segments"], "calls": {}},
    "boundary": {"affected": ["target_boundary", "adjacent_handles", "compiled_timeline", "adjacent_segments", "render_preview", "render_final", "technical_qc"], "reused": ["images", "narration_audio", "other_segments"], "calls": {}},
    "asset": {"affected": ["target_asset", "optional_observation", "consuming_edits", "adjacent_boundaries", "compiled_timeline", "render_preview", "render_final", "technical_qc"], "reused": ["other_images", "script", "narration_audio", "timing"], "calls": {"image": 1}},
    "shot_plan": {"affected": ["shot_plan", "shot_schedule", "asset_manifest_diff", "edit_direction", "compiled_timeline", "render_preview", "render_final"], "reused": ["tts", "narration_audio", "semantically_stable_images"], "conditional": ["asset_reuse_after_manifest_diff"], "calls": {"chatgpt": 1}},
    "voice_model": {"affected": ["voice_resolution", "voice_performance_feasibility", "voice_compile", "tts", "timing", "pacing", "rhythm", "shot_schedule", "edit_direction", "caption_timing", "render_preview", "render_final"], "reused": ["canonical_text", "evidence", "world_style", "independent_images"], "conditional": ["opening_media", "extra_assets_after_retime"], "calls": {"elevenlabs": 1, "chatgpt": 1}},
    "voice_performance": {"affected": ["voice_performance", "voice_compile", "tts", "timing", "pacing", "rhythm", "shot_schedule", "edit_direction", "caption_timing", "render_preview", "render_final"], "reused": ["canonical_text", "independent_images"], "conditional": ["opening_media", "acting_related_assets"], "calls": {"elevenlabs": 1, "chatgpt": 1}},
    "cta": {"affected": ["cta", "tts", "timing", "pacing", "rhythm", "tail_shot_schedule", "caption_timing", "render_preview", "render_final"], "reused": ["hook", "script_core", "world_style", "semantically_stable_images"], "conditional": ["timing_dependent_asset_schedule"], "calls": {"elevenlabs": 1, "chatgpt": 1}},
    "script_core": {"affected": ["script_core", "text_reviews", "tts", "timing", "rhythm", "shot_plan", "asset_manifest_diff", "edit_direction", "captions", "render_preview", "render_final"], "reused": ["evidence", "world_style"], "conditional": ["semantically_stable_images"], "calls": {"elevenlabs": 1, "chatgpt": 2}},
    "hook": {"affected": ["hook", "story_consistency", "script_if_changed", "tts_if_changed", "timing_if_changed", "opening_plan", "related_shots", "render_preview", "render_final"], "reused": ["evidence", "body_factual_assets"], "conditional": ["body_assets_after_story_replan"], "calls": {"chatgpt": 2}},
    "character_style": {"affected": ["character_resolution", "character_performance", "world_style", "identity_assets", "opening_media", "consuming_edits", "render_preview", "render_final"], "reused": ["evidence", "claims"], "conditional": ["identity_independent_assets"], "calls": {"image": -1, "flow": -1, "chatgpt": 1}},
    "quality_policy": {"affected": ["future_review_policy"], "reused": ["all_current_outputs"], "calls": {}},
    "enable_observation": {"affected": ["asset_observation"], "reused": ["asset_generation", "tts", "script"], "conditional": ["edit_geometry_if_observation_changes_safe_crop"], "calls": {"chatgpt": -1}},
}


def plan_revision(request: Mapping[str, Any]) -> dict[str, Any]:
    normalized = _validate_request(request)
    scope = str(normalized.get("scope") or "")
    if scope not in _PLANS:
        raise ContractError(f"unsupported revision scope: {scope}")
    targeted = scope in {"asset", "motion", "boundary"}
    if targeted and not normalized["target_ids"]:
        raise ContractError(f"revision scope {scope} requires stable target_ids")
    template = _PLANS[scope]
    affected = list(template.get("affected", []))
    if scope == "asset":
        affected = [f"asset:{target}" for target in normalized["target_ids"]] + [item for item in affected if item != "target_asset"]
    elif scope == "motion":
        affected = [f"motion:{target}" for target in normalized["target_ids"]] + [item for item in affected if item != "target_edit_geometry"]
    elif scope == "boundary":
        affected = [f"boundary:{target}" for target in normalized["target_ids"]] + [item for item in affected if item != "target_boundary"]
    calls = {"elevenlabs": 0, "image": 0, "flow": 0, "chatgpt": 0}
    calls.update(template.get("calls", {}))
    confidence = "unknown" if any(value < 0 for value in calls.values()) else ("estimated" if scope in {"hook", "script_core", "shot_plan", "character_style", "enable_observation"} else "known")
    calls = {key: (None if value < 0 else value) for key, value in calls.items()}
    result = {
        "schema_version": 1, "base_revision_id": normalized["base_revision_id"],
        "base_config_hash": normalized["base_config_hash"], "base_manifest_hash": normalized["base_manifest_hash"],
        "scope": scope, "target_ids": normalized["target_ids"], "affected": affected,
        "reused": list(template.get("reused", [])), "conditional_reuse": list(template.get("conditional", [])),
        "new": [], "removed_from_active": [], "disabled": [], "conflicts": [],
        "provider_calls": calls, "provider_calls_confidence": confidence,
        "request_hash": canonical_json_hash(normalized),
    }
    result["plan_hash"] = canonical_json_hash(result)
    result["etag"] = f'"{result["plan_hash"]}"'
    result["proposed_revision_id"] = f"rev-{result['plan_hash'][:16]}"
    return result


def reconcile_locks(
    previous_locks: Mapping[str, Mapping[str, Any]], *,
    lineage: Mapping[str, Sequence[str]], explicit_transfers: Mapping[str, str],
) -> dict[str, Any]:
    transferred: dict[str, dict[str, Any]] = {}
    conflicts = []
    for old_id, locks in previous_locks.items():
        stable_id(old_id, "locked_target_id")
        descendants = list(lineage.get(old_id, []))
        selected = explicit_transfers.get(old_id)
        if selected is not None:
            if selected not in descendants:
                raise ContractError(f"explicit lock transfer for {old_id} is outside lineage")
            transferred[selected] = deepcopy(dict(locks))
        elif len(descendants) == 1:
            transferred[descendants[0]] = deepcopy(dict(locks))
        else:
            conflicts.append({"target_id": old_id, "reason": "deleted_or_ambiguous_split", "descendants": descendants})
    if conflicts:
        raise ContractError("lock conflict: split/merge/delete requires an explicit lineage transfer")
    return {"transferred": transferred, "conflicts": conflicts}


class RevisionStore:
    def __init__(self, episode_root: Path) -> None:
        self.episode_root = episode_root.resolve()
        self.engine_root = self.episode_root / "shorts_v2"
        self.accepted_path = self.engine_root / "ACCEPTED_VERSION.json"

    def resolver(self, revision_id: str) -> ArtifactResolver:
        return ArtifactResolver(self.episode_root, revision_id)

    def _accepted(self) -> dict[str, Any]:
        if not self.accepted_path.is_file():
            raise RevisionConflict("409 no accepted base exists; refresh before revising")
        try:
            return json.loads(self.accepted_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ContractError("accepted-version pointer is unreadable") from exc

    def _assert_base(self, request: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        normalized = _validate_request(request)
        current = self._accepted()
        expected = (normalized["base_revision_id"], normalized["base_config_hash"], normalized["base_manifest_hash"])
        actual = (current.get("revision_id"), current.get("config_hash"), current.get("manifest_hash"))
        if expected != actual:
            raise RevisionConflict("409 stale revision base; refresh preview before apply")
        return normalized, current

    @property
    def preview_root(self) -> Path:
        return self.engine_root / "revision_previews"

    def preview(self, request: Mapping[str, Any]) -> dict[str, Any]:
        normalized, current = self._assert_base(request)
        plan = plan_revision(normalized)
        plan["accepted_pointer_hash"] = canonical_json_hash(current)
        # Bind apply to both the semantic plan and the exact pointer observed here.
        plan["apply_token"] = canonical_json_hash({"plan_hash": plan["plan_hash"], "accepted_pointer_hash": plan["accepted_pointer_hash"]})
        self.preview_root.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.preview_root / f"{plan['plan_hash']}.json", {"request": normalized, "plan": plan, "created_at": _now()})
        return plan

    def apply(self, request: Mapping[str, Any], *, plan_hash: str) -> dict[str, Any]:
        normalized, current = self._assert_base(request)
        if not HASH.fullmatch(plan_hash):
            raise ContractError("plan_hash must be a SHA-256 digest")
        preview_path = self.preview_root / f"{plan_hash}.json"
        if not preview_path.is_file():
            raise RevisionConflict("409 revision preview expired; refresh before apply")
        preview = json.loads(preview_path.read_text(encoding="utf-8"))
        plan = preview.get("plan") or {}
        if preview.get("request") != normalized or plan.get("plan_hash") != plan_hash:
            raise RevisionConflict("409 revision preview/request mismatch; refresh before apply")
        if plan.get("accepted_pointer_hash") != canonical_json_hash(current):
            raise RevisionConflict("409 accepted version changed after preview; refresh before apply")
        revision_id = stable_id(plan.get("proposed_revision_id"), "revision_id")
        resolver = self.resolver(revision_id)
        if resolver.revision_root.exists():
            raise RevisionConflict("409 proposed revision already exists; refresh before apply")
        resolver.ensure_layout()
        atomic_write_json(resolver.resolve("request"), normalized)
        atomic_write_json(resolver.resolve("revision_plan"), plan)
        revision = {
            "schema_version": 1, "revision_id": revision_id, "base_revision_id": normalized["base_revision_id"],
            "status": "STAGING", "plan_hash": plan_hash, "apply_token": plan["apply_token"],
            "scope": normalized["scope"], "target_ids": normalized["target_ids"], "plan": plan,
            "created_at": _now(), "immutable_request_hash": canonical_json_hash(normalized),
        }
        atomic_write_json(resolver.resolve("revision"), revision)
        return revision

    def fail(self, revision_id: str, *, reason: str) -> None:
        resolver = self.resolver(revision_id)
        path = resolver.resolve("revision")
        value = json.loads(path.read_text(encoding="utf-8"))
        value.update({"status": "FAILED_TECHNICAL", "failure_reason": str(reason), "failed_at": _now()})
        atomic_write_json(path, value)

    def record_attempt_result(self, *, revision_id: str, attempt_id: str, owner_attempt_id: str, output_hash: str) -> dict[str, Any]:
        stable_id(revision_id, "revision_id"); stable_id(attempt_id, "attempt_id"); stable_id(owner_attempt_id, "owner_attempt_id")
        if attempt_id != owner_attempt_id:
            raise ContractError("late result from an older attempt cannot change the active revision")
        if not HASH.fullmatch(output_hash):
            raise ContractError("attempt output hash is invalid")
        return {"revision_id": revision_id, "attempt_id": attempt_id, "output_sha256": output_hash, "owner_match": True}

    def promote(
        self, *, revision_id: str, output_path: Path, expected_output_hash: str,
        config_hash: str, manifest_hash: str, technical_qc: Mapping[str, Any],
    ) -> dict[str, Any]:
        resolver = self.resolver(revision_id)
        revision_path = resolver.resolve("revision")
        if not revision_path.is_file() or not output_path.resolve().is_relative_to(resolver.revision_root.resolve()):
            raise ContractError("promotion output does not belong to the staging revision")
        revision = json.loads(revision_path.read_text(encoding="utf-8"))
        if revision.get("status") != "STAGING" or not output_path.is_file():
            raise ContractError("only a healthy staging revision can be promoted")
        actual_hash = _sha256(output_path)
        if actual_hash != expected_output_hash or technical_qc.get("status") != "passed" or technical_qc.get("output_sha256") != actual_hash:
            raise ContractError("technical QC/output hash does not match the exact promotion candidate")
        if not HASH.fullmatch(config_hash) or not HASH.fullmatch(manifest_hash):
            raise ContractError("promotion config/manifest hashes are invalid")
        previous = self._accepted()
        pointer = {
            "schema_version": 1, "revision_id": revision_id, "config_hash": config_hash,
            "manifest_hash": manifest_hash, "output": {"path": str(output_path.resolve()), "sha256": actual_hash},
            "technical_acceptance": "passed", "human_artistic_acceptance": "not_requested",
            "accepted_at": _now(), "previous_revision_id": previous.get("revision_id"),
        }
        # Snapshot precedes the single atomic source-of-truth pointer update.
        atomic_write_json(resolver.resolve_relative("receipts/ACCEPTED_SNAPSHOT.json"), pointer)
        atomic_write_json(self.accepted_path, pointer)
        revision.update({"status": "ACCEPTED", "accepted_output_sha256": actual_hash, "accepted_at": pointer["accepted_at"]})
        atomic_write_json(revision_path, revision)
        return pointer

    def rollback(self, target_revision_id: str, *, delivery_requested: bool = False) -> dict[str, Any]:
        stable_id(target_revision_id, "target_revision_id")
        snapshot_path = self.resolver(target_revision_id).resolve_relative("receipts/ACCEPTED_SNAPSHOT.json")
        if not snapshot_path.is_file():
            raise ContractError("rollback target is not an immutable accepted version")
        target = json.loads(snapshot_path.read_text(encoding="utf-8"))
        output = target.get("output") or {}
        path = Path(str(output.get("path") or ""))
        if not path.is_file() or _sha256(path) != output.get("sha256"):
            raise ContractError("rollback target output is missing or changed")
        previous = self._accepted()
        target.update({"rolled_back_at": _now(), "rolled_back_from": previous.get("revision_id"), "delivery_requested": bool(delivery_requested)})
        atomic_write_json(self.accepted_path, target)
        return target
