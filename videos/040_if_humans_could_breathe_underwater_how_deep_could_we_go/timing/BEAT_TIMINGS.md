# Beat Timings

Audio: `assets/audio/narration.mp3`
Duration: **00:59.481**
STT backend: ajil
Provider: groq
Model: whisper-large-v3-turbo
Timestamp source: word

| Beat | Display | Duration | Speech | Match | Narration |
|---:|---|---:|---|---:|---|
| 01 | 00:00.000 → 00:12.960 | 12.960s | 00:08.880 → 00:12.480 | 100% | Body tissue with lots of water barely changes. |
| 02 | 00:12.960 → 00:17.140 | 4.180s | 00:12.960 → 00:16.780 | 100% | Air in your ears and sinuses shrinks much more. |
| 03 | 00:17.140 → 00:21.980 | 4.840s | 00:17.140 → 00:22.400 | 92% | Every ten meters, pressure rises by about the air pressure at the surface. |
| 04 | 00:21.980 → 00:26.820 | 4.840s | 00:21.980 → 00:26.380 | 88% | At ten meters, total pressure is about double. |
| 05 | 00:26.820 → 00:31.100 | 4.280s | 00:26.820 → 00:30.800 | 100% | Unequal pressure can injure your ears and sinuses. |
| 06 | 00:31.100 → 00:36.740 | 5.640s | 00:31.100 → 00:36.520 | 100% | Breathing underwater removes the problem of running out of air. |
| 07 | 00:36.740 → 00:40.240 | 3.500s | 00:36.740 → 00:39.680 | 100% | But pressure would still affect your body. |
| 08 | 00:40.240 → 00:46.160 | 5.920s | 00:40.240 → 00:45.940 | 100% | At extreme depths, high pressure can disturb how nerves normally work. |
| 09 | 00:46.160 → 00:50.540 | 4.380s | 00:46.160 → 00:50.100 | 100% | So breathing alone does not set a fixed depth limit. |
| 10 | 00:50.540 → 00:59.481 | 8.941s | 00:50.540 → 00:55.080 | 100% | Breathing solves one limit, but pressure creates others. |

## QC

- Low-confidence beats (<75% token match): none
- Review the generated timing table once before using it for the final render.
- `display_start/display_end` are continuous edit timings; `speech_start/speech_end` are the matched spoken phrase timings.
- Word timestamps are preferred. Segment-interpolated timestamps require extra QC.
