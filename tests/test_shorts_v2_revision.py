from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from shorts_v2.artifacts import atomic_write_json
from shorts_v2.contracts import ContractError
from shorts_v2.revision import RevisionConflict, RevisionStore, plan_revision, reconcile_locks


CONFIG = "a" * 64
MANIFEST = "b" * 64


def request(scope: str, targets: list[str] | None = None, patch: dict | None = None) -> dict:
    return {
        "episode_id": "episode.001", "base_revision_id": "revision.001",
        "base_config_hash": CONFIG, "base_manifest_hash": MANIFEST,
        "scope": scope, "target_ids": targets or [], "patch_or_feedback": patch or {"value": "changed"},
        "lock_policy": "preserve_or_conflict", "execution_policy": "execute_affected_only",
    }


def accepted(root: Path) -> RevisionStore:
    store = RevisionStore(root)
    store.resolver("revision.001").ensure_layout()
    output = store.resolver("revision.001").resolve("final")
    output.parent.mkdir(parents=True, exist_ok=True); output.write_bytes(b"healthy video")
    atomic_write_json(store.accepted_path, {
        "schema_version": 1, "revision_id": "revision.001", "config_hash": CONFIG,
        "manifest_hash": MANIFEST, "output": {"path": str(output), "sha256": hashlib.sha256(output.read_bytes()).hexdigest()},
        "technical_acceptance": "passed", "human_artistic_acceptance": "not_requested",
    })
    return store


def test_t55_caption_only_has_zero_provider_calls_and_preserves_media() -> None:
    plan = plan_revision(request("caption_style"))
    assert {"caption_plan", "presentation_compile", "render_preview", "render_final"} <= set(plan["affected"])
    assert {"tts", "images", "flow"} <= set(plan["reused"])
    assert plan["provider_calls"] == {"elevenlabs": 0, "image": 0, "flow": 0, "chatgpt": 0}


def test_t56_gain_only_reuses_video_audio_source_and_all_providers() -> None:
    plan = plan_revision(request("narration_gain"))
    assert {"sound_plan", "audio_mix", "mux", "technical_qc"} <= set(plan["affected"])
    assert {"tts", "timing", "video_stream", "images"} <= set(plan["reused"])
    assert not any(plan["provider_calls"].values())


def test_t45_voice_model_revision_retimes_but_preserves_independent_images() -> None:
    plan = plan_revision(request("voice_model", patch={"tts_model": "eleven_multilingual_v2"}))
    assert {"voice_compile", "tts", "timing", "rhythm", "shot_schedule"} <= set(plan["affected"])
    assert "independent_images" in plan["reused"]
    assert "opening_media" in plan["conditional_reuse"]
    assert plan["provider_calls"]["elevenlabs"] == 1 and plan["provider_calls"]["image"] == 0


def test_t46_one_asset_revision_rebuilds_only_real_consumers() -> None:
    plan = plan_revision(request("asset", ["asset.007"]))
    assert "asset:asset.007" in plan["affected"]
    assert "other_images" in plan["reused"] and "narration_audio" in plan["reused"]
    assert plan["provider_calls"]["image"] == 1 and plan["provider_calls"]["elevenlabs"] == 0


def test_t54_failed_revision_preserves_last_healthy_accepted_pointer(tmp_path: Path) -> None:
    store = accepted(tmp_path / "episode")
    preview = store.preview(request("caption_style"))
    revision = store.apply(request("caption_style"), plan_hash=preview["plan_hash"])
    before = store.accepted_path.read_bytes()
    store.fail(revision["revision_id"], reason="fixture render failed")
    assert store.accepted_path.read_bytes() == before
    assert Path(json.loads(before)["output"]["path"]).is_file()


def test_t60_two_tabs_stale_base_gets_409_and_cannot_apply(tmp_path: Path) -> None:
    store = accepted(tmp_path / "episode")
    preview = store.preview(request("caption_style"))
    pointer = json.loads(store.accepted_path.read_text()); pointer["config_hash"] = "c" * 64
    atomic_write_json(store.accepted_path, pointer)
    with pytest.raises(RevisionConflict) as caught:
        store.apply(request("caption_style"), plan_hash=preview["plan_hash"])
    assert caught.value.status_code == 409 and "refresh" in str(caught.value).lower()
    assert not store.resolver(preview["proposed_revision_id"]).revision_root.exists()


def test_atomic_promotion_checks_exact_output_and_late_owner(tmp_path: Path) -> None:
    store = accepted(tmp_path / "episode")
    preview = store.preview(request("caption_style")); revision = store.apply(request("caption_style"), plan_hash=preview["plan_hash"])
    revision_id = revision["revision_id"]
    output = store.resolver(revision_id).resolve("final"); output.parent.mkdir(parents=True, exist_ok=True); output.write_bytes(b"new healthy output")
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    before = store.accepted_path.read_bytes()
    with pytest.raises(ContractError, match="older attempt"):
        store.record_attempt_result(revision_id=revision_id, attempt_id="attempt.old", owner_attempt_id="attempt.current", output_hash=digest)
    assert store.accepted_path.read_bytes() == before
    promoted = store.promote(revision_id=revision_id, output_path=output, expected_output_hash=digest,
                             config_hash=CONFIG, manifest_hash=MANIFEST,
                             technical_qc={"status": "passed", "output_sha256": digest})
    assert promoted["revision_id"] == revision_id
    assert json.loads(store.accepted_path.read_text())["output"]["sha256"] == digest


def test_t61_locks_across_split_require_lineage_or_visible_conflict() -> None:
    with pytest.raises(ContractError, match="lock conflict"):
        reconcile_locks({"shot.old": {"scale": 1.2}}, lineage={"shot.old": ["shot.a", "shot.b"]}, explicit_transfers={})
    result = reconcile_locks({"shot.old": {"scale": 1.2}}, lineage={"shot.old": ["shot.a", "shot.b"]}, explicit_transfers={"shot.old": "shot.b"})
    assert result["transferred"] == {"shot.b": {"scale": 1.2}} and result["conflicts"] == []


@pytest.mark.parametrize("scope", [
    "hook", "script_core", "cta", "voice_model", "voice_performance", "shot_plan",
    "asset", "motion", "boundary", "caption_style", "branding", "music", "sfx",
    "narration_gain", "character_style", "quality_policy", "enable_observation",
])
def test_all_supported_revision_scopes_have_explicit_nonempty_plans(scope: str) -> None:
    targets = ["asset.001"] if scope in {"asset", "motion"} else (["boundary.001"] if scope == "boundary" else [])
    plan = plan_revision(request(scope, targets))
    assert plan["affected"] or plan["conditional_reuse"]
    assert plan["plan_hash"] and plan["provider_calls_confidence"] in {"known", "estimated", "unknown"}
