#!/usr/bin/env python3
"""Data-driven opening/entry formats for Q Station.

Character packs select a presentation profile, but the profile owns HOW an episode moves
from its question intro into the topic world.  The character pack remains the source of WHO,
and WORLD_STYLE_PLAN remains the source of HOW the topic world looks.

The durable A/B stage ids are intentionally retained: historical runs and panel retry state
already use them.  Artifact names and prompt contracts are resolved from this module instead
of being inferred from those compatibility ids.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


class PresentationProfileError(RuntimeError):
    pass


def _safe_child(base: Path, relative: str, *, what: str) -> Path:
    if not relative or Path(relative).is_absolute():
        raise PresentationProfileError(f"{what} must be a relative path; got {relative!r}")
    resolved = (base / relative).resolve()
    base = base.resolve()
    if base != resolved and base not in resolved.parents:
        raise PresentationProfileError(f"{what} escapes its presentation profile: {relative!r}")
    return resolved


@dataclass(frozen=True)
class OpeningArtifacts:
    question_prompt: str
    entry_prompt: str
    question_source: str
    entry_source: str
    question_trimmed: str
    entry_trimmed: str
    entry_direction: str
    entry_frame: str
    entry_image_receipt: str

    def path(self, project: Path, field: str) -> Path:
        return Path(project) / str(getattr(self, field))


@dataclass(frozen=True)
class PresentationContext:
    id: str
    display_name: str
    version: int
    entry_kind: str
    segment_key: str
    segment_label: str
    script_rules: str
    episode_rules: str
    question_prompt_rules: str
    transition_prompt: str
    entry_identity_prompt: str
    entry_frame_prompt: str
    identity_sheet_path: Path
    identity_required_at_preflight: bool
    entry_frame_character_presence: str
    artifacts: OpeningArtifacts
    profile_path: Path

    def prompt_context(self) -> dict[str, Any]:
        return {
            "profile_id": self.id,
            "display_name": self.display_name,
            "entry_kind": self.entry_kind,
            "entry_segment_key": self.segment_key,
            "entry_segment_label": self.segment_label,
            "script_rules": self.script_rules,
            "episode_rules": self.episode_rules,
            "entry_frame_character_presence": self.entry_frame_character_presence,
        }

    def to_resolution(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "profile_id": self.id,
            "profile_version": self.version,
            "entry_kind": self.entry_kind,
            "segment_key": self.segment_key,
            "artifacts": self.artifacts.__dict__,
        }


def _read_required(path: Path, what: str) -> str:
    if not path.is_file():
        raise PresentationProfileError(f"Missing {what}: {path}")
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise PresentationProfileError(f"Empty {what}: {path}")
    return value


@lru_cache(maxsize=None)
def _load_cached(path_string: str, mtime_ns: int) -> PresentationContext:
    path = Path(path_string)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PresentationProfileError(f"Invalid presentation profile {path}: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise PresentationProfileError(f"{path} must be a schema_version 1 JSON object.")
    profile_id = str(data.get("id") or "").strip()
    entry_kind = str(data.get("entry_kind") or "").strip()
    if not _ID_RE.fullmatch(profile_id) or not _ID_RE.fullmatch(entry_kind):
        raise PresentationProfileError(f"Invalid presentation id/entry_kind in {path}.")
    segment = data.get("narration_segment") or {}
    segment_key = str(segment.get("key") or "").strip()
    if not _ID_RE.fullmatch(segment_key):
        raise PresentationProfileError(f"Invalid narration_segment.key in {path}.")
    presence = str(data.get("entry_frame_character_presence") or "none").strip()
    if presence not in {"none", "ownership_cue"}:
        raise PresentationProfileError(
            "entry_frame_character_presence must be 'none' or 'ownership_cue'."
        )
    root = path.parent
    prompt_files = data.get("prompt_files") or {}
    prompts = {
        key: _read_required(_safe_child(root, str(prompt_files.get(key) or ""), what=f"prompt_files.{key}"), f"prompt_files.{key}")
        for key in ("script_rules", "episode_rules", "question_intro", "entry_transition", "entry_identity", "entry_frame")
    }
    identity = data.get("identity") or {}
    identity_rel = str(identity.get("canonical_sheet") or "")
    if not identity_rel or Path(identity_rel).is_absolute():
        raise PresentationProfileError("identity.canonical_sheet must be a relative path.")
    identity_path = (root / identity_rel).resolve()
    project_root = path.parents[2].resolve()
    if project_root != identity_path and project_root not in identity_path.parents:
        raise PresentationProfileError(f"identity.canonical_sheet escapes the content project: {identity_rel!r}")
    if bool(identity.get("required_at_preflight", False)) and not identity_path.is_file():
        raise PresentationProfileError(f"Required entry identity sheet is missing: {identity_path}")
    raw_artifacts = data.get("artifacts") or {}
    fields = tuple(OpeningArtifacts.__dataclass_fields__)
    missing = [field for field in fields if not str(raw_artifacts.get(field) or "").strip()]
    if missing:
        raise PresentationProfileError(f"Presentation {profile_id!r} is missing artifacts: {missing}")
    for field in fields:
        rel = Path(str(raw_artifacts[field]))
        if rel.is_absolute() or ".." in rel.parts:
            raise PresentationProfileError(f"Unsafe artifact path for {field}: {rel}")
    return PresentationContext(
        id=profile_id,
        display_name=str(data.get("display_name") or profile_id),
        version=int(data.get("version") or 1),
        entry_kind=entry_kind,
        segment_key=segment_key,
        segment_label=str(segment.get("label") or segment_key),
        script_rules=prompts["script_rules"],
        episode_rules=prompts["episode_rules"],
        question_prompt_rules=prompts["question_intro"],
        transition_prompt=prompts["entry_transition"],
        entry_identity_prompt=prompts["entry_identity"],
        entry_frame_prompt=prompts["entry_frame"],
        identity_sheet_path=identity_path,
        identity_required_at_preflight=bool(identity.get("required_at_preflight", False)),
        entry_frame_character_presence=presence,
        artifacts=OpeningArtifacts(**{field: str(raw_artifacts[field]) for field in fields}),
        profile_path=path,
    )


def _profile_revision(path: Path) -> int:
    """Fingerprint all declarative inputs so long-lived services reload prompt edits."""
    candidates = [path, *path.parent.rglob("*.md")]
    return max(candidate.stat().st_mtime_ns for candidate in candidates if candidate.is_file())


def load_presentation_profile(path: Path) -> PresentationContext:
    path = Path(path).resolve()
    if not path.is_file():
        raise PresentationProfileError(f"Presentation profile not found: {path}")
    return _load_cached(str(path), _profile_revision(path))


def presentation_for_project(project: Path, content_project: Any | None = None) -> PresentationContext:
    """Resolve a run's persisted presentation, defaulting historical runs to legacy book."""
    project = Path(project)
    resolution = project / "creative" / "PRESENTATION_RESOLUTION.json"
    profile_id = ""
    persisted: dict[str, Any] = {}
    if resolution.is_file():
        try:
            candidate = json.loads(resolution.read_text(encoding="utf-8"))
            persisted = candidate if isinstance(candidate, dict) else {}
            profile_id = str(persisted.get("profile_id") or "")
        except (OSError, ValueError):
            profile_id = ""
    if content_project is None:
        from content_projects import load_content_project
        launch = project / "launch" / "LAUNCH_REQUEST.json"
        try:
            content_id = str(json.loads(launch.read_text(encoding="utf-8")).get("content_project") or "q_station")
        except (OSError, ValueError):
            content_id = "q_station"
        content_project = load_content_project(content_id)
    if not profile_id:
        # Existing runs predate PRESENTATION_RESOLUTION and all used the book contract.
        profile_id = str((content_project.config.get("presentation_profiles") or {}).get("legacy_default") or "book_portal")
    root = content_project.root / "presentation_profiles" / profile_id / "profile.json"
    profile = load_presentation_profile(root)
    if persisted:
        if int(persisted.get("profile_version") or 0) != profile.version:
            raise PresentationProfileError(
                f"Run expects presentation {profile.id!r} version {persisted.get('profile_version')}; installed version is {profile.version}."
            )
        if str(persisted.get("entry_kind") or "") != profile.entry_kind or str(persisted.get("segment_key") or "") != profile.segment_key:
            raise PresentationProfileError("Persisted presentation contract no longer matches the installed profile.")
    return profile
