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


## Base preview accepted — finalization pass

The first preview has now been watched and accepted as good enough to continue.

Before final export, rebuild the timeline once because the timeline builder now also repairs overlapping subtitle cues. The Beat 06 -> 07 STT overlap previously produced a short subtitle overlap even though the image boundary was already repaired.

Run:

```bash
git pull

python scripts/build_timeline.py \
  videos/001_brain_replays_embarrassing_moments
```

Expected additional QC line:

```text
Subtitle overlap repairs: 1
```

Then export the MVP final:

```bash
python scripts/render_video.py \
  videos/001_brain_replays_embarrassing_moments \
  --output videos/001_brain_replays_embarrassing_moments/assets/renders/final.mp4
```

Finally run automated container/stream QC plus a full decode:

```bash
python scripts/qc_render.py \
  videos/001_brain_replays_embarrassing_moments \
  --input videos/001_brain_replays_embarrassing_moments/assets/renders/final.mp4 \
  --decode
```

The QC script checks:

- exactly one video stream
- exactly one audio stream
- expected 1920x1080 resolution
- expected 30 fps
- duration drift within tolerance
- H.264 video codec
- yuv420p pixel format
- AAC audio codec
- non-empty output
- optional full FFmpeg decode with no stream errors

It writes:

```text
render/QC_REPORT.json
```

Commit the rebuilt timeline/subtitle files and the QC report. Do not commit `final.mp4`.

## MVP audio-polish decision

For Video 001, background music and SFX are intentionally deferred until after this clean final export passes automated QC.

Reason: this is the first end-to-end infrastructure validation. Closing one complete deterministic video first gives us a stable baseline before adding a music/SFX asset-selection and mixing subsystem.

After the final export passes QC, the next iteration can add optional:

- background music
- semantic SFX events
- narration/music ducking
- loudness normalization
- final mix targets

without changing the existing script/beat/image/timing architecture.


## Motion policy update — no jittery lateral pans

The first preview showed that the lateral pan effects were visually distracting and introduced a small "shaky" / stepping feel on illustrated stills.

They are now removed from the render profile.

The motion cycle is now:

```text
zoom_in
still
zoom_out
slow_zoom_in
```

Key changes:

- no `pan_left`
- no `pan_right`
- no animated horizontal/vertical crop movement
- lower motion strength: `0.035`
- center-only zoom
- 2x supersampled motion followed by Lanczos downscale
- periodic static holds to avoid constant movement

The supersampled render is intentionally a little more CPU-heavy, but it reduces FFmpeg zoom/crop rounding shimmer and should look materially smoother.

After pulling, rebuild the timeline so the new motion cycle is written into `TIMELINE.json`, then render the preview/final again.


## Revised motion preview accepted

The no-pan, center-zoom motion pass has been reviewed and accepted.

Proceed to the final render and automated QC using the current committed timeline/profile.
