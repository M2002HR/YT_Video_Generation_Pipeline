"""The book spread must show the episode's own world keyframe, and nothing readable (§37, T2.7)."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from PIL import Image, ImageDraw

from compose_book_spread import compose, fit_world_into_page, page_boxes

TEMPLATES = ROOT / "projects" / "question_harvest" / "book_templates"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _template(template_id: str = "001") -> Path:
    path = TEMPLATES / template_id / "blank_book.png"
    assert path.is_file(), f"canonical template missing: {path}"
    return path


def _world(path: Path, *, size=(1080, 1920), seed: int = 3) -> Path:
    """A keyframe with structure, so a crop or swap cannot pass unnoticed."""
    image = Image.new("RGB", size)
    pixels = image.load()
    state = seed * 2654435761 + 1
    for y in range(size[1]):
        for x in range(0, size[0], 8):
            state = (state * 1103515245 + 12345) & 0xFFFFFFFF
            colour = ((state >> 16) & 0xFF, (state >> 8) & 0xFF, (x + y + seed) & 0xFF)
            for dx in range(min(8, size[0] - x)):
                pixels[x + dx, y] = colour
    image.save(path)
    return path


def test_right_page_is_exactly_the_world_keyframe(tmp_path: Path) -> None:
    world = _world(tmp_path / "world.png")
    output = tmp_path / "spread.png"
    meta = compose(
        world_keyframe=world,
        output=output,
        template_id="001",
        seed=7,
        aspect_ratio="9:16",
        template_path=_template("001"),
    )

    box = tuple(meta["right_page_box"])
    with Image.open(output) as spread, Image.open(world) as source:
        rendered = spread.convert("RGB").crop(box)
        expected = fit_world_into_page(source.convert("RGB"), box)
    assert rendered.tobytes() == expected.tobytes()
    assert meta["world_keyframe_sha256"] == sha(world)
    assert meta["world_transform"] == "ImageOps.fit centering=(0.5,0.5) LANCZOS"


def test_a_different_world_keyframe_changes_the_right_page(tmp_path: Path) -> None:
    first = compose(
        world_keyframe=_world(tmp_path / "w1.png", seed=1),
        output=tmp_path / "s1.png",
        template_id="001",
        seed=7,
        template_path=_template("001"),
    )
    second = compose(
        world_keyframe=_world(tmp_path / "w2.png", seed=2),
        output=tmp_path / "s2.png",
        template_id="001",
        seed=7,
        template_path=_template("001"),
    )
    box = tuple(first["right_page_box"])
    with Image.open(first["output"]) as a, Image.open(second["output"]) as b:
        assert a.convert("RGB").crop(box).tobytes() != b.convert("RGB").crop(box).tobytes()


def test_the_left_page_seed_never_changes_the_world_page(tmp_path: Path) -> None:
    world = _world(tmp_path / "world.png")
    a = compose(
        world_keyframe=world, output=tmp_path / "a.png", template_id="001",
        seed=11, template_path=_template("001"),
    )
    b = compose(
        world_keyframe=world, output=tmp_path / "b.png", template_id="001",
        seed=12, template_path=_template("001"),
    )
    box = tuple(a["right_page_box"])
    with Image.open(a["output"]) as first, Image.open(b["output"]) as second:
        assert first.convert("RGB").crop(box).tobytes() == second.convert("RGB").crop(box).tobytes()
    assert a["sha256"] != b["sha256"], "the decorative page should react to the seed"


def test_compose_is_byte_deterministic(tmp_path: Path) -> None:
    world = _world(tmp_path / "world.png")
    first = compose(
        world_keyframe=world, output=tmp_path / "1.png", template_id="002",
        seed=42, template_path=_template("002"),
    )
    second = compose(
        world_keyframe=world, output=tmp_path / "2.png", template_id="002",
        seed=42, template_path=_template("002"),
    )
    assert first["sha256"] == second["sha256"] == sha(tmp_path / "2.png")


def test_no_glyph_is_ever_rendered(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A readable page could state a fact the episode never verified, so text is banned."""

    def _boom(*args, **kwargs):
        raise AssertionError("the compositor must never draw text")

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", _boom)
    monkeypatch.setattr(ImageDraw.ImageDraw, "multiline_text", _boom)
    meta = compose(
        world_keyframe=_world(tmp_path / "world.png"),
        output=tmp_path / "spread.png",
        template_id="003",
        seed=5,
        template_path=_template("003"),
    )
    assert meta["readable_text_drawn"] is False


def test_a_missing_template_is_a_hard_failure(tmp_path: Path) -> None:
    """No synthetic stand-in book: the canonical template is mandatory (§4)."""
    with pytest.raises(FileNotFoundError):
        compose(
            world_keyframe=_world(tmp_path / "world.png"),
            output=tmp_path / "spread.png",
            template_path=tmp_path / "absent.png",
        )
    with pytest.raises(FileNotFoundError):
        compose(
            world_keyframe=_world(tmp_path / "world2.png"),
            output=tmp_path / "spread2.png",
            template_path=None,
        )


def test_a_missing_world_keyframe_is_a_hard_failure(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        compose(
            world_keyframe=tmp_path / "missing.png",
            output=tmp_path / "out.png",
            template_path=_template("001"),
        )


def test_page_boxes_stay_inside_the_canvas_for_every_template() -> None:
    for template_id in ("001", "002", "003"):
        left, right = page_boxes(template_id, 1080, 1920)
        for box in (left, right):
            assert 0 <= box[0] < box[2] <= 1080
            assert 0 <= box[1] < box[3] <= 1920
        assert left[2] <= right[0], "the pages must not overlap"


def test_every_catalogued_template_has_a_usable_blank_book() -> None:
    import json

    catalog = json.loads((TEMPLATES / "CATALOG.json").read_text(encoding="utf-8"))
    entries = catalog.get("templates") or []
    assert len(entries) >= 3
    for entry in entries:
        blank = TEMPLATES / str(entry["path"]) / "blank_book.png"
        assert blank.is_file(), f"{entry['template_id']} has no blank_book.png"
        with Image.open(blank) as image:
            image.verify()
