# Visual Preset 001 — Cinematic Storybook / Green Hoodie

## Purpose

This folder is one reusable visual preset. A visual preset packages the **style prompt + style anchor + character prompt + character anchor** that belong together.

Different videos may select different presets. New presets can be added as sibling folders without changing the storyboard pipeline.

## Contents

- `style_prompt.md` — prompt used to create the style anchor
- `style_anchor.png` — canonical rendering/style reference
- `character_prompt.md` — prompt used to create the recurring character anchor
- `character_anchor.png` — canonical protagonist identity reference

## Preset identity

Rendering:
- polished 2D illustrated-cartoon
- cinematic/storybook lighting
- expressive character acting
- soft painterly shading
- moderate detail

Recurring protagonist:
- adult male in his twenties
- dark tousled hair
- expressive eyebrows and eyes
- green hoodie
- dark pants

## Usage

When a video selects this preset:

For Sheet 01 upload:
1. `style_anchor.png`
2. `character_anchor.png`
3. any video-specific recurring anchors
4. send the current sheet prompt

For Sheet 02+ upload:
1. `style_anchor.png`
2. `character_anchor.png`
3. any video-specific recurring anchors
4. previous raw storyboard sheet
5. send the current sheet prompt

The preset anchors are canonical. The previous sheet is only for local continuity and must never override the canonical character/style anchors.

## Adding another visual mode

Create another sibling folder, for example:

```text
visual_presets/
  001_cinematic_storybook_green_hoodie/
  002_minimal_stick_figure/
  003_flat_editorial/
```

Each preset should contain its own prompts and generated anchor images.
