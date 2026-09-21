# Beat Timings

Audio: `assets/audio/narration.mp3`
Duration: **00:44.121**
STT backend: ajil
Provider: groq
Model: whisper-large-v3-turbo
Timestamp source: word

| Beat | Display | Duration | Speech | Match | Narration |
|---:|---|---:|---|---:|---|
| 01 | 00:00.000 → 00:14.980 | 14.980s | 00:12.020 → 00:13.940 | 67% | Schrödinger proposed it in 1935. |
| 02 | 00:14.980 → 00:17.480 | 2.500s | 00:14.980 → 00:16.860 | 100% | A cat is sealed in a box. |
| 03 | 00:17.480 → 00:20.320 | 2.840s | 00:17.480 → 00:19.600 | 100% | One radioactive atom may decay. |
| 04 | 00:20.320 → 00:22.860 | 2.540s | 00:20.320 → 00:22.120 | 100% | A detector watches for decay. |
| 05 | 00:22.860 → 00:26.120 | 3.260s | 00:22.860 → 00:25.460 | 100% | Decay can trigger a poison mechanism. |
| 06 | 00:26.120 → 00:26.840 | 0.720s | 00:26.120 → 00:27.520 | 100% | Then the cat dies. |
| 07 | 00:26.840 → 00:30.320 | 3.480s | 00:26.840 → 00:29.560 | 100% | No decay leaves it alive. |
| 08 | 00:30.320 → 00:34.020 | 3.700s | 00:30.320 → 00:33.480 | 100% | Quantum theory can describe both possibilities together. |
| 09 | 00:34.020 → 00:36.640 | 2.620s | 00:34.020 → 00:35.920 | 100% | That state is called a superposition. |
| 10 | 00:36.640 → 00:44.121 | 7.481s | 00:36.640 → 00:39.300 | 100% | That jump from atom to cat was the point. |

## QC

- Low-confidence beats (<75% token match): 01
- Review the generated timing table once before using it for the final render.
- `display_start/display_end` are continuous edit timings; `speech_start/speech_end` are the matched spoken phrase timings.
- Word timestamps are preferred. Segment-interpolated timestamps require extra QC.
