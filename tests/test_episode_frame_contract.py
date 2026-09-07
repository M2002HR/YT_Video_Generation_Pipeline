"""The visual frame system must survive independently-written beat prompts."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_question_harvest_pipeline as qh


def test_episode_frame_contract_keeps_a_balanced_lower_caption_field() -> None:
    contract = qh.episode_frame_contract(
        {
            "frame_language": "a fibrous deckled-paper border around a painted inner window",
            "subtitle_reserve": "a quiet lower field occupying 15% of the vertical frame",
        }
    )
    assert "NON-NEGOTIABLE" in contract
    assert "deckled-paper border" in contract
    assert "15%" in contract
    assert "faces, hands, focal action" in contract


def test_episode_frame_contract_has_safe_defaults_for_older_style_plans() -> None:
    contract = qh.episode_frame_contract({})
    assert "8–10%" in contract
    assert "recurring outer material" in contract
