# Ajil UAG Integration

## Decision

Ajil Unified AI Gateway is included as a git submodule and is the default Speech-to-Text backend for narration timing/alignment.

Submodule path:

```text
services/ajil_uag
```

Upstream repository:

```text
https://github.com/M2002HR/Ajil_Unified_AI_Gateway
```

Ajil itself contains provider submodules (Groq, Gemini, Pollinations), so initialization must always be recursive.

## Why use Ajil for STT

For this pipeline, Ajil's Groq integration already provides the features we need:

- OpenAI-compatible Groq access
- dedicated `/v1/audio/transcriptions` endpoint
- primary/fallback Whisper models
- multi-key rotation
- retry/failover for rate limits and upstream failures
- verbose JSON transcription output
- configurable word and segment timestamps
- no local GPU or local Whisper model required
- reusable gateway for future LLM, TTS, embeddings, and image-provider tasks

Default STT policy for this repository:

```text
primary  = whisper-large-v3-turbo
fallback = whisper-large-v3
language = en
format   = verbose_json
timestamps = word,segment
```

Word timestamps are used for beat alignment. Segment timestamps are kept for diagnostics/fallback.

## Root-only configuration policy

The parent repository's root `.env` is the single authoritative runtime configuration file.

Create it once:

```bash
cp .env.example .env
```

Do not create or edit runtime `.env` files inside:

```text
services/ajil_uag/
services/ajil_uag/modules/groq_proxy/
services/ajil_uag/modules/gemini_proxy/
services/ajil_uag/modules/pollinations_proxy/
```

The launcher sets:

```text
UAG_ENV_FILE=<absolute path to parent .env>
```

Ajil loads that file directly.

Ajil's provider submodules are imported as Python libraries, not launched as separate FastAPI servers. Their effective runtime settings are constructed by Ajil from root-level `UAG_*` variables and passed into those libraries programmatically.

This means provider settings that affect embedded behavior are root-configurable. Standalone nested-service host/admin settings are intentionally not duplicated because those nested web servers are not run in this architecture.

## Root configuration namespaces

The authoritative list is `.env.example`.

Main namespaces:

```text
YT_*                   pipeline/client configuration
UAG_APP_*              Ajil process
UAG_LOG_*              observability
UAG_AUTH_*             client authentication
UAG_ADMIN_*            Ajil admin authentication
UAG_ROUTER_*           routing/fallback
UAG_PROXY_*            shared outbound proxy
UAG_REDIS_*            Redis/rate-limit state
UAG_GEMINI_*           embedded Gemini runtime
UAG_GROQ_*             embedded Groq runtime, STT and TTS
UAG_POLLINATIONS_*     embedded Pollinations runtime
UAG_IMAGE_*            image request defaults
```

The root project exposes provider request timeouts and provider-specific runtime controls instead of hard-coding them inside the submodule.

## First setup

After cloning or pulling:

```bash
python scripts/setup_services.py
```

This performs:

```text
git submodule sync --recursive
git submodule update --init --recursive
pip install root requirements
pip install Ajil requirements
```

Then create root config:

```bash
cp .env.example .env
```

At minimum, replace:

```text
UAG_GROQ_API_KEYS=replace_with_groq_key
UAG_AUTH_TOKEN=change_me_local_client_token
```

Multiple Groq keys can be comma-separated.

## Run Ajil

Terminal 1:

```bash
python scripts/run_ajil.py
```

The launcher explicitly forces Ajil to use the root `.env`.

Health check from Terminal 2:

```bash
python scripts/check_ajil.py
```

## Run narration alignment

With Ajil running:

```bash
python scripts/align_beats.py \
  videos/001_brain_replays_embarrassing_moments
```

Default backend:

```text
YT_STT_BACKEND=ajil
```

Flow:

```text
narration.mp3
  -> YT align script
  -> Ajil /v1/audio/transcriptions
  -> Groq whisper-large-v3-turbo
  -> fallback whisper-large-v3 if needed
  -> word timestamps
  -> exact-script token matching
  -> BEAT_TIMINGS.json + BEAT_TIMINGS.md
```

## Optional local fallback

Ajil is the default, but local faster-whisper is retained for offline/server fallback.

Install:

```bash
python -m pip install -r requirements-local-whisper.txt
```

Run:

```bash
python scripts/align_beats.py \
  videos/001_brain_replays_embarrassing_moments \
  --backend local \
  --model small.en \
  --device cpu \
  --compute-type int8
```

The local backend does not need a GPU. It is useful when Groq/Ajil is unavailable, but the Ajil/Groq large-model path is preferred for this project's precise narration alignment.

## Timestamp fallback behavior

Preferred Ajil response:

```text
raw.words[] -> exact word timestamps
```

If word timestamps are unexpectedly missing but segments exist, the aligner can interpolate word positions inside each segment and marks:

```text
timestamp_source=segment_interpolated
```

That mode requires extra QC.

Normal project configuration requests:

```text
UAG_GROQ_STT_TIMESTAMP_GRANULARITIES=word,segment
```

so normal output should report:

```text
timestamp_source=word
```

## Submodule update policy

Do not let submodules float automatically.

The parent repository pins a specific Ajil commit. Ajil pins specific provider-module commits.

To intentionally update later:

```bash
cd services/ajil_uag
git fetch
git checkout <reviewed-commit>
cd ../..
git add services/ajil_uag
git commit -m "Update Ajil UAG submodule"
```

Then run tests and an end-to-end transcription before accepting the update.

## Changes made for this integration

The Groq proxy was extended to make timestamp granularity configurable, including `word,segment`.

Ajil was extended so its root configuration exposes:

- Groq STT timestamp granularities
- provider request timeouts
- Gemini proxy/network/default-request controls
- Gemini Cloudflare access controls
- Pollinations request timeout
- existing Groq/Pollinations retry/model/image defaults

Ajil passes these root settings into its embedded provider libraries.

## Future use

Ajil should remain a reusable service boundary rather than importing its internal provider code directly into the video pipeline.

The video pipeline should talk to Ajil via HTTP.

That keeps:

- provider keys centralized
- rate-limit logic centralized
- provider fallback centralized
- the video project focused on video-domain orchestration
- submodule updates isolated and reviewable
