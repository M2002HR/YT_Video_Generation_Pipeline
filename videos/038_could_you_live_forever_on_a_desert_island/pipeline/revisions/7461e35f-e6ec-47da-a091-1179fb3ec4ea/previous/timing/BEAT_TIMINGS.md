# Beat Timings

Audio: `assets/audio/narration.mp3`
Duration: **00:34.090**
STT backend: ajil
Provider: groq
Model: whisper-large-v3-turbo
Timestamp source: word

| Beat | Display | Duration | Speech | Match | Narration |
|---:|---|---:|---|---:|---|
| 01 | 00:00.000 → 00:12.180 | 12.180s | 00:08.860 → 00:11.640 | 100% | Storms can rip shelters apart and ruin tools. |
| 02 | 00:12.180 → 00:14.920 | 2.740s | 00:12.180 → 00:14.400 | 100% | Strong sun and heat can harm your body. |
| 03 | 00:14.920 → 00:17.980 | 3.060s | 00:14.920 → 00:17.960 | 100% | A bad injury can become dangerous without medical care. |
| 04 | 00:17.980 → 00:20.740 | 2.760s | 00:17.980 → 00:20.440 | 100% | Infection can become serious without treatment. |
| 05 | 00:20.740 → 00:23.560 | 2.820s | 00:20.740 → 00:23.120 | 100% | Storms can spoil food or cut off fresh water. |
| 06 | 00:23.560 → 00:25.120 | 1.560s | 00:23.560 → 00:25.580 | 100% | Rescue may not arrive when you need it. |
| 07 | 00:25.120 → 00:28.560 | 3.440s | 00:25.120 → 00:28.500 | 100% | Even in perfect safety, your body would still age. |
| 08 | 00:28.560 → 00:34.090 | 5.530s | 00:28.560 → 00:32.060 | 100% | Supplies can extend survival, but they cannot make life endless. |

## QC

- Low-confidence beats (<75% token match): none
- Review the generated timing table once before using it for the final render.
- `display_start/display_end` are continuous edit timings; `speech_start/speech_end` are the matched spoken phrase timings.
- Word timestamps are preferred. Segment-interpolated timestamps require extra QC.
