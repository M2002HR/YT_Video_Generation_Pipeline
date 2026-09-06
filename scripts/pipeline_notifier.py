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
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


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
        # Not every pipeline entry point loads the root .env (notably the
        # completion/render child processes).  Notifications must not depend
        # on which stage happened to be the executable entry point.
        env_file = Path(os.getenv("YT_ENV_FILE", ".env")).expanduser()
        if not env_file.is_absolute():
            env_file = Path(__file__).resolve().parents[1] / env_file
        load_dotenv(env_file, override=False)
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


@dataclass(frozen=True)
class EditableMessage:
    """A Telegram message that later progress updates may edit in place."""

    message_id: int


@dataclass
class PipelineNotifier:
    video_id: str
    topic: str
    settings: NotifierSettings = field(default_factory=NotifierSettings.from_environment)
    image_durations: list[float] = field(default_factory=list)
    # The most recent pipeline entry is deliberately retained so resume-only
    # work can extend it instead of flooding the chat with one message per
    # artifact that was already on disk.
    last_message: EditableMessage | None = field(default=None, init=False)
    last_body: str = field(default="", init=False)
    pending_reuse_bodies: list[str] = field(default_factory=list, init=False)
    stage_prefixes: dict[int, str] = field(default_factory=dict, init=False)
    reuse_edit_pending: bool = field(default=False, init=False)

    def restore_image_progress(self, durations: list[float]) -> None:
        """Hydrate accepted-image progress after a resumable runner restart."""
        self.image_durations = [max(0.0, float(value)) for value in durations]

    def _title(self, title: str) -> str:
        return f"<b>Video {html.escape(self.video_id)} · {html.escape(title)}</b>"

    def _run_telegram(self, operation: Any) -> Any:
        """Retry Telegram's explicit, bounded flood wait once instead of dropping a log."""
        for attempt in range(2):
            try:
                return asyncio.run(operation())
            except Exception as exc:
                wait_seconds = int(getattr(exc, "seconds", 0) or 0)
                if attempt == 0 and 0 < wait_seconds <= 60:
                    print(f"NOTIFICATION INFO: Telegram rate limit; retrying in {wait_seconds}s", flush=True)
                    time.sleep(wait_seconds)
                    continue
                raise
        raise AssertionError("unreachable")

    def send_editable(self, body: str) -> EditableMessage | None:
        """Send one HTML message and retain its id for in-place progress updates."""
        if not self.settings.configured:
            return None
        try:
            message_id = self._run_telegram(lambda: self._send_editable_async(body))
        except Exception as exc:  # notifications must never stop the render
            print(f"NOTIFICATION WARNING: {type(exc).__name__}: {exc}", flush=True)
            return None
        return EditableMessage(message_id=message_id)

    def edit(self, message: EditableMessage | None, body: str) -> bool:
        """Edit a prior notification; failures are deliberately non-fatal."""
        if message is None or not self.settings.configured:
            return False
        try:
            self._run_telegram(lambda: self._edit_async(message.message_id, body))
        except Exception as exc:
            print(f"NOTIFICATION WARNING: {type(exc).__name__}: {exc}", flush=True)
            return False
        return True

    async def _send_editable_async(self, body: str) -> int:
        from telethon import TelegramClient
        from telethon.sessions import StringSession

        client = TelegramClient(StringSession(self.settings.string_session), self.settings.api_id, self.settings.api_hash, proxy=self.settings.proxy)
        await client.connect()
        try:
            if not await client.is_user_authorized():
                raise RuntimeError("configured Telegram session is not authorized")
            message = await client.send_message(self.settings.recipient, body, parse_mode="html", link_preview=False)
            return int(message.id)
        finally:
            await client.disconnect()

    async def _edit_async(self, message_id: int, body: str) -> None:
        from telethon import TelegramClient
        from telethon.sessions import StringSession

        client = TelegramClient(StringSession(self.settings.string_session), self.settings.api_id, self.settings.api_hash, proxy=self.settings.proxy)
        await client.connect()
        try:
            if not await client.is_user_authorized():
                raise RuntimeError("configured Telegram session is not authorized")
            await client.edit_message(self.settings.recipient, message_id, body, parse_mode="html", link_preview=False)
        finally:
            await client.disconnect()

    def send(self, title: str, lines: list[str]) -> bool:
        """Send a compact HTML message; return False without raising on failure."""
        body = "\n".join([self._title(title), *[html.escape(line) for line in lines if line]])
        message = self.send_editable(body)
        if message is None:
            return False
        self.last_message, self.last_body = message, body
        return True

    def stage_started(self, title: str) -> EditableMessage | None:
        """Start a new work phase and create its one mutable log entry."""
        self._flush_reuse_edit()
        prefix = "\n".join(self.pending_reuse_bodies)
        body = "\n".join(part for part in (prefix, self._title(title), "▶ Stage started") if part)
        message = self.send_editable(body)
        if message is not None:
            self.pending_reuse_bodies.clear()
            self.last_message, self.last_body = message, body
            self.stage_prefixes[message.message_id] = prefix
        return message

    def stage_update(
        self,
        message: EditableMessage | None,
        title: str,
        lines: list[str],
    ) -> bool:
        """Update a stage's original Telegram entry instead of adding log noise."""
        stage_body = "\n".join([self._title(title), *[html.escape(line) for line in lines if line]])
        prefix = self.stage_prefixes.get(message.message_id, "") if message is not None else ""
        body = "\n".join(part for part in (prefix, stage_body) if part)
        edited = self.edit(message, body)
        if edited and message is not None:
            self.last_message, self.last_body = message, body
        return edited

    def _flush_reuse_edit(self) -> bool:
        if not self.reuse_edit_pending or self.last_message is None:
            return True
        if not self.edit(self.last_message, self.last_body):
            return False
        self.reuse_edit_pending = False
        return True

    def stage_reused(self, title: str, lines: list[str]) -> bool:
        """Append a reuse result to the preceding log entry without sending a new one.

        A resumed run can discover several completed artifacts before it does
        any fresh work.  Those discoveries are log details, not new phases.
        When there is no earlier Telegram entry in this process, hold them
        until the first fresh stage starts, rather than emitting an orphan
        reuse message.
        """
        body = "\n".join([self._title(title), *[html.escape(line) for line in lines if line]])
        if self.last_message is None:
            self.pending_reuse_bodies.append(body)
            return False
        combined = "\n".join(part for part in (self.last_body, body) if part)
        self.last_body = combined
        self.reuse_edit_pending = True
        # A resumed run commonly discovers dozens of completed artifacts in a
        # few seconds.  Do not edit Telegram for each discovery: flush the
        # complete batch exactly once, immediately before the next fresh
        # phase starts.
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
