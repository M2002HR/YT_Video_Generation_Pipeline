"""Read-only Studio projections over the executable Shorts V2 contracts.

The registry, artifact resolver, and accepted pointer remain authoritative.  This
module only turns them into bounded API payloads; it never invents a second DAG.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .artifacts import ArtifactResolver, LOGICAL_ARTIFACTS
from .contracts import ContractError, canonical_json_hash, normalize_engine_settings, stable_id
from .registry import STAGES, effective_graph


JSON_PREVIEW_LIMIT = 512 * 1024
TEXT_PREVIEW_LIMIT = 128 * 1024


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def accepted_pointer(episode_root: Path) -> dict[str, Any] | None:
    value = _load(episode_root.resolve() / "shorts_v2" / "ACCEPTED_VERSION.json")
    return value if isinstance(value, dict) else None


def list_versions(episode_root: Path) -> list[dict[str, Any]]:
    root = episode_root.resolve() / "shorts_v2" / "versions"
    accepted = accepted_pointer(episode_root) or {}
    rows: list[dict[str, Any]] = []
    if not root.is_dir():
        return rows
    for directory in root.iterdir():
        if not directory.is_dir() or directory.is_symlink():
            continue
        try:
            revision_id = stable_id(directory.name, "revision_id")
        except ContractError:
            continue
        revision = _load(directory / "REVISION.json")
        snapshot = _load(directory / "receipts" / "ACCEPTED_SNAPSHOT.json")
        request = _load(directory / "REQUEST.json")
        revision = revision if isinstance(revision, dict) else {}
        snapshot = snapshot if isinstance(snapshot, dict) else {}
        request = request if isinstance(request, dict) else {}
        rows.append({
            "revision_id": revision_id,
            "base_revision_id": revision.get("base_revision_id"),
            "status": revision.get("status") or ("ACCEPTED" if snapshot else "PLANNED"),
            "scope": revision.get("scope") or "initial",
            "created_at": revision.get("created_at"),
            "accepted_at": snapshot.get("accepted_at"),
            "accepted": revision_id == accepted.get("revision_id"),
            "config_hash": snapshot.get("config_hash") or canonical_json_hash(request),
            "manifest_hash": snapshot.get("manifest_hash"),
            "technical_acceptance": snapshot.get("technical_acceptance"),
            "human_artistic_acceptance": snapshot.get("human_artistic_acceptance", "not_requested"),
        })
    return sorted(rows, key=lambda row: (str(row.get("created_at") or row.get("accepted_at") or ""), row["revision_id"]), reverse=True)


def _artifact_projection(resolver: ArtifactResolver, logical_name: str) -> dict[str, Any]:
    path = resolver.resolve(logical_name)
    relative = LOGICAL_ARTIFACTS[logical_name]
    exists = path.is_file() and not path.is_symlink()
    return {
        "logical_name": logical_name, "path": relative, "exists": exists,
        "bytes": path.stat().st_size if exists else 0,
        "sha256": _sha256(path) if exists else None,
        "media": path.suffix.lower() in {".mp4", ".webm", ".mov", ".mp3", ".wav", ".m4a", ".ogg"},
    }


def artifact_path(episode_root: Path, revision_id: str, logical_name: str) -> Path:
    stable_id(revision_id, "revision_id")
    if logical_name not in LOGICAL_ARTIFACTS:
        raise ContractError("unknown logical artifact")
    path = ArtifactResolver(episode_root.resolve(), revision_id).resolve(logical_name)
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(logical_name)
    return path


def artifact_preview(episode_root: Path, revision_id: str, logical_name: str) -> dict[str, Any]:
    path = artifact_path(episode_root, revision_id, logical_name)
    suffix = path.suffix.lower()
    if suffix == ".json":
        if path.stat().st_size > JSON_PREVIEW_LIMIT:
            raise ContractError("JSON artifact is too large for inline preview")
        return {"kind": "json", "value": _load(path), "sha256": _sha256(path)}
    if suffix in {".txt", ".md", ".ass"}:
        if path.stat().st_size > TEXT_PREVIEW_LIMIT:
            raise ContractError("text artifact is too large for inline preview")
        return {"kind": "text", "value": path.read_text(encoding="utf-8", errors="replace"), "sha256": _sha256(path)}
    return {"kind": "media", "sha256": _sha256(path), "bytes": path.stat().st_size}


def workspace(episode_root: Path, raw_settings: Mapping[str, Any], *, revision_id: str | None = None) -> dict[str, Any]:
    episode_root = episode_root.resolve()
    settings = normalize_engine_settings(raw_settings)
    if settings["editing_engine"] != "shorts_v2":
        raise ContractError("Shorts V2 workspace requires an explicit shorts_v2 run")
    accepted = accepted_pointer(episode_root)
    selected = revision_id or str((accepted or {}).get("revision_id") or "initial")
    selected = stable_id(selected, "revision_id")
    resolver = ArtifactResolver(episode_root, selected)
    graph = effective_graph(settings, include_disabled=True)
    runtime = _load(resolver.resolve_relative("diagnostics/RUNTIME_STATE.json"))
    stage_state = runtime.get("stages") if isinstance(runtime, dict) and isinstance(runtime.get("stages"), dict) else {}
    stage_by_id = {stage.id: stage for stage in STAGES}
    for node in graph["nodes"]:
        state = stage_state.get(node["id"])
        if isinstance(state, dict):
            node["status"] = str(state.get("status") or node["status"])
            node["meta"] = state
        artifacts = []
        for logical_name in stage_by_id[node["id"]].owned_artifacts:
            if logical_name in LOGICAL_ARTIFACTS:
                artifacts.append(_artifact_projection(resolver, logical_name))
        node["artifacts"] = artifacts
        node["regeneratable"] = node["revision_policy"] != "managed"
    shot_plan = _load(resolver.resolve("shot_plan"))
    timing = _load(resolver.resolve("narration_timing"))
    captions = _load(resolver.resolve("caption_plan"))
    sound = _load(resolver.resolve("sound_plan"))
    versions = list_versions(episode_root)
    return {
        "schema_version": 1, "editing_engine": "shorts_v2", "revision_id": selected,
        "accepted": accepted, "versions": versions, "graph": graph,
        "review_state": "content_review_not_requested" if settings["quality"]["media_review"] == "off" else "content_review_requested",
        "tracks": {
            "narration": timing if isinstance(timing, dict) else None,
            "shots": shot_plan if isinstance(shot_plan, dict) else None,
            "captions": captions if isinstance(captions, dict) else None,
            "sound": sound if isinstance(sound, dict) else None,
        },
        "inspector": {
            "canonical_script": _artifact_projection(resolver, "script_core"),
            "tts_input": _artifact_projection(resolver, "tts_input"),
            "preview": _artifact_projection(resolver, "preview"),
            "final": _artifact_projection(resolver, "final"),
        },
    }


def compare_versions(episode_root: Path, left_revision_id: str, right_revision_id: str) -> dict[str, Any]:
    left = ArtifactResolver(episode_root.resolve(), stable_id(left_revision_id, "left_revision_id"))
    right = ArtifactResolver(episode_root.resolve(), stable_id(right_revision_id, "right_revision_id"))
    changed, unchanged, missing = [], [], []
    for logical_name in sorted(LOGICAL_ARTIFACTS):
        a, b = _artifact_projection(left, logical_name), _artifact_projection(right, logical_name)
        if not a["exists"] or not b["exists"]:
            if a["exists"] != b["exists"]:
                missing.append({"logical_name": logical_name, "left_exists": a["exists"], "right_exists": b["exists"]})
        elif a["sha256"] == b["sha256"]:
            unchanged.append(logical_name)
        else:
            changed.append({"logical_name": logical_name, "left_sha256": a["sha256"], "right_sha256": b["sha256"]})
    return {"schema_version": 1, "left_revision_id": left.revision_id, "right_revision_id": right.revision_id,
            "changed": changed, "unchanged": unchanged, "missing": missing}
