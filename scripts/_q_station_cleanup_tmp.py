#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def remove(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    # One-shot infrastructure must not survive the resulting cleanup commit.
    remove(ROOT / ".github/workflows/q-station-only-cleanup.yml")
    remove(Path(__file__))

    # Q Station is the sole content project.
    for rel in (
        "projects/default",
        "projects/question_harvest",
        "projects/world_behind_the_question",
        "projects/q_station/characters/farmer_host",
    ):
        remove(ROOT / rel)

    # Retired pre-registry host identity.
    remove(ROOT / "projects/q_station/visual_presets/001_home_world/character_sheet.png")
    remove(ROOT / "projects/q_station/visual_presets/001_home_world/source")

    keep_videos = {
        "026_black_swan_meaning_by_nassim_talib",
        "027_video",
        "028_what_will_happen_if_you_sleep_less_than_5_hours_a_day",
        "029_why_a_song_gets_stuck_in_your_head",
        "030_8_of_the_strangest_ocean_creatures",
        "031_wwhy_does_seeing_someone_yawn_make_you_yawn_too",
        "032_why_does_seeing_someone_yawn_make_you_yawn_too",
        "033_the_ancient_computer_found_in_a_shipwreck",
        "034_what_if_every_human_vanished_tomorrow",
        "035_what_if_every_human_vanished_tomorrow",
        "037_why_are_humans_ashamed_of_being_naked",
    }
    videos_root = ROOT / "videos"
    if videos_root.is_dir():
        for child in list(videos_root.iterdir()):
            if child.name not in keep_videos:
                remove(child)

    # Only style identities referenced by the retained run set survive.
    keep_style_prefixes = {"010", "013", "015", "016", "017", "018", "019", "020", "021"}
    styles_root = ROOT / "projects/q_station/world_styles"
    for child in list(styles_root.iterdir()):
        if child.is_dir() and child.name.split("_", 1)[0] not in keep_style_prefixes:
            remove(child)
    catalog_path = styles_root / "CATALOG.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog["styles"] = [
        item for item in catalog.get("styles", [])
        if str(item.get("path", "")).split("_", 1)[0] in keep_style_prefixes
    ]
    write_json(catalog_path, catalog)

    keep_ids = {name.split("_", 1)[0] for name in keep_videos}
    history_path = ROOT / "projects/q_station/VIDEOS.json"
    history = json.loads(history_path.read_text(encoding="utf-8"))
    history["project_id"] = "q_station"
    history["videos"] = [item for item in history.get("videos", []) if str(item.get("video_id")) in keep_ids]
    write_json(history_path, history)

    registry_path = ROOT / "projects/q_station/characters/registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["auto_fallback_character_id"] = "red_horned_everyman"
    registry["legacy_default_character_id"] = "red_horned_everyman"
    registry["characters"] = [
        {"id": "red_horned_everyman", "config": "red_horned_everyman/character.json"},
        {"id": "moss_cloaked_crone", "config": "moss_cloaked_crone/character.json"},
        {"id": "sea_captain", "config": "sea_captain/character.json"},
    ]
    write_json(registry_path, registry)

    project_path = ROOT / "projects/q_station/PROJECT.json"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    project["id"] = "q_station"
    project["project_id"] = "q_station"
    project["display_name"] = "Q Station"
    project["aliases"] = []
    write_json(project_path, project)

    explicit_renames = {
        "scripts/run_question_harvest_pipeline.py": "scripts/run_q_station_pipeline.py",
        "scripts/run_full_video_pipeline_qh_wrapper.py": "scripts/run_full_video_pipeline_q_station_wrapper.py",
        "docs/QUESTION_HARVEST_PIPELINE.md": "docs/Q_STATION_PIPELINE.md",
    }
    for old_rel, new_rel in explicit_renames.items():
        old, new = ROOT / old_rel, ROOT / new_rel
        if old.exists():
            if new.exists():
                raise RuntimeError(f"rename target already exists: {new_rel}")
            new.parent.mkdir(parents=True, exist_ok=True)
            old.rename(new)

    for old in sorted(ROOT.glob("videos/**/QH_RUNTIME_STATE.json")):
        new = old.with_name("Q_STATION_RUNTIME_STATE.json")
        if new.exists():
            raise RuntimeError(f"rename target already exists: {new}")
        old.rename(new)

    def clean_name(name: str) -> str:
        pairs = (
            ("QUESTION_HARVEST", "Q_STATION"),
            ("Question_Harvest", "Q_Station"),
            ("question_harvest", "q_station"),
            ("question-harvest", "q-station"),
            ("QH_", "Q_STATION_"),
            ("qh_", "q_station_"),
            ("farmer_host", "red_horned_everyman"),
        )
        for old, new in pairs:
            name = name.replace(old, new)
        return name

    existing_files = [p for p in ROOT.rglob("*") if p.is_file() and ".git" not in p.parts]
    for path in sorted(existing_files, key=lambda p: len(p.parts), reverse=True):
        new_name = clean_name(path.name)
        if new_name != path.name:
            target = path.with_name(new_name)
            if target.exists():
                raise RuntimeError(f"filename cleanup collision: {path} -> {target}")
            path.rename(target)

    literal_replacements = (
        ("run_full_video_pipeline_qh_wrapper.py", "run_full_video_pipeline_q_station_wrapper.py"),
        ("run_full_video_pipeline_qh_wrapper", "run_full_video_pipeline_q_station_wrapper"),
        ("run_question_harvest_pipeline.py", "run_q_station_pipeline.py"),
        ("run_question_harvest_pipeline", "run_q_station_pipeline"),
        ("QUESTION_HARVEST", "Q_STATION"),
        ("Question Harvest", "Q Station"),
        ("question harvest", "Q Station"),
        ("question_harvest", "q_station"),
        ("question-harvest", "q-station"),
        ("World Behind the Question", "Q Station"),
        ("World Behind The Question", "Q Station"),
        ("world behind the question", "Q Station"),
        ("WORLD_BEHIND_THE_QUESTION", "Q_STATION"),
        ("world_behind_the_question", "q_station"),
        ("QH_RUNTIME_STATE.json", "Q_STATION_RUNTIME_STATE.json"),
        ("QHState", "QStationState"),
        ("Farmer Host", "Red Horned Everyman"),
        ("FARMER_HOST", "RED_HORNED_EVERYMAN"),
        ("farmer_host", "red_horned_everyman"),
        ("farmer-host", "red-horned-everyman"),
        ("_qh", "_q_station"),
        ("QH_", "Q_STATION_"),
        ("qh_", "q_station_"),
    )

    skip_dirs = {".git", "node_modules", "__pycache__"}
    for path in [p for p in ROOT.rglob("*") if p.is_file() and not any(part in skip_dirs for part in p.parts)]:
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        if b"\x00" in raw[:8192]:
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        original = text
        for old, new in literal_replacements:
            text = text.replace(old, new)
        text = re.sub(r"(?<![A-Za-z0-9_])qh(?![A-Za-z0-9_])", "qstation", text)
        text = re.sub(r"(?<![A-Za-z0-9_])QH(?![A-Za-z0-9_])", "QStation", text)
        if text != original:
            path.write_text(text, encoding="utf-8")

    # The project resolver is intentionally single-project; dead provider/project fallbacks are removed.
    cp_path = ROOT / "scripts/content_projects.py"
    cp = cp_path.read_text(encoding="utf-8")
    cp = cp.replace('DEFAULT_CONTENT_PROJECT = "default"', 'DEFAULT_CONTENT_PROJECT = "q_station"')
    cp = cp.replace(
        'return str(self.config.get("pipeline_profile") or "default").strip().lower()',
        'return str(self.config.get("pipeline_profile") or "bookworld_mixed_media").strip().lower()',
    )
    cp = re.sub(
        r"    def get_provider\(self, kind: str\) -> str:\n.*?\n    def get_default_model",
        "    def get_provider(self, kind: str) -> str:\n"
        "        cfg = self.provider_config(kind)\n"
        "        if not cfg:\n"
        "            if kind == \"text\":\n"
        "                return \"chatgpt\"\n"
        "            if kind == \"image\":\n"
        "                return \"gemini\"\n"
        "            if kind == \"video\":\n"
        "                return \"flow\"\n"
        "            return \"unknown\"\n"
        "        return str(cfg.get(\"provider\") or \"\").strip().lower()\n\n"
        "    def get_default_model",
        cp,
        flags=re.S,
    )
    cp_path.write_text(cp, encoding="utf-8")

    (ROOT / "projects/q_station/visual_presets/001_home_world/README.md").write_text(
        "# 001_home_world — Q Station opening treatment\n\n"
        "This compatibility preset controls rendering treatment only. It does not define host identity.\n"
        "Canonical host identity is resolved exclusively from `projects/q_station/characters/registry.json`.\n"
        "The retained book design assets belong to the `book_portal` presentation used by the red host.\n"
        "No preset-level character sheet exists, and no style sheet is uploaded to Flow as a host identity reference.\n",
        encoding="utf-8",
    )

    (ROOT / "projects/README.md").write_text(
        "# Content projects\n\n"
        "This repository has one content project: `q_station`.\n\n"
        "- Configuration: `projects/q_station/PROJECT.json`\n"
        "- Prompts: `projects/q_station/prompts/`\n"
        "- Characters: `projects/q_station/characters/`\n"
        "- Presentation profiles: `projects/q_station/presentation_profiles/`\n"
        "- Topic-world styles: `projects/q_station/world_styles/`\n\n"
        "No project aliases are supported. The control panel and runners resolve `q_station` directly.\n",
        encoding="utf-8",
    )
    (ROOT / "projects/q_station/README.md").write_text(
        "# Q Station\n\n"
        "Q Station is the sole content project in this repository. It produces short English question-driven videos with a topic-first opening, continuous narration, generated topic-world imagery, and a two-clip entry transition.\n\n"
        "## Hosts\n\n"
        "- `red_horned_everyman` — `book_portal`\n"
        "- `moss_cloaked_crone` — `orb_portal`\n"
        "- `sea_captain` — `spyglass_portal`\n\n"
        "Host identity is resolved from `characters/registry.json`; presentation mechanics are resolved from `presentation_profiles/`. Topic-world style is independent of host identity. The red host is both automatic fallback and compatibility default.\n\n"
        "Runtime entry points are `scripts/run_q_station_pipeline.py` and `scripts/run_full_video_pipeline_q_station_wrapper.py`. See `docs/Q_STATION_PIPELINE.md`, `docs/OPENING_STORY_PIPELINE.md`, `docs/SPOKEN_ENGLISH_POLICY.md`, and `docs/SEA_CAPTAIN_INTEGRATION.md`.\n",
        encoding="utf-8",
    )
    (ROOT / "PROJECT_CONTEXT.md").write_text(
        "# YT Video Generation Pipeline — Q Station architecture\n\n"
        "The repository has one active content project: `q_station`. There are no project aliases.\n\n"
        "## Canonical entry points\n\n"
        "- Panel/API: `scripts/video_control_panel.py` and `control_panel/ui/`\n"
        "- Orchestration: `scripts/run_full_video_pipeline_q_station_wrapper.py`\n"
        "- Creative/visual runtime: `scripts/run_q_station_pipeline.py`\n"
        "- Stage/DAG/artifacts/invalidation: `scripts/pipeline_stages.py`, `scripts/run_graph.py`\n"
        "- Character identity: `scripts/character_runtime.py`, `projects/q_station/characters/`\n"
        "- Opening selection: `scripts/opening_runtime.py`\n"
        "- Presentation profiles: `scripts/presentation_runtime.py`, `projects/q_station/presentation_profiles/`\n"
        "- Topic-world style: `projects/q_station/world_styles/`\n\n"
        "## Supported hosts\n\n"
        "| Character | Presentation | Entry |\n"
        "|---|---|---|\n"
        "| Red Horned Everyman | `book_portal` | recurring storybook |\n"
        "| Moss-Cloaked Crone | `orb_portal` | recognizable orb |\n"
        "| Curious Sea Captain | `spyglass_portal` | recognizable spyglass |\n\n"
        "The red host is the automatic fallback and compatibility default. Host selection is frozen for ordinary resume/retry; the panel Revise operation is the explicit controlled way to change it.\n\n"
        "## Runtime invariants\n\n"
        "- Text provider is ChatGPT, image provider is Gemini, and opening video provider is Flow through Ordak.\n"
        "- No synthetic provider fallback or placeholder media.\n"
        "- Flow A uses the selected canonical character sheet. Flow B uses generated first/last frames only.\n"
        "- Narration alignment drives clip trimming and the final timeline.\n"
        "- Topic-world art direction is independent of host costume and identity.\n"
        "- Paid outputs are reused only with valid durable state and receipt contracts.\n"
        "- Operator-installed host artwork is selectable only after validation.\n\n"
        "See `docs/Q_STATION_PIPELINE.md` for the end-to-end contract and `docs/RECOVERY_RUNBOOK.md` for operations.\n",
        encoding="utf-8",
    )

    # Structural regression guard; identifiers are composed so the retired names are not themselves reintroduced.
    guard = ROOT / "tests/test_q_station_only_repository.py"
    guard.write_text(
        '''from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _old_identifiers() -> tuple[str, ...]:
    return (
        "_".join(("question", "harvest")),
        "_".join(("world", "behind", "the", "question")),
        "_".join(("farmer", "host")),
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
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    tracked = [item for item in tracked if item]
    banned = _old_identifiers()
    for rel in tracked:
        lowered = rel.lower()
        assert all(token not in lowered for token in banned), rel
        path = ROOT / rel
        if not path.is_file():
            continue
        raw = path.read_bytes()
        if b"\0" in raw[:8192]:
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
''',
        encoding="utf-8",
    )

    # Normalize generated docs/guard and any text created after the first pass.
    for path in [p for p in ROOT.rglob("*") if p.is_file() and ".git" not in p.parts]:
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        if b"\x00" in raw[:8192]:
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        original = text
        for old, new in literal_replacements:
            text = text.replace(old, new)
        text = re.sub(r"(?<![A-Za-z0-9_])qh(?![A-Za-z0-9_])", "qstation", text)
        text = re.sub(r"(?<![A-Za-z0-9_])QH(?![A-Za-z0-9_])", "QStation", text)
        if text != original:
            path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
