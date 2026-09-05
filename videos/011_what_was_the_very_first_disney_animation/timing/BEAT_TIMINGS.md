# Beat Timings

Audio: `assets/audio/narration.mp3`
Duration: **00:34.168**
STT backend: ajil
Provider: groq
Model: whisper-large-v3-turbo
Timestamp source: word

| Beat | Display | Duration | Speech | Match | Narration |
|---:|---|---:|---|---:|---|
| 01 | 00:00.000 → 00:13.560 | 13.560s | 00:08.860 → 00:11.920 | 70% | Disney's earliest Kansas City cartoons were the Laugh-O-Grams. |
| 02 | 00:13.560 → 00:15.780 | 2.220s | 00:13.560 → 00:15.380 | 100% | They came years before Mickey. |
| 03 | 00:15.780 → 00:18.320 | 2.540s | 00:15.780 → 00:17.680 | 100% | Next came the Alice Comedies. |
| 04 | 00:18.320 → 00:21.520 | 3.200s | 00:18.320 → 00:20.980 | 100% | Those blended live action with animation. |
| 05 | 00:21.520 → 00:34.168 | 12.648s | 00:21.520 → 00:24.540 | 100% | Steamboat Willie was a milestone, not the start. |

## QC

- Low-confidence beats (<75% token match): 01
- Review the generated timing table once before using it for the final render.
- `display_start/display_end` are continuous edit timings; `speech_start/speech_end` are the matched spoken phrase timings.
- Word timestamps are preferred. Segment-interpolated timestamps require extra QC.
