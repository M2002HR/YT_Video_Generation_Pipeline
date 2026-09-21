#!/usr/bin/env python3
"""Production Motion Director V2: observe, direct, plan, critique, compile and QC."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
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
from ordak_jobs import Generation, OrdakJobError, OrdakJobs, Reference
from pipeline_notifier import PipelineNotifier


def log(message: str) -> None:
    """Write progress immediately when stdout is the control-panel log file."""
    print(message, flush=True)


def save_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


class MotionProgress:
    """Durable batch checkpoints plus one editable Telegram progress message.

    Receipts remain the authority for reuse; this companion state makes that reuse
    visible and leaves an exact restart point even if the parent process is interrupted.
    """

    def __init__(self, video_dir: Path, fingerprint: str) -> None:
        self.video_dir = video_dir
        self.fingerprint = fingerprint
        self.path = video_dir / "pipeline" / "MOTION_DIRECTOR_RUNTIME_STATE.json"
        try:
            previous = load_json(self.path, {})
        except OSError:
            previous = {}
        same_run = previous.get("input_fingerprint") == fingerprint
        self.state: dict[str, Any] = {
            "schema_version": 1,
            "video": video_dir.name,
            "input_fingerprint": fingerprint,
            "status": "RUNNING",
            "started_at": previous.get("started_at") if same_run else datetime.now(timezone.utc).isoformat(),
            "resume_count": int(previous.get("resume_count", 0)) + 1 if same_run else 0,
            "checkpoints": dict(previous.get("checkpoints") or {}) if same_run else {},
        }
        topic = ""
        try:
            topic = str(load_json(video_dir / "launch" / "LAUNCH_REQUEST.json", {}).get("topic") or "")
        except OSError:
            pass
        self.notifier = PipelineNotifier(
            video_id=video_dir.name.split("_", 1)[0],
            topic=topic,
            state_path=video_dir / "pipeline" / "TELEGRAM_NOTIFICATION_STATE.json",
            # Each process resume gets its own visible Telegram entry.  Reusing
            # the old generic "run" message made a fresh recovery look silent
            # in the chat even though its checkpoints were being edited.
            run_context=f"motion:{fingerprint[:12]}:resume-{self.state['resume_count']}",
        )
        self.message = self.notifier.stage_started("Motion Director", key="motion_director")
        self._save()

    def _save(self) -> None:
        self.state["updated_at"] = datetime.now(timezone.utc).isoformat()
        save_json(self.path, self.state)

    def checkpoint(self, phase: str, current: int, total: int, detail: str, status: str) -> None:
        self.state["status"] = "RUNNING"
        self.state["current"] = {
            "phase": phase,
            "current": current,
            "total": total,
            "detail": detail,
            "status": status,
        }
        self.state["checkpoints"][f"{phase}:{current}"] = {
            "status": status,
            "detail": detail,
            "at": datetime.now(timezone.utc).isoformat(),
        }
        self._save()
        marker = "↻ Reused" if status == "REUSED" else ("✅ Complete" if status == "DONE" else "▶ Running")
        self.notifier.stage_update(
            self.message,
            "Motion Director",
            [f"{marker} · {phase} {current}/{total}", detail, f"📌 Checkpoint {current}/{total}"],
        )

    def complete(self, detail: str) -> None:
        self.state["status"] = "DONE"
        self.state["completed_at"] = datetime.now(timezone.utc).isoformat()
        self.state["current"] = {"phase": "complete", "detail": detail, "status": "DONE"}
        self._save()
        self.notifier.stage_update(self.message, "Motion Director", ["✅ Motion plan complete", detail])

    def fail(self, detail: str) -> None:
        """Persist a truthful restart point and close the live progress entry."""
        self.state["status"] = "FAILED"
        self.state["failed_at"] = datetime.now(timezone.utc).isoformat()
        self.state["error"] = str(detail)[:1000]
        self._save()
        self.notifier.stage_update(
            self.message,
            "Motion Director",
            ["❌ Motion planning paused", str(detail)[:500], "↻ Resume continues from saved checkpoints."],
        )


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
    try:
        prompt_limit = int(os.getenv("YT_MOTION_MAX_PROMPT_CHARS", "28000"))
    except ValueError:
        prompt_limit = 28_000
    prompt_limit = min(60_000, max(12_000, prompt_limit))
    scope = os.getenv("YT_MOTION_CHATGPT_SCOPE", "fresh").strip().lower() or "fresh"
    if scope not in {"fresh", "temporary"}:
        scope = "fresh"
    if len(prompt) > prompt_limit:
        raise MotionPlanError(
            f"Motion Director prompt exceeds configured Ordak limit: {len(prompt)} > {prompt_limit} characters"
        )
    job_ids: list[str] = []
    current = prompt
    for correction in range(correction_attempts + 1):
        # A malformed gateway response before job creation is safe to retry
        # once.  Never repeat an Ordak job that has an id: it may already have
        # reached ChatGPT and duplicating an editorial turn would be unsafe.
        result = None
        for transport_attempt in range(2):
            try:
                result = jobs.run(
                    current, provider="chatgpt", mode="chat", generation=Generation(quality="best"),
                    references=references or [], attempts=2, chatgpt_chat=scope,
                )
                break
            except OrdakJobError as exc:
                retryable_gateway = (
                    exc.job_id is None
                    and transport_attempt == 0
                    and ("HTTP 5" in str(exc) or "Internal Server Error" in str(exc))
                )
                if not retryable_gateway:
                    raise
                log(f"↻ {label} Ordak gateway retry 1/1")
        if result is None:
            raise AssertionError("Ordak retry loop returned no result")
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
            available = max(0, prompt_limit - 50 - len(prompt) - len(correction_header))
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
    source_beats = {str(beat["beat_id"]): beat for beat in context["beats"]}
    corrections: list[dict[str, Any]] = list(payload.get("normalization_corrections") or [])
    for beat in payload.get("beats") or []:
        source = source_beats.get(str(beat.get("beat_id")))
        shots = list(beat.get("micro_shots") or [])
        if source is not None and shots:
            start, end = float(source["start"]), float(source["end"])
            beat_duration = end - start
            minimum = float(cfg["min_micro_shot_duration"])
            feasible_count = max(1, min(
                int(cfg["max_micro_shots_per_beat"]),
                int((beat_duration + .025) / minimum),
            ))
            shot_durations = [
                float(shot.get("end", 0)) - float(shot.get("start", 0))
                for shot in shots
            ]
            requires_retime = (
                len(shots) > feasible_count
                or any(duration < minimum - .025 for duration in shot_durations)
                or any(duration > float(cfg["max_micro_shot_duration"]) + .025 for duration in shot_durations)
                or abs(float(shots[0].get("start", start)) - start) > .025
                or abs(float(shots[-1].get("end", end)) - end) > .025
            )
            if requires_retime:
                # Physical body assets can legitimately be shorter than two editorial
                # micro-shots. Keep the model's earliest feasible shot decisions and
                # retime them evenly across the immutable beat window; this changes no
                # target, camera, or motion choice and avoids another paid correction turn.
                retained = shots[:feasible_count]
                interval = beat_duration / len(retained)
                for index, shot in enumerate(retained):
                    shot["start"] = round(start + index * interval, 3)
                    shot["end"] = round(end if index == len(retained) - 1 else start + (index + 1) * interval, 3)
                beat["micro_shots"] = retained
                if len(shots) > len(retained):
                    final_camera = (retained[-1].get("camera") or {}).get("end") or {}
                    ending = dict(beat.get("ending_state") or {})
                    ending.update({key: final_camera.get(key) for key in ("target_id", "coverage", "anchor_x", "anchor_y")})
                    beat["ending_state"] = ending
                corrections.append({
                    "beat_id": beat.get("beat_id"),
                    "code": "micro_shots_retimed_to_physical_beat_window",
                    "original_shot_count": len(shots),
                    "retained_shot_count": len(retained),
                })
        previous_end = None
        for shot in beat.get("micro_shots") or []:
            motion = shot.get("motion") or {}
            # Critic replacements sometimes use the human shorthand "push" or
            # "pull" although the executable contract names those primitives
            # ``push_in`` and ``pull_out``.  This is a one-to-one vocabulary
            # normalization: it preserves target, timing, camera and intent,
            # and prevents a completed critic batch from blocking a resume.
            shorthand_motion = {"push": "push_in", "pull": "pull_out"}
            original_motion = str(motion.get("type") or "")
            normalized_motion = shorthand_motion.get(original_motion)
            if normalized_motion:
                # Camera geometry is the executable evidence when shorthand
                # prose contradicts itself.  For one target, decreasing
                # coverage is a pull-out and increasing coverage is a push-in.
                # This avoids silently changing the recorded camera move.
                camera = shot.get("camera") or {}
                start_camera = camera.get("start") or {}
                end_camera = camera.get("end") or {}
                if start_camera.get("target_id") == end_camera.get("target_id"):
                    try:
                        coverage_delta = float(end_camera.get("coverage")) - float(start_camera.get("coverage"))
                    except (TypeError, ValueError):
                        coverage_delta = 0.0
                    if coverage_delta < -0.001:
                        normalized_motion = "pull_out"
                    elif coverage_delta > 0.001:
                        normalized_motion = "push_in"
                motion["type"] = normalized_motion
                shot["motion"] = motion
                corrections.append({
                    "shot_id": shot.get("shot_id"),
                    "code": f"motion_{original_motion}_normalized_to_{normalized_motion}",
                })
            # Critic replacements may round a camera coverage just outside the
            # strict normalized viewport bounds (for example 0.96).  Clamp only
            # those absolute safety bounds; target selection and composition are
            # left untouched.
            camera = shot.get("camera") or {}
            for state_name in ("start", "end"):
                state = camera.get(state_name)
                if not isinstance(state, dict):
                    continue
                for field, lower, upper in (("coverage", .08, .95), ("anchor_x", 0.0, 1.0), ("anchor_y", 0.0, 1.0)):
                    try:
                        value = float(state.get(field))
                    except (TypeError, ValueError):
                        continue
                    clamped = min(upper, max(lower, value))
                    if clamped != value:
                        state[field] = clamped
                        corrections.append({
                            "shot_id": shot.get("shot_id"),
                            "code": f"camera_{state_name}_{field}_clamped_to_safe_bounds",
                        })
            shot["camera"] = camera
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
        transition = beat.get("transition_out") or {}
        # ``verbal_emphasis`` is the critic's descriptive synonym for the
        # established contrast cut. Preserve the transition itself and map its
        # reason onto the closed executable vocabulary.
        if transition.get("reason_code") == "verbal_emphasis":
            transition["reason_code"] = "contrast"
            beat["transition_out"] = transition
            corrections.append({"beat_id": beat.get("beat_id"), "code": "transition_verbal_emphasis_normalized_to_contrast"})
        ending = beat.get("ending_state") or {}
        ending_aliases = {"neutral": "none", "static": "none", "still": "none", "zoom_in": "in", "zoom_out": "out"}
        original_direction = str(ending.get("movement_direction") or "")
        normalized_direction = ending_aliases.get(original_direction)
        if normalized_direction:
            ending["movement_direction"] = normalized_direction
            beat["ending_state"] = ending
            corrections.append({"beat_id": beat.get("beat_id"), "code": f"ending_direction_{original_direction}_normalized_to_{normalized_direction}"})
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
    progress = MotionProgress(video_dir, fingerprint)
    if not args.force and not args.recompile_existing and plan_path.is_file() and compiled_path.is_file():
        try:
            inventory = validate_inventory(load_json(motion_dir / "VISUAL_INVENTORY.json", {}), beats)
            existing = load_json(plan_path, {})
            if existing.get("input_fingerprint") == fingerprint:
                validate_plan(existing, context, inventory, cfg)
                compiled = load_json(compiled_path, {})
                if compiled.get("input_fingerprint") == fingerprint and compiled.get("compiled") is True:
                    progress.complete("Reused the verified existing motion plan.")
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
        progress.complete("Recompiled the existing verified motion plan.")
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
                progress.checkpoint("observation", batch_number, observation_total, label, "RUNNING")
                log(f"▶ {label}")
                response, job_ids = ask_validated_json(
                    jobs, observation_prompt(batch), validator,
                    references=target_refs(video_dir, batch, "motion_observation"),
                    correction_attempts=cfg["correction_attempts"], label=label,
                )
                save_json(receipt, {"schema_version": 2, "stage": "observation", "prompt_version": PROMPT_VERSION, "input_fingerprint": batch_fp, "job_ids": job_ids, "response": response})
                log(f"✔ {label}")
                progress.checkpoint("observation", batch_number, observation_total, label, "DONE")
            else:
                log(f"↻ {label} reused")
                progress.checkpoint("observation", batch_number, observation_total, label, "REUSED")
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
            progress.checkpoint("direction", 1, 1, direction_label, "RUNNING")
            log(f"▶ {direction_label}")
            direction, job_ids = ask_validated_json(
                jobs, direction_text,
                lambda value: validate_direction(value, context), correction_attempts=cfg["correction_attempts"], label=direction_label,
            )
            save_json(direction_receipt, {"schema_version": 2, "stage": "direction", "prompt_version": PROMPT_VERSION, "input_fingerprint": direction_fp, "job_ids": job_ids, "response": direction})
            log(f"✔ {direction_label}")
            progress.checkpoint("direction", 1, 1, direction_label, "DONE")
        else:
            log("↻ motion_direction 1/1 reused")
            progress.checkpoint("direction", 1, 1, "motion_direction 1/1", "REUSED")
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
                final_image_id=context.get("final_image_id"),
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
                progress.checkpoint("planning", batch_number, planning_total, label, "RUNNING")
                log(f"▶ {label}")
                response, job_ids = ask_validated_json(
                    jobs, prompt, validator, references=target_refs(video_dir, batch, "motion_planning"),
                    correction_attempts=cfg["correction_attempts"], label=label,
                )
                save_json(receipt, {"schema_version": 2, "stage": "planning", "prompt_version": PROMPT_VERSION, "input_fingerprint": batch_fp, "job_ids": job_ids, "response": response})
                log(f"✔ {label}")
                progress.checkpoint("planning", batch_number, planning_total, label, "DONE")
            else:
                log(f"↻ {label} reused")
                progress.checkpoint("planning", batch_number, planning_total, label, "REUSED")
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
                    progress.checkpoint("critic", batch_number, critic_total, label, "RUNNING")
                    log(f"▶ {label}")
                    part, job_ids = ask_validated_json(
                        jobs, prompt, validate_critic, correction_attempts=cfg["correction_attempts"], label=label,
                    )
                    save_json(critic_receipt, {"schema_version": 2, "stage": "critic", "prompt_version": PROMPT_VERSION, "input_fingerprint": critic_fp, "job_ids": job_ids, "response": part})
                    log(f"✔ {label}")
                    progress.checkpoint("critic", batch_number, critic_total, label, "DONE")
                else:
                    log(f"↻ {label} reused")
                    progress.checkpoint("critic", batch_number, critic_total, label, "REUSED")
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
    progress.complete("Validated, compiled, and quality-checked all motion batches.")


if __name__ == "__main__":
    main()
