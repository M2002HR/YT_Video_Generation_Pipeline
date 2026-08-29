# Video 001 — Reference Assets

## Purpose

These files are the canonical visual references for Video 001.

Unlike generated storyboard sheets and cropped beat images, these reference assets **should be committed to Git** because they define the visual identity needed to reproduce consistent images across new ChatGPT sessions.

## Files to place here

Use these exact names:

```text
references/
  style_anchor.png
  character_anchor.png
  bedroom_anchor.png        # optional, add once we decide it is useful
  memory_anchor.png         # optional, add once the recurring embarrassing-memory scene is stable
  REFERENCE_NOTES.md
```

### Required

- `style_anchor.png`
- `character_anchor.png`

### Optional but useful

- `bedroom_anchor.png`
- `memory_anchor.png`

## Source prompts

Generate the required anchors using:

- `prompts/00_style_anchor.md`
- `prompts/00_character_anchor.md`

## Storyboard generation reference order

For Sheet 01, upload:

1. `style_anchor.png`
2. `character_anchor.png`
3. optional environment/memory anchors if available
4. then send `storyboards/SHEET_01_PROMPT.md`

For Sheet 02 and later, upload:

1. `style_anchor.png`
2. `character_anchor.png`
3. optional environment/memory anchors
4. the immediately previous raw storyboard sheet
5. then send the current sheet prompt

Example for Sheet 03:

```text
references/style_anchor.png
references/character_anchor.png
references/bedroom_anchor.png       # if available
assets/raw_storyboards/sheet_02.png
storyboards/SHEET_03_PROMPT.md
```

## Reference priority

When references disagree, use this priority:

1. **character_anchor.png** for face, hair, clothing, proportions, and character identity
2. **style_anchor.png** for rendering style, palette, lighting language, texture, and level of detail
3. dedicated environment/memory anchor for recurring locations or flashbacks
4. previous storyboard sheet for short-range continuity only
5. written prompt for the new action/composition

The previous sheet must not replace the canonical anchors. This prevents gradual visual drift.

## Important rules

- Do not regenerate the character anchor for every video unless intentionally changing the series identity.
- Do not use a newly generated storyboard sheet as the only character reference.
- If a storyboard sheet drifts away from the canonical character, regenerate that sheet using the anchors again.
- Keep reference images visually clean; avoid captions, subtitles, panel numbers, and unnecessary text.
- Commit these reference assets to Git so a new chat/session or automation worker can recover the same visual identity.
