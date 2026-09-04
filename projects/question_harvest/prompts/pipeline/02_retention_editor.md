# Prompt 02 — Retention Editor (Question Harvest)

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
  "book_transition": "...",
  "body": ["...", "..."],
  "optional_closing": "...",
  "cta": "...",
  "full_narration": "..."
}
```

`full_narration` MUST be the exact space-joined concatenation of
`opening_question_spark`, `book_transition`, every `body` entry in order,
`optional_closing`, then `cta`. The alignment step verifies this and rejects the
script if it does not hold, so an edit that changes a segment must also update
`full_narration`.

## Must preserve
- the same ordinary opening activity and curiosity trigger
- the book retrieval and the ~3s `book_transition` beat
- factual integrity: do not strengthen uncertain claims, never add statistics
- a hook that works from second zero
- between {{BEAT_MIN}} and {{BEAT_MAX}} `body` entries, each independently visualisable

## May sharpen
- hook compression and curiosity payoff
- word count tightened to {{WORD_RANGE}} for a {{DURATION_RANGE}} Short
- TTS rhythm and visual translatability
- removing generic openers such as "Have you ever wondered"
- making the book-transition sentence a more natural hinge

## Checks before answering
1. Is the hook still topic-specific rather than generic?
2. Does the body pay off the hook?
3. Is the CTA a single sentence of at most 12 words inviting like + subscribe?
4. Are there no invented numbers?
5. Does `full_narration` still concatenate the segments exactly?
6. Is the output raw JSON with no fences?
