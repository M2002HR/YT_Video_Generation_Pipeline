"""Canonical control-panel DAG and artifact discovery.

The pipeline executors are still mostly sequential, but this registry describes data
dependencies. The panel, regeneration planner and tests consume the same definition so the
visible graph cannot silently diverge from invalidation behaviour.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from image_artifacts import receipt_status


@dataclass(frozen=True)
class NodeSpec:
    title: str
    kind: str
    dependencies: tuple[str, ...] = ()
    artifacts: tuple[str, ...] = ()
    optional_artifacts: tuple[str, ...] = ()
    description: str = ""
    phase: str = "pipeline"
    regeneratable: bool = True


# Adding a regular stage should require one entry here, not coordinated edits in the API,
# graph renderer and regeneration handler. Beat-image nodes are expanded dynamically.
NODE_SPECS: dict[str, NodeSpec] = {
    "script_draft": NodeSpec("Script draft", "text", artifacts=("creative/SCRIPT_DRAFT.json",), description="Initial researched script response.", phase="creative"),
    "retention_edit": NodeSpec("Final script", "text", ("script_draft",), ("creative/SCRIPT_PLAN.json", "SCRIPT_FINAL.md"), description="Retention-edited narration and beat plan.", phase="creative"),
    "character_resolution": NodeSpec("Character resolution", "data", ("retention_edit",), ("creative/CHARACTER_RESOLUTION.json",), description="One-time Auto/manual host resolution between Stages 02 and 03.", phase="creative"),
    "episode_director": NodeSpec("Episode direction", "data", ("character_resolution",), ("creative/EPISODE_PLAN.json",), phase="creative"),
    "world_style_director": NodeSpec("World style", "data", ("retention_edit",), ("creative/WORLD_STYLE_PLAN.json",), phase="creative"),
    "world_style_anchor": NodeSpec("Style anchor", "image", ("world_style_director",), ("references/world_style_anchor.png",), ("pipeline/provider_receipts/gemini_world_style_anchor.json",), phase="visual"),
    "episode_history": NodeSpec("Episode history", "data", ("episode_director", "world_style_director"), description="Records anti-repetition traits for future episodes.", phase="creative", regeneratable=False),
    "visual_plan": NodeSpec("Visual plan", "data", ("retention_edit", "episode_director", "world_style_director", "character_resolution"), ("creative/VISUAL_PLAN.json", "VISUAL_BEATS.md"), phase="creative"),
    "world_keyframe_prompt": NodeSpec("Keyframe prompt", "text", ("retention_edit", "world_style_director"), ("references/world_keyframe_prompt.txt",), phase="visual"),
    "world_keyframe": NodeSpec("World keyframe", "image", ("world_keyframe_prompt", "world_style_anchor"), ("references/world_keyframe.png",), ("pipeline/provider_receipts/gemini_world_keyframe.json",), phase="visual"),
    "book_design_sheet": NodeSpec("Canonical book design", "image", description="Shared project-level book identity; inspected here but not owned by this episode.", phase="visual", regeneratable=False),
    "book_cover_design": NodeSpec("Book-cover direction", "text", artifacts=("creative/BOOK_COVER_DESIGN.txt",), description="Topic-specific motifs; independent of the narration draft.", phase="visual"),
    "book_cover": NodeSpec("Book cover", "image", ("book_cover_design", "world_style_anchor"), ("references/book_cover_frame.png",), ("pipeline/provider_receipts/gemini_book_cover.json",), phase="visual"),
    "flow_prompt_a": NodeSpec("Opening A prompt", "text", ("episode_director", "character_resolution", "retention_edit"), ("references/flow_prompt_opening_a.txt",), phase="opening"),
    "flow_prompt_b": NodeSpec("Opening B prompt", "text", ("world_style_director", "world_keyframe_prompt", "retention_edit"), ("references/flow_prompt_book_transition.txt",), phase="opening"),
    "flow_clip_a": NodeSpec("Opening A", "video", ("flow_prompt_a",), ("assets/opening/question_spark_source.mp4",), ("pipeline/provider_receipts/flow_opening_a.json",), phase="opening"),
    "flow_clip_b": NodeSpec("Opening B", "video", ("flow_prompt_b", "book_cover", "world_keyframe"), ("assets/opening/book_transition_source.mp4",), ("pipeline/provider_receipts/flow_opening_b.json",), phase="opening"),
    "elevenlabs_voiceover": NodeSpec("Narration", "audio", ("retention_edit",), ("assets/audio/narration.mp3",), ("voiceover/ELEVENLABS_RUNTIME_STATE.json",), phase="audio"),
    "background_music": NodeSpec("Music", "audio", ("elevenlabs_voiceover",), ("music/MUSIC_SELECTION.json",), ("music/MUSIC_PLAN.json",), "Selected music and every segment used by the mix.", "audio"),
    "ajil_alignment": NodeSpec("Voice alignment", "data", ("elevenlabs_voiceover", "retention_edit", "visual_plan"), ("timing/BEAT_TIMINGS.json", "timing/OPENING_TIMING.json"), ("timing/WORD_TIMINGS.json", "timing/BEAT_TIMINGS.md"), phase="audio"),
    "opening_trim": NodeSpec("Opening trims", "video", ("flow_clip_a", "flow_clip_b", "ajil_alignment"), ("assets/opening/question_spark_trimmed.mp4", "assets/opening/book_transition_trimmed.mp4"), ("timing/OPENING_TRIM_REPORT.json",), phase="opening"),
    "body_images": NodeSpec("Body images", "data", ("visual_plan",), description="Expandable milestone for the complete sequential beat-image chain.", phase="visual", regeneratable=False),
    "transition_direction": NodeSpec("Transition direction", "data", ("visual_plan", "body_images"), ("creative/TRANSITION_PLAN.json",), phase="edit"),
    "build_timeline": NodeSpec("Timeline", "data", ("opening_trim", "ajil_alignment", "transition_direction", "render_profile"), ("timeline/TIMELINE.json",), ("timeline/SUBTITLES.ass",), phase="edit"),
    "render_profile": NodeSpec("Render profile", "data", (), ("render/RENDER_PROFILE.json",), phase="edit"),
    "audio_mix_profile": NodeSpec("Audio mix", "data", ("background_music", "elevenlabs_voiceover"), ("audio_mix/AUDIO_MIX_PROFILE.json",), phase="audio"),
    "motion_director": NodeSpec("Motion direction", "data", ("build_timeline",), ("motion/MOTION_PLAN.json",), ("motion/MOTION_QC.json", "motion/COMPILED_MOTION_PLAN.json", "motion/MOTION_DIRECTION.json"), phase="edit"),
    "sfx_plan": NodeSpec("SFX plan", "data", ("build_timeline",), ("sfx/SFX_PLAN.json",), ("sfx/SFX_PLAN_RECEIPT.json",), phase="audio"),
    "render_baseline": NodeSpec("Baseline render", "video", ("build_timeline", "motion_director", "render_profile"), ("assets/renders/final.mp4",), ("render/RENDER_STATS.json",), phase="render"),
    "qc_baseline": NodeSpec("Baseline QC", "data", ("render_baseline",), ("render/QC_REPORT.json",), phase="render"),
    "sfx_acquire": NodeSpec("SFX selection", "audio", ("sfx_plan", "qc_baseline"), ("sfx/SFX_SELECTION.json",), phase="audio"),
    "polish_audio": NodeSpec("Polished render", "video", ("render_baseline", "sfx_acquire", "audio_mix_profile"), ("assets/renders/polished.mp4",), phase="render"),
    "qc_polished": NodeSpec("Final QC", "data", ("polish_audio",), ("render/QC_REPORT_polished.json",), phase="render"),
    "telegram_compress": NodeSpec("Telegram render", "video", ("qc_polished",), ("assets/renders/telegram_low.mp4",), ("render/TELEGRAM_RENDER_PROGRESS.json",), phase="publish"),
    "git_commit_push": NodeSpec("Git publish", "data", ("qc_polished",), ("pipeline/GIT_PUBLISH_STATE.json",), phase="publish"),
    "publish_telegram": NodeSpec("Telegram publish", "data", ("qc_polished", "telegram_compress"), ("publish/TELEGRAM_PUBLISH_STATE.json",), phase="publish"),
}

GENERIC_NODE_SPECS: dict[str, NodeSpec] = {
    "script_draft": NodeSpec("Script draft", "text", artifacts=("SCRIPT_DRAFT.md",), phase="creative"),
    "retention_edit": NodeSpec("Final script", "text", ("script_draft",), ("SCRIPT_FINAL.md",), phase="creative"),
    "episode_world_design": NodeSpec("Episode world", "text", ("retention_edit",), ("WORLD_DESIGN.md",), phase="creative"),
    "visual_plan": NodeSpec("Visual beats", "text", ("retention_edit",), ("VISUAL_BEATS.md",), phase="creative"),
    "visual_qc": NodeSpec("Visual QC", "data", (), ("visual_pipeline/VISUAL_QC_REPORT.json",), ("visual_pipeline/RUN_SUMMARY.md", "visual_pipeline/EXECUTION_TIMINGS.json"), phase="visual"),
    "elevenlabs_voiceover": NodeSpec("Narration", "audio", ("retention_edit",), ("assets/audio/narration.mp3",), ("voiceover/ELEVENLABS_RUNTIME_STATE.json",), phase="audio"),
    "ajil_alignment": NodeSpec("Voice alignment", "data", ("elevenlabs_voiceover", "retention_edit", "visual_plan"), ("timing/BEAT_TIMINGS.json",), ("timing/BEAT_TIMINGS.md", "timing/WORD_TIMINGS.json"), phase="audio"),
    "background_music": NodeSpec("Music", "audio", ("elevenlabs_voiceover",), ("music/MUSIC_SELECTION.json",), ("music/MUSIC_PLAN.json",), phase="audio"),
    "audio_mix_profile": NodeSpec("Audio mix", "data", ("background_music", "elevenlabs_voiceover"), ("audio_mix/AUDIO_MIX_PROFILE.json",), phase="audio"),
    "render_profile": NodeSpec("Render profile", "data", artifacts=("render/RENDER_PROFILE.json",), phase="edit"),
    "build_timeline": NodeSpec("Timeline", "data", ("visual_qc", "ajil_alignment", "render_profile"), ("timeline/TIMELINE.json",), ("timeline/SUBTITLES.ass",), phase="edit"),
    "motion_director": NodeSpec("Motion direction", "data", ("build_timeline",), ("motion/MOTION_PLAN.json",), ("motion/MOTION_QC.json", "motion/COMPILED_MOTION_PLAN.json"), phase="edit"),
    "sfx_plan": NodeSpec("SFX plan", "data", ("build_timeline",), ("sfx/SFX_PLAN.json",), phase="audio"),
    "render_baseline": NodeSpec("Baseline render", "video", ("build_timeline", "motion_director", "render_profile"), ("assets/renders/final.mp4",), ("render/RENDER_STATS.json",), phase="render"),
    "qc_baseline": NodeSpec("Baseline QC", "data", ("render_baseline",), ("render/QC_REPORT.json",), phase="render"),
    "sfx_acquire": NodeSpec("SFX selection", "audio", ("sfx_plan", "qc_baseline"), ("sfx/SFX_SELECTION.json",), phase="audio"),
    "polish_audio": NodeSpec("Polished render", "video", ("render_baseline", "sfx_acquire", "audio_mix_profile"), ("assets/renders/polished.mp4",), phase="render"),
    "qc_polished": NodeSpec("Final QC", "data", ("polish_audio",), ("render/QC_REPORT_polished.json",), phase="render"),
    "telegram_compress": NodeSpec("Telegram render", "video", ("qc_polished",), ("assets/renders/telegram_low.mp4",), phase="publish"),
    "git_commit_push": NodeSpec("Git publish", "data", ("qc_polished",), ("pipeline/GIT_PUBLISH_STATE.json",), phase="publish"),
    "publish_telegram": NodeSpec("Telegram publish", "data", ("qc_polished", "telegram_compress"), ("publish/TELEGRAM_PUBLISH_STATE.json",), phase="publish"),
}

MEDIA_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".mp4", ".mov", ".webm", ".mp3", ".wav", ".m4a", ".ogg", ".flac"}


def _edge(source: str, target: str) -> dict[str, str]:
    """Describe why an edge exists so scheduling and regeneration can treat it safely."""
    if source.startswith("beat_image_") and target.startswith("beat_image_"):
        kind = "continuity"
    elif source == "qc_baseline" and target == "sfx_acquire":
        kind = "gate"
    else:
        kind = "data"
    return {"source": source, "target": target, "kind": kind}


def _regeneration_metadata(node_id: str, regeneratable: bool = True) -> dict[str, Any]:
    if not regeneratable:
        return {"policy": "managed", "modes": [], "feedback": False}
    if node_id.startswith("beat_image_"):
        return {
            "policy": "continuity_cascade",
            "modes": ["cascade", "isolated"],
            "default_mode": "cascade",
            "feedback": True,
        }
    return {"policy": "cascade", "modes": ["cascade"], "default_mode": "cascade", "feedback": False}


def load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def project_mode(project: Path) -> str:
    launch = load(project / "launch/LAUNCH_REQUEST.json")
    content_project = str(launch.get("content_project") or "")
    if content_project:
        try:
            from content_projects import load_content_project
            if not load_content_project(content_project).is_question_harvest:
                return "generic"
        except RuntimeError:
            return "generic"
    if (project / "visual_pipeline/RUNTIME_STATE.json").is_file() and not (
        project / "pipeline/QH_RUNTIME_STATE.json"
    ).is_file():
        return "generic"
    return "question_harvest"


def _safe_relative_file(project: Path, value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        target = (project / value).resolve() if not Path(value).is_absolute() else Path(value).resolve()
        relative = target.relative_to(project.resolve())
    except ValueError:
        return None
    return str(relative)


def music_files(project: Path) -> list[str]:
    """Resolve provider-specific, multi-segment, and retained music assets."""
    found: list[str] = []
    plan = load(project / "music/MUSIC_PLAN.json")
    for segment in plan.get("segments") or []:
        relative = _safe_relative_file(project, segment.get("file") if isinstance(segment, dict) else None)
        if relative and relative not in found:
            found.append(relative)
    selection = load(project / "music/MUSIC_SELECTION.json")
    relative = _safe_relative_file(project, selection.get("file"))
    if relative and relative not in found:
        found.append(relative)
    # Include every provider-produced audio file, even when an old manifest references only
    # one of them. The background-music node owns this directory; invalidating only the
    # selected file could make the wrapper incorrectly reuse a stale alternative.
    for path in sorted((project / "assets/music").glob("*")):
        if path.is_file() and path.suffix.lower() in MEDIA_SUFFIXES:
            relative = str(path.relative_to(project))
            if relative not in found:
                found.append(relative)
    return found


def artifacts_for(project: Path, node_id: str, spec: NodeSpec | None = None) -> list[dict[str, Any]]:
    if node_id == "background_music":
        paths = music_files(project) + ["music/MUSIC_SELECTION.json", "music/MUSIC_PLAN.json"]
    elif node_id.startswith("beat_image_"):
        number = int(node_id.rsplit("_", 1)[1])
        paths = [f"assets/raw_beats/beat_{number:03d}.png", f"beats/BEAT_{number:03d}_PROMPT.md", f"beats/BEAT_{number:03d}_PROMPT.inputs.json", f"beats/BEAT_{number:03d}_PROMPT.revision.md", f"pipeline/provider_receipts/gemini_beat_{number:03d}.json"]
    else:
        spec = spec or NODE_SPECS[node_id]
        paths = list(spec.artifacts) + list(spec.optional_artifacts)
    unique = list(dict.fromkeys(paths))
    result: list[dict[str, Any]] = []
    for relative in unique:
        path = project / relative
        present = path.is_file()
        size = path.stat().st_size if present else None
        exists = present and bool(size)
        result.append({"path": relative, "exists": exists, "present": present, "bytes": size, "media": path.suffix.lower() in MEDIA_SUFFIXES, "updated_at": path.stat().st_mtime_ns if present else None})
    return result


def _beat_count(project: Path) -> int:
    count = len(load(project / "creative/VISUAL_PLAN.json").get("beats") or [])
    if count:
        return count
    count = len(load(project / "visual_pipeline/RUNTIME_STATE.json").get("beats") or {})
    if count:
        return count
    ids = [int(path.stem.rsplit("_", 1)[-1]) for path in project.glob("assets/raw_beats/beat_*.png") if path.stem.rsplit("_", 1)[-1].isdigit()]
    return max(ids, default=0)


def _generic_graph_for(
    project: Path,
    *,
    include_disabled: bool,
    settings: dict[str, Any] | None,
) -> dict[str, Any]:
    visual = load(project / "visual_pipeline/RUNTIME_STATE.json")
    full = load(project / "pipeline/FULL_PIPELINE_RUNTIME_STATE.json")
    final = load(project / "pipeline/FINALIZATION_RUNTIME_STATE.json")
    stages: dict[str, dict[str, Any]] = {
        str(name): entry
        for name, entry in (visual.get("stages") or {}).items()
        if isinstance(entry, dict)
    }
    if "visual_beats" in stages:
        stages["visual_plan"] = stages["visual_beats"]
    if "world_design" in stages:
        stages["episode_world_design"] = stages["world_design"]
    for number, entry in (visual.get("beats") or {}).items():
        if isinstance(entry, dict) and str(number).isdigit():
            stages[f"beat_image_{int(number):03d}"] = entry
    aliases = {
        "visuals": "visual_qc",
        "voiceover": "elevenlabs_voiceover",
        "timing": "ajil_alignment",
        "music": "background_music",
    }
    for entry in full.get("events") or []:
        if isinstance(entry, dict) and entry.get("stage"):
            stages[aliases.get(str(entry["stage"]), str(entry["stage"]))] = entry
    for entry in final.get("events") or []:
        if isinstance(entry, dict) and entry.get("stage"):
            stages[str(entry["stage"])] = entry

    launch = settings if isinstance(settings, dict) else load(project / "launch/LAUNCH_REQUEST.json")
    content_project = str(launch.get("content_project") or "default")
    specs = dict(GENERIC_NODE_SPECS)
    if content_project != "world_behind_the_question" and not (project / "WORLD_DESIGN.md").is_file():
        specs.pop("episode_world_design", None)
    visual_dependencies = ("retention_edit", "episode_world_design") if "episode_world_design" in specs else ("retention_edit",)
    specs["visual_plan"] = NodeSpec("Visual beats", "text", visual_dependencies, ("VISUAL_BEATS.md",), phase="creative")

    count = _beat_count(project)
    dependencies: dict[str, tuple[str, ...]] = {name: spec.dependencies for name, spec in specs.items()}
    beats = tuple(f"beat_image_{number:03d}" for number in range(1, count + 1))
    for index, node_id in enumerate(beats):
        dependencies[node_id] = (beats[index - 1],) if index else ("visual_plan",)
    dependencies["visual_qc"] = beats or ("visual_plan",)

    nodes: list[dict[str, Any]] = []
    for node_id in dependencies:
        if node_id.startswith("beat_image_"):
            number = int(node_id.rsplit("_", 1)[1])
            spec = None
            title, kind, phase, description = f"Beat {number:02d}", "image", "visual", "Continuity image for this narration beat."
            required = (f"assets/raw_beats/beat_{number:03d}.png",)
        else:
            spec = specs[node_id]
            title, kind, phase, description, required = spec.title, spec.kind, spec.phase, spec.description, spec.artifacts
            if node_id == "background_music":
                required = (*music_files(project), "music/MUSIC_SELECTION.json")
        artifacts = artifacts_for(project, node_id, spec)
        entry = stages.get(node_id, {})
        required_ok = bool(required) and all(
            (project / relative).is_file() and (project / relative).stat().st_size > 0
            for relative in required
        )
        status = str(entry.get("status") or ("DONE" if required_ok else "PENDING"))
        if status in {"DONE", "REUSED"} and required and not required_ok:
            status = "MISSING"
        regeneratable = spec.regeneratable if spec is not None else True
        nodes.append({"id": node_id, "title": title, "kind": kind, "phase": phase, "description": description, "status": status, "artifacts": artifacts, "meta": entry, "regeneratable": regeneratable, "regeneration": _regeneration_metadata(node_id, regeneratable)})
    edges = [_edge(dependency, node_id) for node_id, deps in dependencies.items() for dependency in deps if dependency in dependencies]
    if not include_disabled:
        disabled = disabled_nodes(project, settings)
        nodes = [node for node in nodes if node["id"] not in disabled]
        visible = {node["id"] for node in nodes}
        edges = [edge for edge in edges if edge["source"] in visible and edge["target"] in visible]
    return {"schema_version": 2, "mode": "generic", "nodes": nodes, "edges": edges, "phases": ["creative", "visual", "audio", "edit", "render", "publish"]}


def disabled_nodes(project: Path, settings: dict[str, Any] | None = None) -> set[str]:
    """Stages not selected by this run's frozen feature configuration."""
    launch = settings if isinstance(settings, dict) else load(project / "launch/LAUNCH_REQUEST.json")
    motion = launch.get("motion")
    sfx = launch.get("sfx")
    motion_enabled = bool(motion.get("enabled", True)) if isinstance(motion, dict) else (project / "motion/MOTION_PLAN.json").is_file()
    sfx_enabled = bool(sfx.get("enabled", False)) if isinstance(sfx, dict) else (project / "sfx/SFX_PLAN.json").is_file()
    disabled: set[str] = set()
    if not motion_enabled:
        disabled.add("motion_director")
    if not sfx_enabled:
        disabled.update(("sfx_plan", "sfx_acquire"))
    if not bool(launch.get("commit_artifacts", (project / "pipeline/GIT_PUBLISH_STATE.json").is_file())):
        disabled.add("git_commit_push")
    if not bool(launch.get("telegram_low_size", True)):
        disabled.add("telegram_compress")
    return disabled


def graph_for(
    project: Path,
    *,
    include_disabled: bool = False,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if project_mode(project) == "generic":
        return _generic_graph_for(
            project,
            include_disabled=include_disabled,
            settings=settings,
        )
    qh = load(project / "pipeline/QH_RUNTIME_STATE.json")
    wrapper = load(project / "pipeline/WRAPPER_RUNTIME_STATE.json")
    final = load(project / "pipeline/FINALIZATION_RUNTIME_STATE.json")
    stages = dict(qh.get("stages") or {})
    for item in wrapper.get("events") or []:
        if item.get("stage"):
            stages[str(item["stage"])] = {**item, "status": item.get("status", "PENDING")}
    for item in final.get("events") or []:
        if item.get("stage"):
            stages[str(item["stage"])] = {**item, "status": item.get("status", "PENDING")}
    count = _beat_count(project)
    dependencies: dict[str, tuple[str, ...]] = {name: spec.dependencies for name, spec in NODE_SPECS.items()}
    if count:
        beats = tuple(f"beat_image_{number:03d}" for number in range(1, count + 1))
        for index, node_id in enumerate(beats):
            dependencies[node_id] = (beats[index - 1],) if index else ("visual_plan", "world_keyframe", "world_style_anchor")
        dependencies["body_images"] = beats
    nodes: list[dict[str, Any]] = []
    for node_id in dependencies:
        if node_id.startswith("beat_image_"):
            number = int(node_id.rsplit("_", 1)[1])
            title, kind, phase, description, required, spec = f"Beat {number:02d}", "image", "visual", "Continuity image for this narration beat.", (f"assets/raw_beats/beat_{number:03d}.png",), None
        else:
            spec = NODE_SPECS[node_id]
            title, kind, phase, description, required = spec.title, spec.kind, spec.phase, spec.description, spec.artifacts
            if node_id == "background_music":
                required = (*music_files(project), "music/MUSIC_SELECTION.json")
        artifacts = artifacts_for(project, node_id, spec)
        entry = stages.get(node_id, {}) if isinstance(stages.get(node_id), dict) else {}
        required_ok = bool(required) and all(
            (project / relative).is_file() and (project / relative).stat().st_size > 0
            for relative in required
        )
        status = str(entry.get("status") or ("DONE" if required_ok else "PENDING"))
        if status in {"DONE", "REUSED"} and required and not required_ok:
            status = "MISSING"
        validation = None
        if kind == "image":
            receipt = next((item for item in artifacts if "provider_receipts/gemini_" in item["path"]), None)
            if receipt:
                validation = receipt_status(project, project / required[0], project / receipt["path"])
                if status in {"DONE", "REUSED"} and validation["status"] != "verified":
                    status = validation["status"].upper()
            elif node_id == "world_style_anchor" and entry.get("reuse_of"):
                validation = {"status": "catalog", "reason": "Reused catalog style anchor"}
        regeneratable = spec.regeneratable if spec is not None else True
        nodes.append({"id": node_id, "title": title, "kind": kind, "phase": phase, "description": description, "status": status, "artifacts": artifacts, "meta": entry, "regeneratable": regeneratable, "regeneration": _regeneration_metadata(node_id, regeneratable), "validation": validation})

    edges = [_edge(dependency, node_id) for node_id, deps in dependencies.items() for dependency in deps if dependency in dependencies]
    if not include_disabled:
        disabled = disabled_nodes(project, settings)
        nodes = [node for node in nodes if node["id"] not in disabled]
        visible = {node["id"] for node in nodes}
        edges = [edge for edge in edges if edge["source"] in visible and edge["target"] in visible]
    return {"schema_version": 2, "mode": "question_harvest", "nodes": nodes, "edges": edges, "phases": ["creative", "visual", "opening", "audio", "edit", "render", "publish"]}


def descendants(graph: dict[str, Any], root: str) -> set[str]:
    return affected_nodes(graph, [root])


def affected_nodes(
    graph: dict[str, Any], roots: Iterable[str], *, regeneration_mode: str = "cascade"
) -> set[str]:
    node_ids = {str(node.get("id")) for node in graph.get("nodes") or []}
    requested = {str(root) for root in roots}
    unknown = requested - node_ids
    if unknown:
        raise ValueError(f"Unknown graph node(s): {', '.join(sorted(unknown))}")
    forward: dict[str, set[str]] = {}
    for edge in graph.get("edges") or []:
        if regeneration_mode == "isolated" and edge.get("kind") == "continuity":
            continue
        forward.setdefault(str(edge["source"]), set()).add(str(edge["target"]))
    found, queue = set(requested), list(requested)
    while queue:
        current = queue.pop(0)
        for child in forward.get(current, set()):
            if child not in found:
                found.add(child)
                queue.append(child)
    return found


def regeneration_plan(
    project: Path,
    roots: Iterable[str],
    *,
    include_disabled: bool = False,
    settings: dict[str, Any] | None = None,
    skip_disabled_descendants: bool = False,
    regeneration_mode: str = "cascade",
) -> dict[str, Any]:
    if regeneration_mode not in {"cascade", "isolated"}:
        raise ValueError("Regeneration mode must be cascade or isolated.")
    graph = graph_for(project, include_disabled=include_disabled, settings=settings)
    root_list = list(dict.fromkeys(str(root) for root in roots))
    node_map = {str(node.get("id")): node for node in graph.get("nodes") or []}
    unknown = set(root_list) - set(node_map)
    if unknown:
        raise ValueError(f"Unknown graph node(s): {', '.join(sorted(unknown))}")
    managed = [node_id for node_id in root_list if node_map[node_id].get("regeneratable") is False]
    if managed:
        raise ValueError("These stages are managed automatically and cannot be regenerated directly: " + ", ".join(managed))
    if regeneration_mode == "isolated" and (
        len(root_list) != 1 or not root_list[0].startswith("beat_image_")
    ):
        raise ValueError("Isolated regeneration is available for one beat image at a time.")
    affected = affected_nodes(graph, root_list, regeneration_mode=regeneration_mode)
    skipped: set[str] = set()
    if skip_disabled_descendants:
        skipped = (affected & disabled_nodes(project, settings)) - set(root_list)
        affected -= skipped
    ordered = [node["id"] for node in graph["nodes"]]
    return {
        "roots": root_list,
        "regeneration_mode": regeneration_mode,
        "affected_nodes": [node_id for node_id in ordered if node_id in affected],
        "reused_nodes": [node_id for node_id in ordered if node_id not in affected and node_id not in skipped],
        "skipped_nodes": [node_id for node_id in ordered if node_id in skipped],
    }


def invalidation_paths(project: Path, node_ids: Iterable[str]) -> list[str]:
    """All existing project-local files owned by the selected nodes."""
    paths: list[str] = []
    specs = GENERIC_NODE_SPECS if project_mode(project) == "generic" else NODE_SPECS
    for node_id in node_ids:
        for artifact in artifacts_for(project, node_id, specs.get(node_id)):
            if artifact["present"] and artifact["path"] not in paths:
                paths.append(str(artifact["path"]))
    return paths
