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

Completion state:
- alignment complete
- timeline/subtitle metadata committed
- clean baseline final rendered and QC-passed
- music-only polish reviewed
- final creative SFX treatment reduced to one opening cue
- `polished_sfx.mp4` passed full technical QC
- `render/QC_REPORT_polished_sfx.json` committed

Video 001 is COMPLETE as the first end-to-end pipeline proof.

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

Video 001 final render has passed automated QC and full decode.


## Video 001 baseline completion

Video 001 has completed the full base pipeline end to end.

Final QC:
- passed: true
- 1920x1080
- 30 fps
- duration: 63.373s with effectively zero drift
- H.264 / yuv420p
- AAC audio
- full decode: clean

The local baseline artifact is:

`assets/renders/final.mp4`

This file remains Git-ignored.

The committed proof of completion is:

`render/QC_REPORT.json`

The next stage is optional audio polish on top of this accepted baseline:
- background music
- sparse semantic SFX
- narration-first ducking
- loudness normalization
- separate polished output for A/B review

Do not overwrite the accepted baseline final during audio-polish experiments.


## Audio polish architecture

Audio polish is layered on top of the accepted baseline render and never overwrites it.

```text
assets/renders/final.mp4
+ assets/music/background.mp3
+ optional assets/sfx/*
        ↓
audio_mix/AUDIO_MIX_PROFILE.json
        ↓
scripts/polish_audio.py
        ↓
assets/renders/polished.mp4
```

The mixer stream-copies the accepted video and rebuilds only audio.

Current policy:
- narration stays dominant
- music starts conservatively around -20 dB
- sidechain ducking lowers music under speech
- SFX are sparse, semantic events
- loudness normalization is applied after mixing
- polished output is A/B compared against the accepted clean baseline

Music/SFX media remain local and Git-ignored; mix profiles and workflow metadata are committed.


## Video 001 music-only mix acceptance

The music-only polished mix has been rendered and reviewed successfully.

Accepted state:
- background music present
- narration remains clear and dominant
- current ducking/gain settings are acceptable
- no SFX yet

Next stage: add a very small number of semantic SFX events, compare against the accepted music-only polished mix, then run QC on the chosen polished output.


## Audio polish versioning rule

Accepted render variants must never be overwritten by later experiments.

For Video 001:

```text
final.mp4          = accepted clean baseline
polished.mp4       = accepted music-only mix
polished_sfx.mp4   = separate SFX experiment
```

The SFX experiment uses `audio_mix/AUDIO_MIX_PROFILE_SFX.json`, while the original `AUDIO_MIX_PROFILE.json` remains the music-only configuration.

This A/B/C structure is the default pattern for future creative experiments: preserve the last accepted artifact and write each materially different treatment to a new output.


## Video 001 SFX mix acceptance

The separate SFX experiment has been rendered and reviewed positively.

Creative state:
- `final.mp4` = accepted clean baseline
- `polished.mp4` = accepted music-only mix
- `polished_sfx.mp4` = accepted creative SFX mix, pending its own technical QC

Important: QC reports for variants must not overwrite the baseline `render/QC_REPORT.json`.
`scripts/qc_render.py` now writes variant-specific reports by default, e.g.:

`render/QC_REPORT_polished_sfx.json`


## Video 001 final SFX decision

The SFX treatment was simplified after review.

Keep only:
- 1.96s intrusive-thought pop (`assets/sfx/intrusive_pop.mp3`)
- gain -17 dB
- trim 0.7s

Remove the replay/rewind and archive/drawer SFX from the active mix.

Final creative direction: one subtle opening SFX cue, then narration + background music only.


## Ordak video-pipeline integration

Ordak is now a first-class service submodule at:

`services/ordak`

Repository:

`AliBalash/ordak`

Dedicated integration/stabilization branch:

`yt-video-pipeline`

The parent repository pins an exact Ordak commit and records the intended branch in `.gitmodules`.

Current provider scope is ChatGPT only. Gemini automation is intentionally out of scope for this milestone.

Runtime configuration remains root-owned:
- root `.env` is authoritative
- `YT_ORDAK_*` controls browser/profile/ChatGPT/timeouts
- `scripts/run_ordak.py` maps root settings into Ordak
- Ordak's pipeline branch accepts `ORDAK_ENV_FILE`
- `scripts/check_ordak.py` verifies API + Chrome + authenticated ChatGPT readiness

The selected real Chrome user-data directory and profile name are explicit root settings. The automation must not silently fall back to a fresh logged-out profile.

Baseline resilience configuration intentionally supports long ChatGPT image generations:
- browser timeout: 180s
- ChatGPT response timeout: 600s
- response stability: 5s
- stall refresh window: 90s
- max stall refreshes: 3
- parent job wait: 900s

Critical recovery semantics:
- active generation is not a stall
- refresh only after genuine no-progress
- after refresh, reconcile server-side completion before resubmitting
- only resubmit if the exchange is still incomplete/stuck
- recovery attempts are bounded and diagnostic evidence must be preserved

Integration details:

`docs/ORDAK_INTEGRATION.md`

Next milestone: write the Codex stabilization goal and let Codex implement/test the full ChatGPT text + sequential multi-reference image workflow on the real configured browser profile until automated and real-browser E2E acceptance criteria pass.
