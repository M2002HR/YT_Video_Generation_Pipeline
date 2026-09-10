# Prompt 07 — Single Beat Image Prompt Writer (Q Station Body)

Convert one visual beat into one standalone Gemini image prompt.

Inputs:
- STYLE RULES: {{STYLE_RULES}}
- WORLD STYLE PLAN: {{WORLD_STYLE_PLAN}}
- CURRENT VISUAL BEAT: {{VISUAL_BEAT}}
- CHARACTER CONTEXT (present only for a host beat): {{CHARACTER_CONTEXT}}
- REFERENCE LIST: {{REFERENCE_IMAGES}}
- PREVIOUS BEAT NOTE: {{PREVIOUS_BEAT}}
- CAPTION LAYOUT: {{CAPTION_LAYOUT_RULE}}
- ASPECT RATIO: {{ASPECT_RATIO}}

Return one paragraph under 1800 characters. Require exactly one {{ASPECT_RATIO}} image, no storyboard/grid/collage/panels/captions or readable text. Preserve the subject world's medium, frame language, texture, palette, lighting and caption layout. If and only if `hero_present` is true, preserve the supplied character identity and behavior while translating rendering medium, and use `character_sheet` for identity only. If absent, do not mention, depict, or infer the selected host. Explain each supplied reference role; never invent an absent reference or copy a reference's pose/layout/composition. The opening environment never carries into an unrelated book-world beat.
