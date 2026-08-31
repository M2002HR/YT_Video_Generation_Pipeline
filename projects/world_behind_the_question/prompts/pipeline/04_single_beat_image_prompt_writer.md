# Prompt 04 — Single Beat Image Prompt Writer

## Purpose

Convert one approved visual beat into one high-quality standalone {{ASPECT_RATIO}} image-generation prompt.

The pipeline no longer uses 2x2 storyboard sheets. **One visual beat = one generated image.**

## Required reference strategy

For Beat 01:
1. STYLE ANCHOR
2. CHARACTER ANCHOR
3. optional video-specific anchors
4. current beat prompt

For Beat 02+:
1. STYLE ANCHOR
2. CHARACTER ANCHOR
3. optional video-specific anchors
4. PREVIOUS BEAT IMAGE
5. current beat prompt

Reference priority:
1. character anchor controls protagonist identity
2. style anchor controls rendering style
3. dedicated video-specific anchors control recurring locations/cast/props
4. previous beat image controls short-range continuity only
5. current prompt controls the new action and composition

Never use the previous image as the only character/style reference. If it has drifted, correct back toward the canonical anchors.

## Output rules

The generated prompt must explicitly require:
- exactly one image
- {{ASPECT_RATIO}} composition
- no storyboard sheet
- no grid
- no collage
- no split into comic panels
- no captions
- no narration text
- no subtitles
- no panel/scene numbers
- no logos/watermarks
- enough safe space for later zoom/pan
- one dominant visual idea

Short story-native text is allowed only when truly necessary and should remain rare.

## Prompt-writing principles

- Preserve the exact meaning of the approved visual beat.
- Preserve recurring character identity.
- Preserve recurring location/cast when relevant.
- Use the previous beat only to continue immediate visual state.
- Do not copy the previous beat mechanically; the new image must advance the visual story.
- Prefer visual clarity over complexity.
- Do not add unsupported scientific mechanisms.
- Avoid unnecessary text.
- Make metaphors readable inside a single coherent frame rather than through multiple panels.
- For this project, use the supplied anchors as non-negotiable canon: the
  hand-drawn educational-adventure language, Library of Living Questions mood,
  and the Seeker's face, hair, small brass glasses, teal/moss outer layer,
  satchel, and Page Key. If the beat does not need the Seeker, preserve the
  style anchor's material, line, color, and lighting language instead.
- When the Seeker enters a topic world, adapt only 15–30% of the outfit through
  fabric, trim, or one modest accessory. Never replace the core silhouette or
  turn him into a generic period/fantasy/space character.
- Do not depict the Seeker as a famous existing character, a wizard, a
  superhero, a child, or a photoreal person.
- Treat EPISODE WORLD DESIGN as binding continuity for the topic-specific book,
  portal, palette, materials, lighting, locations, props, and wardrobe
  adaptation. Translate only the current beat into an image; do not redesign
  the world from scratch for each beat.
- If the current beat belongs to the Opening Hook Block, make it immediately
  legible and high-impact as a still: one decisive subject, one clear
  action/tension, strong depth, and no passive setup pose. Preserve screen
  direction, geography, lighting logic, and action progression across the
  neighboring hook beats. Compose with enough clean temporal and spatial logic
  that the opening still sequence can later be replaced by one continuous
  6–10 second video clip, but still generate exactly one image now.
- For the final CTA beat, use a simple satisfying brand-world closing image
  after the topic payoff—prefer the returned question book, Page Key, or Library
  echo. Do not visualize literal like/subscribe buttons, platform UI, captions,
  logos, pointing gestures, or text; the spoken narration carries the CTA.

## Required output format

```text
Create exactly ONE standalone {{ASPECT_RATIO}} image for one visual beat.

REFERENCE PRIORITY:
<reference hierarchy>

GLOBAL STYLE:
<style behavior>

TEXT POLICY:
<text restrictions>

CURRENT BEAT:
<precise scene description>

CONTINUITY REQUIREMENT:
<how to use previous beat without drift>

OUTPUT REQUIREMENT:
Generate exactly one high-quality standalone {{ASPECT_RATIO}} image.

FRAME COMPOSITION:
{{FRAME_GUIDANCE}}
```

---

## STYLE RULES

{{STYLE_RULES}}

## EPISODE WORLD DESIGN

{{WORLD_DESIGN}}

## VISUAL BEAT

{{VISUAL_BEAT}}

## REFERENCE IMAGES

{{REFERENCE_IMAGES}}

## PREVIOUS BEAT

{{PREVIOUS_BEAT}}
