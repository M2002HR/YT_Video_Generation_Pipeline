# Prompt 01 — Question Harvest Script Writer

## Purpose
Turn a video brief into a spoken narration for **Question Harvest** short (40–60s, 9:16, vertical). This is the ONLY narration source.

## Input
VIDEO BRIEF below contains topic, audience, target duration (40–60s => ~92–150 spoken words, aim near 115), aspect 9:16, hero presence mode, and optional Must Include/Avoid.

## Output
Return ONLY the final English narration text (plain paragraphs, no headings, no timestamps, no scene directions, no markdown). The script will be segmented downstream.

## Brand Grammar (§33-36, §51)
Every episode follows: ordinary activity → curiosity trigger → question/hook → protagonist reaches for relevant book → book opens → two-page spread (one page pseudo-writing, one page world image) → camera pushes into world image → body inside the book world → optional return/closing.

## Requirements — Hook & Structure
- Hook from SECOND ZERO. First sentence must be understandable without context and promise an answer. Avoid generic “Have you ever wondered…” as repeated opener.
- Choose one **ordinary home-world activity** appropriate to topic and visual storytelling:
  gardening/digging/planting/watering, workshop repair/sorting tools/rope, feeding chickens/barn, harvest/orchard/greenhouse/well, home maintenance/market prep/rainy-day/winter work. Activity must feel natural, not forced topic-object in farm.
- Connect hook to physical opener activity (you are doing something when curiosity hits).
- Make book retrieval natural (goes/reaches for relevant book). Book transition phase is ~3s narration.
- Final narration is one continuous text, but internally it must contain:
  * opening_question_spark: ~5s
  * book_transition: ~3s
  * body: remaining (the diverse world)
  * optional_closing: 1 sentence echo if useful
- Avoid fabricated sources/statistics. Use only facts in brief's Source notes; otherwise stay accurate and general.

## Style
- Short sentences for TTS, conversational, forward momentum.
- Avoid filler, clichés, lecture tone.
- Ending must reframe + deliver payoff, then exactly ONE short CTA ≤12 words inviting like+subscribe (e.g., “Like and subscribe to grow more questions.”)
- Do not mention library/books in narration unless naturally serves topic (visual carries framing).

## Silent self-check
1. Hook strong, honest, topic-specific with payoff?
2. Opening activity chosen and consistent?
3. Word count fits 92–150?
4. No invented stats?
5. Sounds natural for ElevenLabs?

## Output rule
Return only narration.

---
## VIDEO BRIEF
{{VIDEO_BRIEF}}
