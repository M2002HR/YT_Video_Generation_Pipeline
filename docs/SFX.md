# SFX subsystem

`sfx_plan` uses ChatGPT through Ordak to create the strict, versioned `sfx/SFX_PLAN.json`; it never searches or downloads. `sfx_acquire` runs after baseline QC, resolves that plan from the shared SQLite/FTS library first, and only then calls the official Freesound API. It writes `sfx/SFX_SELECTION.json` and updates `audio_mix/AUDIO_MIX_PROFILE.json`; `polish_audio.py` remains provider-agnostic.

Set `FREESOUND_API_KEY` (or an OAuth token where the selected download scope requires it) in local `.env`. Default policy is CC0 only. CC BY may be explicitly enabled from the panel; NC is never selected. Creative Commons content licensing and Freesound API terms are separate: commercial production must comply with the current Freesound API terms.

The reusable cache defaults to `runtime/sfx_library` and is intentionally Git-ignored. Rebuild it by removing only its `index.sqlite3` after backing up assets, then run `python3 scripts/bootstrap_sfx_library.py --preset core`. The bootstrap uses the same licensing, ranking, validation, dedupe, and metadata path as episodes. Re-run a plan with `run_sfx_planner.py PROJECT --force`; delete or invalidate only `SFX_SELECTION.json` to reacquire unresolved events.
