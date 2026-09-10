#!/usr/bin/env python3
"""Registry-driven character identity for the Q Station (bookworld mixed-media) runtime.

WHO the recurring host is lives here, deliberately separate from the visual preset
(HOW the opening is rendered), the world style (HOW the book world is rendered) and
the opening environment (WHERE the opening happens). Pipeline stages depend on the
fields of :class:`CharacterContext`, never on hardcoded character prose or ids.

The registry and every character pack are parsed once and cached immutably; callers
get a resolved :class:`CharacterContext` and never re-read prompt files themselves.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

# Resolution sources persisted alongside a run so a resolution can be reproduced/debugged.
SOURCE_MANUAL = "manual"
SOURCE_AUTO = "auto"
SOURCE_AUTO_FALLBACK = "auto_fallback"
SOURCE_LEGACY_DEFAULT = "legacy_default"

VALID_REFERENCE_MODES = frozenset({"IDENTITY_ONLY"})
VALID_ENVIRONMENT_POLICIES = frozenset({"dynamic", "dynamic_with_soft_affinity"})
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


class CharacterRegistryError(RuntimeError):
    """Raised when a character registry or pack is malformed or fails validation."""


class CharacterSelectionError(RuntimeError):
    """Raised when a requested manual character cannot be honored (never silently swapped)."""


def parse_character_request(value: Any) -> tuple[str, str | None]:
    """Normalize the public Auto/manual request contract without guessing invalid input."""
    if value is None:
        return "auto", None
    if not isinstance(value, dict):
        raise CharacterSelectionError("character must be an object with mode='auto' or mode='manual'.")
    mode = str(value.get("mode") or "auto").strip().lower()
    character_id = str(value.get("character_id") or "").strip() or None
    if mode not in {"auto", "manual"}:
        raise CharacterSelectionError("character.mode must be 'auto' or 'manual'.")
    if mode == "auto" and character_id:
        raise CharacterSelectionError("Auto character selection must not include character_id.")
    if mode == "manual" and not character_id:
        raise CharacterSelectionError("Manual character selection requires character_id.")
    return mode, character_id


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_prompt(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def _safe_child(base: Path, relative: str, *, what: str) -> Path:
    """Resolve ``relative`` under ``base``, refusing any path that escapes ``base``."""
    if not relative or Path(relative).is_absolute():
        raise CharacterRegistryError(f"{what} must be a relative path inside the character pack; got {relative!r}")
    resolved = (base / relative).resolve()
    base_resolved = base.resolve()
    if base_resolved != resolved and base_resolved not in resolved.parents:
        raise CharacterRegistryError(f"{what} escapes the character directory: {relative!r}")
    return resolved


@dataclass(frozen=True)
class CharacterContext:
    """Everything a pipeline stage needs to render/act a resolved recurring host."""

    id: str
    display_name: str
    version: int
    archetype: str
    tone: tuple[str, ...]
    strong_topics: tuple[str, ...]
    environment_affinities: tuple[str, ...]
    environment_policy: str
    reference_mode: str
    sheet_path: Path
    sheet_sha256: str
    appearance_full: str
    behavior: str
    negative_constraints: str
    selection_profile: dict[str, Any] = field(default_factory=dict)

    @property
    def appearance_short(self) -> str:
        """First paragraph of the appearance sheet — a compact identity line for prompts."""
        for block in self.appearance_full.split("\n\n"):
            text = " ".join(line.strip() for line in block.splitlines() if not line.strip().startswith("#"))
            text = text.strip()
            if text:
                return text
        return self.appearance_full.strip()

    def selection_summary(self) -> dict[str, Any]:
        """Profile-only view for the Auto selector — never appearance/sheet/environment."""
        return {
            "character_id": self.id,
            "display_name": self.display_name,
            "archetype": self.archetype,
            "tone": list(self.tone),
            "strong_topics": list(self.strong_topics),
            "environment_affinities": list(self.environment_affinities),
        }


@dataclass(frozen=True)
class CharacterResolution:
    """The outcome of resolving a run's recurring host, for persistence + status."""

    requested_mode: str
    resolved_character_id: str
    source: str
    requested_character_id: str | None = None
    confidence: str | None = None
    reason: str | None = None
    character_version: int | None = None
    sheet_sha256: str | None = None

    def to_state(self) -> dict[str, Any]:
        payload = {
            "requested_mode": self.requested_mode,
            "requested_character_id": self.requested_character_id,
            "resolved_character_id": self.resolved_character_id,
            "resolution_source": self.source,
            "confidence": self.confidence,
            "reason": self.reason,
            "character_version": self.character_version,
            "character_sheet_sha256": self.sheet_sha256,
        }
        return {key: value for key, value in payload.items() if value is not None}


@dataclass(frozen=True)
class CharacterRegistry:
    """Parsed, validated, immutable view of a project's character registry."""

    root: Path
    default_selection_mode: str
    auto_fallback_character_id: str
    legacy_default_character_id: str
    _contexts: dict[str, CharacterContext]

    def enabled_ids(self) -> tuple[str, ...]:
        return tuple(self._contexts.keys())

    def has(self, character_id: str) -> bool:
        return character_id in self._contexts

    def get(self, character_id: str) -> CharacterContext:
        try:
            return self._contexts[character_id]
        except KeyError:
            raise CharacterSelectionError(
                f"Character {character_id!r} is not an enabled registry character "
                f"(enabled: {', '.join(self.enabled_ids()) or 'none'})."
            )

    def catalog(self) -> list[dict[str, Any]]:
        """Server-safe catalog for the control panel: no filesystem paths."""
        return [
            {
                "id": ctx.id,
                "display_name": ctx.display_name,
                "archetype": ctx.archetype,
                "tone": list(ctx.tone),
            }
            for ctx in self._contexts.values()
        ]


def _load_character(root: Path, entry: dict[str, Any]) -> tuple[str, CharacterContext | None]:
    """Return (id, context) for one registry entry; context is None when disabled."""
    char_id = str(entry.get("id") or "").strip()
    if not _ID_RE.fullmatch(char_id):
        raise CharacterRegistryError(f"Invalid character id in registry: {char_id!r}")
    rel_config = str(entry.get("config") or "").strip()
    config_path = _safe_child(root, rel_config, what="character config")
    if not config_path.is_file():
        raise CharacterRegistryError(f"Character {char_id!r} config missing: {rel_config!r}")
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CharacterRegistryError(f"Character {char_id!r} config is not valid JSON: {exc}") from exc
    if config.get("id") != char_id:
        raise CharacterRegistryError(f"Character pack id {config.get('id')!r} does not match registry id {char_id!r}")
    if config.get("schema_version") != 1:
        raise CharacterRegistryError(f"Character {char_id!r} must use schema_version 1.")
    enabled = bool(config.get("enabled", True))

    pack_dir = config_path.parent
    references = config.get("references") or {}
    reference_mode = str(references.get("reference_mode") or "").strip()
    if reference_mode not in VALID_REFERENCE_MODES:
        raise CharacterRegistryError(
            f"Character {char_id!r} has invalid reference_mode {reference_mode!r} "
            f"(allowed: {', '.join(sorted(VALID_REFERENCE_MODES))})."
        )
    environment_policy = str(config.get("environment_policy") or "").strip()
    if environment_policy not in VALID_ENVIRONMENT_POLICIES:
        raise CharacterRegistryError(
            f"Character {char_id!r} has invalid environment_policy {environment_policy!r} "
            f"(allowed: {', '.join(sorted(VALID_ENVIRONMENT_POLICIES))})."
        )

    sheet_rel = str(references.get("canonical_sheet") or "").strip()
    sheet_path = _safe_child(pack_dir, sheet_rel, what="canonical_sheet")
    required = bool(references.get("required", True))
    if required and not sheet_path.is_file():
        raise CharacterRegistryError(f"Character {char_id!r} is missing required reference sheet: {sheet_rel!r}")

    prompt_files = config.get("prompt_files") or {}
    prompts: dict[str, str] = {}
    for key in ("appearance", "behavior", "negative"):
        rel = str(prompt_files.get(key) or "").strip()
        if not rel:
            raise CharacterRegistryError(f"Character {char_id!r} is missing prompt_files.{key}")
        prompt_path = _safe_child(pack_dir, rel, what=f"prompt_files.{key}")
        if not prompt_path.is_file():
            raise CharacterRegistryError(f"Character {char_id!r} prompt file missing: {rel!r}")
        prompts[key] = _read_prompt(prompt_path)

    profile = config.get("selection_profile") or {}
    context = CharacterContext(
        id=char_id,
        display_name=str(config.get("display_name") or char_id),
        version=int(config.get("version") or 1),
        archetype=str(profile.get("archetype") or ""),
        tone=tuple(str(item) for item in profile.get("tone") or ()),
        strong_topics=tuple(str(item) for item in profile.get("strong_topics") or ()),
        environment_affinities=tuple(str(item) for item in profile.get("environment_affinities") or ()),
        environment_policy=environment_policy,
        reference_mode=reference_mode,
        sheet_path=sheet_path,
        sheet_sha256=_sha256(sheet_path) if sheet_path.is_file() else "",
        appearance_full=prompts["appearance"],
        behavior=prompts["behavior"],
        negative_constraints=prompts["negative"],
        selection_profile=dict(profile),
    )
    return char_id, context if enabled else None


@lru_cache(maxsize=None)
def _load_registry_cached(registry_path_str: str, mtime_ns: int) -> CharacterRegistry:
    registry_path = Path(registry_path_str)
    root = registry_path.parent
    try:
        payload = json.loads(registry_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CharacterRegistryError(f"Character registry is not valid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise CharacterRegistryError("Character registry root must be a JSON object.")
    if payload.get("schema_version") != 1:
        raise CharacterRegistryError("Character registry must use schema_version 1.")
    entries = payload.get("characters")
    if not isinstance(entries, list) or not entries:
        raise CharacterRegistryError("Character registry has no characters.")

    contexts: dict[str, CharacterContext] = {}
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise CharacterRegistryError("Every character registry entry must be an object.")
        char_id, context = _load_character(root, entry)
        if char_id in seen:
            raise CharacterRegistryError(f"Duplicate character id in registry: {char_id!r}")
        seen.add(char_id)
        if context is not None:
            contexts[char_id] = context

    fallback = str(payload.get("auto_fallback_character_id") or "").strip()
    legacy_default = str(payload.get("legacy_default_character_id") or "").strip()
    if fallback not in contexts:
        raise CharacterRegistryError(f"auto_fallback_character_id {fallback!r} is not an enabled character.")
    if legacy_default not in contexts:
        raise CharacterRegistryError(f"legacy_default_character_id {legacy_default!r} is not an enabled character.")

    return CharacterRegistry(
        root=root,
        default_selection_mode=str(payload.get("default_selection_mode") or "auto").strip().lower(),
        auto_fallback_character_id=fallback,
        legacy_default_character_id=legacy_default,
        _contexts=contexts,
    )


def load_character_registry(registry_path: Path) -> CharacterRegistry:
    """Load + validate a registry, caching on (path, mtime) so packs are parsed once."""
    registry_path = registry_path.resolve()
    if not registry_path.is_file():
        raise CharacterRegistryError(f"Character registry not found: {registry_path}")
    registry = _load_registry_cached(str(registry_path), registry_path.stat().st_mtime_ns)
    if registry.default_selection_mode != "auto":
        raise CharacterRegistryError("default_selection_mode must be 'auto'.")
    return registry


def parse_selector_output(raw: Any, registry: CharacterRegistry) -> CharacterResolution | None:
    """Turn Auto-selector output into a resolution, or None if it cannot be trusted.

    Returning None (not raising) lets the caller apply the deterministic fallback for
    malformed / disabled / unknown ids per the resolution rules.
    """
    data: Any = raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
    if not isinstance(data, dict):
        return None
    char_id = str(data.get("character_id") or "").strip()
    if not registry.has(char_id):
        return None
    ctx = registry.get(char_id)
    confidence = str(data.get("confidence") or "").strip().lower() or None
    if confidence not in ("high", "medium", "low"):
        return None
    reason = str(data.get("reason") or "").strip() or None
    if not reason:
        return None
    reason = " ".join(reason.split())[:240]
    return CharacterResolution(
        requested_mode="auto",
        resolved_character_id=char_id,
        source=SOURCE_AUTO,
        confidence=confidence,
        reason=reason,
        character_version=ctx.version,
        sheet_sha256=ctx.sheet_sha256,
    )


def resolve_character(
    registry: CharacterRegistry,
    *,
    persisted: dict[str, Any] | None = None,
    requested_mode: str | None = None,
    requested_character_id: str | None = None,
    is_legacy_run: bool = False,
    run_auto_selector=None,
) -> CharacterResolution:
    """Deterministic Auto/manual/resume resolution (spec §12).

    Order: (1) reuse persisted resolution; (2) legacy pre-character run → legacy default;
    (3) manual → validate exactly, never swap; (4) auto → selector once, else fallback.
    ``run_auto_selector`` is a zero-arg callable returning raw selector output; it is
    invoked at most once and only when no persisted resolution exists.
    """
    # 1. A persisted resolved id is authoritative: never rerun Auto on resume/retry.
    if persisted:
        resolved_id = str(persisted.get("resolved_character_id") or "").strip()
        if resolved_id:
            ctx = registry.get(resolved_id)
            return CharacterResolution(
                requested_mode=str(persisted.get("requested_mode") or requested_mode or "auto"),
                requested_character_id=persisted.get("requested_character_id"),
                resolved_character_id=resolved_id,
                source=str(persisted.get("resolution_source") or SOURCE_AUTO),
                confidence=persisted.get("confidence"),
                reason=persisted.get("reason"),
                character_version=ctx.version,
                sheet_sha256=ctx.sheet_sha256,
            )

    mode = (requested_mode or registry.default_selection_mode or "auto").strip().lower()
    if mode not in {"auto", "manual"}:
        raise CharacterSelectionError(f"Unknown character selection mode: {mode!r}.")

    # 2. Historical run predating characters → deterministic legacy default (Farmer).
    if is_legacy_run and not requested_character_id and mode != "manual":
        ctx = registry.get(registry.legacy_default_character_id)
        return CharacterResolution(
            requested_mode=mode,
            resolved_character_id=ctx.id,
            source=SOURCE_LEGACY_DEFAULT,
            character_version=ctx.version,
            sheet_sha256=ctx.sheet_sha256,
        )

    # 3. Manual → validate exactly; an invalid manual id is an error, never a swap.
    if mode == "manual" or requested_character_id:
        char_id = str(requested_character_id or "").strip()
        if not char_id:
            raise CharacterSelectionError("Manual character selection requires a character_id.")
        if not registry.has(char_id):
            raise CharacterSelectionError(
                f"Requested character {char_id!r} is not an enabled Q Station character "
                f"(enabled: {', '.join(registry.enabled_ids())})."
            )
        ctx = registry.get(char_id)
        return CharacterResolution(
            requested_mode="manual",
            requested_character_id=char_id,
            resolved_character_id=char_id,
            source=SOURCE_MANUAL,
            character_version=ctx.version,
            sheet_sha256=ctx.sheet_sha256,
        )

    # 4. Auto → run the selector exactly once; fall back deterministically on any failure.
    if run_auto_selector is not None:
        try:
            raw = run_auto_selector()
        except Exception:
            raw = None
        resolution = parse_selector_output(raw, registry) if raw is not None else None
        if resolution is not None:
            return resolution

    ctx = registry.get(registry.auto_fallback_character_id)
    return CharacterResolution(
        requested_mode="auto",
        resolved_character_id=ctx.id,
        source=SOURCE_AUTO_FALLBACK,
        reason="Auto selector unavailable or returned an unusable choice; used deterministic fallback.",
        character_version=ctx.version,
        sheet_sha256=ctx.sheet_sha256,
    )
