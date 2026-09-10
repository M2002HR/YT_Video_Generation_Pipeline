# Q Station

Every question opens a world.

The canonical content-project id is `q_station`; `question_harvest` is a legacy alias used to resume historical runs. A compatibility symlink preserves old persisted asset paths but is excluded from project discovery, so the catalog lists Q Station only once. New runs choose Character as Auto (default) or a validated manual registry id. Auto runs once after the final Stage 02 script and before Stage 03 Episode Director, then its result is persisted and reused on retries/resume. Current packs are Farmer Host and Red Horned Everyman.

Character, visual preset, opening environment and inside-book world style are independent. Stage 03 derives a dynamic episode-specific environment; Farmer's rural affinities are soft and Red owns no environment. WORLD_KEYFRAME and Video 2 are host-free. Body images receive character identity only for explicit host-present beats. Sheets are identity-only.

Flow safety: Clip A uses Ingredients mode with the selected canonical character sheet only. Clip B uses Frames mode with the episode book frame first and host-free WORLD_KEYFRAME last. Flow never receives a style sheet.

Pipeline profile: `bookworld_mixed_media`.
