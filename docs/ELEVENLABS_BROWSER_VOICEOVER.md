# ElevenLabs browser voiceover

`scripts/run_elevenlabs_voiceover.py` creates one full narration through the
authenticated ElevenLabs **web UI** in the Ordak-managed Chrome profile. It
does not use an ElevenLabs API or API key.

```bash
python scripts/run_elevenlabs_voiceover.py --video-id 002 --dry-run
python scripts/run_elevenlabs_voiceover.py --video-id 002
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

While generation is active, the runner polls the actual page every configured
few seconds. It treats visible generation activity as progress, refreshes only
after a genuine no-progress stall, caps recovery refreshes, resumes from the
persisted state, triggers the strongest visible web-UI download option, then
waits for the browser download before moving the audio into the video project.
English Telegram progress, timing and failure notifications use the existing
pipeline notifier when enabled.
