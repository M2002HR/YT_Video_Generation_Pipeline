# Prompt 03 — Episode Director (Q Station)

Choose a natural opening activity, location and staging after the host has been resolved.

Inputs:
- TOPIC: {{TOPIC}}
- CREATIVE BRIEF: {{CREATIVE_BRIEF}}
- FINAL SCRIPT: {{FINAL_SCRIPT}}
- RESOLVED CHARACTER CONTEXT: {{CHARACTER_CONTEXT}}
- RECENT HISTORY: {{RECENT_HISTORY}}

Return raw JSON only:
```json
{
  "opening_activity": "free semantic description",
  "opening_location": "free semantic description",
  "opening_environment": "concise episode-specific setting description",
  "curiosity_trigger": "sensory observation that sparks the question",
  "trigger_object": "specific object or event",
  "reaction": "brief behavior-consistent host reaction",
  "book_retrieval": "natural way the host reaches or reveals the book",
  "camera_pattern": "static_wide|slow_push_in|gentle_pan_left|pan_right|over_shoulder",
  "book_template_id": "001|002|003",
  "hero_presence_mode": "auto|opener_only|limited_in_world|in_world",
  "closing_mode": "return_to_opening|stay_in_world|book_closing_echo",
  "world_style_hint": "one-line subject-world hint independent of host identity",
  "reason": "one sentence explaining the natural topic fit"
}
```

Rules:
- Infer WHERE and WHAT from topic + final script + character tone. Environments are episode-specific, never character-owned.
- `dynamic_with_soft_affinity` affinities are suggestions only. Never force an unrelated topic into a farm metaphor.
- `dynamic` means no inherited home or environment. Never infer fire, an infernal setting, a lair, underground space or fantasy realm from appearance.
- The character influences readable acting and opening action, not the factual script or inside-book world style.
- Avoid repeating recent activity/location/camera/template traits. Fields remain free semantic text except the stated camera/template modes.

Return ONLY JSON.
