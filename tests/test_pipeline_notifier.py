"""Telegram log grouping for resumable pipeline stages."""
from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from pipeline_notifier import EditableMessage, NotifierSettings, PipelineNotifier, safe_detail  # noqa: E402


class RecordingNotifier(PipelineNotifier):
    def __init__(self) -> None:
        super().__init__(video_id="007", topic="test")
        self.sent: list[str] = []
        self.edited: list[tuple[int, str]] = []

    def send_editable(self, body: str) -> EditableMessage | None:
        self.sent.append(body)
        return EditableMessage(len(self.sent))

    def edit(self, message: EditableMessage | None, body: str) -> bool:
        assert message is not None
        self.edited.append((message.message_id, body))
        return True


class PersistentRecordingNotifier(PipelineNotifier):
    def __init__(self, state_path: Path) -> None:
        self.sent: list[str] = []
        self.edited: list[tuple[int, str]] = []
        super().__init__(video_id="007", topic="test", state_path=state_path)

    def send_editable(self, body: str) -> EditableMessage | None:
        self.sent.append(body)
        return EditableMessage(100 + len(self.sent))

    def edit(self, message: EditableMessage | None, body: str) -> bool:
        assert message is not None
        self.edited.append((message.message_id, body))
        return True


def test_reused_artifact_is_appended_to_the_previous_phase_message() -> None:
    notifier = RecordingNotifier()
    message = notifier.stage_started("Script")
    notifier.stage_update(message, "Script", ["✅ Stage complete"])

    assert notifier.stage_reused("Visual beats", ["↻ Reused existing artifact", "📄 beats.json"])

    assert len(notifier.sent) == 1
    # Reuse edits are coalesced to stay below Telegram's edit-rate limit.
    assert notifier.edited[-1][1].endswith("✅ Stage complete")
    notifier.stage_started("Image generation")
    message_id, body = notifier.edited[-1]
    assert message_id == 1
    assert body.endswith("<b>Video 007 · Visual beats</b>\n↻ Reused existing artifact\n📄 beats.json")

    assert len(notifier.sent) == 2


def test_initial_reuses_wait_for_the_first_fresh_phase() -> None:
    notifier = RecordingNotifier()

    assert not notifier.stage_reused("Script", ["↻ Reused existing artifact", "📄 SCRIPT.md"])
    assert notifier.sent == []

    notifier.stage_started("Image generation")

    assert len(notifier.sent) == 1
    assert "<b>Video 007 · Script</b>\n↻ Reused existing artifact\n📄 SCRIPT.md" in notifier.sent[0]
    assert notifier.sent[0].endswith("<b>Video 007 · Image generation</b>\n▶ Stage started")


def test_stage_completion_preserves_reuses_held_for_its_first_message() -> None:
    notifier = RecordingNotifier()
    notifier.stage_reused("Script", ["↻ Reused existing artifact", "📄 SCRIPT.md"])
    message = notifier.stage_started("Image generation")
    notifier.stage_update(message, "Image generation", ["✅ Stage complete"])

    assert "<b>Video 007 · Script</b>\n↻ Reused existing artifact\n📄 SCRIPT.md" in notifier.edited[-1][1]
    assert notifier.edited[-1][1].endswith("<b>Video 007 · Image generation</b>\n✅ Stage complete")


def test_many_reuses_are_flushed_in_one_edit_before_the_next_fresh_phase() -> None:
    notifier = RecordingNotifier()
    message = notifier.stage_started("Script")
    notifier.stage_update(message, "Script", ["✅ Stage complete"])
    edits_before_reuse = len(notifier.edited)

    for number in range(20):
        notifier.stage_reused(f"Reuse {number}", ["↻ Reused existing artifact", f"📄 asset-{number}"])

    assert len(notifier.edited) == edits_before_reuse
    notifier.stage_started("Image generation")
    assert len(notifier.edited) == edits_before_reuse + 1
    assert "📄 asset-0" in notifier.edited[-1][1]
    assert "additional reused stage(s)" in notifier.edited[-1][1]


def test_pending_reuses_are_not_lost_when_the_next_event_is_a_summary() -> None:
    notifier = RecordingNotifier()
    notifier.stage_reused("Script", ["↻ Reused existing artifact", "📄 SCRIPT.md"])

    assert notifier.send("Pipeline complete", ["✅ Done"])
    assert "📄 SCRIPT.md" in notifier.sent[-1]
    assert notifier.sent[-1].endswith("✅ Done")


def test_stage_failure_closes_the_mutable_stage_instead_of_sending_a_duplicate() -> None:
    notifier = RecordingNotifier()
    message = notifier.stage_started("Render")

    assert notifier.stage_failure(message, "Render", 12, "ffmpeg exited")
    assert len(notifier.sent) == 1
    assert notifier.edited[-1][0] == message.message_id
    assert "❌ Failed" in notifier.edited[-1][1]


def test_delivery_credentials_do_not_depend_on_progress_notifications() -> None:
    settings = NotifierSettings(
        enabled=False,
        recipient="me",
        api_id=1,
        api_hash="hash",
        string_session="session",
        proxy=None,
    )
    assert settings.delivery_configured is True
    assert settings.notifications_configured is False
    assert settings.configured is False


def test_oversized_message_is_bounded_safely() -> None:
    body = "<b>Title</b>\n" + "x" * 5000
    bounded = PipelineNotifier._bounded(body)
    assert len(bounded) <= 3900
    assert bounded.endswith("… details truncated")
    assert "<b>" not in bounded


def test_stage_message_id_survives_process_restart(tmp_path: Path) -> None:
    state = tmp_path / "pipeline" / "TELEGRAM_NOTIFICATION_STATE.json"
    first = PersistentRecordingNotifier(state)
    message = first.stage_started("Render", key="render_baseline")
    assert message is not None

    resumed = PersistentRecordingNotifier(state)
    restored = resumed.stage_started("Render", key="render_baseline")

    assert restored == message
    assert resumed.sent == []
    assert resumed.edited[-1][0] == message.message_id


def test_parallel_stages_have_independent_message_ownership(tmp_path: Path) -> None:
    notifier = PersistentRecordingNotifier(tmp_path / "pipeline" / "TELEGRAM_NOTIFICATION_STATE.json")
    image = notifier.stage_started("Images", key="body_images")
    music = notifier.stage_started("Music", key="background_music")

    assert image is not None and music is not None
    assert image.message_id != music.message_id
    assert notifier.message_for("body_images") == image
    assert notifier.message_for("background_music") == music


def test_stale_parallel_writers_merge_message_ownership(tmp_path: Path) -> None:
    state = tmp_path / "pipeline" / "TELEGRAM_NOTIFICATION_STATE.json"
    images = PersistentRecordingNotifier(state)
    music = PersistentRecordingNotifier(state)
    images.stage_started("Images", key="body_images")
    music.stage_started("Music", key="background_music")

    restored = PersistentRecordingNotifier(state)
    assert restored.message_for("body_images") is not None
    assert restored.message_for("background_music") is not None


def test_error_details_redact_credentials_and_url_queries() -> None:
    detail = safe_detail("GET https://example.test/job?access_token=secret token=abc cookie:xyz")
    assert "secret" not in detail and "abc" not in detail and "xyz" not in detail
    assert "[redacted]" in detail
