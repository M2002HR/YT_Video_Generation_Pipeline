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
- Ajil Unified AI Gateway is included under `services/ajil_uag` as a git submodule and is the default STT backend for narration timing.
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

## Scaling and future ordak automation

For long videos with 100–300+ beats:

- prompt generation should be automated in batches, typically 10–20 beats per text job
- generated prompt batches should be parsed into individual beat prompt files
- image generation should remain sequential within each video because Beat N uses Beat N-1 as a continuity reference
- long image runs should be split across multiple browser conversations rather than relying on one giant conversation
- pipeline state must be explicit and resumable so a failed beat does not restart the whole video
- ordak should remain the browser execution layer while this repository owns sequencing, project state, reference selection, retry policy, and output naming

Detailed implementation plan:

`docs/ORDAK_BEAT_AUTOMATION.md`

## Target pipeline

Topic
→ Script
→ Retention edit
→ Visual beats
→ Per-beat image prompts
→ One image per beat
→ ElevenLabs narration
→ Ajil/Groq word timestamps
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

Current next stage:
- alignment is complete and committed
- timeline metadata is built and committed
- first 1920x1080 preview has been rendered and watched
- base preview is accepted to continue
- rebuild timeline once with subtitle-overlap repair
- render `assets/renders/final.mp4`
- run `scripts/qc_render.py --decode`
- commit `render/QC_REPORT.json`
- close Video 001 as the first clean end-to-end MVP before adding optional music/SFX

One STT timestamp overlap exists at the Beat 06 -> 07 boundary (0.320s). The timeline builder resolves it deterministically with a midpoint boundary while preserving raw speech timestamps.

Ajil integration: `docs/AJIL_UAG_INTEGRATION.md`
Voiceover workflow: `videos/001_brain_replays_embarrassing_moments/voiceover/WORKFLOW.md`
Render workflow: `videos/001_brain_replays_embarrassing_moments/render/README.md`


## Root configuration policy

The repository root `.env` is the only authoritative runtime env file.

- `.env.example` documents pipeline and Ajil settings.
- `scripts/run_ajil.py` forces `UAG_ENV_FILE` to the root env.
- Ajil's nested Groq/Gemini/Pollinations modules are imported as libraries and receive settings from Ajil; no nested runtime `.env` files should be maintained.
- Local faster-whisper remains an optional CPU fallback, not the default alignment backend.


## Timeline/render architecture

The render source is built in two explicit stages:

```text
timing/BEAT_TIMINGS.json
+ render/RENDER_PROFILE.json
+ local beat images/audio
        ↓
scripts/build_timeline.py
        ↓
timeline/TIMELINE.json
timeline/SUBTITLES.ass
        ↓
scripts/render_video.py
        ↓
assets/renders/preview.mp4
```

The first preview uses deterministic subtle Ken Burns motion, hard semantic cuts, narration audio, and phrase subtitles. Background music/SFX are intentionally deferred until the base timeline passes human QC.


## Final render QC

`scripts/qc_render.py` validates the rendered file against the committed timeline/render profile.

Checks include stream count, resolution, fps, duration drift, codecs, pixel format, non-empty output, and optional full decode.

The report is written to:

`videos/<video_id>/render/QC_REPORT.json`

Rendered MP4 files remain local/Git-ignored.

For Video 001, background music/SFX are deferred until after the clean deterministic MVP final passes QC. This prevents audio-polish work from obscuring base-pipeline defects.


## Motion quality rule

Avoid lateral FFmpeg pan effects on illustrated beat images. The first preview showed visible stepping/jitter.

Current default motion policy:
- centered smooth zoom in/out only
- occasional static holds
- lower motion strength
- supersampled zoom rendering before final downscale
- no animated left/right/up/down panning

The render profile controls the deterministic motion cycle.


## Video 001 motion preview acceptance

The revised smooth center-motion preview has been reviewed and accepted.

Accepted motion policy:
- no lateral/vertical pan animation
- centered zoom only
- occasional still frames
- reduced motion strength
- supersampled zoom rendering for smoother output

Video 001 is ready for final render and automated QC.
