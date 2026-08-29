# Future Ordak Automation Plan — Beat Prompts and Images

## Purpose

This document defines how the video pipeline should integrate with **ordak** once browser automation is wired into this repository.

The design must scale from short videos with ~20 visual beats to long videos with 100–300+ beats without requiring manual prompt creation or restarting failed work from the beginning.

ordak repository:

```text
https://github.com/AliBalash/ordak
```

ordak should be treated primarily as the **browser execution layer** for ChatGPT/Gemini, not as the owner of video-pipeline business logic.

---

## Architecture responsibility split

### This repository owns

- video project state
- visual beats
- selected visual preset
- prompt-generation rules
- beat prompt files
- reference selection
- output naming
- sequencing
- retry policy
- QC decisions
- resumability
- progress/state tracking

### ordak owns

- authenticated browser session reuse
- ChatGPT/Gemini tab control
- uploading reference images
- submitting prompts
- waiting for provider completion
- extracting text responses
- extracting generated images
- persisted browser jobs
- retry/resume at the browser-job layer
- provider diagnostics

The pipeline must not depend on hidden chat memory for correctness. Required state must live in files and structured project data.

---

# Stage A — Generate prompts for many beats

For a long video, do **not** manually create one prompt at a time.

Input:

```text
VISUAL_BEATS.md
visual preset
video-specific continuity rules
prompts/04_single_beat_image_prompt_writer.md
```

Output:

```text
beats/
  BEAT_001_PROMPT.md
  BEAT_002_PROMPT.md
  ...
  BEAT_200_PROMPT.md
```

## Recommended batching

Prompt generation should be batched because it is text-only and inexpensive relative to image generation.

Example:

```text
Beats 001–010 -> one ordak text job
Beats 011–020 -> one ordak text job
...
Beats 191–200 -> one ordak text job
```

A default batch size of **10–20 beats** is a good starting point.

The prompt-generation response should use a machine-parseable structure so the orchestrator can split it into individual files.

Possible response format:

```text
=== BEAT 001 ===
<full prompt>

=== BEAT 002 ===
<full prompt>
```

A future implementation may use structured JSON instead, if that proves more reliable through the web UI.

## Validation after each batch

Before accepting the batch:

- expected beat IDs are present exactly once
- no beat is missing
- no duplicate beat exists
- narration/visual meaning is preserved
- each prompt requests exactly one standalone image
- each prompt follows the selected visual preset
- previous-beat reference is correct
- file names are deterministic

If validation fails, retry only that batch.

---

# Stage B — Generate images sequentially

Image generation is different from prompt generation.

Because Beat N uses the accepted image from Beat N-1 as a continuity reference, image generation should normally run **sequentially within a video**.

## Beat 001

Inputs:

```text
style_anchor.png
character_anchor.png
optional video-specific anchors
BEAT_001_PROMPT.md
```

Output:

```text
assets/raw_beats/beat_001.png
```

## Beat 002+

Inputs:

```text
style_anchor.png
character_anchor.png
optional video-specific anchors
assets/raw_beats/beat_(N-1).png
BEAT_NNN_PROMPT.md
```

Output:

```text
assets/raw_beats/beat_NNN.png
```

Reference priority remains:

1. character anchor
2. style anchor
3. video-specific recurring anchor
4. previous accepted beat image
5. current beat prompt

The previous beat must never become the source of truth for protagonist identity or rendering style.

---

# Conversation strategy for large videos

Do not rely on a single giant ChatGPT conversation for 100–300 beats.

Long conversations can become slow, polluted by old context, and more prone to visual drift.

Recommended approach:

```text
Beats 001–020 -> Conversation A
Beats 021–040 -> Conversation B
Beats 041–060 -> Conversation C
...
```

The exact chunk size should remain configurable.

When starting a new conversation, the first beat in that conversation must still receive:

```text
style anchor
character anchor
relevant video-specific anchors
previous accepted beat image
current beat prompt
```

Because all important state is supplied explicitly, continuity should survive conversation changes.

A stricter fallback mode may create a fresh conversation for every beat. This is slower but should still work because state is file-driven.

---

# Required orchestrator state

A future pipeline runner should maintain explicit per-beat status.

Recommended states:

```text
PENDING
PROMPT_READY
GENERATING
DONE
FAILED
RETRY
RATE_LIMITED
QC_FAILED
```

Optional additional states:

```text
WAITING_FOR_PREVIOUS_BEAT
CANCELLED
MANUAL_REVIEW
```

Example state record:

```json
{
  "beat_id": 137,
  "prompt_path": "beats/BEAT_137_PROMPT.md",
  "previous_beat": 136,
  "status": "DONE",
  "attempts": 2,
  "output_path": "assets/raw_beats/beat_137.png",
  "ordak_job_id": "...",
  "conversation_id": "...",
  "last_error": null
}
```

The exact storage format can later be JSON, SQLite, or another structured store.

---

# Resume behavior

The automation must be resumable.

If Beat 137 fails:

- Beats 001–136 must remain untouched
- retry Beat 137 only
- Beat 138 must wait until Beat 137 has an accepted image
- once Beat 137 succeeds, continue from Beat 138

Never restart an entire long video because one browser job failed.

At startup, the orchestrator should scan existing state and output files and continue from the first incomplete beat.

---

# Retry policy

Retry categories should be separated.

## Browser/UI transient failure

Examples:

- selector temporarily unavailable
- upload not completed
- provider still busy
- tab lost/rebound
- response stalled

Action:

- use ordak retry/resume
- retry same beat
- preserve the same prompt and references

## Rate limit

Action:

- mark beat as `RATE_LIMITED`
- wait according to configured policy
- resume from the same beat later

## Image-quality / continuity failure

Examples:

- wrong protagonist
- wrong style
- text/captions appeared
- multiple panels created
- previous scene copied instead of advanced
- recurring room/cast drifted significantly

Action:

- mark `QC_FAILED`
- regenerate the same beat
- keep the previous accepted beat as the continuity source
- optionally append a concise corrective instruction

Do not use the rejected image as the previous-beat reference.

---

# QC strategy

Initial MVP should keep human QC.

Later, automated QC may check:

- expected output file exists
- image dimensions/aspect ratio
- one image rather than multiple extracted artifacts
- obvious text/panel/grid violations
- image similarity to canonical anchors
- similarity to previous beat for continuity without being a near-duplicate

Automated QC should not silently replace human creative judgment until tested extensively.

---

# File naming for long videos

Use zero-padded numbering based on expected scale.

For 100+ beats prefer three digits:

```text
BEAT_001_PROMPT.md
BEAT_002_PROMPT.md
...
BEAT_200_PROMPT.md

beat_001.png
beat_002.png
...
beat_200.png
```

For current Video 001, two-digit names already exist and are acceptable.

Future project tooling should derive padding width automatically from total beat count or enforce a project-wide standard.

---

# Proposed future commands

These are target interfaces, not implemented yet.

## Generate prompt files

```bash
python pipeline/generate_beat_prompts.py \
  videos/<video_id> \
  --provider chatgpt \
  --batch-size 10
```

Responsibilities:

- read VISUAL_BEATS.md
- load selected visual preset metadata
- build batched prompt-writer requests
- submit text jobs through ordak
- parse responses
- write individual BEAT_NNN_PROMPT.md files
- validate completeness
- persist progress

## Generate images

```bash
python pipeline/generate_beat_images.py \
  videos/<video_id> \
  --provider chatgpt
```

Responsibilities:

- find first incomplete beat
- select required reference files
- upload references through ordak
- submit beat prompt
- wait for generated image
- extract/download image
- save deterministic file name
- update state
- run QC
- retry or continue

---

# Suggested ordak integration interface

Prefer calling ordak through its local HTTP/job API rather than importing its internal browser modules directly.

Conceptual flow:

```text
pipeline orchestrator
        |
        v
ordak local HTTP API
        |
        v
persisted ordak job queue
        |
        v
ChatGPT/Gemini browser UI
        |
        v
text/image result
        |
        v
pipeline state + project files
```

Benefits:

- keeps repositories loosely coupled
- ordak can evolve independently
- browser failures stay inside ordak
- pipeline can persist its own domain-specific state
- easier to test with mocked ordak responses later

---

# Concurrency rules

## Prompt generation

Can be batched and potentially parallelized later.

## Image generation within one video

Default: sequential, because Beat N depends on Beat N-1.

## Multiple videos

Different videos can potentially generate in parallel if ordak/provider capacity allows it.

Do not add concurrency before reliability and rate-limit behavior are understood.

---

# Implementation order when ordak is added

1. Add an ordak client wrapper to this repository.
2. Implement health/diagnostics check.
3. Implement text-job submission and result polling.
4. Implement batched beat-prompt generation.
5. Add prompt parser and validation.
6. Add pipeline state storage.
7. Implement image-job submission with reference uploads.
8. Implement sequential beat image runner.
9. Add retry/resume handling.
10. Add rate-limit waiting.
11. Add manual QC checkpoints.
12. Only after reliability is proven, add automatic QC and multi-video concurrency.

---

# Key design principle

The system should behave like a compiler/build pipeline:

```text
SCRIPT
  -> VISUAL_BEATS
  -> BEAT_PROMPTS
  -> BEAT_IMAGES
  -> VOICE/TIMING
  -> TIMELINE
  -> FINAL_VIDEO
```

Each stage produces deterministic artifacts that can be inspected, regenerated, resumed, or replaced independently.

ordak is an execution backend inside this larger pipeline, not the source of project truth.
