# Prompt 04 — Storyboard Sheet Prompt Writer

## Purpose

Convert approved visual beats into image-generation prompts for **2x2 storyboard sheets** while preserving visual identity through explicit image references.

Each sheet should contain up to four standalone scenes that can later be cropped automatically into individual 16:9 images.

This prompt is designed to be reusable and later callable through ordak.

## Required references

When generating a storyboard sheet, the calling workflow should provide image references in this order whenever available:

1. **STYLE ANCHOR** — canonical rendering style
2. **CHARACTER ANCHOR** — canonical protagonist identity
3. optional recurring environment/memory anchors
4. **PREVIOUS SHEET** — for short-range continuity only

Reference priority:
- character anchor controls identity
- style anchor controls visual rendering
- dedicated location/memory anchors control recurring world elements
- previous sheet controls local continuity
- current written prompt controls the new action/composition

Never rely on the previous sheet alone for character identity because this can cause cumulative drift.

## Input

Provide:

1. visual/style rules
2. approved visual beats
3. reference-image descriptions/order
4. optional continuity notes from the previous sheet

## Output

Return only one final image-generation prompt for the requested storyboard sheet.

Do not include commentary, explanations, or alternative prompts.

## Prompt

You are preparing a single image-generation prompt for a 2x2 storyboard sheet used in an English faceless YouTube video.

You will receive up to four approved VISUAL BEATS and may also receive image references.

Your job is to create four separate, crop-ready scenes while strictly preserving the canonical visual identity.

### Reference handling

Explicitly tell the image model:

- use the CHARACTER ANCHOR as the source of truth for face shape, hair, clothing, body proportions, age impression, and character identity
- use the STYLE ANCHOR as the source of truth for illustration rendering, palette, lighting language, texture, and level of detail
- use dedicated environment/memory anchors when supplied
- use the PREVIOUS SHEET only for local continuity such as the immediately preceding pose, room state, or recurring object
- do not redesign the protagonist based on the previous sheet
- if the previous sheet differs from the character anchor, follow the character anchor

### Storyboard layout requirements

- Create one **2x2 quadrant layout**.
- The full canvas should be 16:9.
- All four quadrants must have exactly equal dimensions.
- Do **not** draw visible panel borders, white divider lines, comic frames, boxes, panel numbers, or corner labels.
- The four scenes should meet at the exact horizontal and vertical midlines naturally, with no decorative separator.
- Treat the center horizontal and vertical lines as **invisible crop boundaries**.
- No character, prop, glow, bubble, projection, shadow, or important object may cross an invisible crop boundary.
- Each quadrant must work as a complete standalone 16:9 image after a simple 50/50 crop.
- Leave comfortable framing around important subjects so later zoom/pan effects are possible.
- Avoid placing critical details too close to the center crop boundaries or outer edges.

### Text policy

Never add:
- beat numbers
- panel numbers
- captions
- narration text
- subtitles
- scene labels
- watermarks
- logos
- explanatory text at the bottom of a panel

Small diegetic/story-native text may be used only when it materially improves the visual idea, such as:
- a very short speech bubble like “Hey…”
- a clock display
- a tiny natural sign or notification

Keep such text rare and very short. Prefer communicating visually.

### Visual consistency

Across all quadrants:

- keep the exact canonical protagonist identity
- keep recurring clothing and hair unchanged
- preserve recurring props and locations
- preserve the same illustration rendering
- preserve established recurring flashback characters when applicable
- maintain continuity from neighboring beats without drifting away from the anchors

### Panel order

Always map scenes in this exact order:

1. TOP LEFT = first beat
2. TOP RIGHT = second beat
3. BOTTOM LEFT = third beat
4. BOTTOM RIGHT = fourth beat

If fewer than four beats are provided, keep unused quadrants visually neutral and empty rather than inventing additional scenes.

### Silent quality check

Before returning the prompt, silently verify:

1. Every supplied beat is represented once.
2. Quadrant order is correct.
3. Canonical character anchor is explicitly prioritized.
4. Canonical style anchor is explicitly prioritized.
5. Previous sheet is used only for local continuity.
6. There are no requested visible borders or panel numbers.
7. There are no narration captions or subtitles.
8. Any allowed story-native text is minimal.
9. No important object crosses invisible crop boundaries.
10. Each quadrant can be cropped cleanly at exactly 50% width and 50% height.
11. The prompt does not introduce unsupported claims.

## Required output format

Return only the final prompt in this structure:

```text
Create a seamless 2x2 storyboard sheet for a faceless YouTube video.

REFERENCE PRIORITY:
<explain canonical character/style anchors and previous-sheet role>

GLOBAL STYLE:
<shared visual style>

INVISIBLE CROP LAYOUT:
<equal 2x2 quadrant and crop-safety instructions; no visible borders or numbers>

TEXT POLICY:
<no captions/subtitles/narration text; rare short story-native text only if needed>

TOP LEFT — BEAT <id>:
<scene description>

TOP RIGHT — BEAT <id>:
<scene description>

BOTTOM LEFT — BEAT <id>:
<scene description>

BOTTOM RIGHT — BEAT <id>:
<scene description>

CONSISTENCY:
<character, location, memory, reference-image continuity, and crop-safety instructions>
```

---

## STYLE RULES

{{STYLE_RULES}}

---

## VISUAL BEATS

{{VISUAL_BEATS}}

---

## REFERENCE IMAGES

{{REFERENCE_IMAGES}}

---

## PREVIOUS SHEET CONTINUITY

{{PREVIOUS_SHEET_CONTINUITY}}
