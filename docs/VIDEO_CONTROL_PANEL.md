# Video control panel

The control panel is a small authenticated launch surface for a complete new
video run. It is served on port `4143` behind nginx basic authentication using
the same credentials as Ordak VNC. The panel process itself listens only on
`127.0.0.1:4142`.

For a new video, enter only:

- content project / channel universe;
- topic;
- minimum and maximum duration in seconds;
- frame format: `16:9` landscape or `9:16` vertical Shorts/Reels;
- ElevenLabs voice, model, speed, stability, similarity and style;
- music provider.

The panel assigns the next numeric video ID, writes the requested voice profile
and launch request into that video's directory, then starts
`scripts/run_full_video_pipeline.py` in the background. That runner executes:

1. duration-range-aware hook/script, visual beats and sequential ChatGPT/Ordak images;
2. ElevenLabs browser voiceover using the selected settings;
3. local timestamp alignment, provider-browser music download and no-SFX render;
4. baseline and polished QC; and
5. deduplicated Telegram publishing of the verified polished video; and
6. a scoped Git commit and push of that video's durable artifacts and execution evidence.

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
