# Voiceover Workflow — Video 001

## Goal

Create one natural full-length narration track, then align the 18 visual beats to the actual spoken timing.

## Important decision

Do **not** generate one audio file per beat.

Generate the entire narration as **one continuous ElevenLabs voiceover**.

Why:
- more natural pacing and prosody
- sentence transitions sound human
- no audible seams between beats
- image timing can be derived afterward from the spoken audio

The visual beats are editing units, not voice-generation units.

## Input

Use the exact narration text in:

`VOICEOVER_INPUT.txt`

Do not rewrite the script inside ElevenLabs.

## Current MVP process

Until ElevenLabs browser automation is added:

1. Open ElevenLabs manually.
2. Select the voice/model to test.
3. Paste the complete contents of `VOICEOVER_INPUT.txt`.
4. Generate one continuous narration.
5. Listen once for pronunciation, pacing, and obvious artifacts.
6. If acceptable, download it.
7. Save it exactly as:

```text
../assets/audio/narration.mp3
```

If ElevenLabs provides a lossless/WAV download and it is convenient, also acceptable:

```text
../assets/audio/narration.wav
```

Use only one accepted narration source for timing.

Generated audio is Git-ignored.

## Voice profile

Record the exact selected voice and important ElevenLabs settings in:

`VOICE_PROFILE.md`

This makes later regeneration reproducible.

## Do not manually time images yet

Once `narration.mp3` exists, the next pipeline stage will analyze the audio and produce timestamps for the narration.

Those timestamps will be mapped to the exact Narration text already stored for each beat in `VISUAL_BEATS.md`.

Target output concept:

```text
Beat 01  00:00.00 -> 00:02.10
Beat 02  00:02.10 -> 00:03.40
...
Beat 18  00:55.20 -> 00:59.80
```

The numbers above are examples only. Real timings must come from the generated audio.

## Alignment strategy

Preferred workflow:

```text
full narration audio
    ↓
speech transcription / word timestamps
    ↓
match exact beat narration strings
    ↓
beat start/end timestamps
    ↓
timeline data
```

This preserves natural speech while still giving every image an exact duration.

## Future ElevenLabs automation

When browser automation is implemented, the runner should:

1. read `VOICEOVER_INPUT.txt`
2. load the selected voice profile
3. open/reuse an authenticated ElevenLabs browser session
4. paste the full narration
5. generate
6. wait for completion
7. download the accepted audio
8. save it to `assets/audio/narration.*`
9. persist job/status information
10. continue to alignment

Do not split narration per beat unless future testing proves a strong reason to do so.
