# Project Context

## Goal

Build an automation-first pipeline for producing English faceless YouTube videos from a topic to a finished video.

## Current MVP

Start with ~60-second English videos, learn the infrastructure and creative failure modes quickly, then extend to longer videos.

## Current approach

- English content only.
- No official LLM/image APIs for now.
- ordak is intended to automate real signed-in ChatGPT/Gemini browser sessions.
- ElevenLabs browser automation will be added for narration.
- Visual planning uses semantic visual beats rather than strict sentence boundaries.
- **One visual beat generates one full-resolution standalone 16:9 image.**
- The earlier 2x2 storyboard-sheet approach is deprecated because cropping lowered image quality.

## Visual consistency strategy

Every generated beat image uses:
1. canonical STYLE ANCHOR
2. canonical CHARACTER ANCHOR
3. optional video-specific recurring anchors
4. previous accepted beat image (Beat 02+)
5. current beat prompt

The previous image is only a continuity reference. Character/style anchors remain canonical to prevent cumulative drift.

## Visual presets

Reusable style+character combinations live in:

`visual_presets/<preset>/`

Each video selects one preset using `VISUAL_PRESET.md`.

## Target pipeline

Topic
→ Script
→ Retention edit
→ Visual beats
→ Per-beat image prompts
→ One image per beat
→ ElevenLabs narration
→ Timing/alignment
→ Timeline
→ Motion/subtitles/audio
→ Render
→ Human QC
→ Final video

## Asset policy

Commit:
- prompts
- visual presets and canonical anchors
- workflow/docs
- reusable video-specific anchors
- source code/config

Do not commit:
- generated beat images
- generated audio
- renders

Generated beat images are stored under each video's `assets/raw_beats/`.

## Video 001 status

Video 001 has:
- brief
- final narration
- 18 visual beats
- selected visual preset
- 18 per-beat image prompts
- reference-driven per-beat image workflow

Next major stage after image generation: ElevenLabs narration and beat timing/alignment.
