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
from shorts_v2.delivery import accepted_source_binding, delivery_idempotency_key


def accepted(root: Path) -> tuple[ArtifactResolver, Path]:
    resolver = ArtifactResolver(root, "revision.001"); resolver.ensure_layout()
    master = resolver.resolve("final"); master.write_bytes(b"accepted master")
    pointer = {
        "schema_version": 1, "revision_id": "revision.001", "config_hash": "a" * 64,
        "manifest_hash": "b" * 64, "output": {"path": str(master), "sha256": hashlib.sha256(master.read_bytes()).hexdigest()},
        "technical_acceptance": "passed", "human_artistic_acceptance": "not_requested",
    }
    atomic_write_json(root / "shorts_v2" / "ACCEPTED_VERSION.json", pointer)
    return resolver, master


def test_t59_release_binding_is_exact_accepted_version_and_hash(tmp_path: Path) -> None:
    root = tmp_path / "episode"; _resolver, master = accepted(root)
    binding = accepted_source_binding(root)
    assert binding["revision_id"] == "revision.001"
    assert binding["master_sha256"] == hashlib.sha256(master.read_bytes()).hexdigest()
    master.write_bytes(b"changed")
    with pytest.raises(ContractError, match="no longer match"):
        accepted_source_binding(root)


def test_t67_delivery_idempotency_separates_destination_type_and_content() -> None:
    first = delivery_idempotency_key(episode_id="episode.42", accepted_output_sha256="a" * 64, destination="telegram:channel", delivery_type="master")
    assert first == delivery_idempotency_key(episode_id="episode.42", accepted_output_sha256="a" * 64, destination="telegram:channel", delivery_type="master")
    assert first != delivery_idempotency_key(episode_id="episode.42", accepted_output_sha256="b" * 64, destination="telegram:channel", delivery_type="master")
    assert first != delivery_idempotency_key(episode_id="episode.42", accepted_output_sha256="a" * 64, destination="telegram:other", delivery_type="master")
