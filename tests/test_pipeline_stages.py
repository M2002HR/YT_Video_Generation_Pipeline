"""The user-visible pipeline has one stable stage taxonomy end to end."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from pipeline_stages import PIPELINE_STAGE_SEQUENCE, stage_title  # noqa: E402


def test_independent_post_visual_work_has_its_own_visible_stage() -> None:
    expected = {
        "elevenlabs_voiceover", "background_music", "ajil_alignment", "opening_trim",
        "build_timeline", "render_baseline", "qc_baseline", "polish_audio", "qc_polished",
        "git_commit_push", "publish_telegram",
    }
    assert expected <= set(PIPELINE_STAGE_SEQUENCE)
    assert len(PIPELINE_STAGE_SEQUENCE) == len(set(PIPELINE_STAGE_SEQUENCE))


def test_titles_use_the_global_count_for_visual_and_render_stages() -> None:
    total = len(PIPELINE_STAGE_SEQUENCE)
    assert stage_title("body_images") == f"step 14/{total} · Body Images"
    assert stage_title("render_baseline") == f"step 22/{total} · Render Baseline"
