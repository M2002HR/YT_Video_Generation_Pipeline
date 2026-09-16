from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from release_settings import normalize_release_settings  # noqa: E402
from thumbnail_compositor import compose  # noqa: E402


def test_compositor_renders_final_text_and_preview(tmp_path: Path) -> None:
    artwork = tmp_path / "artwork.png"; final = tmp_path / "final.png"
    Image.new("RGB", (1080, 1920), "#315a73").save(artwork)
    settings = normalize_release_settings({"thumbnail": {"text_mode": "manual", "manual_text": "WHY DO WE HIDE"}})["thumbnail"]
    layout = compose(artwork, final, "WHY DO WE HIDE", settings, "character_left")
    assert final.is_file() and final.stat().st_size > 1000
    assert final.with_name("preview_small.jpg").is_file()
    assert layout["text"] == "WHY DO WE HIDE"
    assert layout["text_bounds"]["width"] > 0


def test_compositor_refuses_to_silently_truncate_unfit_manual_copy(tmp_path: Path) -> None:
    artwork = tmp_path / "artwork.png"; Image.new("RGB", (1080, 1920), "#315a73").save(artwork)
    settings = normalize_release_settings({"thumbnail": {"text_mode": "manual", "manual_text": "ONE TWO THREE FOUR FIVE SIX", "max_lines": 1, "text_box_width": .3}})["thumbnail"]
    with pytest.raises(ValueError, match="cannot fit|line limit|readable"):
        compose(artwork, tmp_path / "final.png", "ONE TWO THREE FOUR FIVE SIX", settings, "character_left")
