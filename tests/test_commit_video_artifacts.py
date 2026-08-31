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
    project = tmp_path / "projects" / "world_behind_the_question"
    write_json(project / "PROJECT.json", {"project_id": "world_behind_the_question"})
    write_json(project / "VIDEOS.json", {"schema_version": 1, "project_id": "world_behind_the_question", "videos": []})

    registry = module.register_content_project_video(video, {"content_project": "world_behind_the_question"})
    assert json.loads(registry.read_text(encoding="utf-8"))["videos"] == ["008_first_question"]


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
