# ElevenLabs browser voiceover

`scripts/run_elevenlabs_voiceover.py` creates one full narration through the
authenticated ElevenLabs **web UI** in the Ordak-managed Chrome profile. It
does not use an ElevenLabs API or API key.

```bash
python scripts/run_elevenlabs_voiceover.py --video-id 002 --dry-run
python scripts/run_elevenlabs_voiceover.py --video-id 002
python scripts/run_elevenlabs_voiceover.py --video-id 002 --profile voice_profiles/elevenlabs_mark_default.json
```

The runner uses `voiceover/VOICEOVER_INPUT.txt` when present; otherwise it
copies the approved `SCRIPT_FINAL.md` there once. It persists
`voiceover/ELEVENLABS_RUNTIME_STATE.json`, timing events and the applied
settings in `voiceover/VOICE_PROFILE.json`, all of which are intentionally
Git-trackable. The downloaded media remains ignored at
`assets/audio/narration.<extension>`.

Optional CLI parameters (`--voice`, `--model`, `--speed`, `--stability`,
`--similarity`, `--style`, `--speaker-boost`) are applied only when supplied.
With no parameter, the current ElevenLabs UI defaults are preserved. An
explicit setting that cannot be found or applied fails safely rather than
silently generating with a different setting.

Reusable profile JSON files live in `voice_profiles/`. The included
`elevenlabs_mark_default.json` selects Mark, Eleven Multilingual v2, 0.9
speed, 0.45 stability, and explicitly reapplies the current UI-default 0.75
similarity and 0.10 style exaggeration on every run; command-line values
override a profile. ElevenLabs shows
the voices and models available to the logged-in account, so the runner uses
the visible display name rather than a fragile hard-coded catalog. Voice,
model, speed, stability, similarity, style and speaker boost are supported;
other provider controls remain at their UI defaults until explicitly added to a
profile after verification in the live UI.

Speaker Boost is capability-aware: when ElevenLabs does not expose that control
for the selected model, an explicit `false` is recorded as unavailable/effective
off and generation continues. An explicit `true` still fails safely, because it
cannot be honestly applied without a visible control.

All composer controls are resolved through narrow `data-testid`, role and ARIA
selectors. React/Radix selection triggers and options are focused by selector
and activated with trusted keyboard input. The Download Latest icon does not
honor keyboard activation, so that action alone uses a trusted pointer gesture
whose target is freshly resolved and hit-tested from its exact selector; no
coordinates are stored or accepted by the workflow. Before recording a
submission, the runner reads voice, model, numeric
controls and output format back from the DOM independent of the settings-panel
scroll position and compares them with the requested profile/CLI values. It also
requires Generate Speech to produce a visible acknowledgement (for example
`Loading...`, a disabled generate button, progress, or a visible download). An
on-screen human-verification challenge is reported safely for VNC completion
and is never automated.

While generation is active, the runner polls the actual page every configured
few seconds. It treats `Loading...` and other visible generation activity as
progress, refreshes only after a genuine no-progress stall, caps recovery
refreshes, and after each recovery refresh re-applies and verifies all requested
settings, restores the canonical narration text, and obtains a fresh visible
submission acknowledgement. It then activates ElevenLabs' canonical
`tts-download-latest-button` selector and waits for the browser download before
moving the audio into the video project. A stale persisted download record is cleared when a
runner resumes, and a still-visible download option is retried after the
configured retry window (`YT_ELEVENLABS_DOWNLOAD_RETRY_SECONDS`, default 30),
so a process crash cannot strand an already-generated result. English Telegram
progress, timing and failure notifications use the existing pipeline notifier
when enabled.
