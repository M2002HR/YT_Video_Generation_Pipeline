# Storyboard Workflow

## Goal

Generate crop-ready 2x2 storyboard sheets while keeping character and visual consistency across new chats/sessions.

## Inputs

Canonical references:
- `references/style_anchor.png`
- `references/character_anchor.png`

Optional recurring references:
- `references/bedroom_anchor.png`
- `references/memory_anchor.png`

Per-sheet inputs:
- current `SHEET_XX_PROMPT.md`
- previous raw storyboard sheet for Sheet 02+

## Workflow

### Step 1 — Generate canonical anchors once

Generate:
- style anchor
- character anchor

Review them manually.

When approved, save them under `references/` and commit them to Git.

### Step 2 — Generate Sheet 01

Start a new image-generation chat/session if needed.

Upload:
1. style anchor
2. character anchor
3. optional recurring environment anchors

Then send `SHEET_01_PROMPT.md`.

Download the resulting image as:

```text
assets/raw_storyboards/sheet_01.png
```

Do **not** commit this raw generated sheet.

### Step 3 — Generate Sheet 02+

For each next sheet, upload:

1. style anchor
2. character anchor
3. optional dedicated recurring anchors
4. previous raw storyboard sheet

Then send the next sheet prompt.

Example:

```text
style_anchor.png
character_anchor.png
sheet_02.png
SHEET_03_PROMPT.md
```

Download to:

```text
assets/raw_storyboards/sheet_03.png
```

### Step 4 — Consistency check

Before accepting a sheet, verify:

- same main character face
- same hair shape
- same green hoodie identity
- same body proportions
- same rendering style
- same recurring bedroom when applicable
- same recurring memory cast when applicable
- no visible panel numbers
- no narration captions
- no visible divider lines
- no important content crossing the invisible center crop boundaries

If consistency fails, regenerate the sheet using the same canonical anchors.

### Step 5 — Crop

After all raw sheets are approved, crop each image at exactly 50% width and 50% height:

```text
sheet_01.png
  top-left     -> beat_01.png
  top-right    -> beat_02.png
  bottom-left  -> beat_03.png
  bottom-right -> beat_04.png
```

Continue sequentially.

For Sheet 05, only keep the active beat panels.

Cropped outputs go to:

```text
assets/cropped_beats/
```

Raw sheets and cropped beats are local build assets and remain Git-ignored.

## Git policy

Commit:
- prompts
- workflow docs
- reference notes
- canonical reference images
- scripts/code

Do not commit:
- raw generated storyboard sheets
- cropped beat images
- audio
- rendered video files
