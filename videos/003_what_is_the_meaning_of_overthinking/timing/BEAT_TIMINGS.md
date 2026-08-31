# Beat Timings

Audio: `assets/audio/narration.mp3`
Duration: **00:30.093**
STT backend: local
Provider: faster-whisper
Model: small.en
Timestamp source: word

| Beat | Display | Duration | Speech | Match | Narration |
|---:|---|---:|---|---:|---|
| 01 | 00:00.000 → 00:02.440 | 2.440s | 00:00.000 → 00:01.600 | 100% | You replay one conversation, |
| 02 | 00:02.440 → 00:04.100 | 1.660s | 00:02.440 → 00:03.960 | 100% | picture five different outcomes, |
| 03 | 00:04.100 → 00:08.160 | 4.060s | 00:04.100 → 00:06.860 | 100% | and somehow feel less certain than when you started. |
| 04 | 00:08.160 → 00:14.860 | 6.700s | 00:08.160 → 00:13.520 | 100% | That’s overthinking: your mind keeps circling a problem after useful thinking has run out. |
| 05 | 00:14.860 → 00:18.160 | 3.300s | 00:14.860 → 00:17.420 | 100% | One answer creates another question, then another. |
| 06 | 00:18.160 → 00:21.620 | 3.460s | 00:18.160 → 00:20.740 | 100% | It feels productive because you’re still thinking. |
| 07 | 00:21.620 → 00:24.840 | 3.220s | 00:21.620 → 00:23.980 | 100% | But more thought doesn’t always bring more clarity. |
| 08 | 00:24.840 → 00:27.280 | 2.440s | 00:24.840 → 00:27.280 | 100% | Sometimes the way forward isn’t one more possibility. |
| 09 | 00:27.280 → 00:30.093 | 2.813s | 00:27.280 → 00:29.520 | 100% | It’s choosing what to do next. |

## QC

- Low-confidence beats (<75% token match): none
- Review the generated timing table once before using it for the final render.
- `display_start/display_end` are continuous edit timings; `speech_start/speech_end` are the matched spoken phrase timings.
- Word timestamps are preferred. Segment-interpolated timestamps require extra QC.
