"""Versioned, deliberately conservative SFX planning artifacts."""
from __future__ import annotations
import json, math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
CATEGORIES = {"foley", "ambience", "transition", "impact", "water", "weather", "mechanical", "crowd"}
class SFXPlanError(ValueError): pass
def path(project: Path) -> Path: return Path(project) / "sfx" / "SFX_PLAN.json"
def load(project: Path) -> dict[str, Any]: return json.loads(path(project).read_text(encoding="utf-8"))
def _num(value: Any, name: str) -> float:
    try: value = float(value)
    except (TypeError, ValueError): raise SFXPlanError(f"{name} must be numeric")
    if not math.isfinite(value): raise SFXPlanError(f"{name} must be finite")
    return value
def validate(payload: dict[str, Any], *, max_events_per_minute: float = 6, minimum_gap_seconds: float = 2.0) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION: raise SFXPlanError("unsupported SFX plan schema_version")
    duration = _num(payload.get("episode_duration_seconds"), "episode_duration_seconds")
    if duration <= 0: raise SFXPlanError("episode_duration_seconds must be positive")
    events = payload.get("events")
    if not isinstance(events, list): raise SFXPlanError("events must be a list")
    if len(events) > math.ceil(duration / 60 * max_events_per_minute): raise SFXPlanError("SFX density exceeds configured maximum")
    seen, normalized = set(), []
    for raw in events:
        if not isinstance(raw, dict): raise SFXPlanError("each SFX event must be an object")
        item = dict(raw); event_id = str(item.get("event_id") or "").strip()
        if not event_id or event_id in seen: raise SFXPlanError("SFX event IDs must be unique and non-empty")
        seen.add(event_id); item["event_id"] = event_id
        for name in ("at", "window_start", "window_end", "desired_duration_seconds", "max_duration_seconds", "suggested_gain_db"):
            item[name] = _num(item.get(name), name)
        if not 0 <= item["at"] < duration: raise SFXPlanError(f"{event_id}: at is outside video duration")
        if not 0 <= item["window_start"] <= item["at"] <= item["window_end"] <= duration: raise SFXPlanError(f"{event_id}: invalid timing window")
        if not 0 < item["desired_duration_seconds"] <= item["max_duration_seconds"] <= 30: raise SFXPlanError(f"{event_id}: invalid duration")
        if str(item.get("category") or "").lower() not in CATEGORIES: raise SFXPlanError(f"{event_id}: unsupported category")
        item["category"] = str(item["category"]).lower()
        if not str(item.get("search_query") or "").strip(): raise SFXPlanError(f"{event_id}: search_query is required")
        item["alternate_queries"] = [str(x).strip() for x in item.get("alternate_queries", []) if str(x).strip()]
        normalized.append(item)
    normalized.sort(key=lambda x: x["at"])
    for left, right in zip(normalized, normalized[1:]):
        if right["at"] - left["at"] < minimum_gap_seconds and left["category"] != "ambience" and right["category"] != "ambience": raise SFXPlanError("SFX events violate minimum gap")
    result = dict(payload); result["events"] = normalized; result["event_count"] = len(normalized)
    return result
def write(project: Path, payload: dict[str, Any], **limits: Any) -> Path:
    payload = validate(payload, **limits); payload["updated_at"] = datetime.now(timezone.utc).isoformat(); payload["status"] = "DONE"
    target = path(project); target.parent.mkdir(parents=True, exist_ok=True); target.write_text(json.dumps(payload, ensure_ascii=False, indent=2)+"\n", encoding="utf-8"); return target
