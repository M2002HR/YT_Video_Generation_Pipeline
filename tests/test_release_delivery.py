from __future__ import annotations

import asyncio
import json
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from pipeline_notifier import NotifierSettings  # noqa: E402
from release_youtube_short import deliver_bundle  # noqa: E402


def test_partial_telegram_delivery_checkpoints_and_does_not_resend_master(
    tmp_path: Path, monkeypatch,
) -> None:
    master = tmp_path / "master.mp4"
    candidate = tmp_path / "candidate.png"
    metadata = tmp_path / "metadata.json"
    upload = tmp_path / "upload.md"
    for path, payload in ((master, b"master"), (candidate, b"candidate"), (metadata, b"{}"), (upload, b"guide")):
        path.write_bytes(payload)
    receipt = tmp_path / "DELIVERY_STATE.json"

    class FakeMessage:
        def __init__(self, message_id: int) -> None:
            self.id = message_id

    class FakeClient:
        sent_files: list[str] = []
        next_id = 10
        fail_candidate_once = True

        def __init__(self, *args, **kwargs) -> None:
            pass

        async def connect(self) -> None:
            pass

        async def disconnect(self) -> None:
            pass

        async def is_user_authorized(self) -> bool:
            return True

        async def send_file(self, _recipient, path, **kwargs):
            self.__class__.sent_files.append(str(path))
            if str(path) == str(candidate) and self.__class__.fail_candidate_once:
                self.__class__.fail_candidate_once = False
                raise RuntimeError("temporary delivery failure")
            self.__class__.next_id += 1
            return FakeMessage(self.__class__.next_id)

        async def send_message(self, *args, **kwargs):
            self.__class__.next_id += 1
            return FakeMessage(self.__class__.next_id)

    telethon = types.ModuleType("telethon")
    telethon.TelegramClient = FakeClient
    sessions = types.ModuleType("telethon.sessions")
    sessions.StringSession = lambda value: value
    monkeypatch.setitem(sys.modules, "telethon", telethon)
    monkeypatch.setitem(sys.modules, "telethon.sessions", sessions)
    settings = NotifierSettings(False, "recipient", 1, "hash", "session", None)
    candidates = [{
        "candidate_id": "candidate_01", "final_path": str(candidate), "selected": True,
        "headline": "Test", "review": {"eligible": True, "score": 9}, "final": {"sha256": "candidate-hash"},
    }]

    try:
        asyncio.run(deliver_bundle(
            settings, master, None, upload, metadata, "caption", "title",
            candidates=candidates, receipt_path=receipt,
        ))
    except RuntimeError as exc:
        assert "temporary delivery failure" in str(exc)
    else:
        raise AssertionError("the first delivery attempt should fail")

    checkpoint = json.loads(receipt.read_text(encoding="utf-8"))
    assert checkpoint["status"] == "RUNNING"
    assert checkpoint["messages"]["master"]

    completed = asyncio.run(deliver_bundle(
        settings, master, None, upload, metadata, "caption", "title",
        candidates=candidates, receipt_path=receipt,
        prior_messages=checkpoint["messages"],
    ))
    assert completed["candidates"]["candidate_01"]["message_id"]
    assert FakeClient.sent_files.count(str(master)) == 1

