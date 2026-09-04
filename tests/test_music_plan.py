"""MUSIC_PLAN.json must accept a second segment without a refactor (T9.7)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from music_plan import (
    MusicPlanError,
    MusicSegment,
    audio_mix_music_entries,
    load_plan,
    segment_at,
    single_bed,
    validate_segments,
    write_plan,
)


def test_the_single_track_case_is_expressed_as_one_segment(tmp_path: Path) -> None:
    segments = single_bed(
        narration_seconds=58.2, provider="mixkit", query_prompt="calm instrumental",
        source_url="https://mixkit.co/free-stock-music/item/x", file="assets/music/background.mp3",
    )
    path = write_plan(tmp_path, segments, narration_seconds=58.2, status="DONE")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["segment_count"] == 1
    assert payload["segments"][0]["end_seconds"] == 58.2
    assert payload["segments"][0]["query_prompt"] == "calm instrumental"
    assert payload["status"] == "DONE"


def test_a_second_segment_needs_only_another_entry(tmp_path: Path) -> None:
    """The point of the schema: two cues validate, write and load with no code change."""
    segments = [
        MusicSegment("bed_001", 0.0, 20.0, provider="mixkit", query_prompt="curious opening",
                     file="assets/music/opening.mp3"),
        MusicSegment("bed_002", 20.0, 58.0, provider="mixkit", query_prompt="warm resolution",
                     file="assets/music/body.mp3", gain_db=-18.0),
    ]
    write_plan(tmp_path, segments, narration_seconds=58.0)

    loaded, payload = load_plan(tmp_path)
    assert [segment.segment_id for segment in loaded] == ["bed_001", "bed_002"]
    assert payload["segment_count"] == 2
    assert loaded[1].gain_db == -18.0
    entries = audio_mix_music_entries(loaded)
    assert [entry["file"] for entry in entries] == ["assets/music/opening.mp3", "assets/music/body.mp3"]
    assert entries[1]["start_seconds"] == 20.0


def test_the_segment_covering_a_moment_is_found() -> None:
    segments = [
        MusicSegment("a", 0.0, 10.0, file="a.mp3"),
        MusicSegment("b", 10.0, 20.0, file="b.mp3"),
    ]
    assert segment_at(segments, 0.0).segment_id == "a"
    assert segment_at(segments, 9.999).segment_id == "a"
    assert segment_at(segments, 10.0).segment_id == "b"
    assert segment_at(segments, 25.0) is None


def test_a_gap_between_segments_is_rejected() -> None:
    with pytest.raises(MusicPlanError, match="Silence between"):
        validate_segments([MusicSegment("a", 0.0, 10.0), MusicSegment("b", 14.0, 20.0)])


def test_overlapping_segments_are_rejected() -> None:
    with pytest.raises(MusicPlanError, match="overlaps"):
        validate_segments([MusicSegment("a", 0.0, 12.0), MusicSegment("b", 8.0, 20.0)])


def test_a_zero_length_segment_is_rejected() -> None:
    with pytest.raises(MusicPlanError, match="ends at or before"):
        validate_segments([MusicSegment("a", 5.0, 5.0)])


def test_duplicate_segment_ids_are_rejected() -> None:
    with pytest.raises(MusicPlanError, match="Duplicate"):
        validate_segments([MusicSegment("a", 0.0, 10.0), MusicSegment("a", 10.0, 20.0)])


def test_a_plan_that_does_not_reach_the_end_of_the_narration_is_rejected() -> None:
    """Music that stops early would leave the closing silent without anyone noticing."""
    with pytest.raises(MusicPlanError, match="covers"):
        validate_segments([MusicSegment("a", 0.0, 30.0)], narration_seconds=58.0)


def test_an_empty_plan_is_rejected() -> None:
    with pytest.raises(MusicPlanError):
        validate_segments([])


def test_a_late_start_leaves_the_opening_bare_and_is_rejected() -> None:
    with pytest.raises(MusicPlanError, match="leaving the opening"):
        validate_segments([MusicSegment("a", 3.0, 58.0)], narration_seconds=58.0)


def test_segments_without_a_file_are_not_offered_to_the_mixer() -> None:
    segments = [MusicSegment("a", 0.0, 10.0), MusicSegment("b", 10.0, 20.0, file="b.mp3")]
    assert [entry["segment_id"] for entry in audio_mix_music_entries(segments)] == ["b"]


def test_the_audio_mix_profile_carries_the_segment_list(tmp_path: Path) -> None:
    from run_full_video_pipeline import ensure_audio_mix_profile

    project = tmp_path / "videos" / "904_music"
    (project / "assets" / "music").mkdir(parents=True)
    track = project / "assets" / "music" / "background.mp3"
    track.write_bytes(b"\x00" * 2048)
    write_plan(
        project,
        single_bed(narration_seconds=42.0, provider="mixkit", query_prompt="calm",
                   file="assets/music/background.mp3"),
        narration_seconds=42.0,
    )

    profile = json.loads(ensure_audio_mix_profile(project).read_text(encoding="utf-8"))
    assert profile["music"]["file"] == "assets/music/background.mp3"
    assert profile["music"]["segments"][0]["segment_id"] == "bed_001"
    assert profile["music"]["segments"][0]["end_seconds"] == 42.0


def test_the_profile_falls_back_to_the_downloaded_track_without_a_plan(tmp_path: Path) -> None:
    from run_full_video_pipeline import ensure_audio_mix_profile

    project = tmp_path / "videos" / "905_music"
    (project / "assets" / "music").mkdir(parents=True)
    (project / "assets" / "music" / "background.mp3").write_bytes(b"\x00" * 2048)

    profile = json.loads(ensure_audio_mix_profile(project).read_text(encoding="utf-8"))
    assert profile["music"]["segments"][0]["file"] == "assets/music/background.mp3"
    assert profile["music"]["segments"][0]["end_seconds"] is None
