# Prompt 09 — Book Transition Video Prompt Writer (Flow Clip B)

## Purpose
Write the Google Flow prompt for **Clip B**: a ~3 second (4s source) pure 2D hand-drawn
vertical 9:16 shot in which an ancient magical storybook turns pages, stops on the page
that illustrates **this episode's topic**, and the camera pushes into that illustration.

This clip is the bridge from the home world into the book world. It has **no characters**.

## Canonical reference contract (do not restate as an upload instruction)
Flow receives, through its own controls:
- first frame: `book_cover_frame.png` (one CLOSED, episode-specific book cover)
- last frame: `world_keyframe.png` (the exact frame the camera must end inside)

Frames mode is exclusive: Flow receives no ingredient or canonical sheet for this clip.

Flow receives **NO style sheet** — no world style anchor, no home style sheet, no mood board.
Therefore your prompt text must carry the visual treatment in words.

## Inputs
- BOOK TRANSITION NARRATION: {{BOOK_TRANSITION_NARRATION}}
- TOPIC: {{TOPIC}}
- WORLD STYLE PLAN (JSON): {{WORLD_STYLE_PLAN}}
- WORLD KEYFRAME DESCRIPTION: {{WORLD_KEYFRAME_DESC}}
- SOURCE DURATION SECONDS: {{SOURCE_DURATION_SECONDS}}

## Output
Return **only** the Flow prompt as plain text. No markdown, no headings, no commentary.

## Core concept the prompt must express
A magical, episode-specific storybook is seen closed, opens naturally, then reveals one right-hand
illustrated page and enters it:

BOOK → PAGE TURNING → MYSTERIOUS ILLUSTRATION → ENTERING THE PAINTING

The viewer should feel: "What secret world is hidden inside this book?"

## Reference lock — the book already exists
State that the CLOSED supplied cover is the exact start frame and must be preserved at the first
moment. Camera is locked perfectly top-down and the cover fills almost the whole vertical frame;
never tilt, orbit, use perspective, or pull back. Its detailed topic-symbolic ornament and material
texture are episode-specific; do not add titles, lettering, extra symbols or redesign it. Open this
exact physical book naturally while retaining the top-down view.

## Style lock
Refined 2D illuminated-storybook animation: confident clean ink contours, rich restrained
chestnut leather and antique-gold details, warm parchment grain, elegant page deck, subtle
cel shading, handcrafted premium educational-adventure feeling. It must feel like a carefully
animated heirloom illustration, not generic clip-art.

Forbid: 3D, CGI, realistic materials, photorealism, cinematic realism, realistic camera
effects, 3D depth, realistic portal effects. Everything must look like a beautifully
animated drawing.

## Shot structure (scale the timings to SOURCE DURATION SECONDS)
1. **Closed cover to natural opening** (first ~32% of the clip) — begin on the supplied closed
   cover, fully intact and nearly frame-filling. From the locked overhead view, the cover lifts and
   the book opens by its own believable hinge and page weight; camera stays overhead and follows
   smoothly. No hands, no cut, no jump, no sudden already-open spread.
2. **One right-hand page** (middle ~30%) — pages turn naturally, then settle on ONE visible
   right-hand page; never show a two-page spread. Its hand-drawn illustration relates to
   **{{TOPIC}}** and its paper/material texture belongs to that topic. The drawing stays still.
   The lower 8–10% of this page is an intentionally clean, texture-only subtitle reserve: no
   words, symbols, figures, objects, marks, or decorative detail anywhere in that strip.
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
No recurring host, no selected host, no foreground person/character, no people, no hands opening the book, no moving creatures, no
animated drawings inside the page, no different book design, no new symbols, no 3D book,
no realistic paper, no CGI magic, no fantasy portal effects, no chaotic transitions,
no readable text (decorative marks must stay abstract, never real words), no style drift,
no identity drift.

## Continuity requirements
- Preserve the closed-cover geometry exactly at the start.
- Show only the right-hand target page before entering it; never show a two-page spread.
- The final frame must match the supplied world keyframe exactly so the cut to the first image
  beat is imperceptible: same top-down-to-world push-in direction, palette, edge/frame grammar
  and subtitle reserve; no flash, dissolve, jump, or unrelated intermediate composition.
- End exactly inside the world of the supplied last frame, at the moment before the next
  beat begins.

## Length
Keep the prompt tight and directive — roughly 120–220 words, one flowing block of
instructions. No lists, no numbered shots in the output, no meta commentary.

Return ONLY the prompt text.
