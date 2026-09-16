#!/usr/bin/env python3
"""Provider-free deployment preflight for the topic-first opening pipeline."""
from __future__ import annotations

import re
from pathlib import Path

from character_runtime import load_character_registry
from content_projects import QH_PIPELINE_PROMPTS, load_content_project, validate_content_project
from opening_runtime import POLICY_VERSION
from narration_language import POLICY_VERSION as LANGUAGE_POLICY_VERSION
from pipeline_stages import PIPELINE_STAGE_SEQUENCE
from run_graph import NODE_SPECS

ROOT = Path(__file__).resolve().parents[1]
TOKENS = {
    "EDITORIAL_BRIEF", "CHARACTER_STORY_CONTEXT", "PRESENTATION_CONTEXT", "RECENT_OPENINGS",
    "CANDIDATES", "OPENING_CONCEPT", "SCRIPT_CORE", "EPISODE_PLAN", "VIDEO_BRIEF", "CURRENT_SCRIPT",
    "DURATION_RANGE", "WORD_RANGE", "WORD_TARGET", "BEAT_MIN", "BEAT_MAX", "BEAT_RANGE",
    "ENTRY_SEGMENT_KEY", "ENTRY_SEGMENT_LABEL", "PRESENTATION_RULES", "TOPIC", "CREATIVE_BRIEF",
    "FINAL_SCRIPT", "CHARACTER_CONTEXT", "RECENT_HISTORY", "STYLE_CATALOG", "RECENT_STYLES",
    "STYLE_DIRECTIVE", "WORLD_STYLE_PLAN", "BODY_DURATION_SECONDS", "CAPTION_LAYOUT_RULE",
    "WORLD_ENTRY_DISCOVERY", "BEAT", "BEAT_JSON", "WORLD_KEYFRAME_DESC", "WORLD_KEYFRAME_PROMPT",
    "OPENING_A_NARRATION", "VISUAL_PRESET_RULES", "SOURCE_DURATION_SECONDS", "NARRATION_DURATION_SECONDS",
    "ENTRY_TRANSITION_NARRATION", "ENTRY_TRANSITION_RULES", "ENTRY_BRIDGE", "ENTRY_FRAME_DIRECTION",
    "SCRIPT_CONTEXT", "CTA_HINT", "ASPECT_RATIO", "PREVIOUS_BEAT", "REFERENCE_IMAGES",
    "STYLE_RULES", "VISUAL_BEAT", "LANGUAGE_POLICY", "LANGUAGE_SCOPE", "REFERENCE_SCRIPT", "SPOKEN_SEGMENTS",
}


def check() -> list[str]:
    project = load_content_project("q_station")
    validate_content_project(project)
    registry = load_character_registry(project.root / "characters/registry.json")
    if set(PIPELINE_STAGE_SEQUENCE) != set(NODE_SPECS):
        raise RuntimeError("Stage taxonomy and panel graph disagree.")
    if "opening_concept" not in NODE_SPECS["script_draft"].dependencies:
        raise RuntimeError("Script draft does not depend on the opening concept.")
    for name in QH_PIPELINE_PROMPTS:
        text = (project.root / "prompts/pipeline" / name).read_text(encoding="utf-8")
        unknown = set(re.findall(r"\{\{([A-Z_]+)\}\}", text)) - TOKENS
        if unknown:
            raise RuntimeError(f"Unknown template inputs in {name}: {sorted(unknown)}")
    from narration_language import policy_text
    policy_text(project.root / "prompts/pipeline")
    from run_question_harvest_pipeline import resolve_prompt
    for name in QH_PIPELINE_PROMPTS:
        if "{{LANGUAGE_POLICY}}" in resolve_prompt(project, name):
            raise RuntimeError(f"Unexpanded spoken-language policy in {name}")
    descriptions = []
    for identifier in registry.enabled_ids():
        char = registry.get(identifier)
        if not char.presentation.entry_variants:
            raise RuntimeError(f"{identifier}: presentation has no allowed entry variants.")
        descriptions.append(f"{identifier}: {char.presentation.id}; narration={char.presentation.segment_key}")
    return descriptions


def main() -> int:
    try:
        rows = check()
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Opening preflight FAILED: {exc}")
        return 1
    print(f"Opening policy v{POLICY_VERSION}: configuration, prompt inputs and stage graph OK")
    print(f"Spoken English policy v{LANGUAGE_POLICY_VERSION}: shared prompts and review contracts available")
    for row in rows:
        print("  " + row)
    print("No providers called; no generated media or existing run state changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
