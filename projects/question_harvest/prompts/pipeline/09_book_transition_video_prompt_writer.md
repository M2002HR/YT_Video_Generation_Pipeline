# Prompt 09 — Book Transition Video Prompt Writer (Flow Clip B)

## Purpose
Write the Google Flow prompt for **Clip B**: a ~3 second (4s source) pure 2D hand-drawn
vertical 9:16 shot in which an ancient magical storybook turns pages, stops on the page
that illustrates **this episode's topic**, and the camera pushes into that illustration.

This clip is the bridge from the home world into the book world. It has **no characters**.

## Canonical reference contract (do not restate as an upload instruction)
Flow receives, through its own controls:
- canonical reference sheet: `book_design_sheet.png` (the magical book's locked identity)
- first frame: `book_spread_frame.png` (the open spread whose page holds this episode's world)
- last frame: `world_keyframe.png` (the exact frame the camera must end inside)

Flow receives **NO style sheet** — no world style anchor, no home style sheet, no mood board.
Therefore your prompt text must carry the visual treatment in words.

## Inputs
- BOOK TRANSITION NARRATION: {{BOOK_TRANSITION_NARRATION}}
- EPISODE PLAN (JSON): {{EPISODE_PLAN}}
- TOPIC: {{TOPIC}}
- WORLD STYLE PLAN (JSON): {{WORLD_STYLE_PLAN}}
- WORLD KEYFRAME DESCRIPTION: {{WORLD_KEYFRAME_DESC}}
- SOURCE DURATION SECONDS: {{SOURCE_DURATION_SECONDS}}

## Output
Return **only** the Flow prompt as plain text. No markdown, no headings, no commentary.

## Core concept the prompt must express
A magical ancient storybook is being explored. The scene is only about the book and the
discovery of a hidden illustrated page:

BOOK → PAGE TURNING → MYSTERIOUS ILLUSTRATION → ENTERING THE PAINTING

The viewer should feel: "What secret world is hidden inside this book?"

## Reference lock — the book already exists
State that the book's visual identity comes from the supplied reference sheet and must be
preserved exactly, never redesigned: antique brown leather cover, worn aged surface,
golden/brass corner protectors, side clasp, central eye symbol, crescent moon symbol,
star symbols, thick aged pages, green bookmark ribbon, exact proportions, exact silhouette,
exact illustration style. Animate the asset; do not invent a different book.

## Style lock
Pure 2D hand-drawn storybook animation: clean ink outlines, flat illustrated colors,
simple cel shading, warm parchment tones, handcrafted cartoon feeling, educational
adventure atmosphere, magical storybook mood.

Forbid: 3D, CGI, realistic materials, photorealism, cinematic realism, realistic camera
effects, 3D depth, realistic portal effects. Everything must look like a beautifully
animated drawing.

## Shot structure (scale the timings to SOURCE DURATION SECONDS)
1. **Mysterious book opening** (first ~27% of the clip) — start immediately close-up inside
   the already-open book: aged pages, hand-drawn illustrations, ancient paper texture.
   Pages gently move; soft golden light comes from between them. No character, no hands,
   no movement inside the illustration.
2. **Discovering the topic page** (middle ~33%) — the book slowly turns pages revealing
   faded story illustrations; the camera follows the page movement; the book stops on the
   special page whose hand-drawn illustration relates to **{{TOPIC}}**. The drawing itself
   stays still. Magic comes only from a soft golden glow around the page, subtle particles,
   and illuminated ink lines.
3. **Entering the page world** (final ~40%) — the camera slowly pushes into that
   illustration; the painted image grows; the paper texture fills the screen; the final
   frame is completely inside the illustrated world, matching the supplied last frame.

## Camera direction
Only simple 2D camera movement: slow push-in, gentle zoom, page-following movement, smooth
transition into the illustration. Forbid camera orbit, 3D movement, dramatic perspective,
lens effects, realistic depth of field.

## Animation direction
Animate only: slow page turning, paper movement, gentle magical glow, floating tiny
particles, camera movement. Do not animate characters, creatures, objects inside the
illustration, or events inside the painting. The page illustration stays a still drawing
until the camera enters it.

## Negative constraints the prompt must include
No farmer, no characters, no people, no hands opening the book, no moving creatures, no
animated drawings inside the page, no different book design, no new symbols, no 3D book,
no realistic paper, no CGI magic, no fantasy portal effects, no chaotic transitions,
no readable text (decorative marks must stay abstract, never real words), no style drift,
no identity drift.

## Continuity requirements
- Preserve the first frame's geometry exactly at the start.
- Preserve the page illustration exactly — never invent page elements.
- End exactly inside the world of the supplied last frame, at the moment before the next
  beat begins.

## Length
Keep the prompt tight and directive — roughly 120–220 words, one flowing block of
instructions. No lists, no numbered shots in the output, no meta commentary.

Return ONLY the prompt text.
