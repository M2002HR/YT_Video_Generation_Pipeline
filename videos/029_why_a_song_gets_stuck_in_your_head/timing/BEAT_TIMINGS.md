# Beat Timings

Audio: `assets/audio/narration.mp3`
Duration: **00:59.429**
STT backend: ajil
Provider: groq
Model: whisper-large-v3-turbo
Timestamp source: word

| Beat | Display | Duration | Speech | Match | Narration |
|---:|---|---:|---|---:|---|
| 01 | 00:00.000 → 00:16.840 | 16.840s | 00:10.940 → 00:16.340 | 100% | Scientists call it involuntary musical imagery, or an earworm. |
| 02 | 00:16.840 → 00:19.960 | 3.120s | 00:16.840 → 00:19.320 | 100% | Recent or repeated listening can trigger it. |
| 03 | 00:19.960 → 00:24.520 | 4.560s | 00:19.960 → 00:23.340 | 100% | Short, distinctive fragments are easier to retrieve. |
| 04 | 00:24.520 → 00:28.260 | 3.740s | 00:24.520 → 00:27.260 | 100% | Repetition makes the next note feel predictable. |
| 05 | 00:28.260 → 00:32.660 | 4.400s | 00:28.260 → 00:31.840 | 100% | Your brain can replay that pattern without any sound. |
| 06 | 00:32.660 → 00:36.120 | 3.460s | 00:32.660 → 00:35.220 | 100% | Idle moments give the loop room to return. |
| 07 | 00:36.120 → 00:40.140 | 4.020s | 00:36.120 → 00:39.200 | 100% | Mood or personal memories can strengthen the cue. |
| 08 | 00:40.140 → 00:43.060 | 2.920s | 00:40.140 → 00:43.060 | 100% | Fighting it can keep your attention stuck on it. |
| 09 | 00:43.060 → 00:46.460 | 3.400s | 00:43.060 → 00:46.940 | 100% | An absorbing task can pull attention elsewhere. |
| 10 | 00:46.460 → 00:59.429 | 12.969s | 00:46.460 → 00:50.620 | 100% | Then the loop often fades on its own. |

## QC

- Low-confidence beats (<75% token match): none
- Review the generated timing table once before using it for the final render.
- `display_start/display_end` are continuous edit timings; `speech_start/speech_end` are the matched spoken phrase timings.
- Word timestamps are preferred. Segment-interpolated timestamps require extra QC.
