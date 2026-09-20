from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from run_full_video_pipeline_q_station_wrapper import selected_editing_engine
from run_graph import project_mode
from shorts_v2.artifacts import ArtifactResolver
from shorts_v2.contracts import ContractError, normalize_engine_settings
from shorts_v2.orchestration import ProviderCallSpy, dispatch_plan
from shorts_v2.registry import effective_graph
from shorts_v2.state import FileLease, StageStateStore


def settings(**quality: object) -> dict:
    raw = {
        "_shorts_v2": {
            "editing_engine": "shorts_v2",
            "voice": {"tts_model": "eleven_v3", "voice_id": "voice_mark"},
            "quality": quality,
        }
    }
    return normalize_engine_settings(raw)


def test_effective_graph_is_acyclic_and_alignment_has_no_visual_dependency() -> None:
    graph = effective_graph(settings())
    assert len(graph["order"]) == len(graph["nodes"])
    node = next(item for item in graph["nodes"] if item["id"] == "narration_alignment")
    assert set(node["dependencies"]) == {"elevenlabs_voiceover", "script"}
    assert not {"assets", "asset_manifest", "shot_plan"} & set(node["dependencies"])


def test_review_and_observation_conditions_do_not_orphan_assets_ready() -> None:
    graph = effective_graph(settings(editing_observation="off"))
    ids = {node["id"] for node in graph["nodes"]}
    assert "media_review" not in ids
    assert "asset_observation" not in ids
    assert "assets_ready" in ids
    assert {edge["source"] for edge in graph["edges"] if edge["target"] == "assets_ready"} == {"assets", "opening_media"}
    expanded = effective_graph(settings(editing_observation="off"), include_disabled=True)
    disabled = {node["id"]: node["status"] for node in expanded["nodes"]}
    assert disabled["media_review"] == disabled["asset_observation"] == "SKIPPED_CONFIG"


def test_new_registry_does_not_import_legacy_motion_modules() -> None:
    forbidden = {"run_motion_director", "motion_schema", "motion_v2_schema", "motion_compiler", "motion_context"}
    for relative in ("scripts/shorts_v2/registry.py", "scripts/shorts_v2/orchestration.py", "scripts/shorts_v2/editing.py", "scripts/run_shorts_v2_pipeline.py"):
        tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
        imports = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in (node.names if isinstance(node, ast.Import) else [ast.alias(name=node.module or "")])
        }
        assert not imports & forbidden


def test_dispatch_never_sends_explicit_shorts_v2_to_legacy() -> None:
    raw = {"_shorts_v2": {"editing_engine": "shorts_v2", "voice": {"tts_model": "eleven_v3", "voice_id": "voice_mark"}}}
    plan = dispatch_plan(raw)
    assert plan.entrypoint == "scripts/run_shorts_v2_pipeline.py"
    assert plan.graph is not None
    assert dispatch_plan({}).entrypoint == "scripts/run_full_video_pipeline_q_station_wrapper.py"


def test_wrapper_engine_selection_reads_only_explicit_marker(tmp_path: Path) -> None:
    brief = tmp_path / "brief.json"
    brief.write_text(json.dumps({"_motion": {"enabled": True}}), encoding="utf-8")
    assert selected_editing_engine(brief) == "legacy"
    brief.write_text(json.dumps({"_shorts_v2": {"editing_engine": "shorts_v2", "voice": {"tts_model": "eleven_v3", "voice_id": "voice_mark"}}}), encoding="utf-8")
    assert selected_editing_engine(brief) == "shorts_v2"


def test_qstation_brief_never_dispatches_to_plan_only_shorts_v2(tmp_path: Path) -> None:
    brief = tmp_path / "brief.json"
    brief.write_text(json.dumps({
        "_q_station": {"character": {"mode": "auto"}},
        "_shorts_v2": {"editing_engine": "shorts_v2", "voice": {"tts_model": "eleven_v3", "voice_id": "voice_mark"}},
    }), encoding="utf-8")
    assert selected_editing_engine(brief) == "legacy"


def test_invalid_explicit_marker_never_falls_back_to_legacy(tmp_path: Path) -> None:
    launch = tmp_path / "launch"
    launch.mkdir()
    (launch / "LAUNCH_REQUEST.json").write_text(
        json.dumps({"_shorts_v2": {"editing_engine": "shorts_v2"}}), encoding="utf-8"
    )
    with pytest.raises(ContractError, match="voice"):
        project_mode(tmp_path)


def test_plan_only_entrypoint_writes_effective_graph_without_provider_calls(tmp_path: Path) -> None:
    project = tmp_path / "episode-001"
    launch = project / "launch"
    launch.mkdir(parents=True)
    request = {
        "video_id": "episode-001",
        "_shorts_v2": {
            "editing_engine": "shorts_v2",
            "voice": {
                "tts_model": "eleven_v3",
                "voice_id": "Liam - Energetic, Social Media Creator",
            },
        },
    }
    (launch / "LAUNCH_REQUEST.json").write_text(json.dumps(request), encoding="utf-8")
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/run_shorts_v2_pipeline.py"),
            "--request",
            str(launch / "LAUNCH_REQUEST.json"),
            "--project",
            str(project),
            "--run-id",
            "run-episode-001",
            "--plan-only",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    graph = json.loads((project / "shorts_v2/versions/initial/diagnostics/EFFECTIVE_GRAPH.json").read_text(encoding="utf-8"))
    assert graph["editing_engine"] == "shorts_v2"
    assert graph["order"][0] == "preflight"
    assert not (project / "shorts_v2/versions/initial/audio/TTS_EXECUTION_RECEIPT.json").exists()


def test_artifact_resolver_keeps_every_path_inside_revision(tmp_path: Path) -> None:
    resolver = ArtifactResolver(tmp_path / "episode", "revision-001")
    resolver.ensure_layout()
    assert resolver.resolve("tts_receipt").is_relative_to(resolver.revision_root)
    with pytest.raises(ContractError, match="unsafe"):
        resolver.resolve_relative("../../outside.json")
    with pytest.raises(ContractError, match="unknown logical"):
        resolver.resolve("unknown")


def test_p04_creative_stages_own_their_versioned_artifacts(tmp_path: Path) -> None:
    resolver = ArtifactResolver(tmp_path / "episode", "revision-001")
    graph = effective_graph(settings())
    nodes = {node["id"]: node for node in graph["nodes"]}
    assert set(nodes["evidence"]["owned_artifacts"]) == {"evidence_pack"}
    assert set(nodes["hook"]["owned_artifacts"]) == {"hook_packages", "hook_reviews", "hook_tournament"}
    assert set(nodes["script"]["owned_artifacts"]) == {"story_blueprint", "script_core", "cta", "script_reviews"}
    for logical_name in (*nodes["evidence"]["owned_artifacts"], *nodes["hook"]["owned_artifacts"], *nodes["script"]["owned_artifacts"]):
        assert resolver.resolve(logical_name).is_relative_to(resolver.revision_root)


def test_stage_state_is_resumable_and_rejects_invalid_transitions(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    store = StageStateStore(path, run_id="run-001", revision_id="revision-001")
    store.transition("preflight", "RUNNING")
    store.transition("preflight", "DONE", output_hash="a" * 64)
    resumed = StageStateStore(path, run_id="run-001", revision_id="revision-001")
    assert resumed.data["stages"]["preflight"]["status"] == "DONE"
    with pytest.raises(ContractError, match="invalid stage transition"):
        resumed.transition("script", "DONE")


def test_file_lease_enforces_single_writer_and_increments_epoch(tmp_path: Path) -> None:
    path = tmp_path / "provider.lock"
    first = FileLease(path, "owner-a", "run-001", "revision-001", "attempt-001")
    first.acquire()
    try:
        with pytest.raises(ContractError, match="already held"):
            FileLease(path, "owner-b", "run-002", "revision-002", "attempt-002").acquire()
        assert first.epoch == 1
    finally:
        first.release()
    second = FileLease(path, "owner-b", "run-002", "revision-002", "attempt-002")
    second.acquire()
    try:
        assert second.epoch == 2
    finally:
        second.release()


def test_fake_provider_results_are_explicitly_non_publishable() -> None:
    spy = ProviderCallSpy(fixture_mode=True)
    spy.record(stage="hook", provider="fixture", operation="generate", attempt_id="attempt-001")
    assert spy.fixture_result({"answer": "fixture"})["publishable"] is False
    with pytest.raises(ContractError, match="forbidden"):
        ProviderCallSpy().fixture_result({"answer": "not allowed"})
