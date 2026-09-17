from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _retired_identifiers() -> tuple[str, ...]:
    return (
        "_".join(("question", "harvest")),
        "_".join(("world", "behind", "the", "question")),
        "_".join(("red_host", "host")),
    )


def test_only_q_station_project_and_four_hosts_remain() -> None:
    project_dirs = sorted(p.name for p in (ROOT / "projects").iterdir() if p.is_dir() and not p.is_symlink())
    assert project_dirs == ["q_station"]
    project = json.loads((ROOT / "projects/q_station/PROJECT.json").read_text())
    assert project["project_id"] == "q_station"
    assert project.get("aliases") == []
    registry = json.loads((ROOT / "projects/q_station/characters/registry.json").read_text())
    expected = {"red_horned_everyman", "moss_cloaked_crone", "sea_captain", "newton_scholar"}
    assert {item["id"] for item in registry["characters"]} == expected
    assert registry["auto_fallback_character_id"] == "red_horned_everyman"
    assert registry["legacy_default_character_id"] == "red_horned_everyman"
    assert {p.name for p in (ROOT / "projects/q_station/characters").iterdir() if p.is_dir()} == expected


def test_only_audited_q_station_runs_remain() -> None:
    supported = {item["id"] for item in json.loads((ROOT / "projects/q_station/characters/registry.json").read_text())["characters"]}
    runs = [p for p in (ROOT / "videos").iterdir() if p.is_dir()]
    assert runs
    for run in runs:
        launch = json.loads((run / "launch/LAUNCH_REQUEST.json").read_text())
        assert launch.get("content_project") == "q_station", run.name
        resolution_path = run / "creative/CHARACTER_RESOLUTION.json"
        resolution = json.loads(resolution_path.read_text()) if resolution_path.is_file() else launch.get("character_resolution", {})
        selected = resolution.get("resolved_character_id") or (launch.get("character") or {}).get("character_id")
        assert selected in supported, (run.name, selected)


def test_retired_ids_are_absent_from_tracked_paths_and_text() -> None:
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split(chr(0))
    tracked = [item for item in tracked if item]
    banned = _retired_identifiers()
    for rel in tracked:
        lowered = rel.lower()
        assert all(token not in lowered for token in banned), rel
        path = ROOT / rel
        if not path.is_file():
            continue
        raw = path.read_bytes()
        if bytes([0]) in raw[:8192]:
            continue
        try:
            text = raw.decode("utf-8").lower()
        except UnicodeDecodeError:
            continue
        assert all(token not in text for token in banned), rel


def test_pre_registry_host_sheet_is_gone() -> None:
    preset = ROOT / "projects/q_station/visual_presets/001_home_world"
    assert not (preset / "character_sheet.png").exists()
    assert not (preset / "source").exists()
