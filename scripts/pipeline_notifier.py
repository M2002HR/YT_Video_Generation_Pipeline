#!/usr/bin/env python3
"""Best-effort English Telegram notifications for pipeline execution.

This module deliberately uses Telethon and a user session, never a bot token.
Notification failures are isolated from the media pipeline so a temporary
Telegram or network problem cannot discard a completed artifact.
"""
from __future__ import annotations

import asyncio
import html
import os
import time
from dataclasses import dataclass, field
from typing import Any


def _enabled(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def format_duration(seconds: float | int | None) -> str:
    total = max(0, round(float(seconds or 0)))
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"


@dataclass(frozen=True)
class NotifierSettings:
    enabled: bool
    recipient: str
    api_id: int
    api_hash: str
    string_session: str
    proxy: dict[str, Any] | None

    @classmethod
    def from_environment(cls) -> "NotifierSettings":
        raw_api_id = os.getenv("YT_TELEGRAM_API_ID", "0")
        try:
            api_id = int(raw_api_id)
        except ValueError:
            api_id = 0
        proxy: dict[str, Any] | None = None
        if _enabled(os.getenv("YT_TELEGRAM_PROXY_ENABLED")):
            host = os.getenv("YT_TELEGRAM_PROXY_HOST", "").strip()
            try:
                port = int(os.getenv("YT_TELEGRAM_PROXY_PORT", "0"))
            except ValueError:
                port = 0
            if host and port > 0:
                proxy = {
                    "proxy_type": os.getenv("YT_TELEGRAM_PROXY_TYPE", "http").strip().lower(),
                    "addr": host,
                    "port": port,
                    "rdns": _enabled(os.getenv("YT_TELEGRAM_PROXY_RDNS", "true")),
                }
                username = os.getenv("YT_TELEGRAM_PROXY_USERNAME", "").strip()
                password = os.getenv("YT_TELEGRAM_PROXY_PASSWORD", "").strip()
                if username:
                    proxy["username"] = username
                if password:
                    proxy["password"] = password
        return cls(
            enabled=_enabled(os.getenv("YT_PIPELINE_TELEGRAM_NOTIFICATIONS_ENABLED")),
            recipient=os.getenv("YT_PIPELINE_TELEGRAM_RECIPIENT", "").strip(),
            api_id=api_id,
            api_hash=os.getenv("YT_TELEGRAM_API_HASH", "").strip(),
            string_session=os.getenv("YT_TELEGRAM_STRING_SESSION", "").strip(),
            proxy=proxy,
        )

    @property
    def configured(self) -> bool:
        return self.enabled and bool(self.recipient and self.api_id > 0 and self.api_hash and self.string_session)


@dataclass
class PipelineNotifier:
    video_id: str
    topic: str
    settings: NotifierSettings = field(default_factory=NotifierSettings.from_environment)
    image_durations: list[float] = field(default_factory=list)

    def restore_image_progress(self, durations: list[float]) -> None:
        """Hydrate accepted-image progress after a resumable runner restart."""
        self.image_durations = [max(0.0, float(value)) for value in durations]

    def _title(self, title: str) -> str:
        return f"<b>Video {html.escape(self.video_id)} · {html.escape(title)}</b>"

    def send(self, title: str, lines: list[str]) -> bool:
        """Send a compact HTML message; return False without raising on failure."""
        if not self.settings.configured:
            return False
        body = "\n".join([self._title(title), *[html.escape(line) for line in lines if line]])
        try:
            asyncio.run(self._send_async(body))
        except Exception as exc:  # notification is strictly best-effort
            print(f"NOTIFICATION WARNING: {type(exc).__name__}: {exc}", flush=True)
            return False
        return True

    async def _send_async(self, body: str) -> None:
        from telethon import TelegramClient
        from telethon.sessions import StringSession

        client = TelegramClient(StringSession(self.settings.string_session), self.settings.api_id, self.settings.api_hash, proxy=self.settings.proxy)
        await client.connect()
        try:
            if not await client.is_user_authorized():
                raise RuntimeError("configured Telegram session is not authorized")
            await client.send_message(self.settings.recipient, body, parse_mode="html", link_preview=False)
        finally:
            await client.disconnect()

    def stage_complete(self, stage: str, elapsed_seconds: float, *, artifact: str = "") -> bool:
        lines = ["✅ Stage complete", f"⏱ Duration: {format_duration(elapsed_seconds)}"]
        if artifact:
            lines.append(f"📄 Saved: {artifact}")
        return self.send(stage.replace("_", " ").title(), lines)

    def prompt_complete(self, beat_id: int, total: int, elapsed_seconds: float) -> bool:
        return self.send(
            f"Beat {beat_id:03d} prompt ready",
            ["📝 Prompt complete", f"📍 Progress: {beat_id}/{total} prompts", f"⏱ Duration: {format_duration(elapsed_seconds)}"],
        )

    def image_complete(self, beat_id: int, total: int, elapsed_seconds: float) -> bool:
        self.image_durations.append(elapsed_seconds)
        total_elapsed = sum(self.image_durations)
        average = total_elapsed / len(self.image_durations)
        return self.send(
            f"Beat {beat_id:03d} image complete",
            [
                "🖼️ Image accepted",
                f"📍 Progress: {len(self.image_durations)}/{total} images",
                f"⏱ This image: {format_duration(elapsed_seconds)}",
                f"📊 Images total: {format_duration(total_elapsed)} · Avg: {format_duration(average)}",
            ],
        )

    def images_complete(self, total: int, elapsed_seconds: float, completed: int | None = None) -> bool:
        count = completed if completed is not None else len(self.image_durations)
        total_elapsed = sum(self.image_durations) or elapsed_seconds
        average = total_elapsed / count if count else 0
        return self.send(
            "Image generation complete",
            ["🎉 All planned images accepted", f"📍 Progress: {count}/{total} images", f"⏱ Total: {format_duration(total_elapsed)} · Avg/image: {format_duration(average)}"],
        )

    def warning(self, title: str, detail: str) -> bool:
        return self.send(title, ["⚠️ Warning", detail[:500]])

    def failure(self, title: str, elapsed_seconds: float, detail: str) -> bool:
        return self.send(title, ["❌ Failed", f"⏱ Elapsed: {format_duration(elapsed_seconds)}", detail[:500], "↻ The saved state can be resumed after the issue is fixed."])

    def monitoring_started(self, completed: int, total: int, generating: int | None = None) -> bool:
        detail = f"📍 Current progress: {completed}/{total} images accepted"
        if generating:
            detail += f" · Beat {generating:03d} generating"
        return self.send("Progress monitoring started", ["👀 Live watcher attached", detail])


class StageTimer:
    """Small helper for exactly measuring a notifier-facing stage."""

    def __init__(self) -> None:
        self.started = time.perf_counter()

    @property
    def elapsed(self) -> float:
        return time.perf_counter() - self.started
