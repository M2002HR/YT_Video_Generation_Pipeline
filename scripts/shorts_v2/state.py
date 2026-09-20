"""Durable stage state and single-writer leases for Shorts V2."""
from __future__ import annotations

import fcntl
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .artifacts import atomic_write_json
from .contracts import ContractError, stable_id


STATUSES = frozenset({
    "QUEUED", "RUNNING", "REUSED", "STALE", "SKIPPED_CONFIG", "DONE",
    "PAUSED_AUTH", "WAITING_PROVIDER", "FAILED_TECHNICAL", "FAILED_CONTRACT",
    "INTERRUPTED", "CONFLICT",
})
TERMINAL = frozenset({"REUSED", "SKIPPED_CONFIG", "DONE", "FAILED_TECHNICAL", "FAILED_CONTRACT", "INTERRUPTED", "CONFLICT"})
TRANSITIONS = {
    "QUEUED": {"RUNNING", "REUSED", "SKIPPED_CONFIG", "CONFLICT"},
    "RUNNING": {"DONE", "WAITING_PROVIDER", "PAUSED_AUTH", "FAILED_TECHNICAL", "FAILED_CONTRACT", "INTERRUPTED"},
    "WAITING_PROVIDER": {"RUNNING", "DONE", "PAUSED_AUTH", "FAILED_TECHNICAL", "INTERRUPTED"},
    "PAUSED_AUTH": {"RUNNING", "INTERRUPTED"},
    "STALE": {"QUEUED", "RUNNING", "CONFLICT"},
    "INTERRUPTED": {"QUEUED", "RUNNING", "CONFLICT"},
}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class StageStateStore:
    def __init__(self, path: Path, *, run_id: str, revision_id: str) -> None:
        stable_id(run_id, "run_id")
        stable_id(revision_id, "revision_id")
        self.path = path
        if path.exists():
            value = json.loads(path.read_text(encoding="utf-8"))
            if value.get("run_id") != run_id or value.get("revision_id") != revision_id:
                raise ContractError("state file belongs to a different run/revision")
            self.data = value
        else:
            self.data = {
                "schema_version": 1,
                "editing_engine": "shorts_v2",
                "run_id": run_id,
                "revision_id": revision_id,
                "owner_epoch": 0,
                "stages": {},
                "created_at": utcnow(),
            }
            self.save()

    def save(self) -> None:
        self.data["updated_at"] = utcnow()
        atomic_write_json(self.path, self.data)

    def transition(self, stage: str, status: str, **details: Any) -> dict[str, Any]:
        stable_id(stage, "stage")
        if status not in STATUSES:
            raise ContractError(f"unknown stage status: {status}")
        current = self.data.setdefault("stages", {}).get(stage, {}).get("status", "QUEUED")
        if current == status:
            entry = self.data["stages"].setdefault(stage, {})
            entry.update(details)
            entry["updated_at"] = utcnow()
            self.save()
            return entry
        if current in TERMINAL and status not in {"QUEUED", "RUNNING"}:
            raise ContractError(f"cannot transition terminal stage {stage} from {current} to {status}")
        allowed = TRANSITIONS.get(current, set())
        if status not in allowed:
            raise ContractError(f"invalid stage transition {stage}: {current} -> {status}")
        entry = {"status": status, "updated_at": utcnow(), **details}
        self.data["stages"][stage] = entry
        self.save()
        return entry


@dataclass
class FileLease:
    path: Path
    owner: str
    run_id: str
    revision_id: str
    attempt_id: str
    ttl_seconds: float = 120.0
    _descriptor: int | None = None
    epoch: int = 0

    def __post_init__(self) -> None:
        for field in ("owner", "run_id", "revision_id", "attempt_id"):
            stable_id(getattr(self, field), field)
        if not 5 <= float(self.ttl_seconds) <= 3600:
            raise ContractError("lease ttl_seconds must be between 5 and 3600")

    def acquire(self) -> "FileLease":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(descriptor)
            raise ContractError(f"resource lease is already held: {self.path}") from exc
        self._descriptor = descriptor
        previous: dict[str, Any] = {}
        try:
            raw = os.read(descriptor, 64 * 1024).decode("utf-8")
            previous = json.loads(raw) if raw.strip() else {}
        except (OSError, ValueError):
            previous = {}
        self.epoch = int(previous.get("epoch") or 0) + 1
        self._write("ACTIVE")
        return self

    def _write(self, status: str) -> None:
        if self._descriptor is None:
            raise ContractError("lease has not been acquired")
        payload = json.dumps({
            "schema_version": 1,
            "status": status,
            "owner": self.owner,
            "run_id": self.run_id,
            "revision_id": self.revision_id,
            "attempt_id": self.attempt_id,
            "epoch": self.epoch,
            "heartbeat_unix": time.time(),
            "ttl_seconds": self.ttl_seconds,
        }, sort_keys=True).encode("utf-8")
        os.lseek(self._descriptor, 0, os.SEEK_SET)
        os.ftruncate(self._descriptor, 0)
        os.write(self._descriptor, payload)
        os.fsync(self._descriptor)

    def heartbeat(self) -> None:
        self._write("ACTIVE")

    def release(self) -> None:
        if self._descriptor is None:
            return
        try:
            self._write("RELEASED")
            fcntl.flock(self._descriptor, fcntl.LOCK_UN)
        finally:
            os.close(self._descriptor)
            self._descriptor = None

    def __enter__(self) -> "FileLease":
        return self.acquire()

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.release()
