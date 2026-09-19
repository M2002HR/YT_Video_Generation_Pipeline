from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from release_settings import normalize_release_settings  # noqa: E402
from thumbnail_compositor import FONT_FILES, compose, resolve_font  # noqa: E402


# Release typography is intentionally locked to the verified uploaded font.
LAYOUT_TEST_FONT = "quicky_story"


def test_compositor_renders_final_text_and_preview(tmp_path: Path) -> None:
    artwork = tmp_path / "artwork.png"; final = tmp_path / "final.png"
    Image.new("RGB", (1080, 1920), "#315a73").save(artwork)
    settings = normalize_release_settings({"thumbnail": {"font_id": LAYOUT_TEST_FONT, "text_mode": "manual", "manual_text": "WHY DO WE HIDE"}})["thumbnail"]
    layout = compose(artwork, final, "WHY DO WE HIDE", settings, "stacked_brand")
    assert final.is_file() and final.stat().st_size > 1000
    assert final.with_name("preview_small.jpg").is_file()
    assert layout["text"] == "WHY DO WE HIDE"
    assert layout["text_bounds"]["width"] > 0
    assert layout["font_id"] == LAYOUT_TEST_FONT
    assert layout["font_sha256"] == resolve_font(LAYOUT_TEST_FONT)[1]


def test_compositor_reduces_from_preferred_size_before_rejecting_valid_copy(tmp_path: Path) -> None:
    artwork = tmp_path / "artwork.png"; Image.new("RGB", (1536, 2752), "#315a73").save(artwork)
    settings = normalize_release_settings({"thumbnail": {"font_id": LAYOUT_TEST_FONT, "text_mode": "manual", "manual_text": "Why Nakedness Feels Different"}})["thumbnail"]
    assert compose(artwork, tmp_path / "final.png", "Why Nakedness Feels Different", settings, "character_left")["text_bounds"]["height"] > 0


def test_compositor_refuses_to_silently_truncate_unfit_manual_copy(tmp_path: Path) -> None:
    artwork = tmp_path / "artwork.png"; Image.new("RGB", (1080, 1920), "#315a73").save(artwork)
    # Exercise the standalone legacy compositor directly. Release normalization
    # intentionally discards all text-placement inputs for the text-free flow.
    settings = normalize_release_settings({})["thumbnail"]
    settings.update({"font_id": LAYOUT_TEST_FONT, "max_lines": 1, "text_box_width": .3})
    with pytest.raises(ValueError, match="cannot fit|line limit|readable"):
        compose(artwork, tmp_path / "final.png", "ONE TWO THREE FOUR FIVE SIX", settings, "character_left")


def test_production_thumbnail_default_is_verified_quicky_story() -> None:
    assert normalize_release_settings({})["thumbnail"]["font_id"] == "quicky_story"


def test_missing_requested_font_never_silently_falls_back(tmp_path: Path, monkeypatch) -> None:
    missing = tmp_path / "not-installed.ttf"
    monkeypatch.setitem(FONT_FILES, "quicky_story", missing)
    with pytest.raises(RuntimeError, match="quicky_story is not installed"):
        resolve_font("quicky_story")
