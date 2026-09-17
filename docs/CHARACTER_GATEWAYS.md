# Q Station: four character gateways and full-bleed topic worlds

## Operator installation

Only the new Newton-inspired character sheet needs manual installation. Export the complete
approved turnaround as a real single-frame PNG, keeping original proportions and resolution:

```text
projects/q_station/characters/newton_scholar/refs/character_sheet.png
```

Both edges must be at least 256 pixels and the file at least 10,000 bytes. Renaming a JPEG is
not conversion. No image or placeholder is committed. The locally ignored PNG cannot be
replaced by a normal pull. Upload to `character_sheet.upload.png`, then rename atomically.
Do not replace artwork while a generation job is active.

Deploy in an idle production checkout, preserving local edits, `.env`, sessions and media:

```bash
git status --short
git fetch origin --prune
git switch dev
git pull --ff-only origin dev
# Install the operator PNG at the path above before the selected-character check.
.venv/bin/python scripts/check_character_setup.py --character newton_scholar
.venv/bin/python scripts/check_opening_setup.py
sudo systemctl restart video-control-panel.service video-control-panel-websocket.service
```

Use your installed service names if different. No new production dependency or provider key
is needed. Readiness checks do not call providers. Missing/invalid Newton artwork removes only
that character from the selectable catalog and Auto candidates; an explicit request fails
with the reason, never silently changing hosts. Auto remains topic-dependent; select a host
manually for first acceptance. The captain's already-installed sheet is not modified.

## New-run mappings

| Character | Gateway | Segment |
| --- | --- | --- |
| `red_horned_everyman` | `red_door_portal` | `entry_transition` |
| `moss_cloaked_crone` | `orb_portal` | `entry_transition` |
| `sea_captain` | `spyglass_portal` | `entry_transition` |
| `newton_scholar` | existing `book_portal` | `book_transition` |

Newton is a fictional scholar inspired by Newton, not a judge, historical reenactment or
infallible authority. The operator sheet owns identity; no automatic apple/gravity routine,
courtroom or library setting. His small ordinary accessory book is not the existing canonical
portal book. The book pipeline and its assets remain intact; no duplicate implementation.

## Topic-first stories and camera

The common selector still authors exactly three genuinely different premises and independently
reviews topic fit, factual honesty, feasibility, novelty and payoff. Gateways do not substitute
for premises. Every A starts with the question-triggering event, one place and up to three actions.

The red door has fixed vermilion panels, charcoal frame, front-right brass ring and front-left
hinges. It may occupy a wall, stable freestanding frame, existing exit, recess, unexpected
supported surface or a floor hatch. B starts with the host beside the almost-closed door, then
notice/open, visible intentional crossing, camera arrival. Door geometry must clear both horns.
Floor variants need supported descent and matching camera tilt. `entry_camera` records surface,
transition, attention cue, opening action, crossing action, camera path and world reveal. The
reviewer checks the route and the first-frame reviewer checks supporting-plane geometry.

Choose one path: follow-through, threshold dissolve or texture takeover. The latter two occur
AFTER the actor visibly crosses; a fade is not a substitute for the required action. The first
frame contains a real topic-textured glimpse through the aperture, not a painted poster/white
void. The last frame has no host, door, enclosing frame or lens mask. Later host presence remains
controlled by body `hero_present` decisions.

Door B has a 13-word minimum and a five-second measured minimum. Writers target 13-18 meaningful
spoken words and roughly 5-8 seconds, not filler or narration of stage directions. Actual word
alignment chooses the supported source duration. Too-short B fails before paid visual media;
revise the entry narration, because extending a source alone would still trim away its ending.
All camera prompts require important action to finish before the measured trim boundary.

## Captain orientation: audited cause and fix

In run 038, the image reviewer explicitly reported the broad objective facing the viewer with
the narrow eyepiece away, but accepted it as a non-blocking observation. The old first-frame
brief requested an eyepiece-facing close-up while also demanding a dominant circular lens and
only an anonymous hand/cuff. That made the optical endpoints ambiguous.

New frames establish actual use in oblique side/rear-three-quarter view: small eyepiece at the
visible unpatched eye, barrel extending away, wider objective toward the subject, and a plausible
grip. B matches into the outward-looking viewpoint, never flies backward into the face. A new
shared `spyglass_design_sheet_v2.png` is generated with a verified receipt on demand, keeping the
old sheet/receipt for provenance. No second manual image is required. The red door identity is
also generated lazily. Those first-run image generations consume the usual provider credits.

Geometry is a hard visual contract, not polish: every required check needs a boolean and visible
evidence. Missing, ambiguous or failed checks cannot be accepted even under correction policy 0.
Bounded correction uses the existing provider/recovery settings; no fabricated success receipt.

## Full-bleed world/body contract

The other run-038 defect came from shared world-style and per-beat instructions that explicitly
required an outer parchment/page material and an inner illustration window. Its saved style plan
then repeated that border across the episode. The pipeline profile name by itself was not the cause.

The new rendering projection keeps topic medium, palette, grain and lighting, but replaces old
page-frame metadata with an edge-to-edge scene. Paper-cut, ink, manuscript-like markmaking and
collage remain legitimate media; no enclosing book, card, gutter or inset layout is inherited.
A topic-relevant physical book can still exist INSIDE a scene. The same rule applies to Newton.
Opening choreography is excluded from body character context and world-script inputs. Body
references remain host sheet only when needed, neutral style, host-free keyframe, optional
operator style, and prior beat for texture/palette rather than border/composition.

The generated anchor, world keyframe and new body stills receive explicit pixel-review criteria.
The operator's existing option to disable BODY content QC remains respected and is visibly recorded;
it does not disable entry geometry checks. Prompt rules still apply when body QC is disabled.

## Resume, caching and regression boundaries

Deployment does not rewrite any existing `videos/` files or paid media. A saved presentation stays
authoritative: an old red-host/book episode continues using its book segment and paths. New runs
select the new mapping. To move an existing episode to the new gateway, use explicit character
Revise, which clears both resolutions and dependent creative/media stages; do not edit JSON by hand.

Changed frame/prompt inputs invalidate their corresponding caches. New marked contracts require
matching reviewed evidence; old 'passed with warnings' receipts cannot certify them. Flow receipts
bind actual input image hashes so a regenerated start frame cannot silently reuse the old clip.
Existing unmarked historical artifacts remain visible; they are not retroactively claimed to pass
new geometry/layout review. Regenerating an affected branch can spend credits. For a page-framed
existing video, regenerate world style/keyframe and dependent body images together, not a mix of
old bordered references and a single repaired beat. Inspect run 038 manually before spending.

The durable internal `book_*` stage identifiers and historical pipeline-profile identifier remain
compatibility names. They do not supply page-layout semantics. Crone, timings, subtitle settings,
provider choices, completion/publishing order and existing run data are not replaced.

## Acceptance

Run the Python regression suite, UI tests/build and opening preflight before deployment. Tests
use temporary image fixtures/provider spies and never install pixels in source packs. A successful
CI run is not a real Gemini/Flow smoke: inspect the first production clips for optical orientation,
horn/hinge clearance, visible crossing, temporal seam, target-world reveal and complete removal of
page framing. Browser auth, service state, credits and generative video consistency require that
server-side acceptance with the actual operator sheet.


### Pre-rollout approved stories
An approved pre-rollout opening context can retain its existing premise when only gateway/acting
prose changes in this release. Both stored input and selected-concept hashes must verify; editorial
brief, duration, character identity, gateway identity, selector prompts and language policy must
still agree. Nothing in the frozen context is rewritten. New contexts carry a version marker and
cannot use this compatibility path. This is NOT acceptance of an old reversed or page-framed image:
regenerated media must pass the current geometry/layout review. A real editorial or character
change continues to require explicit Revise.
