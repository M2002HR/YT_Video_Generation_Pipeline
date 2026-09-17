# Q Station production workflow

`q_station` is the canonical project id. `q_station` is accepted only as a compatibility alias.
The panel launches `run_full_video_pipeline_q_station_wrapper.py`, which runs the creative/visual half,
narration/music/alignment, opening trim, then timeline/render/QC/delivery.

## End-to-end data flow

```text
launch topic + frozen config
  -> character + presentation resolution
  -> opening_concept: three mini-stories + independent selection
  -> script draft -> retained SCRIPT_CORE_PLAN
  -> episode direction + blocking opening story review
  -> final CTA -> SCRIPT_PLAN + SCRIPT_FINAL
  -> topic-world style plan + pre-CTA visual plan
  -> continuous narration + real word alignment + opening source plan
  -> style anchor + host-free world keyframe + configured entry frame
  -> sequential body images + Flow Intro A/B with measured timing
  -> measured trims -> shared timeline/render/QC/delivery
```

## Identity, scenario and style

- `characters/<id>/character.json` selects a `presentation_profile` and owns only identity, behavior,
  selection traits and its canonical character sheet.
- `presentation_profiles/<id>/profile.json` owns the fixed two-intro progression, entry mechanism,
  prompt fragments and episode artifact names.
- `WORLD_STYLE_PLAN.json` owns the topic world's medium, palette, texture, lighting and frame language.
  It must not redesign the host or recurring entry object.

`book_portal` preserves the existing red/red_host workflow: varied question scenario → storybook →
topic-styled closed cover → opening/page turn → enter the topic world. Its historical artifact names
remain unchanged.

`orb_portal` implements: varied question scenario → crone's orb → a readable crone ownership/agency
cue (hand, fingers, moss-green sleeve, shadow/reflection or raven) → the orb interior gradually adopts
the topic/style visual language → camera enters the same host-free world keyframe. Its artifacts are
explicitly orb-named.

## Durable state and compatibility

New runs write `creative/PRESENTATION_RESOLUTION.json` beside `CHARACTER_RESOLUTION.json`. The profile
id/version, entry kind, narration key and artifact contract are frozen. Runs without that file predate
multi-presentation support and resolve to `book_portal`; no file is written merely by reading them.

Stage IDs `flow_prompt_a/b`, `flow_clip_a/b`, `book_design_sheet`, `book_cover_design` and
`book_cover` are retained as durable compatibility IDs. `run_graph.q_station_node_specs()` gives them truthful
profile-aware titles and artifacts. This prevents migration of completed state while keeping runtime
behavior data-driven. A deliberate character change through Revise is versioned: the prior character
and presentation branch is archived, their persisted resolutions are invalidated, and resolution plus
all script/opening/downstream consumers rebuild under the newly requested character.

Character resolution now precedes writing new narration so the script uses the correct entry segment.
Book runs retain `book_transition`; orb runs use `entry_transition`. The aligner accepts both and writes
the chosen key into `OPENING_TIMING.json`. Everything after `opening_trim` is presentation-agnostic.

The image contract is one-to-one: every `body` entry owns one still image and a non-empty
`optional_closing` owns one additional final still. CTA is the only allowed exception and may remain
on the closing image. The planner validator checks exact ordered narration slices, the Markdown
handoff preserves all units, the aligner verifies current beat text before reuse, and the graph marks
older plans without the closing beat as `STALE` while exposing the missing beat node.

## Reference policy

- Intro A: Flow Ingredients = `character_sheet` only.
- Intro B: Flow Frames = `first_frame` (entry frame) + `last_frame` (world keyframe).
- Gemini entry-frame generation receives `entry_identity`, `style_reference`, and—only when the
  profile declares `ownership_cue`—`character_sheet`.
- Flow never receives style anchors. Frames and Ingredients remain mutually exclusive.

## Panel and regeneration

The character catalog returns each character's presentation name, shown in the selector. The graph,
status, prerequisites, descendant calculation, retry/resume and invalidation all consume the same
profile-aware `NodeSpec` mapping. Changing world style cascades through the entry frame and Intro B;
body timing/render stages do not become character-aware. Revise exposes character selection and shows
the full impact before applying it; changing a character intentionally starts at `character_resolution`
inside the same versioned run, while a topic change still creates a separate run.

## Canonical prompts and assets

Active Q Station prompts are enumerated by `Q_STATION_PIPELINE_PROMPTS` in `scripts/content_projects.py`,
including the opening designer, independent candidate reviewer and story-consistency reviewer. Presentation-specific
rules are under each `presentation_profiles/<id>/prompts/`. The crone sheet is
`characters/moss_cloaked_crone/refs/character_sheet.jpg` and is the only visual identity authority for
that character. The orb design sheet is generated once, on first real orb run, from its identity-only
prompt and then receipt-verified/reused. This lazy generation avoids spending provider credits during
configuration or tests.

## Validation commands

```bash
.venv/bin/pytest -q tests
npm --prefix control_panel/ui test -- --run
npm --prefix control_panel/ui run build
```

Provider-free coverage validates profiles, prompt assembly, legacy book fallback, orb artifact paths,
DAG propagation, stage ordering, state/resume and panel catalog behavior. A real Gemini/Flow smoke is
deliberately not part of unit tests because it spends credits and requires authenticated browser state.

## Opening quality and deployment

See [OPENING_STORY_PIPELINE.md](OPENING_STORY_PIPELINE.md) for the v2 decision contract, semantic
history, panel invalidation and provider-free deployment checks. New opening rules are enabled for
new runs on dev without changing character sheets, artifact names or provider input roles.
