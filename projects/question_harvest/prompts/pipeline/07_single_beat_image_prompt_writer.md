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
- composition for vertical 9:16: preserve the episode's recurring frame language from the
  world keyframe and previous accepted beat (outer material, edge treatment, inner illustration
  window). The interior scene may change freely, but do not drop the framing system.
- reserve a calm, low-detail caption field inside only the bottom 8–10% of the image (two subtitle lines). Keep faces,
  hands, key action, focal objects and critical diagram details above it. This lower reserve must remain completely free of any text, letters, numbers, captions, labels, words or UI — leave it as calm texture/atmosphere only. This is balanced
  negative space, not a large empty banner and not a hard rectangular UI panel.
- narrative moment + reference hierarchy (character_sheet prevents identity drift; style/world
  references establish medium). When present, `previous_beat` is binding for the recurring
  frame language, material/edge treatment, inner illustration window and lower caption reserve;
  it may also inform texture, palette and lighting. It must never be copied as a crop, camera
  angle, pose, subject placement, or focal object.
- if hero present: same identity (chestnut hair, beard, moss sweater, blue overalls, orange boots) rendered in current world medium — world changes, character identity does not
- absolutely no readable text, letters, numbers, captions, labels, words or UI anywhere in the image, especially in the lower caption reserve

## Reference Hierarchy (§30) to mention:
- If protagonist absent: world style anchor, world keyframe, recurring world reference if needed,
  previous_beat if applicable, prompt
- If present: canonical character_sheet, world style anchor, world keyframe, recurring ref,
  previous_beat if applicable, prompt

Return ONLY prompt (under 600 chars).
