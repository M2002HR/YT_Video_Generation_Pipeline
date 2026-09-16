# Prompt 03 — Episode Director (Q Station)

Stage the selected topic-first mini-story after narration is retained. Do not select a replacement routine.

Inputs:
- TOPIC: {{TOPIC}}
- CREATIVE BRIEF: {{CREATIVE_BRIEF}}
- FINAL SCRIPT: {{FINAL_SCRIPT}}
- RESOLVED CHARACTER CONTEXT: {{CHARACTER_CONTEXT}}
- PRESENTATION CONTEXT: {{PRESENTATION_CONTEXT}}
- PRESENTATION RULES: {{PRESENTATION_RULES}}
- RECENT HISTORY: {{RECENT_HISTORY}}
- SELECTED OPENING CONCEPT: {{OPENING_CONCEPT}}

Return raw JSON only:
```json
{
  "concept_id": "copy the selected concept_id, or empty for a legacy caller",
  "opening_actions": ["one to three concise physical actions, in order"],
  "entry_bridge": {"a_end": "last state of A", "b_start": "compatible profile-specific first frame of B", "reveal": "informational discovery during entry", "world_entry": "host-free first factual discovery"},
  "opening_activity": "free semantic description",
  "opening_location": "free semantic description",
  "opening_environment": "concise episode-specific setting description",
  "topic_visual_link": "one sentence explaining the direct, metaphorical, ironic, causal, or historical connection between the visible opening situation and this specific topic",
  "link_type": "direct|metaphor|irony|cause_effect|historical_echo",
  "opening_visual_proof": "the specific, non-textual object, mismatch, event, or spatial relationship visibly present in the first one to two seconds that proves the topic link",
  "curiosity_trigger": "sensory observation that sparks the question",
  "trigger_object": "specific object or event",
  "reaction": "brief behavior-consistent host reaction",
  "entry_retrieval": "natural physical progression from the question to the configured entry mechanism",
  "entry_variant": "one allowed variation named by PRESENTATION RULES",
  "camera_pattern": "static_wide|slow_push_in|gentle_pan_left|pan_right|over_shoulder",
  "hero_presence_mode": "auto|opener_only|limited_in_world|in_world",
  "closing_mode": "return_to_opening|stay_in_world|entry_echo",
  "world_style_hint": "one-line subject-world hint independent of host identity",
  "reason": "one sentence explaining the natural topic fit"
}
```

Rules:
- Infer WHERE and WHAT from topic + final script + character tone. Environments are episode-specific, never character-owned.
- Every opening must make a topic-specific visual connection that the viewer can see immediately, not merely read about in `reason`. It may be direct, metaphorical, ironic, causal, or a historical echo; choose the most natural form for the topic.
- `opening_visual_proof` is mandatory: it must be physically visible in the first 1–2 seconds, work without captions, readable text, logos, or prior knowledge, and be part of what the host is already doing or noticing at frame zero. It must naturally cause `curiosity_trigger` and the host's reaction.
- Do not solve this by dropping a literal topic prop into an unrelated routine. The topic link must arise from the activity, object relationship, disruption, consequence, or setting itself. Prefer a grounded, readable visual metaphor when a literal link would feel forced.
- `topic_visual_link`, `link_type`, and `opening_visual_proof` must agree with one another and with the opening narration. `reason` must explain why this particular connection fits the topic and remains natural for the selected host.
- `dynamic_with_soft_affinity` affinities are suggestions only. Never force an unrelated topic into a farm metaphor.
- `dynamic` means no inherited home or environment. Never infer fire, an infernal setting, a lair, underground space or fantasy realm from appearance.
- The character influences readable acting and opening action, not the factual script or topic-world style.
- Follow PRESENTATION RULES exactly. They own the fixed entry mechanism and allowed variations.
- Use the selected concept's discrepancy, action, payoff and entry variant. Refine staging, not
  the premise. One location and at most three physically readable actions; no mandatory busy hands.
- Keep A/B an explicit editorial seam, not an unsupported promise of pixel-perfect continuity.
  The configured B first-frame contract wins: no hand/host on a book frame, ownership cue on an orb.
- Avoid repeating a recent dramatic mechanism, not just its words. Camera variety is a soft
  preference and must never force a worse topic-specific opening. The recurring entry is allowed.
- A weak routine cannot be rescued by a persuasive `reason`. Staging must show the link itself.
- All beat timings here are planning targets; real narration timestamps remain authoritative.

Return ONLY JSON.
