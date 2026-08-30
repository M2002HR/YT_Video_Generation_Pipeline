# Timing / Alignment

This stage converts the accepted full narration into exact display durations for every visual beat.

## Required local asset

One accepted narration file must exist:

```text
../assets/audio/narration.mp3
```

(or `narration.wav`).

## Default backend: Ajil UAG + Groq Whisper

The default alignment path no longer downloads or runs a local Whisper model.

It sends the narration to the local Ajil UAG service, which uses:

```text
primary:  whisper-large-v3-turbo
fallback: whisper-large-v3
timestamps: word,segment
```

Ajil returns the transcription/timestamps; the pipeline then matches those timestamps against the exact narration text stored in `VISUAL_BEATS.md`.

Full service setup is documented in:

```text
docs/AJIL_UAG_INTEGRATION.md
```

## First-time setup

From repository root:

```bash
python scripts/setup_services.py
cp .env.example .env
```

Edit root `.env` and set at minimum a real Groq key:

```text
UAG_GROQ_API_KEYS=...
```

Do not put runtime config inside the Ajil submodule.

## Run

Terminal 1:

```bash
python scripts/run_ajil.py
```

Optional health check from Terminal 2:

```bash
python scripts/check_ajil.py
```

Then:

```bash
python scripts/align_beats.py \
  videos/001_brain_replays_embarrassing_moments
```

## Outputs

The script creates:

```text
timing/
  BEAT_TIMINGS.json
  BEAT_TIMINGS.md
```

These timing files are project metadata and should be committed after a quick manual review.

`BEAT_TIMINGS.json` is the machine-readable timing source for the future timeline/render stage.

Each beat contains:

- `speech_start` / `speech_end`
- `display_start` / `display_end`
- `display_duration`
- `match_confidence`

The JSON also records STT metadata such as backend, provider, model, fallback use, and timestamp source.

## QC

Preferred:

```text
timestamp_source=word
```

Review:
- any beat below 75% token-match confidence
- any run reporting `timestamp_source=segment_interpolated`

Because the narration was generated from the exact approved script, normal word-timestamp runs should match closely.

## Optional local CPU fallback

If Ajil/Groq is unavailable:

```bash
python -m pip install -r requirements-local-whisper.txt

python scripts/align_beats.py \
  videos/001_brain_replays_embarrassing_moments \
  --backend local \
  --model small.en \
  --device cpu \
  --compute-type int8
```

This works without a GPU, but is a fallback rather than the default path.
