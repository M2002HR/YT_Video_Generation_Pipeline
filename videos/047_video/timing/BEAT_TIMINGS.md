# Beat Timings

Audio: `assets/audio/narration.mp3`
Duration: **00:36.911**
STT backend: ajil
Provider: groq
Model: whisper-large-v3-turbo
Timestamp source: word

| Beat | Display | Duration | Speech | Match | Narration |
|---:|---|---:|---|---:|---|
| 01 | 00:00.000 → 00:12.500 | 12.500s | 00:08.520 → 00:11.240 | 100% | Outside pressure is lower at high altitude. |
| 02 | 00:12.500 → 00:15.520 | 3.020s | 00:12.500 → 00:15.040 | 100% | A break lets cabin air rush out. |
| 03 | 00:15.520 → 00:18.780 | 3.260s | 00:15.520 → 00:17.900 | 100% | Airflow is strongest near the opening. |
| 04 | 00:18.780 → 00:22.020 | 3.240s | 00:18.780 → 00:21.220 | 100% | Farther away, the air may move much less. |
| 05 | 00:22.020 → 00:25.560 | 3.540s | 00:22.020 → 00:24.520 | 100% | Pressure falls, making breathing harder. |
| 06 | 00:25.560 → 00:29.520 | 3.960s | 00:25.560 → 00:28.320 | 100% | Oxygen masks may drop as pilots descend. |
| 07 | 00:29.520 → 00:36.911 | 7.391s | 00:29.520 → 00:33.600 | 100% | That sudden pressure loss is called rapid decompression. |

## QC

- Low-confidence beats (<75% token match): none
- Review the generated timing table once before using it for the final render.
- `display_start/display_end` are continuous edit timings; `speech_start/speech_end` are the matched spoken phrase timings.
- Word timestamps are preferred. Segment-interpolated timestamps require extra QC.
