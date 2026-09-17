from __future__ import annotations
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from run_q_station_pipeline import episode_frame_contract

@pytest.mark.parametrize("legacy_frame", ["deckled-paper border", "painted card and inner window", "manuscript border", "circular telescope mask"])
def test_frame_contract_replaces_enclosing_layout_but_not_the_medium(legacy_frame):
    prompt = episode_frame_contract({"frame_language": legacy_frame, "medium": "ink", "reserve_subtitle_space": False})
    assert "[VISUAL_CONTRACT:topic_world_v2]" in prompt
    assert "full usable height" in prompt
    assert "Preserve this recurring frame language" not in prompt
    assert f"image: {legacy_frame}" not in prompt
    assert "rendering textures" in prompt

def test_frame_contract_has_full_bleed_default():
    assert "entire 9:16 canvas" in episode_frame_contract({})

def test_frame_contract_does_not_reserve_space_when_disabled():
    assert "Do not reserve a lower caption field" in episode_frame_contract({"reserve_subtitle_space": False})

def test_frame_contract_keeps_optional_caption_field_small_and_unprinted():
    result = episode_frame_contract({"reserve_subtitle_space": True})
    assert "bottom 8-10%" in result and "No printed text" in result
