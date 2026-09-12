from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from subtitle_font_runtime import (
    css_equivalent_ass_geometry,
    prepare_uploaded_fonts_dir,
    sfnt_vertical_metrics,
)


def test_uploaded_display_font_is_scaled_to_css_geometry(tmp_path: Path) -> None:
    source = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    folder = tmp_path / "control_panel" / "subtitle_fonts"
    folder.mkdir(parents=True)
    font_id = "a" * 32
    legacy = folder / f"{font_id}.ttf"
    shutil.copyfile(source, legacy)
    digest = hashlib.sha256(legacy.read_bytes()).hexdigest()
    (folder / "catalog.json").write_text(json.dumps({"fonts": [{
        "id": font_id, "family": "Uploaded DejaVu", "extension": ".ttf", "sha256": digest,
    }]}), encoding="utf-8")

    units, ascender, descender = sfnt_vertical_metrics(legacy)
    size, margin = css_equivalent_ass_geometry(tmp_path, "Uploaded DejaVu", 120, 200)

    assert size == 120 * (ascender - descender) / units
    assert margin == round(200 - 120 * (-descender) / (ascender - descender))
    prepared = prepare_uploaded_fonts_dir(tmp_path)
    assert prepared == folder / "files"
    assert (prepared / legacy.name).read_bytes() == legacy.read_bytes()


def test_non_uploaded_font_keeps_existing_ass_geometry(tmp_path: Path) -> None:
    assert css_equivalent_ass_geometry(tmp_path, "DejaVu Sans", 56, 144) == (56, 144)
