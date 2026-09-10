#!/usr/bin/env python3
"""HTTP API and process lifecycle for the Video Pipeline Studio.

The React client provides launch, provider health, run workspaces, artifact previews, live
activity, and dependency-aware regeneration. This loopback service owns validation and all
filesystem/process mutations; nginx exposes it with authentication on the public ports.
"""
from __future__ import annotations

import argparse
import base64
import html
import hashlib
import json
import os
import re
import mimetypes
import shutil
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import panel_page
from panel_previews import preview as build_preview
from image_artifacts import receipt_status
from panel_contract import defaults as launch_defaults
from panel_contract import launch_schema
from run_graph import graph_for, invalidation_paths, regeneration_plan
from content_projects import (
    DEFAULT_CONTENT_PROJECT, list_content_projects, load_content_project,
    resolve_project_id, validate_content_project, validate_provider_locks,
    normalize_gemini_model, normalize_flow_model, video_slug, character_registry_path,
)
from character_runtime import CharacterSelectionError, load_character_registry

ROOT = Path(__file__).resolve().parents[1]
LAUNCH_LOCK = threading.Lock()
PROVIDER_STATUS_LOCK = threading.Lock()
PROVIDER_STATUS_CACHE: dict[str, object] = {"at": 0.0, "base": "", "value": {}}
PREFERRED_CONTENT_PROJECT = "q_station"
CREATIVE_FIELDS = ("working_title", "audience", "narrative_angle", "must_include", "must_avoid", "source_notes")

QH_ROOTS = {
    "character_mode": ("character_resolution",),
    "character_id": ("character_resolution",),
    "world_style_policy": ("world_style_director",),
    "world_style_id": ("world_style_director",),
    "world_style_hint": ("world_style_director",),
    "gemini_image_model": ("world_style_anchor",),
    "flow_video_model": ("flow_clip_a", "flow_clip_b"),
    "flow_resolution": ("flow_clip_a", "flow_clip_b"),
    "opening_a_seconds": ("flow_clip_a",),
    "opening_b_seconds": ("flow_clip_b",),
    "min_duration_seconds": ("retention_edit",),
    "max_duration_seconds": ("retention_edit",),
    "show_subtitles": ("render_profile",),
    "hero_presence_mode": ("episode_director",),
    # This layout choice changes the paid body-image continuity chain only. Existing
    # opening clips and the world keyframe remain stable during a revision.
    "reserve_subtitle_space": ("beat_image_001",),
    "chatgpt_fallback_auto": (),
}
QH_FIELDS = tuple(QH_ROOTS)
QH_STORED_FIELDS = {
    **{key: key for key in QH_FIELDS if key not in {"character_mode", "character_id"}},
    "opening_a_seconds": "opening_a_source_seconds",
    "opening_b_seconds": "opening_b_source_seconds",
    "chatgpt_fallback_auto": "chatgpt_fallback_mode",
}
VOICE_FIELDS = ("voice", "model", "speed", "stability", "similarity", "style")
MOTION_FIELDS = {
    "motion_transition_preference": "transition_preference",
    "motion_max_micro_shots": "max_micro_shots_per_beat",
    "motion_interval_min": "target_interval_min",
    "motion_interval_max": "target_interval_max",
    "motion_allow_punch_ins": "allow_punch_cuts",
    "motion_allow_directional_pans": "allow_pan",
    "motion_allow_hard_reframe_cuts": "allow_hard_reframes",
    "motion_transition_fraction": "max_decorative_transition_fraction",
    "motion_transition_min": "transition_duration_min",
    "motion_transition_max": "transition_duration_max",
    "motion_observation_batch": "observation_batch_size",
    "motion_planning_batch": "planning_batch_size",
    "motion_critic_batch": "critic_batch_size",
    "motion_correction_attempts": "correction_attempts",
    "motion_neighbor_context": "neighbor_context",
    "motion_word_sync_tolerance": "word_sync_tolerance_ms",
}


def frozen_values(record: dict, brief: dict, voice: dict) -> dict:
    """Flatten a run's versioned files into the launch form's typed field names."""
    values = dict(launch_defaults(studio_schema()))
    values.update({key: brief.get(key, values.get(key, "")) for key in CREATIVE_FIELDS})
    values.update({
        "topic": record.get("topic", ""),
        "content_project": resolve_project_id(str(record.get("content_project", DEFAULT_CONTENT_PROJECT))),
    })
    qh = brief.get("_qh") if isinstance(brief.get("_qh"), dict) else {}
    values.update({
        field: qh[stored]
        for field, stored in QH_STORED_FIELDS.items()
        if field != "chatgpt_fallback_auto" and stored in qh
    })
    values["chatgpt_fallback_auto"] = qh.get("chatgpt_fallback_mode", "approval") == "auto"
    character = qh.get("character") if isinstance(qh.get("character"), dict) else record.get("character") or {}
    values["character_mode"] = str(character.get("mode") or "auto")
    values["character_id"] = str(character.get("character_id") or "")
    values["reserve_subtitle_space"] = bool(qh.get("reserve_subtitle_space", True))
    values["word_highlight"] = bool((brief.get("_subtitle") or {}).get("word_highlight", True))
    values.update({key: voice[key] for key in VOICE_FIELDS if key in voice})
    inverse_motion = {stored: field for field, stored in MOTION_FIELDS.items()}
    for key, value in (brief.get("_motion") or {}).items():
        field = inverse_motion.get(key, f"motion_{key}")
        if field in values:
            values[field] = value
    for key, value in (brief.get("_sfx") or {}).items():
        field = f"sfx_{key}"
        if field in values:
            values[field] = value
    values.update({
        key: record.get(key, values.get(key))
        for key in ("aspect_ratio", "music_providers", "commit_artifacts", "telegram_low_size", "telegram_original")
    })
    return values


def validate_config_values(values: dict) -> dict:
    """Validate and normalize the structured revision payload against the public schema."""
    schema = studio_schema()
    fields = {
        field["name"]: field
        for group in schema["groups"]
        for field in group["fields"]
        if field["type"] != "readonly"
    }
    unknown = set(values) - set(fields)
    if unknown:
        raise ValueError(f"Unknown configuration field(s): {', '.join(sorted(unknown))}")
    normalized: dict[str, Any] = {}
    for name, field in fields.items():
        value = values.get(name, field.get("default", False if field["type"] == "toggle" else ""))
        kind = field["type"]
        if kind == "toggle":
            if not isinstance(value, bool):
                raise ValueError(f"{field['label']} must be on or off.")
        elif kind == "number":
            if isinstance(value, bool):
                raise ValueError(f"{field['label']} must be a number.")
            try:
                number = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{field['label']} must be a number.") from exc
            if field.get("min") is not None and number < float(field["min"]):
                raise ValueError(f"{field['label']} is below its minimum.")
            if field.get("max") is not None and number > float(field["max"]):
                raise ValueError(f"{field['label']} is above its maximum.")
            value = int(number) if number.is_integer() and float(field.get("step", 1)).is_integer() else number
        elif kind == "select":
            value = str(value)
            allowed = {str(option["value"]) for option in field.get("options", [])}
            if value not in allowed:
                raise ValueError(f"Invalid value for {field['label']}.")
        elif kind == "priority":
            allowed = {str(option["value"]) for option in field.get("options", [])}
            if not isinstance(value, list) or not value or len(value) != len(set(value)) or any(item not in allowed for item in value):
                raise ValueError(f"Choose a valid, non-duplicated priority for {field['label']}.")
        else:
            value = str(value or "").strip()
            if field.get("required") and not value:
                raise ValueError(f"{field['label']} is required.")
            if field.get("maxLength") and len(value) > int(field["maxLength"]):
                raise ValueError(f"{field['label']} is too long.")
        normalized[name] = value
    if float(normalized["min_duration_seconds"]) > float(normalized["max_duration_seconds"]):
        raise ValueError("Minimum duration cannot be greater than maximum duration.")
    if not normalized["telegram_low_size"] and not normalized["telegram_original"]:
        raise ValueError("Choose at least one Telegram delivery output.")
    motion_primitives = (
        "motion_allow_hold", "motion_allow_push", "motion_allow_pull",
        "motion_allow_directional_pans", "motion_allow_tilt", "motion_allow_pan_push",
        "motion_allow_pan_pull", "motion_allow_drift", "motion_allow_settle",
        "motion_allow_reveal_move",
    )
    if normalized["motion_enabled"] and not any(normalized[name] for name in motion_primitives):
        raise ValueError("Enable at least one Motion primitive.")
    return normalized


def config_roots(record: dict, previous: dict, voice_before: dict, values: dict) -> tuple[set[str], dict, dict, dict, list[str]]:
    """Build revised frozen files and exact graph roots from panel-shaped values."""
    before = validate_config_values(frozen_values(record, previous, voice_before))
    merged = validate_config_values({**before, **values})
    if resolve_project_id(merged["content_project"]) != resolve_project_id(str(record.get("content_project"))):
        raise ValueError("Content project cannot change inside an existing run.")
    changed_fields = [key for key in merged if before.get(key) != merged.get(key)]
    if any(key in changed_fields for key in ("character_mode", "character_id")):
        raise ValueError("Resolved character cannot be changed inside an existing run; start a new run instead.")
    roots: set[str] = set()
    brief = {**previous, **{key: merged[key] for key in CREATIVE_FIELDS}}
    qh = dict(previous.get("_qh") or {})
    for key in QH_FIELDS:
        if key in {"chatgpt_fallback_auto", "character_mode", "character_id"}:
            continue
        qh[QH_STORED_FIELDS[key]] = merged[key]
        if before.get(key) != merged.get(key):
            roots.update(QH_ROOTS[key])
    qh["chatgpt_fallback_mode"] = "auto" if merged["chatgpt_fallback_auto"] else "approval"
    qh["character"] = {
        "mode": merged["character_mode"],
        **({"character_id": merged["character_id"]} if merged["character_mode"] == "manual" else {}),
    }
    if before.get("chatgpt_fallback_auto") != merged.get("chatgpt_fallback_auto"):
        roots.update(QH_ROOTS["chatgpt_fallback_auto"])
    brief["_qh"] = qh
    brief["_subtitle"] = {**dict(previous.get("_subtitle") or {}), "word_highlight": merged["word_highlight"]}
    if before.get("word_highlight") != merged.get("word_highlight"):
        roots.add("render_profile")
    motion = {
        MOTION_FIELDS.get(key, key.removeprefix("motion_")): merged[key]
        for key in merged if key.startswith("motion_")
    }
    brief["_motion"] = {**dict(previous.get("_motion") or {}), **motion}
    if any(before.get(key) != merged.get(key) for key in merged if key.startswith("motion_")):
        roots.add("motion_director")
    sfx = {key.removeprefix("sfx_"): merged[key] for key in merged if key.startswith("sfx_")}
    brief["_sfx"] = {**dict(previous.get("_sfx") or {}), **sfx}
    if any(before.get(key) != merged.get(key) for key in merged if key.startswith("sfx_")):
        roots.update(("sfx_plan", "sfx_acquire"))
    voice = {**voice_before, **{key: merged[key] for key in VOICE_FIELDS}}
    if any(before.get(key) != merged.get(key) for key in VOICE_FIELDS):
        roots.add("elevenlabs_voiceover")
    launch = {key: merged[key] for key in ("music_providers", "aspect_ratio", "commit_artifacts", "telegram_low_size", "telegram_original")}
    launch["_topic"] = merged["topic"]
    if before.get("music_providers") != merged.get("music_providers"):
        roots.add("background_music")
    if before.get("aspect_ratio") != merged.get("aspect_ratio"):
        roots.update(("flow_clip_a", "flow_clip_b", "render_profile"))
    if before.get("commit_artifacts") != merged.get("commit_artifacts"):
        roots.add("git_commit_push")
    if before.get("telegram_low_size") != merged.get("telegram_low_size"):
        roots.update(("telegram_compress", "publish_telegram"))
    if before.get("telegram_original") != merged.get("telegram_original"):
        roots.add("publish_telegram")
    if before.get("topic") != merged.get("topic") or any(before.get(key) != merged.get(key) for key in CREATIVE_FIELDS):
        roots.add("script_draft")
    return roots, brief, voice, launch, changed_fields

#: Where Ordak answers, for the provider badges.
ORDAK_BASE_URL = os.getenv("YT_ORDAK_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
PROVIDERS = ("chatgpt", "gemini", "flow")
MUSIC_PROVIDERS = ("freesound", "mixkit", "pixabay")
JOB_ID_RE = re.compile(r"^[a-f0-9-]{36}$")
STYLE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,119}$", re.IGNORECASE)


def studio_schema() -> dict:
    """Current launch form contract, including live project and style choices."""
    projects = [
        {"value": project.project_id, "label": project.display_name}
        for project in list_content_projects()
    ]
    schema = launch_schema(projects, catalogued_style_ids(PREFERRED_CONTENT_PROJECT))
    characters = character_catalog_entries(PREFERRED_CONTENT_PROJECT)
    for group in schema["groups"]:
        for field in group["fields"]:
            if field["name"] == "character_id":
                field["options"] = [{"value": "", "label": "Choose a character"}] + [
                    {"value": item["id"], "label": item["display_name"]} for item in characters
                ]
    return schema


def activity_for(record: dict, project: Path) -> list[dict]:
    """Normalize durable runner state into stable, de-duplicatable UI events."""
    events: list[dict] = []
    try:
        qh = json.loads((project / "pipeline/QH_RUNTIME_STATE.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        qh = {}
    for stage, entry in (qh.get("stages") or {}).items():
        if not isinstance(entry, dict):
            continue
        at = entry.get("updated_at") or qh.get("updated_at") or record.get("created_at")
        status = str(entry.get("status") or "PENDING")
        events.append({"id": f"qh:{stage}:{status}:{at}", "stage": stage, "status": status, "at": at, "message": entry.get("message"), "elapsed_seconds": entry.get("elapsed_seconds")})
    try:
        visual = json.loads((project / "visual_pipeline/RUNTIME_STATE.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        visual = {}
    for stage, entry in (visual.get("stages") or {}).items():
        if not isinstance(entry, dict):
            continue
        shown = {"visual_beats": "visual_plan", "world_design": "episode_world_design"}.get(str(stage), str(stage))
        at = entry.get("completed_at") or visual.get("updated_at") or record.get("created_at")
        status = str(entry.get("status") or "PENDING")
        events.append({"id": f"visual:{shown}:{status}:{at}", "stage": shown, "status": status, "at": at, "message": entry.get("last_error"), "elapsed_seconds": entry.get("elapsed_seconds")})
    for number, entry in (visual.get("beats") or {}).items():
        if not isinstance(entry, dict) or not str(number).isdigit():
            continue
        stage, status = f"beat_image_{int(number):03d}", str(entry.get("status") or "PENDING")
        at = entry.get("completed_at") or visual.get("updated_at") or record.get("created_at")
        events.append({"id": f"visual:{stage}:{status}:{at}", "stage": stage, "status": status, "at": at, "message": entry.get("last_error"), "elapsed_seconds": entry.get("elapsed_seconds")})
    try:
        generic = json.loads((project / "pipeline/FULL_PIPELINE_RUNTIME_STATE.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        generic = {}
    aliases = {"visuals": "visual_qc", "voiceover": "elevenlabs_voiceover", "timing": "ajil_alignment", "music": "background_music", "completion": "finalization"}
    for index, entry in enumerate(generic.get("events") or []):
        if not isinstance(entry, dict) or not entry.get("stage"):
            continue
        stage = aliases.get(str(entry["stage"]), str(entry["stage"]))
        at = entry.get("ended_at") or entry.get("started_at")
        status = str(entry.get("status") or "RUNNING")
        events.append({"id": f"generic:{index}:{stage}:{status}:{at}", "stage": stage, "status": status, "at": at, "message": entry.get("error"), "elapsed_seconds": entry.get("elapsed_seconds")})
    try:
        wrapper = json.loads((project / "pipeline/WRAPPER_RUNTIME_STATE.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        wrapper = {}
    for index, entry in enumerate(wrapper.get("events") or []):
        if not isinstance(entry, dict) or not entry.get("stage"):
            continue
        at = entry.get("ended_at") or entry.get("started_at")
        status = str(entry.get("status") or "RUNNING")
        events.append({"id": f"wrapper:{index}:{entry['stage']}:{status}:{at}", "stage": entry["stage"], "status": status, "at": at, "message": entry.get("message"), "elapsed_seconds": entry.get("elapsed_seconds")})
    try:
        final = json.loads((project / "pipeline/FINALIZATION_RUNTIME_STATE.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        final = {}
    for index, entry in enumerate(final.get("events") or []):
        if not isinstance(entry, dict) or not entry.get("stage"):
            continue
        at = entry.get("ended_at") or entry.get("started_at")
        status = str(entry.get("status") or "RUNNING")
        events.append({"id": f"final:{index}:{entry['stage']}:{status}:{at}", "stage": entry["stage"], "status": status, "at": at, "message": entry.get("error") or (f"exit code {entry.get('returncode')}" if entry.get("returncode") is not None else None), "elapsed_seconds": entry.get("elapsed_seconds")})
    revisions = project / "pipeline/revisions"
    for path in revisions.glob("*/REVISION.json") if revisions.is_dir() else []:
        try:
            revision = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        events.append({"id": f"revision:{revision.get('revision_id', path.parent.name)}:{revision.get('status', 'QUEUED')}", "stage": ", ".join(revision.get("roots") or [revision.get("target") or "revision"]), "status": revision.get("status", "QUEUED"), "at": revision.get("completed_at") or revision.get("created_at"), "message": "Revision"})
    return sorted(events, key=lambda item: str(item.get("at") or ""))


def catalogued_style_ids(content_project: str) -> list[str]:
    """The world styles this content project can reuse, newest catalog order kept."""
    try:
        project = load_content_project(content_project)
    except RuntimeError:
        return []
    catalog = project.root / "world_styles" / "CATALOG.json"
    try:
        entries = json.loads(catalog.read_text(encoding="utf-8")).get("styles") or []
    except (OSError, ValueError):
        return []
    return [str(entry.get("style_id")) for entry in entries if entry.get("style_id")]


def style_catalog_entries(content_project: str) -> list[dict[str, object]]:
    """Return safe, presentation-ready catalog metadata without exposing source files."""
    try:
        project = load_content_project(content_project)
    except RuntimeError:
        return []
    content_project = project.project_id
    catalog_root = project.root / "world_styles"
    try:
        styles = json.loads((catalog_root / "CATALOG.json").read_text(encoding="utf-8")).get("styles") or []
    except (OSError, ValueError):
        return []
    result: list[dict[str, object]] = []
    for entry in styles:
        if not isinstance(entry, dict):
            continue
        style_id = str(entry.get("style_id") or "")
        if not STYLE_ID_RE.fullmatch(style_id):
            continue
        anchor = catalog_root / str(entry.get("anchor") or "")
        try:
            anchor.resolve().relative_to(catalog_root.resolve())
        except ValueError:
            continue
        result.append({
            "style_id": style_id,
            "display_name": str(entry.get("display_name") or style_id.replace("_", " ").title()),
            "medium_family": entry.get("medium_family"),
            "texture_family": entry.get("texture_family"),
            "palette_summary": entry.get("palette_summary"),
            "usage_count": int(entry.get("usage_count") or 0),
            "anchor_available": anchor.is_file() and anchor.stat().st_size > 0,
            "anchor_url": f"/api/styles/{content_project}/{style_id}/anchor",
            "sample_url": f"/api/styles/{content_project}/{style_id}/sample",
            "sample_available": bool(style_sample_for(style_id, content_project)),
        })
    return result


def character_catalog_entries(content_project: str) -> list[dict[str, object]]:
    """Enabled server-side character catalog; never exposes reference paths."""
    try:
        project = load_content_project(content_project)
        path = character_registry_path(project)
        if path is None:
            return []
        return load_character_registry(path).catalog()
    except RuntimeError:
        return []


_STYLE_SAMPLE_LOCK = threading.Lock()
_STYLE_SAMPLE_CACHE: dict = {}


def style_sample_for(style_id: str, content_project: str = "q_station") -> Path | None:
    """Choose only validated samples; scan once per short cache window, not per style."""
    key = (str(ROOT), content_project)
    with _STYLE_SAMPLE_LOCK:
        cached = _STYLE_SAMPLE_CACHE.get(key)
        if cached and time.monotonic() - cached[0] < 3:
            return cached[1].get(style_id)
        samples: dict[str, Path] = {}
        videos = ROOT / "videos"
        for project in videos.iterdir() if videos.is_dir() else []:
            if not project.is_dir():
                continue
            try:
                plan = json.loads((project / "creative/WORLD_STYLE_PLAN.json").read_text())
                launch_path = project / "launch/LAUNCH_REQUEST.json"
                launch = json.loads(launch_path.read_text()) if launch_path.is_file() else {}
                if resolve_project_id(str(launch.get("content_project") or "question_harvest")) != resolve_project_id(content_project):
                    continue
                chosen = str(plan.get("style_id") or "")
                for candidate in (project / "assets/raw_beats").glob("beat_*.png"):
                    receipt = project / "pipeline/provider_receipts" / f"gemini_{candidate.stem}.json"
                    if receipt_status(project, candidate, receipt)["status"] != "verified":
                        continue
                    if chosen not in samples or candidate.stat().st_mtime_ns > samples[chosen].stat().st_mtime_ns:
                        samples[chosen] = candidate
            except (OSError, ValueError, TypeError):
                continue
        _STYLE_SAMPLE_CACHE.clear()
        _STYLE_SAMPLE_CACHE[key] = (time.monotonic(), samples)
        return samples.get(style_id)


def style_options_html(content_project: str) -> str:
    """<option> list for the style picker: Auto first, then every catalogued style."""
    options = ['<option value="" selected>Auto — let the director decide (reuse or new)</option>']
    for style_id in catalogued_style_ids(content_project):
        options.append(f'<option value="{html.escape(style_id, quote=True)}">'
                       f'{html.escape(style_id)}</option>')
    return "".join(options)


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def next_video_id() -> str:
    ids = []
    for path in (ROOT / "videos").iterdir():
        match = re.match(r"^(\d+)_", path.name)
        if match:
            ids.append(int(match.group(1)))
    return f"{max(ids, default=0) + 1:03d}"


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def form_text(values: dict[str, list[str]], key: str, limit: int = 4_000) -> str:
    value = values.get(key, [""])[0].strip()
    if len(value) > limit:
        raise ValueError(f"{key} is too long (maximum {limit} characters).")
    return value


def music_provider_priority(value: object) -> list[str]:
    """Parse the panel's ordered provider chain and reject ambiguous launches."""
    raw = value if isinstance(value, list) else str(value or "").split(",")
    providers = [str(part).strip().lower() for part in raw if str(part).strip()]
    if not providers:
        raise ValueError("Choose at least one music provider.")
    if any(provider not in MUSIC_PROVIDERS for provider in providers):
        raise ValueError("Music providers must be Freesound, Mixkit, and/or Pixabay.")
    if len(set(providers)) != len(providers):
        raise ValueError("Music provider priority cannot contain duplicates.")
    return providers


def pid_is_live(pid: object) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        if Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()[2] == "Z":
            return False
        os.kill(pid, 0)
        return True
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return False


def terminate_job(job: dict) -> bool:
    """Signal a job's whole process group; True when something was actually signalled.

    Each stage runs as a child of the wrapper, and the wrapper is started with
    ``start_new_session=True``, so the group is the right unit: signalling only the parent
    leaves a provider stage running in the browser with nothing watching it. TERM first, so
    a stage can close its browser tab, then KILL what ignores it.
    """
    pid = job.get("pid")
    if not pid_is_live(pid):
        return False
    import signal

    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(os.getpgid(int(pid)), sig)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                os.kill(int(pid), sig)
            except (ProcessLookupError, PermissionError, OSError):
                return True
        for _ in range(20):
            if not pid_is_live(pid):
                return True
            time.sleep(0.1)
    return True


def monitor_process(job_id: str, process: subprocess.Popen) -> None:
    """Persist the real child exit code immediately, then reconcile its durable outputs."""
    if not hasattr(process, "wait"):
        return
    def wait_for_exit() -> None:
        returncode = process.wait()
        path = ROOT / "control_panel/jobs" / f"{job_id}.json"
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            if record.get("pid") == process.pid:
                record.update({"exit_code": returncode, "process_exited_at": utcnow()})
                write_json(path, record)
        except (OSError, ValueError):
            return
        reconcile_stuck_jobs_once()
    threading.Thread(target=wait_for_exit, daemon=True, name=f"job-{job_id[:8]}").start()


def watchers_for(jobs_dir: Path, video_id: object) -> list[dict]:
    """Every live Flow watcher attached to this episode."""
    found: list[dict] = []
    if video_id is None:
        return found
    for path in jobs_dir.glob("*.json"):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if (
            job.get("kind") == "flow_watcher"
            and str(job.get("video_id")) == str(video_id)
            and job.get("status") == "RUNNING"
        ):
            found.append(job)
    return found


def active_job(jobs_dir: Path) -> dict | None:
    """The episode currently being produced, if any.

    A Flow watcher does not count: it spends most of its life asleep and must not stand in
    the way of launching the next episode. It only runs the pipeline when Flow returns, and
    the launch lock covers that moment.
    """
    for path in jobs_dir.glob("*.json"):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if job.get("kind") == "flow_watcher":
            continue
        if job.get("status") == "RUNNING" and pid_is_live(job.get("pid")):
            return job
    return None


#: How often the Flow watcher re-probes, in seconds. Twenty minutes by default.
FLOW_WATCH_INTERVAL_SECONDS = int(os.getenv("YT_FLOW_WATCH_INTERVAL_SECONDS", "1200"))


def flow_watcher_alive(jobs_dir: Path, video_id: str) -> bool:
    """True when a watcher for this episode is already running."""
    for path in jobs_dir.glob("*.json"):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if (
            job.get("kind") == "flow_watcher"
            and str(job.get("video_id")) == str(video_id)
            and job.get("status") == "RUNNING"
            and pid_is_live(job.get("pid"))
        ):
            return True
    return False


def ensure_flow_watcher(jobs_dir: Path, episode: dict) -> dict | None:
    """Start one watcher job for a parked episode, unless one is already watching.

    The watcher is a control-panel job like any other, so the wait shows up in the runs
    table and can be stopped or deleted from the same page.
    """
    video_id = str(episode.get("video_id") or "")
    if not video_id or flow_watcher_alive(jobs_dir, video_id):
        return None
    project = ROOT / str(episode.get("project") or "")
    command_file = project / "pipeline" / "RESUME_COMMAND.json"
    command_file.parent.mkdir(parents=True, exist_ok=True)
    command_file.write_text(
        json.dumps(pipeline_command(episode), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    job_id = str(uuid.uuid4())
    record = {
        "schema_version": 5,
        "kind": "flow_watcher",
        "job_id": job_id,
        "status": "RUNNING",
        "created_at": utcnow(),
        "video_id": video_id,
        "topic": episode.get("topic"),
        "project": episode.get("project"),
        "watching_job_id": episode.get("job_id"),
        "interval_seconds": FLOW_WATCH_INTERVAL_SECONDS,
    }
    command = [
        sys.executable, "-u", "scripts/flow_availability_watcher.py", str(project),
        "--command-file", str(command_file),
        "--interval-seconds", str(FLOW_WATCH_INTERVAL_SECONDS),
    ]
    log = jobs_dir / f"{job_id}.log"
    handle = log.open("w", encoding="utf-8")
    try:
        process = subprocess.Popen(
            command, cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT, start_new_session=True
        )
    except OSError as exc:
        record.update({"status": "FAILED", "completed_at": utcnow(), "error": str(exc)})
        write_json(jobs_dir / f"{job_id}.json", record)
        return record
    finally:
        if not handle.closed:
            handle.close()
    record.update({"pid": process.pid, "command": command, "started_at": utcnow()})
    write_json(jobs_dir / f"{job_id}.json", record)
    monitor_process(job_id, process)
    return record


def reconcile_stuck_jobs_once() -> None:
    """Mark defunct RUNNING jobs as FAILED without requiring a page load (§81, permanent anti-stuck)."""
    jobs_dir = ROOT / "control_panel" / "jobs"
    for path in jobs_dir.glob("*.json"):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
            if job.get("status") != "RUNNING" or not isinstance(job.get("pid"), int):
                continue
            if pid_is_live(job["pid"]):
                continue
            log = jobs_dir / f"{job.get('job_id')}.log"
            text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
            # A Flow outage is Google's, not this episode's. The run parks with everything
            # else finished, so it becomes WAITING_FOR_FLOW and a watcher job is started to
            # continue it when Flow answers again — not FAILED.
            if job.get("exit_code") == 4 or "FLOW_CLIPS_PENDING" in text:
                job["status"] = "WAITING_FOR_FLOW"
                job["completed_at"] = utcnow()
                write_json(path, job)
                try:
                    ensure_flow_watcher(jobs_dir, job)
                except Exception as exc:  # a watcher failure must not wedge the reconciler
                    job["watcher_error"] = f"{type(exc).__name__}: {exc}"
                    write_json(path, job)
                continue
            if job.get("exit_code") not in (None, 0):
                job["status"] = "FAILED"
            # consider success only if pipeline explicitly reported PASS
            elif "FULL VIDEO PIPELINE: PASS" in text or "QH CORE STAGES DONE" in text or "FULL QH PIPELINE: PASS" in text or "COMPLETION PIPELINE: PASS" in text or "QH PIPELINE BODY IMAGES" in text:
                # body images done but wrapper may have failed later — still mark DONE only if final reports exist
                # check for final.mp4 QC pass
                try:
                    proj = ROOT / str(job.get("project", ""))
                    final_state = {}
                    try:
                        final_state = json.loads((proj / "pipeline/FINALIZATION_RUNTIME_STATE.json").read_text(encoding="utf-8"))
                    except (OSError, ValueError):
                        pass
                    final_ready = (
                        final_state.get("status") == "DONE"
                        and (proj / "assets/renders/polished.mp4").is_file()
                        and (proj / "render/QC_REPORT_polished.json").is_file()
                    )
                    legacy_ready = (proj / "assets/renders/final.mp4").is_file() and (proj / "render/QC_REPORT.json").is_file()
                    if final_ready or ("FULL VIDEO PIPELINE: PASS" in text and legacy_ready):
                        job["status"] = "DONE"
                    else:
                        job["status"] = "FAILED"
                except Exception:
                    job["status"] = "FAILED"
            else:
                job["status"] = "FAILED"
            job["completed_at"] = utcnow()
            pending = job.get("pending_revision") if isinstance(job.get("pending_revision"), dict) else None
            if pending:
                revision_path = ROOT / str(job.get("project") or "") / "pipeline" / "revisions" / str(pending.get("revision_id")) / "REVISION.json"
                revision = dict(pending)
                revision.update({"status": job["status"], "completed_at": job["completed_at"]})
                try:
                    write_json(revision_path, revision)
                except OSError:
                    pass
                if job["status"] == "DONE":
                    job.pop("pending_revision", None)
                else:
                    job["pending_revision"] = revision
            # preserve original pid for audit but mark completed
            write_json(path, job)
            # also update launch request
            try:
                proj = ROOT / str(job.get("project", ""))
                req = proj / "launch" / "LAUNCH_REQUEST.json"
                if req.is_file():
                    rq = json.loads(req.read_text(encoding="utf-8"))
                    rq["status"] = job["status"]
                    rq["completed_at"] = job["completed_at"]
                    write_json(req, rq)
            except Exception:
                pass
        except Exception:
            continue

def reconcile_scheduled_resumes() -> None:
    for path in (ROOT / "control_panel" / "jobs").glob("*.json"):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
            if job.get("status") != "SCHEDULED" or not job.get("image_limit_schedule"):
                continue
            project = ROOT / str(job["project"])
            subprocess.run([sys.executable, "scripts/schedule_image_limit_resume.py", str(project), "--no-notify"], cwd=ROOT, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (KeyError, OSError, subprocess.SubprocessError, json.JSONDecodeError):
            continue

def pipeline_command(record: dict) -> list[str]:
    """The command that runs one episode. Launch and resume must not diverge (§78)."""
    content_project = str(record.get("content_project") or DEFAULT_CONTENT_PROJECT)
    project = ROOT / str(record["project"])
    creative_brief = ROOT / str(record["creative_brief"])
    voice_profile = ROOT / str(record["voice_profile"])
    music_providers = ",".join(music_provider_priority(record.get("music_providers") or record.get("music_provider") or "mixkit"))
    try:
        is_bookworld = load_content_project(content_project).is_question_harvest
    except RuntimeError:
        is_bookworld = False
    if is_bookworld:
        command = [
            sys.executable, "-u", "scripts/run_full_video_pipeline_qh_wrapper.py",
            "--topic", str(record["topic"]),
            "--video-id", str(record["video_id"]),
            "--content-project", content_project,
            "--creative-brief", str(creative_brief),
            "--voice-profile", str(voice_profile),
            "--aspect-ratio", str(record.get("aspect_ratio") or "9:16"),
            "--music-providers", music_providers,
            "--publish",
        ] + (["--commit"] if record.get("commit_artifacts") else []) \
          + ([] if record.get("telegram_low_size", True) else ["--no-telegram-low-size"]) \
          + (["--telegram-original"] if record.get("telegram_original") else [])
        revision = record.get("pending_revision") or {}
        if revision.get("regenerate_beats"):
            command += ["--regenerate-beats", ",".join(str(x) for x in revision["regenerate_beats"])]
        if revision.get("feedback_path"):
            command += ["--beat-feedback-json", str(ROOT / str(revision["feedback_path"]))]
        return command
    command = [
        sys.executable, "-u", "scripts/run_full_video_pipeline.py",
        "--content-project", content_project,
        "--topic", str(record["topic"]),
        "--video-id", str(record["video_id"]),
        "--min-duration-seconds", str(record.get("duration_min_seconds") or 40),
        "--max-duration-seconds", str(record.get("duration_max_seconds") or 60),
        "--aspect-ratio", str(record.get("aspect_ratio") or "9:16"),
        "--voice-profile", str(voice_profile),
        "--creative-brief", str(creative_brief),
        "--music-providers", music_providers,
    ] + ([] if record.get("telegram_low_size", True) else ["--no-telegram-low-size"]) \
      + (["--telegram-original"] if record.get("telegram_original") else []) \
      + (["--commit"] if record.get("commit_artifacts") else ["--no-commit"])
    revision = record.get("pending_revision") or {}
    if revision.get("regenerate_beats"):
        command += ["--regenerate-beats", ",".join(str(x) for x in revision["regenerate_beats"])]
    if revision.get("feedback_path"):
        command += ["--beat-feedback-json", str(ROOT / str(revision["feedback_path"]))]
    if revision.get("kind") == "config":
        command.append("--config-revision")
    return command


def provider_status() -> dict:
    """Ordak's own view of each provider session, for the badges (§9.2).

    An unreachable Ordak is reported as unreachable rather than as "all fine": the panel
    must never imply a provider is ready when nothing confirmed it.
    """
    with PROVIDER_STATUS_LOCK:
        age = time.monotonic() - float(PROVIDER_STATUS_CACHE["at"])
        if PROVIDER_STATUS_CACHE["base"] == ORDAK_BASE_URL and age < 4:
            return dict(PROVIDER_STATUS_CACHE["value"])
        try:
            import httpx

            response = httpx.get(f"{ORDAK_BASE_URL}/api/diagnostics", timeout=6, trust_env=False)
            data = response.json() if response.status_code == 200 else {}
            if response.status_code != 200:
                raise RuntimeError(f"Ordak diagnostics returned HTTP {response.status_code}")
        except Exception as exc:
            result = {
                "reachable": False,
                "error": f"{type(exc).__name__}: {exc}"[:160],
                "chrome_running": None,
                "providers": {name: {"state": "unknown", "logged_in": None, "tabs": 0} for name in PROVIDERS},
            }
        else:
            sessions = data.get("provider_sessions") or {}
            result = {
                "reachable": True,
                "error": "",
                "chrome_running": bool(data.get("chrome_running")),
                "providers": {
                    name: {
                        "state": str((sessions.get(name) or {}).get("login_state") or "unknown"),
                        "logged_in": (sessions.get(name) or {}).get("logged_in"),
                        "tabs": len((sessions.get(name) or {}).get("open_tabs") or []),
                    }
                    for name in PROVIDERS
                },
            }
        PROVIDER_STATUS_CACHE.update({"at": time.monotonic(), "base": ORDAK_BASE_URL, "value": result})
        return dict(result)


def pipeline_state_of(record: dict) -> dict:
    """The orchestrator's own state for a job, when it has written one (§81)."""
    project = ROOT / str(record.get("project") or "")
    state: dict = {}
    for path in (
        project / "pipeline/QH_RUNTIME_STATE.json",
        project / "pipeline/FULL_PIPELINE_RUNTIME_STATE.json",
    ):
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
            break
        except (OSError, ValueError, TypeError):
            continue
    if not state:
        return {}
    graph_nodes = graph_for(project).get("nodes") or []
    excluded: set[str] = set()
    if not bool((record.get("motion") or {}).get("enabled", True)): excluded.add("motion_director")
    if not bool((record.get("sfx") or {}).get("enabled", False)): excluded.update(("sfx_plan", "sfx_acquire"))
    if not record.get("commit_artifacts"): excluded.add("git_commit_push")
    if not record.get("telegram_low_size", True): excluded.add("telegram_compress")
    visible = [node for node in graph_nodes if node.get("id") not in excluded]
    running = [str(node["id"]) for node in visible if node.get("status") == "RUNNING"]
    is_live = bool(record.get("_live")) or bool(running)
    return {
        # The PID is the source of truth during a direct resume: QH's durable
        # state is intentionally only checkpointed at stage boundaries and can
        # still contain the prior failure for a short time.
        "pipeline_state": "RUNNING" if is_live else record.get("status") or state.get("pipeline_state"),
        "stage_count": len(visible),
        "done": sum(1 for node in visible if node.get("status") in ("DONE", "REUSED")),
        "running": running[0] if running else None,
    }


def motion_status_of(record: dict) -> dict:
    """Concise run-view status derived from committed machine-readable artifacts."""
    project = ROOT / str(record.get("project") or "")
    configured = record.get("motion") if isinstance(record.get("motion"), dict) else {}
    result: dict[str, Any] = {
        "enabled": bool(configured.get("enabled", True)),
        "style": str(configured.get("style", "dynamic")),
        "pace": str(configured.get("pace", "fast")),
        "plan_status": "pending",
    }
    if not result["enabled"]:
        result["plan_status"] = "disabled"; return result
    try:
        plan = json.loads((project / "motion" / "MOTION_PLAN.json").read_text(encoding="utf-8"))
        result["plan_status"] = "ready"
        result["micro_shots"] = sum(len(beat.get("micro_shots") or []) for beat in plan.get("beats") or [])
    except (OSError, ValueError, TypeError):
        return result
    try:
        qc = json.loads((project / "motion" / "MOTION_QC.json").read_text(encoding="utf-8"))
        result["qc"] = "PASS" if qc.get("passed") else "WARN"
    except (OSError, ValueError, TypeError):
        result["qc"] = "pending"
    return result


def external_pipeline_pid(project: Path) -> int | None:
    """Return the live direct-runner PID for an externally launched episode, if any."""
    needle = str(project.relative_to(ROOT))
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            command = (proc / "cmdline").read_text(encoding="utf-8", errors="replace").replace("\0", " ")
        except OSError:
            continue
        if (
            ("run_question_harvest_pipeline.py" in command or "run_full_video_pipeline_qh_wrapper.py" in command or "run_full_video_pipeline.py" in command)
            and needle in command
        ):
            return int(proc.name)
    return None


def external_pipeline_records(jobs_dir: Path, known_projects: set[str]) -> list[dict]:
    """Expose active pipelines started outside the panel as read-only live rows.

    Operators and recovery tooling can legitimately invoke a runner from the terminal.
    Those runs still persist a QH runtime state, but historically became invisible because
    the panel only listed its own launch-record files.  Discovering them here preserves a
    single truthful monitoring view without taking ownership of their process or log file.
    """
    records: list[dict] = []
    videos = ROOT / "videos"
    if not videos.is_dir():
        return records
    for project in videos.iterdir():
        if not project.is_dir():
            continue
        relative_project = str(project.relative_to(ROOT))
        if relative_project in known_projects:
            continue
        state = {}
        for state_path in (
            project / "pipeline/QH_RUNTIME_STATE.json",
            project / "pipeline/FULL_PIPELINE_RUNTIME_STATE.json",
        ):
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
                break
            except (OSError, ValueError):
                continue
        if not state:
            continue
        pipeline_state = str(state.get("pipeline_state") or "").upper()
        live_pid = external_pipeline_pid(project)
        # Completed/old manual runs do not need duplicate rows.  A failed run stays
        # visible as well: it is the actionable counterpart of a live run.
        if live_pid is None and pipeline_state not in {
            "RUNNING", "FAILED", "FAILED_DOWNLOAD", "FAILED_UPLOAD", "FAILED_UI_CHANGED",
            "FAILED_VALIDATION", "PAUSED_LOGIN_REQUIRED", "PAUSED_MANUAL_VERIFICATION",
            "PAUSED_CREDITS",
        }:
            continue
        video_id = str(state.get("video_id") or project.name.split("_", 1)[0])
        records.append(
            {
                "job_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"external-panel:{relative_project}")),
                "kind": "external_episode",
                "video_id": video_id,
                "content_project": str(state.get("content_project") or ("q_station" if (project / "pipeline/QH_RUNTIME_STATE.json").is_file() else DEFAULT_CONTENT_PROJECT)),
                "topic": str(state.get("topic") or project.name),
                # A resumed direct runner may retain the prior terminal state until it
                # reaches its next durable checkpoint. The live PID is authoritative.
                "status": "RUNNING" if live_pid is not None or pipeline_state == "RUNNING" else "FAILED",
                "created_at": state.get("created_at"),
                "project": relative_project,
                "external": True,
                "pid": live_pid,
                "_live": live_pid is not None or pipeline_state == "RUNNING",
                "_pipeline": pipeline_state_of({"project": relative_project}),
                "_resumable": False,
                "_stoppable": False,
                "_flow_pending": flow_pending_of({"project": relative_project}),
            }
        )
    return records


def job_records(jobs_dir: Path, limit: int = 20) -> list[dict]:
    """Newest jobs first, with the derived fields the page and the API both need."""
    records: list[dict] = []
    paths = sorted(jobs_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    known_projects: set[str] = set()
    # Archived rows remain hidden even when their project has a failed runtime state that
    # would otherwise be rediscovered as an external run.
    for path in (jobs_dir / "archived").glob("*.json"):
        try:
            archived = json.loads(path.read_text(encoding="utf-8"))
            if archived.get("project"):
                known_projects.add(str(archived["project"]))
        except (OSError, ValueError):
            continue
    for path in paths:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        kind = str(record.get("kind") or "episode")
        project = str(record.get("project") or "")
        if project:
            known_projects.add(project)
        live = pid_is_live(record.get("pid"))
        record["kind"] = kind
        record["_live"] = live
        record["_pipeline"] = pipeline_state_of(record) if kind == "episode" else {}
        # A watcher is never resumed: it is stopped or deleted, and the episode it watches
        # is what gets resumed.
        record["_resumable"] = (
            kind == "episode" and not live and bool(record.get("project"))
        )
        record["_stoppable"] = live
        record["_flow_pending"] = flow_pending_of(record) if kind == "episode" else {}
        records.append(record)
    records.extend(external_pipeline_records(jobs_dir, known_projects))
    records.sort(key=lambda record: str(record.get("created_at") or ""), reverse=True)
    return records[:limit]


def flow_pending_of(record: dict) -> dict:
    """What the episode is still waiting on Flow for, if anything."""
    project = record.get("project")
    if not project:
        return {}
    path = ROOT / str(project) / "pipeline" / "FLOW_PENDING_STATE.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def start_stuck_job_reconciler(interval: int = 30) -> None:
    """Background thread to periodically reconcile stuck jobs — permanent anti-hang (§81)."""
    def loop() -> None:
        while True:
            try:
                reconcile_stuck_jobs_once()
            except Exception:
                pass
            import time
            time.sleep(interval)
    t = threading.Thread(target=loop, daemon=True, name="stuck-job-reconciler")
    t.start()


class Handler(BaseHTTPRequestHandler):
    server_version = "VideoControlPanel/2.0"

    def version_string(self) -> str:
        return self.server_version

    @property
    def jobs_dir(self) -> Path:
        return ROOT / "control_panel" / "jobs"

    def send_html(self, status: int, body: str) -> None:
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        if getattr(self, "command", "GET") != "HEAD":
            self.wfile.write(encoded)

    def send_json(self, status: int, payload: dict) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Length", str(len(encoded)))
        try:
            self.end_headers()
            if getattr(self, "command", "GET") != "HEAD":
                self.wfile.write(encoded)
        except (BrokenPipeError, ConnectionResetError):
            return

    def send_notice(self, status: int, message: str, **payload: object) -> None:
        """Return compact JSON to the Studio while retaining HTML form compatibility."""
        headers = getattr(self, "headers", None)
        if headers and "application/json" in str(headers.get("Accept") or ""):
            key = "message" if status < 400 else "error"
            self.send_json(status, {key: message, **payload})
        else:
            self.send_html(status, self.page(message))

    def websocket_signature(self, job_id: str | None = None) -> str:
        """A cheap, read-only fingerprint of state visible in one Studio workspace.

        The websocket deliberately observes durable runner files rather than subscribing to
        or controlling runner processes.  That keeps a browser connection incapable of
        pausing, restarting, or otherwise affecting an active pipeline.
        """
        if job_id:
            resolved = self.project_for_job(job_id)
            if not resolved:
                return "missing"
            record, project = resolved
            files = [
                project / "pipeline/QH_RUNTIME_STATE.json",
                project / "visual_pipeline/RUNTIME_STATE.json",
                project / "pipeline/FULL_PIPELINE_RUNTIME_STATE.json",
                project / "pipeline/FINALIZATION_RUNTIME_STATE.json",
                project / "pipeline/WRAPPER_RUNTIME_STATE.json",
                self.jobs_dir / f"{job_id}.json",
                self.jobs_dir / f"{job_id}.log",
            ]
            state = [(str(path), path.stat().st_mtime_ns, path.stat().st_size) for path in files if path.is_file()]
            graph = graph_for(project)
            state.extend(
                (node.get("id"), node.get("status"), tuple((artifact.get("path"), artifact.get("updated_at")) for artifact in node.get("artifacts") or []))
                for node in graph.get("nodes") or []
            )
            state.append(("live", pid_is_live(record.get("pid"))))
        else:
            state = []
            for path in sorted(self.jobs_dir.glob("*.json")):
                try:
                    state.append((path.name, path.stat().st_mtime_ns, path.stat().st_size))
                    record = json.loads(path.read_text(encoding="utf-8"))
                    project = ROOT / str(record.get("project") or "")
                    state.append((path.name, pipeline_state_of(record)))
                    for relative in ("pipeline/QH_RUNTIME_STATE.json", "visual_pipeline/RUNTIME_STATE.json", "pipeline/FULL_PIPELINE_RUNTIME_STATE.json"):
                        runtime = project / relative
                        if runtime.is_file():
                            state.append((path.name, relative, runtime.stat().st_mtime_ns, runtime.stat().st_size))
                except OSError:
                    continue
                except (ValueError, TypeError):
                    continue
        return hashlib.sha256(repr(state).encode("utf-8")).hexdigest()

    def handle_websocket(self, query: dict[str, list[str]]) -> None:
        """Send small change notifications; clients fetch their normal JSON snapshots.

        This is intentionally dependency-free so the service can be upgraded in place.
        It implements the server-to-client half of RFC 6455 and accepts no commands.
        """
        key = self.headers.get("Sec-WebSocket-Key", "")
        upgrade = self.headers.get("Upgrade", "").lower()
        try:
            valid_key = len(base64.b64decode(key.encode("ascii"), validate=True)) == 16
        except (ValueError, UnicodeEncodeError):
            valid_key = False
        if upgrade != "websocket" or not valid_key:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "WebSocket upgrade required"})
            return
        requested_job = (query.get("job_id") or [""])[0]
        job_id = requested_job if JOB_ID_RE.fullmatch(requested_job) else None
        if requested_job and not job_id:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid job id"})
            return
        accept = base64.b64encode(
            hashlib.sha1(f"{key}258EAFA5-E914-47DA-95CA-C5AB0DC85B11".encode("ascii")).digest()
        ).decode("ascii")
        self.send_response(HTTPStatus.SWITCHING_PROTOCOLS)
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", accept)
        self.end_headers()
        self.close_connection = True

        def send_event(event: dict) -> None:
            encoded = json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            # Server frames are never masked. Snapshot notifications are deliberately tiny.
            header = bytes([0x81])
            if len(encoded) < 126:
                header += bytes([len(encoded)])
            else:  # The current payload is tiny; retain correct framing if it grows.
                header += bytes([126]) + len(encoded).to_bytes(2, "big")
            self.wfile.write(header + encoded)
            self.wfile.flush()

        signature = self.websocket_signature(job_id)
        last_heartbeat = time.monotonic()
        try:
            send_event({"type": "connected", "scope": "run" if job_id else "dashboard", "at": utcnow()})
            while True:
                time.sleep(1)
                latest = self.websocket_signature(job_id)
                if latest != signature:
                    signature = latest
                    send_event({"type": "changed", "scope": "run" if job_id else "dashboard", "at": utcnow()})
                    last_heartbeat = time.monotonic()
                elif time.monotonic() - last_heartbeat >= 20:
                    send_event({"type": "heartbeat", "at": utcnow()})
                    last_heartbeat = time.monotonic()
        except (BrokenPipeError, ConnectionResetError, OSError):
            return

    def project_for_job(self, job_id: str) -> tuple[dict, Path] | None:
        """Resolve a panel job or a deterministic read-only external run."""
        path = self.jobs_dir / f"{job_id}.json"
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            project = (ROOT / str(record.get("project") or "")).resolve()
            videos_root = (ROOT / "videos").resolve()
            project.relative_to(videos_root)
            if project == videos_root or not project.is_dir():
                raise ValueError("Job project is not an episode directory.")
            return record, project
        except (OSError, ValueError, TypeError):
            pass
        # Read-only terminal/manual runs use a deterministic id and do not have a panel job
        # record. They should still open from the dashboard instead of leading to a 404.
        videos = ROOT / "videos"
        for project in videos.iterdir() if videos.is_dir() else []:
            if not project.is_dir():
                continue
            relative_project = str(project.relative_to(ROOT))
            external_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"external-panel:{relative_project}"))
            if external_id != job_id:
                continue
            state = {}
            try: state = json.loads((project / "pipeline/QH_RUNTIME_STATE.json").read_text(encoding="utf-8"))
            except (OSError, ValueError): pass
            return ({"job_id": job_id, "video_id": state.get("video_id") or project.name.split("_", 1)[0], "topic": state.get("topic") or project.name, "status": state.get("pipeline_state") or "UNKNOWN", "project": relative_project, "external": True}, project.resolve())
        return None

    def serve_style_preview(self, content_project: str, style_id: str, kind: str) -> None:
        """Serve a small JPEG thumbnail for a style anchor or a representative beat."""
        if kind not in {"anchor", "sample"} or not STYLE_ID_RE.fullmatch(style_id):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            resolved_project = load_content_project(content_project)
        except RuntimeError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_project = resolved_project.project_id
        catalog_root = resolved_project.root / "world_styles"
        try:
            catalog = json.loads((catalog_root / "CATALOG.json").read_text(encoding="utf-8"))
            entry = next(item for item in catalog.get("styles") or [] if isinstance(item, dict) and item.get("style_id") == style_id)
            target = (catalog_root / str(entry.get("anchor") or "")).resolve() if kind == "anchor" else style_sample_for(style_id, content_project)
            if target is None:
                raise ValueError("No sample")
            if kind == "anchor":
                target.relative_to(catalog_root.resolve())
            if not target.is_file() or target.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
                raise ValueError("Unsafe preview target")
        except (OSError, ValueError, StopIteration):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        cache = ROOT / "control_panel" / "style_previews"
        try:
            cache.mkdir(parents=True, exist_ok=True)
            thumbnail, _ = build_preview(target, cache, style=True)
            payload = thumbnail.read_bytes()
        except (OSError, ValueError):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "private, no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        try:
            if getattr(self, "command", "GET") != "HEAD":
                self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            return

    def preview_artifact(self, project: Path, target: Path) -> tuple[Path, str]:
        """Return a deliberately low-bandwidth derivative; masters never leave the host.

        Previews are cached per source mtime/size.  A 720p master therefore cannot be inferred
        from the UI endpoint even when an operator opens the media element in a new tab.
        """
        cache = project / ".panel_previews"
        cache.resolve().relative_to(project.resolve())
        return build_preview(target, cache)

    def serve_artifact(self, project: Path, relative: str) -> None:
        """Serve only a low-quality derivative or text metadata, never the original media."""
        try:
            target = (project / relative).resolve()
            target.relative_to(project)
        except ValueError:
            self.send_error(HTTPStatus.FORBIDDEN); return
        if not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND); return
        try:
            target, content_type = self.preview_artifact(project, target)
        except (ValueError, OSError, subprocess.SubprocessError):
            self.send_error(HTTPStatus.NOT_FOUND); return
        size = target.stat().st_size
        start, end, status = 0, max(0, size - 1), HTTPStatus.OK
        requested = self.headers.get("Range", "")
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", requested.strip()) if requested else None
        if match and size:
            if match.group(1):
                start = int(match.group(1)); end = int(match.group(2)) if match.group(2) else end
            elif match.group(2):
                start = max(0, size - int(match.group(2)))
            if start >= size or end < start:
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.send_header("Content-Range", f"bytes */{size}"); self.end_headers(); return
            end, status = min(end, size - 1), HTTPStatus.PARTIAL_CONTENT
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1 if size else 0))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        if status == HTTPStatus.PARTIAL_CONTENT:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Cache-Control", "private, no-cache")
        try:
            self.end_headers()
            if getattr(self, "command", "GET") == "HEAD":
                return
            with target.open("rb") as handle:
                handle.seek(start)
                remaining = end - start + 1
                while remaining > 0:
                    chunk = handle.read(min(64 * 1024, remaining))
                    if not chunk: break
                    self.wfile.write(chunk); remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            return

    def serve_studio(self, route: str) -> None:
        """Serve the locally-built React application; history routes fall back to index."""
        dist = ROOT / "control_panel" / "dist"
        candidate = (dist / route.lstrip("/")).resolve() if route not in ("/", "") else dist / "index.html"
        try:
            candidate.relative_to(dist.resolve())
        except ValueError:
            candidate = dist / "index.html"
        if not candidate.is_file():
            candidate = dist / "index.html"
        if not candidate.is_file():
            self.send_html(HTTPStatus.SERVICE_UNAVAILABLE, "<p>Studio UI is not built. Run <code>npm run build</code> in control_panel/ui.</p>"); return
        content = candidate.read_bytes(); kind = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK); self.send_header("Content-Type", kind); self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store" if candidate.name == "index.html" else "public, max-age=31536000, immutable")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; media-src 'self' blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        try:
            self.end_headers()
            if getattr(self, "command", "GET") != "HEAD":
                self.wfile.write(content)
        except (BrokenPipeError, ConnectionResetError):
            return

    def read_json_payload(self, limit: int = 100_000) -> dict:
        size = int(self.headers.get("Content-Length", "0"))
        if size <= 0 or size > limit:
            raise ValueError("Request body is empty or too large.")
        value = json.loads(self.rfile.read(size).decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("Request body must be a JSON object.")
        return value

    def handle_regeneration_preview(self) -> None:
        try:
            payload = self.read_json_payload()
            job_id = str(payload.get("job_id") or "")
            roots = payload.get("node_ids") or [payload.get("node_id")]
            if not JOB_ID_RE.fullmatch(job_id) or not isinstance(roots, list) or not all(isinstance(item, str) and item for item in roots):
                raise ValueError("Choose at least one valid node.")
            resolved = self.project_for_job(job_id)
            if not resolved:
                self.send_json(HTTPStatus.NOT_FOUND, {"error": "Unknown run."}); return
            record, project = resolved
            plan = regeneration_plan(project, roots)
            graph = graph_for(project)
            summary = {node["id"]: {key: node.get(key) for key in ("title", "kind", "phase", "status")} for node in graph["nodes"]}
            self.send_json(HTTPStatus.OK, {**plan, "nodes": summary, "can_start": not record.get("external") and active_job(self.jobs_dir) is None, "read_only": bool(record.get("external")), "run_status": record.get("status")})
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc) or "Invalid regeneration request."})

    def start_regeneration(self, record: dict, project: Path, roots: list[str], feedback: str = "", kind: str = "node") -> tuple[dict, subprocess.Popen]:
        """Archive an exact DAG branch and start it, rolling back if spawn fails."""
        plan = regeneration_plan(
            project,
            roots,
            include_disabled=kind == "config",
            settings=record if kind == "config" else None,
            skip_disabled_descendants=kind == "config",
        )
        revision_id = str(uuid.uuid4())
        folder = project / "pipeline" / "revisions" / revision_id
        folder.mkdir(parents=True, exist_ok=False)
        feedback_path = folder / "feedback.json"
        beat_feedback = {str(int(root[-3:])): feedback for root in roots if root.startswith("beat_image_") and feedback}
        if beat_feedback:
            write_json(feedback_path, beat_feedback)
        archived: list[str] = []
        state_before: dict[Path, dict] = {}
        state_paths = [project / "pipeline/QH_RUNTIME_STATE.json", project / "visual_pipeline/RUNTIME_STATE.json"]
        try:
            for relative in invalidation_paths(project, plan["affected_nodes"]):
                source, destination = project / relative, folder / "previous" / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(source, destination)
                archived.append(relative)
            for state_path in state_paths:
                state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else {}
                if not state:
                    continue
                state_before[state_path] = json.loads(json.dumps(state))
                for node_id in plan["affected_nodes"]:
                    stage_id = {
                        "visual_plan": "visual_beats",
                        "episode_world_design": "world_design",
                    }.get(node_id, node_id)
                    (state.get("stages") or {}).pop(stage_id, None)
                    if node_id.startswith("beat_image_"):
                        (state.get("beats") or {}).pop(str(int(node_id[-3:])), None)
                        (state.get("beats") or {}).pop(node_id[-3:], None)
                write_json(state_path, state)
            # Explicit beat IDs are only needed for provider-prompt feedback. Continuity
            # descendants have already had their artifacts archived and therefore rebuild
            # naturally. Passing every old descendant after a visual-plan rewrite could name
            # beats that no longer exist in the newly generated plan.
            regenerate_beats = [int(node[-3:]) for node in roots if node.startswith("beat_image_")]
            revision = {
                "schema_version": 2, "revision_id": revision_id, "kind": kind,
                "created_at": utcnow(), "roots": roots, "affected_nodes": plan["affected_nodes"],
                "reused_nodes": plan["reused_nodes"], "skipped_nodes": plan.get("skipped_nodes", []), "archived_artifacts": archived,
                "regenerate_beats": regenerate_beats, "feedback": feedback, "status": "QUEUED",
            }
            if beat_feedback:
                revision["feedback_path"] = str(feedback_path.relative_to(ROOT))
            write_json(folder / "REVISION.json", revision)
            record["pending_revision"] = revision
            command = pipeline_command(record)
            log = self.jobs_dir / f"{record['job_id']}.log"
            handle = log.open("a", encoding="utf-8")
            handle.write(f"\n=== {kind} revision {revision_id[:8]} roots={','.join(roots)} at {utcnow()} ===\n")
            handle.flush()
            try:
                process = subprocess.Popen(command, cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT, start_new_session=True)
            finally:
                handle.close()
        except Exception as exc:
            for relative in reversed(archived):
                archived_path, original = folder / "previous" / relative, project / relative
                if archived_path.is_file() and not original.exists():
                    original.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(archived_path, original)
            for state_path, state in state_before.items():
                write_json(state_path, state)
            failed = {"schema_version": 2, "revision_id": revision_id, "kind": kind, "created_at": utcnow(), "roots": roots, "status": "FAILED_TO_START", "error": f"{type(exc).__name__}: {exc}"}
            write_json(folder / "REVISION.json", failed)
            raise
        revision.update({"status": "RUNNING", "started_at": utcnow(), "pid": process.pid})
        write_json(folder / "REVISION.json", revision)
        record["pending_revision"] = revision
        record.update({"status": "RUNNING", "pid": process.pid, "command": command, "resumed_at": utcnow()})
        record.pop("completed_at", None)
        write_json(self.jobs_dir / f"{record['job_id']}.json", record)
        monitor_process(str(record["job_id"]), process)
        return revision, process

    def handle_regeneration(self) -> None:
        try:
            payload = self.read_json_payload()
            job_id = str(payload.get("job_id") or "")
            roots = payload.get("node_ids") or [payload.get("node_id")]
            feedback = str(payload.get("feedback") or "").strip()
            if len(feedback) > 4_000 or not JOB_ID_RE.fullmatch(job_id) or not isinstance(roots, list) or not all(isinstance(item, str) and item for item in roots):
                raise ValueError("Choose valid nodes and keep feedback below 4,000 characters.")
            resolved = self.project_for_job(job_id)
            if not resolved:
                self.send_json(HTTPStatus.NOT_FOUND, {"error": "Unknown run."}); return
            if resolved[0].get("external"):
                self.send_json(HTTPStatus.CONFLICT, {"error": "Externally started runs are read-only in Studio."}); return
            with LAUNCH_LOCK:
                if active_job(self.jobs_dir) is not None:
                    self.send_json(HTTPStatus.CONFLICT, {"error": "Another episode is running."}); return
                revision, _ = self.start_regeneration(*resolved, roots, feedback)
            self.send_json(HTTPStatus.ACCEPTED, {"revision": revision, "status": "RUNNING"})
        except (ValueError, KeyError, TypeError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc) or "Invalid regeneration request."})

    def handle_revision(self) -> None:
        """Compatibility alias for the original beat-only endpoint."""
        self.handle_regeneration()

    def handle_config_revision(self) -> None:
        """Re-run an episode with a versioned configuration delta and DAG invalidation."""
        try:
            size = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(size).decode("utf-8")) if 0 < size <= 100_000 else {}
            job_id = str(payload.get("job_id") or "")
            config = payload.get("config") or {}
            brief, voice, launch = config.get("creative_brief"), config.get("voice_profile"), config.get("launch")
            values = config.get("values")
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Configuration payload is invalid."}); return
        if not JOB_ID_RE.fullmatch(job_id) or (
            not isinstance(values, dict) and not all(isinstance(x, dict) for x in (brief, voice, launch))
        ):
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "All configuration sections must be JSON objects."}); return
        if not isinstance(values, dict) and any(key in brief and not isinstance(brief[key], dict) for key in ("_qh", "_motion", "_sfx", "_subtitle")):
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Nested _qh, _motion, _sfx, and _subtitle settings must be JSON objects."}); return
        try:
            if not isinstance(values, dict) and ("music_providers" in launch or "music_provider" in launch):
                music_provider_priority(launch.get("music_providers") or launch.get("music_provider"))
            if not isinstance(values, dict) and launch.get("aspect_ratio") not in (None, "9:16", "16:9"):
                raise ValueError("Aspect ratio must be 9:16 or 16:9.")
            if not isinstance(values, dict):
                for key in ("commit_artifacts", "telegram_low_size", "telegram_original"):
                    if key in launch and not isinstance(launch[key], bool):
                        raise ValueError(f"{key} must be a JSON boolean.")
        except (TypeError, ValueError) as exc:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)}); return
        resolved = self.project_for_job(job_id)
        if not resolved: self.send_json(HTTPStatus.NOT_FOUND, {"error": "Unknown run."}); return
        record, project = resolved
        if record.get("external"):
            self.send_json(HTTPStatus.CONFLICT, {"error": "Externally started runs are read-only in Studio."}); return
        try:
            previous_brief = json.loads((ROOT / str(record["creative_brief"])).read_text(encoding="utf-8"))
            previous_voice = json.loads((ROOT / str(record["voice_profile"])).read_text(encoding="utf-8"))
        except (OSError, ValueError, KeyError) as exc:
            self.send_json(HTTPStatus.CONFLICT, {"error": f"This run's frozen configuration is unavailable: {exc}"}); return
        if isinstance(values, dict):
            try:
                roots, brief, voice, launch, changed_fields = config_roots(
                    record, previous_brief, previous_voice, values
                )
            except ValueError as exc:
                self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)}); return
            self.commit_config_revision(
                record, project, roots, brief, voice, launch, changed_fields
            )
            return
        revision_id = str(uuid.uuid4()); folder = project / "launch" / "config_revisions" / revision_id; folder.mkdir(parents=True, exist_ok=True)
        write_json(folder / "CREATIVE_BRIEF.json", brief); write_json(folder / "VOICE_PROFILE.json", voice)
        # Derive the narrowest safe root(s). Any unknown editorial launch change begins at
        # the script; this errs toward correct output rather than reusing stale media.
        roots: set[str] = set()
        try:
            is_qh = load_content_project(str(record.get("content_project") or DEFAULT_CONTENT_PROJECT)).is_question_harvest
        except RuntimeError:
            is_qh = False
        changed = lambda a, b: json.dumps(a, sort_keys=True) != json.dumps(b, sort_keys=True)
        if changed({k:v for k,v in previous_brief.items() if not k.startswith("_")}, {k:v for k,v in brief.items() if not k.startswith("_")}): roots.add("script_draft")
        old_qh, new_qh = previous_brief.get("_qh", {}), brief.get("_qh", {})
        if changed(old_qh, new_qh):
            if is_qh:
                known_qh: set[str] = set()
                if any(old_qh.get(k) != new_qh.get(k) for k in ("world_style_policy", "world_style_id", "world_style_hint")): roots.add("world_style_director")
                known_qh.update(("world_style_policy", "world_style_id", "world_style_hint"))
                if any(old_qh.get(k) != new_qh.get(k) for k in ("gemini_image_model",)): roots.add("world_style_anchor")
                known_qh.add("gemini_image_model")
                if any(old_qh.get(k) != new_qh.get(k) for k in ("flow_video_model", "flow_resolution", "opening_a_source_seconds", "opening_b_source_seconds")): roots.update(("flow_clip_a", "flow_clip_b"))
                known_qh.update(("flow_video_model", "flow_resolution", "opening_a_source_seconds", "opening_b_source_seconds"))
                # Trim-only rule: changing the 10% sync tolerance never invalidates Flow
                # clips or images; the wrapper simply re-runs the trim on resume.
                known_qh.add("opening_speed_tolerance")
                if any(old_qh.get(k) != new_qh.get(k) for k in ("min_duration_seconds", "max_duration_seconds")): roots.add("retention_edit")
                known_qh.update(("min_duration_seconds", "max_duration_seconds"))
                if old_qh.get("show_subtitles") != new_qh.get("show_subtitles"): roots.add("render_profile")
                known_qh.add("show_subtitles")
                if old_qh.get("reserve_subtitle_space", True) != new_qh.get("reserve_subtitle_space", True): roots.add("beat_image_001")
                known_qh.add("reserve_subtitle_space")
                if old_qh.get("hero_presence_mode") != new_qh.get("hero_presence_mode"): roots.add("episode_director")
                known_qh.add("hero_presence_mode")
                if any(old_qh.get(key) != new_qh.get(key) for key in set(old_qh) | set(new_qh) if key not in known_qh): roots.add("script_draft")
            elif old_qh.get("show_subtitles") != new_qh.get("show_subtitles"):
                roots.add("render_profile")
        if changed(previous_brief.get("_motion", {}), brief.get("_motion", {})): roots.add("motion_director")
        if changed(previous_brief.get("_sfx", {}), brief.get("_sfx", {})): roots.update(("sfx_plan", "sfx_acquire"))
        if changed(previous_brief.get("_subtitle", {}), brief.get("_subtitle", {})): roots.add("render_profile")
        if changed(previous_voice, voice): roots.add("elevenlabs_voiceover")
        for key in ("music_providers", "music_provider"):
            if launch.get(key) != record.get(key): roots.add("background_music")
        if launch.get("aspect_ratio") != record.get("aspect_ratio"):
            roots.update(("flow_clip_a", "flow_clip_b", "render_profile") if is_qh else ("visual_plan", "render_profile"))
        if launch.get("commit_artifacts") != record.get("commit_artifacts"): roots.add("git_commit_push")
        if launch.get("telegram_low_size") != record.get("telegram_low_size"): roots.update(("telegram_compress", "publish_telegram"))
        if launch.get("telegram_original") != record.get("telegram_original"): roots.add("publish_telegram")
        if not roots: self.send_json(HTTPStatus.BAD_REQUEST, {"error": "No effective configuration change was found."}); return
        record.update({k:v for k,v in launch.items() if k in {"music_provider", "music_providers", "aspect_ratio", "commit_artifacts", "telegram_low_size", "telegram_original"}})
        record.update({
            "qh": brief.get("_qh") if isinstance(brief.get("_qh"), dict) else record.get("qh", {}),
            "motion": brief.get("_motion") if isinstance(brief.get("_motion"), dict) else record.get("motion", {}),
            "sfx": brief.get("_sfx") if isinstance(brief.get("_sfx"), dict) else record.get("sfx", {}),
            "word_highlight": bool((brief.get("_subtitle") or {}).get("word_highlight", record.get("word_highlight", True))),
            "subtitles": bool((brief.get("_qh") or {}).get("show_subtitles", record.get("subtitles", False))),
            "creative_brief": str((folder / "CREATIVE_BRIEF.json").relative_to(ROOT)),
            "voice_profile": str((folder / "VOICE_PROFILE.json").relative_to(ROOT)),
        })
        try:
            with LAUNCH_LOCK:
                if active_job(self.jobs_dir) is not None: self.send_json(HTTPStatus.CONFLICT, {"error": "Another episode is running."}); return
                revision, _ = self.start_regeneration(record, project, sorted(roots), kind="config")
        except (ValueError, KeyError, TypeError, OSError) as exc:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc) or "Could not start configuration revision."}); return
        record["last_config_revision"] = revision
        write_json(self.jobs_dir / f"{job_id}.json", record)
        write_json(project / "launch/LAUNCH_REQUEST.json", record)
        self.send_json(HTTPStatus.ACCEPTED, {"revision": revision, "status":"RUNNING"})

    def commit_config_revision(
        self,
        record: dict,
        project: Path,
        roots: set[str],
        brief: dict,
        voice: dict,
        launch: dict,
        changed_fields: list[str],
    ) -> None:
        """Commit the exact typed configuration that the preview endpoint evaluates."""
        if not changed_fields:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "No effective configuration change was found."})
            return
        if record.get("external"):
            self.send_json(HTTPStatus.CONFLICT, {"error": "Externally started runs are read-only in Studio."})
            return
        revision_id = str(uuid.uuid4())
        folder = project / "launch" / "config_revisions" / revision_id
        old_record = json.loads(json.dumps(record))
        job_path = self.jobs_dir / f"{record['job_id']}.json"
        launch_path = project / "launch" / "LAUNCH_REQUEST.json"
        try:
            with LAUNCH_LOCK:
                if active_job(self.jobs_dir) is not None:
                    self.send_json(HTTPStatus.CONFLICT, {"error": "Another episode is running."})
                    return
                folder.mkdir(parents=True, exist_ok=False)
                write_json(folder / "CREATIVE_BRIEF.json", brief)
                write_json(folder / "VOICE_PROFILE.json", voice)
                record.update({key: value for key, value in launch.items() if not key.startswith("_")})
                record.update({
                    "topic": str(launch.get("_topic") or record.get("topic")),
                    "qh": brief.get("_qh", {}),
                    "motion": brief.get("_motion", {}),
                    "sfx": brief.get("_sfx", {}),
                    "word_highlight": bool((brief.get("_subtitle") or {}).get("word_highlight", True)),
                    "subtitles": bool((brief.get("_qh") or {}).get("show_subtitles", False)),
                    "creative_brief": str((folder / "CREATIVE_BRIEF.json").relative_to(ROOT)),
                    "voice_profile": str((folder / "VOICE_PROFILE.json").relative_to(ROOT)),
                })
                # Publish the frozen inputs before spawning so the child cannot race and
                # observe the previous launch contract.
                write_json(job_path, record)
                write_json(launch_path, record)
                if roots:
                    revision, _ = self.start_regeneration(
                        record, project, sorted(roots), kind="config"
                    )
                else:
                    revision = {
                        "schema_version": 2,
                        "revision_id": revision_id,
                        "kind": "config",
                        "status": "DONE",
                        "created_at": utcnow(),
                        "completed_at": utcnow(),
                        "roots": [],
                        "affected_nodes": [],
                        "reused_nodes": [node["id"] for node in graph_for(project).get("nodes", [])],
                        "skipped_nodes": [],
                    }
                    revision_path = project / "pipeline" / "revisions" / revision_id / "REVISION.json"
                    revision_path.parent.mkdir(parents=True, exist_ok=True)
                    write_json(revision_path, revision)
        except (ValueError, KeyError, TypeError, OSError) as exc:
            record.clear()
            record.update(old_record)
            write_json(job_path, old_record)
            write_json(launch_path, old_record)
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc) or "Could not apply configuration revision."})
            return
        revision["changed_fields"] = changed_fields
        revision["config_revision_id"] = revision_id
        revision_path = project / "pipeline" / "revisions" / revision["revision_id"] / "REVISION.json"
        write_json(revision_path, revision)
        record["last_config_revision"] = revision
        write_json(job_path, record)
        write_json(launch_path, record)
        self.send_json(
            HTTPStatus.ACCEPTED if roots else HTTPStatus.OK,
            {"revision": revision, "status": revision["status"]},
        )

    def handle_config_preview(self) -> None:
        try:
            payload = self.read_json_payload()
            job_id = str(payload.get("job_id") or "")
            values = payload.get("values")
            if not JOB_ID_RE.fullmatch(job_id) or not isinstance(values, dict):
                raise ValueError("A valid run and settings form are required.")
            resolved = self.project_for_job(job_id)
            if not resolved:
                self.send_json(HTTPStatus.NOT_FOUND, {"error": "Unknown run."}); return
            record, project = resolved
            old_brief = json.loads((ROOT / str(record["creative_brief"])).read_text(encoding="utf-8"))
            old_voice = json.loads((ROOT / str(record["voice_profile"])).read_text(encoding="utf-8"))
            roots, brief, _voice, launch, changed_fields = config_roots(
                record, old_brief, old_voice, values
            )
            candidate = {
                **record,
                **launch,
                "qh": brief.get("_qh", {}),
                "motion": brief.get("_motion", {}),
                "sfx": brief.get("_sfx", {}),
            }
            plan = (
                regeneration_plan(
                    project,
                    sorted(roots),
                    include_disabled=True,
                    settings=candidate,
                    skip_disabled_descendants=True,
                )
                if roots
                else {
                    "affected_nodes": [],
                    "reused_nodes": [node["id"] for node in graph_for(project).get("nodes", [])],
                    "skipped_nodes": [],
                }
            )
            self.send_json(HTTPStatus.OK, {
                **plan,
                "roots": sorted(roots),
                "changed_fields": changed_fields,
                "can_start": not record.get("external") and active_job(self.jobs_dir) is None,
                "read_only": bool(record.get("external")),
            })
        except (ValueError, OSError, KeyError, json.JSONDecodeError, TypeError) as exc:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc) or "Could not preview this revision."})

    def log_tail(self, job_id: str, offset: int) -> dict:
        """Incremental log bytes, so the page can tail without refetching megabytes."""
        log = self.jobs_dir / f"{job_id}.log"
        if not log.exists():
            return {"offset": 0, "text": "", "waiting": True}
        size = log.stat().st_size
        start = min(max(offset, 0), size)
        if size - start > 200_000:  # a page that fell far behind gets the tail, not everything
            start = size - 200_000
        with log.open("rb") as handle:
            handle.seek(start)
            chunk = handle.read()
        return {"offset": size, "text": chunk.decode("utf-8", errors="replace"), "waiting": False}

    def page(self, message: str = "") -> str:
        """The studio page. Live parts (badges, runs, log) are filled by /api/status."""
        # Status of defunct RUNNING jobs is settled by the background reconciler, so the
        # page only reads; it never has to decide whether a pid is still alive.
        reconcile_stuck_jobs_once()
        project_options = "".join(
            f"<option value='{html.escape(project.project_id)}'"
            f"{' selected' if project.project_id == PREFERRED_CONTENT_PROJECT else ''}>"
            f"{html.escape(project.display_name)}</option>"
            for project in list_content_projects()
        )
        # The handler is constructed without a socket in tests, so Host is read defensively.
        headers = getattr(self, "headers", None)
        host = (headers.get("Host") if headers else None) or "localhost"
        return panel_page.render(
            message=message,
            project_options=project_options,
            style_options=style_options_html(PREFERRED_CONTENT_PROJECT),
            character_options="".join(
                f'<option value="{html.escape(str(item["id"]), quote=True)}">{html.escape(str(item["display_name"]))}</option>'
                for item in character_catalog_entries(PREFERRED_CONTENT_PROJECT)
            ),
            address=f"http://{host}/",
        )

    def read_job_id(self, limit: int = 4_000) -> str | None:
        """The job_id from a form post, or None after already answering with the error."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_notice(HTTPStatus.BAD_REQUEST, "Invalid Content-Length"); return None
        if length <= 0 or length > limit:
            self.send_notice(HTTPStatus.BAD_REQUEST, "Invalid request"); return None
        values = parse_qs(self.rfile.read(length).decode("utf-8", errors="replace"))
        job_id = (values.get("job_id") or [""])[0].strip()
        if not JOB_ID_RE.fullmatch(job_id):
            self.send_notice(HTTPStatus.BAD_REQUEST, "Unknown job id"); return None
        return job_id

    def handle_stop(self) -> None:
        """Stop a running job, and its watcher, without deleting anything it produced.

        The process group is signalled rather than the pid alone: the wrapper runs each
        stage as a child, and killing only the parent would leave a provider job running in
        the browser with nothing watching it.
        """
        job_id = self.read_job_id()
        if job_id is None:
            return
        record_path = self.jobs_dir / f"{job_id}.json"
        if not record_path.is_file():
            self.send_notice(HTTPStatus.NOT_FOUND, "That job no longer exists"); return
        try:
            job = json.loads(record_path.read_text(encoding="utf-8"))
        except ValueError:
            self.send_notice(HTTPStatus.CONFLICT, "That job record is unreadable"); return

        stopped = terminate_job(job)
        job["status"] = "STOPPED"
        job["completed_at"] = utcnow()
        job["stopped_by"] = "panel"
        pending = job.get("pending_revision") if isinstance(job.get("pending_revision"), dict) else None
        if pending:
            pending = {**pending, "status": "STOPPED", "completed_at": job["completed_at"]}
            job["pending_revision"] = pending
            revision_path = ROOT / str(job.get("project") or "") / "pipeline/revisions" / str(pending.get("revision_id")) / "REVISION.json"
            try:
                write_json(revision_path, pending)
            except OSError:
                pass
        write_json(record_path, job)
        request = ROOT / str(job.get("project") or "") / "launch/LAUNCH_REQUEST.json"
        if request.is_file():
            write_json(request, job)
        for watcher in watchers_for(self.jobs_dir, job.get("video_id")):
            terminate_job(watcher)
            watcher["status"] = "STOPPED"
            watcher["completed_at"] = utcnow()
            write_json(self.jobs_dir / f"{watcher['job_id']}.json", watcher)
        note = "stopped" if stopped else "was not running; marked stopped"
        self.send_notice(HTTPStatus.ACCEPTED, f"Job {job_id[:8]} ({job.get('video_id') or '—'}) {note}.")

    def handle_delete(self) -> None:
        """Archive a job's record and log. A running job is stopped first.

        Only the panel's own bookkeeping moves. The episode directory under videos/ is left
        alone, and the archived record prevents failed projects from reappearing as external
        runs. The operation is recoverable by moving the files back into ``jobs_dir``.
        """
        job_id = self.read_job_id()
        if job_id is None:
            return
        record_path = self.jobs_dir / f"{job_id}.json"
        if not record_path.is_file():
            self.send_notice(HTTPStatus.NOT_FOUND, "That job no longer exists"); return
        try:
            job = json.loads(record_path.read_text(encoding="utf-8"))
        except ValueError:
            job = {"job_id": job_id}
        if job.get("status") == "RUNNING" and pid_is_live(job.get("pid")):
            terminate_job(job)
        video_id = job.get("video_id")
        archive = self.jobs_dir / "archived"
        archive.mkdir(parents=True, exist_ok=True)
        record_path.replace(archive / record_path.name)
        log = self.jobs_dir / f"{job_id}.log"
        if log.is_file():
            log.replace(archive / log.name)
        self.send_notice(
            HTTPStatus.ACCEPTED,
            f"Archived job {job_id[:8]} ({video_id or '—'}). Its files under videos/ were kept.",
        )

    def handle_resume(self) -> None:
        """Re-run an existing episode. Completed stages are reused, so nothing is paid twice."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_notice(HTTPStatus.BAD_REQUEST, "Invalid Content-Length"); return
        if length <= 0 or length > 4_000:
            self.send_notice(HTTPStatus.BAD_REQUEST, "Invalid resume request"); return
        values = parse_qs(self.rfile.read(length).decode("utf-8", errors="replace"))
        job_id = (values.get("job_id") or [""])[0].strip()
        if not JOB_ID_RE.fullmatch(job_id):
            self.send_notice(HTTPStatus.BAD_REQUEST, "Unknown job id"); return
        record_path = self.jobs_dir / f"{job_id}.json"
        if not record_path.is_file():
            self.send_notice(HTTPStatus.NOT_FOUND, "That job no longer exists"); return

        with LAUNCH_LOCK:
            active = active_job(self.jobs_dir)
            if active is not None:
                self.send_notice(HTTPStatus.CONFLICT, f"Video {active.get('video_id')} is still running; resume after it finishes."); return
            record = json.loads(record_path.read_text(encoding="utf-8"))
            fallback_action = (values.get("fallback_action") or [""])[0]
            if fallback_action:
                project = ROOT / str(record.get("project") or "")
                request_path = project / "pipeline" / "FALLBACK_ACTION_REQUIRED.json"
                try:
                    pending = json.loads(request_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    self.send_notice(HTTPStatus.CONFLICT, "There is no pending Gemini fallback decision for this run."); return
                if fallback_action == "approve":
                    write_json(project / "pipeline" / "FALLBACK_APPROVAL.json", {
                        "stage": pending.get("stage"), "approved_at": utcnow(), "approved_by": "panel",
                    })
                elif fallback_action == "retry_primary":
                    (project / "pipeline" / "FALLBACK_APPROVAL.json").unlink(missing_ok=True)
                else:
                    self.send_notice(HTTPStatus.BAD_REQUEST, "Unknown fallback action."); return
                request_path.unlink(missing_ok=True)
            try:
                command = pipeline_command(record)
            except (KeyError, TypeError) as exc:
                self.send_notice(HTTPStatus.CONFLICT, f"That job cannot be resumed: {exc}"); return
            log = self.jobs_dir / f"{job_id}.log"
            handle = log.open("a", encoding="utf-8")
            handle.write(f"\n=== resume requested at {utcnow()} ===\n")
            handle.flush()
            try:
                process = subprocess.Popen(
                    command, cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT, start_new_session=True
                )
            except OSError as exc:
                handle.close()
                self.send_notice(HTTPStatus.INTERNAL_SERVER_ERROR, f"Could not resume: {exc}"); return
            finally:
                if not handle.closed:
                    handle.close()
            record.update({
                "status": "RUNNING",
                "pid": process.pid,
                "command": command,
                "resumed_at": utcnow(),
                "resume_count": int(record.get("resume_count") or 0) + 1,
            })
            record.pop("completed_at", None)
            write_json(record_path, record)
            monitor_process(job_id, process)
            request = ROOT / str(record.get("project") or "") / "launch" / "LAUNCH_REQUEST.json"
            if request.is_file():
                write_json(request, record)
        self.send_notice(HTTPStatus.ACCEPTED, f"Resumed {record.get('video_id')} — completed stages are reused, not regenerated.")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        route = parsed.path
        query = parse_qs(parsed.query)

        if route == "/api/ws":
            self.handle_websocket(query)
            return

        if route == "/api/launch-schema":
            schema = studio_schema()
            self.send_json(HTTPStatus.OK, {"schema": schema, "defaults": launch_defaults(schema)})
            return

        if route == "/api/style-catalog":
            content_project = str((query.get("content_project") or [PREFERRED_CONTENT_PROJECT])[0])
            try:
                canonical = resolve_project_id(content_project)
            except RuntimeError as exc:
                self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            self.send_json(HTTPStatus.OK, {"content_project": canonical, "styles": style_catalog_entries(canonical)})
            return
        if route == "/api/character-catalog":
            content_project = str((query.get("content_project") or [PREFERRED_CONTENT_PROJECT])[0])
            try:
                canonical = resolve_project_id(content_project)
            except RuntimeError as exc:
                self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            self.send_json(HTTPStatus.OK, {"content_project": canonical, "characters": character_catalog_entries(canonical)})
            return

        if route.startswith("/api/styles/"):
            parts = route.split("/")
            if len(parts) == 6:
                self.serve_style_preview(unquote(parts[3]), unquote(parts[4]), parts[5])
                return
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        if route.startswith("/api/run/") and route.endswith("/graph"):
            job_id = route.split("/")[3]; resolved = self.project_for_job(job_id)
            if not resolved: self.send_json(HTTPStatus.NOT_FOUND, {"error": "unknown run"}); return
            record, project = resolved
            live = pid_is_live(record.get("pid"))
            read_only = bool(record.get("external"))
            try:
                fallback_action = json.loads((project / "pipeline" / "FALLBACK_ACTION_REQUIRED.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                fallback_action = None
            self.send_json(HTTPStatus.OK, {"job": {**{key: record.get(key) for key in ("job_id", "video_id", "topic", "status", "created_at", "completed_at", "resumed_at", "external")}, "live": live, "read_only": read_only, "resumable": not read_only and not live and record.get("status") not in {"DONE"}, "stoppable": not read_only and live}, "graph": graph_for(project), "activity": activity_for(record, project), "fallback_action": fallback_action}); return

        if route.startswith("/api/run/") and route.endswith("/activity"):
            job_id = route.split("/")[3]; resolved = self.project_for_job(job_id)
            if not resolved: self.send_json(HTTPStatus.NOT_FOUND, {"error": "unknown run"}); return
            record, project = resolved
            self.send_json(HTTPStatus.OK, {"events": activity_for(record, project), "status": record.get("status"), "live": pid_is_live(record.get("pid"))}); return

        if route.startswith("/api/run/") and route.endswith("/config"):
            job_id = route.split("/")[3]; resolved = self.project_for_job(job_id)
            if not resolved: self.send_json(HTTPStatus.NOT_FOUND, {"error": "unknown run"}); return
            record, _project = resolved
            try:
                brief = json.loads((ROOT / str(record["creative_brief"])).read_text(encoding="utf-8"))
                voice = json.loads((ROOT / str(record["voice_profile"])).read_text(encoding="utf-8"))
            except (OSError, ValueError, KeyError):
                self.send_json(HTTPStatus.CONFLICT, {"error": "This run's frozen configuration is unavailable."}); return
            launch = {key: record.get(key) for key in ("music_provider", "music_providers", "aspect_ratio", "commit_artifacts", "telegram_low_size", "telegram_original")}
            self.send_json(HTTPStatus.OK, {
                "creative_brief": brief,
                "voice_profile": voice,
                "launch": launch,
                "values": frozen_values(record, brief, voice),
            }); return

        if route.startswith("/api/run/") and "/artifact/" in route:
            parts = route.split("/", 5)
            if len(parts) != 6: self.send_error(HTTPStatus.NOT_FOUND); return
            resolved = self.project_for_job(parts[3])
            if not resolved: self.send_error(HTTPStatus.NOT_FOUND); return
            self.serve_artifact(resolved[1], unquote(parts[5])); return

        if route in {"/", "/favicon.svg"} or route.startswith("/runs/") or route.startswith("/assets/"):
            self.serve_studio(route); return

        if route == "/api/status":
            jobs = job_records(self.jobs_dir)
            active = active_job(self.jobs_dir)
            self.send_json(HTTPStatus.OK, {
                "at": utcnow(),
                "ordak": provider_status(),
                "active_job_id": (active or {}).get("job_id"),
                "jobs": [
                    {
                        "job_id": job.get("job_id"),
                        "kind": job.get("kind", "episode"),
                        "video_id": job.get("video_id"),
                        "content_project": job.get("content_project", DEFAULT_CONTENT_PROJECT),
                        "topic": job.get("topic", ""),
                        "status": job.get("status", "QUEUED"),
                        "created_at": job.get("created_at"),
                        "pipeline": job.get("_pipeline") or {},
                        "motion": motion_status_of(job),
                        "resumable": bool(job.get("_resumable")),
                        "stoppable": bool(job.get("_stoppable")),
                        "live": bool(job.get("_live")),
                        "flow_pending": job.get("_flow_pending") or {},
                        "interval_seconds": job.get("interval_seconds"),
                    }
                    for job in jobs
                ],
            }); return

        if route.startswith("/api/log/"):
            job_id = route.rsplit("/", 1)[-1]
            if not JOB_ID_RE.fullmatch(job_id):
                self.send_json(HTTPStatus.NOT_FOUND, {"error": "unknown job"}); return
            try:
                offset = int((query.get("offset") or ["0"])[0])
            except ValueError:
                offset = 0
            self.send_json(HTTPStatus.OK, self.log_tail(job_id, offset)); return

        if route.startswith("/logs/"):
            # Kept for links already in circulation; the panel itself tails in place now.
            job_id = Path(route).name
            if not JOB_ID_RE.fullmatch(job_id): self.send_error(HTTPStatus.NOT_FOUND); return
            log = self.jobs_dir / f"{job_id}.log"
            text = log.read_text(encoding="utf-8", errors="replace")[-150_000:] if log.exists() else "Waiting for runner output..."
            self.send_html(HTTPStatus.OK, f"<meta http-equiv=refresh content=5><pre style='white-space:pre-wrap;word-break:break-word'>{html.escape(text)}</pre>"); return

        self.send_error(HTTPStatus.NOT_FOUND)

    def do_HEAD(self) -> None:
        """Expose correct metadata for static assets and range-capable previews."""
        route = urlparse(self.path).path
        if route in {"/", "/favicon.svg"} or route.startswith("/runs/") or route.startswith("/assets/"):
            self.serve_studio(route); return
        if route.startswith("/api/run/") and "/artifact/" in route:
            parts = route.split("/", 5)
            resolved = self.project_for_job(parts[3]) if len(parts) == 6 else None
            if resolved:
                self.serve_artifact(resolved[1], unquote(parts[5])); return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if self.path == "/api/regenerations/preview": self.handle_regeneration_preview(); return
        if self.path == "/api/regenerations": self.handle_regeneration(); return
        if self.path == "/api/revisions": self.handle_revision(); return
        if self.path == "/api/config-revisions/preview": self.handle_config_preview(); return
        if self.path == "/api/config-revisions": self.handle_config_revision(); return
        if self.path in {"/resume", "/api/fallback-action"}: self.handle_resume(); return
        if self.path == "/stop": self.handle_stop(); return
        if self.path == "/delete": self.handle_delete(); return
        if self.path != "/launch": self.send_error(HTTPStatus.NOT_FOUND); return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_notice(HTTPStatus.BAD_REQUEST, "Invalid Content-Length"); return
        if length <= 0 or length > 100_000:
            self.send_notice(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Launch form is too large"); return
        try:
            values = parse_qs(self.rfile.read(length).decode("utf-8"))
        except UnicodeDecodeError:
            self.send_notice(HTTPStatus.BAD_REQUEST, "Launch form must be UTF-8"); return
        try:
            topic = form_text(values, "topic", 220)
            requested_content_project = values.get("content_project", [DEFAULT_CONTENT_PROJECT])[0].strip()
            content_project = resolve_project_id(requested_content_project)
            available_projects = {project.project_id for project in list_content_projects()}
            duration_min = float(values["min_duration_seconds"][0]); duration_max = float(values["max_duration_seconds"][0])
            aspect_ratio = values["aspect_ratio"][0]; voice = values["voice"][0].strip(); model = values["model"][0].strip()
            speed, stability, similarity, style = (float(values[k][0]) for k in ("speed", "stability", "similarity", "style"))
            providers = music_provider_priority(values.get("music_providers", values.get("music_provider", ["mixkit"]))[0])
            show_subtitles = "show_subtitles" in values
            word_highlight = "word_highlight" in values
            commit_artifacts = "commit_artifacts" in values
            telegram_low_size = "telegram_low_size" in values
            telegram_original = "telegram_original" in values
            sfx_enabled = "sfx_enabled" in values
            sfx_freesound_enabled = "sfx_freesound_enabled" in values
            sfx_style = values.get("sfx_planner_style", ["restrained"])[0]
            sfx_max_events = float(values.get("sfx_max_events_per_minute", ["4"])[0])
            sfx_min_gap = float(values.get("sfx_minimum_gap_seconds", ["2"])[0])
            sfx_threshold = float(values.get("sfx_local_match_threshold", [".35"])[0])
            sfx_license = values.get("sfx_license_policy", ["cc0"])[0]
            sfx_candidates = int(values.get("sfx_candidate_count", ["12"])[0])
            sfx_queries = int(values.get("sfx_max_queries_per_event", ["2"])[0])
            sfx_gain = float(values.get("sfx_default_gain_db", ["-9"])[0])
            motion_enabled = "motion_enabled" in values
            motion_pace = values.get("motion_pace", ["fast"])[0]
            motion_intensity = values.get("motion_intensity", ["normal"])[0]
            motion_style = values.get("motion_style", ["dynamic"])[0]
            motion_transition = values.get("motion_transition_preference", ["minimal"])[0]
            motion_max_shots = int(values.get("motion_max_micro_shots", ["3"])[0])
            motion_planning_quality = values.get("motion_planning_quality", ["professional"])[0]
            motion_min_shot = float(values.get("motion_min_shot_duration", [".55"])[0])
            motion_max_shot = float(values.get("motion_max_shot_duration", ["3.2"])[0])
            motion_interval_min = float(values.get("motion_interval_min", [".8"])[0])
            motion_interval_max = float(values.get("motion_interval_max", ["1.8"])[0])
            motion_normal_zoom = float(values.get("motion_normal_max_zoom", ["1.32"])[0])
            motion_punch_zoom = float(values.get("motion_punch_max_zoom", ["1.48"])[0])
            motion_pan_distance = float(values.get("motion_max_pan_distance", [".32"])[0])
            motion_pan_velocity = float(values.get("motion_max_pan_velocity", [".42"])[0])
            motion_zoom_velocity = float(values.get("motion_max_zoom_velocity", [".34"])[0])
            motion_transition_fraction = float(values.get("motion_transition_fraction", [".25"])[0])
            motion_transition_min = float(values.get("motion_transition_min", [".10"])[0])
            motion_transition_max = float(values.get("motion_transition_max", [".40"])[0])
            motion_observation_batch = int(values.get("motion_observation_batch", ["3"])[0])
            motion_planning_batch = int(values.get("motion_planning_batch", ["1"])[0])
            motion_critic_batch = int(values.get("motion_critic_batch", ["2"])[0])
            motion_corrections = int(values.get("motion_correction_attempts", ["4"])[0])
            motion_neighbor_context = int(values.get("motion_neighbor_context", ["1"])[0])
            motion_word_sync_tolerance = int(values.get("motion_word_sync_tolerance", ["50"])[0])
            motion_face_padding = float(values.get("motion_face_padding", [".18"])[0])
            motion_supersample = int(values.get("motion_supersample", ["2"])[0])
            # QH advanced
            character_mode = values.get("character_mode", ["auto"])[0].strip() or "auto"
            character_id = values.get("character_id", [""])[0].strip()
            hero_presence_mode = values.get("hero_presence_mode", ["auto"])[0].strip() or "auto"
            world_style_policy = values.get("world_style_policy", ["auto"])[0].strip() or "auto"
            world_style_hint = form_text(values, "world_style_hint", 500) if values.get("world_style_hint") else ""
            reserve_subtitle_space = "reserve_subtitle_space" in values
            chatgpt_fallback_auto = "chatgpt_fallback_auto" in values
            world_style_id = values.get("world_style_id", [""])[0].strip()
            if world_style_id and world_style_id not in catalogued_style_ids(content_project):
                raise ValueError(f"Unknown world style: {world_style_id}")
            gemini_image_model = values.get("gemini_image_model", ["nano_banana_2"])[0].strip() or "nano_banana_2"
            flow_video_model = values.get("flow_video_model", ["gemini_omni_1_1_flash"])[0].strip() or "gemini_omni_1_1_flash"
            flow_resolution = values.get("flow_resolution", ["720p"])[0].strip() or "720p"
            opening_a_seconds = int(values.get("opening_a_seconds", ["6"])[0])
            opening_b_seconds = int(values.get("opening_b_seconds", ["4"])[0])
            try:
                raw_tol = values.get("opening_speed_tolerance", ["0.1"])[0]
                opening_speed_tolerance = float(str(raw_tol).strip() or "0.1")
            except (TypeError, ValueError):
                raise ValueError("Invalid opening_speed_tolerance")
            if not topic or content_project not in available_projects or not 15 <= duration_min <= duration_max <= 300 or aspect_ratio not in {"16:9", "9:16"} \
               or not voice or len(voice) > 220 or model not in {"Eleven Multilingual v2", "Eleven v3"} \
               or not .7 <= speed <= 1.2 or not all(0 <= value <= 1 for value in (stability, similarity, style)):
                raise ValueError("Invalid launch values.")
            if not telegram_low_size and not telegram_original:
                raise ValueError("Choose at least one Telegram delivery output.")
            if hero_presence_mode not in {"auto", "opener_only", "limited_in_world", "in_world"}:
                raise ValueError("Invalid hero_presence_mode")
            if world_style_policy not in {"auto", "reuse", "new"}:
                raise ValueError("Invalid world_style_policy")
            if gemini_image_model not in {"nano_banana_pro", "nano_banana_2"}:
                try:
                    gemini_image_model = normalize_gemini_model(gemini_image_model)
                except Exception:
                    raise ValueError("Invalid gemini_image_model")
            if flow_video_model not in {"gemini_omni_1_1_flash", "veo_3_1_quality", "veo_3_1_fast", "veo_3_1_lite"}:
                try:
                    flow_video_model = normalize_flow_model(flow_video_model)
                except Exception:
                    raise ValueError(f"Invalid flow_video_model: {flow_video_model}")
            if flow_resolution not in {"720p", "360p"}:
                raise ValueError("Invalid flow_resolution")
            if opening_a_seconds not in {4,5,6,8} or opening_b_seconds not in {3,4,6,8}:
                raise ValueError("Invalid opening durations")
            if not 0 <= opening_speed_tolerance <= 0.5:
                raise ValueError("Invalid opening_speed_tolerance")
            if sfx_style not in {"restrained", "balanced", "expressive"} or not 0 <= sfx_max_events <= 20 or not 0 <= sfx_min_gap <= 30 or not 0 <= sfx_threshold <= 1 or sfx_license not in {"cc0", "cc0_by"} or not 1 <= sfx_candidates <= 50 or not 1 <= sfx_queries <= 5 or not -40 <= sfx_gain <= -3:
                raise ValueError("Invalid SFX settings")
            if motion_enabled and (motion_pace not in {"calm", "balanced", "fast", "very_fast"} or motion_intensity not in {"subtle", "normal", "strong"} or motion_style not in {"clean", "dynamic", "cinematic"} or motion_transition not in {"minimal", "balanced", "expressive"} or not 1 <= motion_max_shots <= 4):
                raise ValueError("Invalid Motion settings")
            if motion_enabled and (motion_planning_quality not in {"draft", "standard", "professional"} \
               or not .35 <= motion_min_shot <= motion_max_shot <= 8 \
               or not .4 <= motion_interval_min <= motion_interval_max <= 8 \
               or not 1 <= motion_normal_zoom <= motion_punch_zoom <= 1.8 \
               or not .02 <= motion_pan_distance <= .7 \
               or not .02 <= motion_pan_velocity <= 1 or not .02 <= motion_zoom_velocity <= 1 \
               or not 0 <= motion_transition_fraction <= 1 \
               or not .08 <= motion_transition_min <= motion_transition_max <= .8 \
               or not 1 <= motion_observation_batch <= 6 or not 1 <= motion_planning_batch <= 6 or not 1 <= motion_critic_batch <= 4 \
               or not 0 <= motion_corrections <= 4 or not 1 <= motion_neighbor_context <= 3 \
               or not 0 <= motion_word_sync_tolerance <= 250 or not 0 <= motion_face_padding <= .5 \
               or not 1 <= motion_supersample <= 4):
                raise ValueError("Invalid advanced Motion settings")
            motion_primitives = (
                "motion_allow_hold", "motion_allow_push", "motion_allow_pull", "motion_allow_directional_pans",
                "motion_allow_tilt", "motion_allow_pan_push", "motion_allow_pan_pull", "motion_allow_drift",
                "motion_allow_settle", "motion_allow_reveal_move",
            )
            if motion_enabled and not any(name in values for name in motion_primitives):
                raise ValueError("Enable at least one Motion primitive (use intentional holds for cut-only editing)")
            cp = load_content_project(content_project)
            # provider locks (§60)
            validate_provider_locks(cp)
            # Validate project assets, including the Q Station character registry.
            validate_content_project(cp)
            if cp.is_question_harvest:
                if character_mode not in {"auto", "manual"}:
                    raise ValueError("Invalid character mode.")
                registry_path = character_registry_path(cp)
                registry = load_character_registry(registry_path) if registry_path else None
                if character_mode == "manual":
                    if registry is None or not character_id:
                        raise ValueError("Manual character selection requires a character.")
                    try:
                        registry.get(character_id)
                    except CharacterSelectionError as exc:
                        raise ValueError(str(exc)) from exc
                elif character_id:
                    raise ValueError("Auto character selection must not include a manual character id.")
            creative_brief = {key: form_text(values, key) for key in CREATIVE_FIELDS}
            # Store bookworld/Q Station settings for the downstream pipeline.
            creative_brief["_qh"] = {
                "character": {
                    "mode": character_mode,
                    **({"character_id": character_id} if character_mode == "manual" else {}),
                },
                "hero_presence_mode": hero_presence_mode,
                "world_style_policy": world_style_policy,
                "world_style_id": world_style_id,
                "world_style_hint": world_style_hint,
                "min_duration_seconds": duration_min,
                "max_duration_seconds": duration_max,
                "gemini_image_model": gemini_image_model,
                "flow_video_model": flow_video_model,
                "flow_resolution": flow_resolution,
                "opening_a_source_seconds": opening_a_seconds,
                "opening_b_source_seconds": opening_b_seconds,
                "opening_speed_tolerance": opening_speed_tolerance,
                "show_subtitles": show_subtitles,
                "reserve_subtitle_space": reserve_subtitle_space,
                "chatgpt_fallback_mode": "auto" if chatgpt_fallback_auto else "approval",
            }
            # Kept outside the QH-only settings so legacy content projects use the same
            # visible panel choice when their render profile is created.
            creative_brief["_subtitle"] = {"word_highlight": word_highlight}
            creative_brief["_sfx"] = {"enabled": sfx_enabled, "planner_enabled": sfx_enabled, "planner_style": sfx_style, "max_events_per_minute": sfx_max_events, "minimum_gap_seconds": sfx_min_gap, "local_match_threshold": sfx_threshold, "freesound_enabled": sfx_freesound_enabled, "license_policy": sfx_license, "candidate_count": sfx_candidates, "max_queries_per_event": sfx_queries, "default_gain_db": sfx_gain, "min_gain_db": -20, "max_gain_db": -3}
            creative_brief["_motion"] = {
                "enabled": motion_enabled, "planning_quality": motion_planning_quality,
                "pace": motion_pace, "intensity": motion_intensity, "style": motion_style,
                "transition_preference": motion_transition,
                "max_micro_shots_per_beat": motion_max_shots,
                "min_micro_shot_duration": motion_min_shot, "max_micro_shot_duration": motion_max_shot,
                "target_interval_min": motion_interval_min, "target_interval_max": motion_interval_max,
                "allow_hold": "motion_allow_hold" in values,
                "allow_push": "motion_allow_push" in values, "allow_pull": "motion_allow_pull" in values,
                "allow_pan": "motion_allow_directional_pans" in values,
                "allow_tilt": "motion_allow_tilt" in values,
                "allow_pan_push": "motion_allow_pan_push" in values,
                "allow_pan_pull": "motion_allow_pan_pull" in values,
                "allow_drift": "motion_allow_drift" in values,
                "allow_settle": "motion_allow_settle" in values,
                "allow_reveal_move": "motion_allow_reveal_move" in values,
                "allow_punch_cuts": "motion_allow_punch_ins" in values,
                "allow_hard_reframes": "motion_allow_hard_reframe_cuts" in values,
                "allow_match_position_cuts": "motion_allow_match_position_cuts" in values,
                "allow_decorative_transitions": "motion_allow_decorative_transitions" in values,
                "allow_directional_transitions": "motion_allow_directional_transitions" in values,
                "allow_reveal_transitions": "motion_allow_reveal_transitions" in values,
                "max_decorative_transition_fraction": motion_transition_fraction,
                "transition_duration_min": motion_transition_min, "transition_duration_max": motion_transition_max,
                "normal_max_zoom": motion_normal_zoom, "punch_max_zoom": motion_punch_zoom,
                "max_pan_distance": motion_pan_distance, "max_pan_velocity": motion_pan_velocity,
                "max_zoom_velocity": motion_zoom_velocity,
                "face_protection": "motion_face_protection" in values,
                "subtitle_avoidance": "motion_subtitle_avoidance" in values,
                "blank_region_avoidance": "motion_blank_avoidance" in values,
                "word_sync": "motion_word_sync" in values,
                "observation_batch_size": motion_observation_batch,
                "planning_batch_size": motion_planning_batch,
                "critic_batch_size": motion_critic_batch,
                "editorial_critic": "motion_editorial_critic" in values,
                "correction_attempts": motion_corrections,
                "neighbor_context": motion_neighbor_context,
                "word_sync_tolerance_ms": motion_word_sync_tolerance,
                "face_padding": motion_face_padding,
                "debug_preview": "motion_debug_preview" in values,
                "supersample": motion_supersample,
            }
        except (KeyError, ValueError) as exc:
            self.send_notice(HTTPStatus.BAD_REQUEST, str(exc)); return
        except RuntimeError as exc:
            self.send_notice(HTTPStatus.CONFLICT, str(exc)); return
        with LAUNCH_LOCK:
            active = active_job(self.jobs_dir)
            if active is not None:
                self.send_notice(HTTPStatus.CONFLICT, f"Video {active.get('video_id')} is already running. Wait for it to finish before launching another."); return
            video_id = next_video_id()
            project = ROOT / "videos" / f"{video_id}_{video_slug(topic)}"; profile = project / "voiceover" / "REQUESTED_VOICE_PROFILE.json"
            write_json(profile, {"voice": voice, "model": model, "speed": speed, "stability": stability, "similarity": similarity, "style": style, "speaker_boost": False, "output_format": "MP3 44.1 kHz (128kbps)"})
            creative_brief_path = project / "launch" / "CREATIVE_BRIEF.json"; write_json(creative_brief_path, creative_brief)
            # Store the launch request with frozen settings §59.
            job_id = str(uuid.uuid4())
            subtitles_enabled = show_subtitles
            record = {
                "schema_version": 5, "content_project": content_project, "job_id": job_id, "status": "RUNNING", "created_at": utcnow(),
                "topic": topic, "video_id": video_id, "duration_min_seconds": duration_min, "duration_max_seconds": duration_max,
                "aspect_ratio": aspect_ratio, "project": str(project.relative_to(ROOT)),
                "voice_profile": str(profile.relative_to(ROOT)), "creative_brief": str(creative_brief_path.relative_to(ROOT)),
                "qh": creative_brief["_qh"],
                "character": creative_brief["_qh"]["character"],
                "subtitles": subtitles_enabled,
                "word_highlight": word_highlight,
                "sfx": creative_brief["_sfx"],
                "motion": creative_brief["_motion"],
                # Recorded so a resume rebuilds exactly this command (§78).
                "music_provider": providers[0],  # legacy readers retain the first choice
                "music_providers": providers,
                "commit_artifacts": commit_artifacts,
                "telegram_low_size": telegram_low_size,
                "telegram_original": telegram_original,
            }
            request = project / "launch" / "LAUNCH_REQUEST.json"; write_json(request, record); write_json(self.jobs_dir / f"{job_id}.json", record)
            log = self.jobs_dir / f"{job_id}.log"; handle = log.open("w", encoding="utf-8")
            # One builder for launch and resume: the QH wrapper owns the whole episode
            # (visual stages, narration, measured timing, trims, music, render, QC, publish).
            command = pipeline_command(record)
            try:
                process = subprocess.Popen(command, cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT, start_new_session=True)
            except OSError as exc:
                handle.close()
                record.update({"status": "FAILED", "completed_at": utcnow(), "error": f"Could not start pipeline: {exc}"})
                write_json(request, record); write_json(self.jobs_dir / f"{job_id}.json", record)
                self.send_notice(HTTPStatus.INTERNAL_SERVER_ERROR, record["error"]); return
            finally:
                if not handle.closed:
                    handle.close()
            record.update({"pid": process.pid, "command": command, "started_at": utcnow()}); write_json(request, record); write_json(self.jobs_dir / f"{job_id}.json", record)
            monitor_process(job_id, process)
        self.send_notice(
            HTTPStatus.ACCEPTED,
            f"Launched {video_id} ({content_project}); live log is available in the run workspace.",
            job_id=job_id,
            video_id=video_id,
        )


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--host", default="127.0.0.1"); parser.add_argument("--port", type=int, default=4142); args = parser.parse_args()
    (ROOT / "control_panel" / "jobs").mkdir(parents=True, exist_ok=True)
    reconcile_scheduled_resumes()
    reconcile_stuck_jobs_once()
    start_stuck_job_reconciler(interval=30)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Video control panel: http://{args.host}:{args.port}", flush=True); server.serve_forever()


if __name__ == "__main__": main()
