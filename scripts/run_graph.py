"""Canonical control-panel DAG and artifact discovery.

The pipeline executors are still mostly sequential, but this registry describes data
dependencies. The panel, regeneration planner and tests consume the same definition so the
visible graph cannot silently diverge from invalidation behaviour.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, replace
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
    "preflight": NodeSpec("Pipeline preflight", "gate", (), ("launch/LAUNCH_REQUEST.json",), description="Validates frozen settings, provider readiness and source contracts before credits are spent.", phase="creative", regeneratable=False),
    "character_resolution": NodeSpec("Character & presentation resolution", "data", ("preflight",), ("creative/CHARACTER_RESOLUTION.json",), ("creative/PRESENTATION_RESOLUTION.json",), description="One-time Auto/manual host and opening-format resolution.", phase="creative"),
    "opening_concept": NodeSpec("Opening story selection", "data", ("character_resolution",), ("creative/OPENING_CONCEPT.json", "creative/OPENING_CONTEXT.json", "creative/OPENING_CANDIDATES.json"), description="Three topic-first mini-stories, independent selection and frozen semantic history.", phase="creative"),
    "script_draft": NodeSpec("Script draft", "text", ("opening_concept", "character_resolution"), ("creative/SCRIPT_DRAFT.json",), ("creative/script_draft.inputs.json",), description="Initial script using the resolved presentation grammar.", phase="creative"),
    "retention_edit": NodeSpec("Retained script core", "text", ("script_draft",), ("creative/SCRIPT_CORE_PLAN.json",), ("creative/retention_edit.inputs.json", "creative/CORE_LANGUAGE_REVIEW.json"), description="Retention-edited, plain-English-reviewed core before the final CTA.", phase="creative"),
    "call_to_action": NodeSpec("Call to action", "text", ("retention_edit",), ("creative/CALL_TO_ACTION.json", "creative/SCRIPT_PLAN.json", "SCRIPT_FINAL.md"), ("creative/CTA_LANGUAGE_REVIEW.json",), description="Plain-English-reviewed, topic-aware closing CTA, optionally steered by the operator without copying their wording.", phase="creative"),
    # CTA wording is spoken only after the visual story is complete. Keeping it out of the
    # episode-direction branch lets a CTA revision preserve valid visual planning and images.
    "episode_director": NodeSpec("Episode direction", "data", ("retention_edit", "character_resolution", "opening_concept"), ("creative/EPISODE_PLAN.json",), ("creative/OPENING_REVIEW.json",), description="Staging and a blocking story-consistency review before narration/media.", phase="creative"),
    "world_style_director": NodeSpec("World style", "data", ("retention_edit",), ("creative/WORLD_STYLE_PLAN.json",), phase="creative"),
    "world_style_anchor": NodeSpec("Style anchor", "image", ("world_style_director",), ("references/world_style_anchor.png",), ("pipeline/provider_receipts/gemini_world_style_anchor.json",), phase="visual"),
    "episode_history": NodeSpec("Episode history", "data", ("episode_director", "world_style_director"), description="Records anti-repetition traits for future episodes.", phase="creative", regeneratable=False),
    "visual_plan": NodeSpec("Visual plan", "data", ("retention_edit", "episode_director", "world_style_director", "character_resolution"), ("creative/VISUAL_PLAN.json", "VISUAL_BEATS.md"), phase="creative"),
    "world_keyframe_prompt": NodeSpec("Keyframe prompt", "text", ("retention_edit", "world_style_director"), ("references/world_keyframe_prompt.txt",), phase="visual"),
    "world_keyframe": NodeSpec("World keyframe", "image", ("world_keyframe_prompt", "world_style_anchor"), ("references/world_keyframe.png",), ("pipeline/provider_receipts/gemini_world_keyframe.json",), phase="visual"),
    "book_design_sheet": NodeSpec("Canonical book design", "image", description="Shared project-level book identity; inspected here but not owned by this episode.", phase="visual", regeneratable=False),
    "book_cover_design": NodeSpec("Book-cover direction", "text", ("episode_director",), ("creative/BOOK_COVER_DESIGN.txt",), description="Topic-specific entry-frame motifs and staging.", phase="visual"),
    "book_cover": NodeSpec("Book cover", "image", ("book_cover_design", "book_design_sheet", "world_style_anchor", "episode_director", "character_resolution"), ("references/book_cover_frame.png",), ("pipeline/provider_receipts/gemini_book_cover.json",), phase="visual"),
    "opening_source_plan": NodeSpec("Opening source plan", "data", ("ajil_alignment",), ("timing/OPENING_SOURCE_PLAN.json",), description="Measured narration boundaries mapped to supported Flow source durations.", phase="audio"),
    "flow_prompt_a": NodeSpec("Opening A prompt", "text", ("episode_director", "character_resolution", "retention_edit", "opening_source_plan"), ("references/flow_prompt_opening_a.txt",), ("references/flow_prompt_question_intro.txt.inputs.json",), phase="opening"),
    "flow_prompt_b": NodeSpec("Opening B prompt", "text", ("world_style_director", "world_keyframe_prompt", "retention_edit", "character_resolution", "opening_source_plan", "episode_director", "book_cover_design"), ("references/flow_prompt_book_transition.txt",), ("references/flow_prompt_orb_transition.txt.inputs.json",), phase="opening"),
    "flow_clip_a": NodeSpec("Opening A", "video", ("flow_prompt_a",), ("assets/opening/question_spark_source.mp4",), ("pipeline/provider_receipts/flow_opening_a.json",), phase="opening"),
    "flow_clip_b": NodeSpec("Opening B", "video", ("flow_prompt_b", "book_cover", "world_keyframe"), ("assets/opening/book_transition_source.mp4",), ("pipeline/provider_receipts/flow_opening_b.json",), phase="opening"),
    "elevenlabs_voiceover": NodeSpec("Narration", "audio", ("call_to_action",), ("assets/audio/narration.mp3",), ("voiceover/ELEVENLABS_RUNTIME_STATE.json",), phase="audio"),
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
    "publish_telegram": NodeSpec("Telegram publish", "data", ("qc_polished", "telegram_compress"), ("publish/TELEGRAM_PUBLISH_STATE.json",), phase="publish"),
    "git_commit_push": NodeSpec("Git publish", "data", ("publish_telegram",), ("pipeline/GIT_PUBLISH_STATE.json",), description="Final repository publication after enabled delivery receipts are durable.", phase="publish"),
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
    "publish_telegram": NodeSpec("Telegram publish", "data", ("qc_polished", "telegram_compress"), ("publish/TELEGRAM_PUBLISH_STATE.json",), phase="publish"),
    "git_commit_push": NodeSpec("Git publish", "data", ("publish_telegram",), ("pipeline/GIT_PUBLISH_STATE.json",), phase="publish"),
}

MEDIA_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".mp4", ".mov", ".webm", ".mp3", ".wav", ".m4a", ".ogg", ".flac"}


def _edge(source: str, target: str) -> dict[str, str]:
    """Describe why an edge exists so scheduling and regeneration can treat it safely."""
    if source.startswith("beat_image_") and target.startswith("beat_image_"):
        kind = "continuity"
    elif source == "preflight" or (source == "qc_baseline" and target == "sfx_acquire"):
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
    # Q Station has a complete production executor and graph.  Shorts V2 is a
    # separate plan-only contract; stale panel controls must not replace the
    # graph for an actual Q Station episode.
    if isinstance(launch.get("qstation"), dict) or isinstance(launch.get("_q_station"), dict):
        return "qstation"
    engine_source: dict[str, Any] = launch
    try:
        from shorts_v2.contracts import normalize_engine_settings
        engine = normalize_engine_settings(engine_source)
        if engine["editing_engine"] == "legacy":
            engine_source = load(project / "launch/CREATIVE_BRIEF.json")
            engine = normalize_engine_settings(engine_source)
        if engine["editing_engine"] == "shorts_v2":
            return "shorts_v2"
    except ImportError:
        pass
    except ValueError:
        # A malformed *explicit* v2 marker must fail closed.  Swallowing the
        # error here would silently route it into the legacy Q-Station graph.
        if isinstance(engine_source.get("_shorts_v2"), dict) and engine_source["_shorts_v2"].get("editing_engine") == "shorts_v2":
            raise
    content_project = str(launch.get("content_project") or "")
    if content_project:
        try:
            from content_projects import load_content_project
            if not load_content_project(content_project).is_q_station:
                return "generic"
        except RuntimeError:
            return "generic"
    if (project / "visual_pipeline/RUNTIME_STATE.json").is_file() and not (
        project / "pipeline/Q_STATION_RUNTIME_STATE.json"
    ).is_file():
        return "generic"
    return "q_station"


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


def q_station_node_specs(project: Path, settings: dict[str, Any] | None = None) -> dict[str, NodeSpec]:
    """Profile-aware QStation specs while retaining durable historical stage ids.

    A manual character change can preview its destination presentation before the old
    resolution is archived. Auto intentionally keeps the current profile until its selector
    has produced the new persisted resolution.
    """
    from presentation_runtime import presentation_for_project
    presentation = presentation_for_project(project)
    if isinstance(settings, dict):
        qstation = settings.get("qstation") if isinstance(settings.get("qstation"), dict) else {}
        request = qstation.get("character") if isinstance(qstation.get("character"), dict) else settings.get("character")
        if isinstance(request, dict) and request.get("mode") == "manual" and request.get("character_id"):
            from character_runtime import load_character_registry
            from content_projects import character_registry_path, load_content_project
            content = load_content_project(str(settings.get("content_project") or "q_station"))
            registry_path = character_registry_path(content)
            if registry_path is not None:
                presentation = load_character_registry(registry_path).get(str(request["character_id"])).presentation
    a = presentation.artifacts
    label = presentation.entry_kind.title()
    specs = dict(NODE_SPECS)
    if (project / "creative/SCRIPT_DRAFT.json").is_file() and not (project / "creative/OPENING_CONCEPT.json").is_file():
        specs["opening_concept"] = replace(specs["opening_concept"], artifacts=(), description="Legacy retained opening; new runs use reviewed story selection.")
    else:
        # A new direction is usable only with its actual story review, not a bare plan.
        specs["episode_director"] = replace(specs["episode_director"], artifacts=("creative/EPISODE_PLAN.json", "creative/OPENING_REVIEW.json"), optional_artifacts=())

    # New language-reviewed work owns its receipt. Legacy completed work has no marker.
    for owner, metadata_path, receipt in (
        ("retention_edit", "creative/retention_edit.inputs.json", "creative/CORE_LANGUAGE_REVIEW.json"),
        ("call_to_action", "creative/CALL_TO_ACTION.json", "creative/CTA_LANGUAGE_REVIEW.json"),
    ):
        if load(project / metadata_path).get("language_review_required"):
            spec = specs[owner]
            specs[owner] = replace(spec, artifacts=(*spec.artifacts, receipt),
                                   optional_artifacts=tuple(p for p in spec.optional_artifacts if p != receipt))

    specs["book_design_sheet"] = replace(specs["book_design_sheet"], title=f"{label} identity", description="Shared recurring entry-object identity; not owned by this episode.")
    specs["book_cover_design"] = replace(specs["book_cover_design"], title=f"{label} frame direction", artifacts=(a.entry_direction,))
    specs["book_cover"] = replace(specs["book_cover"], title=f"Topic-styled {presentation.entry_kind} frame", artifacts=(a.entry_frame,), optional_artifacts=(a.entry_image_receipt,))
    if presentation.entry_frame_character_presence == "acting_host":
        spec = specs["book_cover"]
        specs["book_cover"] = replace(spec, dependencies=(*spec.dependencies, "world_keyframe"))
    spec = specs["book_cover_design"]
    specs["book_cover_design"] = replace(spec, optional_artifacts=(str(Path(a.entry_direction).with_suffix(".inputs.json")),))
    spec = specs["world_keyframe_prompt"]
    specs["world_keyframe_prompt"] = replace(spec, optional_artifacts=("references/world_keyframe_prompt.inputs.json",))
    specs["flow_prompt_a"] = replace(specs["flow_prompt_a"], title="Question intro prompt", artifacts=(a.question_prompt,), optional_artifacts=(f"{a.question_prompt}.inputs.json",))
    specs["flow_prompt_b"] = replace(specs["flow_prompt_b"], title=f"{label} entry prompt", artifacts=(a.entry_prompt,), optional_artifacts=(f"{a.entry_prompt}.inputs.json",))
    specs["flow_clip_a"] = replace(specs["flow_clip_a"], title="Question intro", artifacts=(a.question_source,))
    specs["flow_clip_b"] = replace(specs["flow_clip_b"], title=f"{label} entry", artifacts=(a.entry_source,))
    specs["opening_trim"] = replace(specs["opening_trim"], artifacts=(a.question_trimmed, a.entry_trimmed))
    return specs


def _beat_count(project: Path) -> int:
    script = load(project / "creative/SCRIPT_PLAN.json")
    body = script.get("body")
    expected = len(body) if isinstance(body, list) else 0
    if expected and str(script.get("optional_closing") or "").strip():
        expected += 1
    if expected:
        return expected
    count = len(load(project / "creative/VISUAL_PLAN.json").get("beats") or [])
    if count:
        return count
    count = len(load(project / "visual_pipeline/RUNTIME_STATE.json").get("beats") or {})
    if count:
        return count
    ids = [int(path.stem.rsplit("_", 1)[-1]) for path in project.glob("assets/raw_beats/beat_*.png") if path.stem.rsplit("_", 1)[-1].isdigit()]
    return max(ids, default=0)


def visual_plan_contract_matches(project: Path) -> bool:
    """Every body/closing unit before CTA must own exactly one ordered visual beat."""
    script = load(project / "creative/SCRIPT_PLAN.json")
    body = script.get("body")
    if not isinstance(body, list) or not body:
        return True
    expected = [str(item).strip() for item in body]
    closing = str(script.get("optional_closing") or "").strip()
    if closing:
        expected.append(closing)
    beats = load(project / "creative/VISUAL_PLAN.json").get("beats") or []
    actual = [str(item.get("narration_slice") or "").strip() for item in beats if isinstance(item, dict)]
    ids = [item.get("beat_id") for item in beats if isinstance(item, dict)]
    return actual == expected and ids == list(range(1, len(expected) + 1))


def _generic_graph_for(
    project: Path,
    *,
    include_disabled: bool,
    settings: dict[str, Any] | None,
) -> dict[str, Any]:
    visual = load(project / "visual_pipeline/RUNTIME_STATE.json")
    full = load(project / "pipeline/FULL_PIPELINE_RUNTIME_STATE.json")
    final = load(project / "pipeline/FINALIZATION_RUNTIME_STATE.json")
    terminal_failed = any(
        str(payload.get("status") or "") in {"FAILED", "STOPPED", "INTERRUPTED"}
        for payload in (visual, full, final)
    )
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
    if content_project != "q_station" and not (project / "WORLD_DESIGN.md").is_file():
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
        if status == "RUNNING" and terminal_failed:
            status = "FAILED"
        if status in {"DONE", "REUSED"} and required and not required_ok:
            status = "MISSING"
        if node_id == "visual_plan" and not visual_plan_contract_matches(project):
            status = "STALE"
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
    mode = project_mode(project)
    if mode == "shorts_v2":
        from shorts_v2.contracts import normalize_engine_settings
        from shorts_v2.registry import effective_graph

        source = settings if isinstance(settings, dict) else load(project / "launch/LAUNCH_REQUEST.json")
        normalized = normalize_engine_settings(source)
        if normalized["editing_engine"] == "legacy":
            normalized = normalize_engine_settings(load(project / "launch/CREATIVE_BRIEF.json"))
        if normalized["editing_engine"] != "shorts_v2":
            raise ValueError("Shorts V2 project has no valid explicit engine contract.")
        graph = effective_graph(normalized, include_disabled=include_disabled)
        state = load(project / "shorts_v2/versions/initial/diagnostics/RUNTIME_STATE.json")
        stage_state = state.get("stages") if isinstance(state.get("stages"), dict) else {}
        for node in graph["nodes"]:
            entry = stage_state.get(node["id"])
            if isinstance(entry, dict):
                node["status"] = str(entry.get("status") or node["status"])
                node["meta"] = entry
        return graph
    if mode == "generic":
        return _generic_graph_for(
            project,
            include_disabled=include_disabled,
            settings=settings,
        )
    qstation = load(project / "pipeline/Q_STATION_RUNTIME_STATE.json")
    wrapper = load(project / "pipeline/WRAPPER_RUNTIME_STATE.json")
    final = load(project / "pipeline/FINALIZATION_RUNTIME_STATE.json")
    terminal_failed = any(
        str(payload.get("status") or "") in {"FAILED", "STOPPED", "INTERRUPTED"}
        for payload in (qstation, wrapper, final)
    )
    stages = dict(qstation.get("stages") or {})
    for item in wrapper.get("events") or []:
        if item.get("stage"):
            stages[str(item["stage"])] = {**item, "status": item.get("status", "PENDING")}
    for item in final.get("events") or []:
        if item.get("stage"):
            stages[str(item["stage"])] = {**item, "status": item.get("status", "PENDING")}
    count = _beat_count(project)
    specs = q_station_node_specs(project, settings)
    dependencies: dict[str, tuple[str, ...]] = {name: spec.dependencies for name, spec in specs.items()}
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
            spec = specs[node_id]
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
        if status == "RUNNING" and terminal_failed:
            status = "FAILED"
        if status in {"DONE", "REUSED"} and required and not required_ok:
            status = "MISSING"
        if node_id == "visual_plan" and not visual_plan_contract_matches(project):
            status = "STALE"
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

    # The body-images card is a milestone, not a second independently executed
    # operation. Derive it from its expanded beat nodes so it can never disagree
    # with the actual image chain after a crash or isolated revision.
    if count:
        node_map = {node["id"]: node for node in nodes}
        beat_states = [node_map[f"beat_image_{number:03d}"]["status"] for number in range(1, count + 1)]
        body = node_map.get("body_images")
        if body is not None:
            if any(value in {"FAILED", "MISSING", "STALE", "INVALID"} for value in beat_states):
                body["status"] = "FAILED"
            elif any(value == "RUNNING" for value in beat_states):
                body["status"] = "RUNNING"
            elif all(value in {"DONE", "REUSED"} for value in beat_states):
                body["status"] = "DONE"
            else:
                body["status"] = "PENDING"
            body["meta"] = {**body.get("meta", {}), "derived_from": [f"beat_image_{number:03d}" for number in range(1, count + 1)]}

    edges = [_edge(dependency, node_id) for node_id, deps in dependencies.items() for dependency in deps if dependency in dependencies]
    if not include_disabled:
        disabled = disabled_nodes(project, settings)
        nodes = [node for node in nodes if node["id"] not in disabled]
        visible = {node["id"] for node in nodes}
        edges = [edge for edge in edges if edge["source"] in visible and edge["target"] in visible]
    return {"schema_version": 2, "mode": "q_station", "nodes": nodes, "edges": edges, "phases": ["creative", "visual", "opening", "audio", "edit", "render", "publish"]}


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
    specs = GENERIC_NODE_SPECS if project_mode(project) == "generic" else q_station_node_specs(project)
    for node_id in node_ids:
        for artifact in artifacts_for(project, node_id, specs.get(node_id)):
            if artifact["present"] and artifact["path"] not in paths:
                paths.append(str(artifact["path"]))
    return paths
