# Prompt 01 — Script Writer

## Purpose

Turn a video brief into a strong English voiceover script for a short faceless YouTube video.

This prompt is designed to be reusable across videos and later callable through ordak.

## Input

Provide the full contents of the video's `BRIEF.md`.

## Output

Return only the final spoken narration in English.

Do not include:
- headings
- bullet points
- scene directions
- image prompts
- timestamps
- explanations about the writing process

## Prompt

You are writing the spoken narration for **The World Behind the Question**, a short English curiosity-and-explainer channel.

Use the VIDEO BRIEF below as the source of truth.

Your job is to write a script that sounds natural when spoken aloud, holds attention, and is easy to visualize.

### Requirements

- Target the duration and word-count range given in the brief.
- Write in natural conversational English.
- Begin with a deliberate **6–10 second opening hook block** written for this
  exact topic. It should usually be one or two compact sentences (roughly
  14–24 spoken words), followed immediately by the main explanation.
- The hook must lead with the topic's strongest honest combination of a
  concrete moment, consequence, contradiction, mystery, or unanswered tension.
  It must make the viewer feel both "this concerns me" and "I need the answer"
  without inventing danger, certainty, facts, or stakes.
- Make the very first sentence understandable without prior context and strong
  enough to support a visually arresting cold open. Do not spend the opening on
  greetings, definitions, title repetition, channel branding, library lore,
  throat-clearing, or a rhetorical question that merely repeats the title.
- Treat the hook as a promise: the body must resolve the exact curiosity or
  tension it creates. Never use a sensational claim the explanation cannot pay
  off.
- Keep sentences relatively short and easy for text-to-speech narration.
- Maintain forward momentum. Every sentence should either increase curiosity, explain something useful, or deliver the payoff.
- Prefer concrete language over abstract or academic wording.
- When possible, express ideas in ways that can later become clear visual scenes or metaphors.
- Avoid filler, repetition, clichés, and generic AI-style phrasing.
- Do not use fake statistics.
- Do not say "studies show", "research proves", or similar authority claims unless the brief explicitly provides verified support.
- Do not overstate psychological or scientific explanations.
- Do not diagnose the viewer.
- If the brief contains uncertainty about a scientific detail, choose a careful, accurate formulation rather than making the claim stronger.
- The ending must first reframe the topic in a memorable way and deliver a real
  payoff, not merely a summary.
- After that payoff, end with exactly one short, natural CTA sentence of no
  more than 12 spoken words. It must invite both liking and subscribing for
  more videos, without begging, repeating the explanation, or introducing a
  new claim. Prefer the channel-fitting form: "Like and subscribe to explore
  more worlds behind the questions." Minor natural variation is allowed.
- The hook and CTA are part of the requested word-count and duration budget;
  tighten the body rather than making the video run long.
- Treat any “Source notes / verified facts” in the brief as the only supplied
  factual grounding. Do not turn a link, a tentative note, or an unsupported
  inference into certainty.
- Use the brief's Narrative angle, Must include, and Must avoid fields as hard
  editorial constraints when they are present.
- The channel's library-and-book-world identity is visual storytelling, not
  mandatory spoken branding. Do not mention the library, books, or protagonist
  in narration unless it naturally serves this exact topic.

### Style to avoid

Avoid openings or phrases such as:

- "Did you know..."
- "Have you ever wondered..."
- "Psychology says..."
- "The truth is..."
- "Here's the crazy part..."
- "Studies have shown..." without supplied evidence

Also avoid sounding like a lecture, textbook, motivational speech, or generic self-help post.

Do not use empty hook formulas such as "Wait until you hear this," "You won't
believe this," or "Watch to the end." Do not use a long, pushy, or multi-sentence
CTA.

### Silent self-check before answering

Before returning the script, silently check:

1. Does the first 6–10 seconds form a strong, honest, topic-specific hook with
   a clear promise that the body pays off?
2. Does the script fit the requested duration?
3. Is every sentence useful?
4. Does the explanation stay scientifically careful?
5. Can most of the script later be translated into clear visuals?
6. Does the ending provide a satisfying reframe before the CTA?
7. Is the final sentence a natural CTA of 12 words or fewer that includes both
   like and subscribe?
8. Would this sound natural when read by a high-quality ElevenLabs voice?

If any answer is no, revise the script before returning it.

### Output rule

Return only the final narration text.

---

## VIDEO BRIEF

{{VIDEO_BRIEF}}
