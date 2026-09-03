#!/usr/bin/env python3
"""Trim Flow opening clips based on STT alignment (§67).

After ElevenLabs + STT, identify real spoken time of:
  opening_question_spark (~5s) and book_transition (~3s)
Trim Flow sources accordingly, preferring trimming over speed distortion.

Sources:
  assets/opening/question_spark_source.mp4 (6s default)
  assets/opening/book_transition_source.mp4 (4s default)
Outputs:
  assets/opening/question_spark_trimmed.mp4
  assets/opening/book_transition_trimmed.mp4

If narration exceeds source, we fail (do not stretch) per §67.
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

def ffprobe_duration(p: Path) -> float:
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(p)],
        text=True, timeout=10
    )
    return float(out.strip())

def trim(input_path: Path, output_path: Path, target: float) -> None:
    if not input_path.is_file():
        raise FileNotFoundError(f"Source clip missing: {input_path}")
    src_dur = ffprobe_duration(input_path)
    if target > src_dur + 0.05:  # allow tiny epsilon
        raise RuntimeError(f"Target trim {target:.3f}s exceeds source {src_dur:.3f}s for {input_path.name} — refuse to stretch (§67). Need to regenerate or replan.")
    # Prefer trimming: use -ss 0 -t target, re-encode video (strip audio), keep same codec settings as render profile if possible
    # For simplicity, use libx264 fast
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # If target is very close to source, just copy
    if abs(target - src_dur) < 0.05:
        # copy or stream copy video, strip audio
        subprocess.run([
            "ffmpeg", "-y", "-i", str(input_path), "-an", "-c:v", "copy", str(output_path)
        ], check=True, capture_output=True)
        # if copy succeeds, done
        return
    # else re-encode trimmed
    subprocess.run([
        "ffmpeg", "-y", "-i", str(input_path),
        "-t", f"{target:.3f}",
        "-an",  # strip Flow source audio per §68
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
        str(output_path)
    ], check=True, capture_output=True)

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("video_dir", type=Path)
    parser.add_argument("--opening-a-target", type=float, default=None, help="Override target seconds for Clip A (if not reading from timing)")
    parser.add_argument("--opening-b-target", type=float, default=None, help="Override for Clip B")
    args = parser.parse_args()

    video_dir = Path(args.video_dir).resolve()
    timing_path = video_dir / "timing" / "BEAT_TIMINGS.json"
    if not timing_path.is_file():
        raise FileNotFoundError(f"BEAT_TIMINGS.json missing: {timing_path} — run STT first")

    timing = json.loads(timing_path.read_text(encoding="utf-8"))
    audio_dur = float(timing.get("audio_duration_seconds", 0))
    # Try to infer opening segments from beats or from creative/SCRIPT_PLAN.json
    # For QH, script plan has opening_question_spark / book_transition; but STT word timings tell actual durations
    # Simplified: use first beat(s) speech timings for opening? For QH body beats are separate, opening is not in beats.
    # Instead, read SCRIPT_PLAN or estimate: opening_a should cover first ~5s of narration, opening_b next ~3s
    # We'll look for creative/SCRIPT_PLAN.json segments if exists, else use fixed 5/3
    script_plan_path = video_dir / "creative" / "SCRIPT_PLAN.json"
    if script_plan_path.is_file():
        try:
            sp = json.loads(script_plan_path.read_text(encoding="utf-8"))
            # sp has full_narration + segmented times? We don't have word timings for segmented, so estimate proportional
            total_words = len(sp.get("full_narration", "").split())
            if total_words > 0:
                # opening_a_words ≈ 14/ total, opening_b_words ≈ 8
                opening_a_words = len(sp.get("opening_question_spark", "").split())
                opening_b_words = len(sp.get("book_transition", "").split())
                # map to audio duration proportionally
                a_target = audio_dur * (opening_a_words / total_words) if args.opening_a_target is None else args.opening_a_target
                b_target = audio_dur * (opening_b_words / total_words) if args.opening_b_target is None else args.opening_b_target
            else:
                a_target = 5.0 if args.opening_a_target is None else args.opening_a_target
                b_target = 3.0 if args.opening_b_target is None else args.opening_b_target
        except Exception:
            a_target = 5.0 if args.opening_a_target is None else args.opening_a_target
            b_target = 3.0 if args.opening_b_target is None else args.opening_b_target
    else:
        # fallback: use timing beats to estimate? For mixed pipeline, beats are body only, so audio_duration - body = opening
        # For simplicity, use 5/3
        a_target = 5.0 if args.opening_a_target is None else args.opening_a_target
        b_target = 3.0 if args.opening_b_target is None else args.opening_b_target
        # But ensure a+b <= audio_dur
        if a_target + b_target > audio_dur:
            # scale down proportionally
            factor = audio_dur * 0.18  # keep opening ~18% of total
            a_target = min(a_target, factor * 0.62)
            b_target = min(b_target, factor * 0.38)

    # Clamp to reasonable
    a_target = max(1.0, min(float(a_target), 10.0))
    b_target = max(1.0, min(float(b_target), 10.0))

    src_a = video_dir / "assets" / "opening" / "question_spark_source.mp4"
    src_b = video_dir / "assets" / "opening" / "book_transition_source.mp4"
    dst_a = video_dir / "assets" / "opening" / "question_spark_trimmed.mp4"
    dst_b = video_dir / "assets" / "opening" / "book_transition_trimmed.mp4"

    print(f"Trimming opening clips for {video_dir.name}: A {a_target:.3f}s B {b_target:.3f}s", flush=True)
    trim(src_a, dst_a, a_target)
    trim(src_b, dst_b, b_target)
    # Verify
    for p, t in [(dst_a, a_target), (dst_b, b_target)]:
        dur = ffprobe_duration(p)
        drift = abs(dur - t)
        print(f"  {p.name}: {dur:.3f}s (target {t:.3f} drift {drift:+.3f})", flush=True)
        if drift > 0.25:
            print(f"WARN trim drift >0.25 for {p.name}", flush=True)
    print("TRIM DONE", flush=True)

if __name__ == "__main__":
    main()
