"""Telegram log grouping for resumable pipeline stages."""
from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from pipeline_notifier import EditableMessage, PipelineNotifier  # noqa: E402


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
    assert "📄 asset-19" in notifier.edited[-1][1]
