# Video 001 — Visual Preset

Selected preset:

```text
visual_presets/001_cinematic_storybook_green_hoodie/
```

This preset defines the canonical style and protagonist identity for Video 001.

## Per-beat reference order

### Beat 01
1. selected preset's `style_anchor.png`
2. selected preset's `character_anchor.png`
3. optional video-specific anchors from `references/`
4. current beat prompt

### Beat 02+
1. selected preset's `style_anchor.png`
2. selected preset's `character_anchor.png`
3. optional video-specific anchors from `references/`
4. immediately previous accepted image from `assets/raw_beats/`
5. current beat prompt

## Priority

If the previous beat drifts from the canonical preset, the canonical preset wins.

The previous beat exists only to preserve short-range continuity; it is not the source of truth for character identity or rendering style.
