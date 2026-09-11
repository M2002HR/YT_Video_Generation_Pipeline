"""One canonical, user-visible stage taxonomy for Q Station episodes."""
from __future__ import annotations

PIPELINE_STAGE_SEQUENCE = (
    "script_draft", "retention_edit", "character_resolution", "episode_director", "world_style_director",
    "world_style_anchor", "episode_history", "visual_plan", "world_keyframe_prompt",
    "world_keyframe", "book_design_sheet", "book_cover_design", "book_cover", "flow_prompt_a", "flow_prompt_b",
    "body_images", "transition_direction", "flow_clip_a", "flow_clip_b", "elevenlabs_voiceover", "background_music",
    "ajil_alignment", "opening_trim", "audio_mix_profile", "render_profile", "build_timeline", "motion_director", "sfx_plan", "render_baseline", "qc_baseline", "sfx_acquire",
    "polish_audio", "qc_polished", "telegram_compress", "git_commit_push", "publish_telegram",
)

STAGE_PHASES = {
    **{stage: "creative" for stage in (
        "script_draft", "retention_edit", "character_resolution", "episode_director",
        "world_style_director", "episode_history", "visual_plan",
    )},
    **{stage: "visual" for stage in (
        "world_style_anchor", "world_keyframe_prompt", "world_keyframe", "book_design_sheet",
        "book_cover_design", "book_cover", "body_images",
    )},
    **{stage: "opening" for stage in (
        "flow_prompt_a", "flow_prompt_b", "flow_clip_a", "flow_clip_b", "opening_trim",
    )},
    **{stage: "audio" for stage in (
        "elevenlabs_voiceover", "background_music", "ajil_alignment", "audio_mix_profile",
        "sfx_plan", "sfx_acquire",
    )},
    **{stage: "edit" for stage in (
        "transition_direction", "render_profile", "build_timeline", "motion_director",
    )},
    **{stage: "render" for stage in (
        "render_baseline", "qc_baseline", "polish_audio", "qc_polished",
    )},
    **{stage: "delivery" for stage in (
        "telegram_compress", "git_commit_push", "publish_telegram",
    )},
}


def stage_title(stage: str) -> str:
    """Stable phase-aware title; active orchestrators add truthful plan-local positions."""
    human = stage.replace("_", " ").title()
    phase = STAGE_PHASES.get(stage)
    return f"{phase.title()} · {human}" if phase else human
