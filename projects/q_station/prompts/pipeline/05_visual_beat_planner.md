# Prompt 05 — Visual Beat Planner (Q Station)

## Purpose
Plan BODY visual beats. First ~8 seconds are Flow video (Clip A ~5s + Clip B ~3s) and are NOT counted as still-image beats. The script has already split BODY into short spoken visual units: produce exactly one unique still-image beat for every unit.

## Inputs
- FINAL SCRIPT (segmented): {{FINAL_SCRIPT}}
- EPISODE PLAN (JSON): {{EPISODE_PLAN}}
- WORLD STYLE PLAN (JSON): {{WORLD_STYLE_PLAN}}
- BRIEF: {{VIDEO_BRIEF}}
- BODY DURATION ESTIMATE: {{BODY_DURATION_SECONDS}} seconds
- RESOLVED CHARACTER (behavior and identity label only): {{CHARACTER_CONTEXT}}

## Output — JSON ONLY
Return RAW JSON:
```json
{
  "body_duration_seconds": 42.0,
  "beats": [
    {
      "beat_id": 1,
      "narration_slice": "exact substring of body narration this beat covers",
      "visual": "one clear visual idea for this beat in this world's medium",
      "purpose": "literally what this beat explains (e.g., 'show uneven seedling emergence')",
      "visual_fingerprint": "distinct subject + action + setting + composition; never reuse this in another beat",
      "type": "literal|diagram|metaphor|subject_world",
      "continuity": "how this beat connects to previous (e.g., 'same field, wider angle')",
      "hero_present": true|false,
      "world_keyframe_is_first": false,
      "transition_in": "fade|dissolve|wipeleft|wiperight|slideleft|slideright|radial|circleopen|smoothleft|smoothright"
    }
  ]
}
```

## Rules
- Return exactly as many beats as there are BODY entries, in the same order. One narration_slice must equal exactly one BODY visual unit; never combine units or split one unit across beats.
- Every beat needs a freshly generated, unique standalone image. `world_keyframe_is_first` is always false: the world keyframe is an anchor, never a substitute body image.
- One standalone image per beat, 9:16 vertical, simple composition. Make the visual idea distinct from its neighbours even when the setting remains continuous.
- Each `visual_fingerprint` must be unique across the plan. Change at least two of subject/action,
  shot scale, camera angle, setting zone, time/lighting, symbolic object, or composition from
  each neighboring image. Do not solve continuity by reusing or lightly reframing the prior shot.
- `transition_in` is the transition from the preceding body image. Choose a restrained transition appropriate to the meaning: dissolve/fade for reflection or explanation; directional wipes/slides for travel, sequence, cause-and-effect; radial/circleopen for reveals or discoveries; smooth directions for gentle continuity. Avoid flashy or arbitrary effects. The first body's value is ignored.
- Continuity is short-range support only; canonical character/style anchors beat drift (§56).
- No unwanted readable text in images; no UI/grid/panels.
- Set `hero_present` per beat only when host participation improves the explanation. Do not carry the opening environment into the subject world. Host identity is not an art-style directive.

Narration slices must concatenate to exactly the body narration (no missing or overlapping text).

Return ONLY JSON.
