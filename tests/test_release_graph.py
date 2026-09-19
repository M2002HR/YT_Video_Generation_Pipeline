from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from release_graph import graph_for, revision_plan, settings_revision_roots  # noqa: E402

SPEC = importlib.util.spec_from_file_location("release_panel_graph_tests", ROOT / "scripts/video_control_panel.py")
assert SPEC and SPEC.loader
panel = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = panel
SPEC.loader.exec_module(panel)


def write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def release_fixture(tmp_path: Path, count: int = 2) -> Path:
    root = tmp_path / ("rel_" + "a" * 32)
    settings = panel.normalize_release_settings({
        "send_telegram": False,
        "thumbnail": {"count_mode": "fixed", "count": count, "max_image_generations": count},
    })
    write(root / "RELEASE_REQUEST.json", {"release_id": root.name, "settings": settings})
    write(root / "RELEASE_STATE.json", {"release_id": root.name, "status": "RUNNING", "master_sha256": "abc", "events": []})
    write(root / "SOURCE_SNAPSHOT.json", {"master_sha256": "abc"})
    return root


def test_release_graph_expands_candidate_branches_and_selected_operations(tmp_path: Path) -> None:
    root = release_fixture(tmp_path, 2)
    graph = graph_for(root)
    ids = [node["id"] for node in graph["nodes"]]
    assert "thumbnail_candidate_01_artwork" in ids
    assert "thumbnail_candidate_02_review" in ids
    assert "telegram_delivery" not in ids
    selection_inputs = {
        edge["source"] for edge in graph["edges"] if edge["target"] == "thumbnail_selection"
    }
    assert selection_inputs == {"thumbnail_candidate_01_review", "thumbnail_candidate_02_review"}
    edges = {(edge["source"], edge["target"]) for edge in graph["edges"]}
    assert ("metadata_finalize", "thumbnail_plan") in edges
    assert ("thumbnail_plan", "thumbnail_candidate_01_artwork") in edges


def test_release_settings_revision_uses_narrow_thumbnail_roots(tmp_path: Path) -> None:
    root = release_fixture(tmp_path, 2)
    old = panel.normalize_release_settings({"send_telegram": False, "thumbnail": {"count": 2, "max_image_generations": 2}})
    qc = json.loads(json.dumps(old)); qc["thumbnail"]["review_enabled"] = False
    assert set(settings_revision_roots(root, old, qc)) == {"thumbnail_candidate_01_review", "thumbnail_candidate_02_review"}
    artwork = json.loads(json.dumps(old)); artwork["thumbnail"]["thumbnail_note"] = "one cracked diving helmet"
    assert settings_revision_roots(root, old, artwork) == ["thumbnail_plan"]


def test_terminal_failure_marks_abandoned_running_checkpoint_failed(tmp_path: Path) -> None:
    root = release_fixture(tmp_path, 1)
    write(root / "RELEASE_STATE.json", {
        "release_id": root.name,
        "status": "FAILED",
        "master_sha256": "abc",
        "events": [{"stage": "metadata_draft", "status": "RUNNING"}],
        "error": "provider changed",
    })
    nodes = {node["id"]: node for node in graph_for(root)["nodes"]}
    assert nodes["metadata_draft"]["status"] == "FAILED"
    assert nodes["release_complete"]["status"] == "FAILED"


def test_one_candidate_revision_preserves_sibling_candidates(tmp_path: Path) -> None:
    root = release_fixture(tmp_path, 3)
    plan = revision_plan(root, ["thumbnail_candidate_02_artwork"])
    assert "thumbnail_candidate_02_compose" in plan["affected_nodes"]
    assert "thumbnail_selection" in plan["affected_nodes"]
    assert "upload_guide" in plan["affected_nodes"]
    assert "thumbnail_candidate_01_artwork" in plan["reused_nodes"]
    assert "thumbnail_candidate_03_review" in plan["reused_nodes"]


def test_release_source_gate_rejects_pending_video_revision(tmp_path: Path) -> None:
    project = tmp_path / "videos/901_ready"
    (project / "pipeline").mkdir(parents=True)
    (project / "render").mkdir()
    (project / "assets/renders").mkdir(parents=True)
    write(project / "pipeline/FINALIZATION_RUNTIME_STATE.json", {"status": "DONE"})
    write(project / "render/QC_REPORT_polished.json", {"passed": True})
    (project / "assets/renders/polished.mp4").write_bytes(b"master")
    allowed, reason = panel.release_eligibility({
        "status": "DONE", "pid": None, "external": False,
        "pending_revision": {"status": "RUNNING"},
    }, project)
    assert allowed is False
    assert "pending revision" in reason


def test_legacy_release_history_is_discovered_and_stale_running_is_interrupted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(panel, "ROOT", tmp_path)
    jobs = tmp_path / "control_panel/jobs"
    jobs.mkdir(parents=True)
    project = tmp_path / "videos/901_legacy"
    release_id = "rel_" + "b" * 32
    write(jobs / ("1" * 8 + "-" + "1" * 4 + "-" + "1" * 4 + "-" + "1" * 4 + "-" + "1" * 12 + ".json"), {
        "job_id": "11111111-1111-1111-1111-111111111111", "video_id": "901", "topic": "Legacy",
        "status": "DONE", "project": "videos/901_legacy", "kind": "episode",
    })
    root = project / "publish/youtube_short/releases" / release_id
    write(root / "RELEASE_STATE.json", {"release_id": release_id, "status": "RUNNING", "started_at": "2026-01-01T00:00:00+00:00", "master_sha256": "old"})
    write(root / "RELEASE_REQUEST.json", {"release_id": release_id, "settings": panel.RELEASE_SETTING_DEFAULTS})
    records = panel.release_records(jobs)
    assert len(records) == 1
    assert records[0]["release_id"] == release_id
    assert records[0]["status"] == "INTERRUPTED"
    assert records[0]["source_job_id"] == "11111111-1111-1111-1111-111111111111"
