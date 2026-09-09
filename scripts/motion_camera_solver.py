"""Deterministic camera geometry and safety compiler for Motion Director V2.

The model selects verified subjects and editorial coverage.  This module alone decides
which source rectangle can safely be rendered, and therefore no model-authored crop or
FFmpeg expression is ever executed.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from PIL import Image

from motion_targets import detect_faces


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _box_edges(box: dict[str, float]) -> tuple[float, float, float, float]:
    return (
        box["x"] - box["w"] / 2,
        box["y"] - box["h"] / 2,
        box["x"] + box["w"] / 2,
        box["y"] + box["h"] / 2,
    )


def _iou(left: dict[str, float], right: dict[str, float]) -> float:
    l1, t1, r1, b1 = _box_edges(left)
    l2, t2, r2, b2 = _box_edges(right)
    area = max(0.0, min(r1, r2) - max(l1, l2)) * max(0.0, min(b1, b2) - max(t1, t2))
    union = left["w"] * left["h"] + right["w"] * right["h"] - area
    return area / union if union > 0 else 0.0


def image_dimensions(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        return image.size


def base_viewport(source_width: int, source_height: int, output_width: int, output_height: int) -> tuple[float, float]:
    """Largest source-normalized viewport having the output aspect ratio."""
    source_aspect = source_width / max(1, source_height)
    output_aspect = output_width / max(1, output_height)
    normalized_ratio = output_aspect / source_aspect
    if normalized_ratio <= 1.0:
        return normalized_ratio, 1.0
    return 1.0, 1.0 / normalized_ratio


def _clamp_center(cx: float, cy: float, vw: float, vh: float, artwork: dict[str, float]) -> tuple[float, float]:
    al, at, ar, ab = _box_edges(artwork)
    # When the declared artwork is smaller than the requested view, retain full-frame
    # safety rather than manufacture black pixels or an impossible crop.
    if ar - al < vw:
        al, ar = 0.0, 1.0
    if ab - at < vh:
        at, ab = 0.0, 1.0
    return _clamp(cx, al + vw / 2, ar - vw / 2), _clamp(cy, at + vh / 2, ab - vh / 2)


def resolve_face_target(target: dict[str, Any], local_faces: list[dict[str, float]], padding: float) -> tuple[dict[str, Any], list[str]]:
    """Snap a declared face to a local detection and expand it to protect the head."""
    if target.get("kind") not in {"face", "person"} or not local_faces:
        return target, []
    bbox = target["bbox"]
    nearest = min(local_faces, key=lambda face: (face["x"] - bbox["x"]) ** 2 + (face["y"] - bbox["y"]) ** 2)
    # A distant detection is probably another person; do not silently retarget.
    if math.hypot(nearest["x"] - bbox["x"], nearest["y"] - bbox["y"]) > .20:
        return target, []
    padded = dict(nearest)
    padded["w"] = min(1.0, nearest["w"] * (1 + padding * 2))
    padded["h"] = min(1.0, nearest["h"] * (1 + padding * 2.5))
    return {**target, "bbox": padded, "local_face_verified": True}, ["face_snapped_and_padded"]


def solve_camera_state(
    state: dict[str, Any], *, targets: dict[str, dict[str, Any]], artwork: dict[str, float],
    source_size: tuple[int, int], output_size: tuple[int, int], settings: dict[str, Any],
    local_faces: list[dict[str, float]] | None = None, punch: bool = False,
    subtitle_top: float | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Turn a semantic target/coverage/anchor request into a safe source viewport."""
    corrections: list[str] = []
    target = targets[state["target_id"]]
    if settings.get("face_protection", True):
        target, face_changes = resolve_face_target(target, local_faces or [], float(settings["face_padding"]))
        corrections.extend(face_changes)
    box = target["bbox"]
    bw, bh = base_viewport(*source_size, *output_size)
    coverage = _clamp(float(state["coverage"]), .08, .95)
    ratio = bw / bh
    # coverage is the desired share of the shorter screen dimension occupied by the
    # verified target.  Fit both target axes, preserving the output aspect ratio.
    wanted_h = max(box["h"] / coverage, box["w"] / max(.001, coverage * ratio))
    wanted_h = min(bh, wanted_h)
    wanted_w = wanted_h * ratio
    max_zoom = float(settings["punch_max_zoom"] if punch else settings["normal_max_zoom"])
    # Low-resolution sources receive a stricter ceiling to avoid needless upscaling.
    source_short = min(source_size)
    resolution_factor = _clamp(source_short / max(1.0, min(output_size)), .68, 1.0)
    effective_max_zoom = 1.0 + (max_zoom - 1.0) * resolution_factor
    min_w, min_h = bw / effective_max_zoom, bh / effective_max_zoom
    vw, vh = _clamp(wanted_w, min_w, bw), _clamp(wanted_h, min_h, bh)
    if abs(vw - wanted_w) > 1e-5 or abs(vh - wanted_h) > 1e-5:
        corrections.append("zoom_limited")
    anchor_x, anchor_y = float(state["anchor_x"]), float(state["anchor_y"])
    if settings.get("subtitle_avoidance", True) and subtitle_top is not None and anchor_y >= subtitle_top - .02:
        anchor_y = max(.08, subtitle_top - .06)
        corrections.append("target_anchor_lifted_above_subtitles")
    cx = box["x"] + (.5 - anchor_x) * vw
    cy = box["y"] + (.5 - anchor_y) * vh
    safe_cx, safe_cy = _clamp_center(cx, cy, vw, vh, artwork)
    if abs(safe_cx - cx) > 1e-5 or abs(safe_cy - cy) > 1e-5:
        corrections.append("viewport_clamped_to_artwork")
    # Keep the full verified subject inside the viewport where geometry permits. Face
    # targets have already been padded, which protects forehead/chin rather than merely
    # keeping the eye midpoint visible.
    left, top, right, bottom = _box_edges(box)
    subject_min_x, subject_max_x = right - vw / 2, left + vw / 2
    subject_min_y, subject_max_y = bottom - vh / 2, top + vh / 2
    if subject_min_x <= subject_max_x:
        adjusted = _clamp(safe_cx, subject_min_x, subject_max_x)
        if abs(adjusted - safe_cx) > 1e-5: corrections.append("subject_horizontal_edge_protected")
        safe_cx = adjusted
    if subject_min_y <= subject_max_y:
        adjusted = _clamp(safe_cy, subject_min_y, subject_max_y)
        if abs(adjusted - safe_cy) > 1e-5: corrections.append("subject_vertical_edge_protected")
        safe_cy = adjusted
    safe_cx, safe_cy = _clamp_center(safe_cx, safe_cy, vw, vh, artwork)
    zoom = bw / max(vw, 1e-9)
    return {
        "target_id": state["target_id"], "target_label": target.get("label", state["target_id"]),
        "center_x": round(safe_cx, 7), "center_y": round(safe_cy, 7),
        "width": round(vw, 7), "height": round(vh, 7), "zoom": round(zoom, 7),
        "anchor_x": anchor_x, "anchor_y": anchor_y, "target_bbox": box,
    }, corrections


def _limit_motion(start: dict[str, Any], end: dict[str, Any], duration: float, settings: dict[str, Any], *, punch: bool) -> tuple[dict[str, Any], list[str]]:
    corrections: list[str] = []
    max_distance = min(float(settings["max_pan_distance"]), float(settings["max_pan_velocity"]) * duration)
    dx, dy = end["center_x"] - start["center_x"], end["center_y"] - start["center_y"]
    distance = math.hypot(dx, dy)
    result = dict(end)
    if distance > max_distance > 0:
        factor = max_distance / distance
        result["center_x"] = round(start["center_x"] + dx * factor, 7)
        result["center_y"] = round(start["center_y"] + dy * factor, 7)
        corrections.append("pan_velocity_limited")
    max_zoom_delta = float(settings["max_zoom_velocity"]) * duration
    if punch:
        max_zoom_delta *= 1.65
    delta = result["zoom"] - start["zoom"]
    if abs(delta) > max_zoom_delta:
        result["zoom"] = round(start["zoom"] + math.copysign(max_zoom_delta, delta), 7)
        bw = start["width"] * start["zoom"]
        bh = start["height"] * start["zoom"]
        result["width"], result["height"] = round(bw / result["zoom"], 7), round(bh / result["zoom"], 7)
        corrections.append("zoom_velocity_limited")
    return result, corrections


def _with_zoom(state: dict[str, Any], zoom: float, artwork: dict[str, float]) -> dict[str, Any]:
    result = dict(state)
    base_width, base_height = state["width"] * state["zoom"], state["height"] * state["zoom"]
    result["zoom"] = round(max(1.0, zoom), 7)
    result["width"], result["height"] = round(base_width / result["zoom"], 7), round(base_height / result["zoom"], 7)
    result["center_x"], result["center_y"] = (round(value, 7) for value in _clamp_center(result["center_x"], result["center_y"], result["width"], result["height"], artwork))
    return result


def _enforce_primitive_shape(start: dict[str, Any], end: dict[str, Any], motion: str, settings: dict[str, Any], artwork: dict[str, float]) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    """Ensure a requested push/pull has a visible but bounded camera trajectory."""
    correction: list[str] = []
    minimum = {"subtle": .04, "normal": .065, "strong": .09}.get(str(settings.get("intensity")), .065)
    a, b = dict(start), dict(end)
    if motion in {"push_in", "pan_push", "reveal_move"} and b["zoom"] - a["zoom"] < minimum:
        possible_start = max(1.0, b["zoom"] - minimum)
        if possible_start < b["zoom"] - .01:
            a = _with_zoom(a, possible_start, artwork); correction.append("minimum_push_shape_enforced")
    elif motion in {"pull_out", "pan_pull"} and a["zoom"] - b["zoom"] < minimum:
        possible_end = max(1.0, a["zoom"] - minimum)
        if possible_end < a["zoom"] - .01:
            b = _with_zoom(b, possible_end, artwork); correction.append("minimum_pull_shape_enforced")
    return a, b, correction


def compile_camera_plan(
    plan: dict[str, Any], inventory: dict[str, Any], context: dict[str, Any], video_dir: Path, settings: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Compile and safety-correct every image shot without altering any timing."""
    inv = {str(beat["beat_id"]): beat for beat in inventory["beats"]}
    ctx = {str(beat["beat_id"]): beat for beat in context["beats"]}
    all_corrections: list[dict[str, Any]] = []
    compiled_beats: list[dict[str, Any]] = []
    output = (int(context["episode"]["width"]), int(context["episode"]["height"]))
    subtitle = context["episode"].get("subtitle_safe_region") or {}
    subtitle_top = float(subtitle.get("top", 1.0)) if subtitle.get("enabled") else None
    for beat in plan["beats"]:
        key = str(beat["beat_id"]); beat_inv = inv[key]; beat_ctx = ctx[key]
        source = video_dir / beat_ctx["media"]
        source_size = image_dimensions(source)
        faces = detect_faces(source) if settings.get("face_protection", True) else []
        targets = {target["target_id"]: target for target in beat_inv["targets"]}
        previous_end: dict[str, Any] | None = None; compiled_shots = []
        for shot in beat["micro_shots"]:
            edit_type = shot["edit_in"]["type"]
            punch = edit_type in {"punch_cut_in", "punch_cut_out"}
            start, start_changes = solve_camera_state(
                shot["camera"]["start"], targets=targets, artwork=beat_inv["artwork_region"],
                source_size=source_size, output_size=output, settings=settings, local_faces=faces, punch=punch, subtitle_top=subtitle_top,
            )
            end, end_changes = solve_camera_state(
                shot["camera"]["end"], targets=targets, artwork=beat_inv["artwork_region"],
                source_size=source_size, output_size=output, settings=settings, local_faces=faces, punch=punch, subtitle_top=subtitle_top,
            )
            if shot["motion"]["type"] == "hold" and end != start:
                end = dict(start); end_changes.append("hold_camera_locked")
            start, end, shape_changes = _enforce_primitive_shape(start, end, shot["motion"]["type"], settings, beat_inv["artwork_region"])
            if edit_type == "continue" and previous_end is not None:
                start = dict(previous_end); start_changes.append("continuous_start_matched_previous_end")
            end, velocity_changes = _limit_motion(start, end, shot["end"] - shot["start"], settings, punch=punch)
            changes = list(dict.fromkeys(start_changes + end_changes + shape_changes + velocity_changes))
            if changes:
                all_corrections.append({"beat_id": beat["beat_id"], "shot_id": shot["shot_id"], "corrections": changes})
            compiled_shots.append({**shot, "compiled_camera": {"start": start, "end": end}, "target_corrected": bool(changes), "target_corrections": changes})
            previous_end = end
        compiled_beats.append({**beat, "micro_shots": compiled_shots})
    return {**plan, "compiled": True, "beats": compiled_beats}, all_corrections


def camera_path_metrics(compiled_plan: dict[str, Any]) -> dict[str, float]:
    shots = [shot for beat in compiled_plan["beats"] for shot in beat["micro_shots"]]
    distances = []
    zoom_ranges = []
    for shot in shots:
        a, b = shot["compiled_camera"]["start"], shot["compiled_camera"]["end"]
        distances.append(math.hypot(b["center_x"] - a["center_x"], b["center_y"] - a["center_y"]))
        zoom_ranges.append(abs(b["zoom"] - a["zoom"]))
    noop = sum(distance < .003 and zoom < .008 and shot["motion"]["type"] != "hold" for shot,distance,zoom in zip(shots,distances,zoom_ranges))
    return {
        "average_camera_distance": round(sum(distances) / max(1, len(distances)), 4),
        "maximum_camera_distance": round(max(distances, default=0), 4),
        "average_zoom_range": round(sum(zoom_ranges) / max(1, len(zoom_ranges)), 4),
        "maximum_zoom": round(max((max(s["compiled_camera"]["start"]["zoom"], s["compiled_camera"]["end"]["zoom"]) for s in shots), default=1), 4),
        "non_hold_noop_count": noop,
    }
