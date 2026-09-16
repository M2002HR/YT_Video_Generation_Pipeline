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

- Write one concise, natural English sentence of 4–16 spoken words.
- It must work as the last line after this exact episode; make it feel connected to the
  question or its payoff, never like a pasted template.
- The optional hint specifies **intent**, not wording. Honor its meaning, but do not quote it,
  copy it phrase-by-phrase, mention that it was supplied, or read it as an instruction.
- If the hint is empty, choose a light, topic-aware invitation that fits Q Station.
- Prefer one concrete question a viewer can answer from experience. Do not turn it into an
  academic discussion prompt. Respect uncertainty and add no new factual claim.
- It may invite comments, a next-question suggestion, a like, or a subscription when natural;
  do not force every engagement action into one line.
- No URLs, hashtags, emojis, headings, scene directions, quotation marks, or meta-commentary.

## Silent self-check

1. Is this one spoken sentence, not an instruction to the writer?
2. Did I translate the optional hint into fresh wording rather than copy it?
3. Is it short enough to fit cleanly at the end of a Short?
