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


def test_only_q_station_project_and_three_hosts_remain() -> None:
    project_dirs = sorted(p.name for p in (ROOT / "projects").iterdir() if p.is_dir() and not p.is_symlink())
    assert project_dirs == ["q_station"]
    project = json.loads((ROOT / "projects/q_station/PROJECT.json").read_text())
    assert project["project_id"] == "q_station"
    assert project.get("aliases") == []
    registry = json.loads((ROOT / "projects/q_station/characters/registry.json").read_text())
    expected = {"red_horned_everyman", "moss_cloaked_crone", "sea_captain"}
    assert {item["id"] for item in registry["characters"]} == expected
    assert registry["auto_fallback_character_id"] == "red_horned_everyman"
    assert registry["legacy_default_character_id"] == "red_horned_everyman"
    assert {p.name for p in (ROOT / "projects/q_station/characters").iterdir() if p.is_dir()} == expected


def test_only_audited_q_station_runs_remain() -> None:
    expected = {
        "026_black_swan_meaning_by_nassim_talib", "027_video",
        "028_what_will_happen_if_you_sleep_less_than_5_hours_a_day",
        "029_why_a_song_gets_stuck_in_your_head", "030_8_of_the_strangest_ocean_creatures",
        "031_wwhy_does_seeing_someone_yawn_make_you_yawn_too",
        "032_why_does_seeing_someone_yawn_make_you_yawn_too",
        "033_the_ancient_computer_found_in_a_shipwreck", "034_what_if_every_human_vanished_tomorrow",
        "035_what_if_every_human_vanished_tomorrow", "037_why_are_humans_ashamed_of_being_naked",
    }
    assert {p.name for p in (ROOT / "videos").iterdir()} == expected


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
