"""Integration media coverage for the renderer (§97, T6.4).

Real media, real FFmpeg. Every fixture is a few hundred milliseconds at 240x426 so the
whole file runs in seconds while still exercising the actual encode path — a dry-run-only
suite would not catch a filter graph that FFmpeg rejects.

Scenarios: legacy image-only, video+video+image, portrait 9:16, source-audio stripping,
subtitles on, subtitles off, and rejection of an mp4 that will not decode.
"""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

WIDTH, HEIGHT = 240, 426  # 9:16, small enough to encode instantly
FPS = 24


def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args],
                   check=True, capture_output=True, timeout=120)


def _probe(path: Path) -> dict:
    raw = subprocess.run(
        ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
        check=True, capture_output=True, text=True, timeout=60,
    ).stdout
    return json.loads(raw)


def _png(path: Path, colour: str = "0x2b3a4a") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    _ffmpeg("-f", "lavfi", "-i", f"color=c={colour}:s={WIDTH}x{HEIGHT}", "-frames:v", "1", str(path))
    return path


def _clip(path: Path, seconds: float, *, with_tone: bool = False) -> Path:
    """A real mp4. ``with_tone`` gives it an audio track that must never reach the output."""
    path.parent.mkdir(parents=True, exist_ok=True)
    args = ["-f", "lavfi", "-i", f"testsrc=s={WIDTH}x{HEIGHT}:r={FPS}:d={seconds}"]
    if with_tone:
        args += ["-f", "lavfi", "-i", f"sine=frequency=1000:duration={seconds}", "-c:a", "aac", "-shortest"]
    args += ["-t", f"{seconds}", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast", str(path)]
    _ffmpeg(*args)
    return path


def _narration(path: Path, seconds: float) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    _ffmpeg("-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", f"{seconds}", "-c:a", "mp3", str(path))
    return path


def _ass(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 240\nPlayResY: 426\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, Alignment, MarginV\n"
        "Style: Default,DejaVu Sans,18,&H00FFFFFF,2,20\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Text\n"
        "Dialogue: 0,0:00:00.00,0:00:01.00,Default,first line\n",
        encoding="utf-8",
    )
    return path


def _workspace(root: Path, beats: list[dict], *, subtitles: bool, duration: float) -> Path:
    video_dir = root / "videos" / "900_media_test"
    (video_dir / "render").mkdir(parents=True, exist_ok=True)
    (video_dir / "timeline").mkdir(parents=True, exist_ok=True)
    _narration(video_dir / "assets" / "audio" / "narration.mp3", duration)
    (video_dir / "render" / "RENDER_PROFILE.json").write_text(
        json.dumps(
            {
                "resolution": {"width": WIDTH, "height": HEIGHT},
                "fps": FPS,
                "motion": {"enabled": False},
                "subtitles": {"enabled": subtitles},
                "video": {"codec": "libx264", "preset": "ultrafast", "crf": 30},
                "resource_limits": {"ffmpeg_threads": 1},
            }
        ),
        encoding="utf-8",
    )
    (video_dir / "timeline" / "TIMELINE.json").write_text(
        json.dumps(
            {
                "resolution": {"width": WIDTH, "height": HEIGHT},
                "fps": FPS,
                "duration": duration,
                "audio": "assets/audio/narration.mp3",
                "render_profile": "render/RENDER_PROFILE.json",
                "beats": beats,
            }
        ),
        encoding="utf-8",
    )
    if subtitles:
        _ass(video_dir / "timeline" / "SUBTITLES.ass")
    return video_dir


def _render(video_dir: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "render_video.py"), str(video_dir), *extra],
        capture_output=True, text=True, timeout=300,
    )


def _ffmpeg_command(result: subprocess.CompletedProcess) -> list[str]:
    marker = "FFmpeg command:\n"
    assert marker in result.stdout, result.stdout + result.stderr
    return shlex.split(result.stdout.split(marker, 1)[1].strip())


# --------------------------------------------------------------------------- 1

def test_legacy_image_only_timeline_renders(tmp_path: Path) -> None:
    """Beats with no media_type are images, as older timelines wrote them."""
    beats = [
        {"beat_id": 1, "start": 0.0, "duration": 0.6, "image": "assets/raw_beats/beat_001.png"},
        {"beat_id": 2, "start": 0.6, "duration": 0.6, "image": "assets/raw_beats/beat_002.png"},
    ]
    video_dir = _workspace(tmp_path, beats, subtitles=False, duration=1.2)
    _png(video_dir / "assets" / "raw_beats" / "beat_001.png", "0x203040")
    _png(video_dir / "assets" / "raw_beats" / "beat_002.png", "0x403020")

    result = _render(video_dir)
    assert result.returncode == 0, result.stdout + result.stderr
    output = video_dir / "assets" / "renders" / "preview.mp4"
    probe = _probe(output)
    assert abs(float(probe["format"]["duration"]) - 1.2) < 0.2
    assert [s["codec_type"] for s in probe["streams"]].count("video") == 1


# --------------------------------------------------------------------------- 2

def test_video_video_image_renders_as_one_continuous_clip(tmp_path: Path) -> None:
    beats = [
        {"beat_id": 1, "start": 0.0, "duration": 0.5, "media_type": "video",
         "source": "assets/opening/a.mp4"},
        {"beat_id": 2, "start": 0.5, "duration": 0.5, "media_type": "video",
         "source": "assets/opening/b.mp4"},
        {"beat_id": 3, "start": 1.0, "duration": 0.5, "media_type": "image",
         "image": "assets/raw_beats/beat_001.png"},
    ]
    video_dir = _workspace(tmp_path, beats, subtitles=False, duration=1.5)
    _clip(video_dir / "assets" / "opening" / "a.mp4", 0.8)
    _clip(video_dir / "assets" / "opening" / "b.mp4", 0.8)
    _png(video_dir / "assets" / "raw_beats" / "beat_001.png")

    result = _render(video_dir)
    assert result.returncode == 0, result.stdout + result.stderr
    probe = _probe(video_dir / "assets" / "renders" / "preview.mp4")
    assert abs(float(probe["format"]["duration"]) - 1.5) < 0.2
    assert "concat=n=3:v=1:a=0" in " ".join(_ffmpeg_command(_render(video_dir, "--dry-run")))


# --------------------------------------------------------------------------- 3

def test_portrait_nine_by_sixteen_is_preserved(tmp_path: Path) -> None:
    beats = [
        {"beat_id": 1, "start": 0.0, "duration": 0.5, "media_type": "video",
         "source": "assets/opening/wide.mp4"},
        {"beat_id": 2, "start": 0.5, "duration": 0.5, "media_type": "image",
         "image": "assets/raw_beats/beat_001.png"},
    ]
    video_dir = _workspace(tmp_path, beats, subtitles=False, duration=1.0)
    # A landscape source must be cropped to portrait, not letterboxed or stretched.
    (video_dir / "assets" / "opening").mkdir(parents=True, exist_ok=True)
    _ffmpeg("-f", "lavfi", "-i", f"testsrc=s=640x360:r={FPS}:d=0.8", "-t", "0.8",
            "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast",
            str(video_dir / "assets" / "opening" / "wide.mp4"))
    _png(video_dir / "assets" / "raw_beats" / "beat_001.png")

    result = _render(video_dir)
    assert result.returncode == 0, result.stdout + result.stderr
    stream = next(s for s in _probe(video_dir / "assets" / "renders" / "preview.mp4")["streams"]
                  if s["codec_type"] == "video")
    assert (stream["width"], stream["height"]) == (WIDTH, HEIGHT)
    assert stream.get("sample_aspect_ratio", "1:1") in ("1:1", "0:1", None)


# --------------------------------------------------------------------------- 4

def test_source_clip_audio_never_reaches_the_render(tmp_path: Path) -> None:
    """A Flow clip carries its own audio; only the narration may be heard (§70)."""
    beats = [
        {"beat_id": 1, "start": 0.0, "duration": 0.6, "media_type": "video",
         "source": "assets/opening/loud.mp4"},
        {"beat_id": 2, "start": 0.6, "duration": 0.6, "media_type": "image",
         "image": "assets/raw_beats/beat_001.png"},
    ]
    video_dir = _workspace(tmp_path, beats, subtitles=False, duration=1.2)
    _clip(video_dir / "assets" / "opening" / "loud.mp4", 0.9, with_tone=True)
    _png(video_dir / "assets" / "raw_beats" / "beat_001.png")

    command = _ffmpeg_command(_render(video_dir, "--dry-run"))
    audio_maps = [command[i + 1] for i, token in enumerate(command)
                  if token == "-map" and ":a" in command[i + 1]]
    assert audio_maps == ["2:a:0"], "exactly one audio map, and it is the narration input"
    assert "concat=n=2:v=1:a=0" in " ".join(command), "concat must not carry audio"

    result = _render(video_dir)
    assert result.returncode == 0, result.stdout + result.stderr
    streams = _probe(video_dir / "assets" / "renders" / "preview.mp4")["streams"]
    assert [s["codec_type"] for s in streams].count("audio") == 1


# --------------------------------------------------------------------------- 5 & 6

def test_subtitles_on_burns_the_ass_filter(tmp_path: Path) -> None:
    beats = [{"beat_id": 1, "start": 0.0, "duration": 0.6, "image": "assets/raw_beats/beat_001.png"}]
    video_dir = _workspace(tmp_path, beats, subtitles=True, duration=0.6)
    _png(video_dir / "assets" / "raw_beats" / "beat_001.png")

    dry = _render(video_dir, "--dry-run")
    assert "Subtitles: on" in dry.stdout
    assert "ass=filename=" in " ".join(_ffmpeg_command(dry))

    result = _render(video_dir)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (video_dir / "assets" / "renders" / "preview.mp4").is_file()


def test_subtitles_off_leaves_the_frame_untouched(tmp_path: Path) -> None:
    beats = [{"beat_id": 1, "start": 0.0, "duration": 0.6, "image": "assets/raw_beats/beat_001.png"}]
    video_dir = _workspace(tmp_path, beats, subtitles=True, duration=0.6)
    _png(video_dir / "assets" / "raw_beats" / "beat_001.png")

    dry = _render(video_dir, "--dry-run", "--no-subtitles")
    assert "Subtitles: off" in dry.stdout
    assert "ass=filename=" not in " ".join(_ffmpeg_command(dry))

    result = _render(video_dir, "--no-subtitles")
    assert result.returncode == 0, result.stdout + result.stderr


def test_subtitles_on_without_a_subtitle_file_is_refused(tmp_path: Path) -> None:
    beats = [{"beat_id": 1, "start": 0.0, "duration": 0.6, "image": "assets/raw_beats/beat_001.png"}]
    video_dir = _workspace(tmp_path, beats, subtitles=True, duration=0.6)
    _png(video_dir / "assets" / "raw_beats" / "beat_001.png")
    (video_dir / "timeline" / "SUBTITLES.ass").unlink()

    result = _render(video_dir)
    assert result.returncode != 0
    assert "Subtitle file not found" in result.stdout + result.stderr


# --------------------------------------------------------------------------- 7

def test_an_mp4_that_will_not_decode_is_rejected(tmp_path: Path) -> None:
    beats = [
        {"beat_id": 1, "start": 0.0, "duration": 0.6, "media_type": "video",
         "source": "assets/opening/broken.mp4"},
    ]
    video_dir = _workspace(tmp_path, beats, subtitles=False, duration=0.6)
    broken = video_dir / "assets" / "opening" / "broken.mp4"
    broken.parent.mkdir(parents=True, exist_ok=True)
    broken.write_bytes(b"not an mp4 at all" * 64)

    result = _render(video_dir)
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "broken.mp4" in combined


def test_a_clip_shorter_than_its_slot_is_rejected(tmp_path: Path) -> None:
    """Rendering it would drop frames and desynchronise everything after it (§70)."""
    beats = [
        {"beat_id": 1, "start": 0.0, "duration": 1.5, "media_type": "video",
         "source": "assets/opening/short.mp4"},
    ]
    video_dir = _workspace(tmp_path, beats, subtitles=False, duration=1.5)
    _clip(video_dir / "assets" / "opening" / "short.mp4", 0.5)

    result = _render(video_dir)
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "needs 1.500s of video" in combined and "short.mp4" in combined


def test_a_missing_beat_asset_is_rejected(tmp_path: Path) -> None:
    beats = [{"beat_id": 1, "start": 0.0, "duration": 0.6, "image": "assets/raw_beats/absent.png"}]
    video_dir = _workspace(tmp_path, beats, subtitles=False, duration=0.6)

    result = _render(video_dir)
    assert result.returncode != 0
    assert "absent.png" in result.stdout + result.stderr
