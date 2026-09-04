#!/usr/bin/env python3
"""Flow reference policy — the single source of truth for what Google Flow may receive.

Absolute rules (master_prompt §12-16, §41, §61 + user workflow decision 2026-09-03):

  * Flow NEVER receives a style sheet. Not the world style anchor, not a home/environment
    style sheet, not a mood board, not a previous image used as a style reference.
  * Flow's two reference modes are mutually exclusive — the live composer exposes
    ``Frames | Ingredients`` as one tablist with a single active option (verified
    2026-09-04). A clip therefore uses either frame slots or ingredient chips, never both:
        Clip A (question spark) -> Ingredients: character_sheet
        Clip B (book -> world)  -> Frames: first_frame=book_spread_frame,
                                            last_frame=world_keyframe
  * Clip B has no characters at all (see
    prompts/reference/book_transition_reference_prompt.txt), so no character sheet is sent
    there. The book's locked identity reaches Clip B through the composited
    ``book_spread_frame`` rather than through a separate ingredient, which is what the
    exclusive mode allows.
  * ``book_design_sheet`` remains an allowed canonical role: it is the Gemini-side reference
    used to compose that spread, and it stays in the vocabulary so a future
    Ingredients-mode book shot can use it directly.
  * Frame inputs are job content, not style references.

Every place that builds a Flow job must go through this module. `content_projects`
re-exports these helpers so there is only one definition of the policy.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal, Sequence

Clip = Literal["A", "B"]

# ---------------------------------------------------------------------------
# Role vocabulary
# ---------------------------------------------------------------------------

#: Canonical recurring reference sheets Flow is allowed to receive, per clip.
CLIP_CANONICAL_ROLE: dict[str, str] = {
    "A": "character_sheet",
    "B": "book_design_sheet",
}

#: Every canonical sheet role Flow may ever receive.
ALLOWED_CANONICAL_ROLES = frozenset(CLIP_CANONICAL_ROLE.values())

#: Job-specific scene frame inputs (Clip B only). Not style references.
ALLOWED_FRAME_ROLES = frozenset({"first_frame", "last_frame"})

#: The complete allow-list.
ALLOWED_ROLES = ALLOWED_CANONICAL_ROLES | ALLOWED_FRAME_ROLES

#: Roles that must never reach Flow. Rejection is a hard failure, never a warning.
FORBIDDEN_ROLES = frozenset({
    "style",
    "style_sheet",
    "style_anchor",
    "style_board",
    "home_style",
    "home_style_sheet",
    "home_style_anchor",
    "home_world_style_anchor",
    "world_style",
    "world_style_sheet",
    "world_style_anchor",
    "environment_sheet",
    "environment_style",
    "book_anchor",
    "book_style",
    "book_style_sheet",
    "mood_board",
    "moodboard",
    "visual_style_anchor",
    "previous_image_style",
})

#: Filename fragments that identify a style sheet even when the role label is missing.
FORBIDDEN_NAME_TOKENS = (
    "style_anchor",
    "style_sheet",
    "stylesheet",
    "world_style",
    "home_style",
    "book_anchor",
    "book_style",
    "mood_board",
    "moodboard",
    "style_board",
)

# Backwards-compatible aliases used by earlier code/tests.
FORBIDDEN_FLOW_ROLES = FORBIDDEN_ROLES
ALLOWED_CANONICAL = CLIP_CANONICAL_ROLE["A"]
ALLOWED_ALL = ALLOWED_ROLES


class FlowReferencePolicyError(ValueError):
    """Raised when a Flow job would violate the reference policy."""


def normalize_role(role: str) -> str:
    return str(role).strip().lower().replace(" ", "_").replace("-", "_")


def _looks_like_style(role: str) -> bool:
    return any(token in role for token in ("style", "anchor", "board", "mood"))


def validate_flow_roles(roles: Sequence[str]) -> list[str]:
    """Validate a Flow role list. Returns the normalized roles, or raises."""
    normalized = [normalize_role(role) for role in roles]

    forbidden = [role for role in normalized if role in FORBIDDEN_ROLES]
    if forbidden:
        raise FlowReferencePolicyError(
            "Flow style-sheet upload is FORBIDDEN (master_prompt §12-16, §61). "
            f"Rejected roles: {forbidden}. Allowed: {sorted(ALLOWED_ROLES)}."
        )

    for role in normalized:
        if role in ALLOWED_ROLES:
            continue
        if _looks_like_style(role):
            raise FlowReferencePolicyError(
                f"Flow reference role {role!r} looks like a style sheet — FORBIDDEN (§61)."
            )
        raise FlowReferencePolicyError(
            f"Flow reference role {role!r} is not allowed. Allowed: {sorted(ALLOWED_ROLES)}."
        )

    duplicates = {role for role in normalized if normalized.count(role) > 1}
    if duplicates:
        raise FlowReferencePolicyError(
            f"Duplicate Flow reference roles are not allowed: {sorted(duplicates)}."
        )

    if "A" in CLIP_CANONICAL_ROLE:  # structural guard, keeps the invariant explicit
        canonical = [role for role in normalized if role in ALLOWED_CANONICAL_ROLES]
        if len(canonical) > 1:
            raise FlowReferencePolicyError(
                f"Flow may receive only one canonical reference sheet; got {canonical}."
            )

    return normalized


def canonical_role_for_clip(clip: Clip) -> str:
    try:
        return CLIP_CANONICAL_ROLE[str(clip).upper()]
    except KeyError:
        raise FlowReferencePolicyError(f"clip must be 'A' or 'B', got {clip!r}") from None


def clip_a_roles(*, has_character_sheet: bool = True) -> list[str]:
    """Clip A (question spark): character sheet only (§15)."""
    roles = ["character_sheet"] if has_character_sheet else []
    return validate_flow_roles(roles)


def clip_b_roles(
    *,
    has_first_frame: bool = True,
    has_last_frame: bool = True,
) -> list[str]:
    """Clip B (book -> world): the two scene frames only (§16).

    Frames mode and Ingredients mode are mutually exclusive in the Flow composer, so Clip B
    cannot carry a canonical sheet alongside its frames. The book identity arrives inside the
    composited first frame instead.
    """
    roles: list[str] = []
    if has_first_frame:
        roles.append("first_frame")
    if has_last_frame:
        roles.append("last_frame")
    return validate_flow_roles(roles)


def assert_no_style_sheet_in_references(references: Sequence[Path | str]) -> None:
    """Guard generic reference lists against style-sheet leakage into Flow (§41)."""
    for ref in references:
        name = str(ref).lower()
        for token in FORBIDDEN_NAME_TOKENS:
            if token in name:
                raise FlowReferencePolicyError(
                    f"Reference {ref!r} looks like a style sheet — never send it to Flow (§41)."
                )


def _require_file(path: Path | None, role: str) -> Path:
    if path is None or not Path(path).is_file():
        raise FileNotFoundError(f"Flow {role} asset is missing: {path}")
    return Path(path)


def build_flow_uploads(
    *,
    clip: Clip,
    character_sheet: Path | None = None,
    book_design_sheet: Path | None = None,
    book_spread_frame: Path | None = None,
    world_keyframe: Path | None = None,
) -> list[tuple[str, Path]]:
    """Return the validated ``(role, path)`` upload list for a Flow clip.

    Raises FileNotFoundError when a required asset is missing and
    FlowReferencePolicyError when the resulting role set would break the policy.
    """
    clip_key = str(clip).upper()
    uploads: list[tuple[str, Path]] = []

    if clip_key == "A":
        uploads.append(("character_sheet", _require_file(character_sheet, "character_sheet")))
    elif clip_key == "B":
        # Frames mode excludes ingredient chips, so Clip B sends only its two frames. The
        # book identity is already baked into the composited first frame.
        uploads.append(("first_frame", _require_file(book_spread_frame, "first_frame (book_spread_frame)")))
        uploads.append(("last_frame", _require_file(world_keyframe, "last_frame (world_keyframe)")))
    else:
        raise FlowReferencePolicyError(f"clip must be 'A' or 'B', got {clip!r}")

    validate_flow_roles([role for role, _ in uploads])
    assert_no_style_sheet_in_references([path for _, path in uploads])
    return uploads


__all__ = [
    "Clip",
    "CLIP_CANONICAL_ROLE",
    "ALLOWED_CANONICAL_ROLES",
    "ALLOWED_FRAME_ROLES",
    "ALLOWED_ROLES",
    "FORBIDDEN_ROLES",
    "FORBIDDEN_NAME_TOKENS",
    "FlowReferencePolicyError",
    "normalize_role",
    "validate_flow_roles",
    "canonical_role_for_clip",
    "clip_a_roles",
    "clip_b_roles",
    "assert_no_style_sheet_in_references",
    "build_flow_uploads",
]
