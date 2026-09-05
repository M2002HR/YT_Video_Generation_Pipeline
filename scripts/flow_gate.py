#!/usr/bin/env python3
"""Is the run blocked only on Google Flow, and are its clips here yet?

Flow's regional block is a restriction on Google's side, not a fault in this pipeline. When
it hits, everything that does not need a video clip can still be produced — narration,
timing, music — and only the trim and the render have to wait. These helpers are what lets
the wrapper make that distinction instead of failing the whole episode.
"""
from __future__ import annotations

import json
from pathlib import Path

#: The two Flow sources an episode needs, in the order the pipeline makes them.
FLOW_CLIP_FILES = ("question_spark_source.mp4", "book_transition_source.mp4")

#: Stage names whose failure means "waiting for Flow", not "the episode is wrong".
FLOW_STAGES = ("flow_clip_a", "flow_clip_b")

#: How a Flow outage announces itself in a stage message.
FLOW_OUTAGE_MARKERS = (
    "not available in this country",
    "unsupported-country",
    "flow_region_blocked",
    "high demand",
    "flow_generation_timeout",
    "flow_credits_exhausted",
)


def clip_paths(project: Path) -> list[Path]:
    return [Path(project) / "assets" / "opening" / name for name in FLOW_CLIP_FILES]


def missing_clips(project: Path) -> list[Path]:
    """The Flow sources that are still absent or empty."""
    return [path for path in clip_paths(project) if not path.is_file() or path.stat().st_size == 0]


def clips_ready(project: Path) -> bool:
    return not missing_clips(project)


def _runtime_state(project: Path) -> dict:
    path = Path(project) / "pipeline" / "QH_RUNTIME_STATE.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def failed_stages(project: Path) -> dict[str, str]:
    """Stage name → message, for every stage the last run left failed."""
    stages = _runtime_state(project).get("stages")
    if not isinstance(stages, dict):
        return {}
    out: dict[str, str] = {}
    for name, entry in stages.items():
        if not isinstance(entry, dict):
            continue
        status = str(entry.get("status") or "")
        if status.startswith("FAILED") or status.startswith("PAUSED"):
            out[str(name)] = str(entry.get("message") or "")
    return out


def blocked_only_on_flow(project: Path) -> tuple[bool, str]:
    """True when Flow is the *only* thing standing between here and a finished episode.

    Returns the verdict and the reason to log. A failure in any other stage, or a Flow
    failure that is not an outage, is a real pipeline failure and must not be waited out.
    """
    failures = failed_stages(project)
    if not failures:
        return (False, "no failed stage recorded")
    other = sorted(name for name in failures if name not in FLOW_STAGES)
    if other:
        return (False, f"stages other than Flow failed: {', '.join(other)}")
    for name, message in sorted(failures.items()):
        lowered = message.lower()
        if not any(marker in lowered for marker in FLOW_OUTAGE_MARKERS):
            return (False, f"{name} failed for a reason that is not a Flow outage: {message}")
    reason = "; ".join(f"{name}: {message}" for name, message in sorted(failures.items()))
    return (True, reason)
