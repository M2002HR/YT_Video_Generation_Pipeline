from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from shorts_v2.contracts import ContractError
from shorts_v2.presentation import (
    build_caption_plan, build_layout_constraints, build_overlay_plan,
    build_sound_plan, compile_presentation,
)


def words() -> list[dict]:
    values = ["Wait", "—", "you", "do", "not", "fall", "slower", "here."]
    return [{"word_id": f"u.one.w{i:04d}", "canonical_text": text, "start": i * .25,
             "end": i * .25 + .2} for i, text in enumerate(values)]


def timeline() -> dict:
    return {
        "schema_version": 1, "compile_hash": "a" * 64, "total_frames": 60,
        "clock": {"fps_num": 30, "fps_den": 1, "audio_samples": 96000, "sample_rate": 48000, "interval": "half_open"},
        "resolution": {"width": 1080, "height": 1920},
        "segments": [{"shot_id": "shot.001", "start_frame": 0, "end_frame": 30}, {"shot_id": "shot.002", "start_frame": 30, "end_frame": 60}],
        "transitions": [],
    }


def test_t43_caption_can_cross_a_cut_and_never_contains_performance_markup() -> None:
    caption = build_caption_plan(words=words(), mode="phrase", enabled=True, max_words=8,
                                 style={"font": "DejaVu Sans", "size": 64, "color": "#ffffff", "outline": 4, "position": "bottom"},
                                 manual_locks={"color": True}, emphasis_word_ids=["u.one.w0004"])
    assert len(caption["cues"]) == 1
    assert caption["cues"][0]["start"] < 1 < caption["cues"][0]["end"]
    assert "[" not in caption["cues"][0]["text"] and "<break" not in caption["cues"][0]["text"]
    assert caption["cues"][0]["emphasis_word_ids"] == ["u.one.w0004"]


def test_t55_caption_off_is_real_and_style_only_preserves_media_dependencies() -> None:
    off = build_caption_plan(words=words(), mode="off", enabled=False, max_words=4,
                             style={}, manual_locks={}, emphasis_word_ids=[])
    assert off["enabled"] is False and off["cues"] == []
    assert off["burn_in_required"] is False


def test_layout_and_overlay_honor_user_locks_and_do_not_duplicate_title() -> None:
    layout = build_layout_constraints(width=1080, height=1920, preset="vertical_safe_v1",
                                      ai={"subtitle_y": .7, "title_y": .2}, user={"subtitle_y": .82},
                                      manual_locks={"subtitle_y": True})
    assert layout["effective"]["subtitle_y"] == .82
    overlay = build_overlay_plan(title="Gravity Vanishes", title_range=[0, 30], watermark="Q Station",
                                 watermark_range=[0, 60], total_frames=60, already_branded=False)
    assert len(overlay["overlays"]) == 2
    with pytest.raises(ContractError, match="already branded"):
        build_overlay_plan(title="Again", title_range=[0, 30], watermark=None,
                           watermark_range=None, total_frames=60, already_branded=True)


def test_t56_t57_t58_sound_disable_gain_and_music_dependency_semantics() -> None:
    gain = build_sound_plan(narration_gain_db=2.5, music=None, sfx_enabled=False, sfx_cues=[],
                            music_driven=False, rhythm_events=[])
    assert gain["provider_calls"] == {"tts": 0, "image": 0, "flow": 0, "sfx": 0}
    assert gain["video_stream_policy"] == "reuse"
    assert gain["sfx_status"] == "disabled_no_hidden_effect"
    music = {"path": "music/track.mp3", "sha256": "b" * 64, "license": "CC0", "source": "user_library", "duration_seconds": 30}
    plan = build_sound_plan(narration_gain_db=0, music=music, sfx_enabled=False, sfx_cues=[],
                            music_driven=False, rhythm_events=[])
    assert plan["edit_invalidation"] == "none_music_follows_edit"
    driven = build_sound_plan(narration_gain_db=0, music=music, sfx_enabled=False, sfx_cues=[],
                              music_driven=True, rhythm_events=[{"event_id": "rhythm.1"}], music_features={"beats": [0.5]})
    assert driven["edit_invalidation"] == "rhythm_and_edit"


def test_t62_preview_and_final_share_clock_layout_and_audible_compile() -> None:
    caption = build_caption_plan(words=words(), mode="phrase", enabled=True, max_words=8,
                                 style={"font": "DejaVu Sans", "size": 64, "color": "#ffffff", "outline": 4, "position": "bottom"},
                                 manual_locks={}, emphasis_word_ids=[])
    layout = build_layout_constraints(width=1080, height=1920, preset="vertical_safe_v1", ai={}, user={}, manual_locks={})
    overlay = build_overlay_plan(title=None, title_range=None, watermark=None, watermark_range=None, total_frames=60, already_branded=False)
    sound = build_sound_plan(narration_gain_db=0, music=None, sfx_enabled=False, sfx_cues=[], music_driven=False, rhythm_events=[])
    compiled = compile_presentation(timeline(), caption_plan=caption, layout_constraints=layout,
                                    overlay_plan=overlay, sound_plan=sound)
    assert compiled["preview"]["parity_hash"] == compiled["final"]["parity_hash"]
    assert compiled["preview"]["audio_required"] is True and compiled["preview"]["seekable"] is True
    changed = copy.deepcopy(caption); changed["style"]["color"] = "#ff0000"
    restyled = compile_presentation(timeline(), caption_plan=changed, layout_constraints=layout,
                                    overlay_plan=overlay, sound_plan=sound)
    assert restyled["video_source_compile_hash"] == compiled["video_source_compile_hash"]
    assert restyled["presentation_hash"] != compiled["presentation_hash"]
