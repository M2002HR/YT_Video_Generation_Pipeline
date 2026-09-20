"""Independent integer-clock edit compiler and bounded FFmpeg renderer (P08).

This module deliberately has no dependency on the legacy Motion Director.  It
compiles model decisions into finite local geometry and renders one cacheable
segment at a time so shot count cannot grow one monolithic FFmpeg input graph.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any, Mapping, Sequence

from .contracts import ContractError, canonical_json_hash, stable_id

RENDERER_VERSION = "shorts-v2-renderer-r1"
TRANSITIONS = frozenset({"cut", "fade", "dissolve"})
MOTIONS = frozenset({"hold", "push", "pull", "pan", "reframe"})


@dataclass(frozen=True)
class FrameClock:
    fps_num: int
    fps_den: int = 1

    def __post_init__(self) -> None:
        if isinstance(self.fps_num, bool) or isinstance(self.fps_den, bool) or self.fps_num <= 0 or self.fps_den <= 0:
            raise ContractError("fps must be a positive rational")

    @property
    def fps(self) -> Fraction:
        return Fraction(self.fps_num, self.fps_den)

    def frames_for_samples(self, samples: int, sample_rate: int) -> int:
        if isinstance(samples, bool) or isinstance(sample_rate, bool) or samples <= 0 or sample_rate <= 0:
            raise ContractError("audio clock requires positive integer samples and sample_rate")
        value = Fraction(samples * self.fps_num, sample_rate * self.fps_den)
        # Round the audio master exactly once, half away from zero.
        return max(1, (2 * value.numerator + value.denominator) // (2 * value.denominator))

    def seconds_for_frames(self, frames: int) -> Fraction:
        return Fraction(frames * self.fps_den, self.fps_num)


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ContractError(f"{name} must be finite")
    return float(value)


def _center(value: Any, name: str) -> tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ContractError(f"{name} must contain x,y")
    return _number(value[0], name), _number(value[1], name)


def solve_geometry(
    *, source_width: int, source_height: int, output_width: int, output_height: int,
    start_center: Sequence[float], end_center: Sequence[float], start_scale: float,
    end_scale: float, duration_frames: int, fps_num: int, fps_den: int,
    max_upscale: float, max_pan_source_fraction_per_second: float,
    manual_locks: Mapping[str, Any],
) -> dict[str, Any]:
    """Clamp requested viewports to executable bounds or expose a lock conflict."""
    dimensions = (source_width, source_height, output_width, output_height, duration_frames)
    if any(isinstance(item, bool) or not isinstance(item, int) or item <= 0 for item in dimensions):
        raise ContractError("geometry dimensions and duration_frames must be positive integers")
    max_upscale = _number(max_upscale, "max_upscale")
    pan_limit = _number(max_pan_source_fraction_per_second, "max_pan_source_fraction_per_second")
    if max_upscale < 1 or pan_limit < 0:
        raise ContractError("geometry limits are invalid")
    start = _center(start_center, "start_center")
    end = _center(end_center, "end_center")
    scales = [_number(start_scale, "start_scale"), _number(end_scale, "end_scale")]
    corrections: list[str] = []
    locked = set(str(key) for key, enabled in manual_locks.items() if enabled)
    target_aspect = output_width / output_height
    base_width = min(float(source_width), float(source_height) * target_aspect)
    base_height = base_width / target_aspect
    min_width_for_upscale = output_width / max_upscale
    min_height_for_upscale = output_height / max_upscale
    if base_width + 1e-9 < min_width_for_upscale or base_height + 1e-9 < min_height_for_upscale:
        if {"geometry", "scale", "center"} & locked:
            raise ContractError("locked geometry conflict: source cannot satisfy the maximum upscale")
        raise ContractError("source resolution cannot satisfy the maximum upscale")

    def viewport(center: tuple[float, float], scale: float, label: str) -> dict[str, float]:
        original = (center, scale)
        scale = max(scale, 1e-6)
        width = base_width / scale
        height = base_height / scale
        width = max(width, min_width_for_upscale)
        height = max(height, min_height_for_upscale)
        if width > source_width or height > source_height:
            width, height = base_width, base_height
        width, height = min(width, source_width), min(height, source_height)
        cx = min(1.0, max(0.0, center[0])) * source_width
        cy = min(1.0, max(0.0, center[1])) * source_height
        x = min(max(0.0, cx - width / 2), source_width - width)
        y = min(max(0.0, cy - height / 2), source_height - height)
        if abs(center[0] - min(1.0, max(0.0, center[0]))) > 1e-9 or abs(center[1] - min(1.0, max(0.0, center[1]))) > 1e-9:
            corrections.append(f"{label}_center_clamped")
        effective_scale = base_width / width
        if abs(effective_scale - original[1]) > 1e-6:
            corrections.append(f"{label}_scale_clamped")
        return {"x": x, "y": y, "width": width, "height": height, "scale": effective_scale}

    first = viewport(start, scales[0], "start")
    last = viewport(end, scales[1], "end")
    if corrections and ({"geometry", "scale", "center"} & locked):
        raise ContractError("locked geometry conflict: requested viewport violates source/upscale bounds")
    seconds = duration_frames * fps_den / fps_num
    dx = (last["x"] + last["width"] / 2 - first["x"] - first["width"] / 2) / source_width
    dy = (last["y"] + last["height"] / 2 - first["y"] - first["height"] / 2) / source_height
    distance = math.hypot(dx, dy)
    pan_clamped = seconds > 0 and distance / seconds > pan_limit
    if pan_clamped:
        if "center" in locked or "geometry" in locked:
            raise ContractError("locked geometry conflict: requested pan exceeds the speed limit")
        ratio = (pan_limit * seconds / distance) if distance else 1.0
        last["x"] = first["x"] + (last["x"] - first["x"]) * ratio
        last["y"] = first["y"] + (last["y"] - first["y"]) * ratio
        corrections.append("end_center_pan_speed_clamped")
    noop = all(abs(first[key] - last[key]) < 1e-6 for key in ("x", "y", "width", "height"))
    return {
        "start_viewport": first, "end_viewport": last, "corrections": corrections,
        "pan_speed_clamped": pan_clamped, "is_noop": noop,
        "manual_locks": dict(manual_locks),
    }


def compile_timeline(
    *, shot_plan: Mapping[str, Any], asset_manifest: Mapping[str, Any],
    observations: Mapping[str, Mapping[str, Any]], edit_plan: Mapping[str, Any],
    audio_samples: int, sample_rate: int, fps_num: int, fps_den: int,
    width: int, height: int, max_upscale: float = 2.0,
    max_pan_source_fraction_per_second: float = .35, segment_batch_size: int = 8,
) -> dict[str, Any]:
    """Compile a complete fixed-clock timeline without accumulating duration rounding."""
    if edit_plan.get("schema_version") != 1 or set(edit_plan) != {"schema_version", "decisions"}:
        raise ContractError("edit plan has missing or unknown fields")
    if not 1 <= segment_batch_size <= 16:
        raise ContractError("segment_batch_size must be in 1..16")
    clock = FrameClock(fps_num, fps_den)
    total_frames = clock.frames_for_samples(audio_samples, sample_rate)
    shots = sorted(shot_plan.get("shots") or [], key=lambda item: item.get("display_order", -1))
    decisions = {item.get("shot_id"): item for item in edit_plan.get("decisions") or [] if isinstance(item, Mapping)}
    assets = {item.get("asset_id"): item for item in asset_manifest.get("assets") or []}
    if not shots or len(decisions) != len(shots):
        raise ContractError("every active shot requires exactly one edit decision")
    starts = [0]
    duration_seconds = audio_samples / sample_rate
    for shot in shots[1:]:
        boundary = round(_number(shot.get("start"), "shot.start") / duration_seconds * total_frames)
        starts.append(min(total_frames - 1, max(starts[-1] + 1, boundary)))
    if len(shots) > total_frames:
        raise ContractError("audio clock has fewer frames than shots; zero-frame shots are forbidden")
    segments, transitions = [], []
    for index, shot in enumerate(shots):
        shot_id = stable_id(shot.get("shot_id"), "shot_id")
        decision = decisions.get(shot_id)
        if not decision:
            raise ContractError(f"missing edit decision for {shot_id}")
        allowed = {"shot_id", "asset_id", "transition", "transition_frames", "motion", "start_scale", "end_scale", "start_center", "end_center", "easing", "manual_locks"}
        if set(decision) != allowed:
            raise ContractError(f"edit decision {shot_id} has missing or unknown fields")
        asset_id = stable_id(decision.get("asset_id"), "asset_id")
        asset = assets.get(asset_id)
        if not asset or shot_id not in asset.get("shot_ids", []):
            raise ContractError(f"edit decision {shot_id} references an unrelated asset")
        transition = str(decision.get("transition"))
        transition_frames = decision.get("transition_frames")
        if transition not in TRANSITIONS or isinstance(transition_frames, bool) or not isinstance(transition_frames, int) or transition_frames < 0:
            raise ContractError(f"edit decision {shot_id} has invalid transition")
        if transition == "cut" and transition_frames != 0:
            raise ContractError("a cut has zero transition duration")
        if transition != "cut" and (index == 0 or transition_frames == 0):
            raise ContractError("fade/dissolve requires a positive non-initial window")
        motion = str(decision.get("motion"))
        if motion not in MOTIONS:
            raise ContractError(f"edit decision {shot_id} has unsupported motion")
        start_frame = starts[index]
        end_frame = starts[index + 1] if index + 1 < len(starts) else total_frames
        if transition_frames > min(end_frame - start_frame, segments[-1]["frame_count"] if segments else 0):
            raise ContractError(f"transition for {shot_id} lacks source handles")
        observation = observations.get(asset_id) or {}
        source_width = int(observation.get("width") or 0)
        source_height = int(observation.get("height") or 0)
        if source_width <= 0 or source_height <= 0:
            raise ContractError(f"asset {asset_id} lacks safe source dimensions")
        geometry = solve_geometry(
            source_width=source_width, source_height=source_height,
            output_width=width, output_height=height,
            start_center=decision["start_center"], end_center=decision["end_center"],
            start_scale=decision["start_scale"], end_scale=decision["end_scale"],
            duration_frames=end_frame - start_frame, fps_num=fps_num, fps_den=fps_den,
            max_upscale=max_upscale,
            max_pan_source_fraction_per_second=max_pan_source_fraction_per_second,
            manual_locks=decision["manual_locks"],
        )
        cache_projection = {
            "asset_spec_hash": asset.get("asset_spec_hash"), "frames": [start_frame, end_frame],
            "geometry": geometry, "motion": motion, "easing": decision["easing"],
            "fps": [fps_num, fps_den], "resolution": [width, height], "renderer": RENDERER_VERSION,
        }
        segment = {
            "segment_id": f"segment.{index:04d}", "shot_id": shot_id, "asset_id": asset_id,
            "start_frame": start_frame, "end_frame": end_frame, "frame_count": end_frame - start_frame,
            "geometry": geometry, "motion": motion, "easing": str(decision["easing"]),
            "cache_key": canonical_json_hash(cache_projection),
        }
        segments.append(segment)
        if index:
            transitions.append({
                "boundary_id": f"boundary.{index:04d}", "from_shot_id": shots[index - 1]["shot_id"],
                "to_shot_id": shot_id, "kind": transition, "duration_frames": transition_frames,
                "start_frame": start_frame - transition_frames, "end_frame": start_frame,
                "master_clock_effect": "overlay_only_no_duration_change",
            })
    batches = [[item["segment_id"] for item in segments[index:index + segment_batch_size]] for index in range(0, len(segments), segment_batch_size)]
    compiled = {
        "schema_version": 1, "renderer_version": RENDERER_VERSION,
        "clock": {"fps_num": fps_num, "fps_den": fps_den, "audio_samples": audio_samples, "sample_rate": sample_rate, "interval": "half_open"},
        "resolution": {"width": width, "height": height}, "total_frames": total_frames,
        "audio_duration_seconds": audio_samples / sample_rate, "segments": segments, "transitions": transitions,
        "resource_plan": {"strategy": "cacheable_segments_then_concat", "max_simultaneous_visual_inputs": 2, "segment_batch_size": segment_batch_size, "segment_batches": batches},
        "input_hashes": {"shot_schedule": shot_plan.get("shot_schedule_hash"), "asset_manifest": asset_manifest.get("manifest_hash")},
    }
    compiled["compile_hash"] = canonical_json_hash(compiled)
    return compiled


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(command: list[str]) -> None:
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    if completed.returncode:
        raise ContractError(f"FFmpeg process failed ({completed.returncode}): {completed.stderr[-1000:]}")


def _probe(path: Path) -> dict[str, Any]:
    completed = subprocess.run([
        "ffprobe", "-v", "error", "-count_frames", "-show_entries",
        "format=duration:stream=index,codec_type,nb_read_frames", "-of", "json", str(path),
    ], text=True, capture_output=True, check=False)
    if completed.returncode:
        raise ContractError(f"render output is not decodable: {completed.stderr[-500:]}")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ContractError("ffprobe returned invalid JSON") from exc


def render_timeline(
    timeline: Mapping[str, Any], *, asset_paths: Mapping[str, Path], narration_path: Path,
    output_path: Path, cache_dir: Path, min_free_bytes: int = 256 * 1024 * 1024,
    threads: int = 2, crf: int = 20, presentation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Render cacheable shot segments, assemble them, then atomically mux audio."""
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise ContractError("FFmpeg and ffprobe are required")
    if not narration_path.is_file():
        raise ContractError("narration file is missing")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(output_path.parent).free < min_free_bytes:
        raise ContractError("insufficient free disk for bounded render")
    clock, resolution = timeline["clock"], timeline["resolution"]
    fps = f"{clock['fps_num']}/{clock['fps_den']}"
    rendered, reused, segment_paths = 0, 0, []
    for segment in timeline.get("segments", []):
        source = Path(asset_paths.get(segment["asset_id"], ""))
        if not source.is_file():
            raise ContractError(f"source asset is missing for {segment['asset_id']}")
        source_hash = _sha256(source)
        effective_key = canonical_json_hash({"compile_key": segment["cache_key"], "source_sha256": source_hash, "crf": crf})
        cached = cache_dir / f"{effective_key}.mp4"
        receipt_path = cache_dir / f"{effective_key}.json"
        healthy = cached.is_file() and receipt_path.is_file()
        if healthy:
            try:
                record = json.loads(receipt_path.read_text(encoding="utf-8"))
                healthy = record.get("sha256") == _sha256(cached) and record.get("frames") == segment["frame_count"]
            except (OSError, ValueError):
                healthy = False
        if healthy:
            reused += 1
            segment_paths.append(cached)
            continue
        viewport = segment["geometry"]["start_viewport"]
        crop_w, crop_h = max(2, int(viewport["width"]) // 2 * 2), max(2, int(viewport["height"]) // 2 * 2)
        crop_x, crop_y = max(0, int(viewport["x"])), max(0, int(viewport["y"]))
        temporary = cache_dir / f".{effective_key}.{os.getpid()}.partial.mp4"
        try:
            _run([
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-loop", "1", "-i", str(source),
                "-vf", f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y},scale={resolution['width']}:{resolution['height']}:flags=lanczos,fps={fps},format=yuv420p",
                "-frames:v", str(segment["frame_count"]), "-an", "-c:v", "libx264", "-preset", "veryfast",
                "-crf", str(crf), "-threads", str(max(1, min(threads, 8))), "-movflags", "+faststart", str(temporary),
            ])
            probe = _probe(temporary)
            video = next((item for item in probe.get("streams", []) if item.get("codec_type") == "video"), None)
            if not video or int(video.get("nb_read_frames") or 0) != segment["frame_count"]:
                raise ContractError("rendered segment frame count is invalid")
            os.replace(temporary, cached)
            receipt_path.write_text(json.dumps({"sha256": _sha256(cached), "frames": segment["frame_count"], "source_sha256": source_hash}), encoding="utf-8")
            rendered += 1
            segment_paths.append(cached)
        finally:
            if temporary.exists():
                temporary.unlink()
    with tempfile.TemporaryDirectory(prefix="shorts-v2-assemble-", dir=output_path.parent) as temporary_dir:
        temporary_root = Path(temporary_dir)
        concat_file = temporary_root / "segments.txt"
        concat_file.write_text("".join(f"file '{path.as_posix()}'\n" for path in segment_paths), encoding="utf-8")
        video_only = temporary_root / "video.mp4"
        _run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(concat_file), "-c", "copy", str(video_only)])
        staged = temporary_root / "final.mp4"
        duration = timeline["total_frames"] * clock["fps_den"] / clock["fps_num"]
        video_args = ["-c:v", "copy"]
        audio_filter = None
        if presentation is not None:
            if presentation.get("video_source_compile_hash") != timeline.get("compile_hash"):
                raise ContractError("presentation belongs to a different compiled timeline")
            caption_plan = presentation.get("caption_plan") or {}
            overlay_plan = presentation.get("overlay_plan") or {}
            cues = list(caption_plan.get("cues") or [])
            overlays = list(overlay_plan.get("overlays") or [])
            if caption_plan.get("enabled") or overlays:
                ass_path = temporary_root / "overlays.ass"
                style = caption_plan.get("style") or {"font": "DejaVu Sans", "size": 48, "color": "#ffffff", "outline": 3, "position": "bottom"}
                alignment = {"top": 8, "middle": 5, "bottom": 2}.get(style.get("position"), 2)
                color = str(style.get("color") or "#ffffff").lstrip("#")
                ass_color = f"&H00{color[4:6]}{color[2:4]}{color[0:2]}"

                def ass_time(seconds: float) -> str:
                    centiseconds = max(0, int(round(seconds * 100)))
                    return f"{centiseconds // 360000}:{(centiseconds // 6000) % 60:02d}:{(centiseconds // 100) % 60:02d}.{centiseconds % 100:02d}"

                def clean_ass(text: Any) -> str:
                    return str(text).replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", "\\N")

                lines = [
                    "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {resolution['width']}", f"PlayResY: {resolution['height']}",
                    "[V4+ Styles]", "Format: Name,Fontname,Fontsize,PrimaryColour,OutlineColour,Bold,Italic,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding",
                    f"Style: Caption,{style.get('font')},{int(style.get('size') or 48)},{ass_color},&H00000000,0,0,1,{float(style.get('outline') or 0):g},0,{alignment},40,40,120,1",
                    "Style: Title,DejaVu Sans,64,&H00FFFFFF,&H00000000,-1,0,1,3,0,8,40,40,90,1",
                    "Style: Watermark,DejaVu Sans,28,&H80FFFFFF,&H00000000,0,0,1,1,0,9,30,30,30,1",
                    "[Events]", "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text",
                ]
                lines.extend(f"Dialogue: 0,{ass_time(cue['start'])},{ass_time(cue['end'])},Caption,,0,0,0,,{clean_ass(cue['text'])}" for cue in cues)
                for overlay in overlays:
                    start = overlay["start_frame"] * clock["fps_den"] / clock["fps_num"]
                    end = overlay["end_frame"] * clock["fps_den"] / clock["fps_num"]
                    overlay_style = "Title" if overlay["kind"] == "title" else "Watermark"
                    lines.append(f"Dialogue: 1,{ass_time(start)},{ass_time(end)},{overlay_style},,0,0,0,,{clean_ass(overlay['text'])}")
                ass_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
                video_args = ["-vf", f"ass={ass_path}", "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), "-pix_fmt", "yuv420p"]
            gain = float((presentation.get("sound_plan") or {}).get("narration_gain_db") or 0)
            if abs(gain) > 1e-9:
                audio_filter = f"volume={gain:g}dB"
        mux_command = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(video_only), "-i", str(narration_path), "-map", "0:v:0", "-map", "1:a:0", *video_args, "-c:a", "aac"]
        if audio_filter:
            mux_command.extend(["-af", audio_filter])
        mux_command.extend(["-t", f"{duration:.9f}", "-movflags", "+faststart", str(staged)])
        _run(mux_command)
        probe = _probe(staged)
        video_stream = next((item for item in probe.get("streams", []) if item.get("codec_type") == "video"), None)
        audio_streams = [item for item in probe.get("streams", []) if item.get("codec_type") == "audio"]
        frames = int((video_stream or {}).get("nb_read_frames") or 0)
        drift = abs(frames - int(timeline["total_frames"]))
        if not video_stream or not audio_streams or drift > 1:
            raise ContractError(f"render failed A/V validation; frame drift={drift}")
        os.replace(staged, output_path)
    return {
        "schema_version": 1, "compile_hash": timeline["compile_hash"], "output_path": str(output_path),
        "output_sha256": _sha256(output_path), "validated": True, "video_frames": frames,
        "audio_streams": len(audio_streams), "duration_drift_frames": drift,
        "segments_rendered": rendered, "segments_reused": reused,
        "max_simultaneous_visual_inputs": timeline["resource_plan"]["max_simultaneous_visual_inputs"],
        "codec": "h264+aac", "renderer_version": RENDERER_VERSION,
        "presentation_hash": presentation.get("presentation_hash") if presentation else None,
        "audible_preview": True,
    }
