# Prompt 09 — Entry Transition Video Prompt Writer (Flow Intro B)

Write one tight Flow prompt (roughly 120–220 words) for the second intro clip. Return plain text only.

Inputs:
- ENTRY NARRATION: {{ENTRY_TRANSITION_NARRATION}}
- TOPIC: {{TOPIC}}
- ENTRY PROFILE: {{PRESENTATION_CONTEXT}}
- ENTRY TRANSITION CONTRACT: {{ENTRY_TRANSITION_RULES}}
- WORLD STYLE PLAN: {{WORLD_STYLE_PLAN}}
- FINAL WORLD KEYFRAME DESCRIPTION: {{WORLD_KEYFRAME_DESC}}
- SOURCE DURATION SECONDS: {{SOURCE_DURATION_SECONDS}}
- MEASURED NARRATION SECONDS: {{NARRATION_DURATION_SECONDS}}
- STORY HANDOFF (not a new character ingredient): {{ENTRY_BRIDGE}}
- ACTUAL ENTRY-FRAME DIRECTION: {{ENTRY_FRAME_DIRECTION}}

Flow receives first_frame (the episode-specific entry object/presentation) and last_frame (the exact
host-free topic-world keyframe). It receives no style sheet or character ingredient in Frames mode.
Write a continuous hand-drawn 2D shot that obeys ENTRY TRANSITION CONTRACT, begins exactly on the
supplied first frame, gradually adopts the topic world's palette, texture, atmosphere and visual
language inside the entry mechanism, and ends exactly on the supplied last frame. Preserve any
ownership cue already baked into the first frame when the profile requires it. Do not invent uploads,
readable text, UI, 3D CGI, photorealism, a hard cut, flash, unrelated character, or alternate endpoint.

Carry the selected informational reveal rather than add an unrelated spectacle. The configured first
and last frames are binding; the handoff supplies causal/visual meaning, never alternate endpoints.
Reach the exact world frame before the measured narration boundary. Use excess source duration only
as a stable handle, because it may be trimmed. Never delay the essential reveal to that excess tail.
