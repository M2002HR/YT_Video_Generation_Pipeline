"""Mixed-media timeline: body images must keep their measured spoken positions.

The regression these tests guard is subtle and silent: the old builder rescaled the image
timeline into the window left over after the opening clips, which moved every image off its
own sentence while every file still looked plausible.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

SPARK_END = 5.0
TRANSITION_END = 8.0
AUDIO_DURATION = 42.0

#: Body beats as STT would report them: absolute positions in the continuous narration.
BODY_BEATS = [
    {"beat_id": 1, "narration": "First body beat", "speech_start": 8.2, "speech_end": 20.0, "match_confidence": 0.94},
    {"beat_id": 2, "narration": "Second body beat", "speech_start": 20.4, "speech_end": 41.6, "match_confidence": 0.91},
]


def _run_builder(video_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "build_timeline.py"), str(video_dir)],
        capture_output=True,
        text=True,
        timeout=60,
    )


def _build_workspace(root: Path, *, spark: float, transition: float) -> Path:
    from PIL import Image

    video_dir = root / "videos" / "001_test"
    (video_dir / "timing").mkdir(parents=True)
    (video_dir / "render").mkdir(parents=True)
    (video_dir / "assets" / "raw_beats").mkdir(parents=True)
    (video_dir / "assets" / "audio").mkdir(parents=True)
    (video_dir / "assets" / "opening").mkdir(parents=True)

    (video_dir / "timing" / "BEAT_TIMINGS.json").write_text(
        json.dumps(
            {
                "audio": "assets/audio/narration.mp3",
                "audio_duration_seconds": AUDIO_DURATION,
                "beats": BODY_BEATS,
            }
        ),
        encoding="utf-8",
    )
    (video_dir / "render" / "RENDER_PROFILE.json").write_text(
        json.dumps(
            {
                "resolution": {"width": 1080, "height": 1920},
                "fps": 30,
                "motion": {"enabled": True, "cycle": ["zoom_in", "still"]},
                "subtitles": {"enabled": False},
                "resource_limits": {"ffmpeg_threads": 1},
            }
        ),
        encoding="utf-8",
    )
    for index in (1, 2):
        Image.new("RGB", (1080, 1920), (200, 210, 200)).save(
            video_dir / "assets" / "raw_beats" / f"beat_{index:03d}.png"
        )
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
         "-t", str(AUDIO_DURATION), "-c:a", "mp3", str(video_dir / "assets" / "audio" / "narration.mp3")],
        check=True, capture_output=True, timeout=60,
    )
    for name, duration in (("question_spark_trimmed.mp4", spark), ("book_transition_trimmed.mp4", transition - spark)):
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi",
             "-i", f"color=c=0x333333:s=1080x1920:d={duration}:r=30",
             "-t", f"{duration}", "-pix_fmt", "yuv420p",
             str(video_dir / "assets" / "opening" / name)],
            check=True, capture_output=True, timeout=60,
        )
    (video_dir / "PROJECT.md").write_text("Project: `question_harvest`\n", encoding="utf-8")
    return video_dir


def _write_opening_timing(video_dir: Path, *, spark: float, transition: float) -> None:
    (video_dir / "timing" / "OPENING_TIMING.json").write_text(
        json.dumps(
            {
                "audio_duration_seconds": AUDIO_DURATION,
                "spark_start": 0.0,
                "spark_end": spark,
                "transition_start": spark,
                "transition_end": transition,
                "body_start": BODY_BEATS[0]["speech_start"],
            }
        ),
        encoding="utf-8",
    )


def test_body_images_keep_their_measured_positions():
    with tempfile.TemporaryDirectory() as tmp:
        video_dir = _build_workspace(Path(tmp), spark=SPARK_END, transition=TRANSITION_END)
        _write_opening_timing(video_dir, spark=SPARK_END, transition=TRANSITION_END)

        result = _run_builder(video_dir)
        assert result.returncode == 0, result.stderr

        timeline = json.loads((video_dir / "timeline" / "TIMELINE.json").read_text(encoding="utf-8"))
        videos = [b for b in timeline["beats"] if b["media_type"] == "video"]
        images = [b for b in timeline["beats"] if b["media_type"] == "image"]
        assert len(videos) == 2
        assert len(images) == 2

        # The clips own exactly the measured opening window.
        assert videos[0]["start"] == 0.0
        assert abs(videos[1]["end"] - TRANSITION_END) <= 0.05

        # Each image must contain the midpoint of the speech it illustrates. That is the
        # property rescaling used to break while still producing a valid-looking file.
        for entry, beat in zip(images, BODY_BEATS):
            midpoint = (beat["speech_start"] + beat["speech_end"]) / 2
            assert entry["start"] <= midpoint <= entry["end"], (entry, beat)
        assert images[0]["start"] >= TRANSITION_END - 0.05
        assert abs(images[-1]["end"] - AUDIO_DURATION) <= 0.05


def test_opening_drift_is_rejected():
    """Clips that do not end where the narration says must not render."""
    with tempfile.TemporaryDirectory() as tmp:
        # Clips total 8s, but the narration puts the transition end at 6s.
        video_dir = _build_workspace(Path(tmp), spark=SPARK_END, transition=TRANSITION_END)
        _write_opening_timing(video_dir, spark=3.0, transition=6.0)

        result = _run_builder(video_dir)
        assert result.returncode != 0
        assert "book transition" in (result.stderr + result.stdout)


def test_missing_opening_timing_is_rejected():
    with tempfile.TemporaryDirectory() as tmp:
        video_dir = _build_workspace(Path(tmp), spark=SPARK_END, transition=TRANSITION_END)
        result = _run_builder(video_dir)
        assert result.returncode != 0
        assert "OPENING_TIMING.json" in (result.stderr + result.stdout)


def test_untrimmed_opening_source_is_not_rendered():
    """The source clip is a second longer by design and must never substitute for the trim."""
    with tempfile.TemporaryDirectory() as tmp:
        video_dir = _build_workspace(Path(tmp), spark=SPARK_END, transition=TRANSITION_END)
        _write_opening_timing(video_dir, spark=SPARK_END, transition=TRANSITION_END)
        trimmed = video_dir / "assets" / "opening" / "question_spark_trimmed.mp4"
        trimmed.replace(video_dir / "assets" / "opening" / "question_spark_source.mp4")

        result = _run_builder(video_dir)
        assert result.returncode != 0
        assert "trim_opening_clips" in (result.stderr + result.stdout)


def test_legacy_image_only_timeline_still_builds():
    with tempfile.TemporaryDirectory() as tmp:
        video_dir = _build_workspace(Path(tmp), spark=SPARK_END, transition=TRANSITION_END)
        (video_dir / "PROJECT.md").unlink()
        for name in ("question_spark_trimmed.mp4", "book_transition_trimmed.mp4"):
            (video_dir / "assets" / "opening" / name).unlink()

        result = _run_builder(video_dir)
        assert result.returncode == 0, result.stderr
        timeline = json.loads((video_dir / "timeline" / "TIMELINE.json").read_text(encoding="utf-8"))
        assert len(timeline["beats"]) == 2
        assert all(beat["media_type"] == "image" for beat in timeline["beats"])
        assert timeline["beats"][0]["start"] == 0.0


def test_display_boundaries_can_start_after_the_opening():
    from build_timeline import compute_display_boundaries

    boundaries, _ = compute_display_boundaries(BODY_BEATS, AUDIO_DURATION, start_at=TRANSITION_END)
    assert boundaries[0] == TRANSITION_END
    assert boundaries[-1] == AUDIO_DURATION
    assert boundaries == sorted(boundaries)
