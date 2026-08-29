# Per-Beat Image Workflow

## Core decision

The pipeline uses **one full-resolution generated image per visual beat**.

The previous 2x2 storyboard-sheet approach is deprecated because splitting one generated canvas into four crops reduced usable image quality.

## Visual preset

Video 001 uses the preset declared in `../VISUAL_PRESET.md`.

Canonical anchors:
- style anchor: rendering, palette, lighting, texture, detail level
- character anchor: protagonist identity, face, hair, green hoodie, proportions

Optional video-specific anchors may live in `../references/`.

## Generation sequence

### Beat 01

Upload:
1. style anchor
2. character anchor
3. relevant video-specific anchors, if any

Then send:
`BEAT_01_PROMPT.md`

Save the accepted output as:
`../assets/raw_beats/beat_01.png`

### Beat 02 and later

For each beat N, upload:
1. style anchor
2. character anchor
3. relevant video-specific anchors, if any
4. `beat_(N-1).png` as the previous beat reference

Then send:
`BEAT_NN_PROMPT.md`

Save as:
`../assets/raw_beats/beat_NN.png`

## Reference priority

If references disagree:
1. character anchor wins for protagonist identity
2. style anchor wins for rendering style
3. dedicated video anchor wins for recurring location/cast/prop
4. previous beat controls only immediate continuity
5. current prompt controls new action/composition

This prevents cumulative drift.

## Acceptance checklist

Before keeping any beat image:
- exactly one standalone image
- 16:9
- protagonist matches character anchor
- style matches style anchor
- recurring bedroom/memory/cast remain consistent where relevant
- image advances the current beat rather than duplicating previous beat
- no comic grid or multi-panel layout
- no captions/subtitles/narration text
- no unnecessary readable text
- composition has enough breathing room for editing motion

If a beat fails, regenerate that beat using the same anchors and same previous accepted beat.

## Output directory

```text
assets/raw_beats/
  beat_01.png
  beat_02.png
  ...
  beat_18.png
```

Generated beat images are local build assets and remain Git-ignored.

## Git policy

Commit:
- beat prompt files
- reusable visual presets and their canonical anchors
- workflow docs
- video-specific reusable anchors
- scripts/config/code

Do not commit:
- generated beat images
- generated audio
- rendered video
