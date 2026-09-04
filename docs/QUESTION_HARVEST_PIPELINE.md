# Question Harvest — the pipeline, end to end

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
| Frames and Ingredients are exclusive | one Flow tablist, one active mode |
| `outputs=x1` always | `flow_settings` verifies the control after setting it |
| Zero blind duplicate Generate | credit guard fingerprint + `_reconcile_pending` |
| `model_verified` only with UI evidence | `GenerationReceipt` validator rejects a bare claim |
| No proxy; direct connection | `trust_env=False` on every client |

## The two halves

`run_full_video_pipeline_qh_wrapper.py` is the only entry point the panel uses. It runs
the visual half, then narration and timing, then the completion half.

```
panel /launch
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
| Min/Max duration | `--min-duration-seconds/--max-duration-seconds` | fills `{{DURATION_RANGE}}`, `{{WORD_RANGE}}`, `{{WORD_TARGET}}` in prompts 01 and 02 |
| World style | `--world-style-id` | binding reuse of a catalogued `style_id`; validated against the catalog before anything runs |
| World style policy | `--world-style-policy` | `auto` / `reuse` / `new` |
| World style hint | `--world-style-hint` | free-text steer for a new style |
| Gemini image model | `--gemini-model` | verified against the UI, see below |
| Flow model / resolution | `--flow-model`, `--flow-resolution` | verified against the Flow settings menu |
| Opening A/B seconds | `--opening-a-seconds/-b-` | Flow source length, one second of headroom over the planned segment |

The duration is binding rather than advisory: `DurationTarget` derives the word range from
it at 2.3-2.5 words per second, which is the same ratio the format's own 40-60s => 92-150
word rule encodes.

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

Every stage start, completion, reuse and failure is sent through the Telethon user session
to `YT_PIPELINE_TELEGRAM_RECIPIENT`. Titles carry the position in the run, so the thread
reads as `step 4/17 · World Style Director`. The finished polished video is sent as a file
with a caption built only from artifacts — durations, beat counts, verified model labels,
QC verdicts. See `docs/RECOVERY_RUNBOOK.md` for what to do when a stage stops.
