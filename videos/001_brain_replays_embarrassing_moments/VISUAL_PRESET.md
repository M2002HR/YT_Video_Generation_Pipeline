# Video 001 — Visual Preset

Selected preset:

```text
visual_presets/001_cinematic_storybook_green_hoodie/
```

This preset defines the canonical style and main-character identity for Video 001.

## Storyboard reference order

For Sheet 01:
1. `visual_presets/001_cinematic_storybook_green_hoodie/style_anchor.png`
2. `visual_presets/001_cinematic_storybook_green_hoodie/character_anchor.png`
3. optional video-specific references from `references/`
4. current sheet prompt

For Sheet 02+:
1. style anchor from selected preset
2. character anchor from selected preset
3. optional video-specific references
4. previous raw storyboard sheet from `assets/raw_storyboards/`
5. current sheet prompt

If the previous sheet drifts from the preset, the preset wins.
