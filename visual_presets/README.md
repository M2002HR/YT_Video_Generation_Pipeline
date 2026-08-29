# Visual Presets

This directory stores reusable visual identities for the video pipeline.

Each preset is self-contained and contains the prompts used to create its canonical reference images.

## Required preset structure

```text
visual_presets/<preset_id>/
  README.md
  style_prompt.md
  style_anchor.png
  character_prompt.md
  character_anchor.png
```

A preset may later include additional shared assets if they are genuinely reusable across videos.

## Selection

Each video should explicitly declare which preset it uses in a `VISUAL_PRESET.md` file.

Video-specific references such as a recurring bedroom or a one-off memory scene should stay inside the video's own `references/` directory rather than inside the global preset.
