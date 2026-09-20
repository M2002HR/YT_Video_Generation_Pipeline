from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from shorts_v2.artifacts import ArtifactResolver, atomic_write_json
from shorts_v2.contracts import ContractError
from shorts_v2.studio import artifact_path, compare_versions, list_versions, workspace


def settings() -> dict:
    return {"_shorts_v2": {
        "editing_engine": "shorts_v2",
        "voice": {"tts_model": "eleven_v3", "voice_label": "Fixture Voice"},
        "quality": {"media_review": "off", "editing_observation": "auto_once"},
    }}


def make_version(root: Path, revision_id: str, payload: str) -> ArtifactResolver:
    resolver = ArtifactResolver(root, revision_id); resolver.ensure_layout()
    atomic_write_json(resolver.resolve("revision"), {"revision_id": revision_id, "status": "ACCEPTED", "scope": "initial"})
    atomic_write_json(resolver.resolve("request"), settings()["_shorts_v2"])
    resolver.resolve("tts_input").write_text(payload, encoding="utf-8")
    resolver.resolve("final").write_bytes(payload.encode())
    digest = hashlib.sha256(payload.encode()).hexdigest()
    atomic_write_json(resolver.resolve("accepted_snapshot"), {
        "revision_id": revision_id, "config_hash": "a" * 64, "manifest_hash": "b" * 64,
        "accepted_at": "2026-09-20T00:00:00+00:00", "technical_acceptance": "passed",
        "human_artistic_acceptance": "not_requested", "output": {"path": str(resolver.resolve("final")), "sha256": digest},
    })
    return resolver


def test_t60_t62_workspace_uses_registry_and_exposes_separate_text_preview(tmp_path: Path) -> None:
    root = tmp_path / "episode.001"; resolver = make_version(root, "revision.001", "Hello world")
    atomic_write_json(root / "shorts_v2" / "ACCEPTED_VERSION.json", json.loads(resolver.resolve("accepted_snapshot").read_text()))
    payload = workspace(root, settings())
    assert set(payload["graph"]["order"]) == {node["id"] for node in payload["graph"]["nodes"]}
    positions = {node_id: index for index, node_id in enumerate(payload["graph"]["order"])}
    assert all(positions[edge["source"]] < positions[edge["target"]] for edge in payload["graph"]["edges"])
    assert payload["review_state"] == "content_review_not_requested"
    assert payload["inspector"]["canonical_script"]["logical_name"] == "script_core"
    assert payload["inspector"]["tts_input"]["logical_name"] == "tts_input"
    assert payload["inspector"]["preview"]["media"]
    assert len(payload["versions"]) == 1 and payload["versions"][0]["accepted"]


def test_t61_version_compare_is_hash_bound_and_paths_are_typed(tmp_path: Path) -> None:
    root = tmp_path / "episode.001"
    make_version(root, "revision.001", "one"); make_version(root, "revision.002", "two")
    comparison = compare_versions(root, "revision.001", "revision.002")
    assert {row["logical_name"] for row in comparison["changed"]} >= {"tts_input", "final"}
    assert artifact_path(root, "revision.001", "tts_input").read_text() == "one"
    with pytest.raises(ContractError, match="unknown logical"):
        artifact_path(root, "revision.001", "../../secret")


def test_t63_version_listing_ignores_unsafe_or_unowned_directories(tmp_path: Path) -> None:
    root = tmp_path / "episode.001"; make_version(root, "revision.001", "one")
    (root / "shorts_v2" / "versions" / "INVALID NAME").mkdir()
    rows = list_versions(root)
    assert [row["revision_id"] for row in rows] == ["revision.001"]
