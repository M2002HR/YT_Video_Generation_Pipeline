from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from run_graph import graph_for, invalidation_paths, music_files, regeneration_plan


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def project_with_beats(tmp_path: Path, count: int = 4) -> Path:
    project = tmp_path / "video"
    write_json(project / "creative/VISUAL_PLAN.json", {"beats": [{"beat_id": number} for number in range(1, count + 1)]})
    for number in range(1, count + 1):
        path = project / f"assets/raw_beats/beat_{number:03d}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"image")
    return project


def generic_project_with_beats(tmp_path: Path, count: int = 3) -> Path:
    project = tmp_path / "generic_video"
    write_json(
        project / "launch/LAUNCH_REQUEST.json",
        {
            "content_project": "default",
            "motion": {"enabled": False},
            "sfx": {"enabled": False},
            "commit_artifacts": False,
            "telegram_low_size": True,
        },
    )
    write_json(
        project / "visual_pipeline/RUNTIME_STATE.json",
        {
            "stages": {
                "script_draft": {"status": "DONE"},
                "retention_edit": {"status": "DONE"},
                "visual_beats": {"status": "DONE"},
            },
            "beats": {
                f"{number:03d}": {"status": "DONE"}
                for number in range(1, count + 1)
            },
        },
    )
    for relative in ("SCRIPT_DRAFT.md", "SCRIPT_FINAL.md", "VISUAL_BEATS.md"):
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("content", encoding="utf-8")
    for number in range(1, count + 1):
        path = project / f"assets/raw_beats/beat_{number:03d}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"image")
    write_json(project / "visual_pipeline/VISUAL_QC_REPORT.json", {"passed": True})
    return project


def test_music_artifact_is_resolved_from_provider_manifest(tmp_path: Path) -> None:
    project = project_with_beats(tmp_path)
    music = project / "assets/music/freesound_background.mp3"
    music.parent.mkdir(parents=True); music.write_bytes(b"audio")
    write_json(project / "music/MUSIC_SELECTION.json", {"file": "assets/music/freesound_background.mp3"})
    assert music_files(project) == ["assets/music/freesound_background.mp3"]
    node = next(node for node in graph_for(project)["nodes"] if node["id"] == "background_music")
    assert node["artifacts"][0]["path"] == "assets/music/freesound_background.mp3"
    assert node["artifacts"][0]["exists"] is True


def test_music_node_owns_stale_provider_alternatives_too(tmp_path: Path) -> None:
    project = project_with_beats(tmp_path)
    selected = project / "assets/music/freesound_background.mp3"
    alternative = project / "assets/music/mixkit_background.mp3"
    selected.parent.mkdir(parents=True)
    selected.write_bytes(b"selected")
    alternative.write_bytes(b"old alternative")
    write_json(
        project / "music/MUSIC_SELECTION.json",
        {"file": "assets/music/freesound_background.mp3"},
    )

    files = music_files(project)
    assert files == [
        "assets/music/freesound_background.mp3",
        "assets/music/mixkit_background.mp3",
    ]
    paths = invalidation_paths(project, ["background_music"])
    assert "assets/music/freesound_background.mp3" in paths
    assert "assets/music/mixkit_background.mp3" in paths


def test_beat_regeneration_cascades_continuity_but_reuses_independent_audio(tmp_path: Path) -> None:
    project = project_with_beats(tmp_path)
    plan = regeneration_plan(project, ["beat_image_002"])
    assert {"beat_image_002", "beat_image_003", "beat_image_004", "transition_direction", "build_timeline", "render_baseline"} <= set(plan["affected_nodes"])
    assert {"script_draft", "elevenlabs_voiceover", "background_music", "flow_clip_a"} <= set(plan["reused_nodes"])


def test_music_regeneration_does_not_invalidate_timeline_or_motion(tmp_path: Path) -> None:
    project = project_with_beats(tmp_path)
    affected = set(regeneration_plan(project, ["background_music"])["affected_nodes"])
    assert "audio_mix_profile" in affected and "render_baseline" in affected
    assert "build_timeline" not in affected and "motion_director" not in affected


def test_episode_direction_regenerates_its_world_style_and_visual_descendants(tmp_path: Path) -> None:
    project = project_with_beats(tmp_path)
    affected = set(regeneration_plan(project, ["episode_director"])["affected_nodes"])
    assert {
        "episode_director",
        "world_style_director",
        "world_style_anchor",
        "visual_plan",
        "flow_prompt_a",
        "flow_prompt_b",
        "beat_image_001",
        "render_baseline",
    } <= affected


def test_graph_hides_stages_disabled_by_the_frozen_run(tmp_path: Path) -> None:
    project = project_with_beats(tmp_path)
    write_json(
        project / "launch/LAUNCH_REQUEST.json",
        {
            "motion": {"enabled": False},
            "sfx": {"enabled": False},
            "commit_artifacts": False,
            "telegram_low_size": False,
        },
    )
    visible = {node["id"] for node in graph_for(project)["nodes"]}
    assert {
        "motion_director",
        "sfx_plan",
        "sfx_acquire",
        "git_commit_push",
        "telegram_compress",
    }.isdisjoint(visible)
    all_nodes = {node["id"] for node in graph_for(project, include_disabled=True)["nodes"]}
    assert {"motion_director", "sfx_plan", "git_commit_push"} <= all_nodes
    with pytest.raises(ValueError, match="Unknown graph node"):
        regeneration_plan(project, ["motion_director"])
    assert "motion_director" in regeneration_plan(
        project, ["motion_director"], include_disabled=True
    )["affected_nodes"]


def test_invalidation_paths_include_only_existing_owned_files(tmp_path: Path) -> None:
    project = project_with_beats(tmp_path)
    write_json(project / "creative/TRANSITION_PLAN.json", {})
    paths = invalidation_paths(project, regeneration_plan(project, ["beat_image_003"])["affected_nodes"])
    assert "assets/raw_beats/beat_003.png" in paths
    assert "assets/raw_beats/beat_004.png" in paths
    assert "creative/TRANSITION_PLAN.json" in paths
    assert "assets/raw_beats/beat_002.png" not in paths


def test_stale_done_state_is_reported_missing_when_required_artifact_is_absent(tmp_path: Path) -> None:
    project = project_with_beats(tmp_path)
    write_json(project / "pipeline/QH_RUNTIME_STATE.json", {"stages": {"world_keyframe": {"status": "DONE"}}})
    node = next(node for node in graph_for(project)["nodes"] if node["id"] == "world_keyframe")
    assert node["status"] == "MISSING"


def test_zero_byte_required_artifact_is_not_reported_done(tmp_path: Path) -> None:
    project = project_with_beats(tmp_path)
    keyframe = project / "references/world_keyframe.png"
    keyframe.parent.mkdir(parents=True)
    keyframe.touch()
    write_json(
        project / "pipeline/QH_RUNTIME_STATE.json",
        {"stages": {"world_keyframe": {"status": "DONE"}}},
    )
    node = next(
        node for node in graph_for(project)["nodes"] if node["id"] == "world_keyframe"
    )
    assert node["status"] == "MISSING"


def test_generic_content_projects_use_their_real_visual_graph(tmp_path: Path) -> None:
    project = generic_project_with_beats(tmp_path)
    graph = graph_for(project)
    nodes = {node["id"]: node for node in graph["nodes"]}
    assert graph["mode"] == "generic"
    assert "flow_clip_a" not in nodes and "opening_trim" not in nodes
    assert nodes["script_draft"]["artifacts"][0]["path"] == "SCRIPT_DRAFT.md"
    assert nodes["visual_plan"]["status"] == "DONE"
    assert nodes["beat_image_003"]["status"] == "DONE"
    plan = regeneration_plan(project, ["beat_image_002"])
    assert {
        "beat_image_002",
        "beat_image_003",
        "visual_qc",
        "build_timeline",
        "render_baseline",
    } <= set(plan["affected_nodes"])
    assert "elevenlabs_voiceover" in plan["reused_nodes"]
