# Prompt 05 — Visual Beat Planner (Question Harvest)

## Purpose
Plan BODY visual beats. First ~8 seconds are Flow video (Clip A ~5s + Clip B ~3s) and are NOT counted as still-image beats. Use BODY narration duration (total minus ~8s) to choose beat count.

## Inputs
- FINAL SCRIPT (segmented): {{FINAL_SCRIPT}}
- EPISODE PLAN (JSON): {{EPISODE_PLAN}}
- WORLD STYLE PLAN (JSON): {{WORLD_STYLE_PLAN}}
- BRIEF: {{VIDEO_BRIEF}}
- BODY DURATION ESTIMATE: {{BODY_DURATION_SECONDS}} seconds

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
      "type": "literal|diagram|metaphor|subject_world",
      "continuity": "how this beat connects to previous (e.g., 'same field, wider angle')",
      "hero_present": true|false,
      "world_keyframe_is_first": true|false
    }
  ]
}
```

## Rules
- world_keyframe.png may serve as first body image — mark one beat with "world_keyframe_is_first": true if so.
- For 40–60s Short, usually 8–15 body stills depending on narration density. Do not force one image every 3.5s if storytelling suffers.
- One standalone image per beat, 9:16 vertical, simple composition.
- Continuity is short-range support only; canonical character/style anchors beat drift (§56).
- No unwanted readable text in images; no UI/grid/panels.

Narration slices must concatenate to exactly the body narration (no missing or overlapping text).

Return ONLY JSON.

