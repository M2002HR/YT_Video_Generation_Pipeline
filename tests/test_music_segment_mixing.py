"""The mixer must consume ``music.segments``, not just a single ``music.file``.

MUSIC_PLAN.json has always been a segment list so a second cue could be added by appending
an entry. The mixer only read ``music.file``, so appending that entry would have produced a
plan nobody played.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from polish_audio import music_segment_inputs  # noqa: E402


@pytest.fixture()
def video(tmp_path: Path) -> Path:
    music = tmp_path / "assets" / "music"
    music.mkdir(parents=True)
    for name in ("bed.mp3", "second.mp3"):
        (music / name).write_bytes(b"ID3" + b"0" * 32)
    return tmp_path


def test_a_single_file_becomes_one_full_length_segment(video: Path) -> None:
    entries = music_segment_inputs(video, {"file": "assets/music/bed.mp3"}, 28.0)
    assert len(entries) == 1
    assert entries[0]["start"] == 0.0
    assert entries[0]["end"] == 28.0
    assert entries[0]["file"].name == "bed.mp3"


def test_two_segments_keep_their_windows_and_order(video: Path) -> None:
    entries = music_segment_inputs(video, {"segments": [
        {"segment_id": "b", "start_seconds": 12.0, "end_seconds": 28.0, "file": "assets/music/second.mp3"},
        {"segment_id": "a", "start_seconds": 0.0, "end_seconds": 12.0, "file": "assets/music/bed.mp3"},
    ]}, 28.0)
    assert [entry["file"].name for entry in entries] == ["bed.mp3", "second.mp3"]
    assert [(entry["start"], entry["end"]) for entry in entries] == [(0.0, 12.0), (12.0, 28.0)]


def test_a_segment_is_clamped_to_the_render_length(video: Path) -> None:
    entries = music_segment_inputs(video, {"segments": [
        {"segment_id": "a", "start_seconds": 0.0, "end_seconds": 99.0, "file": "assets/music/bed.mp3"},
    ]}, 28.0)
    assert entries[0]["end"] == 28.0


def test_an_open_ended_segment_runs_to_the_end(video: Path) -> None:
    entries = music_segment_inputs(video, {"segments": [
        {"segment_id": "a", "start_seconds": 0.0, "file": "assets/music/bed.mp3"},
    ]}, 28.0)
    assert entries[0]["end"] == 28.0


def test_per_segment_gain_and_fades_override_the_profile(video: Path) -> None:
    entries = music_segment_inputs(video, {
        "gain_db": -20.0, "fade_in_sec": 0.8, "fade_out_sec": 1.4,
        "segments": [{"segment_id": "a", "start_seconds": 0.0, "end_seconds": 28.0,
                      "file": "assets/music/bed.mp3", "gain_db": -14.0,
                      "fade_in_seconds": 0.2, "fade_out_seconds": 3.0}],
    }, 28.0)
    assert entries[0]["gain_db"] == -14.0
    assert entries[0]["fade_in"] == 0.2
    assert entries[0]["fade_out"] == 3.0


def test_the_profile_supplies_defaults_a_segment_omits(video: Path) -> None:
    entries = music_segment_inputs(video, {
        "gain_db": -16.0, "fade_in_sec": 0.3,
        "segments": [{"segment_id": "a", "start_seconds": 0.0, "end_seconds": 28.0,
                      "file": "assets/music/bed.mp3"}],
    }, 28.0)
    assert entries[0]["gain_db"] == -16.0
    assert entries[0]["fade_in"] == 0.3


def test_a_missing_segment_file_is_an_error_not_a_gap(video: Path) -> None:
    with pytest.raises(FileNotFoundError):
        music_segment_inputs(video, {"segments": [
            {"segment_id": "a", "start_seconds": 0.0, "end_seconds": 28.0,
             "file": "assets/music/absent.mp3"},
        ]}, 28.0)


def test_a_segment_without_a_file_is_an_error(video: Path) -> None:
    with pytest.raises(FileNotFoundError):
        music_segment_inputs(video, {"segments": [
            {"segment_id": "a", "start_seconds": 0.0, "end_seconds": 28.0},
        ]}, 28.0)


def test_a_zero_length_segment_is_dropped(video: Path) -> None:
    entries = music_segment_inputs(video, {"segments": [
        {"segment_id": "a", "start_seconds": 5.0, "end_seconds": 5.0, "file": "assets/music/bed.mp3"},
        {"segment_id": "b", "start_seconds": 0.0, "end_seconds": 5.0, "file": "assets/music/bed.mp3"},
    ]}, 28.0)
    assert len(entries) == 1
    assert entries[0]["start"] == 0.0


def test_no_music_configured_yields_nothing(video: Path) -> None:
    assert music_segment_inputs(video, {}, 28.0) == []


def test_segments_take_precedence_over_a_stale_file_key(video: Path) -> None:
    entries = music_segment_inputs(video, {
        "file": "assets/music/absent.mp3",
        "segments": [{"segment_id": "a", "start_seconds": 0.0, "end_seconds": 28.0,
                      "file": "assets/music/second.mp3"}],
    }, 28.0)
    assert [entry["file"].name for entry in entries] == ["second.mp3"]
