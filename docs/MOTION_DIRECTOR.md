# Motion Director V2

Motion Director turns each accepted still-image beat into an ordered sequence of semantic
micro-shots. ChatGPT through Ordak decides the editorial intent from the real images,
narration, Ajil word timings, neighboring beats, and whole-episode rhythm. Local code then
validates, safety-corrects, compiles, and renders that intent. Model-authored FFmpeg or crop
expressions are never accepted or executed.

## Pipeline position

The completion path is:

```text
Ajil alignment
opening trim
build_timeline
motion_director
sfx_plan (when enabled)
render_baseline
qc_baseline
sfx_acquire (when enabled)
polish_audio
qc_polished
```

`motion_director` is one resumable user-visible stage. Its internal passes are:

1. Visual observation: ChatGPT sees the actual image attachments and returns only visible,
   normalized targets and forbidden regions.
2. Episode direction: one compact whole-episode energy, rhythm, emphasis, transition, and
   ending brief is created from the script, beat timings, Ajil words, and visual inventory.
3. Beat direction: configurable batches receive actual images, the global brief, exact word
   IDs/times, verified target IDs, previous camera state, and configurable neighbor context.
4. Senior-editor critic: batched semantic review can replace invalid/weak beat plans, after
   which the replacement must pass the same local validator.

The default planning batch is one image because the currently deployed Ordak/ChatGPT upload
UI proved more reliable with one attachment. Observation defaults to three images and critic
review to two beats. All batch sizes are configurable and each successful batch has its own
fingerprinted receipt.

## Artifacts

```text
motion/
  VISUAL_INVENTORY.json       image-grounded targets from the observation pass
  MOTION_DIRECTION.json       whole-episode editing brief
  MOTION_PLAN.json            validated semantic V2 plan
  COMPILED_MOTION_PLAN.json   deterministic safe camera geometry
  MOTION_QC.json              machine-readable quality report
  receipts/                   resumable Ordak pass/batch receipts
  debug/                      optional annotated target/camera previews
```

Debug media and rendered previews are ignored by Git's existing render policy. The JSON
metadata is intentionally small and commit-friendly.

## MOTION_PLAN V2 contract

All times are absolute timeline seconds. Image coordinates are normalized against the full
source image: `x` and `y` are bounding-box center, `w` and `h` are box dimensions, and every
value is in `0..1`. A semantic camera state references a verified target ID; it never contains
a crop expression.

```json
{
  "schema_version": 2,
  "duration_seconds": 58.514,
  "prompt_version": "motion-director-v2.0",
  "input_fingerprint": "sha256",
  "created_at": "ISO-8601",
  "settings_snapshot": {
    "pace": "fast",
    "style": "dynamic",
    "intensity": "normal"
  },
  "global_direction": {
    "schema_version": 2,
    "pace": "fast",
    "sections": [
      {
        "name": "hook",
        "start": 0.0,
        "end": 5.0,
        "energy": 0.95,
        "attention_velocity": 0.9
      }
    ],
    "emphasis_words": [
      {"word_id": "w_0042", "reason": "number"}
    ],
    "rhythm_notes": [],
    "transition_philosophy": [],
    "motion_contrast_plan": [],
    "ending_strategy": "purposeful final state",
    "prohibited_patterns": []
  },
  "beats": [
    {
      "beat_id": 3,
      "start": 14.4,
      "end": 18.28,
      "attention_story": ["athlete", "medal", "context"],
      "micro_shots": [
        {
          "shot_id": "b03_s01",
          "role": "establish",
          "start": 14.4,
          "end": 15.25,
          "edit_in": {"type": "cut"},
          "camera": {
            "start": {
              "target_id": "b03_athlete",
              "coverage": 0.45,
              "anchor_x": 0.5,
              "anchor_y": 0.42
            },
            "end": {
              "target_id": "b03_athlete",
              "coverage": 0.56,
              "anchor_x": 0.5,
              "anchor_y": 0.42
            }
          },
          "motion": {
            "type": "push_in",
            "easing": "ease_out",
            "start_delay": 0.0,
            "end_hold": 0.1,
            "reason": "Move attention to the athlete before the achievement."
          },
          "sync": {
            "mode": "movement_start_on_word",
            "word_id": "w_0042"
          }
        }
      ],
      "ending_state": {
        "target_id": "b03_athlete",
        "coverage": 0.56,
        "anchor_x": 0.5,
        "anchor_y": 0.42,
        "movement_direction": "in"
      },
      "transition_out": {
        "type": "cut",
        "duration": 0.0,
        "reason_code": "new_fact",
        "reason": "The narration begins a separate fact."
      }
    }
  ]
}
```

Required plan invariants:

- every image beat appears exactly once and uses its exact timeline start/end;
- micro-shots are ordered, have unique IDs, cover the full beat, and have no gap/overlap;
- every camera target exists in the image-grounded `VISUAL_INVENTORY.json`;
- every synchronized word exists in authoritative Ajil timings and belongs in the shot;
- `continue` begins at the preceding camera state; a different framing requires a real edit;
- holds have identical start/end states and do not claim a visual word-sync event;
- cuts have zero duration; decorative transitions use validated bounded durations;
- disabled primitives/transitions cannot appear;
- episode duration, narration, subtitles, and audio are never retimed.

## Vocabulary

Motion primitives:

```text
hold push_in pull_out pan tilt pan_push pan_pull drift settle reveal_move
```

First-class internal edit types:

```text
continue cut reframe_cut punch_cut_in punch_cut_out
match_position_cut detail_cut establishing_cut
```

Inter-beat transitions:

```text
cut dissolve fade
smoothleft smoothright smoothup smoothdown
wipeleft wiperight wipeup wipedown
slideleft slideright slideup slidedown
revealleft revealright revealup revealdown zoomin
```

Easing values:

```text
linear ease_in ease_out ease_in_out snappy gentle hold_then_move impact_then_settle
```

Word synchronization modes:

```text
none cut_on_word_start movement_start_on_word impact_apex_on_word
reveal_complete_on_word settle_on_word_end
```

## Deterministic compilation and safety

The camera solver converts semantic target coverage/anchors into a source viewport with the
output aspect ratio. It clamps the viewport to artwork/source bounds, keeps the verified
subject inside the crop when geometry allows, raises critical anchors above the subtitle
region, reduces the zoom ceiling for low-resolution inputs, clamps pan and zoom velocity,
and applies a small bounded minimum trajectory when a requested push/pull would otherwise be
a no-op. Every correction is recorded per shot in the compiled plan and QC.

Face protection uses the verified ChatGPT face/person box and safety padding in all installs.
When optional MediaPipe plus OpenCV are available, the target is snapped to a nearby detected
face before padding. A distant face detection is never allowed to retarget the shot. The
provider interface is `resolve_target(target, image)` with `chatgpt_bbox`,
`mediapipe_face`, and `fallback_center` results; an open-vocabulary detector can be inserted
later without changing the plan or compiler.

The renderer opens each still source once per beat and uses an FFmpeg `split` graph for all
of that beat's micro-shots. Internal cuts are zero-overlap concat operations, including a
wide-to-detail hard reframe of the same image. Non-cut inter-beat transitions use FFmpeg's
validated `xfade` vocabulary. Existing video beats retain their native motion and are only
normalized/reframed and transitioned as before.

Precedence is:

1. valid enabled V2 plan plus compiled plan;
2. valid V1 motion plan for backward compatibility;
3. legacy timeline `beat.motion`, `transition_in`, and `transition_seconds` behavior when no
   plan exists or Dynamic Motion is disabled.

## Resume and invalidation

The episode fingerprint includes the prompt version, episode geometry/subtitle settings,
timeline and beat timing, Ajil word timings, script/visual context, actual image SHA-256 and
dimensions, and every Motion setting. An unchanged valid plan and compiled artifact are
reused without contacting Ordak. Pass receipts have narrower fingerprints and allow a failed
batch to resume without repeating earlier expensive successful batches. Any relevant input
or setting change invalidates the dependent artifact.

Ordak requests use existing `OrdakJobs`, `Generation`, `Reference`, provider readiness,
timeouts, and bounded transport retries. JSON/semantic correction is also bounded. Chrome,
login, verification, upload, provider UI, timeout, malformed JSON, and missing-media failures
remain explicit; the system never silently substitutes random motion.

## Panel controls

The main Motion / Editing section exposes enablement, pace, intensity, style, transition
preference, maximum micro-shots, punch cuts, directional pans, hard reframes, and face
protection. The advanced section exposes all bounded production tunables: shot and event
durations, normal/punch zoom ceilings, pan distance/velocity, zoom velocity, transition
budget/durations, all primitive families, directional/reveal transitions, subtitle/blank
safety, word sync and tolerance, face padding, neighbor context, pass batch sizes, JSON
correction attempts, critic, debug previews, and supersampling. The frozen `_motion` launch
object is the sole configuration source and therefore survives resume.

`Enable Dynamic Motion Director` is a true master switch, not merely a UI preference. When
off, all subordinate controls are disabled in the panel, `motion_director` is omitted from
the completion-stage sequence, Ordak is never contacted for motion planning, and the renderer
ignores any retained V1/V2 plan and uses the legacy timeline motion path. Plans are retained
for a later re-enable; they are not deleted. When on, every individual checkbox is enforced by
the semantic validator: a disabled primitive, word sync, match-position cut, or non-cut
transition cannot enter the compiled render plan.

## Motion QC

`MOTION_QC.json` reports beats, micro-shots, visual events/minute, average/minimum/maximum
shot duration, hard cuts/reframes, non-cut transitions, motion/edit/transition distribution,
maximum repeated motion streak, holds percentage, average/maximum camera distance, average
zoom range, maximum zoom, non-hold no-op count, Ajil-synchronized event count, target
corrections, unsafe targets, critic findings, speech end, visual-tail duration, and whether
the tail has meaningful motion. Warnings cover repetition, transition spam, insufficient
event density for the selected pace, too-short shots, excessive zoom, no-op movement, unsafe
targets, and dead visual tails.

## Commands

```bash
python scripts/run_motion_director.py videos/020_video
python scripts/run_motion_director.py videos/020_video --force
python scripts/run_motion_director.py videos/020_video --recompile-existing
python scripts/render_video.py videos/020_video --output /tmp/motion-preview.mp4
python scripts/qc_render.py videos/020_video --input /tmp/motion-preview.mp4 --decode \
  --report /tmp/motion-preview-qc.json
```

`--recompile-existing` is an explicit developer recovery/verification operation: it never
contacts Ordak, but it does revalidate the real V2 semantic plan against current inputs and
rebuilds compiled geometry/QC. Normal pipeline execution uses fingerprints and receipts.
