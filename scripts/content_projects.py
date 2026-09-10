#!/usr/bin/env python3
"""Resolve channel/content-project configuration without coupling it to video jobs."""
from __future__ import annotations
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PROJECTS_ROOT = ROOT / "projects"
DEFAULT_CONTENT_PROJECT = "default"
PROJECT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
PIPELINE_PROMPTS = (
    "01_script_writer.md",
    "02_retention_editor.md",
    "03_visual_beats.md",
    "04_single_beat_image_prompt_writer.md",
)

# Q Station / legacy Question Harvest (bookworld_mixed_media) uses 9 prompts per §46
QH_PIPELINE_PROMPTS = (
    "01_script_writer.md",
    "02_retention_editor.md",
    "03_episode_director.md",
    "04_world_style_director.md",
    "05_visual_beat_planner.md",
    "06_world_keyframe_prompt_writer.md",
    "07_single_beat_image_prompt_writer.md",
    "08_opening_video_prompt_writer.md",
    "09_book_transition_video_prompt_writer.md",
)

# Flow reference policy lives in exactly one module (scripts/flow_reference_policy.py).
# These re-exports keep older call sites working without duplicating the rules.
from flow_reference_policy import (  # noqa: E402  (re-export)
    ALLOWED_CANONICAL_ROLES as FLOW_ALLOWED_CANONICAL_ROLES,
    ALLOWED_FRAME_ROLES as FLOW_ALLOWED_FRAME_ROLES,
    ALLOWED_ROLES as FLOW_ALLOWED_REFERENCE_ROLES,
    CLIP_CANONICAL_ROLE as FLOW_CLIP_CANONICAL_ROLE,
    FORBIDDEN_ROLES as FLOW_FORBIDDEN_REFERENCE_ROLES,
    FlowReferencePolicyError,
    build_flow_uploads,
    canonical_role_for_clip,
    clip_a_roles,
    clip_b_roles,
    validate_flow_roles as validate_flow_reference_roles,
)

# Gemini image model / Flow video model normalization
GEMINI_MODEL_ALIASES = {
    "nano_banana_pro": "nano_banana_pro",
    "nano-banana-pro": "nano_banana_pro",
    "Nano Banana Pro": "nano_banana_pro",
    "nano_banana_2": "nano_banana_2",
    "nano-banana-2": "nano_banana_2",
    "Nano Banana 2": "nano_banana_2",
}
FLOW_MODEL_ALIASES = {
    "gemini_omni_1_1_flash": "gemini_omni_1_1_flash",
    "gemini omni 1.1 flash": "gemini_omni_1_1_flash",
    "Gemini Omni 1.1 Flash": "gemini_omni_1_1_flash",
    "veo_3_1_quality": "veo_3_1_quality",
    "veo 3.1 quality": "veo_3_1_quality",
    "Veo 3.1 Quality": "veo_3_1_quality",
    "veo_3_1_fast": "veo_3_1_fast",
    "Veo 3.1 Fast": "veo_3_1_fast",
    "veo_3_1_lite": "veo_3_1_lite",
    "Veo 3.1 Lite": "veo_3_1_lite",
}

@dataclass(frozen=True)
class ContentProject:
    project_id: str
    root: Path
    config: dict[str, Any]

    @property
    def display_name(self) -> str:
        return str(self.config.get("display_name") or self.project_id)

    @property
    def aliases(self) -> tuple[str, ...]:
        raw = self.config.get("aliases")
        if not isinstance(raw, list):
            return ()
        return tuple(str(item).strip() for item in raw if str(item).strip())

    @property
    def pipeline_profile(self) -> str:
        return str(self.config.get("pipeline_profile") or "default").strip().lower()

    @property
    def is_question_harvest(self) -> bool:
        # Capability, not identity: the bookworld mixed-media profile is what makes a
        # project drive the Q Station / question-harvest runtime. Keyed on the profile
        # (not a hardcoded id) so the canonical q_station project and its legacy
        # question_harvest alias both qualify without scattered id checks.
        return self.pipeline_profile == "bookworld_mixed_media"

    @property
    def default_visual_preset(self) -> str:
        value = str(self.config.get("default_visual_preset") or "").strip()
        if not value:
            raise RuntimeError(f"Content project {self.project_id!r} has no default_visual_preset.")
        return value

    def provider_config(self, kind: str) -> dict[str, Any]:
        providers = self.config.get("providers") or {}
        cfg = providers.get(kind) if isinstance(providers, dict) else None
        return dict(cfg) if isinstance(cfg, dict) else {}

    def get_provider(self, kind: str) -> str:
        cfg = self.provider_config(kind)
        # legacy projects may not have providers block → infer
        if not cfg:
            if kind == "text":
                return "chatgpt"
            if kind == "image":
                return "chatgpt" if self.project_id == "default" else "gemini" if self.project_id == "world_behind_the_question" else "gemini"
            if kind == "video":
                return "flow" if self.is_question_harvest else "none"
            return "unknown"
        return str(cfg.get("provider") or "").strip().lower()

    def get_default_model(self, kind: str) -> str | None:
        cfg = self.provider_config(kind)
        if kind == "image":
            return str(cfg.get("default_model") or self.config.get("defaults", {}).get("gemini_image_model") or "").strip() or None
        if kind == "video":
            return str(cfg.get("default_model") or self.config.get("defaults", {}).get("flow_video_model") or "").strip() or None
        return None


def video_slug(value: str) -> str:
    """Canonical video-directory slug used by panel and every runner."""
    result = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return result or "video"

def _load_project_dir(dir_name: str) -> ContentProject | None:
    """Load the project whose directory is ``dir_name`` if it is well-formed."""
    root = PROJECTS_ROOT / dir_name
    config_path = root / "PROJECT.json"
    if not config_path.is_file():
        return None
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if config.get("project_id") != dir_name:
        raise RuntimeError(f"{config_path.relative_to(ROOT)} project_id does not match its directory.")
    return ContentProject(dir_name, root, config)


def resolve_project_id(project_id: str) -> str:
    """Map any requested id (canonical or legacy alias) to its canonical project id.

    This is the single place aliases are resolved. A directory whose config declares
    its own id wins; a compatibility symlink/config that declares the request as an
    alias resolves to the declared canonical id. Otherwise declared aliases are scanned.
    """
    project_id = project_id.strip()
    if not PROJECT_ID_RE.fullmatch(project_id):
        raise RuntimeError(f"Invalid content-project id: {project_id!r}")
    direct_config = PROJECTS_ROOT / project_id / "PROJECT.json"
    if direct_config.is_file():
        try:
            direct_payload = json.loads(direct_config.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Malformed content project config: {direct_config.relative_to(ROOT)}") from exc
        declared_id = str(direct_payload.get("project_id") or "")
        if declared_id == project_id:
            return project_id
        aliases = direct_payload.get("aliases") if isinstance(direct_payload.get("aliases"), list) else []
        if project_id in aliases and PROJECT_ID_RE.fullmatch(declared_id):
            return declared_id
    if PROJECTS_ROOT.is_dir():
        for path in sorted(PROJECTS_ROOT.iterdir()):
            if not (path.is_dir() and not path.is_symlink() and (path / "PROJECT.json").is_file()):
                continue
            project = _load_project_dir(path.name)
            if project is not None and project_id in project.aliases:
                return project.project_id
    return project_id


def load_content_project(project_id: str) -> ContentProject:
    canonical = resolve_project_id(project_id)
    project = _load_project_dir(canonical)
    if project is None:
        requested = project_id.strip()
        hint = f" (requested via alias {requested!r})" if requested != canonical else ""
        raise RuntimeError(
            f"Unknown content project {canonical!r}{hint}; missing projects/{canonical}/PROJECT.json"
        )
    return project

def list_content_projects() -> list[ContentProject]:
    if not PROJECTS_ROOT.is_dir():
        return []
    return [
        load_content_project(path.name)
        for path in sorted(PROJECTS_ROOT.iterdir())
        if path.is_dir() and not path.is_symlink() and (path / "PROJECT.json").is_file()
    ]

def resolve_pipeline_prompt(project: ContentProject, name: str) -> Path:
    path = project.root / "prompts" / "pipeline" / name
    if path.is_file():
        return path
    if project.config.get("allow_legacy_prompt_fallback", False):
        legacy = ROOT / "prompts" / name
        if legacy.is_file():
            return legacy
    raise RuntimeError(f"Content project {project.project_id!r} is missing pipeline prompt {name!r}: expected {path.relative_to(ROOT)}")

def character_registry_path(project: ContentProject) -> Path | None:
    """Absolute path to a project's character registry, or None if it declares none."""
    characters = project.config.get("characters")
    rel = ""
    if isinstance(characters, dict):
        rel = str(characters.get("registry") or "").strip()
    if not rel:
        return None
    target = (project.root / rel).resolve()
    try:
        target.relative_to(project.root.resolve())
    except ValueError as exc:
        raise RuntimeError(
            f"Character registry path escapes content project {project.project_id!r}: {rel!r}"
        ) from exc
    return target


def resolve_visual_preset(project: ContentProject, preset: str) -> Path:
    path = project.root / "visual_presets" / preset
    if path.is_dir():
        return path
    if project.config.get("allow_global_visual_preset_fallback", False):
        legacy = ROOT / "visual_presets" / preset
        if legacy.is_dir():
            return legacy
    raise RuntimeError(f"Visual preset {preset!r} is not available to content project {project.project_id!r}: expected {path.relative_to(ROOT)}")


def required_pipeline_prompts(project: ContentProject) -> tuple[str, ...]:
    if project.is_question_harvest:
        return QH_PIPELINE_PROMPTS
    return PIPELINE_PROMPTS


def validate_content_project(project: ContentProject, preset: str | None = None) -> Path:
    """Fail before a launch when a project cannot complete the visual workflow."""
    selected_preset = preset or project.default_visual_preset
    for name in required_pipeline_prompts(project):
        resolve_pipeline_prompt(project, name)
    world_design_prompt = str(project.config.get("world_design_prompt") or "").strip()
    if world_design_prompt:
        resolve_pipeline_prompt(project, world_design_prompt)
    preset_root = resolve_visual_preset(project, selected_preset)
    # profile-aware preset validation (§46-47)
    if project.is_question_harvest:
        # The preset is rendering style only. Character identity is validated from the
        # registry below; the old preset sheet may remain solely for historical runs.
        missing = [name for name in ("README.md",) if not (preset_root / name).is_file()]
        # allow placeholder check to give clearer message
        if missing:
            # also show if placeholder exists
            hints = []
            if (preset_root / "character_sheet.png.placeholder").exists():
                hints.append("character_sheet.png.placeholder exists but real PNG missing — generate via Gemini (§47)")
            raise RuntimeError(
                f"Visual preset {selected_preset!r} for content project {project.project_id!r} is not production-ready; "
                f"missing: {', '.join(missing)}"
                + (f" ({'; '.join(hints)})" if hints else "")
            )
        registry_path = character_registry_path(project)
        if registry_path is None:
            raise RuntimeError(f"Content project {project.project_id!r} has no character registry configured.")
        from character_runtime import CharacterRegistryError, load_character_registry
        try:
            load_character_registry(registry_path)
        except CharacterRegistryError as exc:
            raise RuntimeError(f"Invalid character registry for {project.display_name}: {exc}") from exc
    else:
        missing = [name for name in ("README.md", "style_anchor.png", "character_anchor.png") if not (preset_root / name).is_file()]
        if missing:
            raise RuntimeError(
                f"Visual preset {selected_preset!r} for content project {project.project_id!r} is not production-ready; "
                f"missing: {', '.join(missing)}"
            )
    return preset_root


def validate_provider_locks(project: ContentProject, image_provider: str | None = None, video_provider: str | None = None) -> None:
    """Enforce absolute provider contract §60: QH image must be gemini, video must be flow (§3-4)."""
    if not project.is_question_harvest:
        return
    locked_image = "gemini"
    locked_video = "flow"
    if image_provider is not None and image_provider.strip().lower() != locked_image:
        raise RuntimeError(f"Q Station image provider is LOCKED to {locked_image!r}; got {image_provider!r} (§60)")
    if video_provider is not None and video_provider.strip().lower() != locked_video:
        raise RuntimeError(f"Q Station video provider is LOCKED to {locked_video!r}; got {video_provider!r} (§60)")
    # also validate config itself
    cfg_image = project.get_provider("image")
    cfg_video = project.get_provider("video")
    if cfg_image != locked_image:
        raise RuntimeError(f"PROJECT.json image provider must be {locked_image!r}; found {cfg_image!r}")
    if cfg_video != locked_video:
        raise RuntimeError(f"PROJECT.json video provider must be {locked_video!r}; found {cfg_video!r}")


def normalize_gemini_model(value: str) -> str:
    key = value.strip()
    if key in GEMINI_MODEL_ALIASES:
        return GEMINI_MODEL_ALIASES[key]
    lowered = key.lower().replace("-", "_").replace(" ", "_")
    if lowered in GEMINI_MODEL_ALIASES:
        return GEMINI_MODEL_ALIASES[lowered]
    raise ValueError(f"Unknown Gemini image model: {value!r}. Allowed: nano_banana_pro, nano_banana_2")


def normalize_flow_model(value: str) -> str:
    key = value.strip()
    if key in FLOW_MODEL_ALIASES:
        return FLOW_MODEL_ALIASES[key]
    lowered = key.lower().replace("-", "_").replace(" ", "_")
    # try lower direct
    for k, v in FLOW_MODEL_ALIASES.items():
        if k.lower() == key.lower():
            return v
    if lowered in FLOW_MODEL_ALIASES:
        return FLOW_MODEL_ALIASES[lowered]
    raise ValueError(f"Unknown Flow video model: {value!r}. Allowed: gemini_omni_1_1_flash, veo_3_1_quality, veo_3_1_fast, veo_3_1_lite")


def build_flow_clip_references(
    *,
    clip: str,
    has_character: bool = True,
    has_first_frame: bool = False,
    has_last_frame: bool = False,
) -> list[str]:
    """Validated Flow role list for Clip A/B (§15-16). Thin wrapper over the policy module."""
    clip_key = str(clip).upper()
    if clip_key == "A":
        if has_first_frame or has_last_frame:
            raise FlowReferencePolicyError("Clip A must not receive first/last frame inputs (§15)")
        return clip_a_roles(has_character_sheet=has_character)
    if clip_key == "B":
        return clip_b_roles(
            has_first_frame=has_first_frame,
            has_last_frame=has_last_frame,
        )
    raise FlowReferencePolicyError(f"clip must be 'A' or 'B', got {clip!r}")
