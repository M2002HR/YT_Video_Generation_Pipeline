"""Hash-pinned Release/delivery compatibility for accepted Shorts V2 versions."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .artifacts import ArtifactResolver, atomic_write_json
from .contracts import ContractError, canonical_json_hash, stable_id


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def accepted_source_binding(episode_root: Path) -> dict[str, Any]:
    episode_root = episode_root.resolve()
    pointer_path = episode_root / "shorts_v2" / "ACCEPTED_VERSION.json"
    try:
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError("Shorts V2 Release requires a readable accepted-version pointer") from exc
    revision_id = stable_id(pointer.get("revision_id"), "revision_id")
    resolver = ArtifactResolver(episode_root, revision_id)
    output = pointer.get("output") if isinstance(pointer.get("output"), dict) else {}
    path = Path(str(output.get("path") or ""))
    try:
        path = path.resolve(strict=True)
        path.relative_to(resolver.revision_root.resolve())
    except (OSError, ValueError) as exc:
        raise ContractError("accepted output is missing or outside its immutable revision") from exc
    digest = sha256_file(path)
    if output.get("sha256") != digest:
        raise ContractError("accepted output bytes no longer match the accepted hash")
    if pointer.get("technical_acceptance") != "passed":
        raise ContractError("accepted version has not passed technical validation")
    return {
        "schema_version": 1, "editing_engine": "shorts_v2", "revision_id": revision_id,
        "config_hash": pointer.get("config_hash"), "manifest_hash": pointer.get("manifest_hash"),
        "master_path": str(path), "master_sha256": digest,
        "technical_acceptance": "passed",
        "human_artistic_acceptance": pointer.get("human_artistic_acceptance", "not_requested"),
        "accepted_pointer_hash": canonical_json_hash(pointer),
    }


def delivery_idempotency_key(*, episode_id: str, accepted_output_sha256: str, destination: str, delivery_type: str) -> str:
    stable_id(episode_id, "episode_id")
    if len(accepted_output_sha256) != 64 or any(char not in "0123456789abcdef" for char in accepted_output_sha256):
        raise ContractError("accepted_output_sha256 must be a lowercase SHA-256 digest")
    if not destination.strip() or not delivery_type.strip():
        raise ContractError("destination and delivery_type are required")
    return canonical_json_hash({
        "episode_id": episode_id, "accepted_output_sha256": accepted_output_sha256,
        "destination": destination.strip(), "delivery_type": delivery_type.strip(),
    })


def write_compatibility_export(episode_root: Path, binding: dict[str, Any]) -> Path:
    """Publish a small derived locator for old summary/release consumers.

    The immutable V2 version remains the only editable truth; the large media is
    never copied to a mutable `latest` path.
    """
    target = episode_root.resolve() / "pipeline" / "SHORTS_V2_COMPATIBILITY_EXPORT.json"
    atomic_write_json(target, {
        "schema_version": 1, "derived": True, "source_of_truth": "shorts_v2/ACCEPTED_VERSION.json",
        "editing_engine": "shorts_v2", "revision_id": binding["revision_id"],
        "master_path": binding["master_path"], "master_sha256": binding["master_sha256"],
        "technical_acceptance": binding["technical_acceptance"],
        "human_artistic_acceptance": binding["human_artistic_acceptance"],
    })
    return target
