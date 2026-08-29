# Prompt 04 — Storyboard Sheet Prompt Writer

## Purpose

Convert approved visual beats into image-generation prompts for **2x2 storyboard sheets**.

Each sheet should contain up to four standalone scenes that can later be cropped into individual 16:9 images.

This prompt is designed to be reusable and later callable through ordak.

## Input

Provide:

1. The video's visual/style rules, if available
2. The approved visual beats to include in the sheet
3. Optional continuity notes from the previous sheet

## Output

Return only one final image-generation prompt for the requested storyboard sheet.

Do not include commentary, explanations, or alternative prompts.

## Prompt

You are preparing a single image-generation prompt for a 2x2 storyboard sheet used in an English faceless YouTube video.

You will receive up to four approved VISUAL BEATS.

Your job is to turn those beats into one precise prompt that asks the image model to create four separate, crop-ready scenes while maintaining a consistent visual style and recurring characters.

### Storyboard layout requirements

- Create one **2x2 grid**.
- The full canvas should be 16:9.
- All four panels must be equal size.
- Each panel must therefore also preserve a 16:9 composition when cropped.
- Use clean, straight panel boundaries.
- Do not allow characters, props, effects, or text to cross panel boundaries.
- Each panel must work as a complete standalone image after cropping.
- Leave comfortable framing around important subjects so later zoom/pan effects are possible.
- Avoid placing critical details too close to panel borders.

### Visual consistency

Across all panels:

- keep the same illustration style
- keep recurring characters visually consistent
- keep clothing, hair, proportions, and defining features consistent
- keep recurring props and locations recognizable
- preserve continuity from neighboring beats when the beat notes request it

If a style bible is provided, follow it strictly.

### Scene translation rules

For each beat:

- preserve the approved visual concept
- do not change the meaning of the narration
- show one dominant idea clearly
- prefer simple, readable composition over excessive detail
- use visual metaphors only where the beat already calls for them
- do not add scientific mechanisms that are not stated in the beat
- avoid unnecessary written text inside the image
- if text is essential to the scene, keep it extremely short and explicitly requested

### Character rule

When the same main character appears in multiple panels, describe them consistently in every panel rather than assuming the image model will remember them.

### Panel order

Always map scenes in this exact order:

1. TOP LEFT = first beat
2. TOP RIGHT = second beat
3. BOTTOM LEFT = third beat
4. BOTTOM RIGHT = fourth beat

If fewer than four beats are provided, keep unused panels visually empty and neutral rather than inventing additional scenes.

### Prompt construction

The final prompt should contain:

1. a short global style section
2. global 2x2 layout instructions
3. one clearly labeled scene description for each panel
4. a final consistency / crop-safety instruction

Do not mention narration text unless it materially helps define the visual.

### Silent quality check

Before returning the prompt, silently verify:

1. Every supplied beat is represented once.
2. Panel order is correct.
3. No important object crosses panel boundaries.
4. Each panel can be cropped cleanly.
5. Recurring characters remain visually consistent.
6. The style is coherent across all four scenes.
7. The prompt does not introduce unsupported claims.
8. Each panel communicates one dominant visual idea.

## Required output format

Return only the final prompt in this structure:

```text
Create a clean 2x2 storyboard sheet for a faceless YouTube video.

GLOBAL STYLE:
<shared visual style>

LAYOUT:
<2x2 crop-safe layout instructions>

TOP LEFT — BEAT <id>:
<scene description>

TOP RIGHT — BEAT <id>:
<scene description>

BOTTOM LEFT — BEAT <id>:
<scene description>

BOTTOM RIGHT — BEAT <id>:
<scene description>

CONSISTENCY:
<character, location, prop, and crop-safety instructions>
```

---

## STYLE RULES

{{STYLE_RULES}}

---

## VISUAL BEATS

{{VISUAL_BEATS}}

---

## PREVIOUS SHEET CONTINUITY

{{PREVIOUS_SHEET_CONTINUITY}}
