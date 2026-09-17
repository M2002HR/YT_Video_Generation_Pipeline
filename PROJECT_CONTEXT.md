# YT Video Generation Pipeline — Q Station architecture

The repository has one active content project: `q_station`. There are no project aliases.

## Canonical entry points

- Panel/API: `scripts/video_control_panel.py` and `control_panel/ui/`
- Orchestration: `scripts/run_full_video_pipeline_q_station_wrapper.py`
- Creative/visual runtime: `scripts/run_q_station_pipeline.py`
- Stage/DAG/artifacts/invalidation: `scripts/pipeline_stages.py`, `scripts/run_graph.py`
- Character identity: `scripts/character_runtime.py`, `projects/q_station/characters/`
- Opening selection: `scripts/opening_runtime.py`
- Presentation profiles: `scripts/presentation_runtime.py`, `projects/q_station/presentation_profiles/`
- Topic-world style: `projects/q_station/world_styles/`

## Supported hosts

| Character | Presentation | Entry |
|---|---|---|
| Red Horned Everyman | `book_portal` | recurring storybook |
| Moss-Cloaked Crone | `orb_portal` | recognizable orb |
| Curious Sea Captain | `spyglass_portal` | recognizable spyglass |

The red host is the automatic fallback and compatibility default. Host selection is frozen for ordinary resume/retry; the panel Revise operation is the explicit controlled way to change it.

## Runtime invariants

- Text provider is ChatGPT, image provider is Gemini, and opening video provider is Flow through Ordak.
- No synthetic provider fallback or placeholder media.
- Flow A uses the selected canonical character sheet. Flow B uses generated first/last frames only.
- Narration alignment drives clip trimming and the final timeline.
- Topic-world art direction is independent of host costume and identity.
- Paid outputs are reused only with valid durable state and receipt contracts.
- Operator-installed host artwork is selectable only after validation.

See `docs/Q_STATION_PIPELINE.md` for the end-to-end contract and `docs/RECOVERY_RUNBOOK.md` for operations.
