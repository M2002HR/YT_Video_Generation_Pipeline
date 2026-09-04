# Prompt 01 — Question Harvest Script Writer

## Purpose
Turn a video brief into the spoken narration for a **Question Harvest** short (40–60s, 9:16,
vertical). This is the ONLY narration source for the episode.

## Why the output is JSON
The pipeline aligns the finished audio against real word timestamps and trims the two Flow
opening clips to the *measured* end of each narration segment. It therefore needs to know
exactly which words belong to which segment. Segment boundaries chosen here are authoritative;
nothing downstream re-guesses them by counting words.

## Input
VIDEO BRIEF below contains topic, audience, target duration (40–60s => ~92–150 spoken words,
aim near 115), aspect 9:16, hero presence mode, and optional Must Include/Avoid.

## Output — raw JSON only
Return ONLY a raw JSON object, no markdown fences, no commentary:

```
{
  "opening_question_spark": "<~5s of narration: the hook, spoken while the hero is mid-activity>",
  "book_transition": "<~3s of narration: the hero reaches for the book and it opens>",
  "body": ["<one sentence or clause per visual beat>", "..."],
  "optional_closing": "<one short echo sentence, or empty string>",
  "cta": "<one CTA of at most 12 words>",
  "full_narration": "<every field above concatenated in order, exactly as it will be spoken>"
}
```

Hard rules for the JSON:
- `full_narration` MUST be the exact concatenation of `opening_question_spark`,
  `book_transition`, each `body` entry in order, `optional_closing`, then `cta`, joined by a
  single space. No extra words, no repeated words, no re-ordering. The alignment step verifies
  this and rejects the script if it does not hold.
- `body` must contain between 8 and 15 entries. One entry = one visual beat.
- No headings, no timestamps, no scene directions, no speaker labels, no emoji.
- Plain spoken English only — anything unspeakable (URLs, parentheses, asterisks) is a defect.

## Brand grammar (§33-36, §51)
Every episode follows: ordinary activity → curiosity trigger → question/hook → protagonist
reaches for the relevant book → book opens → two-page spread (one page pseudo-writing, one page
world image) → camera pushes into the world image → body inside the book world → optional
return/closing.

## Requirements — hook and structure
- Hook from SECOND ZERO. The first sentence must stand alone and promise an answer. Do not open
  with "Have you ever wondered".
- Choose one **ordinary home-world activity** that suits the topic and reads well on camera:
  gardening/digging/planting/watering, workshop repair/sorting tools/rope, feeding
  chickens/barn, harvest/orchard/greenhouse/well, home maintenance/market prep/rainy-day/winter
  work. The activity must feel natural, never a topic prop dropped into a farm.
- Tie the hook to that physical activity: curiosity arrives while the hands are busy.
- Make the book retrieval natural. `book_transition` is roughly 3 seconds of speech.
- `opening_question_spark` is roughly 5 seconds of speech.
- Every `body` entry should be independently visualisable — it becomes one image prompt.
- Use only facts present in the brief's Source notes. Never invent statistics or sources.

## Style
- Short sentences for TTS, conversational, forward momentum.
- No filler, no clichés, no lecture tone.
- The closing reframes and pays off; the CTA invites like + subscribe in ≤12 words
  (e.g. "Like and subscribe to grow more questions.").
- Do not mention libraries or books unless the topic genuinely calls for it — the visuals carry
  that framing.

## Silent self-check before answering
1. Is the hook strong, honest, topic-specific, and does it promise a payoff?
2. Is one opening activity chosen and kept consistent?
3. Is the total spoken word count between 92 and 150?
4. Are there no invented statistics?
5. Does `full_narration` concatenate the segments exactly, with nothing added or dropped?
6. Is the output raw JSON with no fences?

---
## VIDEO BRIEF
{{VIDEO_BRIEF}}
