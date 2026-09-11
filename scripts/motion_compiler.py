"""Local camera compiler for validated semantic motion plans.

All FFmpeg expressions originate here.  The model only supplies constrained semantic
tokens and normalised geometry, which is clamped before it reaches this module.
"""
from __future__ import annotations

import math
from typing import Any


def solve_target(target: dict[str, Any], *, subtitle_top: float = .78) -> tuple[dict[str, float], list[str]]:
    """Return safe normalised centre bbox.  Preserve a readable focal point over bad input."""
    changes: list[str] = []
    x, y, w, h = (float(target.get(k, v)) for k, v in (("x", .5), ("y", .45), ("w", .35), ("h", .35)))
    w, h = min(.95, max(.06, w)), min(.95, max(.06, h))
    nx, ny = min(1-w/2, max(w/2, x)), min(1-h/2, max(h/2, y))
    if (nx, ny, w, h) != (x, y, float(target.get("w", .35)), float(target.get("h", .35))): changes.append("clamped_bbox")
    # A target fully behind lower captions is moved to the nearest readable position.
    if ny - h / 2 > subtitle_top:
        ny = subtitle_top - h / 2; changes.append("subtitle_safe_shift")
    return {"x": nx, "y": ny, "w": w, "h": h}, changes


def _ease(t: str, p: str) -> str:
    if t == "linear": return p
    if t == "ease_in": return f"pow({p},2)"
    if t == "ease_out": return f"1-pow(1-{p},2)"
    if t == "ease_in_out": return f"if(lt({p},.5),2*pow({p},2),1-pow(-2*{p}+2,2)/2)"
    if t == "snappy": return f"1-pow(1-{p},3)"
    if t == "gentle": return f"({p}*{p}*(3-2*{p}))"
    return f"if(lt({p},.35),0,({p}-.35)/.65)"  # hold_then_move


def _ease_v2(kind: str, progress: str) -> str:
    """Semantic easing vocabulary compiled into a bounded 0..1 expression."""
    if kind == "impact_then_settle":
        # A quick arrival followed by a tiny deterministic settle; endpoints remain exact.
        return f"if(lt({progress},.72),1.035*(1-pow(1-({progress})/.72,3)),1+.035*(1-({progress})/.72))"
    return _ease(kind, progress)


def _motion_window(shot: dict[str, Any], duration: float) -> tuple[float, float]:
    """Resolve word-aware movement timing inside a shot without changing its duration."""
    motion = shot.get("motion") or {}
    delay = max(0.0, float(motion.get("start_delay") or 0.0))
    end_hold = max(0.0, float(motion.get("end_hold") or 0.0))
    sync = shot.get("sync") or {}
    mode = str(sync.get("mode") or "none")
    shot_start = float(shot["start"])
    if mode == "movement_start_on_word":
        delay = max(delay, float(sync["authoritative_start"]) - shot_start)
    elif mode in {"reveal_complete_on_word", "impact_apex_on_word"}:
        end_hold = max(end_hold, duration - (float(sync["authoritative_start"]) - shot_start))
    elif mode == "settle_on_word_end":
        end_hold = max(end_hold, duration - (float(sync["authoritative_end"]) - shot_start))
    delay = min(duration * .8, delay)
    end_hold = min(duration * .8, end_hold)
    if delay + end_hold > duration - .08:
        scale = max(0.0, (duration - .08) / max(.001, delay + end_hold))
        delay, end_hold = delay * scale, end_hold * scale
    return delay, end_hold


def dynamic_motion_filter_v2(
    *, input_index: int | str, label: str, width: int, height: int, fps: int,
    duration: float, motion_duration: float, shot: dict[str, Any], supersample: int,
) -> str:
    """Compile a solved V2 camera path; only local expressions reach FFmpeg."""
    camera = shot["compiled_camera"]
    start, end = camera["start"], camera["end"]
    frames = max(2, math.ceil(duration * fps)); moving_frames = max(2, math.ceil(motion_duration * fps))
    delay, end_hold = _motion_window(shot, motion_duration)
    delay_frames = round(delay * fps); active_frames = max(2, moving_frames - delay_frames - round(end_hold * fps))
    raw = f"clip((on-{delay_frames})/{max(1, active_frames-1)},0,1)"
    easing = str((shot.get("motion") or {}).get("easing") or "linear")
    progress = _ease_v2(easing, raw)
    kind = str((shot.get("motion") or {}).get("type") or "hold")
    if kind == "hold":
        progress = "0"
    ss = max(1, min(4, int(supersample))); work_width, work_height = width * ss, height * ss
    start_zoom, end_zoom = float(start["zoom"]), float(end["zoom"])
    zoom = f"{start_zoom:.7f}+({end_zoom-start_zoom:.7f})*({progress})"
    cx = f"{float(start['center_x']):.7f}+({float(end['center_x'])-float(start['center_x']):.7f})*({progress})"
    cy = f"{float(start['center_y']):.7f}+({float(end['center_y'])-float(start['center_y']):.7f})*({progress})"
    x = f"clip(({cx})*iw-iw/zoom/2,0,iw-iw/zoom)"
    y = f"clip(({cy})*ih-ih/zoom/2,0,ih-ih/zoom)"
    # The cover canvas is a deliberate renderer contract shared with legacy mode.  The
    # camera solver has already accounted for source/output aspect and safe zoom limits.
    input_pad = f"[{input_index}:v]" if isinstance(input_index, int) else f"[{input_index}]"
    return (
        f"{input_pad}scale={work_width}:{work_height}:force_original_aspect_ratio=increase,"
        f"crop={work_width}:{work_height},setsar=1,"
        f"zoompan=z='{zoom}':x='{x}':y='{y}':d=1:s={work_width}x{work_height}:fps={fps},"
        f"scale={width}:{height}:flags=lanczos,trim=duration={duration:.6f},"
        f"setpts=PTS-STARTPTS,settb=AVTB[{label}]"
    )


def dynamic_motion_filter(*, input_index: int, label: str, width: int, height: int, fps: int, duration: float, shot: dict[str, Any], supersample: int, subtitle_top: float = .78) -> tuple[str, list[str]]:
    """Compile one sub-shot. zoompan gets a smooth target-aware crop with no black edges."""
    target, corrections = solve_target(shot.get("target") or {}, subtitle_top=subtitle_top)
    frames, ss = max(2, math.ceil(duration * fps)), max(1, min(4, int(supersample)))
    ww, hh = width * ss, height * ss; p = f"min(on/{frames-1},1)"; e = _ease(str(shot.get("easing", "linear")), p)
    zs, ze = float(shot.get("zoom_start", 1)), float(shot.get("zoom_end", 1))
    motion = str(shot.get("motion", "hold"))
    if motion in {"hold", "establish"}: ze = zs
    if motion in {"pull_out", "pan_pull", "punch_out"}: zs, ze = max(zs, ze), min(zs, ze)
    if motion == "punch_in": ze = max(ze, min(1.48, zs + .12))
    zoom = f"{zs:.6f}+({ze-zs:.6f})*({e})"
    # target-aware crop; clip guarantees source crop remains entirely inside canvas.
    tx, ty = target["x"], target["y"]
    # A pan is an actual attention transfer, not a centred zoom with a different
    # name.  In V1 the plan supplies the destination; the deterministic compiler
    # starts a short, clamped distance away so every result remains reproducible.
    if motion in {"pan", "pan_push", "pan_pull", "drift"}:
        sx = min(.94, max(.06, tx + (-.12 if tx >= .5 else .12)))
        sy = min(.94, max(.06, ty + (-.06 if ty >= .5 else .06)))
        cx, cy = f"{sx:.6f}+({tx-sx:.6f})*({e})", f"{sy:.6f}+({ty-sy:.6f})*({e})"
    else:
        cx, cy = f"{tx:.6f}", f"{ty:.6f}"
    x = f"clip(({cx})*iw-iw/zoom/2,0,iw-iw/zoom)"
    y = f"clip(({cy})*ih-ih/zoom/2,0,ih-ih/zoom)"
    graph = (f"[{input_index}:v]scale={ww}:{hh}:force_original_aspect_ratio=increase,crop={ww}:{hh},setsar=1,"
             f"zoompan=z='{zoom}':x='{x}':y='{y}':d=1:s={ww}x{hh}:fps={fps},"
             f"scale={width}:{height}:flags=lanczos,trim=duration={duration:.6f},setpts=PTS-STARTPTS,settb=AVTB[{label}]")
    return graph, corrections


def plan_render_units(plan: dict[str, Any], timeline_beats: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Expand image beats while keeping timeline boundary decisions authoritative.

    The Motion Director owns camera movement inside an image.  Studio/Revise owns the
    transition between original media beats, so an LLM camera plan may never replace a
    manual or default timeline transition.
    """
    by_id = {str(b["beat_id"]): b for b in plan.get("beats", [])}; units: list[dict[str, Any]] = []
    for beat in timeline_beats:
        planned = by_id.get(str(beat.get("beat_id")))
        if planned and str(beat.get("media_type", "image")) == "image":
            for i, shot in enumerate(planned["micro_shots"]):
                units.append({**beat, "duration": round(shot["end"]-shot["start"], 6), "motion_shot": shot,
                              "transition_in": "cut" if i else beat.get("transition_in", "cut"), "transition_seconds": 0.0 if i else float(beat.get("transition_seconds", 0)),
                              "plan_transition_out": planned["transition_out"] if i == len(planned["micro_shots"])-1 else {"type":"cut","duration":0}})
        else:
            units.append({**beat, "plan_transition_out": {"type": beat.get("transition_in", "cut"), "duration": float(beat.get("transition_seconds", 0))}})
    # Preserve the incoming boundary on each original beat's first unit.  Internal
    # micro-shot edits are cuts; no motion-plan transition leaks across media beats.
    for i in range(1, len(units)):
        is_first_unit = str(units[i].get("beat_id")) != str(units[i - 1].get("beat_id"))
        t = ({"type": units[i].get("transition_in", "cut"), "duration": float(units[i].get("transition_seconds", 0))}
             if is_first_unit else {"type": "cut", "duration": 0.0})
        units[i]["transition_in"] = t.get("type", "cut"); units[i]["transition_seconds"] = float(t.get("duration", 0))
    if units: units[0]["transition_in"], units[0]["transition_seconds"] = "cut", 0.0
    return units


def plan_render_units_v2(plan: dict[str, Any], timeline_beats: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Expand compiled V2 image beats without replacing timeline transitions."""
    planned_by_id = {str(beat["beat_id"]): beat for beat in plan.get("beats") or []}
    units: list[dict[str, Any]] = []
    for beat in timeline_beats:
        planned = planned_by_id.get(str(beat.get("beat_id")))
        if planned and str(beat.get("media_type") or "image") == "image":
            for index, shot in enumerate(planned["micro_shots"]):
                internal_edit = shot["edit_in"]["type"]
                units.append({
                    **beat,
                    "duration": round(float(shot["end"]) - float(shot["start"]), 6),
                    "motion_shot_v2": shot,
                    "transition_in": beat.get("transition_in", "cut") if index == 0 else "cut",
                    "transition_seconds": float(beat.get("transition_seconds") or 0) if index == 0 else 0.0,
                    "internal_edit_in": internal_edit,
                    "plan_transition_out": planned["transition_out"] if index == len(planned["micro_shots"]) - 1 else {"type": "cut", "duration": 0.0},
                })
        else:
            units.append({
                **beat,
                "plan_transition_out": {"type": beat.get("transition_in", "cut"), "duration": float(beat.get("transition_seconds") or 0.0)},
            })
    # The timeline owns original-media boundaries. Internal micro-shot edits are always
    # real zero-overlap cuts; a continue is a visually continuous camera path across it.
    for index in range(1, len(units)):
        is_first_unit = str(units[index].get("beat_id")) != str(units[index - 1].get("beat_id"))
        decision = ({"type": units[index].get("transition_in", "cut"), "duration": float(units[index].get("transition_seconds") or 0)}
                    if is_first_unit else {"type": "cut", "duration": 0.0})
        units[index]["transition_in"] = str(decision.get("type") or "cut")
        units[index]["transition_seconds"] = float(decision.get("duration") or 0.0)
    if units:
        units[0]["transition_in"], units[0]["transition_seconds"] = "cut", 0.0
    return units
