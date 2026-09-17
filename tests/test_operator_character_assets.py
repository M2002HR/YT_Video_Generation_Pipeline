from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from captain_test_support import setup_registry, write_sheet
from character_assets import operator_reference_error, registry_asset_revision
from character_runtime import (
    CharacterRegistryError, CharacterSelectionError, load_character_registry,
    parse_selector_output, resolve_character,
)


def test_missing_operator_sheet_does_not_break_bundled_catalog(tmp_path):
    registry_path, sheet = setup_registry(tmp_path)
    before = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*") if p.is_file())
    registry = load_character_registry(registry_path)
    assert registry.enabled_ids() == ("fixture_host",)
    assert [row["id"] for row in registry.catalog()] == ["fixture_host"]
    assert registry.get("fixture_host").id == "fixture_host"
    with pytest.raises(CharacterSelectionError, match="Install.*character_sheet.png"):
        registry.get("sea_captain")
    assert not sheet.exists()
    assert sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*") if p.is_file()) == before


@pytest.mark.parametrize("mode", ["manual", "resume"])
def test_unready_manual_and_resume_never_switch_host(tmp_path, mode):
    path, _ = setup_registry(tmp_path)
    registry = load_character_registry(path)
    kwargs = {"requested_mode": "manual", "requested_character_id": "sea_captain"}
    if mode == "resume":
        kwargs = {"persisted": {"resolved_character_id": "sea_captain", "requested_mode": "auto"}}
    with pytest.raises(CharacterSelectionError, match="not ready"):
        resolve_character(registry, **kwargs, run_auto_selector=lambda: pytest.fail("selector must not run"))


def test_auto_rejects_unready_candidate_and_keeps_existing_fallback(tmp_path):
    path, _ = setup_registry(tmp_path)
    registry = load_character_registry(path)
    result = {"character_id": "sea_captain", "confidence": "high", "reason": "Topic fit."}
    assert parse_selector_output(result, registry) is None
    assert resolve_character(registry, run_auto_selector=lambda: result).resolved_character_id == "fixture_host"
    assert resolve_character(registry, is_legacy_run=True).resolved_character_id == "fixture_host"


def test_upload_with_old_mtime_activates_and_removal_deactivates(tmp_path):
    path, sheet = setup_registry(tmp_path)
    first = load_character_registry(path)
    assert not first.has("sea_captain")
    write_sheet(sheet)
    os.utime(sheet, (1, 1))  # Simulate scp/rsync preserving an older timestamp.
    ready = load_character_registry(path)
    assert ready is not first
    captain = ready.get("sea_captain")
    assert captain.sheet_sha256 == hashlib.sha256(sheet.read_bytes()).hexdigest()
    assert captain.presentation.id == "spyglass_portal"
    assert load_character_registry(path) is ready
    assert ready.catalog()[-1]["presentation_name"] == captain.presentation.display_name
    sheet.unlink()
    missing = load_character_registry(path)
    assert not missing.has("sea_captain")
    assert missing.enabled_ids() == ("fixture_host",)


def test_atomic_same_mtime_replacement_is_revalidated(tmp_path):
    path, sheet = setup_registry(tmp_path, installed=True)
    ready = load_character_registry(path)
    old_stat = sheet.stat()
    replacement = sheet.with_suffix(".upload")
    replacement.write_bytes(b"x" * old_stat.st_size)
    os.utime(replacement, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
    replacement.replace(sheet)
    broken = load_character_registry(path)
    assert broken is not ready
    assert not broken.has("sea_captain")
    assert broken.has("fixture_host")
    with pytest.raises(CharacterSelectionError, match="corrupt"):
        broken.get("sea_captain")


def test_ready_manual_resolution_is_reused_without_auto(tmp_path):
    path, _ = setup_registry(tmp_path, installed=True)
    registry = load_character_registry(path)
    first = resolve_character(registry, requested_mode="manual", requested_character_id="sea_captain")
    resumed = resolve_character(registry, persisted=first.to_state(),
                                run_auto_selector=lambda: pytest.fail("resume must not reroll"))
    assert resumed.to_state() == first.to_state()


def test_ready_captain_can_be_selected_by_auto(tmp_path):
    path, _ = setup_registry(tmp_path, installed=True)
    registry = load_character_registry(path)
    result = resolve_character(registry, run_auto_selector=lambda: {
        "character_id": "sea_captain", "confidence": "high", "reason": "A visible comparison suits this host.",
    })
    assert result.resolved_character_id == "sea_captain"
    assert result.source == "auto"


def test_bundled_missing_reference_still_fails_strictly(tmp_path):
    path, _ = setup_registry(tmp_path)
    (path.parent / "fixture_host/sheet.png").unlink()
    with pytest.raises(CharacterRegistryError, match="missing required reference"):
        load_character_registry(path)


def test_missing_operator_image_does_not_hide_broken_prompt_config(tmp_path):
    path, sheet = setup_registry(tmp_path)
    (sheet.parents[1] / "behavior.md").unlink()
    with pytest.raises(CharacterRegistryError, match="prompt file missing"):
        load_character_registry(path)


@pytest.mark.parametrize("field,value", [("provisioning", "typo"), ("required", False)])
def test_invalid_provisioning_contract_fails(tmp_path, field, value):
    path, sheet = setup_registry(tmp_path)
    config_path = sheet.parents[1] / "character.json"
    config = json.loads(config_path.read_text())
    config["references"][field] = value
    config_path.write_text(json.dumps(config))
    with pytest.raises(CharacterRegistryError):
        load_character_registry(path)


@pytest.mark.parametrize("key", ["auto_fallback_character_id", "legacy_default_character_id"])
def test_unready_pack_cannot_be_a_default(tmp_path, key):
    path, _ = setup_registry(tmp_path)
    data = json.loads(path.read_text()); data[key] = "sea_captain"
    path.write_text(json.dumps(data))
    with pytest.raises(CharacterRegistryError, match=key):
        load_character_registry(path)


def test_disabled_operator_pack_stays_disabled_after_upload(tmp_path):
    path, sheet = setup_registry(tmp_path, installed=True)
    config_path = sheet.parents[1] / "character.json"
    data = json.loads(config_path.read_text()); data["enabled"] = False
    config_path.write_text(json.dumps(data))
    assert not load_character_registry(path).has("sea_captain")


@pytest.mark.parametrize("kind,expected", [
    ("missing", "Install"), ("empty", "too small"), ("corrupt", "corrupt"),
    ("renamed_jpeg", "real PNG"), ("tiny_dimensions", "256 pixels"),
    ("animated", "single still"),
])
def test_operator_artwork_validation(tmp_path, kind, expected):
    sheet = tmp_path / "character_sheet.png"
    if kind == "empty": sheet.touch()
    elif kind == "corrupt": sheet.write_bytes(b"x" * 12_000)
    elif kind == "renamed_jpeg": write_sheet(sheet, fmt="JPEG")
    elif kind == "tiny_dimensions": write_sheet(sheet, size=(128, 512))
    elif kind == "animated":
        frames = [Image.effect_noise((512, 512), 90) for _ in range(2)]
        frames[0].save(sheet, save_all=True, append_images=frames[1:], format="PNG", duration=100)
    assert expected in operator_reference_error(sheet)


def test_valid_sheet_check_is_read_only(tmp_path):
    path = write_sheet(tmp_path / "character_sheet.png")
    before = path.read_bytes(), path.stat().st_mtime_ns
    assert operator_reference_error(path) is None
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


def test_registry_revision_tracks_path_set(tmp_path):
    registry = tmp_path / "registry.json"; registry.write_text("{}")
    first = registry_asset_revision(registry)
    sheet = write_sheet(tmp_path / "character_sheet.png")
    os.utime(sheet, (1, 1))
    second = registry_asset_revision(registry)
    assert first != second
    sheet.unlink()
    assert registry_asset_revision(registry) == first
