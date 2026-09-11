# Beat Timings

Audio: `assets/audio/narration.mp3`
Duration: **00:59.611**
STT backend: ajil
Provider: groq
Model: whisper-large-v3-turbo
Timestamp source: word

| Beat | Display | Duration | Speech | Match | Narration |
|---:|---|---:|---|---:|---|
| 01 | 00:00.000 → 00:12.960 | 12.960s | 00:09.060 → 00:12.480 | 100% | Attention drifts; obvious details slip past. |
| 02 | 00:12.960 → 00:16.880 | 3.920s | 00:12.960 → 00:16.100 | 100% | Reaction time slows, making mistakes easier. |
| 03 | 00:16.880 → 00:20.100 | 3.220s | 00:16.880 → 00:19.200 | 100% | New memories become harder to store. |
| 04 | 00:20.100 → 00:24.360 | 4.260s | 00:20.100 → 00:23.640 | 100% | Emotional control weakens, so feelings hit harder. |
| 05 | 00:24.360 → 00:28.060 | 3.700s | 00:24.360 → 00:27.320 | 71% | Hunger shifts toward more calorie-dense foods. |
| 06 | 00:28.060 → 00:31.660 | 3.600s | 00:28.060 → 00:31.220 | 100% | Your immune system gets less recovery time. |
| 07 | 00:31.660 → 00:34.360 | 2.700s | 00:31.660 → 00:33.880 | 100% | Blood pressure control can worsen. |
| 08 | 00:34.360 → 00:37.680 | 3.320s | 00:34.360 → 00:36.740 | 100% | Blood sugar control can worsen too. |
| 09 | 00:37.680 → 00:42.220 | 4.540s | 00:37.680 → 00:41.260 | 100% | Repeated short sleep is linked with heart disease and diabetes. |
| 10 | 00:42.220 → 00:47.120 | 4.900s | 00:42.220 → 00:46.400 | 100% | Caffeine can mask sleepiness, but cannot replace sleep. |
| 11 | 00:47.120 → 00:59.611 | 12.491s | 00:47.120 → 00:50.120 | 100% | Most adults need at least seven hours nightly. |

## QC

- Low-confidence beats (<75% token match): 05
- Review the generated timing table once before using it for the final render.
- `display_start/display_end` are continuous edit timings; `speech_start/speech_end` are the matched spoken phrase timings.
- Word timestamps are preferred. Segment-interpolated timestamps require extra QC.
