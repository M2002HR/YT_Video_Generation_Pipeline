"""The render must fit an 80% share of a small server and say what it cost (T9.5)."""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from render_video import (
    MAX_SUPERSAMPLED_MEGAPIXELS,
    budgeted_threads,
    capped_supersample,
    cpu_count,
    ionice_prefix,
)

WIDTH, HEIGHT, FPS = 240, 426, 24


@pytest.mark.parametrize(
    "cpus,expected",
    [(1, 1), (2, 2), (3, 2), (4, 3), (8, 6), (12, 10), (16, 13), (64, 51)],
)
def test_eighty_percent_of_the_machine_is_never_zero_and_never_more(cpus: int, expected: int) -> None:
    assert budgeted_threads(0.8, cpus=cpus) == expected
    assert 1 <= budgeted_threads(0.8, cpus=cpus) <= cpus


def test_an_absurd_budget_is_clamped_into_range() -> None:
    assert budgeted_threads(0.0, cpus=8) == 1
    assert budgeted_threads(-5, cpus=8) == 1
    assert budgeted_threads(9.0, cpus=8) == 8


def test_the_supersample_factor_is_reduced_until_the_frame_fits() -> None:
    factor, note = capped_supersample(3, 2160, 3840)
    assert factor < 3 and note
    assert (2160 * 3840 * factor * factor) / 1_000_000 <= MAX_SUPERSAMPLED_MEGAPIXELS


def test_a_normal_short_keeps_its_requested_supersample() -> None:
    assert capped_supersample(2, 1080, 1920) == (2, "")


def test_cpu_count_reflects_what_this_process_may_schedule_on() -> None:
    assert cpu_count() >= 1


def _workspace(root: Path) -> Path:
    video_dir = root / "videos" / "903_budget"
    (video_dir / "render").mkdir(parents=True)
    (video_dir / "timeline").mkdir(parents=True)
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", "anullsrc=r=44100:cl=stereo", "-t", "0.8", "-c:a", "mp3",
         str(video_dir / "assets" / "audio" / "narration.mp3")],
        check=True, capture_output=True, timeout=60,
    ) if (video_dir / "assets" / "audio").mkdir(parents=True, exist_ok=True) is None else None
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", f"testsrc2=s={WIDTH}x{HEIGHT}", "-frames:v", "1",
         str(video_dir / "assets" / "raw_beats" / "beat_001.png")],
        check=True, capture_output=True, timeout=60,
    ) if (video_dir / "assets" / "raw_beats").mkdir(parents=True, exist_ok=True) is None else None
    (video_dir / "render" / "RENDER_PROFILE.json").write_text(
        json.dumps({
            "resolution": {"width": WIDTH, "height": HEIGHT},
            "fps": FPS,
            "motion": {"enabled": True, "supersample": 2},
            "subtitles": {"enabled": False},
            "video": {"codec": "libx264", "preset": "ultrafast", "crf": 32},
        }),
        encoding="utf-8",
    )
    (video_dir / "timeline" / "TIMELINE.json").write_text(
        json.dumps({
            "resolution": {"width": WIDTH, "height": HEIGHT},
            "fps": FPS,
            "duration": 0.8,
            "audio": "assets/audio/narration.mp3",
            "render_profile": "render/RENDER_PROFILE.json",
            "beats": [{"beat_id": 1, "start": 0.0, "duration": 0.8,
                       "image": "assets/raw_beats/beat_001.png", "motion": "zoom_in"}],
        }),
        encoding="utf-8",
    )
    return video_dir


def _render(video_dir: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "render_video.py"), str(video_dir), *extra],
        capture_output=True, text=True, timeout=300,
    )


def test_the_budget_sets_the_thread_caps_when_the_profile_is_silent(tmp_path: Path) -> None:
    video_dir = _workspace(tmp_path)
    result = _render(video_dir, "--dry-run", "--resource-budget", "0.8")
    assert result.returncode == 0, result.stdout + result.stderr
    expected = budgeted_threads(0.8)
    assert f"encoder={expected}" in result.stdout
    assert f"from {0.8:.2f} of {cpu_count()} CPU" in result.stdout
    command = shlex.split(result.stdout.split("FFmpeg command:\n", 1)[1].strip())
    assert command[command.index("-threads") + 1] == str(expected)


def test_an_explicit_thread_flag_beats_the_budget(tmp_path: Path) -> None:
    video_dir = _workspace(tmp_path)
    result = _render(video_dir, "--dry-run", "--threads", "1", "--resource-budget", "1.0")
    assert "encoder=1" in result.stdout and "from --threads" in result.stdout


def test_the_render_profile_beats_the_budget(tmp_path: Path) -> None:
    video_dir = _workspace(tmp_path)
    profile_path = video_dir / "render" / "RENDER_PROFILE.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    profile["resource_limits"] = {"ffmpeg_threads": 1}
    profile_path.write_text(json.dumps(profile), encoding="utf-8")

    result = _render(video_dir, "--dry-run", "--resource-budget", "1.0")
    assert "encoder=1" in result.stdout and "from render profile" in result.stdout


def _launcher_index(command: list[str], tool: str) -> int | None:
    """Index of a launcher binary, matching the token and not a substring of another."""
    for index, token in enumerate(command):
        if token == tool or token.endswith("/" + tool):
            return index
    return None


def test_the_render_is_niced_and_io_deprioritised(tmp_path: Path) -> None:
    """An uncapped render makes SSH and VNC unusable for its whole duration."""
    video_dir = _workspace(tmp_path)
    command = shlex.split(
        _render(video_dir, "--dry-run", "--nice", "12").stdout.split("FFmpeg command:\n", 1)[1].strip()
    )
    nice_at = _launcher_index(command, "nice")
    assert nice_at is not None, command[:6]
    assert command[nice_at + 1 : nice_at + 3] == ["-n", "12"]
    if ionice_prefix():
        assert _launcher_index(command, "ionice") == 0
    assert _launcher_index(command, "ffmpeg") > nice_at


def test_nice_zero_leaves_the_command_unwrapped(tmp_path: Path) -> None:
    video_dir = _workspace(tmp_path)
    command = shlex.split(
        _render(video_dir, "--dry-run", "--nice", "0").stdout.split("FFmpeg command:\n", 1)[1].strip()
    )
    assert _launcher_index(command, "nice") is None


def test_a_real_render_records_what_it_cost(tmp_path: Path) -> None:
    video_dir = _workspace(tmp_path)
    result = _render(video_dir, "--resource-budget", "0.8")
    assert result.returncode == 0, result.stdout + result.stderr

    stats = json.loads((video_dir / "render" / "RENDER_STATS.json").read_text(encoding="utf-8"))
    assert stats["beats"] == 1
    assert stats["resolution"] == f"{WIDTH}x{HEIGHT}"
    assert stats["wall_seconds"] > 0
    assert stats["peak_child_rss_mb"] > 0
    assert stats["threads"]["encoder"] == budgeted_threads(0.8)
    assert stats["resource_budget"] == 0.8
    assert stats["cpus_available"] == cpu_count()
    assert abs(stats["actual_duration_seconds"] - 0.8) < 0.3
