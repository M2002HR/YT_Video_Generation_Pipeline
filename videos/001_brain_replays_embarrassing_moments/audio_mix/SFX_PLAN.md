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


## Recommended source candidates

Use only three SFX for the first pass.

### 1) Intrusive-thought cue — 1.96s

Target filename:

`assets/sfx/intrusive_pop.mp3`

Candidate:
https://pixabay.com/sound-effects/technology-soft-ui-pop-light-minimal-click-451232/

Suggested mix:
- at: 1.96
- gain: -17 dB
- trim: 0.7s

### 2) Replay cue — 28.34s

Target filename:

`assets/sfx/replay_rewind.mp3`

Candidate:
https://pixabay.com/sound-effects/film-special-effects-tape-recorder-rewind-fanmade-6914/

Suggested mix:
- at: 28.34
- gain: -15 dB
- trim: 0.9s

### 3) Archive cue — 51.58s

Target filename:

`assets/sfx/archive_drawer.mp3`

Candidate:
https://pixabay.com/sound-effects/film-special-effects-drawer-opens-and-closes-101328/

Suggested mix:
- at: 51.58
- gain: -18 dB
- trim: 1.0s

Do not add an ending SFX in the first pass. Let the music fade and narration carry the final line.
