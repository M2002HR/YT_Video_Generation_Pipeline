#!/usr/bin/env python3
"""Create an audio-polished version of an accepted baseline render.

The baseline video is never overwritten. Video is stream-copied; only audio is
rebuilt from the baseline narration plus optional music/SFX.

Example:
    python scripts/polish_audio.py \
      videos/001_brain_replays_embarrassing_moments

Output:
    <video>/assets/renders/polished.mp4
"""

from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return data


def require_binary(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"{name} was not found in PATH.")
    return path


def resolve_video_path(video_dir: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return video_dir / path


def probe_duration(ffprobe: str, path: Path) -> float:
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


def as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    return bool(value)


def main() -> None:
    parser = argparse.ArgumentParser(description="Add music/SFX and loudness polish.")
    parser.add_argument("video_dir", type=Path)
    parser.add_argument(
        "--profile",
        type=Path,
        default=None,
        help="Defaults to <video>/audio_mix/AUDIO_MIX_PROFILE.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Overrides output path from the audio mix profile.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate assets and print the FFmpeg command only.",
    )
    args = parser.parse_args()

    ffmpeg = require_binary("ffmpeg")
    ffprobe = require_binary("ffprobe")

    video_dir = args.video_dir.expanduser().resolve()
    profile_path = (
        args.profile.expanduser().resolve()
        if args.profile
        else video_dir / "audio_mix" / "AUDIO_MIX_PROFILE.json"
    )
    profile = load_json(profile_path)

    baseline = resolve_video_path(video_dir, str(profile["baseline_video"]))
    if not baseline.exists():
        raise FileNotFoundError(f"Baseline video not found: {baseline}")

    duration = probe_duration(ffprobe, baseline)

    output = (
        args.output.expanduser().resolve()
        if args.output
        else resolve_video_path(video_dir, str(profile["output_video"]))
    )
    if output.resolve() == baseline.resolve():
        raise ValueError("Audio polish output must not overwrite the accepted baseline.")
    output.parent.mkdir(parents=True, exist_ok=True)

    music_cfg = profile.get("music") if isinstance(profile.get("music"), dict) else {}
    music_enabled = as_bool(music_cfg.get("enabled"), False)

    sfx_cfg = profile.get("sfx") if isinstance(profile.get("sfx"), dict) else {}
    sfx_enabled = as_bool(sfx_cfg.get("enabled"), False)
    raw_events = sfx_cfg.get("events") if isinstance(sfx_cfg.get("events"), list) else []
    sfx_events = [dict(item) for item in raw_events if isinstance(item, dict)] if sfx_enabled else []

    command: list[str] = [ffmpeg, "-hide_banner", "-y", "-i", str(baseline)]
    filter_parts: list[str] = []

    # Narration/audio already accepted in the baseline render.
    # Split it when sidechain ducking needs a dedicated detector signal.
    narration_mix_label = "narr"
    sidechain_label = ""

    music_input_index: int | None = None
    if music_enabled:
        music_file = resolve_video_path(video_dir, str(music_cfg.get("file") or ""))
        if not music_file.exists():
            raise FileNotFoundError(
                f"Background music is enabled but file is missing: {music_file}"
            )

        music_input_index = 1
        if as_bool(music_cfg.get("loop"), True):
            command.extend(["-stream_loop", "-1"])
        command.extend(["-i", str(music_file)])

        duck_cfg = (
            music_cfg.get("ducking")
            if isinstance(music_cfg.get("ducking"), dict)
            else {}
        )
        duck_enabled = as_bool(duck_cfg.get("enabled"), True)

        if duck_enabled:
            filter_parts.append(
                f"[0:a:0]atrim=0:{duration:.6f},asetpts=PTS-STARTPTS,"
                "asplit=2[narr][sidechain]"
            )
            sidechain_label = "sidechain"
        else:
            filter_parts.append(
                f"[0:a:0]atrim=0:{duration:.6f},asetpts=PTS-STARTPTS[narr]"
            )

        gain_db = float(music_cfg.get("gain_db", -20.0))
        fade_in = max(0.0, float(music_cfg.get("fade_in_sec", 0.8)))
        fade_out = max(0.0, float(music_cfg.get("fade_out_sec", 1.4)))
        fade_out_start = max(0.0, duration - fade_out)

        music_filters = [
            f"[{music_input_index}:a:0]",
            f"atrim=0:{duration:.6f}",
            "asetpts=PTS-STARTPTS",
            f"volume={gain_db:.3f}dB",
        ]
        if fade_in > 0:
            music_filters.append(f"afade=t=in:st=0:d={fade_in:.3f}")
        if fade_out > 0:
            music_filters.append(
                f"afade=t=out:st={fade_out_start:.3f}:d={fade_out:.3f}"
            )

        filter_parts.append(",".join(music_filters) + "[musicpre]")

        if duck_enabled:
            threshold = float(duck_cfg.get("threshold", 0.025))
            ratio = float(duck_cfg.get("ratio", 8.0))
            attack = float(duck_cfg.get("attack_ms", 18))
            release = float(duck_cfg.get("release_ms", 320))

            filter_parts.append(
                f"[musicpre][{sidechain_label}]"
                "sidechaincompress="
                f"threshold={threshold:.6f}:"
                f"ratio={ratio:.3f}:"
                f"attack={attack:.3f}:"
                f"release={release:.3f}"
                "[music]"
            )
        else:
            filter_parts.append("[musicpre]anull[music]")
    else:
        filter_parts.append(
            f"[0:a:0]atrim=0:{duration:.6f},asetpts=PTS-STARTPTS[narr]"
        )

    next_input_index = 2 if music_enabled else 1
    sfx_labels: list[str] = []

    for event_index, event in enumerate(sfx_events):
        file_value = str(event.get("file") or "").strip()
        if not file_value:
            raise ValueError(f"SFX event {event_index} has no file.")

        sfx_file = resolve_video_path(video_dir, file_value)
        if not sfx_file.exists():
            raise FileNotFoundError(
                f"SFX event {event_index} file not found: {sfx_file}"
            )

        at = max(0.0, float(event.get("at", 0.0)))
        if at >= duration:
            raise ValueError(
                f"SFX event {event_index} starts after video end: {at:.3f}s"
            )

        gain_db = float(event.get("gain_db", -10.0))
        trim_sec = event.get("trim_sec")

        command.extend(["-i", str(sfx_file)])

        label = f"sfx{event_index}"
        chain = [
            f"[{next_input_index}:a:0]",
            "asetpts=PTS-STARTPTS",
        ]
        if trim_sec is not None:
            chain.append(f"atrim=0:{max(0.001, float(trim_sec)):.6f}")
            chain.append("asetpts=PTS-STARTPTS")

        chain.extend(
            [
                f"volume={gain_db:.3f}dB",
                f"adelay={round(at * 1000)}:all=1",
            ]
        )
        filter_parts.append(",".join(chain) + f"[{label}]")
        sfx_labels.append(label)
        next_input_index += 1

    mix_labels = [narration_mix_label]
    if music_enabled:
        mix_labels.append("music")
    mix_labels.extend(sfx_labels)

    if len(mix_labels) == 1:
        filter_parts.append("[narr]anull[mix]")
    else:
        pads = "".join(f"[{label}]" for label in mix_labels)
        filter_parts.append(
            f"{pads}amix=inputs={len(mix_labels)}:"
            "normalize=0:dropout_transition=0[mix]"
        )

    loudness_cfg = (
        profile.get("loudness")
        if isinstance(profile.get("loudness"), dict)
        else {}
    )

    if as_bool(loudness_cfg.get("enabled"), True):
        target_i = float(loudness_cfg.get("integrated_lufs", -14.0))
        target_tp = float(loudness_cfg.get("true_peak_db", -1.5))
        target_lra = float(loudness_cfg.get("lra", 11.0))
        filter_parts.append(
            "[mix]"
            f"loudnorm=I={target_i:.2f}:TP={target_tp:.2f}:LRA={target_lra:.2f}"
            "[aout]"
        )
    else:
        filter_parts.append("[mix]anull[aout]")

    command.extend(
        [
            "-filter_complex",
            ";".join(filter_parts),
            "-map",
            "0:v:0",
            "-map",
            "[aout]",
            "-t",
            f"{duration:.6f}",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(output),
        ]
    )

    print(f"Baseline: {baseline}")
    print(f"Duration: {duration:.3f}s")
    print(f"Music: {'on' if music_enabled else 'off'}")
    print(f"SFX events: {len(sfx_events)}")
    print(f"Output: {output}")

    if args.dry_run:
        print()
        print("FFmpeg command:")
        print(shlex.join(command))
        return

    subprocess.run(command, check=True)
    polished_duration = probe_duration(ffprobe, output)
    drift = polished_duration - duration

    print()
    print("Audio polish complete.")
    print(f"Polished duration: {polished_duration:.3f}s")
    print(f"Duration drift: {drift:+.3f}s")
    print(f"File: {output}")

    if abs(drift) > 0.10:
        print("WARNING: polished duration drift exceeds 100ms.")


if __name__ == "__main__":
    main()
