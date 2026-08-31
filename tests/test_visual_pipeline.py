from __future__ import annotations
import importlib.util
import os
import sys
from pathlib import Path
import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location("run_visual_pipeline", SCRIPTS / "run_visual_pipeline.py")
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)

class NoopClient:
    pass

def make_content_project(tmp_path: Path):
    root = tmp_path / "projects" / "test_project"
    root.mkdir(parents=True)
    return module.ContentProject("test_project", root, {
        "project_id": "test_project",
        "display_name": "Test Project",
        "default_visual_preset": "preset",
        "brief_defaults": {"audience": "curious viewers", "constraints": "be accurate"},
    })

def make_pipeline(tmp_path: Path):
    return module.Pipeline(tmp_path, "Topic", "002", "preset", 60, 60, "16:9", make_content_project(tmp_path), NoopClient(), False)

def save_nontrivial_png(path: Path, width: int, height: int) -> None:
    Image.frombytes("RGB", (width, height), os.urandom(width * height * 3)).save(path)

def make_beats(count: int) -> str:
    return "\n\n".join(
        f"### Beat {i:02d}\nNarration:\nN{i}\n\nVisual:\nV{i}\n\nPurpose:\nP{i}\n\nType:\nliteral\n\nContinuity:\nnone"
        for i in range(1, count + 1)
    )

def test_parse_beats_requires_complete_sequential_range(tmp_path: Path) -> None:
    pipeline = make_pipeline(tmp_path)
    parsed = pipeline.parse_beats(make_beats(17))
    assert len(parsed) == 17
    malformed = make_beats(16).replace("Beat 16", "Beat 17")
    with pytest.raises(RuntimeError, match="sequential"):
        pipeline.parse_beats(malformed)


def test_clean_model_text_removes_only_editor_affordance() -> None:
    assert module.clean_model_text("Edit\n\nUseful answer") == "Useful answer"
    assert module.clean_model_text("Editing is useful") == "Editing is useful"

def test_image_validation_rejects_duplicate_and_wrong_aspect(tmp_path: Path) -> None:
    pipeline = make_pipeline(tmp_path)
    pipeline.project.mkdir(parents=True)
    landscape = pipeline.project / "beat.png"
    save_nontrivial_png(landscape, 1600, 900)
    metadata = pipeline.valid_image(landscape)
    with pytest.raises(RuntimeError, match="duplicates"):
        pipeline.valid_image(landscape, metadata["sha256"])
    portrait = pipeline.project / "portrait.png"
    save_nontrivial_png(portrait, 900, 1600)
    with pytest.raises(RuntimeError, match="approximately 16:9"):
        pipeline.valid_image(portrait)

def test_existing_valid_beat_is_skipped(tmp_path: Path) -> None:
    pipeline = make_pipeline(tmp_path)
    pipeline.project.mkdir(parents=True)
    pipeline.state = {"beats": {"001": {"status": "PROMPT_READY", "attempts": 0}}, "stages": {}}
    output = pipeline.project / "assets" / "raw_beats"
    output.mkdir(parents=True)
    save_nontrivial_png(output / "beat_001.png", 1600, 900)
    style = tmp_path / "style.png"; character = tmp_path / "character.png"
    Image.new("RGB", (1600, 900), "red").save(style)
    Image.new("RGB", (1600, 900), "green").save(character)
    pipeline.generate_images([{"id": 1}], style, character)
    assert pipeline.state["beats"]["001"]["status"] == "DONE"
    assert pipeline.state["beats"]["001"]["attempts"] == 0


def test_creative_brief_is_persisted_and_resume_locked(tmp_path: Path) -> None:
    project = make_content_project(tmp_path)
    brief = {"narrative_angle": "Enter through a clockwork book.", "must_avoid": "No fake statistics."}
    pipeline = module.Pipeline(tmp_path, "Topic", "002", "preset", 60, 60, "16:9", project, NoopClient(), False, brief)
    text = pipeline.brief().read_text(encoding="utf-8")
    assert "Narrative angle: Enter through a clockwork book." in text
    assert "Must avoid: No fake statistics." in text
    pipeline.load_or_init()

    changed = module.Pipeline(tmp_path, "Topic", "002", "preset", 60, 60, "16:9", project, NoopClient(), False, {"narrative_angle": "A different world."})
    with pytest.raises(RuntimeError, match="creative brief"):
        changed.load_or_init()


def test_world_design_requires_complete_production_bible(tmp_path: Path) -> None:
    pipeline = make_pipeline(tmp_path)
    headings = (
        "Governing Metaphor", "The Question Book", "Portal Transition", "Subject World",
        "Palette, Materials, and Light", "Seeker Adaptation", "Recurring Locations and Props",
        "Visual Arc", "Continuity Rules", "Avoid",
    )
    complete = "# Episode World Design\n\n" + "\n\n".join(f"## {heading}\n" + "specific production detail " * 14 for heading in headings)
    pipeline.validate_world_design(complete)
    pipeline.validate_world_design(complete.replace("## ", ""))
    with pytest.raises(RuntimeError, match="world design validation"):
        pipeline.validate_world_design(complete.replace("## The Question Book", "## Missing Book"))
