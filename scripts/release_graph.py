"""Canonical DAG, artifact ownership and revision planning for Release runs.

Release is deliberately separate from the episode pipeline.  A release consumes one
hash-pinned, QC-passed master and owns only files below its release directory.  Both the
worker and Studio use this registry so inspection, resume and revision cannot disagree
about dependency closure or artifact ownership.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class ReleaseNodeSpec:
    title: str
    kind: str
    phase: str
    dependencies: tuple[str, ...] = ()
    artifacts: tuple[str, ...] = ()
    description: str = ""
    regeneratable: bool = True


STATIC_SPECS: dict[str, ReleaseNodeSpec] = {
    "source_gate": ReleaseNodeSpec(
        "Approved video source", "data", "source", (),
        ("SOURCE_SNAPSHOT.json", "RELEASE_REQUEST.json"),
        "Binds this Release to the exact finalized master and passing QC evidence.", False,
    ),
    "release_context": ReleaseNodeSpec(
        "Release context", "data", "metadata", ("source_gate",),
        ("RELEASE_CONTEXT.json",),
        "Factual episode, channel, music and upload-policy context.",
    ),
    "visual_references": ReleaseNodeSpec(
        "Final-render references", "image", "metadata", ("source_gate",),
        ("THUMBNAIL_CONTEXT.json", "visual_references/render_opening.png",
         "visual_references/render_body.png", "visual_references/render_closing.png"),
        "Frames extracted from the approved master plus bounded identity references.",
    ),
    "metadata_draft": ReleaseNodeSpec(
        "Metadata draft", "data", "metadata", ("release_context", "visual_references"),
        ("METADATA_DRAFT.json",),
        "First factual title, description, tags and thumbnail brief.",
    ),
    "metadata_review": ReleaseNodeSpec(
        "Metadata editorial review", "data", "metadata", ("metadata_draft", "release_context"),
        ("METADATA_REVIEW.json",),
        "Strict factual and YouTube-contract review of the draft.",
    ),
    "metadata_finalize": ReleaseNodeSpec(
        "Final metadata", "data", "metadata", ("metadata_review",),
        ("YOUTUBE_SHORT_METADATA.json",),
        "Schema-validated, copy-ready release metadata.",
    ),
    "thumbnail_plan": ReleaseNodeSpec(
        "Thumbnail concepts", "data", "thumbnail", ("metadata_finalize",),
        ("THUMBNAIL_PLAN.json",),
        "Independent evidence-led candidate concepts and layout assignments.",
    ),
    "thumbnail_selection": ReleaseNodeSpec(
        "Thumbnail selection", "data", "thumbnail", (),
        ("THUMBNAIL_REVIEW.json", "THUMBNAIL_SELECTION.json", "thumbnail.png"),
        "Ranks eligible final files and records the recommended candidate.",
    ),
    "upload_guide": ReleaseNodeSpec(
        "Upload package", "text", "package", ("metadata_finalize", "thumbnail_selection"),
        ("YOUTUBE_SHORT_UPLOAD.md",),
        "Copy-ready upload instructions and manual-review declarations.",
    ),
    "telegram_delivery": ReleaseNodeSpec(
        "Telegram delivery", "data", "delivery", ("source_gate", "metadata_finalize", "thumbnail_selection", "upload_guide"),
        ("DELIVERY_STATE.json",),
        "Idempotent receipts for the master, candidates and release documents.",
    ),
    "release_complete": ReleaseNodeSpec(
        "Release complete", "data", "delivery", ("metadata_finalize",),
        ("RELEASE_STATE.json",),
        "Terminal receipt for every operation selected in this Release run.", False,
    ),
}

PHASES = ["source", "metadata", "thumbnail", "package", "delivery"]
MEDIA_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".mp4", ".mov", ".webm", ".mp3", ".wav", ".ogg"}


def load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _candidate_ids(root: Path, request: dict[str, Any]) -> list[str]:
    plan = load(root / "THUMBNAIL_PLAN.json")
    planned = [
        str(item.get("candidate_id")) for item in plan.get("plans") or []
        if isinstance(item, dict) and item.get("candidate_id")
    ]
    found = [path.name for path in sorted((root / "thumbnail_candidates").glob("candidate_*")) if path.is_dir()]
    settings = request.get("settings") if isinstance(request.get("settings"), dict) else request
    thumb = settings.get("thumbnail") if isinstance(settings.get("thumbnail"), dict) else {}
    if thumb and settings.get("generate_thumbnail", True):
        count = thumb.get("count") if thumb.get("count_mode") == "fixed" else thumb.get("auto_max")
        if isinstance(count, int):
            found.extend(f"candidate_{number:02d}" for number in range(1, count + 1))
    return list(dict.fromkeys(planned + found))


def candidate_specs(root: Path, request: dict[str, Any]) -> dict[str, ReleaseNodeSpec]:
    specs: dict[str, ReleaseNodeSpec] = {}
    review_nodes: list[str] = []
    for candidate_id in _candidate_ids(root, request):
        prefix = f"thumbnail_{candidate_id}"
        artwork, compose, review = f"{prefix}_artwork", f"{prefix}_compose", f"{prefix}_review"
        base = f"thumbnail_candidates/{candidate_id}"
        specs[artwork] = ReleaseNodeSpec(
            f"{candidate_id.replace('_', ' ').title()} artwork", "image", "thumbnail", ("thumbnail_plan",),
            (f"{base}/concept.json", f"{base}/artwork.png", f"{base}/candidate.json"),
            "Text-free provider artwork for this candidate only.",
        )
        specs[compose] = ReleaseNodeSpec(
            f"{candidate_id.replace('_', ' ').title()} composition", "image", "thumbnail", (artwork,),
            (f"{base}/final.png", f"{base}/preview_small.jpg", f"{base}/layout.json"),
            "Deterministic finalization and phone-size preview of the headline-bearing artwork.",
        )
        specs[review] = ReleaseNodeSpec(
            f"{candidate_id.replace('_', ' ').title()} final review", "data", "thumbnail", (compose,),
            (f"{base}/review.json",),
            "Final-file eligibility and editorial review.",
        )
        review_nodes.append(review)
    selection = STATIC_SPECS["thumbnail_selection"]
    specs["thumbnail_selection"] = ReleaseNodeSpec(
        selection.title, selection.kind, selection.phase, tuple(review_nodes) or ("thumbnail_plan",),
        selection.artifacts, selection.description, selection.regeneratable,
    )
    return specs


def specs_for(root: Path) -> dict[str, ReleaseNodeSpec]:
    request = load(root / "RELEASE_REQUEST.json")
    specs = dict(STATIC_SPECS)
    dynamic = candidate_specs(root, request)
    selection = dynamic.pop("thumbnail_selection")
    ordered: dict[str, ReleaseNodeSpec] = {}
    for node_id, spec in specs.items():
        if node_id == "thumbnail_selection":
            ordered.update(dynamic)
            ordered[node_id] = selection
        else:
            ordered[node_id] = spec
    settings = request.get("settings") if isinstance(request.get("settings"), dict) else request
    thumb_settings = settings.get("thumbnail") if isinstance(settings.get("thumbnail"), dict) else {}
    if thumb_settings.get("image_model") != "chatgpt":
        # Preserve the dependency shape of historical non-ChatGPT Release runs.
        if "thumbnail_plan" in ordered:
            spec = ordered["thumbnail_plan"]
            ordered["thumbnail_plan"] = ReleaseNodeSpec(
                spec.title, spec.kind, spec.phase, ("metadata_finalize", "visual_references"),
                spec.artifacts, spec.description, spec.regeneratable,
            )
        for node_id, spec in list(ordered.items()):
            if node_id.endswith("_artwork"):
                ordered[node_id] = ReleaseNodeSpec(
                    spec.title, spec.kind, spec.phase, ("thumbnail_plan", "visual_references"),
                    spec.artifacts, spec.description, spec.regeneratable,
                )
    if not settings.get("generate_thumbnail", True):
        ordered = {key: value for key, value in ordered.items() if value.phase != "thumbnail"}
    if not settings.get("create_upload_guide", True):
        ordered.pop("upload_guide", None)
    if not settings.get("send_telegram", True):
        ordered.pop("telegram_delivery", None)
    # A thumbnail-free guide/delivery consumes final metadata directly.
    if "thumbnail_selection" not in ordered:
        for key in ("upload_guide", "telegram_delivery"):
            if key in ordered:
                spec = ordered[key]
                ordered[key] = ReleaseNodeSpec(spec.title, spec.kind, spec.phase,
                    tuple(dep for dep in spec.dependencies if dep != "thumbnail_selection"),
                    spec.artifacts, spec.description, spec.regeneratable)
    # Completion depends on every selected terminal operation, not disabled branches.
    terminals = tuple(key for key in ("upload_guide", "telegram_delivery") if key in ordered)
    terminal = ordered["release_complete"]
    ordered["release_complete"] = ReleaseNodeSpec(
        terminal.title, terminal.kind, terminal.phase,
        terminals or (("thumbnail_selection",) if "thumbnail_selection" in ordered else ("metadata_finalize",)),
        terminal.artifacts, terminal.description, terminal.regeneratable,
    )
    return ordered


def _events_by_stage(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    aliases = {"metadata": "metadata_finalize", "thumbnail": "thumbnail_selection", "telegram_delivery": "telegram_delivery", "upload_guide": "upload_guide"}
    for entry in state.get("events") or []:
        if not isinstance(entry, dict) or not entry.get("stage"):
            continue
        stage = aliases.get(str(entry["stage"]), str(entry["stage"]))
        result[stage] = entry
    for stage, entry in (state.get("nodes") or {}).items():
        if isinstance(entry, dict):
            result[str(stage)] = entry
    return result


def _artifact(root: Path, relative: str) -> dict[str, Any]:
    path = root / relative
    present = path.is_file()
    size = path.stat().st_size if present else None
    return {
        "path": relative, "present": present, "exists": bool(present and size), "bytes": size,
        "media": path.suffix.lower() in MEDIA_SUFFIXES,
        "updated_at": path.stat().st_mtime_ns if present else None,
    }


def graph_for(root: Path) -> dict[str, Any]:
    specs = specs_for(root)
    state = load(root / "RELEASE_STATE.json")
    request = load(root / "RELEASE_REQUEST.json")
    events = _events_by_stage(state)
    reused = set(request.get("reused_nodes") or state.get("reused_nodes") or [])
    nodes: list[dict[str, Any]] = []
    for node_id, spec in specs.items():
        artifacts = [_artifact(root, relative) for relative in spec.artifacts]
        entry = events.get(node_id, {})
        required = [item for item in artifacts if not item["path"].endswith("candidate.json")]
        artifacts_ok = bool(required) and all(item["exists"] for item in required)
        status = str(entry.get("status") or "")
        if node_id == "source_gate" and state.get("master_sha256"):
            status = status or "DONE"
        if node_id == "release_context" and not artifacts_ok and (root / "THUMBNAIL_CONTEXT.json").is_file():
            artifacts_ok = True  # legacy releases stored the bounded context in this file
        if node_id == "release_complete":
            status = str(state.get("status") or status or "PENDING")
        elif not status:
            status = "REUSED" if node_id in reused and artifacts_ok else "DONE" if artifacts_ok else "PENDING"
        # Once the worker is terminal, its last active checkpoint is no longer
        # running. Surface it as the attention node instead of a stale spinner.
        if status == "RUNNING" and state.get("status") in {"FAILED", "STOPPED", "INTERRUPTED", "NEEDS_REVIEW"}:
            status = "FAILED" if state.get("status") == "FAILED" else str(state.get("status"))
        if status in {"DONE", "REUSED"} and required and not artifacts_ok and not (
            node_id == "source_gate" and state.get("master_sha256")
        ):
            status = "MISSING"
        nodes.append({
            "id": node_id, "title": spec.title, "kind": spec.kind, "phase": spec.phase,
            "description": spec.description, "status": status, "artifacts": artifacts,
            "meta": entry, "regeneratable": spec.regeneratable,
            "regeneration": {"policy": "cascade", "modes": ["cascade"], "default_mode": "cascade", "feedback": spec.regeneratable},
        })
    visible = {node["id"] for node in nodes}
    edges = [
        {"source": dependency, "target": node_id, "kind": "gate" if dependency == "source_gate" else "data"}
        for node_id, spec in specs.items() for dependency in spec.dependencies
        if dependency in visible
    ]
    return {"schema_version": 1, "mode": "release", "nodes": nodes, "edges": edges, "phases": PHASES}


def affected_nodes(graph: dict[str, Any], roots: Iterable[str]) -> set[str]:
    node_ids = {str(node.get("id")) for node in graph.get("nodes") or []}
    selected = {str(root) for root in roots}
    unknown = selected - node_ids
    if unknown:
        raise ValueError("Unknown Release stage(s): " + ", ".join(sorted(unknown)))
    children: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
    for edge in graph.get("edges") or []:
        children.setdefault(str(edge.get("source")), set()).add(str(edge.get("target")))
    queue = list(selected)
    while queue:
        current = queue.pop()
        for child in children.get(current, set()):
            if child not in selected:
                selected.add(child); queue.append(child)
    return selected


def revision_plan(root: Path, roots: Iterable[str]) -> dict[str, Any]:
    graph = graph_for(root)
    selected = list(dict.fromkeys(str(item) for item in roots))
    node_map = {node["id"]: node for node in graph["nodes"]}
    managed = [node_id for node_id in selected if node_map.get(node_id, {}).get("regeneratable") is False]
    if managed:
        raise ValueError("Managed Release stages cannot be revised directly: " + ", ".join(managed))
    affected = affected_nodes(graph, selected)
    ordered = [node["id"] for node in graph["nodes"]]
    return {
        "roots": selected,
        "affected_nodes": [node_id for node_id in ordered if node_id in affected],
        "reused_nodes": [node_id for node_id in ordered if node_id not in affected],
    }


def settings_revision_roots(root: Path, old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    """Map configuration changes to the narrowest valid Release DAG roots."""
    graph_ids = {str(node.get("id")) for node in graph_for(root).get("nodes") or []}
    operation_keys = {"generate_metadata", "generate_thumbnail", "create_upload_guide", "send_telegram", "force"}
    if any(old.get(key) != new.get(key) for key in operation_keys):
        return ["release_context"]
    roots: list[str] = []
    if any(old.get(key) != new.get(key) for key in ("metadata_note", "title_override")):
        roots.append("metadata_draft")
    old_thumb = old.get("thumbnail") if isinstance(old.get("thumbnail"), dict) else {}
    new_thumb = new.get("thumbnail") if isinstance(new.get("thumbnail"), dict) else {}
    changed = {key for key in set(old_thumb) | set(new_thumb) if old_thumb.get(key) != new_thumb.get(key)}
    art_fields = {"count_mode", "count", "auto_min", "auto_max", "concept_count", "diversity", "layout_mode", "allowed_layouts", "tension", "brand_profile", "approved_style_reference", "thumbnail_note", "character_expression", "topic_objects", "color_direction", "must_include", "must_avoid", "text_mode", "manual_text", "max_image_generations", "aspect_ratio", "image_model", "quality", "image_fallback"}
    compose_fields = {"preview_small"}
    review_fields = {"review_preset", "review_enabled", "corrections_per_candidate"}
    delivery_fields = {"send_previews", "send_master_video", "send_comparison_sheet", "send_report_json", "send_raw_artwork", "delivery_mode", "resend"}
    if changed & art_fields:
        roots.append("thumbnail_plan")
    if changed & compose_fields:
        roots.extend(node_id for node_id in graph_ids if node_id.startswith("thumbnail_candidate_") and node_id.endswith("_compose"))
    if changed & review_fields:
        roots.extend(node_id for node_id in graph_ids if node_id.startswith("thumbnail_candidate_") and node_id.endswith("_review"))
    if changed & delivery_fields:
        roots.append("telegram_delivery")
    if changed & {"comparison_sheet", "export_format", "jpeg_quality"}:
        roots.append("thumbnail_selection")
    known = art_fields | compose_fields | review_fields | delivery_fields | {"comparison_sheet", "export_format", "jpeg_quality", "reference_mode", "reference_timestamps", "max_references"}
    if changed & {"reference_mode", "reference_timestamps", "max_references"}:
        roots.append("visual_references")
    if changed - known:
        roots.append("thumbnail_plan")
    roots = [root_id for root_id in dict.fromkeys(roots) if root_id in graph_ids]
    return roots or ["release_context"]


def artifact_paths_for(root: Path, node_ids: Iterable[str]) -> list[str]:
    specs = specs_for(root)
    paths: list[str] = []
    for node_id in node_ids:
        spec = specs.get(str(node_id))
        if spec:
            paths.extend(spec.artifacts)
    # Selection owns aliases and aggregated reports; removing it must never leave an old winner.
    if "thumbnail_selection" in set(node_ids):
        paths.extend(("comparison.jpg", "thumbnail.png"))
    return list(dict.fromkeys(paths))
