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

@dataclass(frozen=True)
class ContentProject:
    project_id: str
    root: Path
    config: dict[str, Any]

    @property
    def display_name(self) -> str:
        return str(self.config.get("display_name") or self.project_id)

    @property
    def default_visual_preset(self) -> str:
        value = str(self.config.get("default_visual_preset") or "").strip()
        if not value:
            raise RuntimeError(f"Content project {self.project_id!r} has no default_visual_preset.")
        return value

def load_content_project(project_id: str) -> ContentProject:
    project_id = project_id.strip()
    if not PROJECT_ID_RE.fullmatch(project_id):
        raise RuntimeError(f"Invalid content-project id: {project_id!r}")
    root = PROJECTS_ROOT / project_id
    config_path = root / "PROJECT.json"
    if not config_path.is_file():
        raise RuntimeError(f"Unknown content project {project_id!r}; missing {config_path.relative_to(ROOT)}")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if config.get("project_id") != project_id:
        raise RuntimeError(f"{config_path.relative_to(ROOT)} project_id does not match its directory.")
    return ContentProject(project_id, root, config)

def list_content_projects() -> list[ContentProject]:
    if not PROJECTS_ROOT.is_dir():
        return []
    return [load_content_project(path.name) for path in sorted(PROJECTS_ROOT.iterdir()) if path.is_dir() and (path / "PROJECT.json").is_file()]

def resolve_pipeline_prompt(project: ContentProject, name: str) -> Path:
    path = project.root / "prompts" / "pipeline" / name
    if path.is_file():
        return path
    if project.config.get("allow_legacy_prompt_fallback", False):
        legacy = ROOT / "prompts" / name
        if legacy.is_file():
            return legacy
    raise RuntimeError(f"Content project {project.project_id!r} is missing pipeline prompt {name!r}: expected {path.relative_to(ROOT)}")

def resolve_visual_preset(project: ContentProject, preset: str) -> Path:
    path = project.root / "visual_presets" / preset
    if path.is_dir():
        return path
    if project.config.get("allow_global_visual_preset_fallback", False):
        legacy = ROOT / "visual_presets" / preset
        if legacy.is_dir():
            return legacy
    raise RuntimeError(f"Visual preset {preset!r} is not available to content project {project.project_id!r}: expected {path.relative_to(ROOT)}")
