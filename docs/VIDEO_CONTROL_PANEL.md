# Video control panel

The control panel is a small authenticated launch surface for a complete new
video run. It is served on port `4143` behind nginx basic authentication using
the same credentials as Ordak VNC. The panel process itself listens only on
`127.0.0.1:4142`.

For a new video, enter only:

- content project / channel universe;
- topic;
- optional working title, audience override, narrative angle, required/forbidden
  points, and verified source notes;
- minimum and maximum duration in seconds;
- frame format: `16:9` landscape or `9:16` vertical Shorts/Reels;
- ElevenLabs voice, model, speed, stability, similarity and style;
- music provider.

The panel assigns the next numeric video ID, writes the requested voice profile,
creative brief (`launch/CREATIVE_BRIEF.json`), and launch request into that
video's directory, then starts
`scripts/run_full_video_pipeline.py` in the background. That runner executes:

1. duration-range-aware hook/script;
2. for configured projects such as The World Behind the Question, a durable
   episode design for the question book, portal, subject world, palette,
   locations, props, Seeker adaptation, and visual arc;
3. visual beats and sequential ChatGPT/Ordak images bound to that design;
4. ElevenLabs browser voiceover using the selected settings;
5. local timestamp alignment, provider-browser music download and no-SFX render;
6. baseline and polished QC;
7. deduplicated Telegram publishing of the verified polished video; and
8. a scoped Git commit and push of that video's durable artifacts and execution evidence.

After successful finalization, the video is also added to the selected content
project's `VIDEOS.json`. Git publication is path-scoped to that video and its
registry entry, so unrelated staged work is preserved.

Launch and stage timing evidence is persisted under the video directory. The
panel's log link provides a live, auto-refreshing view of the job output.

The range is intentional: the writer chooses the most natural spoken length
within the supplied bounds instead of padding to a fixed duration. Script word
counts and visual-beat counts are validated against the whole range; later
timing, music and rendering use the actual duration of the generated narration.
The same frame format is carried into the image prompt, image validation,
render profile and final QC resolution (`1920x1080` for `16:9`, `1080x1920`
for `9:16`).


## Content projects

The panel reads available projects from `projects/*/PROJECT.json` and passes the selected project through the full pipeline. New videos record their membership in `PROJECT.md`.

The legacy/default project preserves all existing videos and behavior. New brand work should use its own project namespace so prompt and canonical visual changes cannot silently affect previous channels.

For **The World Behind the Question**, the panel selects that project by default.
Its creative brief is included in `BRIEF.md`, so its project-owned script,
retention, visual-beat, and image-prompt templates all use the same editorial
constraints. A launch is rejected before a background process starts if the
selected project is missing a required prompt or canonical visual anchor.
The generated episode bible is persisted as `WORLD_DESIGN.md` beside the
script, making the question-specific visual template auditable and reusable
through every beat.
