# Q Station Character Reference Rules

Character sheets are `IDENTITY_ONLY`: they define face, silhouette, proportions, hair, facial hair and outfit. They never define pose, camera, sheet/grid layout, background or environment. Opening environment is generated per episode by Stage 03; it is not owned by a character.

- Visual preset controls opening rendering treatment, not WHO the host is.
- World style controls the inside-book subject world, not WHO the host is.
- Gemini body images receive `CharacterContext` and the selected canonical sheet only when `hero_present` is true. Host-absent beats receive neither.
- WORLD_KEYFRAME is always host-free and receives no character context or sheet.
- Flow never receives any visual/style sheet.
- Flow Clip A uses Ingredients mode with only the selected character-pack sheet in role `character_sheet`.
- Flow Clip B uses Frames mode only: episode book cover as `first_frame`, host-free WORLD_KEYFRAME as `last_frame`. It receives no character ingredient or character/opening prompt context.

New runtime identity must come from `characters/registry.json` and `CharacterContext`, never `visual_presets/001_home_world/character_sheet.png`. That old file remains only for historical compatibility.
