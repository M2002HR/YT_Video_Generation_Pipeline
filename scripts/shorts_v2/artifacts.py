"""Safe revision-local artifact resolution and atomic JSON writes."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contracts import ContractError, stable_id


LOGICAL_ARTIFACTS: dict[str, str] = {
    "request": "REQUEST.json",
    "revision": "REVISION.json",
    "character_resolution": "creative/CHARACTER_RESOLUTION.json",
    "character_performance": "creative/CHARACTER_PERFORMANCE_CONTEXT.json",
    "evidence_pack": "creative/EVIDENCE_PACK.json",
    "hook_packages": "creative/HOOK_PACKAGES.json",
    "hook_reviews": "creative/HOOK_REVIEWS.json",
    "hook_tournament": "creative/HOOK_TOURNAMENT.json",
    "story_blueprint": "creative/STORY_BLUEPRINT.json",
    "voice_resolution": "voiceover/VOICE_RESOLUTION.json",
    "voice_capabilities": "voiceover/VOICE_CAPABILITIES.json",
    "voice_performance": "voiceover/VOICE_PERFORMANCE_PLAN.json",
    "script_core": "creative/SCRIPT_CORE.json",
    "cta": "creative/CTA.json",
    "script_reviews": "creative/SCRIPT_REVIEWS.json",
    "tts_input": "voiceover/TTS_INPUT.txt",
    "voice_token_map": "voiceover/VOICE_TOKEN_MAP.json",
    "tts_receipt": "receipts/TTS_EXECUTION_RECEIPT.json",
    "narration_audio": "voiceover/narration.mp3",
    "narration_timing": "timing/NARRATION_TIMING.json",
    "narration_pacing": "timing/NARRATION_PACING_REPORT.json",
    "rhythm_map": "timing/RHYTHM_MAP.json",
    "opening_source_plan": "planning/OPENING_SOURCE_PLAN.json",
    "opening_plan": "planning/OPENING_PLAN.json",
    "shot_plan": "planning/SHOT_PLAN.json",
    "asset_manifest": "planning/ASSET_MANIFEST.json",
    "asset_observations": "planning/ASSET_OBSERVATIONS.json",
    "media_review": "planning/MEDIA_REVIEW.json",
    "opening_media_receipt": "receipts/OPENING_MEDIA_RECEIPT.json",
    "edit_plan": "editing/EDIT_PLAN.json",
    "compiled_timeline": "editing/COMPILED_TIMELINE.json",
    "layout_constraints": "editing/LAYOUT_CONSTRAINTS.json",
    "segment_cache_manifest": "editing/SEGMENT_CACHE_MANIFEST.json",
    "preview": "render/preview.mp4",
    "final": "render/final.mp4",
    "render_receipt": "receipts/RENDER_RECEIPT.json",
}


def _within(root: Path, target: Path) -> Path:
    root = root.resolve()
    target = target.resolve(strict=False)
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ContractError(f"artifact path escapes revision root: {target}") from exc
    current = target
    while current != root and current.exists():
        if current.is_symlink():
            raise ContractError(f"artifact path traverses symlink: {current}")
        current = current.parent
    return target


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


@dataclass(frozen=True)
class ArtifactResolver:
    episode_root: Path
    revision_id: str

    def __post_init__(self) -> None:
        stable_id(self.revision_id, "revision_id")

    @property
    def engine_root(self) -> Path:
        return self.episode_root.resolve() / "shorts_v2"

    @property
    def revision_root(self) -> Path:
        return self.engine_root / "versions" / self.revision_id

    def resolve(self, logical_name: str) -> Path:
        try:
            relative = LOGICAL_ARTIFACTS[logical_name]
        except KeyError as exc:
            raise ContractError(f"unknown logical artifact: {logical_name}") from exc
        return _within(self.revision_root, self.revision_root / relative)

    def resolve_relative(self, relative: str) -> Path:
        candidate = Path(str(relative))
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ContractError("revision-relative artifact path is unsafe")
        return _within(self.revision_root, self.revision_root / candidate)

    def ensure_layout(self) -> None:
        for directory in ("creative", "voiceover", "timing", "planning", "editing", "render", "receipts", "diagnostics"):
            self.resolve_relative(directory).mkdir(parents=True, exist_ok=True)

    def accepted_pointer(self) -> Path:
        return _within(self.engine_root, self.engine_root / "ACCEPTED_VERSION.json")
