# Prompt 07 — Single Beat Image Prompt Writer (Question Harvest — Body)

## Purpose
Convert ONE visual beat (from body plan) into ONE precise standalone 9:16 image prompt for Gemini.

## Inputs
- STYLE RULES (from preset README + world style): {{STYLE_RULES}}
- WORLD STYLE PLAN: {{WORLD_STYLE_PLAN}}
- CURRENT VISUAL BEAT (JSON): {{VISUAL_BEAT}}
- REFERENCE LIST: {{REFERENCE_IMAGES}}
- PREVIOUS BEAT NOTE: {{PREVIOUS_BEAT}}
- CAPTION LAYOUT: {{CAPTION_LAYOUT_RULE}}
- ASPECT RATIO: {{ASPECT_RATIO}}

## Output
Return plain text prompt for Gemini — single paragraph.

## Must Specify
- exactly one standalone image, {{ASPECT_RATIO}}, no storyboard/grid/collage/panels/captions
- world medium (from WORLD STYLE PLAN), texture, palette, lighting
- composition for vertical 9:16: preserve the episode's recurring frame language from the
  world keyframe and previous accepted beat (outer material, edge treatment, inner illustration
  window). The interior scene may change freely, but do not drop the framing system.
- caption layout: {{CAPTION_LAYOUT_RULE}}
- narrative moment + reference hierarchy (character_sheet prevents identity drift; style/world
  references establish medium). When present, `previous_beat` is binding for the recurring
  frame language, material/edge treatment, inner illustration window, texture, palette and
  lighting. Follow the explicit caption-layout rule even if the reference contains a different
  lower layout. It must never be copied as a crop, camera
  angle, pose, subject placement, or focal object.
- if hero present: same identity (chestnut hair, beard, moss sweater, blue overalls, orange boots) rendered in current world medium — world changes, character identity does not
- absolutely no readable text, letters, numbers, captions, labels, words or UI anywhere in the image

## Reference Hierarchy (§30) to mention:
- If protagonist absent: world style anchor, world keyframe, recurring world reference if needed,
  previous_beat if applicable, prompt
- If present: canonical character_sheet, world style anchor, world keyframe, recurring ref,
  previous_beat if applicable, prompt

The reference hierarchy applies ONLY to identity and visual medium. The requested scene,
subject and composition are authoritative. Never write "references > prompt". Character
and style sheets must never be reproduced as sheets, grids, panels or swatches in the output.
Name the purpose of each supplied reference explicitly. Do not invent an absent reference.

Return ONLY prompt (under 1800 chars; preserve the constraints instead of over-compressing).
