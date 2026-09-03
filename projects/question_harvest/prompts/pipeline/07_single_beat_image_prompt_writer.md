# Prompt 07 — Single Beat Image Prompt Writer (Question Harvest — Body)

## Purpose
Convert ONE visual beat (from body plan) into ONE precise standalone 9:16 image prompt for Gemini.

## Inputs
- STYLE RULES (from preset README + world style): {{STYLE_RULES}}
- WORLD STYLE PLAN: {{WORLD_STYLE_PLAN}}
- CURRENT VISUAL BEAT (JSON): {{VISUAL_BEAT}}
- REFERENCE LIST: {{REFERENCE_IMAGES}}
- PREVIOUS BEAT NOTE: {{PREVIOUS_BEAT}}
- ASPECT RATIO: {{ASPECT_RATIO}}

## Output
Return plain text prompt for Gemini — single paragraph.

## Must Specify
- exactly one standalone image, {{ASPECT_RATIO}}, no storyboard/grid/collage/panels/captions
- world medium (from WORLD STYLE PLAN), texture, palette, lighting
- composition for vertical 9:16 (centered subject, top/bottom safe space)
- narrative moment + reference hierarchy (character_sheet beats drift; previous image short-range only)
- if hero present: same identity (chestnut hair, beard, moss sweater, blue overalls, orange boots) rendered in current world medium — world changes, character identity does not
- no unwanted readable text, no UI

## Reference Hierarchy (§30) to mention:
- If protagonist absent: world style anchor, world keyframe, recurring world reference if needed, previous accepted body image if applicable, prompt
- If present: canonical character_sheet, world style anchor, world keyframe, recurring ref, previous image, prompt

Return ONLY prompt (under 600 chars).

