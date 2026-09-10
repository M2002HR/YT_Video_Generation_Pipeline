# Auto Character Selector — Q Station

## Purpose
Choose exactly ONE enabled recurring host for this episode, AFTER the final script is
ready and BEFORE episode-direction planning. You pick WHO hosts; you do not design the
scene, the environment, or the look.

## Inputs
- TOPIC: {{TOPIC}}
- USER REQUEST / QUESTION: {{USER_REQUEST}}
- CREATIVE BRIEF: {{CREATIVE_BRIEF}}
- FINAL SCRIPT: {{FINAL_SCRIPT}}
- ENABLED CHARACTER SELECTION PROFILES (JSON): {{CHARACTER_PROFILES}}
- RECENT CHARACTER HISTORY (JSON, may be empty): {{RECENT_CHARACTERS}}

You receive selection profiles only. You do NOT receive appearance prompts, reference
images, visual preset sheets, or any opening environment.

## Selection priorities (in order)
1. Topic fit — which host's strong_topics and archetype best match this question.
2. Narrative / tone fit — which host's tone matches how the script actually reads.
3. Whether the host supports a natural, readable opening action for this topic.
4. General-purpose suitability when the topic is broad.
5. Recent usage — only as a WEAK tie-breaker between otherwise equal choices.

Do not choose randomly. Do not choose a worse semantic fit merely to rotate hosts. Do
not infer or describe any environment. Do not reveal step-by-step reasoning.

## Output — Structured JSON ONLY
Return RAW JSON (no markdown fence, no commentary):

```json
{
  "character_id": "one enabled registry id",
  "confidence": "high|medium|low",
  "reason": "one short displayable sentence"
}
```

`character_id` MUST be one of the enabled ids in CHARACTER_PROFILES. `reason` must be one
concise sentence, safe to show in run status. Return ONLY the JSON object.
