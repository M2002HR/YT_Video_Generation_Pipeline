# Control panel

**http://&lt;host&gt;:4141/** behind nginx basic auth. Port 4144 is a legacy alias for the same
thing. The backend listens only on `127.0.0.1:4142`; nginx is the only public door.

Everything is on one page: launch a run, watch provider health, tail the live log, resume a
stopped run. No navigation, so a long run can be watched from where it was started.

## Launching

Locked choices are rendered as **disabled** inputs rather than editable ones, so the UI cannot
suggest a combination the pipeline would reject: text=ChatGPT, image=Gemini, video=Flow, and
Flow's reference contract (`character_sheet` for Clip A, `first_frame`+`last_frame` for Clip
B, never a style sheet).

| Field | Notes |
|---|---|
| Question / topic | required; becomes the episode slug |
| Working title, audience, narrative angle, must include / must avoid, source notes | free text, stored in `launch/CREATIVE_BRIEF.json` |
| Min / max duration | **binding.** Drives the word and beat ranges in the script prompts — a 25-30s request asks for ~57-75 words in 5-8 beats, a 40-60s one for 92-150 in 8-15 |
| Frame format | 9:16 Shorts (default) or 16:9 |
| Show subtitles | off by default for Question Harvest (§71) |
| Commit & push artifacts | off by default; needs a remote with write access |
| **World style** | `Auto` or any catalogued `style_id`. Picking one is a binding reuse instruction; the run fails rather than silently using another |
| World style policy | `auto` / `reuse` / `new`; ignored when a style is picked |
| World style hint | free text steer for a new style |
| Gemini image model | Nano Banana 2 (what the UI offers today) or Nano Banana Pro, which fails with `MODEL_NOT_AVAILABLE` until Google exposes it |
| Flow model / resolution | verified against the live Flow settings menu |
| Opening A / B seconds | Flow source length; one second of headroom over the planned segment |
| Voice, model, speed, stability, similarity, style | ElevenLabs profile |
| Music provider | mixkit or pixabay, through the browser |

A new style created during a run is written into
`projects/<id>/world_styles/CATALOG.json` with its anchor, so it appears in this picker for
the next episode. That is what makes "reuse if it exists" real.

Only one run at a time: a launch while another is `RUNNING` returns `409` naming the busy
episode.

## Endpoints

| Route | Purpose |
|---|---|
| `GET /` | the page |
| `POST /launch` | start a run; `202` on success, `400` on invalid input, `409` when busy |
| `GET /api/status` | provider badges plus per-job progress from `QH_RUNTIME_STATE.json` |
| `GET /api/log/<job_id>?offset=N` | **incremental** tail — returns new bytes and the next offset, not the whole file |
| `POST /resume` | re-run an episode; completed stages are reused |
| `GET /logs/<job_id>` | the whole log |
| `GET /nginx-health` | open, no auth |

## Provider badges

Read them with the single-tab policy in mind. Ordak keeps exactly one work tab, so at most one
provider can have its login re-confirmed at any moment.

| Badge | Meaning |
|---|---|
| `signed in` (green) | has a tab, and the UI says ready |
| `idle (no tab)` (amber) | ready, but no tab to confirm it — **normal**, not a problem |
| `login_required` / `manual_verification_required` (red) | a human must sign in at 4143 |
| `Ordak unreachable` | the API is down; nothing else on the row is trustworthy |

## Anti-stuck

A background reconciler runs every 30s: a job marked `RUNNING` whose pid is gone becomes
`FAILED` (or `DONE` when the log reported a pass **and** `final.mp4` plus `QC_REPORT.json`
exist). Page loads only read this state, so no row depends on someone refreshing.

## Credentials

`/root/.config/yt-video-pipeline/access-credentials.txt`, mode `600`. The htpasswd files must
be `root:www-data` mode `640` — see the trap described in `docs/SERVER_DEPLOYMENT.md`, where
correct credentials return `500` instead of `200`.
