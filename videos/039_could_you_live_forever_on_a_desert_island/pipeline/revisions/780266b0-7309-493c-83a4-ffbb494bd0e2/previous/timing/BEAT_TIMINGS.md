# Beat Timings

Audio: `assets/audio/narration.mp3`
Duration: **00:45.871**
STT backend: ajil
Provider: groq
Model: whisper-large-v3-turbo
Timestamp source: word

| Beat | Display | Duration | Speech | Match | Narration |
|---:|---|---:|---|---:|---|
| 01 | 00:00.000 → 00:11.660 | 11.660s | 00:08.820 → 00:11.160 | 100% | Seawater has too much salt for your body. |
| 02 | 00:11.660 → 00:14.660 | 3.000s | 00:11.660 → 00:14.100 | 100% | Your kidneys use water to remove that salt. |
| 03 | 00:14.660 → 00:19.980 | 5.320s | 00:14.660 → 00:19.460 | 100% | Drink seawater, and you may lose more water than you gain. |
| 04 | 00:19.980 → 00:21.160 | 1.180s | 00:19.980 → 00:21.720 | 100% | Rain can help if you collect it. |
| 05 | 00:21.160 → 00:24.460 | 3.300s | 00:21.160 → 00:23.740 | 100% | Some islands have springs or fresh groundwater. |
| 06 | 00:24.460 → 00:27.220 | 2.760s | 00:24.460 → 00:26.620 | 100% | Others may have no reliable fresh water. |
| 07 | 00:27.220 → 00:30.140 | 2.920s | 00:27.220 → 00:30.140 | 100% | Desalination can turn seawater into fresh water. |
| 08 | 00:30.140 → 00:34.220 | 4.080s | 00:30.140 → 00:34.220 | 100% | But it needs equipment, energy, and care. |
| 09 | 00:34.220 → 00:37.340 | 3.120s | 00:34.220 → 00:37.340 | 100% | Food, injury, disease, and aging still matter. |
| 10 | 00:37.340 → 00:45.871 | 8.531s | 00:37.340 → 00:41.400 | 100% | Even perfect fresh water cannot make island life last forever. |

## QC

- Low-confidence beats (<75% token match): none
- Review the generated timing table once before using it for the final render.
- `display_start/display_end` are continuous edit timings; `speech_start/speech_end` are the matched spoken phrase timings.
- Word timestamps are preferred. Segment-interpolated timestamps require extra QC.
