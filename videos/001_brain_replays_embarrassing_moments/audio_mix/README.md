# Audio Polish — Video 001

## Baseline is locked

The accepted clean baseline remains:

```text
assets/renders/final.mp4
```

Do not overwrite it.

Audio polish creates a separate comparison output:

```text
assets/renders/polished.mp4
```

The video stream is copied unchanged; only audio is rebuilt.

## Root idea

```text
accepted final.mp4
+ optional background music
+ optional sparse SFX
        ↓
narration-first ducking
        ↓
loudness normalization
        ↓
polished.mp4
```

## Local assets

Background music:

```text
assets/music/background.mp3
```

SFX:

```text
assets/sfx/
```

These generated/downloaded assets are Git-ignored.

## Current default mix

`AUDIO_MIX_PROFILE.json` starts conservatively:

- music gain: -20 dB
- music fade-in: 0.8s
- music fade-out: 1.4s
- narration-triggered sidechain ducking
- duck ratio: 8:1
- fast attack / smooth release
- loudness target: -14 LUFS
- true-peak ceiling: -1.5 dBTP
- SFX event list initially empty

The main creative rule is: narration stays dominant.

## Add background music

Place one local music file at:

```text
assets/music/background.mp3
```

Then dry-run:

```bash
python scripts/polish_audio.py \
  videos/001_brain_replays_embarrassing_moments \
  --dry-run
```

Then render:

```bash
python scripts/polish_audio.py \
  videos/001_brain_replays_embarrassing_moments
```

Output:

```text
assets/renders/polished.mp4
```

## Add SFX later

SFX are configured as explicit events in `AUDIO_MIX_PROFILE.json`.

Example:

```json
{
  "file": "assets/sfx/whoosh.wav",
  "at": 28.34,
  "gain_db": -12.0,
  "trim_sec": 0.8
}
```

Use SFX sparsely and only where they reinforce a semantic beat.

Do not decorate every image change.

## A/B review

Always compare:

```text
final.mp4      = accepted clean baseline
polished.mp4   = music/SFX experiment
```

If polish makes narration less clear or makes the short feel busier, keep the baseline.

## QC

After an audio-polished version is accepted, run:

```bash
python scripts/qc_render.py \
  videos/001_brain_replays_embarrassing_moments \
  --input videos/001_brain_replays_embarrassing_moments/assets/renders/polished.mp4 \
  --decode
```

This reuses the existing structural render QC.

A future audio-specific QC pass can measure integrated loudness and true peak directly.
