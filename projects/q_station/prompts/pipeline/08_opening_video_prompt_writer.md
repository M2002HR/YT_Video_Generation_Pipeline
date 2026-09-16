# Prompt 08 — Opening Video Prompt Writer (Flow Clip A)

Write one Flow prompt of roughly 100-180 words (at most 1800 characters) for the question-spark opening. Return plain text only.

Inputs:
- OPENING NARRATION: {{OPENING_A_NARRATION}}
- SOURCE DURATION SECONDS: {{SOURCE_DURATION_SECONDS}}
- MEASURED NARRATION SECONDS: {{NARRATION_DURATION_SECONDS}}
- SELECTED CONCEPT: {{OPENING_CONCEPT}}
- EPISODE PLAN: {{EPISODE_PLAN}}
- VISUAL PRESET RULES: {{VISUAL_PRESET_RULES}}
- RESOLVED CHARACTER CONTEXT: {{CHARACTER_CONTEXT}}
- PRESENTATION RULES: {{PRESENTATION_RULES}}

The uploaded `character_sheet` is identity-only and the only ingredient. Prioritize the exact first-frame evidence, one clear cause/reaction and the A/B handoff.
Use only the most identifying appearance anchors plus the sheet; do not spend the entire prompt
relisting anatomy. Preserve behavior and negative constraints. Describe the episode-specific action
and setting, never independently invent a generic routine. The host is already acting at frame zero.

Follow PRESENTATION RULES for how the action progresses into Intro B. Do not substitute a different entry mechanism.

The first 1–2 seconds MUST visibly establish `opening_visual_proof` from the episode plan: put its object, mismatch, event, or spatial relationship on-screen and connect it to what the host is doing or noticing. Preserve the intended `topic_visual_link` and `link_type` through action and composition, not an explanatory caption, readable text, logo, or a random literal topic prop. The prompt must make this visual proof and its resulting reaction explicit; do not leave their connection implied. Topic/script determine shot purpose. Never request a style-sheet upload, sheet/grid layout, photorealism, 3D CGI or anime. Do not substitute a different character.

Complete the required evidence and handoff inside the measured narration interval, not merely by
the end of the longer source clip. Extra source frames are trim handles: hold the attained end state
instead of placing the key reveal there. No more than three clear physical actions. Preserve the
selected premise and planned end state. Do not include a promise of audience reaction or performance.
