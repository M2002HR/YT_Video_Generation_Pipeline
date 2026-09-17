"""Temporary, provider-free fixtures; never install artwork in the source checkout."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def write_sheet(path: Path, size: tuple[int, int] = (512, 512), fmt: str = "PNG") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Test pixels only. No placeholder artwork is committed or sent to providers.
    Image.effect_noise(size, 90).convert("RGB").save(path, format=fmt)
    return path


def setup_registry(tmp_path: Path, *, installed: bool = False) -> tuple[Path, Path]:
    root = tmp_path / "content"
    source = ROOT / "projects/q_station"
    shutil.copytree(source / "characters/sea_captain", root / "characters/sea_captain",
                    ignore=shutil.ignore_patterns("character_sheet*.png"))
    shutil.copytree(source / "presentation_profiles/spyglass_portal", root / "presentation_profiles/spyglass_portal",
                    ignore=shutil.ignore_patterns("*.png", "*.receipt.json"))
    host = root / "characters/fixture_host"
    host.mkdir()
    config = json.loads((root / "characters/sea_captain/character.json").read_text())
    config.update(id="fixture_host", display_name="Bundled fixture host")
    config["references"] = {"canonical_sheet": "sheet.png", "reference_mode": "IDENTITY_ONLY", "required": True}
    (host / "character.json").write_text(json.dumps(config))
    (host / "sheet.png").write_bytes(b"bundled fixture: historical loader checks existence")
    for key in ("appearance", "behavior", "negative"):
        (host / f"{key}.md").write_text("Fixture prompt.")
    registry = root / "characters/registry.json"
    registry.write_text(json.dumps({
        "schema_version": 1, "default_selection_mode": "auto",
        "auto_fallback_character_id": "fixture_host", "legacy_default_character_id": "fixture_host",
        "characters": [{"id": key, "config": f"{key}/character.json"} for key in ("fixture_host", "sea_captain")],
    }))
    sheet = root / "characters/sea_captain/refs/character_sheet.png"
    if installed:
        write_sheet(sheet)
    return registry, sheet
