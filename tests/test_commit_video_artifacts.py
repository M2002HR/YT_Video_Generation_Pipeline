from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("commit_video_artifacts", ROOT / "scripts" / "commit_video_artifacts.py")
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data) + "\n", encoding="utf-8")


def test_completed_video_is_registered_in_selected_content_project(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(module, "ROOT", tmp_path)
    video = tmp_path / "videos" / "008_first_question"
    video.mkdir(parents=True)
    project = tmp_path / "projects" / "q_station"
    write_json(project / "PROJECT.json", {"project_id": "q_station"})
    write_json(project / "VIDEOS.json", {"schema_version": 1, "project_id": "q_station", "videos": []})

    registry = module.register_content_project_video(video, {"content_project": "q_station"})
    videos = json.loads(registry.read_text(encoding="utf-8"))["videos"]
    assert [entry["video_id"] for entry in videos] == ["008_first_question"]

    # Registering the same video again must not duplicate it.
    module.register_content_project_video(video, {"content_project": "q_station"})
    videos = json.loads(registry.read_text(encoding="utf-8"))["videos"]
    assert [entry["video_id"] for entry in videos] == ["008_first_question"]


def test_registration_preserves_the_traits_already_recorded(tmp_path: Path, monkeypatch) -> None:
    """The anti-repetition traits are written by the pipeline; registration must not erase them."""
    monkeypatch.setattr(module, "ROOT", tmp_path)
    video = tmp_path / "videos" / "010_second_question"
    video.mkdir(parents=True)
    project = tmp_path / "projects" / "q_station"
    write_json(project / "PROJECT.json", {"project_id": "q_station"})
    write_json(project / "VIDEOS.json", {
        "schema_version": 1,
        "project_id": "q_station",
        "videos": [
            "009_legacy_string_entry",
            {"video_id": "010_second_question", "opening_activity": "watering plants"},
        ],
    })

    registry = module.register_content_project_video(video, {"content_project": "q_station"})
    videos = json.loads(registry.read_text(encoding="utf-8"))["videos"]
    assert any(entry.get("opening_activity") == "watering plants" for entry in videos)


def test_run_related_extras_cover_style_and_identity(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(module, "ROOT", tmp_path)
    video = tmp_path / "videos" / "008_first_question"
    (video / "creative").mkdir(parents=True)
    write_json(video / "creative" / "WORLD_STYLE_PLAN.json", {"style_id": "demo_style_001"})
    write_json(video / "creative" / "PRESENTATION_RESOLUTION.json", {"profile_id": "demo_portal"})
    content = tmp_path / "projects" / "q_station"
    write_json(content / "world_styles" / "CATALOG.json", {
        "schema_version": 1,
        "styles": [{"style_id": "demo_style_001", "path": "001_demo", "anchor": "001_demo/style_anchor.png"}],
    })
    write_json(content / "world_styles" / "001_demo" / "STYLE_PLAN.json", {"style_id": "demo_style_001"})
    (content / "world_styles" / "001_demo" / "style_anchor.png").write_bytes(b"fake-png")
    profile = content / "presentation_profiles" / "demo_portal"
    prompts = {key: f"{key} text" for key in (
        "script_rules", "episode_rules", "question_intro",
        "entry_transition", "entry_identity", "entry_frame",
    )}
    for key, text in prompts.items():
        (profile / "prompts" / f"{key}.md").parent.mkdir(parents=True, exist_ok=True)
        (profile / "prompts" / f"{key}.md").write_text(text + "\n", encoding="utf-8")
    write_json(profile / "profile.json", {
        "schema_version": 1, "id": "demo_portal", "entry_kind": "demo",
        "narration_segment": {"key": "entry_transition", "label": "demo"},
        "prompt_files": {key: f"prompts/{key}.md" for key in prompts},
        "identity": {"canonical_sheet": "refs/demo_sheet.png"},
        "entry_variants": ["near_detail"],
        "artifacts": {
            "question_prompt": "references/q.txt", "entry_prompt": "references/e.txt",
            "question_source": "assets/q.mp4", "entry_source": "assets/e.mp4",
            "question_trimmed": "assets/qt.mp4", "entry_trimmed": "assets/et.mp4",
            "entry_direction": "creative/D.txt", "entry_frame": "references/f.png",
            "entry_image_receipt": "pipeline/r.json",
        },
    })
    (profile / "refs" / "demo_sheet.png").parent.mkdir(parents=True, exist_ok=True)
    (profile / "refs" / "demo_sheet.png").write_bytes(b"fake-png")
    (profile / "refs" / "demo_sheet.png.receipt.json").write_text("{}\n", encoding="utf-8")

    extras = module.run_related_extra_paths(video, "q_station")
    relatives = sorted(str(path.relative_to(tmp_path)) for path in extras)
    assert relatives == [
        "projects/q_station/presentation_profiles/demo_portal/refs/demo_sheet.png",
        "projects/q_station/presentation_profiles/demo_portal/refs/demo_sheet.png.receipt.json",
        "projects/q_station/world_styles/001_demo/STYLE_PLAN.json",
        "projects/q_station/world_styles/001_demo/style_anchor.png",
        "projects/q_station/world_styles/CATALOG.json",
    ]


def test_run_related_extras_are_empty_without_creative_records(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(module, "ROOT", tmp_path)
    video = tmp_path / "videos" / "008_first_question"
    video.mkdir(parents=True)
    assert module.run_related_extra_paths(video, "q_station") == []


def test_scoped_commit_preserves_unrelated_staged_work(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(module, "ROOT", tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    unrelated = tmp_path / "unrelated.txt"
    unrelated.write_text("user work\n", encoding="utf-8")
    subprocess.run(["git", "add", "unrelated.txt"], cwd=tmp_path, check=True)
    video = tmp_path / "videos" / "008_first_question"
    video.mkdir(parents=True)
    (video / "result.txt").write_text("done\n", encoding="utf-8")

    assert module.commit_paths([video], "video only")
    committed = subprocess.check_output(["git", "show", "--pretty=", "--name-only", "HEAD"], cwd=tmp_path, text=True).splitlines()
    still_staged = subprocess.check_output(["git", "diff", "--cached", "--name-only"], cwd=tmp_path, text=True).splitlines()
    assert committed == ["videos/008_first_question/result.txt"]
    assert still_staged == ["unrelated.txt"]
