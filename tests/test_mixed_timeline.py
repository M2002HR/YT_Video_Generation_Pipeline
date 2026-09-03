from __future__ import annotations
import json, sys
from pathlib import Path
import tempfile
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

def test_build_timeline_mixed_media_and_legacy():
    # Legacy: only images
    # Mixed: video + image
    with tempfile.TemporaryDirectory() as d:
        import shutil
        vd = Path(d) / "videos" / "001_test"
        vd.mkdir(parents=True)
        # create dummy beats timing
        timing = {
            "audio": "assets/audio/narration.mp3",
            "audio_duration_seconds": 42.0,
            "beats": [
                {"beat_id": 1, "narration": "Hello world hello world hello world", "speech_start": 0.0, "speech_end": 3.0, "match_confidence": 0.9},
                {"beat_id": 2, "narration": "Second beat content here", "speech_start": 3.0, "speech_end": 6.0, "match_confidence": 0.9},
            ]
        }
        (vd / "timing").mkdir(parents=True)
        (vd / "timing" / "BEAT_TIMINGS.json").write_text(json.dumps(timing))
        (vd / "render").mkdir(parents=True)
        (vd / "render" / "RENDER_PROFILE.json").write_text(json.dumps({
            "resolution": {"width": 1080, "height": 1920}, "fps": 30,
            "motion": {"enabled": True, "cycle": ["zoom_in", "still"]},
            "subtitles": {"enabled": False},
            "resource_limits": {"ffmpeg_threads": 1}
        }))
        (vd / "assets" / "raw_beats").mkdir(parents=True)
        from PIL import Image
        import os
        for i in (1,2):
            p = vd / "assets" / "raw_beats" / f"beat_{i:03d}.png"
            Image.new("RGB", (1080,1920), (200,210,200)).save(p)
        (vd / "assets" / "audio").mkdir(parents=True)
        # create dummy audio via ffmpeg silent
        audio = vd / "assets" / "audio" / "narration.mp3"
        try:
            subprocess.run(["ffmpeg","-y","-f","lavfi","-i","anullsrc=r=44100:cl=stereo","-t","42","-c:a","mp3",str(audio)], check=True, capture_output=True, timeout=10)
        except Exception:
            audio.write_bytes(b"\x00"*1024)

        # Legacy build (no opening clips) should produce 2 image beats
        subprocess.run([sys.executable, str(ROOT / "scripts" / "build_timeline.py"), str(vd)], check=True, capture_output=True, timeout=15)
        tl = json.loads((vd / "timeline" / "TIMELINE.json").read_text(encoding="utf-8"))
        assert len(tl["beats"]) == 2
        assert all(b["media_type"] == "image" for b in tl["beats"])

        # Now add mixed media: create trimmed opening clips via ffmpeg
        (vd / "assets" / "opening").mkdir(parents=True, exist_ok=True)
        for name, dur in [("question_spark_trimmed.mp4", 5), ("book_transition_trimmed.mp4", 3)]:
            out = vd / "assets" / "opening" / name
            try:
                subprocess.run(["ffmpeg","-y","-f","lavfi","-i",f"color=c=0x333333:s=1080x1920:d={dur}:r=30","-t",str(dur),"-pix_fmt","yuv420p",str(out)], check=True, capture_output=True, timeout=10)
            except Exception:
                out.write_bytes(b"\x00"*1024)

        (vd / "PROJECT.md").write_text("Project: `question_harvest`\n")
        subprocess.run([sys.executable, str(ROOT / "scripts" / "build_timeline.py"), str(vd)], check=True, capture_output=True, timeout=15)
        tl2 = json.loads((vd / "timeline" / "TIMELINE.json").read_text(encoding="utf-8"))
        # should have 2 video + 2 image = 4
        assert any(b["media_type"] == "video" for b in tl2["beats"])
        assert any(b["media_type"] == "image" for b in tl2["beats"])
        assert len(tl2["beats"]) == 4

def test_legacy_timeline_backward_compat():
    # Ensure legacy entries without media_type still work (render handles)
    from build_timeline import compute_display_boundaries
    beats = [
        {"beat_id": 1, "speech_start": 0.0, "speech_end": 2.0},
        {"beat_id": 2, "speech_start": 2.5, "speech_end": 5.0},
    ]
    b, adj = compute_display_boundaries(beats, 5.0)
    assert len(b) == 3
