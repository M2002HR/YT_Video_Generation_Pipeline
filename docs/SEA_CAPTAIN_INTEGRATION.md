# Curious Sea Captain: current setup and optical-entry contract

The `sea_captain` pack belongs to Q Station and uses `spyglass_portal`. It uses the shared
character resolver, three-premise opening selection, independent review, timing, media,
revision and completion pipeline. It is not restricted to maritime questions or locations.
Current four-host mappings and deployment details are in `CHARACTER_GATEWAYS.md`.

## Operator-owned character image

Install the complete approved turnaround at this exact repository-relative path:

```text
projects/q_station/characters/sea_captain/refs/character_sheet.png
```

Use a real single-frame PNG, at original proportions/resolution. No portrait crop, transparent
background or replacement artwork is required. Both edges must be at least 256 pixels and the
file at least 10,000 bytes. A renamed JPEG is rejected. Preserve an already-installed valid
sheet; this update changes optical staging, not the captain's identity.

Upload to `character_sheet.upload.png`, then rename atomically while no generation is active.
Do not use `git clean -x` on a production checkout. Check readiness from repository root:

```bash
.venv/bin/python scripts/check_character_setup.py --character sea_captain
.venv/bin/python scripts/check_opening_setup.py
```

These checks are read-only and do not call paid providers. Missing/corrupt operator artwork
excludes only the pack from selectable characters/Auto candidates. Explicit manual/resume
requests fail with the installation reason, never silently switching hosts. The registry
notices file replacement, old-mtime uploads, corruption and removal. Restart installed panel
services after deployment; do not replace artwork during a run.

## Topic-first scenario selection

A begins with the actual topic's observation, comparison, misleading impression, pattern or
consequence. One setting, at most three actions; no required ship, treasure, sea, chore or
catchphrase. The six allowed entry strategies are `near_detail`, `far_target`,
`two_object_compare`, `trace_to_cause`, `changed_viewpoint` and `pattern_inspection`. These guide
a topic-specific story, not a rotation of stock scripts. The common selector authors three
different premises and independently reviews feasibility, honesty, novelty and payoff.

B and the first body unit supply the promised explanatory clue. A change of scale is an
editorial visualization, not a claim that an ordinary telescope proves hidden scientific facts.

## Corrected first frame and camera

B starts with actual optical use in a mildly oblique side/rear-three-quarter view. The SMALL
narrow rear eyepiece is beside the visible unpatched eye. The connected barrel extends AWAY
from the face to the physically LARGER front objective, aimed toward the observed subject.
Both ends, the eye relationship and a plausible supporting grip must be legible. Preserve the
canonical face, patch side, hat, beard and blue cuff. A dominant circular lens and anonymous
cuff do not establish the correct direction.

The camera makes one restrained matched handoff into the captain's outward-looking viewpoint,
then reveals the subject world. It never flies backward through the objective into his face,
reverses the telescope or shows an eye inside its tube. Finish essential action inside the
measured B narration boundary; hold the supplied last frame for any remaining source tail.
The endpoint has no host, spyglass, brass rim or circular mask. Body/closing stills are full-bleed
world scenes, not pages or lens-framed illustrations.

The first real updated run generates the shared `spyglass_design_sheet_v2.png` under the profile's
`refs/`, with a verified provider/content receipt. No manual object image is needed. The original
sheet/receipt remain historical provenance. Generation of the new shared identity consumes the
usual provider credits once; verified reuse avoids repeating it.

Gemini entry-frame references are `entry_identity`, `style_reference`, `character_sheet` and the
actual `world_keyframe`. Flow A receives only the character ingredient; Flow B receives only
first_frame and last_frame. New optical review requires boolean checks plus visible evidence.
Reversal, hidden/ambiguous endpoints or an invalid grip are blocking defects, not minor warnings.
No correction setting or stale permissive receipt can certify the new entry geometry.

## Existing runs and acceptance

Deployment does not modify old episodes or their pixels. To repair an already-built captain
opening, explicitly regenerate the corrected entry identity/frame and dependent B animation.
Prompt/input hashes and review contracts prevent silent reuse of the old reversed frame/clip.
An approved old premise may be retained under verified rollout compatibility; an editorial or
character change still needs explicit Revise. Rebuilding media can spend credits.

```bash
.venv/bin/python -m pytest -q tests/test_operator_character_assets.py tests/test_sea_captain_integration.py tests/test_gateway_visual_contracts.py tests/test_gateway_resume.py
```

Tests use temporary fixtures and provider spies. Inspect the first actual production start frame
and clip for small-eyepiece-at-eye orientation, unchanged identity/grip, a coherent A/B handoff,
outward-view camera motion and a host-free full-bleed endpoint. Offline CI does not validate live
browser authentication, credits, provider availability or the final generative animation.
