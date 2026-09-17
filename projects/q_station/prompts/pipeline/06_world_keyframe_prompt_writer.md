# Prompt 06 — World Keyframe Prompt Writer (Q Station)

Write one precise Gemini prompt for a host-free WORLD_KEYFRAME establishing the post-entry subject world.

Inputs:
- FINAL SCRIPT: {{FINAL_SCRIPT}}
- WORLD STYLE PLAN: {{WORLD_STYLE_PLAN}}
- CAPTION LAYOUT: {{CAPTION_LAYOUT_RULE}}
- FIRST SUBJECT-WORLD DISCOVERY: {{WORLD_ENTRY_DISCOVERY}}

Return one plain-text prompt under 1800 characters. Specify one standalone 9:16 image, the chosen subject-world medium, texture, palette, lighting, recurring frame language, narrative atmosphere, and caption layout. The composition must contain no recurring host, no selected host, no foreground person/character, no readable text, UI, grid, sheet layout or swatches. Do not mention or infer the opening activity/environment. Reference input is the world-style anchor only and conveys medium, never composition. WORLD_KEYFRAME is Clip B's final frame, so host isolation is absolute.

Use the supplied factual discovery for shot purpose, never its original host or opening setting. No recurring host is allowed even if an upstream description accidentally includes one.


## Binding layout isolation
The viewer is INSIDE the topic world. Every scene fills the 9:16 image edge-to-edge, including the final optional-closing image. No enclosing physical page, book spread, card, gutter, decorative border, inset illustration window, doorway rim or lens mask. Preserve artistic medium, grain, palette and lighting, not a reference's border or composition. Paper/ink/collage texture is allowed; a subject-relevant book can be an object in the scene without becoming the layout. Opening entry mechanisms must not dictate body/world composition. If returning a production image prompt, include these constraints explicitly. Respect the caption-layout rule, never insert printed labels or a blank footer.
