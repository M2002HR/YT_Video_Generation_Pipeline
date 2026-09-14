# Visual Preset 001 — Cinematic Storybook / Green Hoodie

## Purpose

This folder is one reusable visual preset. A visual preset packages the **style prompt + style anchor + character prompt + character anchor** that belong together.

Different videos may select different presets. New presets can be added as sibling folders without changing the image pipeline.

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

When a video selects this legacy preset, each beat is generated as one image. Supply
`style_anchor.png`, add `character_anchor.png` only when the protagonist is present, add any
genuinely required video-owned identity reference, and send the current single-beat prompt.
The preset anchors remain canonical; a previous generated scene is not a style source.

## Adding another visual mode

Create another sibling folder, for example:

```text
visual_presets/
  001_cinematic_storybook_green_hoodie/
  002_minimal_stick_figure/
  003_flat_editorial/
```

Each preset should contain its own prompts and generated anchor images.
