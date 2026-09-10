"""Subtitles must sit on the words that were spoken, and clear the platform UI (T9.8).

The cue timing comes from ``timing/WORD_TIMINGS.json`` when the aligner measured it. These
tests check the placement against those measurements — a caption within 0.1s of its own
words — and check the fallback path stays honest when no measurements exist.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from build_timeline import (
    LANDSCAPE_BOTTOM_SAFE_FRACTION,
    PORTRAIT_BOTTOM_SAFE_FRACTION,
    build_cues_from_words,
    build_subtitle_cues,
    caption_token,
    associate_subtitle_cues_with_beats,
    load_word_timings,
    normalize_subtitle_cue_boundaries,
    subtitle_margin_v,
    write_ass,
)

SUBTITLE_CFG = {
    "font_name": "DejaVu Sans",
    "font_size": 56,
    "max_words_per_cue": 3,
    "max_chars_per_line": 34,
    "max_lines": 2,
}

NARRATION = "The kettle boils again and steam clouds the cold window pane"


def _words(narration: str, *, start: float = 4.0, step: float = 0.4) -> list[dict[str, float]]:
    """Measured word timings, deliberately uneven so a proportional split cannot match."""
    words = []
    moment = start
    for index, word in enumerate(narration.split()):
        length = step * (1.6 if len(word) > 5 else 0.7)
        words.append({"token": caption_token(word), "start": round(moment, 3), "end": round(moment + length, 3)})
        moment += length + 0.05
    return words


def _beat(narration: str, words: list[dict[str, float]]) -> dict:
    return {
        "beat_id": 1,
        "narration": narration,
        "speech_start": words[0]["start"],
        "speech_end": words[-1]["end"],
        "match_confidence": 0.95,
    }


def test_every_cue_lands_on_its_own_words_within_a_tenth_of_a_second() -> None:
    words = _words(NARRATION)
    cues = build_subtitle_cues([_beat(NARRATION, words)], SUBTITLE_CFG, words)

    assert cues, "the narration must produce cues"
    # Walk the measured words in order: "the" occurs twice, so a token->word map would
    # compare the second cue against the wrong occurrence.
    cursor = 0
    for cue in cues:
        assert cue["timing_source"] == "word"
        span = words[cursor : cursor + len(cue["text"].split())]
        assert [word["token"] for word in span] == [caption_token(t) for t in cue["text"].split()]
        assert abs(cue["start"] - span[0]["start"]) < 0.1, cue
        assert abs(cue["end"] - span[-1]["end"]) < 0.1, cue
        cursor += len(span)
    assert cursor == len(words), "every measured word ends up in a caption"


def test_measured_cues_differ_from_the_proportional_estimate() -> None:
    """If they matched, the measurement would not be doing anything."""
    words = _words(NARRATION)
    beat = _beat(NARRATION, words)
    measured = build_subtitle_cues([beat], SUBTITLE_CFG, words)
    estimated = build_subtitle_cues([beat], SUBTITLE_CFG, [])

    assert [cue["text"] for cue in measured] == [cue["text"] for cue in estimated]
    assert any(
        abs(a["start"] - b["start"]) > 0.05 or abs(a["end"] - b["end"]) > 0.05
        for a, b in zip(measured, estimated)
    )
    assert all(cue["timing_source"] == "proportional" for cue in estimated)


def test_cues_stay_ordered_and_inside_the_beat() -> None:
    words = _words(NARRATION)
    cues = build_subtitle_cues([_beat(NARRATION, words)], SUBTITLE_CFG, words)
    for earlier, later in zip(cues, cues[1:]):
        assert earlier["end"] <= later["start"] + 1e-6
    assert cues[0]["start"] >= words[0]["start"] - 1e-6
    assert cues[-1]["end"] <= words[-1]["end"] + 1e-6


def test_a_word_the_transcriber_dropped_does_not_derail_the_rest() -> None:
    words = [word for word in _words(NARRATION) if word["token"] != "and"]
    cues = build_subtitle_cues([_beat(NARRATION, _words(NARRATION))], SUBTITLE_CFG, words)
    measured = [cue for cue in cues if cue["timing_source"] == "word"]
    assert len(measured) >= len(cues) - 1, "at most the affected cue falls back"


def test_a_chunk_that_cannot_be_located_falls_back_alone() -> None:
    narration = "alpha bravo charlie delta echo foxtrot"
    words = _words(narration)
    # Remove a whole chunk's worth of words: that chunk must estimate, the others must not.
    trimmed = [word for word in words if word["token"] not in {"delta", "echo", "foxtrot"}]
    cues = build_subtitle_cues([_beat(narration, words)], SUBTITLE_CFG, trimmed)
    sources = [cue["timing_source"] for cue in cues]
    assert "word" in sources and "proportional" in sources


def test_word_timings_are_loaded_from_the_aligner_artifact(tmp_path: Path) -> None:
    (tmp_path / "timing").mkdir()
    (tmp_path / "timing" / "WORD_TIMINGS.json").write_text(
        json.dumps({
            "schema_version": 1,
            "words": [
                {"text": "The", "token": "the", "start": 0.1, "end": 0.3},
                {"text": "kettle,", "token": "kettle", "start": 0.35, "end": 0.8},
                {"text": "  ", "token": "", "start": 0.9, "end": 1.0},
            ],
        }),
        encoding="utf-8",
    )
    loaded = load_word_timings(tmp_path)
    assert [word["token"] for word in loaded] == ["the", "kettle"], "empty tokens are dropped"
    assert loaded[1]["end"] == 0.8


def test_a_project_without_word_timings_loads_nothing(tmp_path: Path) -> None:
    assert load_word_timings(tmp_path) == []


def test_overlapping_whole_narration_word_cues_do_not_require_beat_ids() -> None:
    cues, adjustments = normalize_subtitle_cue_boundaries([
        {"start": 1.0, "end": 2.0, "text": "opening", "timing_source": "word"},
        {"start": 1.8, "end": 2.6, "text": "continues", "timing_source": "word"},
    ])
    assert cues[0]["end"] == cues[1]["start"] == 1.9
    assert adjustments == [{
        "previous_beat": None, "current_beat": None,
        "previous_cue": 0, "current_cue": 1,
        "previous_end": 2.0, "current_start": 1.8,
        "overlap_seconds": 0.2, "chosen_boundary": 1.9,
    }]


def test_whole_narration_word_cues_are_associated_with_their_media_beat() -> None:
    cues = [
        {"start": 0.2, "end": 1.1, "text": "opening"},
        {"start": 2.8, "end": 4.2, "text": "body"},
        # This cue straddles a cut; most of its spoken duration is in beat 2.
        {"start": 1.7, "end": 3.1, "text": "boundary"},
    ]
    associate_subtitle_cues_with_beats(cues, [
        {"beat_id": "video_opening_a", "start": 0.0, "end": 2.0},
        {"beat_id": 1, "start": 2.0, "end": 5.0},
    ])
    assert [cue["beat_id"] for cue in cues] == ["video_opening_a", 1, 1]


def test_the_bottom_margin_clears_the_shorts_ui_band() -> None:
    assert subtitle_margin_v({}, 1920) == round(1920 * PORTRAIT_BOTTOM_SAFE_FRACTION)
    assert subtitle_margin_v({}, 1080) == round(1080 * LANDSCAPE_BOTTOM_SAFE_FRACTION)
    assert subtitle_margin_v({}, 1920) > 90, "the old fixed margin sat inside the UI band"


def test_an_explicit_margin_is_still_respected() -> None:
    assert subtitle_margin_v({"margin_v": 120}, 1920) == 120
    assert subtitle_margin_v({"margin_v": 0}, 1920) == 0


def test_the_written_ass_carries_the_derived_margin(tmp_path: Path) -> None:
    words = _words(NARRATION)
    cues = build_subtitle_cues([_beat(NARRATION, words)], SUBTITLE_CFG, words)
    path = tmp_path / "SUBTITLES.ass"
    write_ass(path, width=1080, height=1920, subtitle_cfg=SUBTITLE_CFG, cues=cues)

    text = path.read_text(encoding="utf-8")
    style = next(line for line in text.splitlines() if line.startswith("Style: Default,"))
    assert style.split(",")[-2] == str(subtitle_margin_v(SUBTITLE_CFG, 1920))
    assert text.count("Dialogue: 0,") == len(cues)
    assert "0:00:04" in text, "the first cue starts where the first word was measured"


def test_measured_words_generate_a_word_by_word_karaoke_sweep(tmp_path: Path) -> None:
    words = _words("alpha bravo charlie", start=1.0, step=0.3)
    for word, text in zip(words, ["Alpha", "bravo", "charlie"]):
        word["text"] = text
    cues = build_cues_from_words(words, SUBTITLE_CFG)
    ass = tmp_path / "SUBTITLES.ass"
    write_ass(ass, width=1080, height=1920, subtitle_cfg=SUBTITLE_CFG, cues=cues)

    text = ass.read_text(encoding="utf-8")
    dialogue = next(line for line in text.splitlines() if line.startswith("Dialogue: 0,"))
    assert "Karaoke" in dialogue
    assert dialogue.count(r"{\kf") == 3
    assert r"{\kf" in dialogue and "Alpha" in dialogue and "bravo" in dialogue
    assert "Style: Karaoke," in text


def test_word_highlight_can_be_disabled_without_changing_plain_subtitles(tmp_path: Path) -> None:
    words = _words("alpha bravo", start=1.0, step=0.3)
    for word, text in zip(words, ["alpha", "bravo"]):
        word["text"] = text
    cues = build_cues_from_words(words, SUBTITLE_CFG)
    ass = tmp_path / "SUBTITLES.ass"
    cfg = {**SUBTITLE_CFG, "word_highlight": {"enabled": False}}
    write_ass(ass, width=1080, height=1920, subtitle_cfg=cfg, cues=cues)

    dialogue = next(line for line in ass.read_text(encoding="utf-8").splitlines() if line.startswith("Dialogue: 0,"))
    assert ",Default,," in dialogue
    assert r"{\kf" not in dialogue


def test_libass_accepts_the_generated_file(tmp_path: Path) -> None:
    """A file FFmpeg cannot parse would silently render a caption-free video."""
    words = _words(NARRATION)
    for word, text in zip(words, NARRATION.split()):
        word["text"] = text
    cues = build_cues_from_words(words, SUBTITLE_CFG)
    ass = tmp_path / "SUBTITLES.ass"
    write_ass(ass, width=240, height=426, subtitle_cfg=SUBTITLE_CFG, cues=cues)
    output = tmp_path / "burned.mp4"

    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc2=s=240x426:r=24:d=0.5",
         "-vf", f"ass=filename={ass}", "-t", "0.5",
         "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast", str(output)],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert output.stat().st_size > 0


def test_position_presets_move_the_margin_without_touching_explicit_values() -> None:
    from build_timeline import SUBTITLE_POSITION_FRACTIONS

    assert SUBTITLE_POSITION_FRACTIONS["low"] == 0.045
    assert SUBTITLE_POSITION_FRACTIONS["standard"] is None
    assert SUBTITLE_POSITION_FRACTIONS["high"] == 0.13
    assert subtitle_margin_v({"position": "low"}, 1920) == round(1920 * 0.045)
    assert subtitle_margin_v({"position": "high"}, 1920) == round(1920 * 0.13)
    assert subtitle_margin_v({"position": "standard"}, 1920) == subtitle_margin_v({}, 1920)
    assert subtitle_margin_v({"position": "low", "margin_v": 10}, 1920) == 10


def test_italic_and_panel_style_land_in_the_ass(tmp_path: Path) -> None:
    words = _words(NARRATION)
    cues = build_subtitle_cues([_beat(NARRATION, words)], SUBTITLE_CFG, words)
    cfg = {
        **SUBTITLE_CFG,
        "font_name": "Liberation Serif",
        "font_size": 64,
        "bold": False,
        "italic": True,
        "position": "high",
        "max_words_per_cue": 4,
    }
    path = tmp_path / "STYLED.ass"
    write_ass(path, width=1080, height=1920, subtitle_cfg=cfg, cues=cues)

    text = path.read_text(encoding="utf-8")
    style = next(line for line in text.splitlines() if line.startswith("Style: Default,"))
    parts = style.split(",")
    assert parts[1] == "Liberation Serif"
    assert parts[2] == "64"
    assert parts[7] == "0", "bold off must clear the Bold flag"
    assert parts[8] == "-1", "italic on must set the Italic flag"
    assert parts[-2] == str(subtitle_margin_v(cfg, 1920))


def test_apply_subtitle_style_copies_panel_keys_and_rejects_garbage() -> None:
    from run_full_video_pipeline import apply_subtitle_style

    subtitles: dict = {}
    apply_subtitle_style(subtitles, {
        "font_name": "Nimbus Sans", "font_size": 64, "bold": False, "italic": True,
        "position": "low", "max_words_per_cue": 4,
    })
    assert subtitles == {
        "font_name": "Nimbus Sans", "font_size": 64, "bold": False, "italic": True,
        "position": "low", "max_words_per_cue": 4,
    }
    apply_subtitle_style(subtitles, {})
    assert subtitles["font_name"] == "Nimbus Sans", "empty style must not clobber"
    with pytest.raises(ValueError):
        apply_subtitle_style({}, {"font_size": 200})
    with pytest.raises(ValueError):
        apply_subtitle_style({}, {"max_words_per_cue": 0})
    with pytest.raises(ValueError):
        apply_subtitle_style({}, {"position": "top"})


def test_custom_offsets_become_pixel_margins_with_clamps() -> None:
    assert subtitle_margin_v({"position": "custom", "custom_offset_value": 10, "custom_offset_unit": "percent"}, 1920) == 192
    assert subtitle_margin_v({"position": "custom", "custom_offset_value": 200, "custom_offset_unit": "px"}, 1920) == 200
    assert subtitle_margin_v({"position": "custom", "custom_offset_value": 99, "custom_offset_unit": "percent"}, 1920) == round(1920 * 0.4)
    assert subtitle_margin_v({"position": "custom", "custom_offset_value": 5000, "custom_offset_unit": "px"}, 1920) == round(1920 * 0.5)
    assert subtitle_margin_v({"position": "custom", "custom_offset_value": "bogus", "custom_offset_unit": "percent"}, 1920) == 192


def test_css_hex_colours_land_in_both_ass_styles(tmp_path: Path) -> None:
    from build_timeline import css_hex_to_ass

    assert css_hex_to_ass("#FFD700", "dflt") == "&H0000D7FF"
    assert css_hex_to_ass("#000000", "dflt") == "&H00000000"
    assert css_hex_to_ass("bogus", "dflt") == "dflt"
    words = _words(NARRATION)
    cues = build_subtitle_cues([_beat(NARRATION, words)], SUBTITLE_CFG, words)
    cfg = {**SUBTITLE_CFG, "font_colour": "#00E5FF", "outline": 0, "outline_colour": "#123456"}
    path = tmp_path / "COLOURED.ass"
    write_ass(path, width=1080, height=1920, subtitle_cfg=cfg, cues=cues)

    text = path.read_text(encoding="utf-8")
    default = next(line for line in text.splitlines() if line.startswith("Style: Default,"))
    karaoke = next(line for line in text.splitlines() if line.startswith("Style: Karaoke,"))
    assert ",&H00FFE500," in default, "text colour must reach the Default primary"
    assert ",&H00FFE500," in karaoke, "text colour must remain visible with word highlight"
    assert ",0.0," in default, "outline 0 must switch the outline off"
    assert ",&H00563412," in default and ",&H00563412," in karaoke


def test_apply_subtitle_style_validates_colours_and_outline() -> None:
    from run_full_video_pipeline import apply_subtitle_style

    subtitles: dict = {}
    apply_subtitle_style(subtitles, {"font_colour": "#ffd700", "outline": 0, "outline_colour": "#123456"})
    assert subtitles == {"font_colour": "#FFD700", "outline": 0.0, "outline_colour": "#123456"}
    for bad in ({"font_colour": "gold"}, {"outline_colour": "#12345"}, {"outline": 9}, {"custom_offset_unit": "em"}):
        with pytest.raises(ValueError):
            apply_subtitle_style({}, bad)
