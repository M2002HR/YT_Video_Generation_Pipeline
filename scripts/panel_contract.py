"""Declarative public contract for the Studio launch form.

The React client renders this schema directly. Defaults and constraints therefore live next
to the backend instead of being copied into JSX; adding a setting is a small, reviewable data
change plus its pipeline mapping.
"""
from __future__ import annotations

from typing import Any


def _field(name: str, label: str, kind: str = "text", **values: Any) -> dict[str, Any]:
    return {"name": name, "label": label, "type": kind, **values}


def launch_schema(projects: list[dict[str, str]], styles: list[str]) -> dict[str, Any]:
    select = lambda values: [{"value": value, "label": label} for value, label in values]
    groups = [
        {"id": "episode", "title": "Episode", "description": "Topic, audience and editorial constraints.", "fields": [
            _field("content_project", "Content project", "select", required=True, default="question_harvest", options=projects),
            _field("topic", "Question or topic", required=True, maxLength=220, placeholder="What should this video explain?"),
            _field("working_title", "Working title", maxLength=220, placeholder="Optional title direction"),
            _field("audience", "Audience", maxLength=500, placeholder="Curious adults who enjoy thoughtful explainers"),
            _field("narrative_angle", "Narrative angle", "textarea", maxLength=2000),
            _field("must_include", "Must include", "textarea", maxLength=2000),
            _field("must_avoid", "Must avoid", "textarea", maxLength=2000),
            _field("source_notes", "Source notes / verified facts", "textarea", maxLength=4000),
        ]},
        {"id": "format", "title": "Length & output", "description": "Binding duration and delivery options.", "fields": [
            _field("min_duration_seconds", "Minimum seconds", "number", required=True, default=40, min=15, max=300, step=1, width="half"),
            _field("max_duration_seconds", "Maximum seconds", "number", required=True, default=60, min=15, max=300, step=1, width="half"),
            _field("aspect_ratio", "Frame format", "select", default="9:16", options=select([("9:16", "9:16 — Shorts / Reels"), ("16:9", "16:9 — YouTube landscape")])),
            _field("show_subtitles", "Burn in subtitles", "toggle", default=False),
            _field("word_highlight", "Highlight the spoken word", "toggle", default=True, help="Used only when subtitles are enabled."),
        ]},
        {"id": "visual", "title": "Visual direction", "description": "Question Harvest style, image model and opening clips.", "projects": ["question_harvest"], "fields": [
            _field("hero_presence_mode", "Hero presence", "select", default="auto", options=select([("auto", "Auto"), ("opener_only", "Opener only"), ("limited_in_world", "Limited in world"), ("in_world", "In world")])),
            _field("world_style_id", "World style", "select", default="", options=[{"value": "", "label": "Auto — let the director decide"}] + [{"value": value, "label": value} for value in styles]),
            _field("world_style_policy", "Style policy", "select", default="auto", options=select([("auto", "Auto — reuse or create"), ("reuse", "Reuse an existing style"), ("new", "Create a new style")])),
            _field("world_style_hint", "Style hint", maxLength=500, placeholder="charcoal, woodcut, ink wash…"),
            _field("chatgpt_fallback_auto", "Automatically fall back to Gemini if ChatGPT fails", "toggle", default=False, help="Off: pause as Action required and ask an operator before Gemini is used."),
            _field("gemini_image_model", "Gemini image model", "select", default="nano_banana_2", options=select([("nano_banana_2", "Nano Banana 2"), ("nano_banana_pro", "Nano Banana Pro (availability required)")])),
            _field("flow_video_model", "Flow video model", "select", default="gemini_omni_1_1_flash", options=select([("gemini_omni_1_1_flash", "Gemini Omni 1.1 Flash"), ("veo_3_1_quality", "Veo 3.1 Quality"), ("veo_3_1_fast", "Veo 3.1 Fast"), ("veo_3_1_lite", "Veo 3.1 Lite")]), width="half"),
            _field("flow_resolution", "Flow resolution", "select", default="720p", options=select([("720p", "720p"), ("360p", "360p draft")]), width="half"),
            _field("opening_a_seconds", "Clip A source seconds", "select", default="6", options=select([("4", "4s"), ("5", "5s"), ("6", "6s"), ("8", "8s")]), width="half"),
            _field("opening_b_seconds", "Clip B source seconds", "select", default="4", options=select([("3", "3s"), ("4", "4s"), ("6", "6s"), ("8", "8s")]), width="half"),
        ]},
        {"id": "audio", "title": "Voice & music", "description": "Narration character and ordered music fallback.", "fields": [
            _field("voice", "Voice", required=True, default="Mark - Natural Conversations"),
            _field("model", "ElevenLabs model", "select", default="Eleven Multilingual v2", options=select([("Eleven Multilingual v2", "Eleven Multilingual v2"), ("Eleven v3", "Eleven v3")])),
            _field("speed", "Speed", "number", default=.9, min=.7, max=1.2, step=.01, width="half"),
            _field("stability", "Stability", "number", default=.3, min=0, max=1, step=.01, width="half"),
            _field("similarity", "Similarity", "number", default=.5, min=0, max=1, step=.01, width="half"),
            _field("style", "Voice style", "number", default=.15, min=0, max=1, step=.01, width="half"),
            _field("music_providers", "Music provider priority", "priority", default=["freesound", "mixkit", "pixabay"], options=select([("freesound", "Freesound"), ("mixkit", "Mixkit"), ("pixabay", "Pixabay")]), help="Use the arrows to set fallback order; each provider is tried once."),
        ]},
        {"id": "sfx", "title": "Sound effects", "description": "Optional restrained sound-design pass.", "collapsed": True, "fields": [
            _field("sfx_enabled", "Enable SFX", "toggle", default=False),
            _field("sfx_planner_style", "Planner style", "select", default="restrained", options=select([("restrained", "Restrained"), ("balanced", "Balanced"), ("expressive", "Expressive")])),
            _field("sfx_max_events_per_minute", "Max events / minute", "number", default=4, min=0, max=20, step=.5, width="half"),
            _field("sfx_minimum_gap_seconds", "Minimum gap seconds", "number", default=2, min=0, max=30, step=.1, width="half"),
            _field("sfx_local_match_threshold", "Local match threshold", "number", default=.35, min=0, max=1, step=.05, width="half"),
            _field("sfx_license_policy", "License policy", "select", default="cc0", options=select([("cc0", "CC0 only"), ("cc0_by", "CC0 + CC BY")]), width="half"),
            _field("sfx_candidate_count", "Candidate count", "number", default=12, min=1, max=50, width="half"),
            _field("sfx_max_queries_per_event", "Max queries / event", "number", default=2, min=1, max=5, width="half"),
            _field("sfx_default_gain_db", "Default gain dB", "number", default=-9, min=-20, max=-3, step=1, width="half"),
            _field("sfx_freesound_enabled", "Use Freesound after a local miss", "toggle", default=True),
        ]},
        {"id": "motion", "title": "Motion & editing", "description": "Semantic camera direction and deterministic compilation.", "collapsed": True, "fields": [
            _field("motion_enabled", "Enable Dynamic Motion Director", "toggle", default=True),
            _field("motion_pace", "Editing pace", "select", default="fast", options=select([("calm", "Calm"), ("balanced", "Balanced"), ("fast", "Fast"), ("very_fast", "Very fast")]), width="half"),
            _field("motion_intensity", "Motion intensity", "select", default="normal", options=select([("subtle", "Subtle"), ("normal", "Normal"), ("strong", "Strong")]), width="half"),
            _field("motion_style", "Editing style", "select", default="dynamic", options=select([("clean", "Clean"), ("dynamic", "Dynamic"), ("cinematic", "Cinematic")]), width="half"),
            _field("motion_transition_preference", "Transitions", "select", default="minimal", options=select([("minimal", "Minimal"), ("balanced", "Balanced"), ("expressive", "Expressive")]), width="half"),
            _field("motion_max_micro_shots", "Max micro-shots / image", "number", default=3, min=1, max=4),
            *[_field(name, label, "toggle", default=True) for name, label in [
                ("motion_allow_punch_ins", "Allow punch-ins"), ("motion_allow_directional_pans", "Allow directional pans"), ("motion_allow_hard_reframe_cuts", "Allow hard reframe cuts"), ("motion_face_protection", "Protect faces"),
                ("motion_allow_hold", "Allow intentional holds"), ("motion_allow_push", "Allow pushes"), ("motion_allow_pull", "Allow pull-outs"), ("motion_allow_tilt", "Allow tilts"), ("motion_allow_pan_push", "Allow pan + push"), ("motion_allow_pan_pull", "Allow pan + pull"), ("motion_allow_drift", "Allow drift"), ("motion_allow_settle", "Allow settle"), ("motion_allow_reveal_move", "Allow reveal moves"), ("motion_allow_match_position_cuts", "Allow match-position cuts"), ("motion_allow_decorative_transitions", "Allow decorative transitions"), ("motion_allow_directional_transitions", "Allow directional transitions"), ("motion_allow_reveal_transitions", "Allow reveal transitions"), ("motion_subtitle_avoidance", "Protect subtitle region"), ("motion_blank_avoidance", "Avoid blank regions"), ("motion_word_sync", "Synchronize to words"), ("motion_editorial_critic", "Run editorial critic"),
            ]],
            _field("motion_debug_preview", "Generate debug previews", "toggle", default=False),
            *[_field(name, label, kind, default=default, min=minimum, max=maximum, step=step, advanced=True, width="half", **extra) for name, label, kind, default, minimum, maximum, step, extra in [
                ("motion_planning_quality", "Planning quality", "select", "professional", None, None, None, {"options": select([("draft", "Draft"), ("standard", "Standard"), ("professional", "Professional")])}),
                ("motion_min_shot_duration", "Min micro-shot", "number", .55, .35, 3, .05, {}), ("motion_max_shot_duration", "Max micro-shot", "number", 3.2, .6, 8, .1, {}),
                ("motion_interval_min", "Target interval min", "number", .8, .4, 5, .1, {}), ("motion_interval_max", "Target interval max", "number", 1.8, .6, 8, .1, {}),
                ("motion_normal_max_zoom", "Normal max zoom", "number", 1.32, 1, 1.6, .01, {}), ("motion_punch_max_zoom", "Punch max zoom", "number", 1.48, 1, 1.8, .01, {}),
                ("motion_max_pan_distance", "Max pan distance", "number", .32, .02, .7, .01, {}), ("motion_max_pan_velocity", "Max pan / sec", "number", .42, .02, 1, .01, {}), ("motion_max_zoom_velocity", "Max zoom / sec", "number", .34, .02, 1, .01, {}),
                ("motion_transition_fraction", "Transition budget", "number", .25, 0, 1, .05, {}), ("motion_transition_min", "Transition min", "number", .1, .08, .6, .01, {}), ("motion_transition_max", "Transition max", "number", .4, .08, .8, .01, {}),
                ("motion_observation_batch", "Observation batch", "number", 3, 1, 6, 1, {}), ("motion_planning_batch", "Planning batch", "number", 1, 1, 6, 1, {}), ("motion_critic_batch", "Critic batch", "number", 2, 1, 4, 1, {}),
                ("motion_correction_attempts", "JSON correction attempts", "number", 4, 0, 4, 1, {}), ("motion_neighbor_context", "Neighbor beats", "number", 1, 1, 3, 1, {}), ("motion_word_sync_tolerance", "Word-sync tolerance ms", "number", 50, 0, 250, 5, {}), ("motion_face_padding", "Face safety padding", "number", .18, 0, .5, .01, {}),
                ("motion_supersample", "Supersample", "select", "2", None, None, None, {"options": select([("1", "1×"), ("2", "2×"), ("3", "3×"), ("4", "4×")])}),
            ]],
        ]},
        {"id": "publish", "title": "Publishing", "description": "Delivery happens only after QC passes.", "collapsed": True, "fields": [
            _field("telegram_low_size", "Send compact Telegram copy", "toggle", default=True),
            _field("telegram_original", "Send original to Telegram", "toggle", default=False),
            _field("commit_artifacts", "Commit and push artifacts", "toggle", default=False),
        ]},
        {"id": "providers", "title": "Locked provider contract", "description": "Fixed by Question Harvest project design.", "projects": ["question_harvest"], "collapsed": True, "fields": [
            _field("locked_text", "Text", "readonly", default="ChatGPT · via Ordak"),
            _field("locked_image", "Image", "readonly", default="Gemini · via Ordak"),
            _field("locked_video", "Video", "readonly", default="Google Flow · via Ordak"),
        ]},
    ]
    return {"schema_version": 1, "groups": groups}


def defaults(schema: dict[str, Any]) -> dict[str, Any]:
    return {field["name"]: field.get("default", False if field["type"] == "toggle" else "") for group in schema["groups"] for field in group["fields"] if field["type"] != "readonly"}
