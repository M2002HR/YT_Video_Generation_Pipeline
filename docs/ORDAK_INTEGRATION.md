# Ordak Integration — YT Video Generation Pipeline

## Repository / branch

Ordak is included as:

```text
services/ordak
```

Upstream repository:

```text
https://github.com/AliBalash/ordak.git
```

Pipeline branch:

```text
yt-video-pipeline
```

The parent repository pins an exact Ordak commit while `.gitmodules` records the intended branch.

## Responsibility boundary

The parent video pipeline owns:

- video/job state
- script/beat planning
- prompt files
- reference selection/order
- deterministic output naming
- accepted/rejected beat state
- cross-job retry/resume policy
- copying accepted generated images into `videos/<id>/assets/raw_beats/`

Ordak owns:

- the real authenticated Chrome session
- ChatGPT tab discovery/rebinding/opening
- prompt insertion
- reference-image upload
- submit/wait/extract behavior
- generated-image download/export
- browser diagnostics, screenshots, traces, and low-level UI recovery

Current provider scope is **ChatGPT only**. Gemini is intentionally out of scope for this stabilization milestone.

## Root environment is authoritative

Do not maintain a second pipeline runtime `.env` inside `services/ordak`.

The root `.env` contains `YT_ORDAK_*` settings.

`scripts/run_ordak.py`:

1. loads the parent root env
2. maps `YT_ORDAK_*` to Ordak's native setting names
3. exports `ORDAK_ENV_FILE=<absolute root .env>`
4. launches Ordak from `services/ordak`

The pipeline branch of Ordak supports `ORDAK_ENV_FILE`.

## Browser profile

The authenticated Chrome profile is explicitly selected in root env:

```env
YT_ORDAK_BROWSER_USER_DATA_DIR=/home/<your-user>/.config/google-chrome
YT_ORDAK_BROWSER_PROFILE_NAME=Default
YT_ORDAK_BROWSER_EXECUTABLE_PATH=/usr/bin/google-chrome
YT_ORDAK_BROWSER_REMOTE_DEBUGGING_URL=http://127.0.0.1:9222
```

Ordak/Codex must never silently switch to a new logged-out profile when the configured profile is unavailable.

For the current upstream runtime, attach-only mode remains the default:

```env
YT_ORDAK_BROWSER_REMOTE_DEBUGGING_AUTO_LAUNCH=false
```

The dedicated Codex stabilization goal will implement and validate safe automatic browser startup/recovery using the configured authenticated profile.

## Timeouts / stall recovery baseline

Root defaults intentionally allow long image generations:

```env
YT_ORDAK_BROWSER_TIMEOUT_MS=180000
YT_ORDAK_CHATGPT_RESPONSE_TIMEOUT_MS=600000
YT_ORDAK_CHATGPT_STABLE_RESPONSE_SECONDS=5
YT_ORDAK_CHATGPT_STALL_REFRESH_SECONDS=90
YT_ORDAK_CHATGPT_MAX_STALL_REFRESHES=3
YT_ORDAK_JOB_WAIT_TIMEOUT_SECONDS=900
YT_ORDAK_JOB_POLL_INTERVAL_SECONDS=2
```

Important semantic rule for future stabilization:

- **active generation is not a stall**
- if ChatGPT shows meaningful progress/busy state, keep waiting
- only refresh after a real no-progress stall window
- after refresh, reconcile whether the original response/image completed server-side
- do not blindly resubmit before reconciliation
- if still incomplete/stuck, resubmit the same idempotent job/exchange
- cap recoveries and preserve evidence/logs

## Setup

From repository root:

```bash
git pull
git submodule sync --recursive
git submodule update --init --recursive
python scripts/setup_services.py
```

Copy root config if needed:

```bash
cp .env.example .env
```

Then edit the Ordak profile settings in the root `.env`.

## Run

Terminal 1:

```bash
python scripts/run_ordak.py
```

Terminal 2:

```bash
python scripts/check_ordak.py
```

A healthy authenticated setup ends with:

```text
ORDAK CHECK: PASS
```

The readiness check requires:

- Ordak API reachable
- Chrome attached
- ChatGPT session detected
- ChatGPT `login_state=ready`

## Image workflow target

The stabilization branch will ultimately support this strict per-beat order:

```text
STYLE ANCHOR
CHARACTER ANCHOR
optional recurring/video anchors
previous accepted beat (Beat 02+)
current beat prompt
        ↓
exactly one accepted standalone 16:9 beat image
```

A rejected/failed image must never become the previous-beat continuity reference.

## Next milestone

The next artifact is a Codex goal document defining:

- complete browser state machine
- resilient timeout/refresh/reconcile/resubmit behavior
- text generation flow
- multi-reference ChatGPT image generation
- deterministic download/output handling
- resumable parent pipeline integration
- automated tests
- real-browser E2E acceptance criteria
- repeated failure/recovery tests under unstable network/UI conditions

Codex should continue iterating until all automated and real-browser acceptance criteria pass.
