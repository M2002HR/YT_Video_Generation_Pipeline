"""One canonical, user-visible stage taxonomy for Question Harvest episodes."""
from __future__ import annotations

PIPELINE_STAGE_SEQUENCE = (
    "script_draft", "retention_edit", "episode_director", "world_style_director",
    "world_style_anchor", "episode_history", "visual_plan", "world_keyframe_prompt",
    "world_keyframe", "book_design_sheet", "book_spread", "flow_prompt_a", "flow_prompt_b",
    "body_images", "flow_clip_a", "flow_clip_b", "elevenlabs_voiceover", "background_music",
    "ajil_alignment", "opening_trim", "build_timeline", "render_baseline", "qc_baseline",
    "polish_audio", "qc_polished", "git_commit_push", "publish_telegram",
)


def stage_title(stage: str) -> str:
    """Stable ``step N/27 · Human Name`` title, or a readable name for ad-hoc work."""
    human = stage.replace("_", " ").title()
    try:
        return f"step {PIPELINE_STAGE_SEQUENCE.index(stage) + 1}/{len(PIPELINE_STAGE_SEQUENCE)} · {human}"
    except ValueError:
        return human
