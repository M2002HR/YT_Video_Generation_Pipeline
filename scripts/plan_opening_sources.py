#!/usr/bin/env python3
"""Choose supported Flow source durations from measured narration boundaries.

The launch settings express a preferred opening length.  They are not blindly sent to
Flow: ElevenLabs and word-level alignment run first, then this planner selects the closest
supported source duration that can reach each real narration boundary within the permitted
silent-video slow-down tolerance.  The durable plan is also the source contract used by
the Flow stages on every resume.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flow_capabilities import durations_for_model
from presentation_runtime import presentation_for_project
from gateway_contracts import validate_entry_duration


PLAN_RELATIVE_PATH = Path("timing") / "OPENING_SOURCE_PLAN.json"


class OpeningSourcePlanError(RuntimeError):
    pass


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise OpeningSourcePlanError(f"Cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise OpeningSourcePlanError(f"{path} must contain a JSON object.")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _number(value: object, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise OpeningSourcePlanError(f"{label} is not a usable number.") from exc
    if number <= 0:
        raise OpeningSourcePlanError(f"{label} must be positive.")
    return number


def choose_source_seconds(target: float, preferred: int, candidates: tuple[int, ...], tolerance: float) -> dict[str, Any]:
    """Pick the closest truthful Flow duration, using tolerance only when needed.

    A longer source is harmless because trim removes unused frames.  A slightly shorter
    source is allowed only when the silent-video rate adjustment can honestly cover it.
    Preference is a deterministic tie-breaker, never a reason to select an incapable clip.
    """
    capable = [
        seconds for seconds in candidates
        if target <= seconds + 0.05 or target <= seconds * (1 + tolerance) + 1e-9
    ]
    if not capable:
        maximum = max(candidates)
        raise OpeningSourcePlanError(
            f"The narration needs {target:.3f}s, but the longest supported source is "
            f"{maximum}s and can reach only {maximum * (1 + tolerance):.3f}s at the "
            f"configured {tolerance * 100:.1f}% tolerance. Shorten the opening narration "
            "or add a longer Flow duration option."
        )
    selected = min(capable, key=lambda seconds: (abs(seconds - target), abs(seconds - preferred), seconds))
    factor = target / selected
    return {
        "target_seconds": round(target, 3),
        "preferred_source_seconds": preferred,
        "supported_source_seconds": list(candidates),
        "selected_source_seconds": selected,
        "estimated_speed_factor": round(factor, 6),
        "estimated_rate_adjusted": target > selected + 0.05,
        "estimated_headroom_seconds": round(selected - target, 3),
    }


def build_plan(project: Path) -> dict[str, Any]:
    timing_path = project / "timing" / "OPENING_TIMING.json"
    brief_path = project / "launch" / "CREATIVE_BRIEF.json"
    timing = _load_object(timing_path)
    brief = _load_object(brief_path)
    settings = brief.get("_q_station") if isinstance(brief.get("_q_station"), dict) else {}
    try:
        tolerance = float(settings.get("opening_speed_tolerance", 0.1))
    except (TypeError, ValueError) as exc:
        raise OpeningSourcePlanError("opening_speed_tolerance is not a usable number.") from exc
    if not 0 <= tolerance <= 0.5:
        raise OpeningSourcePlanError("opening_speed_tolerance must be between 0 and 0.5.")
    spark_end = _number(timing.get("spark_end"), "OPENING_TIMING.spark_end")
    transition_end = _number(timing.get("transition_end"), "OPENING_TIMING.transition_end")
    if transition_end <= spark_end:
        raise OpeningSourcePlanError("OPENING_TIMING.transition_end must be after spark_end.")
    try:
        validate_entry_duration(presentation_for_project(project), transition_end - spark_end)
    except ValueError as exc:
        raise OpeningSourcePlanError(str(exc)) from exc
    model = str(settings.get("flow_video_model") or "gemini_omni_1_1_flash")
    candidates = durations_for_model(model)
    if not candidates:
        raise OpeningSourcePlanError(
            f"No verified Flow duration capability is recorded for model {model!r}. "
            "Refresh the model capability contract before requesting media."
        )
    preferred_a = int(_number(settings.get("opening_a_source_seconds", 6), "opening_a_source_seconds"))
    preferred_b = int(_number(settings.get("opening_b_source_seconds", 4), "opening_b_source_seconds"))
    if preferred_a not in candidates or preferred_b not in candidates:
        raise OpeningSourcePlanError("The preferred opening durations are not supported by the Flow integration.")
    return {
        "schema_version": 1,
        "status": "PLANNED",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "timing_sha256": _sha256(timing_path),
        "flow_model": model,
        "verified_source_seconds": list(candidates),
        "opening_speed_tolerance": tolerance,
        "clips": {
            "A": choose_source_seconds(spark_end, preferred_a, candidates, tolerance),
            "B": choose_source_seconds(transition_end - spark_end, preferred_b, candidates, tolerance),
        },
    }


def comparable(plan: dict[str, Any]) -> dict[str, Any]:
    return {key: plan.get(key) for key in ("timing_sha256", "flow_model", "verified_source_seconds", "opening_speed_tolerance", "clips")}


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan Flow opening-source durations from word-level narration timing.")
    parser.add_argument("video_dir", type=Path)
    args = parser.parse_args()
    project = args.video_dir.resolve()
    path = project / PLAN_RELATIVE_PATH
    plan = build_plan(project)
    try:
        previous = _load_object(path)
    except OpeningSourcePlanError:
        previous = {}
    changed = comparable(previous) != comparable(plan)
    if not changed:
        plan = {**previous, "status": "REUSED", "reused_at": datetime.now(timezone.utc).isoformat()}
    else:
        plan["changed_from_previous"] = bool(previous)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    clips = plan["clips"]
    print(
        f"OPENING SOURCE PLAN {'UPDATED' if changed else 'REUSED'}: "
        f"A={clips['A']['selected_source_seconds']}s for {clips['A']['target_seconds']:.3f}s, "
        f"B={clips['B']['selected_source_seconds']}s for {clips['B']['target_seconds']:.3f}s",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except OpeningSourcePlanError as exc:
        print(f"FAILED_VALIDATION: {exc}", file=sys.stderr, flush=True)
        sys.exit(2)
