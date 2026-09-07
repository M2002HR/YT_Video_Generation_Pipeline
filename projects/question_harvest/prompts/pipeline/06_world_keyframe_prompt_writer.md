# Prompt 06 — World Keyframe Prompt Writer (Question Harvest)

## Purpose
Write ONE precise image prompt for the WORLD_KEYFRAME that establishes world texture/palette/medium and will become book page image + Flow end frame + first body image (& body reference).

## Inputs
- FINAL SCRIPT: {{FINAL_SCRIPT}}
- EPISODE PLAN: {{EPISODE_PLAN}}
- WORLD STYLE PLAN (JSON): {{WORLD_STYLE_PLAN}}
- VISUAL PLAN (JSON): {{VISUAL_PLAN}}

## Output
Return plain text prompt (no JSON, no headings) — exactly one line of instructions for Gemini image generation.

## Must Specify
- one standalone image
- 9:16 aspect (vertical, readable silhouettes, safe space)
- world medium (from WORLD STYLE PLAN medium)
- texture family
- composition (subject, atmosphere, lighting)
- establish the episode's recurring frame language: outer material/edge treatment plus an
  inner illustration window appropriate to the chosen medium
- reserve a calm lower caption field inside only the bottom 8–10% of the frame (two subtitle lines); it must be free
  of the focal subject and readable detail, but not an oversized blank strip
- narrative moment (the world as frozen keyframe, before animation)
- no readable text, no UI, no grid, no farm leakage unless relevant
- if protagonist present, same identity but rendered in this world's medium (hair/beard/overalls silhouette preserved)

## Constraints
- Gemini will receive references: canonical character_sheet (if protagonist present), style_anchor (from world style), recurring world reference if needed. Your prompt must not require extra uploads.
- Keep prompt under 500 characters, highly visual.
- The world keyframe is the structural reference for all later body images: its frame language,
  paper/material texture and lower caption reserve must be plainly visible and repeatable.

Example beginning: "Create exactly one 9:16 image, charcoal on warm paper, ..."

Return ONLY prompt text.
