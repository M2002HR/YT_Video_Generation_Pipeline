"""Install a hash-pinned Studio music upload as the episode's selected bed."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from music_plan import single_bed, write_plan

AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".flac"}


def audio_duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        check=True, capture_output=True, text=True, timeout=30,
    )
    duration = float(result.stdout.strip())
    if duration <= 0:
        raise ValueError(f"Audio duration is not positive: {path}")
    return duration


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def install_operator_music(
    project: Path, source: Path, expected_sha256: str, narration_seconds: float,
    source_metadata: dict | None = None,
) -> Path:
    """Verify immutable input, copy it atomically, and write normal music manifests."""
    project = project.resolve()
    source = source.resolve()
    if not source.is_file() or source.suffix.lower() not in AUDIO_EXTENSIONS:
        raise FileNotFoundError(f"Uploaded background music is unavailable or unsupported: {source}")
    actual = sha256_path(source)
    if len(expected_sha256) != 64 or actual != expected_sha256:
        raise ValueError("Uploaded background music failed its frozen SHA-256 check.")
    if narration_seconds <= 0:
        raise ValueError("Narration duration must be positive before installing uploaded music.")

    destination = project / "assets" / "music" / f"operator_background{source.suffix.lower()}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    try:
        shutil.copyfile(source, temporary)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    relative = str(destination.relative_to(project))
    source_metadata = source_metadata or {}
    provider = str(source_metadata.get("provider") or "operator_upload")
    origin = str(source_metadata.get("origin") or "upload")
    selection_mode = "operator_upload" if origin == "upload" and provider == "operator_upload" else "library_selection"
    selection = {
        "schema_version": 1,
        "provider": provider,
        "selection_mode": selection_mode,
        "file": relative,
        "source_url": source_metadata.get("source_url"),
        "source_sha256": expected_sha256,
        "license": source_metadata.get("license") or "Operator-supplied; publication rights must be verified by the operator.",
        "original_name": source_metadata.get("original_name") or source.name,
        "library_origin": origin,
        "selected_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest = project / "music" / "MUSIC_SELECTION.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(selection, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    segments = single_bed(
        narration_seconds=narration_seconds,
        provider=provider,
        query_prompt=f"Studio {selection_mode.replace('_', ' ')}; no provider search performed.",
        file=relative,
    )
    write_plan(project, segments, narration_seconds=narration_seconds, status="SELECTED")
    return destination
