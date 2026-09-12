"""The panel's single-page API: status, incremental log tail, and resume (T9.1/T9.2)."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from urllib.parse import urlencode

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from panel_page import launch_form

SPEC = importlib.util.spec_from_file_location("video_control_panel", SCRIPTS / "video_control_panel.py")
assert SPEC and SPEC.loader
panel = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = panel
SPEC.loader.exec_module(panel)


def _record(project: str = "videos/901_panel", **extra) -> dict:
    record = {
        "job_id": "11111111-2222-3333-4444-555555555555",
        "video_id": "901",
        "content_project": "question_harvest",
        "topic": "why panels matter",
        "project": project,
        "creative_brief": f"{project}/launch/CREATIVE_BRIEF.json",
        "voice_profile": f"{project}/voiceover/REQUESTED_VOICE_PROFILE.json",
        "aspect_ratio": "9:16",
        "music_provider": "pixabay",
        "status": "FAILED",
    }
    record.update(extra)
    return record


def test_launch_and_resume_build_the_same_command() -> None:
    """A resume that differs from the launch would produce a different episode (§78)."""
    record = _record()
    command = panel.pipeline_command(record)
    assert command[:3] == [sys.executable, "-u", "scripts/run_full_video_pipeline_qh_wrapper.py"]
    assert "--publish" in command
    assert "--commit" not in command
    assert panel.pipeline_command(record) == command, "the builder must be deterministic"


def test_render_only_config_revision_locks_out_visual_generation_even_on_resume() -> None:
    """Subtitle style edits must never reach Gemini after an isolated beat revision."""
    record = _record(pending_revision={
        "kind": "config",
        "roots": ["render_profile"],
    })
    command = panel.pipeline_command(record)
    assert "--skip-visual-stages" in command
    assert panel.config_revision_skips_qh_visual_stages(record["pending_revision"]) is True

    visual = _record(pending_revision={
        "kind": "config",
        "roots": ["beat_image_001"],
    })
    assert "--skip-visual-stages" not in panel.pipeline_command(visual)
    assert panel.config_revision_skips_qh_visual_stages(visual["pending_revision"]) is False


def test_style_reference_is_hash_pinned_and_frozen_inside_the_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An upload token must never leak into the launch brief or point outside its run."""
    from PIL import Image

    monkeypatch.setattr(panel, "ROOT", tmp_path)
    upload_id = "a" * 32
    uploads = tmp_path / "control_panel" / "style_reference_uploads"
    uploads.mkdir(parents=True)
    source = uploads / f"{upload_id}.png"
    Image.new("RGB", (160, 160), "navy").save(source)
    panel.write_json(uploads / f"{upload_id}.json", {
        "sha256": panel.sha256_path(source), "width": 160, "height": 160,
    })
    project = tmp_path / "videos" / "001_reference"
    brief = {"_qh": {"_style_reference_upload_id": upload_id}}

    panel.freeze_style_reference(brief, project, project / "launch" / "style_references")

    reference = brief["_qh"]["world_style_reference"]
    assert "_style_reference_upload_id" not in brief["_qh"]
    assert reference["path"] == "videos/001_reference/launch/style_references/style_reference.png"
    assert reference["sha256"] == panel.sha256_path(tmp_path / reference["path"])


def test_logo_upload_is_normalized_with_alpha_and_frozen_inside_the_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A logo upload becomes a hash-pinned run asset, never a global root file."""
    from PIL import Image

    monkeypatch.setattr(panel, "ROOT", tmp_path)
    upload_id = "c" * 32
    uploads = tmp_path / "control_panel" / "logo_uploads"
    uploads.mkdir(parents=True)
    source = uploads / f"{upload_id}.png"
    Image.new("RGBA", (96, 64), (12, 34, 56, 127)).save(source)
    panel.write_json(uploads / f"{upload_id}.json", {
        "sha256": panel.sha256_path(source), "width": 96, "height": 64,
    })
    project = tmp_path / "videos" / "001_logo"
    brief = {"_branding": {"show_logo": True, "_logo_upload_id": upload_id}}

    panel.freeze_logo_asset(brief, project, project / "launch" / "branding")

    asset = brief["_branding"]["logo_asset"]
    frozen = tmp_path / asset["path"]
    assert "_logo_upload_id" not in brief["_branding"]
    assert asset["path"] == "videos/001_logo/launch/branding/logo.png"
    assert asset["sha256"] == panel.sha256_path(frozen)
    with Image.open(frozen) as image:
        assert image.mode == "RGBA"
        assert image.getpixel((0, 0))[3] == 127


def test_branding_revision_requires_an_uploaded_or_frozen_logo() -> None:
    record = _record()
    brief = {"_branding": {"show_logo": False}}
    voice = {}
    values = panel.frozen_values(record, brief, voice)
    values["show_logo"] = True

    with pytest.raises(ValueError, match="Upload a logo"):
        panel.config_roots(record, brief, voice, values)


def test_hash_verified_uploaded_subtitle_font_is_available_to_both_panel_forms(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The runtime schema is the shared source for launch and Revise font choices."""
    monkeypatch.setattr(panel, "ROOT", tmp_path)
    font_id = "b" * 32
    folder = tmp_path / "control_panel" / "subtitle_fonts"; folder.mkdir(parents=True)
    font = folder / f"{font_id}.ttf"; font.write_bytes(b"operator-owned-font")
    panel.write_json(folder / "catalog.json", {"schema_version": 1, "fonts": [{
        "id": font_id, "family": "Operator Sans", "extension": ".ttf",
        "sha256": panel.sha256_path(font), "created_at": "2026-01-01T00:00:00+00:00",
    }]})

    custom = panel.custom_subtitle_fonts()
    assert custom == [{
        "id": font_id, "family": "Operator Sans", "extension": ".ttf",
        "sha256": panel.sha256_path(font), "mime_type": "font/ttf", "created_at": "2026-01-01T00:00:00+00:00",
    }]
    assert "Operator Sans" in panel.available_subtitle_font_families()
    schema = panel.studio_schema()
    subtitle = next(group for group in schema["groups"] if group["id"] == "subtitles")
    choice = next(field for field in subtitle["fields"] if field["name"] == "subtitle_font")
    assert {"value": "Operator Sans", "label": "Operator Sans · Uploaded", "uploaded": True, "font_url": f"/api/fonts/custom-{font_id}"} in choice["options"]
    assert panel.custom_font_for_slug(f"custom-{font_id}")["family"] == "Operator Sans"


def test_launch_form_exposes_the_word_highlight_choice() -> None:
    form = launch_form("", "")
    assert 'name=word_highlight checked' in form
    assert "Highlight the spoken word" in form
    assert 'name=telegram_low_size checked' in form
    assert 'name=telegram_original' in form
    assert 'name=reserve_subtitle_space checked' in form
    assert 'name=sfx_enabled' in form
    assert 'name=sfx_license_policy' in form
    assert 'name=motion_enabled' in form
    assert 'name=motion_image_zoom_strength' in form
    assert 'name=motion_image_transition_style' in form
    assert 'name=motion_image_transition_seconds' in form
    assert 'name=motion_opening_to_image_seconds' in form
    assert 'name=motion_pace' in form
    assert 'name=motion_max_micro_shots' in form
    assert 'name=motion_planning_quality' in form
    assert 'name=motion_normal_max_zoom' in form
    assert 'name=motion_editorial_critic' in form
    assert 'name=motion_debug_preview' in form
    assert 'name=motion_neighbor_context' in form
    assert 'name=motion_word_sync_tolerance' in form
    assert 'name=motion_face_padding' in form
    assert 'id=motion_enabled' in form
    assert 'id=motion_controls' in form
    assert 'syncMotionControls()' in form
    assert 'name=motion_allow_drift' in form
    assert 'name=motion_allow_settle' in form
    assert 'name=motion_allow_reveal_move' in form
    assert 'name=motion_allow_match_position_cuts' in form
    assert 'name=motion_allow_decorative_transitions' in form
    assert "Existing Motion Plan artifacts are ignored" in form
    assert 'FREESOUND_API_KEY' not in form


def test_the_commit_flag_is_carried_into_the_command() -> None:
    assert "--commit" in panel.pipeline_command(_record(commit_artifacts=True))


def test_telegram_delivery_preferences_survive_into_a_resume() -> None:
    command = panel.pipeline_command(_record(telegram_low_size=False, telegram_original=True))
    assert "--no-telegram-low-size" in command
    assert "--telegram-original" in command


def test_the_music_provider_priority_survives_into_a_resume() -> None:
    command = panel.pipeline_command(_record(music_providers=["mixkit", "pixabay"]))
    assert command[command.index("--music-providers") + 1] == "mixkit,pixabay"


def test_music_provider_priority_requires_unique_supported_values() -> None:
    assert panel.music_provider_priority("pixabay,mixkit") == ["pixabay", "mixkit"]
    with pytest.raises(ValueError, match="duplicates"):
        panel.music_provider_priority("mixkit,mixkit")


def test_a_non_question_harvest_project_uses_the_generic_pipeline() -> None:
    command = panel.pipeline_command(
        _record(content_project="world_behind_the_question", duration_min_seconds=30, duration_max_seconds=45)
    )
    assert "scripts/run_full_video_pipeline.py" in command
    assert command[command.index("--min-duration-seconds") + 1] == "30"


def test_provider_status_reports_unreachable_rather_than_healthy(monkeypatch: pytest.MonkeyPatch) -> None:
    """A panel that shows green while Ordak is down would invite a doomed launch."""
    monkeypatch.setattr(panel, "ORDAK_BASE_URL", "http://127.0.0.1:1")
    status = panel.provider_status()
    assert status["reachable"] is False
    assert status["chrome_running"] is None
    assert set(status["providers"]) == set(panel.PROVIDERS)
    assert all(entry["logged_in"] is None for entry in status["providers"].values())


def test_pipeline_state_is_read_from_the_orchestrator_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(panel, "ROOT", tmp_path)
    project = tmp_path / "videos" / "901_panel"
    (project / "pipeline").mkdir(parents=True)
    (project / "pipeline" / "QH_RUNTIME_STATE.json").write_text(
        json.dumps(
            {
                "pipeline_state": "RUNNING",
                "stages": {
                    "script": {"status": "DONE"},
                    "world_keyframe": {"status": "REUSED"},
                    "flow_clip_a": {"status": "RUNNING"},
                    "flow_clip_b": {"status": "PENDING"},
                },
            }
        ),
        encoding="utf-8",
    )
    (project / "references").mkdir()
    (project / "references" / "world_keyframe.png").write_bytes(b"valid artifact")

    state = panel.pipeline_state_of({"project": "videos/901_panel"})
    assert state["pipeline_state"] == "RUNNING"
    assert state["running"] == "flow_clip_a"
    assert state["done"] == 0  # A file without a receipt is visible, but not validated.
    assert state["stage_count"] > 20, "progress uses the canonical whole-pipeline graph, not only keys emitted so far"


def test_a_project_without_state_reports_nothing_rather_than_guessing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(panel, "ROOT", tmp_path)
    assert panel.pipeline_state_of({"project": "videos/does_not_exist"}) == {}
    assert panel.pipeline_state_of({}) == {}


def test_job_records_marks_finished_runs_resumable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(panel, "ROOT", tmp_path)
    jobs = tmp_path / "control_panel" / "jobs"
    jobs.mkdir(parents=True)
    (jobs / "a.json").write_text(json.dumps(_record(status="FAILED", pid=101)), encoding="utf-8")
    (jobs / "b.json").write_text(json.dumps(_record(status="RUNNING", pid=202)), encoding="utf-8")
    (jobs / "c.json").write_text("{not json", encoding="utf-8")
    # Resumability follows whether the process is actually alive, not the recorded label:
    # a RUNNING row whose pid is gone is exactly what needs resuming.
    monkeypatch.setattr(panel, "pid_is_live", lambda pid: pid == 202)

    records = panel.job_records(jobs)
    assert len(records) == 2, "an unreadable record is skipped, not fatal"
    by_status = {record["status"]: record["_resumable"] for record in records}
    assert by_status == {"FAILED": True, "RUNNING": False}
    stoppable = {record["status"]: record["_stoppable"] for record in records}
    assert stoppable == {"FAILED": False, "RUNNING": True}


def test_a_running_row_whose_process_died_can_be_resumed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(panel, "ROOT", tmp_path)
    jobs = tmp_path / "control_panel" / "jobs"
    jobs.mkdir(parents=True)
    (jobs / "a.json").write_text(json.dumps(_record(status="RUNNING", pid=303)), encoding="utf-8")
    monkeypatch.setattr(panel, "pid_is_live", lambda pid: False)

    record = panel.job_records(jobs)[0]
    assert record["_resumable"] is True
    assert record["_stoppable"] is False


def test_stopping_a_revision_updates_its_durable_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(panel, "ROOT", tmp_path)
    jobs = tmp_path / "control_panel/jobs"; jobs.mkdir(parents=True)
    project = tmp_path / "videos/901_panel"
    revision_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    pending = {"revision_id": revision_id, "status": "RUNNING", "roots": ["background_music"]}
    record = _record(status="RUNNING", pid=9999, pending_revision=pending)
    (jobs / f"{record['job_id']}.json").write_text(json.dumps(record), encoding="utf-8")
    request_path = project / "launch/LAUNCH_REQUEST.json"
    request_path.parent.mkdir(parents=True); request_path.write_text(json.dumps(record), encoding="utf-8")
    revision_path = project / f"pipeline/revisions/{revision_id}/REVISION.json"
    revision_path.parent.mkdir(parents=True); revision_path.write_text(json.dumps(pending), encoding="utf-8")
    body = urlencode({"job_id": record["job_id"]}).encode()
    monkeypatch.setattr(panel, "terminate_job", lambda job: True)

    class StopHandler(_Handler):
        def __init__(self):
            super().__init__(jobs)
            self.headers = {"Content-Length": str(len(body)), "Accept": "application/json"}
            self.rfile = io.BytesIO(body)
            self.response = None

        def send_json(self, status, value):
            self.response = (status, value)

    handler = StopHandler()
    handler.handle_stop()

    assert handler.response[0] == 202
    assert json.loads(revision_path.read_text())["status"] == "STOPPED"
    assert json.loads(request_path.read_text())["status"] == "STOPPED"


def test_reconciler_records_failed_revision_for_safe_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(panel, "ROOT", tmp_path)
    jobs = tmp_path / "control_panel/jobs"; jobs.mkdir(parents=True)
    revision_id = "aaaaaaaa-bbbb-cccc-dddd-ffffffffffff"
    pending = {"revision_id": revision_id, "status": "RUNNING", "roots": ["background_music"]}
    record = _record(status="RUNNING", pid=999_999_999, exit_code=2, pending_revision=pending)
    record_path = jobs / f"{record['job_id']}.json"
    record_path.write_text(json.dumps(record), encoding="utf-8")
    revision_path = tmp_path / record["project"] / f"pipeline/revisions/{revision_id}/REVISION.json"
    revision_path.parent.mkdir(parents=True)
    revision_path.write_text(json.dumps(pending), encoding="utf-8")

    panel.reconcile_stuck_jobs_once()

    saved = json.loads(record_path.read_text())
    assert saved["status"] == "FAILED"
    assert saved["pending_revision"]["status"] == "FAILED"
    assert json.loads(revision_path.read_text())["status"] == "FAILED"


def test_reconciler_completes_and_clears_a_successful_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(panel, "ROOT", tmp_path)
    jobs = tmp_path / "control_panel/jobs"; jobs.mkdir(parents=True)
    revision_id = "aaaaaaaa-bbbb-cccc-dddd-111111111111"
    pending = {"revision_id": revision_id, "status": "RUNNING", "roots": ["background_music"]}
    record = _record(
        status="RUNNING",
        pid=999_999_999,
        exit_code=0,
        pending_revision=pending,
        last_config_revision={**pending, "config_revision_id": "config-input-id"},
    )
    record_path = jobs / f"{record['job_id']}.json"
    record_path.write_text(json.dumps(record), encoding="utf-8")
    (jobs / f"{record['job_id']}.log").write_text("FULL QH PIPELINE: PASS\n", encoding="utf-8")
    project = tmp_path / record["project"]
    revision_path = project / f"pipeline/revisions/{revision_id}/REVISION.json"
    revision_path.parent.mkdir(parents=True)
    revision_path.write_text(json.dumps(pending), encoding="utf-8")
    (project / "assets/renders").mkdir(parents=True)
    (project / "assets/renders/polished.mp4").write_bytes(b"video")
    (project / "render").mkdir()
    (project / "render/QC_REPORT_polished.json").write_text("{}", encoding="utf-8")
    (project / "pipeline/FINALIZATION_RUNTIME_STATE.json").write_text(
        json.dumps({"status": "DONE"}), encoding="utf-8"
    )

    panel.reconcile_stuck_jobs_once()

    saved = json.loads(record_path.read_text())
    assert saved["status"] == "DONE"
    assert "pending_revision" not in saved
    assert json.loads(revision_path.read_text())["status"] == "DONE"
    assert saved["last_config_revision"]["status"] == "DONE"
    assert saved["last_config_revision"]["completed_at"] == saved["completed_at"]


class _Handler(panel.Handler):
    """Only log_tail is exercised, so the socket machinery is deliberately not built."""

    def __init__(self, jobs_dir: Path) -> None:  # noqa: D107 - test double
        self._jobs_dir = jobs_dir

    @property
    def jobs_dir(self) -> Path:
        return self._jobs_dir


def test_the_log_tail_is_incremental(tmp_path: Path) -> None:
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    job_id = "11111111-2222-3333-4444-555555555555"
    log = jobs / f"{job_id}.log"
    log.write_text("first line\n", encoding="utf-8")
    handler = _Handler(jobs)

    first = handler.log_tail(job_id, 0)
    assert first["text"] == "first line\n" and first["offset"] == log.stat().st_size

    with log.open("a", encoding="utf-8") as handle:
        handle.write("second line\n")
    second = handler.log_tail(job_id, first["offset"])
    assert second["text"] == "second line\n", "only the new bytes come back"
    assert handler.log_tail(job_id, second["offset"])["text"] == ""


def test_a_missing_log_reports_waiting(tmp_path: Path) -> None:
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    tail = _Handler(jobs).log_tail("11111111-2222-3333-4444-555555555555", 0)
    assert tail == {"offset": 0, "text": "", "waiting": True}


def test_delete_archives_bookkeeping_and_keeps_the_project_hidden(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(panel, "ROOT", tmp_path)
    jobs = tmp_path / "control_panel/jobs"; jobs.mkdir(parents=True)
    project = tmp_path / "videos/901_panel"
    state = project / "pipeline/QH_RUNTIME_STATE.json"
    state.parent.mkdir(parents=True)
    state.write_text(json.dumps({"pipeline_state": "FAILED", "video_id": "901"}), encoding="utf-8")
    record = _record(status="FAILED")
    record_path = jobs / f"{record['job_id']}.json"
    log_path = jobs / f"{record['job_id']}.log"
    record_path.write_text(json.dumps(record), encoding="utf-8")
    log_path.write_text("diagnostic log", encoding="utf-8")
    body = urlencode({"job_id": record["job_id"]}).encode()

    class DeleteHandler(_Handler):
        def __init__(self):
            super().__init__(jobs)
            self.headers = {"Content-Length": str(len(body)), "Accept": "application/json"}
            self.rfile = io.BytesIO(body)
            self.response = None

        def send_json(self, status, value):
            self.response = (status, value)

    handler = DeleteHandler()
    handler.handle_delete()

    assert handler.response[0] == 202
    assert not record_path.exists() and not log_path.exists()
    assert (jobs / "archived" / record_path.name).is_file()
    assert (jobs / "archived" / log_path.name).is_file()
    assert panel.job_records(jobs) == []
    assert state.is_file(), "archiving panel history never removes project artifacts"


def test_a_far_behind_reader_gets_the_tail_not_the_whole_file(tmp_path: Path) -> None:
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    job_id = "11111111-2222-3333-4444-555555555555"
    (jobs / f"{job_id}.log").write_text("x" * 500_000, encoding="utf-8")
    tail = _Handler(jobs).log_tail(job_id, 0)
    assert len(tail["text"]) == 200_000
    assert tail["offset"] == 500_000


def test_regeneration_archives_only_the_affected_branch_and_records_reuse(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(panel, "ROOT", tmp_path)
    jobs = tmp_path / "control_panel/jobs"; jobs.mkdir(parents=True)
    project = tmp_path / "videos/901_panel"
    (project / "creative").mkdir(parents=True)
    (project / "creative/VISUAL_PLAN.json").write_text(json.dumps({"beats": [{"beat_id": 1}, {"beat_id": 2}, {"beat_id": 3}]}), encoding="utf-8")
    for number in range(1, 4):
        target = project / f"assets/raw_beats/beat_{number:03d}.png"; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(b"image")
    (project / "creative/TRANSITION_PLAN.json").write_text("{}", encoding="utf-8")
    brief = project / "launch/CREATIVE_BRIEF.json"; brief.parent.mkdir(parents=True); brief.write_text("{}", encoding="utf-8")
    voice = project / "voiceover/REQUESTED_VOICE_PROFILE.json"; voice.parent.mkdir(parents=True); voice.write_text("{}", encoding="utf-8")
    record = _record(project="videos/901_panel", creative_brief="videos/901_panel/launch/CREATIVE_BRIEF.json", voice_profile="videos/901_panel/voiceover/REQUESTED_VOICE_PROFILE.json")

    class Process:
        pid = 4242
    monkeypatch.setattr(panel.subprocess, "Popen", lambda *args, **kwargs: Process())
    handler = _Handler(jobs)
    revision, process = handler.start_regeneration(record, project, ["beat_image_002"], "make it calmer")

    assert process.pid == 4242
    assert (project / "assets/raw_beats/beat_001.png").is_file()
    assert not (project / "assets/raw_beats/beat_002.png").exists()
    assert not (project / "assets/raw_beats/beat_003.png").exists()
    assert "beat_image_001" in revision["reused_nodes"]
    assert {"beat_image_002", "beat_image_003", "transition_direction"} <= set(revision["affected_nodes"])
    assert revision["regenerate_beats"] == [2], "later continuity beats rebuild from archived files, not stale explicit IDs"
    revision_dir = project / "pipeline/revisions" / revision["revision_id"]
    assert (revision_dir / "previous/assets/raw_beats/beat_002.png").is_file()
    assert json.loads((revision_dir / "feedback.json").read_text())["2"] == "make it calmer"


def test_isolated_beat_revision_keeps_other_images_and_sets_runtime_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(panel, "ROOT", tmp_path)
    jobs = tmp_path / "control_panel/jobs"; jobs.mkdir(parents=True)
    project = tmp_path / "videos/901_panel"
    (project / "creative").mkdir(parents=True)
    (project / "creative/VISUAL_PLAN.json").write_text(
        json.dumps({"beats": [{"beat_id": 1}, {"beat_id": 2}, {"beat_id": 3}]}),
        encoding="utf-8",
    )
    for number in range(1, 4):
        image = project / f"assets/raw_beats/beat_{number:03d}.png"
        image.parent.mkdir(parents=True, exist_ok=True); image.write_bytes(b"image")
    (project / "creative/TRANSITION_PLAN.json").write_text("{}", encoding="utf-8")
    brief = project / "launch/CREATIVE_BRIEF.json"; brief.parent.mkdir(parents=True); brief.write_text("{}", encoding="utf-8")
    voice = project / "voiceover/REQUESTED_VOICE_PROFILE.json"; voice.parent.mkdir(parents=True); voice.write_text("{}", encoding="utf-8")
    record = _record(project="videos/901_panel", creative_brief="videos/901_panel/launch/CREATIVE_BRIEF.json", voice_profile="videos/901_panel/voiceover/REQUESTED_VOICE_PROFILE.json")

    class Process:
        pid = 4343
    monkeypatch.setattr(panel.subprocess, "Popen", lambda *args, **kwargs: Process())
    revision, _ = _Handler(jobs).start_regeneration(
        record, project, ["beat_image_002"], "make the subject face left",
        regeneration_mode="isolated",
    )

    assert (project / "assets/raw_beats/beat_001.png").is_file()
    assert not (project / "assets/raw_beats/beat_002.png").exists()
    assert (project / "assets/raw_beats/beat_003.png").is_file()
    assert revision["regeneration_mode"] == "isolated"
    assert "beat_image_003" in revision["reused_nodes"]
    command = json.loads((jobs / f"{record['job_id']}.json").read_text())["command"]
    assert "--preserve-downstream-beats" in command


def test_chatgpt_feedback_revision_archives_source_and_forwards_one_shot_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(panel, "ROOT", tmp_path)
    jobs = tmp_path / "control_panel/jobs"; jobs.mkdir(parents=True)
    project = tmp_path / "videos/901_panel"
    (project / "creative").mkdir(parents=True)
    (project / "creative/VISUAL_PLAN.json").write_text(
        json.dumps({"beats": [{"beat_id": 1}, {"beat_id": 2}]}), encoding="utf-8"
    )
    for number in (1, 2):
        image = project / f"assets/raw_beats/beat_{number:03d}.png"
        image.parent.mkdir(parents=True, exist_ok=True); image.write_bytes(f"image-{number}".encode())
    (project / "creative/TRANSITION_PLAN.json").write_text("{}", encoding="utf-8")
    brief = project / "launch/CREATIVE_BRIEF.json"; brief.parent.mkdir(parents=True); brief.write_text("{}", encoding="utf-8")
    voice = project / "voiceover/REQUESTED_VOICE_PROFILE.json"; voice.parent.mkdir(parents=True); voice.write_text("{}", encoding="utf-8")
    record = _record(project="videos/901_panel")

    class Process:
        pid = 4545

    monkeypatch.setattr(panel.subprocess, "Popen", lambda *args, **kwargs: Process())
    revision, _ = _Handler(jobs).start_regeneration(
        record, project, ["beat_image_002"], "remove the distracting object",
        use_chatgpt_feedback=True,
    )

    request_path = tmp_path / revision["chatgpt_feedback_path"]
    request = json.loads(request_path.read_text(encoding="utf-8"))["2"]
    source = project / request["source_image"]
    assert source.read_bytes() == b"image-2"
    assert request["instruction"] == "remove the distracting object"
    assert revision["use_chatgpt_feedback"] is True
    command = json.loads((jobs / f"{record['job_id']}.json").read_text())["command"]
    assert command[command.index("--chatgpt-revision-feedback-json") + 1] == str(request_path)


def test_regeneration_rolls_back_artifacts_and_state_when_spawn_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(panel, "ROOT", tmp_path)
    jobs = tmp_path / "control_panel/jobs"; jobs.mkdir(parents=True)
    project = tmp_path / "videos/901_panel"
    (project / "creative").mkdir(parents=True)
    (project / "creative/VISUAL_PLAN.json").write_text(
        json.dumps({"beats": [{"beat_id": 1}]}), encoding="utf-8"
    )
    image = project / "assets/raw_beats/beat_001.png"
    image.parent.mkdir(parents=True); image.write_bytes(b"original image")
    state_path = project / "pipeline/QH_RUNTIME_STATE.json"
    state_path.parent.mkdir(parents=True)
    original_state = {"stages": {"beat_image_001": {"status": "DONE"}}}
    state_path.write_text(json.dumps(original_state), encoding="utf-8")
    brief = project / "launch/CREATIVE_BRIEF.json"
    brief.parent.mkdir(parents=True); brief.write_text("{}", encoding="utf-8")
    voice = project / "voiceover/REQUESTED_VOICE_PROFILE.json"
    voice.parent.mkdir(parents=True); voice.write_text("{}", encoding="utf-8")
    record = _record()

    def fail_to_spawn(*args, **kwargs):
        raise OSError("runner unavailable")

    monkeypatch.setattr(panel.subprocess, "Popen", fail_to_spawn)
    with pytest.raises(OSError, match="runner unavailable"):
        _Handler(jobs).start_regeneration(record, project, ["beat_image_001"])

    assert image.read_bytes() == b"original image"
    assert json.loads(state_path.read_text()) == original_state
    manifests = list((project / "pipeline/revisions").glob("*/REVISION.json"))
    assert len(manifests) == 1
    failed = json.loads(manifests[0].read_text())
    assert failed["status"] == "FAILED_TO_START"
    assert "runner unavailable" in failed["error"]


def test_generic_run_regeneration_uses_its_visual_state_and_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(panel, "ROOT", tmp_path)
    jobs = tmp_path / "control_panel/jobs"; jobs.mkdir(parents=True)
    project = tmp_path / "videos/901_panel"
    launch = {"content_project": "default", "motion": {"enabled": False}, "sfx": {"enabled": False}, "commit_artifacts": False, "telegram_low_size": True}
    launch_path = project / "launch/LAUNCH_REQUEST.json"
    launch_path.parent.mkdir(parents=True); launch_path.write_text(json.dumps(launch), encoding="utf-8")
    visual_state = {
        "stages": {"visual_beats": {"status": "DONE"}},
        "beats": {f"{number:03d}": {"status": "DONE"} for number in range(1, 4)},
    }
    visual_state_path = project / "visual_pipeline/RUNTIME_STATE.json"
    visual_state_path.parent.mkdir(parents=True); visual_state_path.write_text(json.dumps(visual_state), encoding="utf-8")
    (project / "VISUAL_BEATS.md").write_text("beats", encoding="utf-8")
    for number in range(1, 4):
        image = project / f"assets/raw_beats/beat_{number:03d}.png"
        image.parent.mkdir(parents=True, exist_ok=True); image.write_bytes(b"image")
        prompt = project / f"beats/BEAT_{number:03d}_PROMPT.md"
        prompt.parent.mkdir(parents=True, exist_ok=True); prompt.write_text("prompt", encoding="utf-8")
    report = project / "visual_pipeline/VISUAL_QC_REPORT.json"
    report.write_text("{}", encoding="utf-8")
    brief = project / "launch/CREATIVE_BRIEF.json"; brief.write_text("{}", encoding="utf-8")
    voice = project / "voiceover/REQUESTED_VOICE_PROFILE.json"
    voice.parent.mkdir(parents=True); voice.write_text("{}", encoding="utf-8")
    record = _record(
        content_project="default",
        creative_brief="videos/901_panel/launch/CREATIVE_BRIEF.json",
        voice_profile="videos/901_panel/voiceover/REQUESTED_VOICE_PROFILE.json",
        motion={"enabled": False},
        sfx={"enabled": False},
        commit_artifacts=False,
        telegram_low_size=True,
    )

    class Process:
        pid = 6363

    monkeypatch.setattr(panel.subprocess, "Popen", lambda *args, **kwargs: Process())
    revision, _ = _Handler(jobs).start_regeneration(
        record, project, ["beat_image_002"], "use warmer light"
    )

    folder = project / "pipeline/revisions" / revision["revision_id"] / "previous"
    assert (folder / "assets/raw_beats/beat_002.png").is_file()
    assert (folder / "assets/raw_beats/beat_003.png").is_file()
    assert (folder / "visual_pipeline/VISUAL_QC_REPORT.json").is_file()
    assert (project / "assets/raw_beats/beat_001.png").is_file()
    saved_state = json.loads(visual_state_path.read_text())
    assert set(saved_state["beats"]) == {"001"}
    command = json.loads((jobs / f"{record['job_id']}.json").read_text())["command"]
    assert "scripts/run_full_video_pipeline.py" in command
    assert command[command.index("--regenerate-beats") + 1] == "2"
    assert "--beat-feedback-json" in command


def test_config_revision_updates_the_frozen_runtime_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(panel, "ROOT", tmp_path)
    jobs = tmp_path / "control_panel/jobs"; jobs.mkdir(parents=True)
    project = tmp_path / "videos/901_panel"
    old_brief = {"audience": "adults", "_qh": {"show_subtitles": False}, "_motion": {"enabled": False}, "_sfx": {"enabled": False}, "_subtitle": {"word_highlight": True}}
    brief_path = project / "launch/CREATIVE_BRIEF.json"
    brief_path.parent.mkdir(parents=True); brief_path.write_text(json.dumps(old_brief), encoding="utf-8")
    voice_value = {"voice": "Mark - Natural Conversations"}
    voice_path = project / "voiceover/REQUESTED_VOICE_PROFILE.json"
    voice_path.parent.mkdir(parents=True); voice_path.write_text(json.dumps(voice_value), encoding="utf-8")
    record = _record(
        status="FAILED",
        motion={"enabled": False},
        sfx={"enabled": False},
        subtitles=False,
        word_highlight=True,
        music_providers=["pixabay"],
        commit_artifacts=False,
        telegram_low_size=True,
        telegram_original=False,
    )
    (jobs / f"{record['job_id']}.json").write_text(json.dumps(record), encoding="utf-8")
    new_brief = json.loads(json.dumps(old_brief))
    new_brief["_motion"] = {"enabled": True, "style": "dynamic"}
    payload = json.dumps({
        "job_id": record["job_id"],
        "config": {
            "creative_brief": new_brief,
            "voice_profile": voice_value,
            "launch": {
                "music_provider": "pixabay",
                "music_providers": ["pixabay"],
                "aspect_ratio": "9:16",
                "commit_artifacts": False,
                "telegram_low_size": True,
                "telegram_original": False,
            },
        },
    }).encode()

    class Process:
        pid = 6262

    monkeypatch.setattr(panel.subprocess, "Popen", lambda *args, **kwargs: Process())

    class ConfigHandler(_Handler):
        def __init__(self):
            super().__init__(jobs)
            self.headers = {"Content-Length": str(len(payload))}
            self.rfile = io.BytesIO(payload)
            self.response = None

        def send_json(self, status, value):
            self.response = (status, value)

    handler = ConfigHandler()
    handler.handle_config_revision()

    assert handler.response[0] == 202
    revision = handler.response[1]["revision"]
    assert "motion_director" in revision["roots"]
    assert "sfx_acquire" in revision["skipped_nodes"]
    assert "git_commit_push" in revision["skipped_nodes"]
    saved = json.loads((jobs / f"{record['job_id']}.json").read_text())
    assert saved["motion"] == {"enabled": True, "style": "dynamic"}
    frozen = json.loads((project / "launch/LAUNCH_REQUEST.json").read_text())
    assert frozen["creative_brief"].endswith("CREATIVE_BRIEF.json")
    assert frozen["pending_revision"]["revision_id"] == revision["revision_id"]


def test_structured_config_revision_maps_caption_layout_to_body_images() -> None:
    record = _record(
        music_providers=["pixabay"], telegram_low_size=True, telegram_original=False,
        commit_artifacts=False, motion={"enabled": False}, sfx={"enabled": False},
    )
    brief = {
        "_qh": {"reserve_subtitle_space": True, "show_subtitles": False},
        "_motion": {"enabled": False}, "_sfx": {"enabled": False},
        "_subtitle": {"word_highlight": True},
    }
    voice = {"voice": "Mark - Natural Conversations", "model": "Eleven Multilingual v2"}
    values = panel.frozen_values(record, brief, voice)
    values["reserve_subtitle_space"] = False

    roots, revised_brief, _voice, _launch, changed = panel.config_roots(
        record, brief, voice, values
    )

    assert roots == {"beat_image_001"}
    assert revised_brief["_qh"]["reserve_subtitle_space"] is False
    assert changed == ["reserve_subtitle_space"]


def test_structured_config_revision_persists_opening_speed_tolerance() -> None:
    """Trim-only tolerance must reach the brief without invalidating any stage."""
    record = _record(
        music_providers=["pixabay"], telegram_low_size=True, telegram_original=False,
        commit_artifacts=False, motion={"enabled": False}, sfx={"enabled": False},
    )
    brief = {
        "_qh": {"opening_speed_tolerance": 0.1},
        "_motion": {"enabled": False}, "_sfx": {"enabled": False},
        "_subtitle": {"word_highlight": True},
    }
    voice = {"voice": "Mark - Natural Conversations", "model": "Eleven Multilingual v2"}
    values = panel.frozen_values(record, brief, voice)
    assert values["opening_speed_tolerance"] == 0.1
    values["opening_speed_tolerance"] = 0.2

    roots, revised_brief, _voice, _launch, changed = panel.config_roots(
        record, brief, voice, values
    )

    assert roots == set()
    assert revised_brief["_qh"]["opening_speed_tolerance"] == 0.2
    assert changed == ["opening_speed_tolerance"]


def test_topic_change_from_revision_launches_a_separate_clean_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A new subject must not inherit the source run's project or runtime state."""
    monkeypatch.setattr(panel, "ROOT", tmp_path)
    (tmp_path / "videos").mkdir()
    jobs = tmp_path / "control_panel/jobs"; jobs.mkdir(parents=True)
    project = tmp_path / "videos/901_panel"
    brief = {
        "_qh": {"show_subtitles": False, "character": {"mode": "auto"}},
        "_motion": {"enabled": False}, "_sfx": {"enabled": False},
        "_subtitle": {"word_highlight": True},
    }
    voice = {"voice": "Mark - Natural Conversations", "model": "Eleven Multilingual v2"}
    brief_path = project / "launch/CREATIVE_BRIEF.json"; brief_path.parent.mkdir(parents=True)
    brief_path.write_text(json.dumps(brief), encoding="utf-8")
    voice_path = project / "voiceover/REQUESTED_VOICE_PROFILE.json"; voice_path.parent.mkdir(parents=True)
    voice_path.write_text(json.dumps(voice), encoding="utf-8")
    # A source artifact makes it explicit that the new workspace must not reuse it.
    source_artifact = project / "pipeline/QH_RUNTIME_STATE.json"; source_artifact.parent.mkdir(parents=True)
    source_artifact.write_text(json.dumps({"topic": "why panels matter"}), encoding="utf-8")
    record = _record(
        status="FAILED", music_providers=["pixabay"], commit_artifacts=False,
        telegram_low_size=True, telegram_original=False, motion={"enabled": False},
        sfx={"enabled": False}, qh=brief["_qh"],
    )
    (jobs / f"{record['job_id']}.json").write_text(json.dumps(record), encoding="utf-8")
    (project / "launch/LAUNCH_REQUEST.json").write_text(json.dumps(record), encoding="utf-8")
    values = panel.frozen_values(record, brief, voice)
    values["topic"] = "A completely different episode"
    payload = json.dumps({"job_id": record["job_id"], "config": {"values": values}}).encode()

    class Process:
        pid = 7171

    monkeypatch.setattr(panel.subprocess, "Popen", lambda *args, **kwargs: Process())

    class ConfigHandler(_Handler):
        def __init__(self):
            super().__init__(jobs)
            self.headers = {"Content-Length": str(len(payload))}
            self.rfile = io.BytesIO(payload)
            self.response = None

        def send_json(self, status, value):
            self.response = (status, value)

    handler = ConfigHandler()
    handler.handle_config_revision()

    assert handler.response[0] == 202
    response = handler.response[1]
    assert response["new_run"] is True
    saved_source = json.loads((jobs / f"{record['job_id']}.json").read_text())
    assert saved_source["topic"] == "why panels matter"
    assert not (project / "launch/config_revisions").exists()
    new_record = json.loads((jobs / f"{response['job_id']}.json").read_text())
    new_project = tmp_path / new_record["project"]
    assert new_record["topic"] == "A completely different episode"
    assert new_record["launched_from_job_id"] == record["job_id"]
    assert new_project != project
    assert (new_project / "launch/LAUNCH_REQUEST.json").is_file()
    assert not (new_project / "pipeline/QH_RUNTIME_STATE.json").exists()
    assert source_artifact.is_file()


def test_structured_image_edit_settings_use_only_their_render_and_transition_roots() -> None:
    record = _record(motion={"enabled": False}, sfx={"enabled": False})
    brief = {"_qh": {}, "_motion": {"enabled": False}, "_sfx": {}, "_subtitle": {}}
    voice = {"voice": "Mark - Natural Conversations", "model": "Eleven Multilingual v2"}
    values = panel.frozen_values(record, brief, voice)

    values["motion_image_zoom_strength"] = .18
    roots, revised, _voice, _launch, changed = panel.config_roots(record, brief, voice, values)
    assert roots == {"render_profile"}
    assert revised["_motion"]["image_zoom_strength"] == .18
    assert "motion_image_zoom_strength" in changed

    values = panel.frozen_values(record, brief, voice)
    values["motion_image_transition_style"] = "cut_fade"
    roots, revised, _voice, _launch, changed = panel.config_roots(record, brief, voice, values)
    assert roots == {"render_profile", "transition_direction"}
    assert revised["_motion"]["image_transition_style"] == "cut_fade"
    assert "motion_image_transition_style" in changed


def test_branding_revision_is_render_only_and_persists_the_shared_font_style() -> None:
    record = _record(motion={"enabled": False}, sfx={"enabled": False})
    brief = {"_qh": {}, "_motion": {"enabled": False}, "_sfx": {}, "_subtitle": {}}
    voice = {"voice": "Mark - Natural Conversations", "model": "Eleven Multilingual v2"}
    values = panel.frozen_values(record, brief, voice)
    values.update({
        "logo_width_percent": 18,
        "logo_position": "bottom_left",
        "title_font": "Rubik",
        "title_font_colour": "#FFD700",
        "title_position": "custom",
        "title_custom_x_percent": 62,
        "title_custom_y_percent": 21,
        "title_max_words_per_line": 12,
        "title_line_spacing": 14,
    })

    roots, revised, _voice, _launch, changed = panel.config_roots(record, brief, voice, values)

    assert roots == {"render_profile"}
    assert revised["_branding"]["logo_width_percent"] == 18
    assert revised["_branding"]["logo_position"] == "bottom_left"
    assert revised["_branding"]["title_font"] == "Rubik"
    assert revised["_branding"]["title_font_colour"] == "#FFD700"
    assert revised["_branding"]["title_max_words_per_line"] == 12
    assert revised["_branding"]["title_line_spacing"] == 14
    assert {"logo_width_percent", "logo_position", "title_font", "title_position"} <= set(changed)


def test_structured_config_rejects_unknown_and_invalid_values() -> None:
    values = panel.launch_defaults(panel.studio_schema())
    values["topic"] = "validation test"
    with pytest.raises(ValueError, match="Unknown configuration"):
        panel.validate_config_values({**values, "raw_json_escape": True})
    with pytest.raises(ValueError, match="Minimum duration"):
        panel.validate_config_values({**values, "min_duration_seconds": 90, "max_duration_seconds": 40})


def test_declarative_form_defaults_are_accepted_by_the_launch_endpoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(panel, "ROOT", tmp_path)
    (tmp_path / "videos").mkdir()
    jobs = tmp_path / "control_panel/jobs"; jobs.mkdir(parents=True)
    schema = panel.studio_schema()
    values = panel.launch_defaults(schema)
    values["topic"] = "A complete schema launch"
    pairs = []
    for key, value in values.items():
        if isinstance(value, bool):
            if value: pairs.append((key, "on"))
        elif isinstance(value, list): pairs.append((key, ",".join(value)))
        else: pairs.append((key, str(value)))
    encoded = urlencode(pairs).encode()

    class Process:
        pid = 5151
    monkeypatch.setattr(panel.subprocess, "Popen", lambda *args, **kwargs: Process())

    class PostHandler(panel.Handler):
        def __init__(self):
            self.path = "/launch"
            self.headers = {"Content-Length": str(len(encoded)), "Host": "localhost", "Accept": "application/json"}
            self.rfile = io.BytesIO(encoded)
            self.response = None
        @property
        def jobs_dir(self): return jobs
        def send_html(self, status, body): self.response = (status, body)
        def send_json(self, status, body): self.response = (status, body)
        def send_error(self, status, message=None): self.response = (status, message)

    handler = PostHandler(); handler.do_POST()
    assert handler.response[0] == 202
    assert handler.response[1]["job_id"]
    records = list(jobs.glob("*.json"))
    assert len(records) == 1
    record = json.loads(records[0].read_text())
    assert record["topic"] == "A complete schema launch"
    assert record["music_providers"] == ["freesound", "mixkit", "pixabay"]
    assert record["motion"]["enabled"] is True
    assert record["qh"]["reserve_subtitle_space"] is True
