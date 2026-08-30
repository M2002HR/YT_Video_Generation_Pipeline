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
`elevenlabs_mark_default.json` selects Mark, Eleven v3, 0.9 speed
and 0.45 stability; command-line values override a profile. ElevenLabs shows
the voices and models available to the logged-in account, so the runner uses
the visible display name rather than a fragile hard-coded catalog. Voice,
model, speed, stability, similarity, style and speaker boost are supported;
other provider controls remain at their UI defaults until explicitly added to a
profile after verification in the live UI.

While generation is active, the runner polls the actual page every configured
few seconds. It treats visible generation activity as progress, refreshes only
after a genuine no-progress stall, caps recovery refreshes, resumes from the
persisted state, triggers the strongest visible web-UI download option, then
waits for the browser download before moving the audio into the video project.
English Telegram progress, timing and failure notifications use the existing
pipeline notifier when enabled.

## Navigation advisor

For unstable menus the optional advisor calls the local Ajil gateway on port
8188 with `openai/gpt-oss-120b`. It sees only a capped list of visible labels
and a narrow goal, returns one schema-validated JSON decision, and has no
browser, filesystem, credential, or generation authority. Ordak remains the
deterministic executor and rejects invented labels/actions.
