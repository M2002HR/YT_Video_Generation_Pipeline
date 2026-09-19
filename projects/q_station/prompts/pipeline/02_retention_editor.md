# Prompt 02 — Retention Editor (Q Station)

{{LANGUAGE_POLICY}}

## Purpose
Sharpen the draft narration for retention without breaking visual logic or narration timing.

## Inputs
- VIDEO BRIEF: {{VIDEO_BRIEF}}
- CURRENT_SCRIPT (raw JSON from prompt 01): {{CURRENT_SCRIPT}}

## Output — raw JSON only, same schema as the input
Return ONLY a raw JSON object with exactly these keys, no markdown fences, no commentary:

```
{
  "opening_question_spark": "...",
  "{{ENTRY_SEGMENT_KEY}}": "...",
  "body": ["...", "..."],
  "optional_closing": "...",
  "cta": "...",
  "full_narration": "..."
}
```

`full_narration` MUST be the exact space-joined concatenation of
`opening_question_spark`, `{{ENTRY_SEGMENT_KEY}}`, every `body` entry in order,
`optional_closing`, then `cta`. The alignment step verifies this and rejects the
script if it does not hold, so an edit that changes a segment must also update
`full_narration`.

## Selected opening and character
CHARACTER STORY CONTEXT: {{CHARACTER_STORY_CONTEXT}}
SELECTED OPENING CONCEPT: {{OPENING_CONCEPT}}

## Must preserve
- the selected premise, its frame-zero evidence, and supported promise/payoff; do not preserve an unrelated chore merely because a draft invented it
- the active presentation progression and the ~3–4s `{{ENTRY_SEGMENT_KEY}}` beat
- factual integrity: do not strengthen uncertain claims, never add statistics
- a hook that works from second zero
- between {{BEAT_MIN}} and {{BEAT_MAX}} `body` entries, each an independently visualisable
  spoken unit of ≤16 words. Split every separately depictable action, object, reveal, cause, or
  consequence into its own unit, including natural clauses from a longer sentence. Each entry
  triggers one unique picture; never merge separate visual moments to make the narration sound
  more literary.
- a non-empty `optional_closing` is one additional, separate final image beat before CTA. It must
  be one sentence of at most 16 words; CTA may share that final image.

## May sharpen
- clearer hook wording and curiosity payoff; preserve the premise, not the candidate's exact words
- remove unnecessary jargon and abstract noun piles; explain necessary terms in context
- clarity before compression: never replace everyday wording with a formal synonym just to save words
- keep word count within {{WORD_RANGE}} for a {{DURATION_RANGE}} Short, and always leave at least
  4 words of headroom below the top of that range: the downstream CTA stage appends a 4–16 word
  closing line inside the same cap, so a core that fills the range leaves it no legal wording
- TTS rhythm and visual translatability
- removing generic openers such as "Have you ever wondered"
- making the {{ENTRY_SEGMENT_LABEL}} carry a concrete clue while visuals handle the entry mechanics; never merely announce that we enter the prop
- replacing vague summaries with supported, concrete named details (people, place, origin,
  mechanism, or consequence) when the brief's Source notes support them; if they are absent,
  retain only conservative, widely-established canonical details

## Checks before answering
1. Is the hook still topic-specific rather than generic?
2. Does the body pay off the hook?
3. Is the CTA a single concise provisional sentence? A dedicated downstream CTA stage will
   replace it with the final topic-aware spoken CTA.
4. Are there no invented numbers?
5. Does `full_narration` still concatenate the segments exactly?
6. Is the output raw JSON with no fences?

## Active presentation contract
{{PRESENTATION_RULES}}
