#!/usr/bin/env python3
"""Production Motion Director V2: observe, direct, plan, critique, compile and QC."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from motion_camera_solver import camera_path_metrics, compile_camera_plan
from motion_context import build_motion_context, compact_neighbor, load_json
from motion_debug import render_debug_overlays
from motion_prompts import PROMPT_VERSION, critic_prompt, direction_prompt, observation_prompt, planning_prompt
from motion_schema import MotionPlanError
from motion_targets import face_detector_status
from motion_v2_schema import semantic_qc, settings, validate_inventory, validate_plan
from ordak_jobs import Generation, OrdakJobs, Reference


def log(message: str) -> None:
    """Write progress immediately when stdout is the control-panel log file."""
    print(message, flush=True)


def save_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def clean_json(value: str) -> dict[str, Any]:
    text = value.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.I | re.S)
    if fenced:
        text = fenced.group(1)
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise MotionPlanError("ChatGPT response must be one JSON object")
    return payload


def digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def validate_direction(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    if int(payload.get("schema_version", 0)) != 2:
        raise MotionPlanError("direction schema_version 2 required")
    if payload.get("pace") not in {"calm", "balanced", "fast", "very_fast"}:
        raise MotionPlanError("direction pace is invalid")
    duration = float(context["episode"]["duration"])
    sections = payload.get("sections") or []
    if not sections:
        raise MotionPlanError("direction requires episode sections")
    for section in sections:
        start, end, energy = float(section["start"]), float(section["end"]), float(section["energy"])
        velocity = float(section["attention_velocity"])
        if start < 0 or end <= start or end > duration + .05 or not 0 <= energy <= 1 or not 0 <= velocity <= 1:
            raise MotionPlanError("direction has an invalid section")
    words = {word["word_id"] for word in context["words"]}
    for item in payload.get("emphasis_words") or []:
        if item.get("word_id") not in words:
            raise MotionPlanError(f"direction references unknown word {item.get('word_id')}")
    return payload


def validate_critic(payload: dict[str, Any]) -> dict[str, Any]:
    if int(payload.get("schema_version", 0)) != 2 or not isinstance(payload.get("approved"), bool):
        raise MotionPlanError("critic response is invalid")
    if not isinstance(payload.get("issues", []), list) or not isinstance(payload.get("replacement_beats", []), list):
        raise MotionPlanError("critic issues/replacements must be arrays")
    # A critic rejection without a complete replacement is not actionable: it caused
    # the prior run to fail after all planning work had already completed. Reject that
    # response here so the bounded correction turn asks for the missing beat only.
    error_ids = {
        str(issue.get("beat_id"))
        for issue in payload["issues"]
        if isinstance(issue, dict) and issue.get("severity") == "error"
    }
    replacement_ids = {
        str(beat.get("beat_id"))
        for beat in payload["replacement_beats"]
        if isinstance(beat, dict)
    }
    missing = error_ids - replacement_ids
    if not payload["approved"] and missing:
        raise MotionPlanError(
            "critic rejected beat(s) " + ", ".join(sorted(missing))
            + " but omitted their complete replacement_beats"
        )
    return payload


def ask_validated_json(
    jobs: OrdakJobs, prompt: str, validator: Callable[[dict[str, Any]], dict[str, Any]], *,
    references: list[Reference] | None = None, correction_attempts: int = 1,
    label: str = "motion",
) -> tuple[dict[str, Any], list[str]]:
    """Call Ordak with bounded transport retries and bounded schema correction turns."""
    if len(prompt) > 19_500:
        raise MotionPlanError(f"Motion Director prompt exceeds safe Ordak limit: {len(prompt)} characters")
    job_ids: list[str] = []
    current = prompt
    for correction in range(correction_attempts + 1):
        result = jobs.run(
            current, provider="chatgpt", mode="chat", generation=Generation(quality="best"),
            references=references or [], attempts=2,
        )
        job_ids.append(result.job_id)
        answer = result.answer or ""
        try:
            return validator(clean_json(answer)), job_ids
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, MotionPlanError) as exc:
            if correction >= correction_attempts:
                raise MotionPlanError(f"invalid Motion Director response after bounded correction: {exc}") from exc
            log(
                f"↻ {label} correction {correction + 1}/{correction_attempts} "
                f"— {exc}"
            )
            correction_header = "\n\nCORRECTION REQUIRED: The prior JSON failed validation with: " + str(exc) + "\nReturn a complete corrected raw JSON object only. PRIOR RESPONSE:\n"
            available = max(0, 19_450 - len(prompt) - len(correction_header))
            current = prompt + correction_header + answer[:available]
    raise AssertionError("unreachable")


def receipt_value(path: Path, fingerprint: str, key: str) -> dict[str, Any] | None:
    payload = load_json(path, {})
    value = payload.get(key) if payload.get("input_fingerprint") == fingerprint else None
    return value if isinstance(value, dict) else None


def image_beats(context: dict[str, Any]) -> list[dict[str, Any]]:
    return [beat for beat in context["beats"] if beat["media_type"] == "image"]


def subset_context(context: dict[str, Any], beats: list[dict[str, Any]]) -> dict[str, Any]:
    return {**context, "beats": beats}


def target_refs(video_dir: Path, beats: list[dict[str, Any]], role_prefix: str) -> list[Reference]:
    references: list[Reference] = []
    for beat in beats:
        path = video_dir / str(beat["media"])
        if not path.is_file():
            raise FileNotFoundError(f"Motion Director image missing for beat {beat['beat_id']}: {path}")
        references.append(Reference(role=f"{role_prefix}_beat_{beat['beat_id']}", path=path))
    return references


def batch_label(stage: str, current: int, total: int, beats: list[dict[str, Any]] | None = None) -> str:
    """Human-readable live-log label for one Ordak call."""
    suffix = ""
    if beats:
        files = ", ".join(Path(str(beat["media"])).name for beat in beats)
        beat_ids = ", ".join(str(beat["beat_id"]) for beat in beats)
        suffix = f" — beats {beat_ids}; images: {files}"
    return f"motion_{stage} {current}/{total}{suffix}"


def plan_fingerprint(context: dict[str, Any], cfg: dict[str, Any]) -> str:
    relevant = {
        "prompt_version": PROMPT_VERSION, "episode": context["episode"], "words": context["words"],
        "beats": context["beats"], "settings": cfg,
    }
    return digest(relevant)


def merge_replacements(plan: dict[str, Any], replacements: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {str(item.get("beat_id")): item for item in replacements if isinstance(item, dict)}
    return {**plan, "beats": [by_id.get(str(beat["beat_id"]), beat) for beat in plan["beats"]]}


def normalize_safe_contradictions(payload: dict[str, Any], context: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    """Repair only deterministic semantic contradictions, recording every change.

    Targets, shot timing and editorial attention order are never invented here. The
    repairs merely choose the only safe representation of an already requested event.
    """
    words = {word["word_id"]: word for word in context["words"]}
    corrections: list[dict[str, Any]] = list(payload.get("normalization_corrections") or [])
    for beat in payload.get("beats") or []:
        previous_end = None
        for shot in beat.get("micro_shots") or []:
            motion = shot.get("motion") or {}
            if motion.get("type") == "hold" and motion.get("easing") == "hold":
                motion["easing"] = "linear"
                corrections.append({"shot_id": shot.get("shot_id"), "code": "hold_easing_normalized"})
            if motion.get("type") == "hold":
                camera = shot.get("camera") or {}
                start_camera = camera.get("start") or {}
                end_camera = camera.get("end") or {}
                if any(start_camera.get(key) != end_camera.get(key) for key in ("target_id", "coverage", "anchor_x", "anchor_y")):
                    # A hold cannot move or reframe. Keeping its declared start state is
                    # deterministic, preserves the chosen target, and avoids inventing
                    # a camera move that the editor did not request.
                    camera["end"] = dict(start_camera)
                    shot["camera"] = camera
                    corrections.append({"shot_id": shot.get("shot_id"), "code": "moving_hold_became_static_hold"})
            edit = shot.get("edit_in") or {}
            # The LLM occasionally proposes a reframe/punch/detail cut even when the
            # creative brief prohibits hard reframes. These edit types all represent
            # a discontinuity; a plain cut preserves the target/timing decision without
            # inventing a new camera state and is the only deterministic safe repair.
            hard_edits = {"reframe_cut", "punch_cut_in", "punch_cut_out", "detail_cut"}
            if edit.get("type") in hard_edits and not cfg.get("allow_hard_reframes", True):
                original_edit = edit["type"]
                edit["type"] = "cut"
                corrections.append({"shot_id": shot.get("shot_id"), "code": f"{original_edit}_became_cut_hard_reframes_disabled"})
            elif edit.get("type") in {"punch_cut_in", "punch_cut_out"} and not cfg.get("allow_punch_cuts", True):
                original_edit = edit["type"]
                edit["type"] = "cut"
                corrections.append({"shot_id": shot.get("shot_id"), "code": f"{original_edit}_became_cut_punch_cuts_disabled"})
            start_state = (shot.get("camera") or {}).get("start") or {}
            def differs(key: str) -> bool:
                if key == "target_id": return str(start_state.get(key)) != str(previous_end.get(key))
                try: return abs(float(start_state.get(key)) - float(previous_end.get(key))) > .001
                except (TypeError, ValueError): return True
            if edit.get("type") == "continue" and previous_end is not None and any(differs(key) for key in ("target_id", "coverage", "anchor_x", "anchor_y")):
                edit["type"] = "reframe_cut" if cfg.get("allow_hard_reframes", True) else "cut"
                corrections.append({"shot_id": shot.get("shot_id"), "code": "impossible_continue_became_hard_cut"})
            sync = shot.get("sync") or {}
            if motion.get("type") == "hold" and sync.get("mode") not in {None, "none", "cut_on_word_start"}:
                shot["sync"] = {"mode": "none"}
                sync = shot["sync"]
                corrections.append({"shot_id": shot.get("shot_id"), "code": "nonvisual_hold_sync_removed"})
            if sync.get("mode") == "cut_on_word_start":
                word = words.get(str(sync.get("word_id") or ""))
                if edit.get("type") == "continue":
                    edit["type"] = "reframe_cut" if cfg.get("allow_hard_reframes", True) else "cut"
                    corrections.append({"shot_id": shot.get("shot_id"), "code": "word_cut_requires_cut_edit"})
                if word is not None and abs(float(shot.get("start", 0)) - float(word["start"])) > cfg["word_sync_tolerance_ms"] / 1000:
                    if motion.get("type") != "hold" and float(shot.get("start", 0)) <= float(word["start"]) < float(shot.get("end", 0)):
                        sync["mode"] = "movement_start_on_word"
                        corrections.append({"shot_id": shot.get("shot_id"), "code": "impossible_cut_became_word_synced_move"})
                    else:
                        shot["sync"] = {"mode": "none"}
                        corrections.append({"shot_id": shot.get("shot_id"), "code": "impossible_cut_sync_removed"})
            previous_end = (shot.get("camera") or {}).get("end") or previous_end
    if corrections:
        payload["normalization_corrections"] = corrections
    return payload


def finalize_plan(
    *, candidate: dict[str, Any], inventory: dict[str, Any], context: dict[str, Any],
    video_dir: Path, cfg: dict[str, Any], fingerprint: str, critic: dict[str, Any],
) -> dict[str, Any]:
    """Deterministically compile, measure and persist a strictly validated plan."""
    motion_dir = video_dir / "motion"
    compiled, corrections = compile_camera_plan(candidate, inventory, context, video_dir, cfg)
    compiled.update({"input_fingerprint": fingerprint, "compiler_version": 2})
    qc = semantic_qc(candidate, cfg); qc.update(camera_path_metrics(compiled))
    speech_end = max((float(word["end"]) for word in context["words"]), default=candidate["duration_seconds"])
    visual_tail = max(0.0, float(candidate["duration_seconds"]) - speech_end)
    last_shot = compiled["beats"][-1]["micro_shots"][-1] if compiled.get("beats") else None
    tail_has_motion = bool(last_shot and (last_shot["motion"]["type"] != "hold" or abs(last_shot["compiled_camera"]["end"]["zoom"] - last_shot["compiled_camera"]["start"]["zoom"]) > .01))
    if visual_tail > 1.0 and not tail_has_motion: qc["warnings"].append("dead visual tail after speech")
    unresolved_critic_errors = [issue for issue in critic.get("issues", []) if issue.get("severity") == "error" and str(issue.get("beat_id")) not in {str(item.get("beat_id")) for item in critic.get("replacement_beats", [])}]
    qc.update({
        "input_fingerprint": fingerprint, "target_correction_count": len(corrections), "unsafe_target_count": 0,
        "target_corrections": corrections, "visual_events_per_minute": round(qc["micro_shots"] / max(.01, candidate["duration_seconds"]) * 60, 2),
        "hard_cut_count": sum(shot["edit_in"]["type"] != "continue" for beat in candidate["beats"] for shot in beat["micro_shots"][1:]) + sum(beat["transition_out"]["type"] == "cut" for beat in candidate["beats"][:-1]),
        "transition_count": sum(beat["transition_out"]["type"] != "cut" for beat in candidate["beats"][:-1]),
        "face_detector": face_detector_status(), "critic_approved": not unresolved_critic_errors,
        "critic_original_approved": critic.get("approved", True), "critic_issues": critic.get("issues", []),
        "speech_end": round(speech_end, 3), "visual_tail_seconds": round(visual_tail, 3), "tail_has_meaningful_motion": tail_has_motion,
    })
    save_json(motion_dir / "MOTION_PLAN.json", candidate); save_json(motion_dir / "COMPILED_MOTION_PLAN.json", compiled); save_json(motion_dir / "MOTION_QC.json", qc)
    if cfg["debug_preview"]:
        debug_outputs = render_debug_overlays(video_dir, context, inventory, compiled)
        print(f"Motion debug overlays: {len(debug_outputs)} files in {motion_dir / 'debug'}")
    print(f"Motion Director complete: {qc['beats']} image beats, {qc['micro_shots']} micro-shots, {qc['hard_cut_count']} hard cuts/reframes, {qc['transition_count']} transitions, {qc['visual_events_per_minute']} events/min, QC {'PASS' if qc['passed'] else 'WARN'}")
    return qc


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a verified episode-aware Motion Director plan.")
    parser.add_argument("video_dir", type=Path)
    parser.add_argument("--settings", type=Path, help="Launch/creative brief containing _motion settings")
    parser.add_argument("--force", action="store_true", help="Ignore reusable completed artifacts")
    parser.add_argument("--recompile-existing", action="store_true", help="Explicitly revalidate and compile an existing V2 semantic plan without calling Ordak")
    args = parser.parse_args()

    video_dir = args.video_dir.expanduser().resolve()
    timeline = load_json(video_dir / "timeline" / "TIMELINE.json", {})
    if not timeline:
        raise FileNotFoundError(f"Timeline missing: {video_dir / 'timeline/TIMELINE.json'}")
    raw = load_json(args.settings, {}) if args.settings else load_json(video_dir / "launch" / "CREATIVE_BRIEF.json", {})
    if isinstance(raw, dict) and "_motion" in raw:
        motion_values = raw.get("_motion") or {}
    elif isinstance(raw, dict) and any(key in raw for key in ("enabled", "pace", "style", "max_micro_shots_per_beat")):
        motion_values = raw
    else:
        motion_values = {}
    cfg = settings(motion_values)
    if not cfg["enabled"]:
        print("Motion Director disabled: legacy motion remains authoritative.")
        return

    context = build_motion_context(video_dir, timeline, cfg)
    beats = image_beats(context)
    fingerprint = plan_fingerprint(context, cfg)
    motion_dir = video_dir / "motion"
    receipts = motion_dir / "receipts"
    plan_path = motion_dir / "MOTION_PLAN.json"
    compiled_path = motion_dir / "COMPILED_MOTION_PLAN.json"
    if not args.force and not args.recompile_existing and plan_path.is_file() and compiled_path.is_file():
        try:
            inventory = validate_inventory(load_json(motion_dir / "VISUAL_INVENTORY.json", {}), beats)
            existing = load_json(plan_path, {})
            if existing.get("input_fingerprint") == fingerprint:
                validate_plan(existing, context, inventory, cfg)
                compiled = load_json(compiled_path, {})
                if compiled.get("input_fingerprint") == fingerprint and compiled.get("compiled") is True:
                    print(f"Motion Director reused: {plan_path}")
                    return
        except (OSError, KeyError, TypeError, ValueError, MotionPlanError):
            pass

    if args.recompile_existing:
        if not plan_path.is_file(): raise FileNotFoundError("--recompile-existing requires motion/MOTION_PLAN.json")
        inventory = validate_inventory(load_json(motion_dir / "VISUAL_INVENTORY.json", {}), beats)
        candidate = normalize_safe_contradictions(load_json(plan_path, {}), context, cfg)
        candidate.update({"settings_snapshot": cfg, "input_fingerprint": fingerprint, "prompt_version": PROMPT_VERSION, "recompiled_at": datetime.now(timezone.utc).isoformat()})
        candidate = validate_plan(candidate, context, inventory, cfg)
        prior_qc = load_json(motion_dir / "MOTION_QC.json", {})
        prior_issues = prior_qc.get("critic_issues", [])
        critic = {"approved": prior_qc.get("critic_original_approved", prior_qc.get("critic_approved", True)), "issues": prior_issues, "replacement_beats": [{"beat_id": issue.get("beat_id")} for issue in prior_issues if issue.get("severity") == "error"]}
        finalize_plan(candidate=candidate, inventory=inventory, context=context, video_dir=video_dir, cfg=cfg, fingerprint=fingerprint, critic=critic)
        return

    receipts.mkdir(parents=True, exist_ok=True)
    inventory_parts: list[dict[str, Any]] = []
    with OrdakJobs() as jobs:
        jobs.require_ready(["chatgpt"])

        # Pass 1: visual evidence, isolated from editorial decisions to prevent narrated
        # concepts from becoming hallucinated focal targets.
        observation_total = (len(beats) + cfg["observation_batch_size"] - 1) // cfg["observation_batch_size"]
        for offset in range(0, len(beats), cfg["observation_batch_size"]):
            batch = beats[offset:offset + cfg["observation_batch_size"]]
            batch_number = offset // cfg["observation_batch_size"] + 1
            label = batch_label("observation", batch_number, observation_total, batch)
            batch_fp = digest({"stage": "observation", "prompt": PROMPT_VERSION, "beats": batch})
            receipt = receipts / f"observation_{batch_number:03d}.json"
            response = None if args.force else receipt_value(receipt, batch_fp, "response")
            validator = lambda value, current=batch: validate_inventory(value, current)
            if response is not None:
                try: response = validator(response)
                except (KeyError, TypeError, ValueError, MotionPlanError): response = None
            if response is None:
                log(f"▶ {label}")
                response, job_ids = ask_validated_json(
                    jobs, observation_prompt(batch), validator,
                    references=target_refs(video_dir, batch, "motion_observation"),
                    correction_attempts=cfg["correction_attempts"], label=label,
                )
                save_json(receipt, {"schema_version": 2, "stage": "observation", "prompt_version": PROMPT_VERSION, "input_fingerprint": batch_fp, "job_ids": job_ids, "response": response})
                log(f"✔ {label}")
            else:
                log(f"↻ {label} reused")
            inventory_parts.extend(response["beats"])
        inventory = validate_inventory({"schema_version": 2, "beats": inventory_parts}, beats)
        inventory.update({"input_fingerprint": fingerprint, "prompt_version": PROMPT_VERSION})
        save_json(motion_dir / "VISUAL_INVENTORY.json", inventory)

        # Pass 2: one coherent episode-level rhythm and energy direction.
        direction_text = direction_prompt(context["episode"], context["beats"], inventory)
        direction_fp = digest({"stage": "direction", "prompt_text": direction_text})
        direction_receipt = receipts / "direction.json"
        direction = None if args.force else receipt_value(direction_receipt, direction_fp, "response")
        if direction is not None:
            try: direction = validate_direction(direction, context)
            except (KeyError, TypeError, ValueError, MotionPlanError): direction = None
        if direction is None:
            direction_label = "motion_direction 1/1"
            log(f"▶ {direction_label}")
            direction, job_ids = ask_validated_json(
                jobs, direction_text,
                lambda value: validate_direction(value, context), correction_attempts=cfg["correction_attempts"], label=direction_label,
            )
            save_json(direction_receipt, {"schema_version": 2, "stage": "direction", "prompt_version": PROMPT_VERSION, "input_fingerprint": direction_fp, "job_ids": job_ids, "response": direction})
            log(f"✔ {direction_label}")
        else:
            log("↻ motion_direction 1/1 reused")
        save_json(motion_dir / "MOTION_DIRECTION.json", {"schema_version": 2, "prompt_version": PROMPT_VERSION, "input_fingerprint": fingerprint, "direction": direction})

        # Pass 3: batch shot direction with actual images, exact word IDs, neighbor context
        # and the prior camera state. Fingerprints cascade so resume starts at first change.
        planned: list[dict[str, Any]] = []
        previous_state: dict[str, Any] | None = None
        inv_by_id = {str(item["beat_id"]): item for item in inventory["beats"]}
        all_context = context["beats"]
        index_by_id = {str(item["beat_id"]): index for index, item in enumerate(all_context)}
        planning_total = (len(beats) + cfg["planning_batch_size"] - 1) // cfg["planning_batch_size"]
        for offset in range(0, len(beats), cfg["planning_batch_size"]):
            batch = beats[offset:offset + cfg["planning_batch_size"]]
            batch_number = offset // cfg["planning_batch_size"] + 1
            label = batch_label("planning", batch_number, planning_total, batch)
            first_index = index_by_id[str(batch[0]["beat_id"])]
            last_index = index_by_id[str(batch[-1]["beat_id"])]
            radius = int(cfg["neighbor_context"])
            previous_neighbor = [
                compact_neighbor(item) for item in all_context[max(0, first_index - radius):first_index]
            ]
            next_neighbor = [
                compact_neighbor(item) for item in all_context[last_index + 1:last_index + 1 + radius]
            ]
            batch_inventory = [inv_by_id[str(item["beat_id"])] for item in batch]
            prompt = planning_prompt(
                episode=context["episode"], batch=batch, inventory=batch_inventory, direction=direction,
                previous_state=previous_state, previous_neighbor=previous_neighbor, next_neighbor=next_neighbor,
            )
            batch_fp = digest({"stage": "planning", "prompt": PROMPT_VERSION, "batch": batch, "inventory": batch_inventory, "direction": direction, "previous_state": previous_state, "neighbors": [previous_neighbor, next_neighbor]})
            receipt = receipts / f"planning_{batch_number:03d}.json"
            response = None if args.force else receipt_value(receipt, batch_fp, "response")
            local_context = subset_context(context, batch)
            local_inventory = {"schema_version": 2, "beats": batch_inventory}
            validator = lambda value, lc=local_context, li=local_inventory: validate_plan(normalize_safe_contradictions(value, lc, cfg), lc, li, cfg, enforce_episode_qc=False)
            if response is not None:
                try: response = validator(response)
                except (KeyError, TypeError, ValueError, MotionPlanError): response = None
            if response is None:
                log(f"▶ {label}")
                response, job_ids = ask_validated_json(
                    jobs, prompt, validator, references=target_refs(video_dir, batch, "motion_planning"),
                    correction_attempts=cfg["correction_attempts"], label=label,
                )
                save_json(receipt, {"schema_version": 2, "stage": "planning", "prompt_version": PROMPT_VERSION, "input_fingerprint": batch_fp, "job_ids": job_ids, "response": response})
                log(f"✔ {label}")
            else:
                log(f"↻ {label} reused")
            planned.extend(response["beats"])
            previous_state = response["beats"][-1].get("ending_state") if response["beats"] else previous_state

        candidate = {
            "schema_version": 2, "duration_seconds": context["episode"]["duration"],
            "settings_snapshot": cfg, "global_direction": direction, "beats": planned,
            "input_fingerprint": fingerprint, "prompt_version": PROMPT_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        candidate = validate_plan(candidate, context, inventory, cfg, enforce_episode_qc=False)

        # Pass 4: senior-editor audit. Replacements are complete semantic beats and are
        # sent through the same validator; critic output can never bypass local safety.
        critic: dict[str, Any] = {"schema_version": 2, "approved": True, "issues": [], "replacement_beats": []}
        if cfg["editorial_critic"]:
            critic_parts: list[dict[str, Any]] = []
            critic_total = (len(candidate["beats"]) + cfg["critic_batch_size"] - 1) // cfg["critic_batch_size"]
            for offset in range(0, len(candidate["beats"]), cfg["critic_batch_size"]):
                segment_beats = candidate["beats"][offset:offset + cfg["critic_batch_size"]]
                batch_number = offset // cfg["critic_batch_size"] + 1
                label = f"motion_critic {batch_number}/{critic_total} — beats " + ", ".join(str(beat["beat_id"]) for beat in segment_beats)
                segment_ids = {str(beat["beat_id"]) for beat in segment_beats}
                segment_plan = {"schema_version": 2, "duration_seconds": candidate["duration_seconds"], "beats": segment_beats}
                segment_inventory = {"schema_version": 2, "beats": [beat for beat in inventory["beats"] if str(beat["beat_id"]) in segment_ids]}
                prompt = critic_prompt(segment_plan, segment_inventory, direction, cfg)
                critic_fp = digest({"stage": "critic", "prompt": PROMPT_VERSION, "plan": segment_plan, "inventory": segment_inventory, "direction": direction})
                critic_receipt = receipts / f"critic_{batch_number:03d}.json"
                cached = None if args.force else receipt_value(critic_receipt, critic_fp, "response")
                if cached is not None:
                    try: part = validate_critic(cached)
                    except (KeyError, TypeError, ValueError, MotionPlanError): cached = None
                if cached is None:
                    log(f"▶ {label}")
                    part, job_ids = ask_validated_json(
                        jobs, prompt, validate_critic, correction_attempts=cfg["correction_attempts"], label=label,
                    )
                    save_json(critic_receipt, {"schema_version": 2, "stage": "critic", "prompt_version": PROMPT_VERSION, "input_fingerprint": critic_fp, "job_ids": job_ids, "response": part})
                    log(f"✔ {label}")
                else:
                    log(f"↻ {label} reused")
                critic_parts.append(part)
            critic = {
                "schema_version": 2,
                "approved": all(part["approved"] for part in critic_parts),
                "issues": [issue for part in critic_parts for issue in part["issues"]],
                "replacement_beats": [beat for part in critic_parts for beat in part["replacement_beats"]],
            }
            replacement_ids = {str(item.get("beat_id")) for item in critic["replacement_beats"]}
            if critic["replacement_beats"]:
                candidate = normalize_safe_contradictions(
                    merge_replacements(candidate, critic["replacement_beats"]), context, cfg
                )
                candidate = validate_plan(candidate, context, inventory, cfg, enforce_episode_qc=False)
            remaining_errors = [item for item in critic["issues"] if item.get("severity") == "error" and str(item.get("beat_id")) not in replacement_ids]
            if not critic["approved"] and remaining_errors:
                raise MotionPlanError("editorial critic rejected plan: " + "; ".join(str(item.get("message")) for item in remaining_errors))
        candidate = validate_plan(candidate, context, inventory, cfg)

    finalize_plan(candidate=candidate, inventory=inventory, context=context, video_dir=video_dir, cfg=cfg, fingerprint=fingerprint, critic=critic)


if __name__ == "__main__":
    main()
