#!/usr/bin/env python3
"""Publish a verified final video with the configured Telethon user session.

The media itself can remain Git-ignored, while the durable publish receipt is
stored per video in ``publish/TELEGRAM_PUBLISH_STATE.json``.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from pipeline_notifier import NotifierSettings, format_duration


ROOT = Path(__file__).resolve().parents[1]


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


async def send_video(settings: NotifierSettings, video: Path, caption: str, artifact_marker: str) -> int:
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    client = TelegramClient(StringSession(settings.string_session), settings.api_id, settings.api_hash, proxy=settings.proxy)
    await client.connect()
    try:
        if not await client.is_user_authorized():
            raise RuntimeError("Configured Telegram user session is not authorized.")
        try:
            message = await client.send_file(
                settings.recipient,
                file=str(video),
                caption=caption,
                supports_streaming=True,
            )
            return int(message.id)
        except Exception:
            # Some old Telegram TL schemas can fail while decoding the final
            # update even though the upload was accepted. Confirm the marker
            # before ever allowing a retry to create a duplicate upload.
            recent = await client.get_messages(settings.recipient, limit=12)
            recovered = next((item for item in recent if artifact_marker in (item.message or "")), None)
            if recovered is not None:
                return int(recovered.id)
            raise
    finally:
        await client.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser(description="Send a verified polished video to the configured Telegram recipient.")
    parser.add_argument("video_dir", type=Path)
    parser.add_argument("--input", type=Path, default=None, help="Defaults to assets/renders/polished.mp4.")
    parser.add_argument("--force", action="store_true", help="Allow sending again when the exact artifact already has a receipt.")
    args = parser.parse_args()

    load_dotenv(ROOT / os.getenv("YT_ENV_FILE", ".env"), override=False)
    settings = NotifierSettings.from_environment()
    if not settings.configured:
        raise RuntimeError("Telegram publishing is not configured. Set the YT_PIPELINE_TELEGRAM_* variables in the root .env.")

    video_dir = args.video_dir.expanduser().resolve()
    video = args.input.expanduser().resolve() if args.input else video_dir / "assets" / "renders" / "polished.mp4"
    if not video.is_file() or video.stat().st_size == 0:
        raise FileNotFoundError(f"Publish input is missing or empty: {video}")

    report = video_dir / "render" / ("QC_REPORT.json" if video.name == "final.mp4" else f"QC_REPORT_{video.stem}.json")
    if not report.is_file() or not bool(json.loads(report.read_text(encoding="utf-8")).get("passed")):
        raise RuntimeError(f"A passing QC report is required before publishing: {report}")

    receipt = video_dir / "publish" / "TELEGRAM_PUBLISH_STATE.json"
    digest = sha256(video)
    if receipt.exists() and not args.force:
        prior = json.loads(receipt.read_text(encoding="utf-8"))
        if prior.get("status") == "DONE" and prior.get("sha256") == digest:
            print(f"TELEGRAM PUBLISH: ALREADY DONE\nMessage ID: {prior.get('message_id')}")
            return

    duration = 0.0
    try:
        import subprocess
        duration = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(video)], text=True).strip())
    except Exception:
        pass
    marker = f"Artifact: {digest[:12]}"
    # The caption is built from the artifacts the run produced — beat counts, the models each
    # provider confirmed, and what the render cost — so the message is auditable (T9.4).
    from episode_summary import build_summary, format_caption

    summary = build_summary(video_dir, artifact=video)
    if not summary.get("duration_seconds") and duration:
        summary["duration_seconds"] = duration
    caption = format_caption(summary, artifact_marker=marker)
    started = time.perf_counter()
    try:
        message_id = asyncio.run(send_video(settings, video, caption, marker))
    except Exception as exc:
        write_json(receipt, {"schema_version": 1, "status": "FAILED", "updated_at": utcnow(), "file": str(video.relative_to(video_dir)), "sha256": digest, "error": f"{type(exc).__name__}: {exc}", "elapsed_seconds": round(time.perf_counter() - started, 3)})
        raise
    write_json(receipt, {"schema_version": 2, "status": "DONE", "published_at": utcnow(), "recipient": settings.recipient, "message_id": message_id, "file": str(video.relative_to(video_dir)), "bytes": video.stat().st_size, "sha256": digest, "duration_seconds": round(duration, 3), "elapsed_seconds": round(time.perf_counter() - started, 3), "qc_report": str(report.relative_to(video_dir)), "summary": summary, "caption": caption})
    print(f"TELEGRAM PUBLISH: PASS\nMessage ID: {message_id}")


if __name__ == "__main__":
    main()
