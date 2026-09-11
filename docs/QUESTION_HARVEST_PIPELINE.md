# Q Station — the pipeline, end to end

Canonical id: `q_station`. The filename is retained as a documentation compatibility path;
`question_harvest` is now only a legacy alias for resuming historical runs.

One launch on the panel produces one episode: a vertical Short whose narration, images and
opening clips all come from real provider UIs driven through Ordak. This document is the
map. It says what each stage consumes, what it writes, and what makes it refuse.

## Absolute rules (§4, §60-61)

These are not preferences. Code enforces each one, and tests assert the refusal.

| Rule | Enforced by |
|---|---|
| text = ChatGPT, image = Gemini, video = Flow — all through Ordak | `validate_provider_locks`, `tests/test_provider_lock.py` |
| No synthetic media, no provider fallback, no placeholder frame | no fallback path exists; `check_full_stack.py` greps `scripts/` |
| Flow never receives a style sheet | `flow_reference_policy`, re-checked at the upload boundary |
| Character identity is registry-driven and independent of visual/world style | `character_runtime`, `characters/registry.json` |
| WORLD_KEYFRAME and Clip B are host-free | Stage 06/09 prompts and frames-only Flow policy |
| Frames and Ingredients are exclusive | one Flow tablist, one active mode |
| `outputs=x1` always | `flow_settings` verifies the control after setting it |
| Zero blind duplicate Generate | credit guard fingerprint + `_reconcile_pending` |
| `model_verified` only with UI evidence | `GenerationReceipt` validator rejects a bare claim |
| No proxy; direct connection | `trust_env=False` on every client |

## The two halves

`run_full_video_pipeline_qh_wrapper.py` is the only entry point the panel uses. It runs
the visual half, then narration and timing, then the completion half.

```
panel /launch (Auto or manual Character)
  └─ run_full_video_pipeline_qh_wrapper.py
       ├─ run_question_harvest_pipeline.py     17 stages: script → Flow clips → body images
       ├─ run_elevenlabs_voiceover.py          one continuous narration track (§66)
       ├─ align_beats.py                       real word timestamps → WORD_TIMINGS.json
       ├─ trim_opening_clips.py                cut Flow sources to measured boundaries (§67)
       ├─ run_pixabay_music.py --provider mixkit
       └─ run_completion_pipeline.py           timeline → render → QC → polish → QC → publish
```

Every stage is resumable. A stage with a valid artifact **and** a recorded `DONE` state is
reused, which is what makes a failed run cheap to continue: `/resume` on the panel re-runs
the same command, and paid work is never bought twice.

## Visual half — the 17 stages

| # | Stage | Provider | Writes |
|---|---|---|---|
| 1 | `script_draft` | ChatGPT | `creative/SCRIPT_DRAFT.json` |
| 2 | `retention_edit` | ChatGPT | `creative/SCRIPT_PLAN.json`, `SCRIPT_FINAL.md` |
| — | `character_resolution` | ChatGPT for Auto; local for manual/resume | `creative/CHARACTER_RESOLUTION.json`, launch manifest |
| 3 | `episode_director` | ChatGPT | `creative/EPISODE_PLAN.json` |
| 4 | `world_style_director` | ChatGPT | `creative/WORLD_STYLE_PLAN.json` |
| 5 | `world_style_anchor` | Gemini *or* catalog copy | `references/world_style_anchor.png` |
| 6 | `episode_history` | — | `projects/<id>/VIDEOS.json` |
| 7 | `visual_plan` | ChatGPT | `creative/VISUAL_PLAN.json` |
| 8 | `world_keyframe_prompt` | ChatGPT | prompt text |
| 9 | `world_keyframe` | Gemini | `references/world_keyframe.png` |
| 10 | `book_design_sheet` | Gemini | `references/book_design_sheet.png` |
| 11 | `book_spread` | local compositor | `references/book_spread.png` |
| 12-13 | `flow_prompt_a` / `_b` | ChatGPT | clip prompts |
| 14 | `flow_clip_a` | Flow | `assets/opening/question_spark_source.mp4` |
| 15 | `flow_clip_b` | Flow | `assets/opening/book_transition_source.mp4` |
| 16 | `beat_prompts` | ChatGPT | per-beat image prompts |
| 17 | `body_images` | Gemini | `assets/images/beat_*.png` |

Stage 6 runs immediately after the style decision rather than at publication, so an episode
that fails later still constrains the next one instead of vanishing from history (§35).

## What the operator controls

The panel writes every choice into `launch/CREATIVE_BRIEF.json` under `_qh`, and the wrapper
turns those into CLI flags. Nothing is inferred from the topic text.

| Panel field | Flag | Effect |
|---|---|---|
| Character | `--character-mode`, `--character-id` | Auto resolves once after Stage 02; manual validates an enabled registry id |
| Min/Max duration | `--min-duration-seconds/--max-duration-seconds` | fills `{{DURATION_RANGE}}`, `{{WORD_RANGE}}`, `{{WORD_TARGET}}` in prompts 01 and 02 |
| World style | `--world-style-id` | binding reuse of a catalogued `style_id`; validated against the catalog before anything runs |
| World style policy | `--world-style-policy` | `auto` / `reuse` / `new` |
| World style hint | `--world-style-hint` | free-text steer for a new style |
| Gemini image model | `--gemini-model` | verified against the UI, see below |
| Non-critical image QC corrections | `--image-qc-correction-policy` | `0`, `1`, `2`, or `strict` (three total attempts and then fail unless fully clean) |
| Flow model / resolution | `--flow-model`, `--flow-resolution` | verified against the Flow settings menu |
| Opening A/B seconds | `--opening-a-seconds/-b-` | Flow source length, one second of headroom over the planned segment |

The duration is binding rather than advisory: `DurationTarget` derives the word range from
it at 2.3-2.5 words per second, which is the same ratio the format's own 40-60s => 92-150
word rule encodes.

Every Gemini request verifies Extended Thinking from the live mode picker after model/tool
selection and immediately before submission. Image QC corrections attach the previous
candidate as a quality floor, target only the reported findings, and atomically publish the
best non-blocking candidate. A retry with new regressions cannot displace a better earlier
candidate; blocking identity, continuity, or wrong-output failures are never accepted.

Farmer Host and Red Horned Everyman are the current packs. Environments are dynamic per
episode; Farmer's rural affinities are soft and Red has none. Character sheets are
identity-only. Host-present body beats may receive the selected sheet; host-absent beats do
not. Clip A uses Ingredients with only that sheet. Clip B uses only first/last Frames and is
independent of the selected host and opening environment.

## Length, and why the word range is derived

`body_seconds = max(20, word_count × 0.42 − (opening_a + opening_b))`. The 0.42 is the
inverse of the speaking rate. A 25-30s request therefore asks for ~57-75 words, and the
retention editor tightens to that range instead of the 40-60s default.

## Refusals worth knowing

* **`aspect_mismatch`** — Gemini has no aspect-ratio control, so the requested ratio is
  stated in the prompt and the downloaded file is measured. A landscape answer to a 9:16
  request is rejected, not cropped.
* **`MODEL_NOT_AVAILABLE`** — the requested image model is not the one the UI names. See
  `docs/ORDAK_GEMINI_BROWSER_AUTOMATION.md`.
* **`FAILED_VALIDATION` on the style** — `--world-style-id` was given and the director
  answered with a different id.
* **repeated opening** — `stage_episode_director` gets an explicit avoidance note; one
  retry names the repeat exactly, a second repeat fails the stage.
* **alignment without word timestamps** — the wrapper stops rather than trimming the
  opening clips against estimated boundaries.

## Telegram

Progress notifications and final media delivery share Telegram credentials but have separate
enablement policies: disabling progress logs never disables a requested final upload. Each
long-running stage owns one editable message keyed by run/revision and stage ID; resumes edit
that message instead of creating a duplicate. Fast reuse results are summarized, body images
use one aggregate counter, and render/upload messages use measured progress. Static global
step counts are omitted when optional stages make them untrue; completion uses its frozen,
enabled stage list for exact local positions. Failures and waits close the active message.

Message IDs and notification errors are recorded in
`pipeline/TELEGRAM_NOTIFICATION_STATE.json`. The finished video caption is artifact-grounded
and includes the correct QC gate for original or compact delivery.
