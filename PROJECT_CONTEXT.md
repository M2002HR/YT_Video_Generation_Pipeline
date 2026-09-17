# Q Station - current architecture

Only the `q_station` content project is supported. Character identity, opening presentation,
and per-episode topic-world art direction are separate contracts.

| Character | New-run presentation |
| --- | --- |
| Red Horned Everyman | `red_door_portal` |
| Moss-Cloaked Crone | `orb_portal` |
| Curious Sea Captain | `spyglass_portal` |
| Newton-Inspired Scholar | `book_portal` |

The Newton sheet is operator-provisioned; see `docs/CHARACTER_GATEWAYS.md` for its exact PNG path,
preflight and deployment. Missing artwork does not disable ready packs. A frozen episode's
presentation remains authoritative across registry changes; explicit character Revise is the
controlled way to change both character/presentation and dependent media.

## Entry points and invariants

- `scripts/video_control_panel.py`, `control_panel/ui/`: launch, preview, revision, recovery.
- `scripts/run_full_video_pipeline_q_station_wrapper.py`: narration/alignment before visual media.
- `scripts/run_q_station_pipeline.py`: three independent opening candidates/review, text, art and media.
- `scripts/character_runtime.py`: WHO; `scripts/presentation_runtime.py`: gateway HOW.
- `scripts/gateway_contracts.py`: full-bleed layout, optical/threshold review, camera/timing requirements.
- `scripts/run_graph.py`, `scripts/pipeline_stages.py`: profile-aware dependencies and invalidation.
- `scripts/plan_opening_sources.py`: supported Flow lengths from real narration boundaries.
- `scripts/run_completion_pipeline.py`: complete/save/publish first, commit run artifacts last.
- `scripts/commit_video_artifacts.py`: owns the run and its actually-used shared style/entry assets.

Flow A has only the character ingredient; Flow B has first_frame and last_frame only. Gemini
bakes any necessary actor identity into the first frame. The endpoint is always host-free.
Body images are full-bleed topic-world scenes, never enclosing pages inherited from the gateway.
Paper grain/ink/collage remain artistic media; a book may be a factual in-world object.

Keep existing provider selection, bounded correction/alternation, user body-QC opt-out, narration,
CTA/language policies and publishing settings. Hard entry geometry cannot be waived as a minor
warning. Review actual pixels, preserve provider receipts, and never manufacture successful media.
Internal book stage IDs and historical pipeline-profile names remain compatibility identifiers,
not rendering rules. Deployment does not rewrite existing videos or operator artwork.

See `docs/Q_STATION_PIPELINE.md`, `docs/OPENING_STORY_PIPELINE.md`, `docs/RECOVERY_RUNBOOK.md`,
`docs/SPOKEN_ENGLISH_POLICY.md` and `docs/CHARACTER_GATEWAYS.md`.
