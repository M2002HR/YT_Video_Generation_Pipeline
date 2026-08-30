# Voiceover Workflow — Video 001

## Goal

Create one natural full-length narration track, then align the 18 visual beats to the actual spoken timing.

## Voice generation decision

Generate the entire narration as **one continuous ElevenLabs voiceover**, not one file per beat.

This preserves natural pacing, prosody, and sentence transitions.

## Input

Use the exact narration in:

`VOICEOVER_INPUT.txt`

Accepted narration is stored locally as:

```text
../assets/audio/narration.mp3
```

Generated audio is Git-ignored.

## Current stage — alignment

Once the accepted narration file exists, run the local timing pipeline documented in:

```text
../timing/README.md
```

Command from repository root:

```bash
python -m pip install -r requirements-alignment.txt

python scripts/align_beats.py \
  videos/001_brain_replays_embarrassing_moments
```

This produces:

```text
../timing/BEAT_TIMINGS.json
../timing/BEAT_TIMINGS.md
```

The JSON file becomes the machine-readable timing source for timeline construction.

## Alignment logic

```text
full narration
    ↓
Ajil UAG / Groq Whisper word timestamps
    ↓
match exact narration strings from VISUAL_BEATS.md
    ↓
speech timing per beat
    ↓
continuous display timing per beat
```

## Future ElevenLabs automation

When browser automation is implemented, the runner should:

1. read `VOICEOVER_INPUT.txt`
2. load the selected voice profile
3. open/reuse an authenticated ElevenLabs session
4. generate the full narration
5. download it into `assets/audio/`
6. persist status
7. automatically invoke beat alignment

Do not split narration per beat unless future testing proves a strong reason.

## Current STT backend

Timing/alignment now defaults to the Ajil UAG git submodule and its Groq STT path.

See:

`docs/AJIL_UAG_INTEGRATION.md`

The root project `.env` controls Ajil and all embedded-provider runtime settings. No submodule-local `.env` files are used.
