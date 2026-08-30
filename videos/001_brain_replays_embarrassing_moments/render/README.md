# Render Workflow — Video 001

## Status entering this stage

The accepted inputs are:

- 18 local beat images in `assets/raw_beats/`
- one local narration in `assets/audio/narration.mp3`
- committed alignment metadata in `timing/BEAT_TIMINGS.json`

The alignment is high quality:

- backend: Ajil UAG
- provider: Groq
- model: `whisper-large-v3-turbo`
- timestamp source: word
- all 18 beat matches: 100%

## Important timing QC

The STT output contains one small timestamp overlap:

- Beat 06 speech end: 21.400
- Beat 07 speech start: 21.080
- overlap: 0.320s

This is possible with model word timestamps.

The timeline builder does not blindly copy that overlap. It chooses the midpoint:

```text
21.240s
```

So Beat 06 and Beat 07 receive one clean, continuous visual boundary.

The raw speech timestamps remain unchanged for auditability.

## 1. Build the timeline

From repository root:

```bash
python scripts/build_timeline.py \
  videos/001_brain_replays_embarrassing_moments
```

This validates that the narration and all beat images exist locally and creates:

```text
videos/001_brain_replays_embarrassing_moments/timeline/
  TIMELINE.json
  SUBTITLES.ass
```

These are metadata/text assets and should be committed.

`TIMELINE.json` contains:

- exact visual start/end/duration
- image path per beat
- speech start/end
- narration
- motion preset
- subtitle cues
- QC information
- any repaired timestamp-overlap boundaries

## 2. Dry-run the render

Before spending CPU time:

```bash
python scripts/render_video.py \
  videos/001_brain_replays_embarrassing_moments \
  --dry-run
```

This validates:

- FFmpeg
- ffprobe
- all 18 images
- narration
- timeline
- subtitle file
- libass/ASS subtitle support

and prints the generated FFmpeg command.

## 3. Render the first preview

```bash
python scripts/render_video.py \
  videos/001_brain_replays_embarrassing_moments
```

Default output:

```text
assets/renders/preview.mp4
```

The render is Git-ignored.

## Current render profile

`RENDER_PROFILE.json` currently uses:

- 1920x1080
- 30 fps
- H.264 / libx264
- CRF 18
- AAC 192 kbps
- subtle Ken Burns motion
- hard cuts between semantic beats
- burned phrase subtitles

Motion cycles deterministically through:

```text
zoom_in
pan_right
zoom_out
pan_left
```

This intentionally avoids random motion so the same project renders reproducibly.

## Subtitle strategy for MVP

The current alignment persists exact beat phrase timing, but not every individual STT word timestamp.

For the first render, subtitles are therefore:

- split into short readable phrases
- timed proportionally inside each beat's exact speech window
- rendered as ASS subtitles
- centered near the bottom
- maximum two lines

This is appropriate for the first full-video QC.

A future caption upgrade can persist raw word timestamps from Ajil and support word-by-word highlighting without changing the image timeline.

## FFmpeg subtitle fallback

If the installed FFmpeg does not include the `ass` filter, the renderer will stop with an actionable error.

For a temporary render without subtitles:

```bash
python scripts/render_video.py \
  videos/001_brain_replays_embarrassing_moments \
  --no-subtitles
```

Do not treat a no-subtitle render as the final publishing output unless that is an intentional style choice.

## What to review in preview.mp4

For the first human QC, focus on:

1. image order and continuity
2. whether cuts happen at the right semantic moments
3. whether any beat feels too long or too short
4. whether motion is too strong or too static
5. subtitle timing/readability
6. narration/image synchronization
7. visual continuity around Beat 06 -> Beat 07
8. final 2–3 seconds and ending cadence

Do not add background music/SFX before this base edit passes QC. Otherwise audio decoration can hide timeline problems.

## After base-render QC

Once the image+narration+subtitle edit is accepted, the next stage is:

```text
base timeline
-> targeted timing/motion corrections
-> background music / SFX
-> loudness mix
-> final render
-> human QC
```
