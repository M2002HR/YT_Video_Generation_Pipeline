# Storyboard Workflow

## Goal

Generate crop-ready 2x2 storyboard sheets while keeping character and visual consistency across different chats and browser sessions.

## 1. Select a reusable visual preset

Every video selects one preset from:

```text
visual_presets/
```

The selected preset for this video is declared in:

```text
../VISUAL_PRESET.md
```

A preset contains:
- style prompt
- style anchor image
- character prompt
- character anchor image

The preset is reusable across multiple videos.

## 2. Add optional video-specific anchors

Only references unique to this video's world belong in:

```text
../references/
```

Examples:
- `bedroom_anchor.png`
- `memory_anchor.png`

Do not duplicate the global style or main-character anchors here.

## 3. Generate Sheet 01

Upload, in this order:

1. selected preset's `style_anchor.png`
2. selected preset's `character_anchor.png`
3. any video-specific anchors
4. send `SHEET_01_PROMPT.md`

Download the accepted result to:

```text
../assets/raw_storyboards/sheet_01.png
```

Raw storyboard sheets are local assets and are Git-ignored.

## 4. Generate Sheet 02 and later

For every later sheet, upload:

1. selected preset's `style_anchor.png`
2. selected preset's `character_anchor.png`
3. any relevant video-specific anchors
4. the immediately previous raw storyboard sheet
5. send the current `SHEET_XX_PROMPT.md`

Example for Sheet 03:

```text
visual_presets/<selected>/style_anchor.png
visual_presets/<selected>/character_anchor.png
../assets/raw_storyboards/sheet_02.png
SHEET_03_PROMPT.md
```

### Reference priority

If references disagree:

1. character anchor controls protagonist identity
2. style anchor controls rendering style
3. dedicated video-specific anchors control recurring locations/flashbacks
4. previous sheet controls short-range continuity only
5. current prompt controls the new action/composition

Never rely on the previous sheet as the only identity reference; that creates cumulative visual drift.

## 5. Acceptance check for every raw sheet

Before keeping a generated sheet, verify:

- protagonist identity matches the character anchor
- style matches the style anchor
- recurring locations/cast remain recognizable
- no visible panel numbers
- no narration captions or subtitles
- no visible divider/grid lines
- no important content crosses the invisible 50% horizontal or vertical crop lines
- all four quadrants are usable as standalone images

If a sheet fails, regenerate it using the same canonical anchors.

## 6. Raw storyboard file names

For Video 001, save the five accepted sheets exactly as:

```text
../assets/raw_storyboards/
  sheet_01.png
  sheet_02.png
  sheet_03.png
  sheet_04.png
  sheet_05.png
```

Do not commit these files.

## 7. Crop all sheets into beat images

Install local dependencies once:

```bash
python -m pip install -r requirements.txt
```

From the repository root run:

```bash
python scripts/crop_storyboards.py \
  videos/001_brain_replays_embarrassing_moments
```

The cropper reads `VISUAL_BEATS.md`, detects that Video 001 has 18 beats, and maps quadrants in this order:

```text
top-left
top-right
bottom-left
bottom-right
```

So:

```text
sheet_01.png -> beat_01.png ... beat_04.png
sheet_02.png -> beat_05.png ... beat_08.png
sheet_03.png -> beat_09.png ... beat_12.png
sheet_04.png -> beat_13.png ... beat_16.png
sheet_05.png -> beat_17.png, beat_18.png
```

Unused quadrants in the final sheet are ignored automatically.

Outputs are written to:

```text
../assets/cropped_beats/
  beat_01.png
  ...
  beat_18.png
```

These files are also Git-ignored.

If you intentionally want to replace existing crops:

```bash
python scripts/crop_storyboards.py \
  videos/001_brain_replays_embarrassing_moments \
  --overwrite
```

## Git policy

Commit:
- visual presets and their canonical anchor images
- prompts
- storyboard workflow/docs
- video-specific reusable anchors
- source code/scripts

Do not commit:
- raw generated storyboard sheets
- cropped beat images
- generated audio
- rendered videos
