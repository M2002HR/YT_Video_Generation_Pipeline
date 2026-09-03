# Prompt 03 — Episode Director (Question Harvest)

## Purpose
Choose concrete episode direction to avoid repetition and ground visuals.

## Inputs
- TOPIC: {{TOPIC}}
- CREATIVE BRIEF: {{CREATIVE_BRIEF}}
- FINAL SCRIPT: {{FINAL_SCRIPT}}
- RECENT HISTORY (JSON, may be empty): {{RECENT_HISTORY}}
- BRAND RULES: hand-drawn cartoon protagonist (tall/slim, chestnut hair, beard/goatee, moss sweater, blue overalls, orange boots). Home-world: farm/garden/workshop/orchard/greenhouse/home.

## Output — Structured JSON ONLY
Return RAW JSON (no markdown fence, no commentary) matching this schema:

```json
{
  "opening_activity": "gardening|digging|planting|watering|workshop repair|sorting tools|handling rope|feeding chickens|barn work|carrying harvest|orchard work|greenhouse work|well|market preparation|rainy-day work|winter work|home maintenance",
  "opening_location": "garden|workshop|barn|orchard|greenhouse|home interior|farmyard|field",
  "curiosity_trigger": "short phrase describing sensory observation that sparks question (e.g., 'noticing seedlings sprouting in uneven rows')",
  "trigger_object": "small object that catches eye (e.g., 'sprout', 'rusted hinge')",
  "reaction": "brief protagonist reaction (e.g., 'pauses, brushes soil, looks closer')",
  "book_retrieval": "how he reaches book (e.g., 'wipes hands, steps to shelf, pulls down worn green book')",
  "camera_pattern": "static_wide|slow_push_in|gentle_pan_left|pan_right|over_shoulder",
  "book_template_id": "001|002|003",
  "hero_presence_mode": "auto|opener_only|limited_in_world|in_world",
  "closing_mode": "return_to_home|stay_in_world|book_closing_echo",
  "world_style_hint": "one-line hint to world style director (e.g., 'charcoal with warm paper texture')",
  "reason": "1-sentence why this activity fits topic without forcing object into farm"
}
```

## Rules
- Topic relevance > novelty. Do not force bizarre object into farm to match topic.
- Anti-repetition: avoid identical opening_activity within last 4 videos, same location consecutive, same camera consecutively, same book template consecutively (use history if given; if history empty, choose freely but justify).
- Hook must connect physical activity to question.
- Keep book_template_id varied but recognizable.
- hero_presence_mode: historical subjects often opener_only/limited_in_world; conceptual (psychology/philosophy) may benefit in_world; but choose per narrative role.

Return ONLY JSON.

