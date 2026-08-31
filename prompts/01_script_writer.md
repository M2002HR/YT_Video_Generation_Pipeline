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

You are writing the spoken narration for a short English faceless YouTube video.

Use the VIDEO BRIEF below as the source of truth.

Your job is to write a script that sounds natural when spoken aloud, holds attention, and is easy to visualize.

### Requirements

- Target the duration and word-count range given in the brief.
- Write in natural conversational English.
- Open with a specific, relatable hook rather than a generic introduction.
- The opening 2–4 spoken seconds must present an immediate concrete moment,
  tension, or surprising recognition from this exact topic; do not spend those
  seconds on setup, definitions, channel branding, or a rhetorical preamble.
- Make the first sentence immediately create curiosity or recognition and make
  sure the remainder of the script genuinely pays that promise off.
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
- The ending should reframe the topic in a memorable way and feel like a payoff, not merely a summary.
- Do not add a call to action unless the brief explicitly requests one.

### Style to avoid

Avoid openings or phrases such as:

- "Did you know..."
- "Have you ever wondered..."
- "Psychology says..."
- "The truth is..."
- "Here's the crazy part..."
- "Studies have shown..." without supplied evidence

Also avoid sounding like a lecture, textbook, motivational speech, or generic self-help post.

### Silent self-check before answering

Before returning the script, silently check:

1. Does the first 2–4 seconds contain a strong, topic-specific hook?
2. Does the script fit the requested duration?
3. Is every sentence useful?
4. Does the explanation stay scientifically careful?
5. Can most of the script later be translated into clear visuals?
6. Does the ending provide a satisfying reframe?
7. Would this sound natural when read by a high-quality ElevenLabs voice?

If any answer is no, revise the script before returning it.

### Output rule

Return only the final narration text.

---

## VIDEO BRIEF

{{VIDEO_BRIEF}}
