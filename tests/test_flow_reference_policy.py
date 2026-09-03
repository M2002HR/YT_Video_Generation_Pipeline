from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from flow_reference_policy import (  # noqa: E402
    ALLOWED_ROLES,
    FlowReferencePolicyError,
    assert_no_style_sheet_in_references,
    build_flow_uploads,
    canonical_role_for_clip,
    clip_a_roles,
    clip_b_roles,
    validate_flow_roles,
)

STYLE_ROLES = [
    "style",
    "style_sheet",
    "style_anchor",
    "home_style",
    "home_style_anchor",
    "world_style",
    "world_style_anchor",
    "book_anchor",
    "book_style",
    "mood_board",
    "style_board",
    "environment_sheet",
]


def test_canonical_role_per_clip():
    assert canonical_role_for_clip("A") == "character_sheet"
    assert canonical_role_for_clip("B") == "book_design_sheet"
    with pytest.raises(FlowReferencePolicyError):
        canonical_role_for_clip("C")


def test_clip_a_is_character_sheet_only():
    assert clip_a_roles() == ["character_sheet"]
    assert clip_a_roles(has_character_sheet=False) == []


def test_clip_b_is_book_sheet_plus_frames_without_character():
    roles = clip_b_roles()
    assert roles == ["book_design_sheet", "first_frame", "last_frame"]
    # Clip B carries no character: the character sheet is not part of its contract.
    assert "character_sheet" not in roles


@pytest.mark.parametrize("bad", STYLE_ROLES)
def test_every_style_role_is_rejected(bad):
    with pytest.raises(FlowReferencePolicyError):
        validate_flow_roles([bad])
    with pytest.raises(FlowReferencePolicyError):
        validate_flow_roles(["character_sheet", bad])
    with pytest.raises(FlowReferencePolicyError):
        validate_flow_roles(["book_design_sheet", "first_frame", "last_frame", bad])


def test_unknown_style_like_role_is_rejected():
    for bad in ("episode_style_ref", "world_anchor", "vibe_board", "mood"):
        with pytest.raises(FlowReferencePolicyError):
            validate_flow_roles([bad])


def test_two_canonical_sheets_rejected():
    with pytest.raises(FlowReferencePolicyError):
        validate_flow_roles(["character_sheet", "book_design_sheet"])


def test_duplicate_roles_rejected():
    with pytest.raises(FlowReferencePolicyError):
        validate_flow_roles(["first_frame", "first_frame"])


def test_allowed_roles_are_exactly_four():
    assert ALLOWED_ROLES == {
        "character_sheet",
        "book_design_sheet",
        "first_frame",
        "last_frame",
    }


def _touch(directory: Path, name: str) -> Path:
    path = directory / name
    path.write_bytes(b"fake-png-bytes")
    return path


def test_build_uploads_clip_a():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        char = _touch(d, "character_sheet.png")
        uploads = build_flow_uploads(clip="A", character_sheet=char)
        assert uploads == [("character_sheet", char)]
        with pytest.raises(FileNotFoundError):
            build_flow_uploads(clip="A", character_sheet=d / "missing.png")


def test_build_uploads_clip_b_requires_all_three():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        book_sheet = _touch(d, "book_design_sheet.png")
        spread = _touch(d, "book_spread_frame.png")
        world = _touch(d, "world_keyframe.png")

        uploads = build_flow_uploads(
            clip="B",
            book_design_sheet=book_sheet,
            book_spread_frame=spread,
            world_keyframe=world,
        )
        assert [role for role, _ in uploads] == ["book_design_sheet", "first_frame", "last_frame"]

        for kwargs in (
            {"book_design_sheet": d / "nope.png", "book_spread_frame": spread, "world_keyframe": world},
            {"book_design_sheet": book_sheet, "book_spread_frame": d / "nope.png", "world_keyframe": world},
            {"book_design_sheet": book_sheet, "book_spread_frame": spread, "world_keyframe": d / "nope.png"},
        ):
            with pytest.raises(FileNotFoundError):
                build_flow_uploads(clip="B", **kwargs)


def test_build_uploads_rejects_style_named_file():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        # A style anchor smuggled in under the canonical role must still be refused.
        sneaky = _touch(d, "world_style_anchor.png")
        with pytest.raises(FlowReferencePolicyError):
            build_flow_uploads(clip="A", character_sheet=sneaky)


def test_generic_reference_list_guard():
    assert_no_style_sheet_in_references([Path("/a/character_sheet.png"), Path("/a/book_design_sheet.png")])
    for bad in ("world_style_anchor.png", "style_anchor.png", "home_style_sheet.png", "mood_board.png"):
        with pytest.raises(FlowReferencePolicyError):
            assert_no_style_sheet_in_references([Path("/a") / bad])


def test_content_projects_reexports_same_policy():
    import content_projects as cp

    assert cp.FLOW_FORBIDDEN_REFERENCE_ROLES is not None
    assert cp.validate_flow_reference_roles(["character_sheet"]) == ["character_sheet"]
    with pytest.raises(FlowReferencePolicyError):
        cp.validate_flow_reference_roles(["world_style_anchor"])
    assert cp.build_flow_clip_references(clip="A") == ["character_sheet"]
    assert cp.build_flow_clip_references(
        clip="B", has_first_frame=True, has_last_frame=True
    ) == ["book_design_sheet", "first_frame", "last_frame"]
    with pytest.raises(FlowReferencePolicyError):
        cp.build_flow_clip_references(clip="A", has_first_frame=True)
