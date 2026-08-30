# Timing / Alignment

This stage converts the accepted full narration into exact display durations for every visual beat.

## Assumption

The following local file already exists:

```text
../assets/audio/narration.mp3
```

(or `narration.wav`).

## Why local forced alignment

The narration was generated as one continuous track for natural prosody.

We now use local Whisper word timestamps to match the exact narration phrases in `VISUAL_BEATS.md` to the real audio.

## Install

From the repository root:

```bash
python -m pip install -r requirements-alignment.txt
```

The first run downloads the selected Whisper model.

FFmpeg/ffprobe is recommended and will be needed later for rendering anyway.

## Run

From the repository root:

```bash
python scripts/align_beats.py \
  videos/001_brain_replays_embarrassing_moments
```

Default model:

```text
small.en
```

For a faster/lighter test:

```bash
python scripts/align_beats.py \
  videos/001_brain_replays_embarrassing_moments \
  --model base.en
```

## Outputs

The script creates:

```text
timing/
  BEAT_TIMINGS.json
  BEAT_TIMINGS.md
```

These timing files should be committed to Git after a quick manual review.

`BEAT_TIMINGS.json` is the machine-readable source for the future timeline/render step.

Each beat contains:

- `speech_start` / `speech_end`: matched spoken phrase
- `display_start` / `display_end`: continuous image-edit interval
- `display_duration`
- `match_confidence`

## QC

Review any beat below 75% match confidence.

Because ElevenLabs is reading the exact approved script, normal runs should align very closely.

Do not manually guess image durations unless the alignment result is clearly wrong.
