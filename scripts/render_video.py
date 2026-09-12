#!/usr/bin/env python3
"""Render a video from TIMELINE.json using FFmpeg.

The first render intentionally stays simple and deterministic:
- one image per beat
- smooth center-only motion with no lateral pan/jitter
- hard cuts at beat boundaries
- narration as the master audio
- readable phrase subtitles

Example:
    python scripts/render_video.py \
      videos/001_brain_replays_embarrassing_moments
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import resource
import shlex
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from pipeline_notifier import EditableMessage, PipelineNotifier, format_duration
from pipeline_stages import stage_title
from motion_compiler import dynamic_motion_filter, dynamic_motion_filter_v2, plan_render_units, plan_render_units_v2
from motion_context import build_motion_context
from motion_schema import MotionPlanError, validate_plan
from motion_v2_schema import settings as motion_v2_settings, validate_inventory, validate_plan as validate_plan_v2

ROOT = Path(__file__).resolve().parents[1]

#: Share of the machine a render may use. The server this runs on has two vCPUs and 7 GB,
#: and an uncapped x264 makes SSH, VNC and the watchdog unresponsive for the whole render.
DEFAULT_RESOURCE_BUDGET = 0.8

#: Supersampling multiplies the working frame area, which is where render memory goes.
#: Above this many megapixels of intermediate frame the factor is reduced rather than
#: letting the render get OOM-killed halfway through.
MAX_SUPERSAMPLED_MEGAPIXELS = 12.0
# A V2 episode has many camera branches in one filter graph.  Limiting only one frame
# misses their aggregate queues/buffers and can still OOM a 7 GB production host.  The
# value below keeps a 1080x1920 episode with 29 micro-shots at 1x (~60 MP aggregate),
# while allowing 2x for short previews with at most eight simultaneous branches.
MAX_GRAPH_WORKING_MEGAPIXELS = 72.0
V2_SEGMENT_RENDER_THRESHOLD = 8


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return data


def require_binary(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(
            f"{name} was not found in PATH. Install FFmpeg before rendering."
        )
    return path


def ffmpeg_has_ass_filter(ffmpeg: str) -> bool:
    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-filters"],
        capture_output=True,
        text=True,
        check=False,
    )
    text = (result.stdout or "") + "\n" + (result.stderr or "")
    return any(
        line.strip().split(maxsplit=2)[1:2] == ["ass"]
        for line in text.splitlines()
        if line.strip()
    )


#: A clip may fall this far short of its timeline slot before the render is a lie.
VIDEO_SLOT_TOLERANCE = 0.04


def cpu_count() -> int:
    """Schedulable CPUs, honouring cgroup/affinity limits rather than the host total."""
    try:
        return max(1, len(os.sched_getaffinity(0)))
    except AttributeError:
        return max(1, os.cpu_count() or 1)


def budgeted_threads(budget: float, *, cpus: int | None = None) -> int:
    """``round(cpus * budget)``, never zero and never more than the machine has."""
    total = cpus if cpus is not None else cpu_count()
    share = max(0.05, min(1.0, float(budget)))
    return max(1, min(total, round(total * share)))


def capped_supersample(requested: int, width: int, height: int, *, parallel_filters: int = 1) -> tuple[int, str]:
    """Reduce supersampling until per-frame and aggregate graph budgets both fit."""
    factor = max(1, int(requested))
    pixels = width * height
    branches = max(1, int(parallel_filters))
    while factor > 1 and (
        (pixels * factor * factor) / 1_000_000 > MAX_SUPERSAMPLED_MEGAPIXELS
        or (pixels * factor * factor * branches) / 1_000_000 > MAX_GRAPH_WORKING_MEGAPIXELS
    ):
        factor -= 1
    if factor != max(1, int(requested)):
        aggregate = (pixels * factor * factor * branches) / 1_000_000
        return factor, (
            f"supersample reduced {requested}->{factor} for {branches} camera branches "
            f"({aggregate:.1f} MP aggregate; limits {MAX_SUPERSAMPLED_MEGAPIXELS:.0f} MP/frame, "
            f"{MAX_GRAPH_WORKING_MEGAPIXELS:.0f} MP/graph)"
        )
    return factor, ""


def render_v2_segments(
    *, beats: list[dict[str, Any]], video_dir: Path, ffmpeg: str, ffprobe: str,
    width: int, height: int, fps: int, supersample: int, thread_cap: int,
    filter_threads: int, filter_complex_threads: int, nice_level: int,
    plan_fingerprint: str,
) -> tuple[list[dict[str, Any]], int, int]:
    """Render V2 still micro-shots serially, bounding memory regardless of shot count.

    A monolithic graph fed by many looped images can queue future raw frames behind concat
    and grow to several gigabytes.  These cacheable, visually lossless-ish intermediates
    leave the final graph with finite video inputs, so FFmpeg pulls frames on demand.
    """
    key = hashlib.sha256(
        f"{plan_fingerprint}|{width}x{height}|{fps}|ss={supersample}|segments-v1".encode()
    ).hexdigest()[:16]
    cache_dir = video_dir / "assets" / "renders" / ".motion_segments" / key
    cache_dir.mkdir(parents=True, exist_ok=True)
    output: list[dict[str, Any]] = []
    rendered = reused = 0
    image_units = [beat for beat in beats if str(beat.get("media_type") or "image") == "image" and beat.get("motion_shot_v2")]
    for sequence, beat in enumerate(beats, start=1):
        shot = beat.get("motion_shot_v2")
        if str(beat.get("media_type") or "image") != "image" or not isinstance(shot, dict):
            output.append(beat)
            continue
        duration = float(beat["duration"])
        segment = cache_dir / f"{sequence:03d}_{shot['shot_id']}.mp4"
        valid = False
        if segment.is_file():
            try:
                probe = probe_video(ffprobe, segment)
                stream = next(item for item in probe.get("streams", []) if item.get("codec_type") == "video")
                actual = float((probe.get("format") or {}).get("duration") or 0)
                valid = int(stream.get("width") or 0) == width and int(stream.get("height") or 0) == height and abs(actual - duration) <= .08
            except (OSError, ValueError, StopIteration):
                valid = False
        if valid:
            reused += 1
        else:
            source = resolve_video_path(video_dir, str(beat.get("image") or beat.get("source") or ""))
            label = "motion_segment"
            graph = dynamic_motion_filter_v2(
                input_index=0, label=label, width=width, height=height, fps=fps,
                duration=duration, motion_duration=duration, shot=shot, supersample=supersample,
            )
            command = [
                ffmpeg, "-hide_banner", "-loglevel", "warning", "-y",
                "-threads", str(thread_cap), "-filter_threads", str(filter_threads),
                "-filter_complex_threads", str(filter_complex_threads),
                "-loop", "1", "-framerate", str(fps), "-t", f"{duration:.6f}", "-i", str(source),
                "-filter_complex", graph, "-map", f"[{label}]", "-an", "-t", f"{duration:.6f}",
                "-c:v", "libx264", "-threads", str(thread_cap), "-preset", "veryfast", "-crf", "14",
                "-pix_fmt", "yuv420p", "-x264-params", f"threads={thread_cap}:lookahead-threads=1",
                "-movflags", "+faststart", str(segment),
            ]
            launcher = ionice_prefix()
            if nice_level:
                launcher = [*launcher, "nice", "-n", str(nice_level)]
            result = subprocess.run([*launcher, *command], text=True, capture_output=True, check=False)
            if result.returncode:
                raise RuntimeError(f"Motion segment {shot['shot_id']} failed: {(result.stderr or result.stdout)[-2000:]}")
            rendered += 1
            print(f"motion segment {rendered + reused}/{len(image_units)}: {shot['shot_id']}", flush=True)
        output.append({**beat, "media_type": "video", "source": str(segment), "motion_segment": True})
    return output, rendered, reused


def child_peak_rss_mb() -> float:
    """Peak resident memory of the FFmpeg child, as the kernel measured it."""
    try:
        usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    except (ValueError, OSError):
        return 0.0
    return round(usage.ru_maxrss / 1024, 1)


def ionice_prefix() -> list[str]:
    """Best-effort idle I/O class, so a long render does not starve the rest of the box."""
    binary = shutil.which("ionice")
    if not binary:
        return []
    return [binary, "-c", "2", "-n", "7"]


def resolve_video_path(video_dir: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return video_dir / path


def escape_filter_path(path: Path) -> str:
    value = str(path.resolve())
    value = value.replace("\\", "\\\\")
    value = value.replace(":", r"\:")
    value = value.replace("'", r"\'")
    return value


def motion_filter(
    *,
    input_index: int,
    label: str,
    width: int,
    height: int,
    fps: int,
    duration: float,
    motion: str,
    strength: float,
    supersample: int,
) -> str:
    """Create smooth center-only motion.

    Lateral pan effects were removed because integer crop movement inside
    FFmpeg's zoompan can look like micro-jitter on illustrated stills.

    Zoom effects are rendered on a supersampled canvas and downscaled afterward,
    which greatly reduces rounding shimmer while keeping subtle motion.
    """

    frames = max(2, int(math.ceil(duration * fps)))
    # ``strength`` is the full per-image zoom range. The Studio default is now a
    # deliberately noticeable 14%; retain a safe ceiling for low-detail/portrait artwork.
    strength = max(0.0, min(float(strength), 0.24))
    supersample = max(1, min(int(supersample), 4))
    if motion == "still" or strength <= 0:
        return (
            f"[{input_index}:v]"
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},"
            "setsar=1,"
            f"fps={fps},"
            f"trim=duration={duration:.6f},"
            "setpts=PTS-STARTPTS,settb=AVTB"
            f"[{label}]"
        )

    work_width = width * supersample
    work_height = height * supersample
    progress = f"min(on/{frames - 1},1)"
    accelerating_progress = f"pow({progress},1.65)"

    if motion == "zoom_out":
        effective_strength = strength
        # Exact counterpart to the inward curve: begin close, then ease back to the
        # full frame. Only the final body image receives this motion policy.
        z = f"1+{effective_strength:.6f}*pow(1-{progress},1.65)"
    elif motion == "slow_zoom_in":
        effective_strength = strength * 0.60
        z = f"1+{effective_strength:.6f}*{accelerating_progress}"
    elif motion == "slow_zoom_out":
        effective_strength = strength * 0.60
        z = f"1+{effective_strength:.6f}*pow(1-{progress},1.65)"
    else:
        effective_strength = strength
        z = f"1+{effective_strength:.6f}*{accelerating_progress}"

    # Always keep the crop centered. No pan_x/pan_y animation.
    x = "iw/2-(iw/zoom/2)"
    y = "ih/2-(ih/zoom/2)"

    return (
        f"[{input_index}:v]"
        f"scale={work_width}:{work_height}:force_original_aspect_ratio=increase,"
        f"crop={work_width}:{work_height},"
        "setsar=1,"
        f"zoompan="
        f"z='{z}':"
        f"x='{x}':"
        f"y='{y}':"
        f"d=1:s={work_width}x{work_height}:fps={fps},"
        f"scale={width}:{height}:flags=lanczos,"
        f"trim=duration={duration:.6f},"
        "setpts=PTS-STARTPTS,settb=AVTB"
        f"[{label}]"
    )


def probe_video(ffprobe: str, path: Path) -> dict[str, Any]:
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type,width,height,r_frame_rate",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    return payload if isinstance(payload, dict) else {}


#: How often a running render says where it has got to. The render is the longest step in an
#: episode, and it used to be silent until it finished, so a slow render and a stuck one looked
#: identical in the log.
# A render status is useful, but a malformed environment value must never turn
# it into a message stream.  Fifteen seconds is the shortest useful cadence.
RENDER_PROGRESS_INTERVAL_SECONDS = max(15.0, float(os.getenv("YT_RENDER_PROGRESS_INTERVAL_SECONDS", "20")))


def is_production_episode(video_dir: Path) -> bool:
    """Only a real workspace episode may emit Telegram render telemetry.

    Integration tests intentionally render tiny videos under ``/tmp``.  They use
    the same executable and environment as production, so without this boundary
    every test render looked like a completed production render in Telegram.
    """
    try:
        video_dir.resolve().relative_to(ROOT / "videos")
    except ValueError:
        return False
    return (video_dir / "launch" / "LAUNCH_REQUEST.json").is_file()


def read_process_resources(pid: int, *, started_cpu_seconds: float, elapsed_seconds: float) -> dict[str, float | str]:
    """Read render and host resource usage from procfs without another dependency."""
    process_cpu_seconds = started_cpu_seconds
    process_rss_mb = 0.0
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        fields = stat[stat.rfind(")") + 2 :].split()
        ticks = float(os.sysconf("SC_CLK_TCK"))
        process_cpu_seconds = (float(fields[11]) + float(fields[12])) / ticks
    except (OSError, ValueError, IndexError):
        pass
    try:
        for line in Path(f"/proc/{pid}/status").read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                process_rss_mb = float(line.split()[1]) / 1024
                break
    except (OSError, ValueError, IndexError):
        pass
    mem_total = mem_available = 0.0
    try:
        values = {
            line.split(":", 1)[0]: float(line.split()[1]) / 1024 / 1024
            for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines()
            if ":" in line and len(line.split()) >= 2
        }
        mem_total = values.get("MemTotal", 0.0)
        mem_available = values.get("MemAvailable", 0.0)
    except (OSError, ValueError):
        pass
    try:
        load = os.getloadavg()[0]
    except OSError:
        load = 0.0
    return {
        "render_cpu_percent": max(0.0, (process_cpu_seconds - started_cpu_seconds) / max(elapsed_seconds, 0.001) * 100),
        "render_rss_mb": process_rss_mb,
        "system_memory_used_gb": max(0.0, mem_total - mem_available),
        "system_memory_total_gb": mem_total,
        "load_1m": load,
    }


def render_progress_message(
    video_id: str,
    progress: dict[str, Any],
    resources: dict[str, float | str],
    *,
    finished: bool = False,
    failed: bool = False,
    title: str | None = None,
) -> str:
    """One compact, readable Telegram message for the entire render lifecycle."""
    percent = max(0, min(100, round(float(progress.get("share", 0.0)) * 100)))
    filled = round(percent / 10)
    bar = "▓" * filled + "░" * (10 - filled)
    state = "✅ Render complete" if finished else "❌ Render failed" if failed else "🎬 Rendering"
    position = float(progress.get("position", 0.0))
    total = float(progress.get("total_seconds", 0.0))
    elapsed = float(progress.get("elapsed_seconds", 0.0))
    remaining = float(progress.get("remaining_seconds", 0.0))
    speed = str(progress.get("speed") or "—")
    frame = str(progress.get("frame") or "—")
    eta = "—" if not remaining else format_duration(remaining)
    return "\n".join([
        f"<b>{title or f'Video {video_id}'} · {state}</b>",
        "",
        f"<code>{bar}</code> <b>{percent}%</b>",
        f"🎞 Encoded: {format_duration(position)} / {format_duration(total)} · frame {frame}",
        f"⚡ Speed: {speed} · ⏱ Elapsed: {format_duration(elapsed)} · ETA: {eta}",
        "",
        "<b>🖥 Resources</b>",
        f"• FFmpeg: {float(resources.get('render_cpu_percent', 0.0)):.0f}% CPU · {float(resources.get('render_rss_mb', 0.0)):.0f} MB RAM",
        f"• System: {float(resources.get('system_memory_used_gb', 0.0)):.1f}/{float(resources.get('system_memory_total_gb', 0.0)):.1f} GB RAM · load {float(resources.get('load_1m', 0.0)):.2f}",
        "",
        "↻ Live update every 20 seconds" if not (finished or failed) else "↻ Final render status",
    ])


class TelegramRenderProgress:
    """One durable, in-place Telegram monitor for one render lifecycle."""

    def __init__(self, video_id: str, total_seconds: float, state_path: Path, title: str | None = None) -> None:
        self.notifier = PipelineNotifier(video_id=video_id, topic="render")
        self.total_seconds = total_seconds
        self.state_path = state_path
        self.message: EditableMessage | None = None
        self.pid = 0
        self.started_cpu_seconds = 0.0
        self.title = title or stage_title("render_baseline")

    def _save_state(self, status: str) -> None:
        if self.message is None:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps({"schema_version": 1, "message_id": self.message.message_id, "status": status}, indent=2) + "\n",
            encoding="utf-8",
        )

    def _restore_running_message(self, body: str) -> EditableMessage | None:
        """Reuse a monitor left by a restarted parent instead of sending another one."""
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
            message_id = int(payload.get("message_id") or 0)
        except (OSError, ValueError, TypeError):
            return None
        if payload.get("status") != "RUNNING" or message_id <= 0:
            return None
        message = EditableMessage(message_id=message_id)
        return message if self.notifier.edit(message, body) else None

    def start(self, pid: int) -> None:
        self.pid = pid
        initial = read_process_resources(pid, started_cpu_seconds=0.0, elapsed_seconds=1.0)
        self.started_cpu_seconds = max(0.0, float(initial.get("render_cpu_percent", 0.0)) / 100)
        # Start at precisely 0%, before FFmpeg has encoded a frame.
        body = render_progress_message(
            self.notifier.video_id,
            {"share": 0.0, "position": 0.0, "total_seconds": self.total_seconds, "elapsed_seconds": 0.0},
            initial,
            title=self.title,
        )
        self.message = self._restore_running_message(body) or self.notifier.send_editable(body)
        self._save_state("RUNNING")

    def update(self, progress: dict[str, Any]) -> None:
        if self.message is None:
            return
        resources = read_process_resources(
            self.pid, started_cpu_seconds=self.started_cpu_seconds,
            elapsed_seconds=float(progress.get("elapsed_seconds", 0.0)),
        )
        self.notifier.edit(self.message, render_progress_message(self.notifier.video_id, progress, resources, title=self.title))

    def finish(self, progress: dict[str, Any], *, failed: bool = False) -> None:
        if self.message is None:
            return
        resources = read_process_resources(
            self.pid, started_cpu_seconds=self.started_cpu_seconds,
            elapsed_seconds=max(0.001, float(progress.get("elapsed_seconds", 0.0))),
        )
        self.notifier.edit(
            self.message,
            render_progress_message(self.notifier.video_id, progress, resources, finished=not failed, failed=failed, title=self.title),
        )
        self._save_state("FAILED" if failed else "DONE")


def run_with_progress(
    command: list[str],
    *,
    total_seconds: float,
    interval: float = RENDER_PROGRESS_INTERVAL_SECONDS,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> None:
    """Run ffmpeg, reporting the timeline position it has encoded on a fixed cadence.

    ``-progress pipe:1`` is ffmpeg's own machine-readable stream, so the percentage is measured
    against the timeline's known duration rather than guessed from wall time. Failure still
    raises ``CalledProcessError``, exactly as ``subprocess.run(check=True)`` did.
    """
    binary = next((index for index, part in enumerate(command) if part.endswith("ffmpeg")), 0)
    progressive = [*command]
    progressive[binary + 1 : binary + 1] = ["-nostats", "-progress", "pipe:1"]
    process = subprocess.Popen(progressive, stdout=subprocess.PIPE, text=True, bufsize=1)
    started = time.monotonic()
    last_report = started
    position = 0.0
    speed = ""
    frame = ""
    if progress_callback is not None:
        progress_callback({
            "position": 0.0, "total_seconds": total_seconds, "share": 0.0,
            "elapsed_seconds": 0.0, "remaining_seconds": 0.0,
            "speed": speed, "frame": frame, "pid": process.pid, "event": "started",
        })
    assert process.stdout is not None
    for line in process.stdout:
        key, _, value = line.strip().partition("=")
        value = value.strip()
        if key == "out_time_ms":
            try:
                position = int(value) / 1_000_000
            except ValueError:
                pass
        elif key == "speed":
            speed = value
        elif key == "frame":
            frame = value
        now = time.monotonic()
        if now - last_report < interval:
            continue
        last_report = now
        elapsed = now - started
        share = min(1.0, position / total_seconds) if total_seconds > 0 else 0.0
        remaining = (elapsed / share - elapsed) if share > 0.02 else 0.0
        progress = {
            "position": position, "total_seconds": total_seconds, "share": share,
            "elapsed_seconds": elapsed, "remaining_seconds": remaining,
            "speed": speed, "frame": frame, "pid": process.pid, "event": "progress",
        }
        if progress_callback is not None:
            progress_callback(progress)
        left = f" · ~{remaining / 60:.1f}m left" if remaining else ""
        print(
            f"render progress: {share * 100:.0f}% ({position:.1f}s/{total_seconds:.1f}s) "
            f"· frame {frame or '?'} · {speed or '?'} · {elapsed / 60:.1f}m elapsed{left}",
            flush=True,
        )
    code = process.wait()
    final_elapsed = time.monotonic() - started
    final_progress = {
        "position": total_seconds if code == 0 else position,
        "total_seconds": total_seconds,
        "share": 1.0 if code == 0 else (min(1.0, position / total_seconds) if total_seconds > 0 else 0.0),
        "elapsed_seconds": final_elapsed,
        "remaining_seconds": 0.0,
        "speed": speed,
        "frame": frame,
        "pid": process.pid,
        "event": "finished" if code == 0 else "failed",
    }
    if progress_callback is not None:
        progress_callback(final_progress)
    if code != 0:
        raise subprocess.CalledProcessError(code, progressive)


def main() -> None:
    parser = argparse.ArgumentParser(description="Render video timeline with FFmpeg.")
    parser.add_argument("video_dir", type=Path)
    parser.add_argument(
        "--timeline",
        type=Path,
        default=None,
        help="Defaults to <video>/timeline/TIMELINE.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Defaults to <video>/assets/renders/preview.mp4",
    )
    parser.add_argument(
        "--no-subtitles",
        action="store_true",
        help="Render without burning subtitles.",
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=None,
        help="Override the profile FFmpeg thread cap. A cap of 1 keeps a small server responsive.",
    )
    parser.add_argument(
        "--resource-budget",
        type=float,
        default=float(os.getenv("YT_RENDER_RESOURCE_BUDGET", str(DEFAULT_RESOURCE_BUDGET))),
        help=(
            "Share of the machine the render may use (default 0.8). Sets the thread caps from "
            "the schedulable CPU count unless --threads or the profile overrides them."
        ),
    )
    parser.add_argument(
        "--nice",
        type=int,
        default=int(os.getenv("YT_RENDER_NICE", "10")),
        help="Niceness for FFmpeg (0-19). Combined with idle I/O priority when ionice exists.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and print the FFmpeg command without running it.",
    )
    parser.add_argument(
        "--no-telegram-progress",
        action="store_true",
        help="Disable the editable Telegram render-progress message for this invocation.",
    )
    parser.add_argument("--telegram-title", default="", help="Exact active-plan title for the mutable Telegram render message.")
    args = parser.parse_args()

    ffmpeg = require_binary("ffmpeg")
    ffprobe = require_binary("ffprobe")

    video_dir = args.video_dir.expanduser().resolve()
    timeline_path = (
        args.timeline.expanduser().resolve()
        if args.timeline
        else video_dir / "timeline" / "TIMELINE.json"
    )

    if not timeline_path.exists():
        raise FileNotFoundError(
            f"Timeline not found: {timeline_path}\n"
            "Build it first with: "
            f"python scripts/build_timeline.py {video_dir}"
        )

    timeline = load_json(timeline_path)

    profile_value = str(timeline.get("render_profile") or "render/RENDER_PROFILE.json")
    profile_path = resolve_video_path(video_dir, profile_value)
    profile = load_json(profile_path)

    resolution = timeline.get("resolution") or {}
    width = int(resolution.get("width", 1920))
    height = int(resolution.get("height", 1080))
    fps = int(timeline.get("fps", 30))
    duration = float(timeline["duration"])

    beats_value = timeline.get("beats")
    if not isinstance(beats_value, list) or not beats_value:
        raise ValueError("Timeline contains no beats.")

    beats = [dict(item) for item in beats_value if isinstance(item, dict)]
    if len(beats) != len(beats_value):
        raise ValueError("Timeline contains an invalid beat entry.")

    # Dynamic plans are deliberately optional: old episodes retain their exact legacy
    # center-motion path. A plan is semantic data validated before any FFmpeg is built.
    dynamic_plan = None
    dynamic_plan_version = 0
    plan_path = video_dir / "motion" / "MOTION_PLAN.json"
    launch_brief = load_json(video_dir / "launch" / "CREATIVE_BRIEF.json") if (video_dir / "launch" / "CREATIVE_BRIEF.json").is_file() else {}
    launch_motion = launch_brief.get("_motion") if isinstance(launch_brief.get("_motion"), dict) else {}
    plan_enabled = bool(launch_motion.get("enabled", True))
    if plan_path.is_file() and plan_enabled:
        try:
            semantic = load_json(plan_path)
            dynamic_plan_version = int(semantic.get("schema_version", 0))
            if dynamic_plan_version == 2:
                cfg = motion_v2_settings(semantic.get("settings_snapshot") if isinstance(semantic.get("settings_snapshot"), dict) else launch_motion)
                motion_context = build_motion_context(video_dir, timeline, cfg)
                inventory = validate_inventory(load_json(video_dir / "motion" / "VISUAL_INVENTORY.json"), motion_context["beats"])
                semantic = validate_plan_v2(semantic, motion_context, inventory, cfg)
                compiled_path = video_dir / "motion" / "COMPILED_MOTION_PLAN.json"
                if not compiled_path.is_file():
                    raise MotionPlanError("V2 plan requires COMPILED_MOTION_PLAN.json")
                dynamic_plan = load_json(compiled_path)
                if not dynamic_plan.get("compiled") or dynamic_plan.get("input_fingerprint") != semantic.get("input_fingerprint"):
                    raise MotionPlanError("compiled plan is missing or stale")
                # Compilation is data-only, but verify that its semantic identifiers and
                # timings still match the validated plan before FFmpeg sees it.
                semantic_shots = [s["shot_id"] for b in semantic["beats"] for s in b["micro_shots"]]
                compiled_shots = [s.get("shot_id") for b in dynamic_plan.get("beats", []) for s in b.get("micro_shots", [])]
                if semantic_shots != compiled_shots or any("compiled_camera" not in s for b in dynamic_plan["beats"] for s in b["micro_shots"]):
                    raise MotionPlanError("compiled camera data does not match semantic plan")
                beats = plan_render_units_v2(dynamic_plan, beats)
            elif dynamic_plan_version == 1:
                dynamic_plan = validate_plan(semantic, timeline)
                beats = plan_render_units(dynamic_plan, beats)
            else:
                raise MotionPlanError("unsupported motion plan schema version")
            print(f"Dynamic motion V{dynamic_plan_version}: {sum(1 for b in beats if b.get('motion_shot') or b.get('motion_shot_v2'))} micro-shots")
        except (MotionPlanError, ValueError) as exc:
            raise ValueError(f"Invalid MOTION_PLAN.json; refusing unsafe dynamic render: {exc}") from exc

    audio_path = resolve_video_path(video_dir, str(timeline["audio"]))
    if not audio_path.exists():
        raise FileNotFoundError(f"Narration audio not found: {audio_path}")

    # Mixed-media validation: check appropriate asset per media_type (§69)
    image_paths: list[Path] = []  # kept for backward compatibility but will hold mixed input paths
    for beat in beats:
        mt = str(beat.get("media_type") or "image").lower()
        if mt == "video":
            src = beat.get("source") or beat.get("image")
            if not src:
                raise ValueError(f"Video beat {beat.get('beat_id')} missing source")
            p = resolve_video_path(video_dir, str(src))
            if not p.exists():
                raise FileNotFoundError(f"Beat {beat['beat_id']} video not found: {p}")
            # A clip shorter than its slot silently shortens the concat and drifts the
            # narration against everything after it, so it fails here instead (§70).
            slot = float(beat["duration"])
            probed = probe_video(ffprobe, p).get("format") or {}
            actual = float(probed.get("duration") or 0.0)
            if actual + VIDEO_SLOT_TOLERANCE < slot:
                raise ValueError(
                    f"Beat {beat['beat_id']} needs {slot:.3f}s of video but {p.name} is only "
                    f"{actual:.3f}s. Re-generate or re-trim that clip: rendering it would drop "
                    f"{slot - actual:.3f}s and desynchronise the narration."
                )
            image_paths.append(p)  # reuse list for input order (actually mixed)
        else:
            src = beat.get("image") or beat.get("source")
            if not src:
                raise ValueError(f"Image beat {beat.get('beat_id')} missing image/source")
            p = resolve_video_path(video_dir, str(src))
            if not p.exists():
                raise FileNotFoundError(f"Beat {beat['beat_id']} image not found: {p}")
            image_paths.append(p)

    output_path = (
        args.output.expanduser().resolve()
        if args.output
        else video_dir / "assets" / "renders" / "preview.mp4"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    motion_cfg = profile.get("motion") if isinstance(profile.get("motion"), dict) else {}
    motion_enabled = bool(motion_cfg.get("enabled", True))
    motion_strength = float(motion_cfg.get("strength", 0.035))
    motion_branches = sum(
        1 for beat in beats
        if str(beat.get("media_type") or "image") == "image" and beat.get("motion_shot_v2")
    ) if dynamic_plan_version == 2 else 1
    segmented_dynamic = dynamic_plan_version == 2 and motion_branches > V2_SEGMENT_RENDER_THRESHOLD and not args.dry_run
    motion_supersample, supersample_note = capped_supersample(
        int((dynamic_plan.get("settings_snapshot") or {}).get("supersample", motion_cfg.get("supersample", 2))) if dynamic_plan_version == 2 else int(motion_cfg.get("supersample", 2)),
        width, height, parallel_filters=1 if segmented_dynamic else motion_branches,
    )
    if segmented_dynamic:
        supersample_note = (
            f"resource-safe segmented V2 backend for {motion_branches} camera branches; "
            f"micro-shots render serially at {motion_supersample}x"
        )
    if supersample_note:
        print(f"Resource budget: {supersample_note}")

    subtitle_cfg = (
        profile.get("subtitles")
        if isinstance(profile.get("subtitles"), dict)
        else {}
    )
    subtitles_enabled = bool(subtitle_cfg.get("enabled", True)) and not args.no_subtitles
    subtitle_path = video_dir / "timeline" / "SUBTITLES.ass"

    if subtitles_enabled:
        if not subtitle_path.exists():
            raise FileNotFoundError(
                f"Subtitle file not found: {subtitle_path}\n"
                "Rebuild the timeline first."
            )
        if not ffmpeg_has_ass_filter(ffmpeg):
            raise RuntimeError(
                "This FFmpeg build does not expose the 'ass' subtitle filter. "
                "Install an FFmpeg build with libass, or render with --no-subtitles."
            )

    video_cfg = profile.get("video") if isinstance(profile.get("video"), dict) else {}
    audio_cfg = profile.get("audio") if isinstance(profile.get("audio"), dict) else {}

    video_codec = str(video_cfg.get("codec", "libx264"))
    preset = str(video_cfg.get("preset", "medium"))
    crf = int(video_cfg.get("crf", 18))
    pixel_format = str(video_cfg.get("pixel_format", "yuv420p"))
    audio_codec = str(audio_cfg.get("codec", "aac"))
    audio_bitrate = str(audio_cfg.get("bitrate", "192k"))

    resource_cfg = (
        profile.get("resource_limits")
        if isinstance(profile.get("resource_limits"), dict)
        else {}
    )
    # Precedence: --threads (explicit) > profile ffmpeg_threads > the resource budget.
    budget_threads = budgeted_threads(args.resource_budget)
    if args.threads is not None:
        thread_cap = max(1, args.threads)
        thread_source = "--threads"
    elif "ffmpeg_threads" in resource_cfg:
        thread_cap = max(1, int(resource_cfg["ffmpeg_threads"]))
        thread_source = "render profile"
    else:
        thread_cap = budget_threads
        thread_source = f"{args.resource_budget:.2f} of {cpu_count()} CPU(s)"
    filter_threads = max(1, int(resource_cfg.get("filter_threads", thread_cap)))
    filter_complex_threads = max(
        1, int(resource_cfg.get("filter_complex_threads", filter_threads))
    )

    segment_rendered = segment_reused = 0
    if segmented_dynamic:
        beats, segment_rendered, segment_reused = render_v2_segments(
            beats=beats, video_dir=video_dir, ffmpeg=ffmpeg, ffprobe=ffprobe,
            width=width, height=height, fps=fps, supersample=motion_supersample,
            thread_cap=thread_cap, filter_threads=filter_threads,
            filter_complex_threads=filter_complex_threads,
            nice_level=max(0, min(19, int(args.nice))),
            plan_fingerprint=str((dynamic_plan or {}).get("input_fingerprint") or "unfingerprinted"),
        )
        print(f"Motion segment cache: rendered={segment_rendered}, reused={segment_reused}")

    # These are deliberately global options. Without explicit caps, FFmpeg can
    # schedule filters and x264 across every vCPU, starving SSH/VNC on small
    # Ordak servers during a long render.
    command: list[str] = [
        ffmpeg,
        "-hide_banner",
        "-nostats",
        "-loglevel",
        "warning",
        "-y",
        "-threads",
        str(thread_cap),
        "-filter_threads",
        str(filter_threads),
        "-filter_complex_threads",
        str(filter_complex_threads),
    ]

    # Mixed-media inputs: image vs video (§69-70). Each source receives a tiny tail hold when
    # the next boundary crossfades; that overlap preserves the measured total duration.
    # Build input list and remember which indices are video
    media_types: list[str] = []
    input_paths: list[Path] = []
    source_media_types: list[str] = []
    unit_input_indices: list[int] = []
    reusable_images: dict[str, int] = {}
    for beat in beats:
        mt = str(beat.get("media_type") or "image").lower()
        # legacy beats without media_type -> image
        if mt not in ("video", "image"):
            mt = "image"
        # resolve path: for video use source, for image use image/source
        if mt == "video":
            src = beat.get("source") or beat.get("image")
            if not src:
                raise ValueError(f"Video beat {beat.get('beat_id')} missing source")
            path = resolve_video_path(video_dir, str(src))
            # Flow sources may contain audio — we strip it, so mark as video
            media_types.append("video")
            unit_input_indices.append(len(input_paths)); input_paths.append(path); source_media_types.append("video")
        else:
            src = beat.get("image") or beat.get("source")
            path = resolve_video_path(video_dir, str(src))
            media_types.append("image")
            # V2 micro-shots from one still share a single looped decoder. The filter
            # graph splits it into independent camera branches, reducing descriptors,
            # decode work, and memory pressure without duplicating image files.
            key = str(path.resolve())
            if dynamic_plan_version == 2 and key in reusable_images:
                unit_input_indices.append(reusable_images[key])
            else:
                source_index = len(input_paths)
                unit_input_indices.append(source_index); input_paths.append(path); source_media_types.append("image")
                if dynamic_plan_version == 2:
                    reusable_images[key] = source_index

    allowed_transitions = {
        "fade", "dissolve", "fadeblack", "fadewhite", "smoothleft", "smoothright", "smoothup", "smoothdown",
        "wipeleft", "wiperight", "wipeup", "wipedown", "wipetl", "wipetr", "wipebl", "wipebr",
        "slideleft", "slideright", "slideup", "slidedown", "radial", "circleopen", "circleclose", "zoomin",
        "hblur", "distance", "diagtl", "diagtr", "diagbl", "diagbr", "coverleft", "coverright", "coverup",
        "coverdown", "revealleft", "revealright", "revealup", "revealdown",
    }
    incoming_transitions: list[tuple[str, float]] = [("cut", 0.0)]
    for index, beat in enumerate(beats[1:], start=1):
        name = str(beat.get("transition_in") or "fade").strip().lower()
        if name == "cut":
            incoming_transitions.append(("cut", 0.0))
            continue
        if name not in allowed_transitions:
            name = "fade"
        requested = float(beat.get("transition_seconds") or 0.24)
        max_overlap = max(0.08, min(float(beats[index - 1]["duration"]), float(beat["duration"])) / 3)
        incoming_transitions.append((name, round(max(0.08, min(requested, max_overlap, 0.45)), 3)))
    outgoing_holds = [
        incoming_transitions[index + 1][1] if index + 1 < len(beats) else 0.0
        for index in range(len(beats))
    ]

    required_source_durations = [0.0 for _ in input_paths]
    for unit_index, beat in enumerate(beats):
        required_source_durations[unit_input_indices[unit_index]] = max(
            required_source_durations[unit_input_indices[unit_index]],
            float(beat["duration"]) + outgoing_holds[unit_index],
        )
    for idx, (path, mt) in enumerate(zip(input_paths, source_media_types)):
        if not path.exists():
            raise FileNotFoundError(f"Render {mt} input not found: {path}")
        dur = required_source_durations[idx]
        if mt == "image":
            command.extend(["-loop", "1", "-framerate", str(fps), "-t", f"{dur:.6f}", "-i", str(path)])
        else:
            # video: strip audio via -an (we also ensure later mapping ignores video audio), normalize via filter
            # use accurate seek if needed; for now, input as is and trim via filter if source longer than needed
            command.extend(["-i", str(path)])

    audio_input_index = len(input_paths)
    command.extend(["-i", str(audio_path)])

    filter_parts: list[str] = []
    labels: list[str] = []

    # One source pad cannot feed several filters directly. Split only reused stills;
    # single-use and video inputs stay on the simplest possible path.
    source_use_counts = {index: unit_input_indices.count(index) for index in set(unit_input_indices)}
    unit_input_refs: list[int | str] = list(unit_input_indices)
    for source_index, count in source_use_counts.items():
        if count <= 1:
            continue
        names = [f"motion_src_{source_index}_{branch}" for branch in range(count)]
        filter_parts.append(f"[{source_index}:v]split={count}" + "".join(f"[{name}]" for name in names))
        cursor = 0
        for unit_index, value in enumerate(unit_input_indices):
            if value == source_index:
                unit_input_refs[unit_index] = names[cursor]; cursor += 1

    for index, (beat, mt) in enumerate(zip(beats, media_types)):
        label = f"v{index}"
        labels.append(f"[{label}]")
        base_dur = float(beat["duration"])
        dur = base_dur + outgoing_holds[index]
        if mt == "video":
            # Normalize video: scale+pad to target, set SAR, fps, format, trim/pad to exact duration
            # §70: normalize dimensions, SAR, pixel format, frame rate, strip Flow source audio
            # We trim to dur via -t on input already, but ensure filter outputs exactly dur
            # Use fps and scale filters
            filter_parts.append(
                f"[{unit_input_refs[index]}:v]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1,fps={fps},format={pixel_format},trim=duration={base_dur:.6f},setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration={outgoing_holds[index]:.6f},trim=duration={dur:.6f},setpts=PTS-STARTPTS,settb=AVTB[{label}]"
            )
        else:
            if dynamic_plan_version == 2 and isinstance(beat.get("motion_shot_v2"), dict):
                filter_parts.append(dynamic_motion_filter_v2(
                    input_index=unit_input_refs[index], label=label, width=width, height=height, fps=fps,
                    duration=dur, motion_duration=base_dur, shot=beat["motion_shot_v2"],
                    supersample=motion_supersample,
                ))
            elif dynamic_plan_version == 1 and isinstance(beat.get("motion_shot"), dict):
                compiled, corrections = dynamic_motion_filter(
                    input_index=index, label=label, width=width, height=height, fps=fps,
                    duration=dur, shot=beat["motion_shot"], supersample=motion_supersample,
                    subtitle_top=float((subtitle_cfg.get("safe_region") or {}).get("top", .78)),
                )
                if corrections:
                    beat["motion_shot"]["target_corrected"] = True
                    beat["motion_shot"]["target_corrections"] = corrections
                filter_parts.append(compiled)
            else:
                motion = str(beat.get("motion") or "still") if motion_enabled else "still"
                strength = motion_strength if motion_enabled else 0.0
                filter_parts.append(motion_filter(input_index=index, label=label, width=width, height=height, fps=fps, duration=dur, motion=motion, strength=strength, supersample=motion_supersample))

    concat_output = "vcat"
    current_label = "v0"
    planned_duration = float(beats[0]["duration"])
    for index in range(1, len(beats)):
        transition, overlap = incoming_transitions[index]
        next_label = f"x{index}"
        if transition == "cut":
            # A real cut is a concat, not a tiny disguised crossfade.
            filter_parts.append(f"[{current_label}][v{index}]concat=n=2:v=1:a=0[{next_label}]")
        else:
            filter_parts.append(f"[{current_label}][v{index}]xfade=transition={transition}:duration={overlap:.3f}:offset={planned_duration:.6f}[{next_label}]")
        current_label = next_label
        planned_duration += float(beats[index]["duration"])
    filter_parts.append(f"[{current_label}]null[{concat_output}]")

    final_video_label = concat_output
    if subtitles_enabled:
        final_video_label = "vout"
        ass_path = escape_filter_path(subtitle_path)
        # Operator-uploaded subtitle faces are stored with the panel, outside an
        # episode directory.  Passing the directory directly to libass makes the
        # persisted selected family deterministic without relying on system cache.
        custom_fonts_dir = ROOT / "control_panel" / "subtitle_fonts"
        fontsdir = (
            f":fontsdir='{escape_filter_path(custom_fonts_dir)}'"
            if custom_fonts_dir.is_dir()
            else ""
        )
        filter_parts.append(
            f"[{concat_output}]ass=filename='{ass_path}'{fontsdir}[{final_video_label}]"
        )

    filter_complex = ";".join(filter_parts)

    command.extend(
        [
            "-filter_complex",
            filter_complex,
            "-map",
            f"[{final_video_label}]",
            "-map",
            f"{audio_input_index}:a:0",
            "-t",
            f"{duration:.6f}",
            "-c:v",
            video_codec,
            # ``-threads`` must appear in the output encoder option group;
            # the earlier global option only constrains decoder threads.
            "-threads",
            str(thread_cap),
            "-preset",
            preset,
            "-crf",
            str(crf),
            "-pix_fmt",
            pixel_format,
            "-c:a",
            audio_codec,
            "-b:a",
            audio_bitrate,
            "-movflags",
            "+faststart",
            "-shortest",
            str(output_path),
        ]
    )

    if video_codec == "libx264":
        # libx264 otherwise derives a separate look-ahead worker even when
        # FFmpeg's generic thread cap is set.
        insert_at = command.index("-c:a")
        command[insert_at:insert_at] = [
            "-x264-params",
            f"threads={thread_cap}:lookahead-threads=1",
        ]

    print(f"Timeline: {timeline_path}")
    print(f"Beats: {len(beats)}")
    print(f"Resolution: {width}x{height} @ {fps}fps")
    print(f"Duration target: {duration:.3f}s")
    nice_level = max(0, min(19, int(args.nice)))
    launcher: list[str] = ionice_prefix()
    if nice_level:
        launcher = [*launcher, "nice", "-n", str(nice_level)]
    command = [*launcher, *command] if launcher else command

    print(f"Subtitles: {'on' if subtitles_enabled else 'off'}")
    print(
        f"Resource caps: encoder={thread_cap}, filter={filter_threads}, "
        f"complex={filter_complex_threads} (from {thread_source})"
    )
    print(f"Scheduling: nice={nice_level}, io={'idle-ish' if ionice_prefix() else 'default'}")
    print(f"Supersample: {motion_supersample}")
    print(f"Output: {output_path}")

    if args.dry_run:
        print()
        print("FFmpeg command:")
        print(shlex.join(command))
        return

    started = time.perf_counter()
    reporter = None if args.no_telegram_progress or not is_production_episode(video_dir) else TelegramRenderProgress(
        video_dir.name.split("_", 1)[0], duration, video_dir / "render" / "TELEGRAM_RENDER_PROGRESS.json",
        title=args.telegram_title or None,
    )

    def report_render_progress(progress: dict[str, Any]) -> None:
        if reporter is None:
            return
        event = str(progress.get("event") or "")
        if event == "started":
            reporter.start(int(progress["pid"]))
        elif event in {"finished", "failed"}:
            reporter.finish(progress, failed=event == "failed")
        else:
            reporter.update(progress)

    run_with_progress(command, total_seconds=duration, progress_callback=report_render_progress)
    elapsed = time.perf_counter() - started

    probe = probe_video(ffprobe, output_path)
    actual_duration = float((probe.get("format") or {}).get("duration") or 0.0)
    drift = actual_duration - duration

    stats = {
        "schema_version": 1,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "output": str(output_path),
        "output_bytes": output_path.stat().st_size if output_path.exists() else 0,
        "target_duration_seconds": round(duration, 3),
        "actual_duration_seconds": round(actual_duration, 3),
        "duration_drift_seconds": round(drift, 3),
        "wall_seconds": round(elapsed, 3),
        "realtime_factor": round(elapsed / duration, 3) if duration else None,
        "beats": len(beats),
        "resolution": f"{width}x{height}",
        "fps": fps,
        "subtitles": subtitles_enabled,
        "resource_budget": round(float(args.resource_budget), 3),
        "cpus_available": cpu_count(),
        "threads": {
            "encoder": thread_cap,
            "filter": filter_threads,
            "filter_complex": filter_complex_threads,
            "source": thread_source,
        },
        "nice": nice_level,
        "ionice": bool(ionice_prefix()),
        "supersample": motion_supersample,
        "supersample_note": supersample_note,
        "motion_render_backend": "segmented_v2" if segmented_dynamic else "single_graph",
        "motion_segments_rendered": segment_rendered,
        "motion_segments_reused": segment_reused,
        "peak_child_rss_mb": child_peak_rss_mb(),
    }
    stats_path = video_dir / "render" / "RENDER_STATS.json"
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print()
    print("Render complete.")
    print(f"Actual duration: {actual_duration:.3f}s")
    print(f"Duration drift: {drift:+.3f}s")
    print(f"Wall time: {elapsed:.1f}s ({stats['realtime_factor']}x realtime)")
    print(f"Peak child RSS: {stats['peak_child_rss_mb']} MB")
    print(f"Stats: {stats_path}")
    print(f"File: {output_path}")

    if abs(drift) > 0.10:
        print("WARNING: render duration drift exceeds 100ms; inspect before final export.")


if __name__ == "__main__":
    main()
