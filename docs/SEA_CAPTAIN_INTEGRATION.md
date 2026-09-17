# Curious Sea Captain: operator setup and integration contract

The `sea_captain` pack uses `spyglass_portal` in Q Station. It is additive: the farmer,
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
`red_horned_everyman` / `farmer_host`.

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

A uses the selected mini-story from frame zero, one location and at most three clear actions.
It ends with a compatible eyepiece handoff. B begins on the generated eyepiece close-up:
the barrel points away, and a small actual hand/blue-cuff cue makes ownership clear. A and B
are separate clips with an editorial seam, not guaranteed continuous pixels.

A restrained forward push through the lens reveals the subject-world clue. The final
keyframe contains no host, hand, spyglass, circular mask or opening setting. The viewer's
**gaze** enters the world; the captain is not forced bodily into the endpoint. His voice
continues; later stills may include him only through the existing `hero_present` and
host-presence policy. The first body unit pays off the opening; later units explain it.
An optional closing may echo the opening; CTA does not replace the answer.

- Character identity: this pack's canonical sheet and appearance/behavior/negative prose.
- Recurring object: `spyglass_portal/refs/spyglass_design_sheet.png`, generated lazily by the
  existing non-book identity stage on the first real run, quality-reviewed and receipt-verified.
  No second asset needs manual installation. It is a shared object asset, not episode-owned.
- Gemini entry frame: `entry_identity`, `style_reference`, `character_sheet`.
- Flow A: only `character_sheet` in Ingredients mode.
- Flow B: only `first_frame` + `last_frame` in Frames mode. Never a style or character ingredient.
- World keyframe: topic-world references only, no character sheet or entry identity.
- Narration: existing `opening_question_spark` + `entry_transition`; no new spoken segment key.
- Timing: actual word alignment and supported source lengths drive trimming, not a fixed 6+4 edit.
- Body: one image per body unit, plus one for non-empty `optional_closing`; no extra CTA image
  or third Flow clip. Art style belongs to the topic world, not the captain's costume.

The profile names episode outputs `spyglass_entry_frame.png`,
`flow_prompt_spyglass_transition.txt`, `spyglass_transition_source.mp4`,
`spyglass_transition_trimmed.mp4`, `SPYGLASS_ENTRY_DIRECTION.txt` and
`gemini_spyglass_entry_frame.json`. The existing profile-aware gate, graph, trim, timeline,
resume and invalidation code resolves these paths. Internal `book_*` compatibility stage
IDs are deliberately retained. No existing `videos/` media or frozen resolution is migrated.

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
