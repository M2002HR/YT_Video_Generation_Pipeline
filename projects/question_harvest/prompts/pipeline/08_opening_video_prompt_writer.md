# Prompt 08 — Opening Video Prompt Writer (Flow Clip A — Question Spark)

## Purpose
Write prompt for Flow Clip A (question spark, ~6s source trimmed to ~5s). This clip uses character_sheet as ONLY canonical reference — no style sheet (§12,15). Visual home-world language must be carried by prompt description, not uploaded sheet.

## Inputs
- FINAL SCRIPT (opening_question_spark segment): {{OPENING_A_NARRATION}}
- EPISODE PLAN (JSON): {{EPISODE_PLAN}}
- WORLD STYLE PLAN (JSON): {{WORLD_STYLE_PLAN}}

## Output
Return plain text prompt for Flow (single paragraph, under 500 chars).

## Must Describe (text, not upload)
- simple hand-drawn 2D cartoon, clean dark outlines, warm rustic educational animation, simplified geometry, muted natural palette, readable silhouettes
- protagonist design must match uploaded character_sheet (tall/slim, chestnut hair, beard/goatee, moss sweater, blue overalls, orange boots)
- farm/home/workshop/garden environment appropriate to opening_activity (from episode plan) — but do NOT copy style sheet as upload
- specific ordinary activity (e.g., watering seedlings, sorting tools)
- curiosity trigger moment
- no photorealism, no 3D CGI, no anime, no high-detail concept art
- gentle camera: slow push-in or static, no rapid motion
- protagonist already doing something at frame 0, natural movement

## Example
"Simple hand-drawn 2D cartoon, clean outlines, warm muted palette. Protagonist (tall slim, chestnut hair, beard, moss sweater, blue overalls, orange boots — match character sheet) kneeling in garden watering seedlings at golden hour, pauses noticing uneven sprout line, curious tilt of head, gentle slow push-in, soft daylight, no photorealism"

Return ONLY prompt.

