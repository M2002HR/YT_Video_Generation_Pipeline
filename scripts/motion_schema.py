"""Validated, deterministic contract for the Motion Director.

The director may describe editorial intent, never FFmpeg expressions.  Coordinates are
normalised image-space bounding boxes: x/y are centre coordinates and w/h are sizes.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

MOTIONS = {"hold", "push_in", "pull_out", "pan", "pan_push", "pan_pull", "punch_in", "punch_out", "reframe_cut", "establish", "drift"}
EASINGS = {"linear", "ease_in", "ease_out", "ease_in_out", "snappy", "gentle", "hold_then_move"}
TRANSITIONS = {"cut", "dissolve", "fade", "smoothleft", "smoothright", "smoothup", "smoothdown", "wipeleft", "wiperight", "wipeup", "wipedown", "slideleft", "slideright", "slideup", "slidedown", "revealleft", "revealright", "revealup", "revealdown", "zoomin"}
PACE_INTERVALS = {"calm": (2.0, 3.5), "balanced": (1.4, 2.4), "fast": (.8, 1.6), "very_fast": (.55, 1.2)}


class MotionPlanError(ValueError):
    pass


def defaults(value: dict[str, Any] | None = None) -> dict[str, Any]:
    source = value or {}
    return {
        "enabled": bool(source.get("enabled", True)), "pace": str(source.get("pace", "fast")),
        "intensity": str(source.get("intensity", "normal")), "style": str(source.get("style", "dynamic")),
        "max_micro_shots_per_beat": int(source.get("max_micro_shots_per_beat", 3)),
        "min_micro_shot_duration": float(source.get("min_micro_shot_duration", .55)),
        "max_micro_shot_duration": float(source.get("max_micro_shot_duration", 2.8)),
        "allow_punch_ins": bool(source.get("allow_punch_ins", True)),
        "allow_directional_pans": bool(source.get("allow_directional_pans", True)),
        "allow_hard_reframe_cuts": bool(source.get("allow_hard_reframe_cuts", True)),
        "transition_preference": str(source.get("transition_preference", "minimal")),
        "face_protection": bool(source.get("face_protection", True)), "batch_size": int(source.get("batch_size", 5)),
    }


def _number(value: Any, name: str) -> float:
    try: result = float(value)
    except (TypeError, ValueError): raise MotionPlanError(f"{name} must be numeric") from None
    if not math.isfinite(result): raise MotionPlanError(f"{name} must be finite")
    return result


def validate_plan(plan: dict[str, Any], timeline: dict[str, Any], settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Strictly validate and normalise a plan; no duration or timing drift is allowed."""
    if not isinstance(plan, dict) or int(plan.get("schema_version", 0)) != 1: raise MotionPlanError("schema_version 1 is required")
    duration = _number(plan.get("duration_seconds"), "duration_seconds")
    if abs(duration - _number(timeline.get("duration"), "timeline duration")) > .02: raise MotionPlanError("plan duration differs from timeline")
    expected = {str(x.get("beat_id")): x for x in timeline.get("beats", []) if str(x.get("media_type", "image")) == "image"}
    seen: set[str] = set(); shot_ids: set[str] = set(); out: list[dict[str, Any]] = []
    cfg = defaults(settings or plan.get("settings") if isinstance(plan.get("settings"), dict) else {})
    for beat in plan.get("beats", []):
        if not isinstance(beat, dict): raise MotionPlanError("beat must be object")
        key = str(beat.get("beat_id")); source = expected.get(key)
        if source is None: raise MotionPlanError(f"unknown/non-image beat {key}")
        if key in seen: raise MotionPlanError(f"duplicate beat {key}")
        seen.add(key); start = _number(beat.get("start"), "beat start"); end = _number(beat.get("end"), "beat end")
        if abs(start - float(source["start"])) > .02 or abs(end - float(source["end"])) > .02: raise MotionPlanError(f"beat {key} timing differs from timeline")
        cursor = start; shots = beat.get("micro_shots")
        if not isinstance(shots, list) or not shots or len(shots) > cfg["max_micro_shots_per_beat"]: raise MotionPlanError(f"beat {key} has invalid micro-shot count")
        normal: list[dict[str, Any]] = []
        for index, shot in enumerate(shots):
            if not isinstance(shot, dict): raise MotionPlanError("micro-shot must be object")
            sid = str(shot.get("shot_id") or "")
            if not sid or sid in shot_ids: raise MotionPlanError("missing or duplicate shot_id")
            shot_ids.add(sid); a = _number(shot.get("start"), "shot start"); b = _number(shot.get("end"), "shot end")
            if abs(a - cursor) > .025 or b <= a or b > end + .02: raise MotionPlanError(f"beat {key} has a micro-shot gap/overlap")
            if b - a < cfg["min_micro_shot_duration"] - .025: raise MotionPlanError("micro-shot too short")
            motion = str(shot.get("motion") or "")
            easing = str(shot.get("easing") or "linear")
            if motion not in MOTIONS or easing not in EASINGS: raise MotionPlanError("unknown motion or easing")
            target = shot.get("target") or {}
            if not isinstance(target, dict): raise MotionPlanError("target must be object")
            bbox = {k: _number(target.get(k), f"target.{k}") for k in ("x", "y", "w", "h")}
            if bbox["w"] <= 0 or bbox["h"] <= 0 or bbox["w"] > 1 or bbox["h"] > 1: raise MotionPlanError("invalid target bbox")
            zs, ze = _number(shot.get("zoom_start", 1.0), "zoom_start"), _number(shot.get("zoom_end", 1.0), "zoom_end")
            if not .95 <= zs <= 1.55 or not .95 <= ze <= 1.55: raise MotionPlanError("invalid zoom")
            normalized = dict(shot); normalized.update({"start": round(a, 3), "end": round(b, 3), "target": {**target, **bbox}, "zoom_start": zs, "zoom_end": ze, "easing": easing, "motion": motion})
            normal.append(normalized); cursor = b
        if abs(cursor - end) > .025: raise MotionPlanError(f"beat {key} does not cover its duration")
        transition = beat.get("transition_out") or {"type": "cut", "duration": 0}
        kind = str(transition.get("type") or "cut")
        td = _number(transition.get("duration", 0), "transition duration")
        if kind not in TRANSITIONS or (kind == "cut" and abs(td) > .001) or (kind != "cut" and not .08 <= td <= .45): raise MotionPlanError("invalid transition")
        out.append({**beat, "beat_id": beat.get("beat_id"), "start": start, "end": end, "micro_shots": normal, "transition_out": {**transition, "type": kind, "duration": round(td, 3)}})
    if set(expected) != seen: raise MotionPlanError("plan must cover every image beat")
    return {**plan, "settings": cfg, "beats": out, "duration_seconds": round(duration, 3)}


def input_fingerprint(video_dir: Path, timeline: dict[str, Any], settings: dict[str, Any]) -> str:
    digest = hashlib.sha256()
    for path in [video_dir / "SCRIPT_FINAL.md", video_dir / "VISUAL_BEATS.md", video_dir / "timing" / "WORD_TIMINGS.json", video_dir / "timeline" / "TIMELINE.json"]:
        digest.update(path.read_bytes() if path.is_file() else b"")
    for beat in timeline.get("beats", []):
        source = beat.get("image") or beat.get("source")
        if source:
            path = video_dir / str(source)
            if path.is_file(): digest.update(hashlib.sha256(path.read_bytes()).digest())
    digest.update(json.dumps(defaults(settings), sort_keys=True).encode())
    return digest.hexdigest()


def motion_qc(plan: dict[str, Any]) -> dict[str, Any]:
    shots = [s for b in plan["beats"] for s in b["micro_shots"]]; motions = [s["motion"] for s in shots]
    durations = [s["end"] - s["start"] for s in shots]; transitions = [b["transition_out"] for b in plan["beats"][:-1]]
    streak = best = 1
    for a, b in zip(motions, motions[1:]): streak = streak + 1 if a == b else 1; best = max(best, streak)
    warnings = []
    if best >= 3: warnings.append("repeated-motion streak >= 3")
    noncuts = sum(t["type"] != "cut" for t in transitions)
    if transitions and noncuts / len(transitions) > .45: warnings.append("transition density is high")
    return {"schema_version": 1, "beats": len(plan["beats"]), "micro_shots": len(shots), "visual_events_per_minute": round(len(shots) / max(plan["duration_seconds"], .01) * 60, 2), "average_micro_shot_duration": round(sum(durations) / max(1, len(durations)), 3), "minimum_micro_shot_duration": round(min(durations, default=0), 3), "maximum_micro_shot_duration": round(max(durations, default=0), 3), "hard_cut_count": sum(t["type"] == "cut" for t in transitions) + sum(s["motion"] == "reframe_cut" for s in shots), "transition_count": noncuts, "motion_type_distribution": dict(Counter(motions)), "repeated_motion_streak": best, "average_zoom_range": round(sum(abs(s["zoom_end"]-s["zoom_start"]) for s in shots)/max(1,len(shots)),3), "maximum_zoom": max((max(s["zoom_start"],s["zoom_end"]) for s in shots), default=1), "target_correction_count": sum(int(bool(s.get("target_corrected"))) for s in shots), "unsafe_target_count": sum(int(bool(s.get("target_fallback"))) for s in shots), "still_hold_percentage": round(sum(d for s,d in zip(shots,durations) if s["motion"] == "hold") / max(.01,sum(durations))*100,2), "warnings": warnings, "passed": not warnings}
