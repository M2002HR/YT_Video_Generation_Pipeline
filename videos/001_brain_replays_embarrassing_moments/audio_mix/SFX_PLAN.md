# SFX Plan — Video 001

Use SFX sparingly. The narration and visuals already carry the story.

Recommended maximum: 3–4 subtle effects for the full ~63s short.

| Event | Time | Purpose | Suggested character |
|---|---:|---|---|
| Intrusive thought appears | 1.96s | Reinforce the sudden “Hey…” interruption | soft pop / tiny mental ping, very short |
| Replay begins | 28.34s | Support the looping-memory metaphor | subtle rewind / tape flutter, <1s |
| Embarrassment archive opens | 51.58s | Reinforce the archive visual metaphor | soft drawer / paper slide |
| Ending settles | 60.02s | Support the “everything got quieter” payoff | optional very soft airy tail, only if it helps |

## Mix guidance

- Keep each SFX below narration.
- Avoid comedic/cartoon sounds that break the calm intelligent tone.
- Do not add a sound to every cut.
- If an effect is noticeable as an “effect” rather than a story cue, turn it down or remove it.
- The ending may work better with no SFX at all; compare both versions.

## Implementation

Once local files exist under `assets/sfx/`, add matching events to:

`audio_mix/AUDIO_MIX_PROFILE.json`

Example:

```json
{
  "file": "assets/sfx/replay_rewind.wav",
  "at": 28.34,
  "gain_db": -14.0,
  "trim_sec": 0.8
}
```
