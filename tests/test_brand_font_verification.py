"""Burned ASS families must resolve to a real font before the long render.

libass silently substitutes a fallback face, so an unresolvable upload would
otherwise render a full episode in the wrong font with a passing pipeline.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from render_video import _ass_font_families, verify_ass_fonts


def _ass(tmp_path: Path, name: str, family: str) -> Path:
    path = tmp_path / name
    path.write_text(
        "[V4+ Styles]\n"
        "Format: Name,Fontname,Fontsize\n"
        f"Style: Default,{family},40\n",
        encoding="utf-8",
    )
    return path


def test_ass_font_families_reads_style_lines(tmp_path: Path) -> None:
    path = _ass(tmp_path, "A.ass", "DejaVu Sans")
    assert _ass_font_families(path) == {"DejaVu Sans"}
    assert _ass_font_families(tmp_path / "missing.ass") == set()


def test_verify_ass_fonts_accepts_installed_face(tmp_path: Path) -> None:
    # DejaVu ships with virtually every fontconfig install, including CI hosts.
    verify_ass_fonts([_ass(tmp_path, "A.ass", "DejaVu Sans")], tmp_path)


def test_verify_ass_fonts_rejects_unknown_family(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unavailable font"):
        verify_ass_fonts([_ass(tmp_path, "A.ass", "No Such Font XYZ")], tmp_path)


def test_verify_ass_fonts_names_the_source_file(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="SUBTITLES.ass"):
        verify_ass_fonts([_ass(tmp_path, "SUBTITLES.ass", "No Such Font XYZ")], tmp_path)
