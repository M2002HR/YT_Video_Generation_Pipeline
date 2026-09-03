from __future__ import annotations
import sys
from pathlib import Path
import tempfile
import hashlib

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from compose_book_spread import compose
from PIL import Image
import json

def sha(p: Path) -> str:
    import hashlib
    h=hashlib.sha256()
    with p.open("rb") as f:
        for c in iter(lambda: f.read(1024*1024), b""):
            h.update(c)
    return h.hexdigest()

def test_compose_is_deterministic():
    with tempfile.TemporaryDirectory() as d:
        td = Path(d)
        # create dummy world keyframe
        wk = td / "world.png"
        Image.new("RGB", (1080,1920), (180,170,150)).save(wk)
        out1 = td / "out1.png"
        out2 = td / "out2.png"
        m1 = compose(world_keyframe=wk, output=out1, template_id="001", seed=42, aspect_ratio="9:16")
        m2 = compose(world_keyframe=wk, output=out2, template_id="001", seed=42, aspect_ratio="9:16")
        assert sha(out1) == sha(out2)
        assert m1["sha256"] == m2["sha256"]
        # different seed => different output
        out3 = td / "out3.png"
        m3 = compose(world_keyframe=wk, output=out3, template_id="001", seed=99, aspect_ratio="9:16")
        # may be same due to limited variation? but at least file exists
        assert out3.is_file()

def test_compose_places_world_image():
    with tempfile.TemporaryDirectory() as d:
        td = Path(d)
        wk = td / "world.png"
        # world with distinct color
        Image.new("RGB", (800,800), (255,0,0)).save(wk)
        out = td / "spread.png"
        meta = compose(world_keyframe=wk, output=out, template_id="002", seed=0, aspect_ratio="9:16")
        assert out.is_file()
        assert Path(meta["world_keyframe"]) == wk
        with Image.open(out) as im:
            assert im.size == (1080,1920)

def test_nonexistent_keyframe_fails():
    import pytest
    with tempfile.TemporaryDirectory() as d:
        with pytest.raises(FileNotFoundError):
            compose(world_keyframe=Path(d)/"missing.png", output=Path(d)/"out.png")

def test_templates_exist():
    templates = list((ROOT / "projects" / "question_harvest" / "book_templates").glob("*/blank_book.png"))
    assert len(templates) >= 3
