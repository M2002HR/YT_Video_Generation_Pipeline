# Beat Timings

Audio: `assets/audio/narration.mp3`
Duration: **00:45.975**
STT backend: ajil
Provider: groq
Model: whisper-large-v3-turbo
Timestamp source: word

| Beat | Display | Duration | Speech | Match | Narration |
|---:|---|---:|---|---:|---|
| 01 | 00:00.000 → 00:10.560 | 10.560s | 00:08.920 → 00:10.020 | 67% | Picture a human at four tons. |
| 02 | 00:10.560 → 00:14.080 | 3.520s | 00:10.560 → 00:13.740 | 86% | That is fifty times your normal weight. |
| 03 | 00:14.080 → 00:16.440 | 2.360s | 00:14.080 → 00:16.440 | 100% | Weight grows with volume in three directions, |
| 04 | 00:16.440 → 00:21.740 | 5.300s | 00:16.440 → 00:20.540 | 100% | but bone strength only grows with bone thickness. |
| 05 | 00:21.740 → 00:23.460 | 1.720s | 00:21.740 → 00:23.460 | 80% | Your weight jumps fifty times, |
| 06 | 00:23.460 → 00:27.780 | 4.320s | 00:23.460 → 00:27.280 | 86% | while bone thickness only grows fourteen times. |
| 07 | 00:27.780 → 00:31.200 | 3.420s | 00:27.780 → 00:30.760 | 100% | Elephants survive with legs like thick pillars. |
| 08 | 00:31.200 → 00:34.220 | 3.020s | 00:31.200 → 00:33.660 | 100% | Slender human legs bend at angles. |
| 09 | 00:34.220 → 00:35.880 | 1.660s | 00:34.220 → 00:35.880 | 100% | The moment you try to stand, |
| 10 | 00:35.880 → 00:38.880 | 3.000s | 00:35.880 → 00:38.500 | 100% | your leg bones snap under the load. |
| 11 | 00:38.880 → 00:45.975 | 7.095s | 00:38.880 → 00:42.100 | 100% | To carry that weight, you need legs like tree trunks. |

## QC

- Low-confidence beats (<75% token match): 01
- Review the generated timing table once before using it for the final render.
- `display_start/display_end` are continuous edit timings; `speech_start/speech_end` are the matched spoken phrase timings.
- Word timestamps are preferred. Segment-interpolated timestamps require extra QC.
