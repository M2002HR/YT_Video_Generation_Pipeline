# Beat Timings

Audio: `assets/audio/narration.mp3`
Duration: **00:54.570**
STT backend: ajil
Provider: groq
Model: whisper-large-v3-turbo
Timestamp source: word

| Beat | Display | Duration | Speech | Match | Narration |
|---:|---|---:|---|---:|---|
| 01 | 00:00.000 → 00:16.400 | 16.400s | 00:10.580 → 00:15.480 | 100% | In 1900, sponge divers found a wreck off Antikythera. |
| 02 | 00:16.400 → 00:20.480 | 4.080s | 00:16.400 → 00:19.600 | 100% | Its cargo included a corroded bronze lump. |
| 03 | 00:20.480 → 00:24.860 | 4.380s | 00:20.480 → 00:24.180 | 71% | Inside were tightly packed, precision-cut gears. |
| 04 | 00:24.860 → 00:28.180 | 3.320s | 00:24.860 → 00:27.320 | 78% | The mechanism was built over two thousand years ago. |
| 05 | 00:28.180 → 00:32.440 | 4.260s | 00:28.180 → 00:32.100 | 100% | A hand crank moved pointers across astronomical dials. |
| 06 | 00:32.440 → 00:34.680 | 2.240s | 00:32.440 → 00:34.380 | 100% | One dial tracked the Sun and Moon. |
| 07 | 00:34.680 → 00:38.440 | 3.760s | 00:34.680 → 00:38.080 | 100% | Others modeled cycles used to predict eclipses. |
| 08 | 00:38.440 → 00:43.020 | 4.580s | 00:38.440 → 00:42.340 | 100% | Another tracked the cycle of major Greek games. |
| 09 | 00:43.020 → 00:46.540 | 3.520s | 00:43.020 → 00:46.280 | 100% | Inscriptions even explained parts of its operation. |
| 10 | 00:46.540 → 00:54.570 | 8.030s | 00:46.540 → 00:50.500 | 80% | It was a hand-powered mechanical model of the heavens. |

## QC

- Low-confidence beats (<75% token match): 03
- Review the generated timing table once before using it for the final render.
- `display_start/display_end` are continuous edit timings; `speech_start/speech_end` are the matched spoken phrase timings.
- Word timestamps are preferred. Segment-interpolated timestamps require extra QC.
