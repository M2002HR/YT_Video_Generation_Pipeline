"""Strict schemas and safety validation for content-agnostic Motion Director V2."""
from __future__ import annotations

import math
from collections import Counter
from typing import Any

from motion_schema import MotionPlanError

MOTIONS = {"hold", "push_in", "pull_out", "pan", "tilt", "pan_push", "pan_pull", "drift", "settle", "reveal_move"}
EDIT_IN = {"continue", "cut", "reframe_cut", "punch_cut_in", "punch_cut_out", "match_position_cut", "detail_cut", "establishing_cut"}
EASINGS = {"linear", "ease_in", "ease_out", "ease_in_out", "snappy", "gentle", "hold_then_move", "impact_then_settle"}
SHOT_ROLES = {"establish", "primary", "detail", "reaction", "context", "release", "hold"}
TRANSITIONS = {"cut", "dissolve", "fade", "smoothleft", "smoothright", "smoothup", "smoothdown", "wipeleft", "wiperight", "wipeup", "wipedown", "slideleft", "slideright", "slideup", "slidedown", "revealleft", "revealright", "revealup", "revealdown", "zoomin"}
IMAGE_TRANSITION_STYLES = {
    "cuts": {"cut"},
    "cut_fade": {"cut", "fade"},
    "cut_fade_dissolve": {"cut", "fade", "dissolve"},
}
SYNC_MODES = {"none", "cut_on_word_start", "movement_start_on_word", "impact_apex_on_word", "reveal_complete_on_word", "settle_on_word_end"}
REASON_CODES = {"new_fact", "contrast", "time_shift", "location_shift", "memory", "emotional_continuity", "directional_match", "reveal", "ending", "cta", "continuity"}

DEFAULTS: dict[str, Any] = {
    "enabled": True, "planning_quality": "professional", "pace": "fast", "style": "dynamic", "intensity": "normal",
    "max_micro_shots_per_beat": 3, "min_micro_shot_duration": .55, "max_micro_shot_duration": 3.2,
    "target_interval_min": .8, "target_interval_max": 1.8,
    "allow_hold": True, "allow_push": True, "allow_pull": True, "allow_pan": True, "allow_tilt": True,
    "allow_pan_push": True, "allow_pan_pull": True, "allow_drift": True, "allow_settle": True,
    "allow_reveal_move": True, "allow_punch_cuts": True, "allow_hard_reframes": True,
    "allow_match_position_cuts": True, "allow_decorative_transitions": True,
    "allow_directional_transitions": True, "allow_reveal_transitions": True,
    "transition_preference": "minimal", "max_decorative_transition_fraction": 1.0,
    "image_transition_style": "cut_fade_dissolve", "image_transition_seconds": .28,
    "transition_duration_min": .10, "transition_duration_max": .40,
    "normal_max_zoom": 1.32, "punch_max_zoom": 1.48, "max_pan_distance": .32,
    "max_pan_velocity": .42, "max_zoom_velocity": .34, "image_zoom_strength": .14,
    "enforce_image_zoom_policy": False,
    "face_protection": True, "face_padding": .18,
    "subtitle_avoidance": True, "blank_region_avoidance": True, "word_sync": True, "word_sync_tolerance_ms": 50,
    "observation_batch_size": 3, "planning_batch_size": 1, "critic_batch_size": 2, "neighbor_context": 1,
    "editorial_critic": True, "correction_attempts": 4, "debug_preview": False, "supersample": 2,
}


def settings(value: dict[str, Any] | None = None) -> dict[str, Any]:
    incoming = dict(value or {})
    # Read the public V1 panel names as aliases so old frozen launch requests resume
    # identically after the V2 upgrade.
    aliases = {
        "allow_punch_ins": "allow_punch_cuts",
        "allow_directional_pans": "allow_pan",
        "allow_hard_reframe_cuts": "allow_hard_reframes",
        "batch_size": "planning_batch_size",
    }
    for old, new in aliases.items():
        if old in incoming and new not in incoming:
            incoming[new] = incoming[old]
    result = dict(DEFAULTS)
    # Presets establish editorial behavior, not a cosmetic label. Explicit advanced
    # values still win, so a user can combine (for example) Cinematic + Very Fast.
    pace = str(incoming.get("pace", result["pace"]))
    pace_defaults = {
        "calm": {"target_interval_min": 2.0, "target_interval_max": 3.5},
        "balanced": {"target_interval_min": 1.4, "target_interval_max": 2.4},
        "fast": {"target_interval_min": .8, "target_interval_max": 1.6},
        "very_fast": {"target_interval_min": .55, "target_interval_max": 1.2},
    }
    intensity = str(incoming.get("intensity", result["intensity"]))
    intensity_defaults = {
        "subtle": {"normal_max_zoom": 1.22, "punch_max_zoom": 1.32, "max_pan_velocity": .28, "max_zoom_velocity": .22},
        "normal": {"normal_max_zoom": 1.32, "punch_max_zoom": 1.48, "max_pan_velocity": .42, "max_zoom_velocity": .34},
        "strong": {"normal_max_zoom": 1.38, "punch_max_zoom": 1.58, "max_pan_velocity": .52, "max_zoom_velocity": .46},
    }
    style = str(incoming.get("style", result["style"]))
    style_defaults = {
        "clean": {"max_decorative_transition_fraction": .10},
        "dynamic": {"max_decorative_transition_fraction": .25},
        "cinematic": {"max_decorative_transition_fraction": .32},
    }
    result.update(pace_defaults.get(pace, {})); result.update(intensity_defaults.get(intensity, {})); result.update(style_defaults.get(style, {}))
    result.update({key: value for key, value in incoming.items() if key in DEFAULTS})
    enums = {"planning_quality": {"draft", "standard", "professional"}, "pace": {"calm", "balanced", "fast", "very_fast"}, "style": {"clean", "dynamic", "cinematic"}, "intensity": {"subtle", "normal", "strong"}, "transition_preference": {"minimal", "balanced", "expressive"}, "image_transition_style": set(IMAGE_TRANSITION_STYLES)}
    for key, choices in enums.items():
        if result[key] not in choices: raise MotionPlanError(f"invalid setting {key}")
    for key, low, high in (("max_micro_shots_per_beat",1,5),("observation_batch_size",1,6),("planning_batch_size",1,6),("critic_batch_size",1,4),("correction_attempts",0,4),("neighbor_context",1,3),("word_sync_tolerance_ms",0,250),("supersample",1,4)):
        result[key] = int(result[key])
        if not low <= result[key] <= high: raise MotionPlanError(f"invalid setting {key}")
    for key in ("min_micro_shot_duration", "max_micro_shot_duration", "target_interval_min", "target_interval_max", "normal_max_zoom", "punch_max_zoom", "max_pan_distance", "max_pan_velocity", "max_zoom_velocity", "image_zoom_strength", "image_transition_seconds", "transition_duration_min", "transition_duration_max", "max_decorative_transition_fraction", "face_padding"):
        result[key] = float(result[key])
        if not math.isfinite(result[key]): raise MotionPlanError(f"invalid setting {key}")
    if result["min_micro_shot_duration"] > result["max_micro_shot_duration"]: raise MotionPlanError("minimum shot duration exceeds maximum")
    if result["target_interval_min"] > result["target_interval_max"]: raise MotionPlanError("target interval minimum exceeds maximum")
    if not 0 <= result["face_padding"] <= .5: raise MotionPlanError("face_padding outside 0..0.5")
    if not .04 <= result["image_zoom_strength"] <= .24: raise MotionPlanError("image_zoom_strength outside .04..0.24")
    if not .14 <= result["image_transition_seconds"] <= .42: raise MotionPlanError("image_transition_seconds outside .14..0.42")
    for key in [name for name, value in DEFAULTS.items() if isinstance(value, bool)]:
        result[key] = bool(result[key])
    primitive_switches = (
        "allow_hold", "allow_push", "allow_pull", "allow_pan", "allow_tilt",
        "allow_pan_push", "allow_pan_pull", "allow_drift", "allow_settle", "allow_reveal_move",
    )
    if result["enabled"] and not any(result[key] for key in primitive_switches):
        raise MotionPlanError("Dynamic Motion requires at least one enabled motion primitive; enable holds for cut-only editing")
    return result


def _num(value: Any, field: str) -> float:
    try: number = float(value)
    except (TypeError, ValueError): raise MotionPlanError(f"{field} must be numeric") from None
    if not math.isfinite(number): raise MotionPlanError(f"{field} must be finite")
    return number


def _bbox(value: Any, field: str) -> dict[str, float]:
    if not isinstance(value, dict): raise MotionPlanError(f"{field} must be an object")
    box = {key: _num(value.get(key), f"{field}.{key}") for key in ("x", "y", "w", "h")}
    if not (0 <= box["x"] <= 1 and 0 <= box["y"] <= 1 and 0 < box["w"] <= 1 and 0 < box["h"] <= 1): raise MotionPlanError(f"invalid {field}")
    return box


def validate_inventory(payload: dict[str, Any], expected: list[dict[str, Any]]) -> dict[str, Any]:
    if int(payload.get("schema_version", 0)) != 2: raise MotionPlanError("inventory schema_version 2 required")
    wanted = {str(beat["beat_id"]): beat for beat in expected if beat["media_type"] == "image"}; seen: set[str] = set(); global_ids: set[str] = set(); output=[]
    for item in payload.get("beats") or []:
        key=str(item.get("beat_id")); expected_beat=wanted.get(key)
        if expected_beat is None or key in seen: raise MotionPlanError(f"unexpected or duplicate inventory beat {key}")
        seen.add(key); artwork=_bbox(item.get("artwork_region"), "artwork_region")
        targets=[]; ids=set()
        for target in item.get("targets") or []:
            target_id=str(target.get("target_id") or "")
            if not target_id or target_id in ids or target_id in global_ids: raise MotionPlanError(f"invalid or non-unique target id in beat {key}")
            ids.add(target_id); global_ids.add(target_id); confidence=_num(target.get("confidence",0),"target confidence")
            if not 0 <= confidence <= 1: raise MotionPlanError("target confidence outside 0..1")
            targets.append({**target,"target_id":target_id,"bbox":_bbox(target.get("bbox"),"target bbox"),"confidence":confidence})
        if not targets: raise MotionPlanError(f"beat {key} has no verified visual targets")
        forbidden=[]
        for region in item.get("forbidden_regions") or []:
            forbidden.append({**region,"bbox":_bbox(region.get("bbox"),"forbidden bbox")})
        output.append({**item,"beat_id":expected_beat["beat_id"],"media_sha256":expected_beat.get("media_sha256"),"artwork_region":artwork,"targets":targets,"forbidden_regions":forbidden})
    if seen != set(wanted): raise MotionPlanError("inventory does not cover every image beat")
    return {**payload,"schema_version":2,"beats":output}


def validate_plan(payload: dict[str, Any], context: dict[str, Any], inventory: dict[str, Any], cfg: dict[str, Any], *, enforce_episode_qc: bool = True) -> dict[str, Any]:
    if int(payload.get("schema_version",0)) != 2: raise MotionPlanError("motion plan schema_version 2 required")
    expected={str(b["beat_id"]):b for b in context["beats"] if b["media_type"]=="image"}; inv={str(b["beat_id"]):b for b in inventory["beats"]}
    final_image_id = next(reversed(expected), None)
    word_map={w["word_id"]:w for w in context["words"]}; seen=set(); shots_seen=set(); output=[]
    allowed_motion=set(MOTIONS)
    allow_map={
        "hold":"allow_hold", "push_in":"allow_push", "pull_out":"allow_pull",
        "pan":"allow_pan", "tilt":"allow_tilt", "pan_push":"allow_pan_push",
        "pan_pull":"allow_pan_pull", "drift":"allow_drift", "settle":"allow_settle",
        "reveal_move":"allow_reveal_move",
    }
    for motion,key in allow_map.items():
        if not cfg.get(key,True): allowed_motion.discard(motion)
    for beat in payload.get("beats") or []:
        key=str(beat.get("beat_id")); source=expected.get(key)
        if source is None or key in seen: raise MotionPlanError(f"unexpected or duplicate plan beat {key}")
        seen.add(key); start,end=_num(beat.get("start"),"beat.start"),_num(beat.get("end"),"beat.end")
        required_motions = {"pull_out", "pan_pull"} if key == final_image_id else {"push_in", "pan_push", "reveal_move"}
        if abs(start-source["start"])>.025 or abs(end-source["end"])>.025: raise MotionPlanError(f"beat {key} timing mismatch")
        targets={t["target_id"]:t for t in inv[key]["targets"]}; shots=beat.get("micro_shots") or []
        if not 1 <= len(shots) <= cfg["max_micro_shots_per_beat"]: raise MotionPlanError(f"invalid shot count for beat {key}")
        cursor=start; normalized=[]; previous_camera_end: dict[str, Any] | None = None
        for index,shot in enumerate(shots):
            sid=str(shot.get("shot_id") or "")
            if not sid or sid in shots_seen: raise MotionPlanError("missing or duplicate shot_id")
            shots_seen.add(sid); a,b=_num(shot.get("start"),"shot.start"),_num(shot.get("end"),"shot.end"); duration=b-a
            if abs(a-cursor)>.025 or b<=a or b>end+.025: raise MotionPlanError(f"shot coverage gap/overlap in beat {key}")
            if duration < cfg["min_micro_shot_duration"]-.025 or duration > cfg["max_micro_shot_duration"]+.025: raise MotionPlanError(f"shot duration outside configured range in {sid}")
            edit=str((shot.get("edit_in") or {}).get("type") or "continue")
            if edit not in EDIT_IN: raise MotionPlanError(f"unknown edit type {edit}")
            if edit in {"reframe_cut","punch_cut_in","punch_cut_out","detail_cut"} and not cfg.get("allow_hard_reframes",True): raise MotionPlanError("hard reframe disabled")
            if edit in {"punch_cut_in","punch_cut_out"} and not cfg.get("allow_punch_cuts",True): raise MotionPlanError("punch cuts disabled")
            if edit == "match_position_cut" and not cfg.get("allow_match_position_cuts", True): raise MotionPlanError("match-position cuts disabled")
            role=str(shot.get("role") or "")
            if role not in SHOT_ROLES: raise MotionPlanError(f"unknown shot role in {sid}")
            motion=shot.get("motion") or {}; motion_type=str(motion.get("type") or "hold"); easing=str(motion.get("easing") or "linear")
            if motion_type not in allowed_motion or easing not in EASINGS: raise MotionPlanError(f"unsupported/disallowed motion in {sid}")
            if cfg.get("enforce_image_zoom_policy", False) and motion_type not in required_motions:
                direction = "pull out" if key == final_image_id else "push in"
                raise MotionPlanError(f"image zoom policy requires every shot in beat {key} to {direction}")
            delay=_num(motion.get("start_delay",0),"motion.start_delay"); end_hold=_num(motion.get("end_hold",0),"motion.end_hold")
            if delay < 0 or end_hold < 0 or delay + end_hold > duration - .08: raise MotionPlanError(f"invalid motion window in {sid}")
            reason=str(motion.get("reason") or "").strip()
            if not reason: raise MotionPlanError(f"motion reason required in {sid}")
            camera=shot.get("camera") or {}; states={}
            for state_name in ("start","end"):
                state=camera.get(state_name) or {}; target_id=str(state.get("target_id") or "")
                if target_id not in targets: raise MotionPlanError(f"unverified target {target_id!r} in {sid}")
                coverage=_num(state.get("coverage"),f"camera.{state_name}.coverage"); ax=_num(state.get("anchor_x",.5),"anchor_x"); ay=_num(state.get("anchor_y",.45),"anchor_y")
                if not .08<=coverage<=.95 or not 0<=ax<=1 or not 0<=ay<=1: raise MotionPlanError(f"unsafe camera state in {sid}")
                states[state_name]={"target_id":target_id,"coverage":coverage,"anchor_x":ax,"anchor_y":ay}
            if edit == "continue" and previous_camera_end is not None:
                if any(abs(states["start"][field] - previous_camera_end[field]) > .015 for field in ("coverage", "anchor_x", "anchor_y")) or states["start"]["target_id"] != previous_camera_end["target_id"]:
                    raise MotionPlanError(f"continue camera mismatch in {sid}")
            same_target = states["start"]["target_id"] == states["end"]["target_id"]
            if same_target and motion_type in {"push_in", "pan_push"} and states["end"]["coverage"] + .01 < states["start"]["coverage"]:
                raise MotionPlanError(f"push motion has decreasing coverage in {sid}")
            if same_target and motion_type in {"pull_out", "pan_pull"} and states["end"]["coverage"] > states["start"]["coverage"] + .01:
                raise MotionPlanError(f"pull motion has increasing coverage in {sid}")
            if motion_type == "hold" and (not same_target or any(abs(states["start"][field]-states["end"][field])>.08 for field in ("coverage","anchor_x","anchor_y"))):
                raise MotionPlanError(f"hold changes camera state in {sid}")
            sync=shot.get("sync") or {"mode":"none"}; mode=str(sync.get("mode") or "none")
            if mode not in SYNC_MODES: raise MotionPlanError(f"unknown sync mode in {sid}")
            if mode!="none":
                if not cfg.get("word_sync", True): raise MotionPlanError(f"word synchronization disabled in {sid}")
                wid=str(sync.get("word_id") or ""); word=word_map.get(wid)
                midpoint=(word["start"]+word["end"])/2 if word is not None else -1
                if word is None or not start-.025 <= midpoint < end+.025: raise MotionPlanError(f"invalid sync word in {sid}")
                sync={**sync,"word_id":wid,"word":word["text"],"authoritative_start":word["start"],"authoritative_end":word["end"]}
                if motion_type == "hold" and mode != "cut_on_word_start": raise MotionPlanError(f"motion sync on a hold is not a visual event in {sid}")
                if mode == "cut_on_word_start" and edit == "continue": raise MotionPlanError(f"cut sync requires a cut edit in {sid}")
                if mode == "cut_on_word_start" and abs(a - word["start"]) > cfg["word_sync_tolerance_ms"] / 1000:
                    raise MotionPlanError(f"cut in {sid} is not aligned to {wid}")
            else:
                # A disabled sync must not retain a misleading word_id/trigger label.
                sync={"mode":"none"}
            normalized.append({**shot,"shot_id":sid,"role":role,"start":round(a,3),"end":round(b,3),"edit_in":{"type":edit},"camera":states,"motion":{**motion,"type":motion_type,"easing":easing,"start_delay":delay,"end_hold":end_hold,"reason":reason},"sync":sync}); cursor=b; previous_camera_end=states["end"]
        if abs(cursor-end)>.025: raise MotionPlanError(f"beat {key} not fully covered")
        transition=beat.get("transition_out") or {"type":"cut","duration":0,"reason_code":"new_fact"}; kind=str(transition.get("type") or "cut"); td=_num(transition.get("duration",0),"transition duration"); reason=str(transition.get("reason_code") or "")
        if kind not in TRANSITIONS or reason not in REASON_CODES: raise MotionPlanError("invalid transition decision")
        if cfg.get("enforce_image_zoom_policy", False) and kind not in IMAGE_TRANSITION_STYLES[cfg["image_transition_style"]]:
            raise MotionPlanError("image transition policy allows only " + ", ".join(sorted(IMAGE_TRANSITION_STYLES[cfg["image_transition_style"]])))
        if kind != "cut" and not cfg.get("allow_decorative_transitions", True): raise MotionPlanError("decorative transitions disabled")
        if kind.startswith(("smooth", "wipe", "slide")) and not cfg.get("allow_directional_transitions", True): raise MotionPlanError("directional transitions disabled")
        if kind.startswith("reveal") and not cfg.get("allow_reveal_transitions", True): raise MotionPlanError("reveal transitions disabled")
        if kind=="cut" and abs(td)>.001: raise MotionPlanError("cut duration must be zero")
        if kind!="cut" and not cfg.get("enforce_image_zoom_policy", False) and not cfg["transition_duration_min"]<=td<=cfg["transition_duration_max"]: raise MotionPlanError("transition duration outside configured range")
        if cfg.get("enforce_image_zoom_policy", False) and kind != "cut" and abs(td - cfg["image_transition_seconds"]) > .005:
            raise MotionPlanError("image transition duration must match image_transition_seconds")
        ending=beat.get("ending_state") or {}
        ending_target=str(ending.get("target_id") or "")
        if ending_target not in targets: raise MotionPlanError(f"invalid ending target in beat {key}")
        ending_state={"target_id":ending_target,"coverage":_num(ending.get("coverage"),"ending coverage"),"anchor_x":_num(ending.get("anchor_x"),"ending anchor_x"),"anchor_y":_num(ending.get("anchor_y"),"ending anchor_y"),"movement_direction":str(ending.get("movement_direction") or "none")}
        if ending_state["movement_direction"] not in {"left","right","up","down","in","out","none"}: raise MotionPlanError("invalid ending movement direction")
        if ending_target != previous_camera_end["target_id"] or any(abs(ending_state[field]-previous_camera_end[field])>.015 for field in ("coverage","anchor_x","anchor_y")): raise MotionPlanError(f"ending_state mismatch in beat {key}")
        required_direction = "out" if key == final_image_id else "in"
        if cfg.get("enforce_image_zoom_policy", False) and ending_state["movement_direction"] != required_direction:
            raise MotionPlanError(f"image zoom policy requires beat {key} to end moving {required_direction}")
        output.append({**beat,"beat_id":source["beat_id"],"start":start,"end":end,"micro_shots":normalized,"ending_state":ending_state,"transition_out":{**transition,"type":kind,"duration":td,"reason_code":reason}})
    if seen!=set(expected): raise MotionPlanError("plan does not cover every image beat")
    result={**payload,"schema_version":2,"duration_seconds":context["episode"]["duration"],"settings_snapshot":cfg,"beats":output}
    qc=semantic_qc(result,cfg)
    if enforce_episode_qc and qc["errors"]: raise MotionPlanError("; ".join(qc["errors"]))
    return result


def semantic_qc(plan: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    shots=[s for b in plan["beats"] for s in b["micro_shots"]]; motions=[s["motion"]["type"] for s in shots]; edits=[s["edit_in"]["type"] for s in shots]
    durations=[s["end"]-s["start"] for s in shots]; synced=[s for s in shots if s.get("sync",{}).get("mode")!="none"]
    transitions=[b["transition_out"] for b in plan["beats"][:-1]]; noncuts=[t for t in transitions if t["type"]!="cut"]
    streak=best=1
    for left,right in zip(motions,motions[1:]): streak=streak+1 if left==right else 1; best=max(best,streak)
    warnings=[]; errors=[]
    fraction=len(noncuts)/max(1,len(transitions))
    image_duration=sum(float(beat["end"])-float(beat["start"]) for beat in plan["beats"])
    event_interval=image_duration/max(1,len(shots))
    if best>=4: errors.append("motion repetition streak >= 4")
    elif best>=3: warnings.append("motion repetition streak >= 3")
    if event_interval > cfg["target_interval_max"] * 1.35: warnings.append("visual changes are slower than the selected pace")
    if event_interval < cfg["target_interval_min"] * .65: warnings.append("visual changes may be too fragmented for the selected pace")
    hold_duration=sum(duration for shot,duration in zip(shots,durations) if shot["motion"]["type"]=="hold")
    return {"schema_version":2,"passed":not errors,"errors":errors,"warnings":warnings,"beats":len(plan["beats"]),"micro_shots":len(shots),"motion_distribution":dict(Counter(motions)),"edit_distribution":dict(Counter(edits)),"transition_distribution":dict(Counter(t["type"] for t in transitions)),"average_micro_shot_duration":round(sum(durations)/max(1,len(durations)),3),"min_micro_shot_duration":round(min(durations,default=0),3),"max_micro_shot_duration":round(max(durations,default=0),3),"average_visual_event_interval":round(event_interval,3),"still_hold_percentage":round(100*hold_duration/max(.001,sum(durations)),2),"synced_event_count":len(synced),"sync_coverage_percent":round(100*len(synced)/max(1,len(shots)),1),"repeated_motion_streak":best,"decorative_transition_fraction":round(fraction,3)}
