# Curious Sea Captain: operator setup and integration contract

The `sea_captain` pack uses `spyglass_portal` in Q Station. It is additive: the red_host,
red host, crone, book/orb profiles, provider locks, release/thumbnail pipeline and
legacy stage IDs are unchanged. There is no captain-specific branch in orchestration.

## Install the one operator-owned asset

The only manual asset is the supplied character turnaround. Export/copy it as a real,
single-frame **PNG** at this exact, case-sensitive path from the repository root:

```text
projects/q_station/characters/sea_captain/refs/character_sheet.png
```

Keep the complete original sheet at its original resolution (the supplied 1408 x 1056
sheet is suitable). No 9:16 crop or transparent background is needed: this is an identity
reference, not an episode frame. The file must decode as PNG, have both edges at least
256 pixels, and be at least 10,000 bytes. Merely renaming a JPEG to `.png` is rejected.
No character sheet, placeholder artwork or fabricated provider receipt is shipped.
The file is locally ignored by Git so later pulls cannot overwrite operator artwork.
Do not run `git clean -x` on a production checkout.

Deploy only when no generation job is running. In the actual server checkout (adjust the
example installation directory), review local changes before pulling; never force-reset
`.env`, generated episodes, service configuration or submodules:

```bash
cd /opt/YT_Video_Generation_Pipeline
git status --short
git fetch origin --prune
git switch dev
git pull --ff-only origin dev

# Upload to this temporary filename first, then atomically rename after upload finishes.
# The source path below is the operator's exported PNG.
install -m 0644 /path/to/exported-character-sheet.png \
  projects/q_station/characters/sea_captain/refs/character_sheet.upload.png
mv projects/q_station/characters/sea_captain/refs/character_sheet.upload.png \
  projects/q_station/characters/sea_captain/refs/character_sheet.png

.venv/bin/python scripts/check_character_setup.py --character sea_captain
.venv/bin/python scripts/check_opening_setup.py
sudo systemctl restart video-control-panel.service video-control-panel-websocket.service
```

Use your deployed service names if they differ. No new production dependency, API key,
provider, UI build, Ordak service rename or submodule branch change is required.
The existing Pillow dependency is used to verify the operator image.

The selected-character preflight must print `READY: Curious Sea Captain (sea_captain)`.
It is read-only and does not spend credits. The general opening preflight still works
before the new sheet is installed, because existing characters remain available.

## Availability and first launch

The character is registered with `references.provisioning: "operator"` and still has
`required: true`. Only these explicitly operator-provisioned packs defer missing/invalid
artwork. Bundled packs retain their historical strict missing-reference behavior.

Before the image is ready, the captain is excluded from the selectable catalog and Auto
candidate list. Other characters continue working. Explicit manual/resume requests for an
unready captain fail with the installation/validation reason; they never silently become
a different host. Invalid pack configuration or missing prompt files still fail loudly.
A missing operator pack cannot be configured as the Auto fallback or legacy default.

The registry cache tracks the path set, mtime, ctime and size. An upload preserving an
old mtime, an atomic replacement, corruption or removal is noticed on the next registry
load. Services should nevertheless be restarted after deployment. Do not change artwork
during an active job. For an existing episode, use the panel's explicit Revise operation
rather than editing frozen resolution files.

Start a **new video**, choose **Curious Sea Captain** manually, and enter any supported
question with a clear editorial brief and source notes. Its presentation label is
`Question -> Captain's Spyglass -> Topic World`. Auto remains topic-dependent; merely
adding this pack does not make it the default. Existing fallback/legacy defaults stay
`red_horned_everyman` / `red_horned_everyman`.

## Topic-first scenario selection

This pack uses the existing `opening_concept` stage, not a new hand-coded topic router:
three genuinely distinct premises, independent review, deterministic ranking of eligible
candidates, bounded text-only corrections, frozen history and the existing story review.
It is not restricted to maritime subjects. Identity stays fixed; topic determines location,
evidence, tension and payoff. A spyglass does not force an ocean, ship, treasure hunt,
nautical metaphor, chore or opening catchphrase into every episode.

The profile declares six allowed staging strategies:

| Variant | Use |
| --- | --- |
| `near_detail` | Inspect an ordinary detail that matters to the question. |
| `far_target` | Isolate distant, topic-relevant evidence. |
| `two_object_compare` | Contrast outcomes or apparently similar objects. |
| `trace_to_cause` | Move from an observed consequence toward its explanation. |
| `changed_viewpoint` | Reconsider a misleading first impression. |
| `pattern_inspection` | Follow a meaningful repetition or arrangement. |

These are guidance for selection, not six fixed scripts or a rotation. The author chooses
from the actual topic/brief, and the reviewer can reject every proposal. Facts, metaphors
and thought experiments remain distinct. The spyglass transition never makes an impossible
optical effect into scientific evidence. Plain-English, honesty, novelty and payoff checks
remain enabled; an appropriate scenario for every conceivable prompt is not guaranteed.
Unsupported claims must be qualified, redesigned or rejected before paid media.

## Visual and runtime contracts

For current new runs, B begins with actual optical use in an oblique side/rear-three-quarter
view, not a dominant circular lens and anonymous cuff: small eyepiece at the visible unpatched
eye, wider objective aimed away toward the subject. Both ends, connecting barrel and plausible
grip must be visible. The camera matches into his outward-looking viewpoint, then reveals the
world. Optical reversal or uncheckable orientation is a blocking visual defect.

The shared object is generated lazily as `spyglass_design_sheet_v2.png`; it is not a second
manual asset. The old identity remains only as historical provenance. Gemini entry-frame
references are entry_identity, style_reference, character_sheet and the generated world_keyframe.
Flow A receives only the character ingredient; Flow B receives only first_frame and last_frame.
The endpoint and all body images are full-bleed topic-world scenes, without enclosing page edges
or persistent lens masks. Actual narration alignment governs the edit.

See `docs/CHARACTER_GATEWAYS.md` for four-host mappings, review/caching requirements, existing-run
revision and the server acceptance checklist. Existing operator artwork is not overwritten.

## Validation and first paid smoke

```bash
.venv/bin/python -m pytest -q tests/test_operator_character_assets.py tests/test_sea_captain_integration.py
.venv/bin/python -m pytest -q tests
npm --prefix control_panel/ui test -- --run
npm --prefix control_panel/ui run build
```

Tests use temporary fixture pixels and provider spies only. They exercise readiness,
old-mtime installation/removal/replacement, manual/Auto/resume, frozen independent scenario
selection across different topic inputs, rejection paths, reference roles, canonical receipt
reuse, narration keys, timing input contracts, DAG/invalidation and old book/crone mappings.
They never install test pixels in the source checkout or call paid providers.

After installing the real sheet, inspect the first real video's entry identity and A/B seam:
correct eye/peg-leg sides, same spyglass geometry, visible ownership, no eye inside the tube,
no host/spyglass at the world endpoint, and an actual answer to the opening question.
Start with a simple readable comparison. The first run also pays for the shared spyglass
identity. An unrelated second topic checks that maritime scenery is not forced.

Offline/CI success cannot verify browser login, account credits, current provider availability,
visual model consistency or audience retention. An authenticated Gemini/Flow smoke with the
real operator sheet is the final production acceptance step. Never manufacture a success
receipt or placeholder when a provider fails; use the existing recovery workflow.


## Gateway update

For new runs, the red host uses `red_door_portal`, the Newton-inspired scholar uses the existing `book_portal`, the crone keeps `orb_portal`, and the captain uses the corrected optical-use `spyglass_portal`. Topic-world images are full-bleed, not enclosing pages. Earlier operational examples describe frozen historical runs; current installation, camera/QC contracts and revision guidance are in `docs/CHARACTER_GATEWAYS.md`.
