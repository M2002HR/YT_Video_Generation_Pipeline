# Video control panel

The control panel is a small authenticated launch surface for a complete new
video run. It is served on port `4143` behind nginx basic authentication using
the same credentials as Ordak VNC. The panel process itself listens only on
`127.0.0.1:4142`.

For a new video, enter only:

- topic;
- minimum and maximum duration in seconds;
- ElevenLabs voice, model, speed, stability, similarity and style;
- music provider.

The panel assigns the next numeric video ID, writes the requested voice profile
and launch request into that video's directory, then starts
`scripts/run_full_video_pipeline.py` in the background. That runner executes:

1. duration-range-aware hook/script, visual beats and sequential ChatGPT/Ordak images;
2. ElevenLabs browser voiceover using the selected settings;
3. local timestamp alignment, provider-browser music download and no-SFX render;
4. baseline and polished QC; and
5. deduplicated Telegram publishing of the verified polished video.

Launch and stage timing evidence is persisted under the video directory. The
panel's log link provides a live, auto-refreshing view of the job output.

The range is intentional: the writer chooses the most natural spoken length
within the supplied bounds instead of padding to a fixed duration. Script word
counts and visual-beat counts are validated against the whole range; later
timing, music and rendering use the actual duration of the generated narration.
