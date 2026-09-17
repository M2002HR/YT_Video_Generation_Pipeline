# Q Station production workflow

`q_station` is the only supported content project; it has no project aliases. The panel launches
`scripts/run_full_video_pipeline_q_station_wrapper.py`, with creative/media stages in
`scripts/run_q_station_pipeline.py`. The completion pipeline saves, renders and publishes before
its final scoped Git artifact commit/push; that operator workflow is unchanged.

## End-to-end data flow

```text
question + frozen launch configuration
  -> character + presentation resolution
  -> three distinct opening premises + independent selection
  -> script draft -> retained SCRIPT_CORE_PLAN
  -> episode direction + blocking story review
  -> final CTA -> SCRIPT_PLAN + SCRIPT_FINAL
  -> topic-world style plan + pre-CTA visual plan
  -> continuous narration + real word alignment + supported source-length plan
  -> neutral style anchor + host-free world keyframe + configured entry frame
  -> Flow Intro A/B + topic-world body and optional-closing stills
  -> measured trims -> timeline/render/QC/delivery
  -> final scoped Git artifact commit/push
```

## Identity, gateway and art direction

Character packs own identity, behavior, selection traits and canonical reference. Presentation
profiles own opening rules, recurring entry mechanism, prompt fragments and artifact names.
`WORLD_STYLE_PLAN.json` owns the topic's medium, palette, texture and lighting, not host anatomy or
entry-object design. `scripts/gateway_contracts.py` supplies rendering and geometric acceptance rules.

| New-run character | Presentation | Narration segment |
| --- | --- | --- |
| Red Horned Everyman | `red_door_portal` | `entry_transition` |
| Moss-Cloaked Crone | `orb_portal` | `entry_transition` |
| Curious Sea Captain | `spyglass_portal` | `entry_transition` |
| Newton-Inspired Scholar | `book_portal` | `book_transition` |

A visibly establishes why THIS question arises in one place and at most three clear actions.
B uses the profile-specific gateway and ends on a host-free topic world. The existing book
mechanism/assets are reused for Newton; his small accessory book is not automatically that gateway.
The crone keeps her orb ownership cue. Captain B establishes actual correct optical use before
matching into his outward-looking viewpoint. Red-door B starts beside an almost-closed door, then
notice/open, visible physical crossing, and camera arrival. Its declared surface and route must agree.

The red door supports follow-through, threshold dissolve and texture takeover. Any dissolve or
expansion follows the visible crossing; it cannot hide a missing action. Its entry segment has a
13-word minimum and five-second measured minimum, with supported source lengths selected after
real narration alignment. Too-short timing fails before visual generation; lengthening a source
alone would not prevent the final edit from cutting away the crossing.

## Full-bleed world and body

The viewer is INSIDE the explanatory world, not looking at a picture on an enclosing page.
World keyframe, body stills and optional closing extend to all four edges. No enclosing book/card,
page border, gutter, binding, inset illustration window, doorway rim or persistent lens mask.
Paper grain, ink, manuscript-like markmaking and collage remain valid artistic treatments; a real
book can be a topic-relevant object inside a scene. Old catalog/reference border metadata is not a
continuity requirement. With subtitles enabled only the bottom 8-10% is naturally quiet; without
them the scene uses the full height. No embedded labels or printed captions.

Every body unit owns one still; non-empty `optional_closing` owns one additional final still. CTA
alone may stay on that final image. Narration slices, beat counts and ordering are validated, then
aligned to actual speech. Opening choreography is not passed to the body/world planners as identity
or factual script context.

## Provider reference policy

Flow A uses Ingredients mode with the selected character sheet only. Flow B uses Frames mode with
exactly first_frame and last_frame; it never receives an extra style or character ingredient.
Gemini bakes required identity into the entry frame. Book entry remains host-free; orb entry uses
its identity, style and ownership-character references. Acting-host entries (red door and spyglass)
use entry_identity, style_reference, character_sheet and the actual world_keyframe. Their graph
therefore includes a world-keyframe dependency for entry-frame regeneration.

Optical orientation, doorway route/initial state and full-bleed scene layout have explicit pixel
review rubrics. Required checks must contain booleans and visible evidence. Missing, ambiguous or
failed geometry cannot be demoted to a non-blocking polish warning, including correction policy 0.
The existing operator option to disable BODY content QC remains respected and recorded; it does not
waive entry geometry. Provider failures still use bounded correction/recovery, never placeholder media.

## Durable state, caching and revision

`creative/PRESENTATION_RESOLUTION.json` freezes profile ID/version, entry kind, segment and artifact
contract beside character resolution. A saved old red-host/book episode does not acquire the new
door mapping on resume. Runs without presentation state predate that contract and keep the historical
book fallback. Corrupt saved presentation state fails loudly, not by silently substituting a host.

Internal `book_*` stage IDs and `bookworld_mixed_media` remain compatibility identifiers, not page-layout
instructions. The panel, graph, trim and timeline resolve profile-specific paths/titles. Explicit
character Revise archives the old resolution/media branch, clears both authorities and invalidates
all dependent creative/media stages. A changed question creates a separate run.

Prompt caches bind current rules, script/style/camera inputs and output hashes. New visual contracts
require matching reviewed evidence; old permissive receipts do not certify corrected frames. Flow
receipts bind input image hashes, preventing a changed entry frame from reusing its old animation.
Verified pre-rollout opening contexts may retain approved premises across this release's prose changes
only under the strict compatibility checks in `gateway_resume.py`; changed editorial/identity inputs
still require Revise. Retaining a premise does not certify its old media under new geometric rules.

Deployment itself does not rewrite `videos/`, operator images or paid receipts. To correct an old
page-framed episode, revise the world-style/keyframe branch and dependent stills together. To repair
an old captain entry, regenerate the corrected identity/entry frame and dependent B clip. These real
provider operations can spend credits; opening a preview or running preflight cannot repair old pixels.

## Installation and validation

Newton's full turnaround is operator-installed as a real single-frame PNG at
`projects/q_station/characters/newton_scholar/refs/character_sheet.png`. Missing/invalid operator
artwork excludes only that pack from selection; explicit requests report the reason. Red-door and
corrected spyglass object sheets are generated lazily with verified receipts, not manually installed.

```bash
.venv/bin/python scripts/check_character_setup.py --character newton_scholar
.venv/bin/python scripts/check_opening_setup.py
.venv/bin/python -m pytest -q -rs tests
npm --prefix control_panel/ui test -- --run
npm --prefix control_panel/ui run build
```

See `CHARACTER_GATEWAYS.md` for PNG requirements, complete camera contracts, deployment/restart and
first paid acceptance. See `OPENING_STORY_PIPELINE.md`, `SPOKEN_ENGLISH_POLICY.md` and
`RECOVERY_RUNBOOK.md` for the shared creative, language and recovery contracts. CI validates software
with isolated fixtures; authenticated Gemini/Flow output on the actual server still needs visual
acceptance for character consistency, physical crossing, optical use and camera motion.
