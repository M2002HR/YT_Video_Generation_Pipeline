# Q Station

Q Station is the sole content project in this repository, with no project aliases. It produces English question-driven videos with a topic-first opening, continuous narration, two opening clips and full-bleed explanatory-world imagery.

## New-run hosts and gateways

| Character | Presentation |
| --- | --- |
| `red_horned_everyman` | `red_door_portal` |
| `moss_cloaked_crone` | `orb_portal` |
| `sea_captain` | `spyglass_portal` |
| `newton_scholar` | existing `book_portal` |

Identity comes from `characters/registry.json`; gateway mechanics from `presentation_profiles/`; topic-world medium and palette are independent of both. Auto remains topic-dependent, with the red host as fallback. An operator-provisioned character is selectable only after a valid sheet is installed. The new Newton PNG is deliberately absent from Git; its exact path and validation are in `docs/CHARACTER_GATEWAYS.md`.

A shows why the question arose. B uses the selected gateway and arrives at a host-free world keyframe. The red door includes visible actor crossing and a declared camera route. The captain's small eyepiece stays beside his visible eye while the larger objective points toward the subject. Body/closing images fill the canvas, without enclosing book pages, doorway rims or lens masks; paper grain and other artistic media remain valid.

Saved presentations stay authoritative for historical runs, including earlier red-host/book episodes. Explicit character Revise owns changing that mapping and its downstream artifacts. Deployment does not rewrite existing media.

Canonical runtimes are `scripts/run_q_station_pipeline.py` and `scripts/run_full_video_pipeline_q_station_wrapper.py`. Read `docs/Q_STATION_PIPELINE.md`, `docs/CHARACTER_GATEWAYS.md`, `docs/OPENING_STORY_PIPELINE.md`, `docs/SPOKEN_ENGLISH_POLICY.md` and `docs/RECOVERY_RUNBOOK.md`.
