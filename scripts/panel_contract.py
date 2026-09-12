"""Declarative public contract for the Studio launch form.

The React client renders this schema directly. Defaults and constraints therefore live next
to the backend instead of being copied into JSX; adding a setting is a small, reviewable data
change plus its pipeline mapping.
"""
from __future__ import annotations

from typing import Any


def _field(name: str, label: str, kind: str = "text", **values: Any) -> dict[str, Any]:
    return {"name": name, "label": label, "type": kind, **values}


#: Curated subtitle families. Every entry must resolve through fontconfig on the render
#: host AND have a file in SUBTITLE_FONT_FILES (video_control_panel.py) so the Studio
#: preview renders the exact same face that libass will burn in. Starred families are
#: the research-backed subtitle recommendations and sort first in the Studio picker.
SUBTITLE_FONTS = (
    "DejaVu Sans",
    "DejaVu Serif",
    "Liberation Sans",
    "Liberation Serif",
    "Liberation Sans Narrow",
    "Nimbus Sans",
    "Noto Sans Mono",
)

#: Research-backed subtitle faces (YouTube/Netflix defaults and editor favourites).
#: Rendered first in the picker with a star; values stay plain family names.
RECOMMENDED_SUBTITLE_FONTS = (
    "Roboto",
    "Open Sans",
    "Lato",
    "Montserrat",
    "Poppins",
    "Noto Sans",
    "Source Sans 3",
    "Rubik",
    "Atkinson Hyperlegible",
    "Bebas Neue",
    "Oswald",
    "Zilla Slab",
    "Roboto Slab",
    "Bitter",
    "Titillium Web",
    "Exo 2",
    "Encode Sans",
)

#: All selectable families: recommended first, then the server-fallback faces.
ALL_SUBTITLE_FONTS = RECOMMENDED_SUBTITLE_FONTS + tuple(
    name for name in SUBTITLE_FONTS if name not in RECOMMENDED_SUBTITLE_FONTS
)

#: Vertical caption presets. Pixels are derived from the frame height by
#: build_timeline.SUBTITLE_POSITION_FRACTIONS; the preview mirrors those fractions.
#: ``custom`` additionally reads subtitle_offset_value/unit.
SUBTITLE_POSITIONS = (
    ("low", "Low — near the bottom edge"),
    ("standard", "Standard — clears the app UI"),
    ("high", "High — raised lower-third"),
    ("custom", "Custom — offset from the bottom"),
)

#: Quick colour shortcuts shown beside the colour picker (pure frontend sugar).
SUBTITLE_COLOUR_PRESETS = (
    ("#FFFFFF", "White"),
    ("#FFD700", "Gold"),
    ("#FFFF00", "Yellow"),
    ("#00E5FF", "Cyan"),
    ("#000000", "Black"),
)


def launch_schema(projects: list[dict[str, str]], styles: list[str]) -> dict[str, Any]:
    select = lambda values: [{"value": value, "label": label} for value, label in values]
    groups = [
        {"id": "episode", "title": "Episode", "description": "Topic, audience and editorial constraints.", "fields": [
            _field("content_project", "Content project", "select", required=True, default="q_station", options=projects),
            _field("topic", "Question or topic", required=True, maxLength=220, placeholder="What should this video explain?"),
            _field("working_title", "Working title", maxLength=220, placeholder="Optional title direction"),
            _field("audience", "Audience", maxLength=500, placeholder="Curious adults who enjoy thoughtful explainers"),
            _field("narrative_angle", "Narrative angle", "textarea", maxLength=2000),
            _field("must_include", "Must include", "textarea", maxLength=2000),
            _field("must_avoid", "Must avoid", "textarea", maxLength=2000),
            _field("source_notes", "Source notes / verified facts", "textarea", maxLength=4000),
        ]},
        {"id": "format", "title": "Length & output", "description": "Binding duration and canvas format.", "fields": [
            _field("min_duration_seconds", "Minimum seconds", "number", required=True, default=40, min=15, max=300, step=1, width="half"),
            _field("max_duration_seconds", "Maximum seconds", "number", required=True, default=60, min=15, max=300, step=1, width="half"),
            _field("aspect_ratio", "Frame format", "select", default="9:16", options=[
                {"value": "9:16", "label": "9:16 — Shorts / Reels"},
                {"value": "16:9", "label": "16:9 — YouTube landscape", "disabledProjects": ["q_station"]},
            ], help="Q Station's book-world image contract is currently vertical; landscape remains available to generic projects."),
        ]},
        {"id": "subtitles", "title": "Subtitles & safe areas", "description": "Caption content, styling and the visual space protected for it.", "fields": [
            _field("show_subtitles", "Burn in subtitles", "toggle", default=False),
            _field("word_highlight", "Highlight the spoken word", "toggle", default=True, help="Applies karaoke-style emphasis to the active word.", requires={"field": "show_subtitles", "value": True}),
            _field("reserve_subtitle_space", "Reserve caption space in generated images", "toggle", default=True, help="Changing this rebuilds the complete body-image continuity chain.", requires={"field": "show_subtitles", "value": True}),
            _field("motion_subtitle_avoidance", "Protect captions during camera motion", "toggle", default=True, help="Keeps faces and focal action outside the subtitle region.", requires={"field": "show_subtitles", "value": True}),
            _field("subtitle_font", "Font", "select", default="Roboto", options=[
                {"value": name, "label": name, "recommended": True}
                for name in RECOMMENDED_SUBTITLE_FONTS
            ] + [
                {"value": name, "label": name} for name in SUBTITLE_FONTS
            ], searchable=True, help="Highlighted faces are the research-backed subtitle picks.", requires={"field": "show_subtitles", "value": True}),
            _field("subtitle_font_size", "Font size", "number", default=56, min=24, max=120, step=1, width="half", requires={"field": "show_subtitles", "value": True}),
            _field("subtitle_max_words", "Max words per caption", "number", default=6, min=1, max=12, step=1, width="half", requires={"field": "show_subtitles", "value": True}),
            _field("subtitle_bold", "Bold", "toggle", default=True, requires={"field": "show_subtitles", "value": True}),
            _field("subtitle_italic", "Italic", "toggle", default=False, requires={"field": "show_subtitles", "value": True}),
            _field("subtitle_position", "Position", "select", default="standard", options=select(list(SUBTITLE_POSITIONS)), requires={"field": "show_subtitles", "value": True}),
            _field("subtitle_offset_value", "Custom offset", "number", default=10, min=0, max=800, step=0.5, width="half", help="Used only when Position is Custom.", requires=[{"field": "show_subtitles", "value": True}, {"field": "subtitle_position", "value": "custom"}]),
            _field("subtitle_offset_unit", "Offset unit", "select", default="percent", options=select([("percent", "Percent of height"), ("px", "Pixels")]), width="half", requires=[{"field": "show_subtitles", "value": True}, {"field": "subtitle_position", "value": "custom"}]),
            _field("subtitle_font_colour", "Text colour", "color", default="#FFFFFF", width="half", presets=list(SUBTITLE_COLOUR_PRESETS), requires={"field": "show_subtitles", "value": True}),
            _field("subtitle_outline_colour", "Outline colour", "color", default="#000000", width="half", presets=list(SUBTITLE_COLOUR_PRESETS), requires={"field": "show_subtitles", "value": True}),
            _field("subtitle_outline", "Outline width", "number", default=3, min=0, max=8, step=0.5, help="0 switches the outline off.", requires={"field": "show_subtitles", "value": True}),
        ]},
        {"id": "character", "title": "Character & presence", "description": "Choose the recurring host and where it may appear.", "projects": ["q_station"], "fields": [
            _field("character_mode", "Character", "select", default="auto", options=select([("auto", "Auto"), ("manual", "Manual character")])),
            _field("character_id", "Manual character", "select", default="", options=[{"value": "", "label": "Choose a character"}]),
            _field("hero_presence_mode", "Hero presence", "select", default="auto", options=select([("auto", "Auto"), ("opener_only", "Opener only"), ("limited_in_world", "Limited in world"), ("in_world", "In world")])),
        ]},
        {"id": "visual", "title": "World style & still images", "description": "World identity, style selection and Gemini still generation.", "projects": ["q_station"], "fields": [
            _field("world_style_id", "World style", "select", default="", options=[{"value": "", "label": "Auto — let the director decide"}] + [{"value": value, "label": value} for value in styles]),
            _field("world_style_policy", "Style policy", "select", default="auto", options=select([("auto", "Auto — reuse or create"), ("reuse", "Reuse an existing style"), ("new", "Create a new style")])),
            # Rendered by the Studio's dedicated upload control.  Keeping its opaque
            # token in the typed contract means launch and revision use one validator.
            _field("world_style_reference_id", "Style reference upload", maxLength=96, placeholder=""),
            _field("world_style_hint", "Style hint", maxLength=500, placeholder="charcoal, woodcut, ink wash…"),
            _field("gemini_image_model", "Gemini image model", "select", default="nano_banana_2", options=select([("nano_banana_2", "Nano Banana 2"), ("nano_banana_pro", "Nano Banana Pro (availability required)")])),
            _field(
                "beat_image_qc_disabled", "Disable ChatGPT QC for beat images", "toggle", default=False,
                help="Skips visual review entirely for body beats: generated beat images are never uploaded to ChatGPT.",
            ),
            _field(
                "image_qc_correction_policy", "Non-critical QC corrections", "select", default="0",
                options=select([
                    ("0", "0 — report only (current behaviour)"),
                    ("1", "1 corrective regeneration"),
                    ("2", "2 corrective regenerations, then use best"),
                    ("strict", "Strict — 3 attempts, then fail if not clean"),
                ]),
                help="Blocking identity/style/output failures always retry and never get accepted. Non-critical retries preserve the best candidate seen.",
                requires={"field": "beat_image_qc_disabled", "value": False},
                hideWhenGated=True,
            ),
        ]},
        {"id": "opening", "title": "Opening clips", "description": "Flow model, source quality and narration-sync headroom.", "projects": ["q_station"], "fields": [
            _field("flow_video_model", "Flow video model", "select", default="gemini_omni_1_1_flash", options=select([("gemini_omni_1_1_flash", "Gemini Omni 1.1 Flash"), ("veo_3_1_quality", "Veo 3.1 Quality"), ("veo_3_1_fast", "Veo 3.1 Fast"), ("veo_3_1_lite", "Veo 3.1 Lite")]), width="half"),
            _field("flow_resolution", "Flow resolution", "select", default="720p", options=select([("720p", "720p"), ("360p", "360p draft")]), width="half"),
            _field("opening_a_seconds", "Clip A source seconds", "select", default="6", options=select([("4", "4s"), ("5", "5s"), ("6", "6s"), ("8", "8s")]), width="half"),
            _field("opening_b_seconds", "Clip B source seconds", "select", default="4", options=select([("3", "3s"), ("4", "4s"), ("6", "6s"), ("8", "8s")]), width="half"),
            _field("opening_speed_tolerance", "Opening sync tolerance", "number", default=0.1, min=0, max=0.5, step=0.01, help="Max fraction a silent opening clip may be slowed to meet narration."),
        ]},
        {"id": "voice", "title": "Narration", "description": "ElevenLabs voice and delivery controls.", "fields": [
            _field("voice", "Voice", required=True, default="Mark - Natural Conversations"),
            _field("model", "ElevenLabs model", "select", default="Eleven Multilingual v2", options=select([("Eleven Multilingual v2", "Eleven Multilingual v2"), ("Eleven v3", "Eleven v3")])),
            _field("speed", "Speed", "number", default=.9, min=.7, max=1.2, step=.01, width="half"),
            _field("stability", "Stability", "number", default=.3, min=0, max=1, step=.01, width="half"),
            _field("similarity", "Similarity", "number", default=.5, min=0, max=1, step=.01, width="half"),
            _field("style", "Voice style", "number", default=.15, min=0, max=1, step=.01, width="half"),
        ]},
        {"id": "music", "title": "Background music", "description": "Ordered source fallback for the final audio mix.", "fields": [
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
        {"id": "transitions", "title": "Editing & transitions", "description": "Default timeline boundaries and optional AI/per-boundary decisions.", "fields": [
            _field("motion_transition_default_type", "Default transition", "select", default="fade", options=select([("fade", "Fade"), ("dissolve", "Dissolve"), ("fadeblack", "Fade to black"), ("fadewhite", "Fade to white"), ("smoothleft", "Smooth left"), ("smoothright", "Smooth right"), ("wipeleft", "Wipe left"), ("wiperight", "Wipe right"), ("slideleft", "Slide left"), ("slideright", "Slide right"), ("cut", "Cut")]), help="Used at every boundary unless AI or a per-boundary Revise override changes it."),
            _field("motion_transition_seconds", "Transition intensity / seconds", "number", default=.28, min=.08, max=.45, step=.01, help="Intensity maps to overlap duration. 0.28s is the balanced default.", width="half"),
            _field("motion_transition_ai_enabled", "Let ChatGPT choose image-pair transitions", "toggle", default=False, help="Off by default: no transition-selection requests are sent to ChatGPT; all unedited boundaries use the default above."),
            # These legacy fields remain frozen for old runs and keep the Motion Director's
            # internal image-plan contract compatible. Timeline boundaries are now owned by
            # the explicit default/override policy above.
            _field("motion_image_transition_style", "AI image transition palette", "select", default="cut_fade_dissolve", options=select([("cuts", "Cuts only"), ("cut_fade", "Cut + soft fade"), ("cut_fade_dissolve", "Cut + fade + dissolve")]), advanced=True, requires={"field": "motion_transition_ai_enabled", "value": True}),
            _field("motion_image_transition_seconds", "AI image transition seconds", "number", default=.28, min=.14, max=.42, step=.01, advanced=True, width="half", requires={"field": "motion_transition_ai_enabled", "value": True}),
            _field("motion_opening_to_image_seconds", "AI opening fade seconds", "number", default=.28, min=.08, max=.45, step=.01, advanced=True, width="half", requires={"field": "motion_transition_ai_enabled", "value": True}),
        ]},
        {"id": "motion", "title": "Camera motion", "description": "Base image movement and optional semantic Motion Director.", "collapsed": True, "fields": [
            _field("motion_enabled", "Enable Dynamic Motion Director", "toggle", default=True),
            _field("motion_image_zoom_strength", "Base image zoom strength", "number", default=.14, min=.04, max=.24, step=.01, help="Every body image pushes in continuously; the final image pulls out.", width="half"),
            _field("motion_pace", "Editing pace", "select", default="fast", options=select([("calm", "Calm"), ("balanced", "Balanced"), ("fast", "Fast"), ("very_fast", "Very fast")]), width="half"),
            _field("motion_intensity", "Motion intensity", "select", default="normal", options=select([("subtle", "Subtle"), ("normal", "Normal"), ("strong", "Strong")]), width="half"),
            _field("motion_style", "Editing style", "select", default="dynamic", options=select([("clean", "Clean"), ("dynamic", "Dynamic"), ("cinematic", "Cinematic")]), width="half"),
            _field("motion_transition_preference", "Transitions", "select", default="minimal", options=select([("minimal", "Minimal"), ("balanced", "Balanced"), ("expressive", "Expressive")]), width="half"),
            _field("motion_max_micro_shots", "Max micro-shots / image", "number", default=3, min=1, max=4),
            *[_field(name, label, "toggle", default=True) for name, label in [
                ("motion_allow_punch_ins", "Allow punch-ins"), ("motion_allow_directional_pans", "Allow directional pans"), ("motion_allow_hard_reframe_cuts", "Allow hard reframe cuts"), ("motion_face_protection", "Protect faces"),
                ("motion_allow_hold", "Allow intentional holds"), ("motion_allow_push", "Allow pushes"), ("motion_allow_pull", "Allow pull-outs"), ("motion_allow_tilt", "Allow tilts"), ("motion_allow_pan_push", "Allow pan + push"), ("motion_allow_pan_pull", "Allow pan + pull"), ("motion_allow_drift", "Allow drift"), ("motion_allow_settle", "Allow settle"), ("motion_allow_reveal_move", "Allow reveal moves"), ("motion_allow_match_position_cuts", "Allow match-position cuts"), ("motion_allow_decorative_transitions", "Allow decorative transitions"), ("motion_allow_directional_transitions", "Allow directional transitions"), ("motion_allow_reveal_transitions", "Allow reveal transitions"), ("motion_blank_avoidance", "Avoid blank regions"), ("motion_word_sync", "Synchronize to words"), ("motion_editorial_critic", "Run editorial critic"),
            ]],
            _field("motion_debug_preview", "Generate debug previews", "toggle", default=False),
            *[_field(name, label, kind, default=default, min=minimum, max=maximum, step=step, advanced=True, width="half", **extra) for name, label, kind, default, minimum, maximum, step, extra in [
                ("motion_planning_quality", "Planning quality", "select", "professional", None, None, None, {"options": select([("draft", "Draft"), ("standard", "Standard"), ("professional", "Professional")])}),
                ("motion_min_shot_duration", "Min micro-shot", "number", .55, .35, 3, .05, {}), ("motion_max_shot_duration", "Max micro-shot", "number", 3.2, .6, 8, .1, {}),
                ("motion_interval_min", "Target interval min", "number", .8, .4, 5, .1, {}), ("motion_interval_max", "Target interval max", "number", 1.8, .6, 8, .1, {}),
                ("motion_normal_max_zoom", "Normal max zoom", "number", 1.32, 1, 1.6, .01, {}), ("motion_punch_max_zoom", "Punch max zoom", "number", 1.48, 1, 1.8, .01, {}),
                ("motion_max_pan_distance", "Max pan distance", "number", .32, .02, .7, .01, {}), ("motion_max_pan_velocity", "Max pan / sec", "number", .42, .02, 1, .01, {}), ("motion_max_zoom_velocity", "Max zoom / sec", "number", .34, .02, 1, .01, {}),
                ("motion_transition_min", "Transition min", "number", .1, .08, .6, .01, {}), ("motion_transition_max", "Transition max", "number", .4, .08, .8, .01, {}),
                ("motion_observation_batch", "Observation batch", "number", 3, 1, 6, 1, {}), ("motion_planning_batch", "Planning batch", "number", 1, 1, 6, 1, {}), ("motion_critic_batch", "Critic batch", "number", 2, 1, 4, 1, {}),
                ("motion_correction_attempts", "JSON correction attempts", "number", 4, 0, 4, 1, {}), ("motion_neighbor_context", "Neighbor beats", "number", 1, 1, 3, 1, {}), ("motion_word_sync_tolerance", "Word-sync tolerance ms", "number", 50, 0, 250, 5, {}), ("motion_face_padding", "Face safety padding", "number", .18, 0, .5, .01, {}),
                ("motion_supersample", "Supersample", "select", "2", None, None, None, {"options": select([("1", "1×"), ("2", "2×"), ("3", "3×"), ("4", "4×")])}),
            ]],
        ]},
        {"id": "delivery", "title": "Delivery & versioning", "description": "Outputs are delivered only after final QC passes.", "collapsed": True, "fields": [
            _field("telegram_low_size", "Send compact Telegram copy", "toggle", default=True),
            _field("telegram_original", "Send original to Telegram", "toggle", default=False),
            _field("commit_artifacts", "Commit and push artifacts", "toggle", default=False),
        ]},
        {"id": "providers", "title": "Locked provider contract", "description": "Fixed by Q Station project design.", "projects": ["q_station"], "collapsed": True, "fields": [
            _field("locked_text", "Text", "readonly", default="ChatGPT · via Ordak"),
            _field("locked_image", "Image", "readonly", default="Gemini · via Ordak"),
            _field("locked_video", "Video", "readonly", default="Google Flow · via Ordak"),
            _field("chatgpt_fallback_auto", "Allow Gemini for a failed text request", "toggle", default=False, help="Recovery policy for text stages only. Off pauses for operator approval; it never changes image or video providers."),
        ]},
    ]
    order = (
        "episode", "format", "character", "visual", "opening", "voice", "music",
        "subtitles", "transitions", "motion", "sfx", "delivery", "providers",
    )
    groups.sort(key=lambda group: order.index(group["id"]))
    return {"schema_version": 2, "groups": groups}


def defaults(schema: dict[str, Any]) -> dict[str, Any]:
    return {field["name"]: field.get("default", False if field["type"] == "toggle" else "") for group in schema["groups"] for field in group["fields"] if field["type"] != "readonly"}
