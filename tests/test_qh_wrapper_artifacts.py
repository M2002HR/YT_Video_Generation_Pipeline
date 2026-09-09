from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from run_full_video_pipeline_qh_wrapper import file_is_usable, music_is_usable


def test_music_reuse_ignores_directory_placeholders_and_tiny_files(tmp_path: Path) -> None:
    (tmp_path / ".gitkeep").touch()
    (tmp_path / "broken.mp3").write_bytes(b"not an actual track")
    assert music_is_usable(tmp_path) is False


def test_music_reuse_accepts_a_provider_named_audio_file(tmp_path: Path) -> None:
    (tmp_path / "freesound_background.mp3").write_bytes(b"a" * (64 * 1024))
    assert music_is_usable(tmp_path) is True


def test_required_wrapper_files_must_be_non_empty(tmp_path: Path) -> None:
    narration = tmp_path / "narration.mp3"
    narration.touch()
    assert file_is_usable(narration) is False
    narration.write_bytes(b"audio")
    assert file_is_usable(narration) is True
