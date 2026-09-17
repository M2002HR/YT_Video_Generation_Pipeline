# Q Station

Q Station is the sole content project in this repository. It produces short English question-driven videos with a topic-first opening, continuous narration, generated topic-world imagery, and a two-clip entry transition.

## Hosts

- `red_horned_everyman` — `book_portal`
- `moss_cloaked_crone` — `orb_portal`
- `sea_captain` — `spyglass_portal`

Host identity is resolved from `characters/registry.json`; presentation mechanics are resolved from `presentation_profiles/`. Topic-world style is independent of host identity. The red host is both automatic fallback and compatibility default.

Runtime entry points are `scripts/run_q_station_pipeline.py` and `scripts/run_full_video_pipeline_q_station_wrapper.py`. See `docs/Q_STATION_PIPELINE.md`, `docs/OPENING_STORY_PIPELINE.md`, `docs/SPOKEN_ENGLISH_POLICY.md`, and `docs/SEA_CAPTAIN_INTEGRATION.md`.
