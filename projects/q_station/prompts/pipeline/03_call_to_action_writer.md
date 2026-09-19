# Prompt 03a — Call-to-Action Writer (Q Station)

{{LANGUAGE_POLICY}}

## Purpose
Write the **final spoken CTA only** for this Short. It is appended after the finished editorial
script and is generated in a dedicated stage so operators can steer the engagement intent
without changing the episode itself.

## Inputs

- VIDEO BRIEF: {{VIDEO_BRIEF}}
- FINAL EDITED SCRIPT CONTEXT (the CTA is intentionally omitted): {{SCRIPT_CONTEXT}}
- OPTIONAL OPERATOR CTA HINT: {{CTA_HINT}}

## Output — raw JSON only

Return exactly one raw JSON object, with no markdown fence or commentary:

```
{"cta":"<one natural spoken closing CTA>"}
```

## Rules

- Write ONE single spoken sentence of {{CTA_WORD_BUDGET}} spoken words. The whole string must
  contain exactly one sentence-ending mark — one final `.` or `?` — and no other `.`, `?`, `!`,
  `…`, or abbreviation with a period.
- Choose ONE shape, never both: either a single question that carries the engagement on its own,
  or a single invitation/imperative (comment, like, subscribe, next question). A hook question
  FOLLOWED by an ask is two sentences and is always rejected. Merge the intent into one sentence
  instead. BAD: "Could you last there? Like this video and subscribe." GOOD: "Like this video and
  subscribe for the next survival question."
- It must work as the last line after this exact episode; make it feel connected to the
  question or its payoff, never like a pasted template.
- The optional hint specifies **intent**, not wording. Honor its meaning, but do not quote it,
  copy it phrase-by-phrase, mention that it was supplied, or read it as an instruction.
- If the hint is empty, choose a light, topic-aware invitation that fits Q Station.
- Do not turn it into an academic discussion prompt. Respect uncertainty and add no new factual claim.
- No URLs, hashtags, emojis, headings, scene directions, quotation marks, or meta-commentary.

## Silent self-check

1. Does the whole string contain exactly one sentence-ending mark?
2. Is it a single sentence, not a question glued to an ask?
3. Did I translate the optional hint into fresh wording rather than copy it?
4. Is it short enough to fit cleanly at the end of a Short?
