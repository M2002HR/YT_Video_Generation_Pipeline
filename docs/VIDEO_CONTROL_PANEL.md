# Video Pipeline Studio

The Studio is the operator UI for launching, observing, inspecting, resuming, stopping, and
selectively regenerating video runs. The official address is
`http://<host>:4141/` behind nginx basic authentication. Port `4144` is a legacy alias;
the Python service itself binds only to `127.0.0.1:4142`.

## Architecture

The implementation deliberately has one source of truth for each public contract:

| Concern | Source of truth |
|---|---|
| Launch fields, defaults, constraints, and groups | `scripts/panel_contract.py` |
| Pipeline nodes, dependencies, phases, and owned artifacts | `scripts/run_graph.py` |
| HTTP API, process lifecycle, revision transactions | `scripts/video_control_panel.py` |
| React application | `control_panel/ui/src/main.jsx` |
| Tested browser-side status, URL, and launch helpers | `control_panel/ui/src/studio-utils.js` |
| Visual system and responsive behavior | `control_panel/ui/src/studio.css` |
| Built production assets | `control_panel/dist/` |

The browser never reads project files directly. It receives a normalized graph and uses
authenticated artifact endpoints. Media is transcoded to a low-bandwidth preview and text
artifacts are exposed only for a small allowlist (`json`, `txt`, `md`, and `ass`).

## Operator workflow

### Launch

The home page obtains its form from `GET /api/launch-schema`. It currently exposes all 91
editable inputs from the previous panel, grouped into Episode, Length & output, Visual,
Voice & music, Sound effects, Motion & editing, Publishing, and locked providers. Collapsed
and advanced controls still retain and submit their defaults.

The form posts the complete configuration to `POST /launch`. The backend validates ranges
and supported provider/model choices, freezes the request into the project, creates the job
record, and starts the canonical wrapper. At least one Telegram delivery output must remain
enabled. Only one provider-using run can execute at a time; concurrent launch attempts get
HTTP `409`.

Frozen input files:

- `launch/LAUNCH_REQUEST.json`: durable run/job settings used by resume.
- `launch/CREATIVE_BRIEF.json`: editorial, Question Harvest, subtitle, SFX, and motion input.
- `voiceover/REQUESTED_VOICE_PROFILE.json`: ElevenLabs settings.

The locked provider contract remains ChatGPT for text, Gemini for images, and Flow for video.
Music has an ordered fallback list: Freesound, Mixkit, then Pixabay by default.

### Observe

The dashboard polls status every five seconds. A run workspace polls its graph, normalized
activity, and incremental log every 2.5 seconds. New completion and failure events produce
toasts; user actions also produce success/error toasts. The activity drawer combines:

- Question Harvest stage state from `pipeline/QH_RUNTIME_STATE.json`;
- wrapper-owned voice, music, timing, and trim events from
  `pipeline/WRAPPER_RUNTIME_STATE.json`;
- finalization events from `pipeline/FINALIZATION_RUNTIME_STATE.json`;
- revision lifecycle events from `pipeline/revisions/*/REVISION.json`;
- incremental bytes from the panel job log.

The process monitor stores the subprocess exit code immediately. A background reconciler
also checks dead PIDs every 30 seconds. A run becomes `DONE` only when the finalization state
is complete and the polished video plus polished QC report exist. Flow-provider outages use
`WAITING_FOR_FLOW` and the existing watcher/resume mechanism instead of being mislabeled as
a pipeline failure.

### Inspect artifacts

Every node reports both present and missing artifacts. Selecting it displays execution
metadata plus all available image, video, audio, JSON, text, prompt, and subtitle artifacts.
Audio and video endpoints implement HTTP byte ranges, so native browser seeking and audio
playback work.

Music is not assumed to have a fixed filename. `run_graph.music_files()` resolves every
segment from `music/MUSIC_PLAN.json`, then the selected file from
`music/MUSIC_SELECTION.json`, and finally provider-produced audio under `assets/music/`.
This supports Freesound, Mixkit, Pixabay, and multi-segment plans without UI-specific paths.

Media safety and bandwidth rules:

- images are cached as maximum 480px JPEG previews;
- video is cached at maximum 360px without audio;
- audio is cached as 32 kbps mono Opus/Ogg;
- cache keys include the original path, size, and nanosecond mtime;
- resolved paths must remain below the selected project;
- master media is never returned by the panel endpoint.

Generated derivatives live in `.panel_previews/` within the run. They are disposable caches,
not pipeline artifacts.

## Dependency-aware regeneration

`scripts/run_graph.py` is the canonical data DAG. Regular stages are declared in
`NODE_SPECS`; beat-image nodes are expanded from the episode's visual plan. Beat images form
a continuity chain, so regenerating beat 2 also regenerates later beats, while independent
audio/voice branches can be reused.

The operator graph contains only stages enabled by that run's frozen settings. For example,
a run with SFX, Motion, compact Telegram output, or Git publishing disabled does not show a
permanently pending node for that feature. The full registry remains available internally to
configuration revisions, which is necessary when a revision enables or disables a feature.
Their manifests distinguish affected, reusable, and configuration-disabled/skipped nodes, so
an unrelated disabled branch is not invalidated during an editorial change.

The workspace offers regeneration on every graph node. The browser first calls the preview
endpoint and shows two exact lists:

- affected: the selected roots and every transitive descendant;
- reused: nodes outside that dependency closure.

After confirmation, the backend performs a transaction-like start:

1. Compute the dependency closure from the canonical graph.
2. Move only existing artifacts owned by affected nodes to
   `pipeline/revisions/<revision-id>/previous/<original-path>`.
3. Remove affected Question Harvest stage checkpoints.
4. Store feedback and a `REVISION.json` manifest.
5. Start the normal wrapper, whose stages reuse valid unaffected artifacts.
6. If the subprocess cannot start, restore archived artifacts and runtime state.

The completion runner reuses an output only when it exists and its prior durable event is
`DONE` or `REUSED`. Before each real child process it persists `RUNNING`; the same event is
then updated to `DONE` or `FAILED`. This prevents a partial file from being mistaken for a
valid checkpoint after interruption.

Beat feedback is written to `feedback.json` and consumed by the existing beat regeneration
path. A failed revision remains recorded and pending for audit/safe retry; successful
reconciliation clears `pending_revision` from the job.

Configuration revisions are available through the advanced frozen-JSON editor. The backend
maps changed settings to the narrowest safe graph roots: voice to narration, music priority
to background music, subtitle settings to timeline, motion/SFX to their directors, Flow
settings to opening clips, and unknown editorial changes conservatively to script draft.

Runs discovered from terminal/manual execution have deterministic IDs and can be inspected,
but are explicitly read-only because they do not have a panel-owned frozen job contract.

## API reference

| Method and route | Purpose |
|---|---|
| `GET /` | React Studio shell |
| `GET /runs/<job-id>` | React run workspace (history fallback) |
| `GET /api/launch-schema` | Declarative groups, fields, options, constraints, and defaults |
| `GET /api/status` | Provider health, active job, run history, progress, and controls |
| `GET /api/run/<job-id>/graph` | Job controls, canonical DAG, artifacts, and activity |
| `GET /api/run/<job-id>/activity` | Normalized durable events |
| `GET /api/run/<job-id>/config` | Frozen creative, voice, and launch input |
| `GET /api/run/<job-id>/artifact/<path>` | Safe media/text preview; supports `Range` |
| `GET /api/log/<job-id>?offset=N` | Incremental UTF-8 log tail and next byte offset |
| `GET /logs/<job-id>` | Legacy full-tail log view |
| `POST /launch` | Validate, freeze, and start a new run (`application/x-www-form-urlencoded`) |
| `POST /resume` | Resume a panel-owned run and reuse completed stages |
| `POST /stop` | Terminate an active panel-owned process group |
| `POST /delete` | Archive panel bookkeeping while retaining every project artifact |
| `POST /api/regenerations/preview` | Compute affected/reused nodes without changing state |
| `POST /api/regenerations` | Version artifacts and rebuild the chosen graph branch |
| `POST /api/revisions` | Compatibility alias for regeneration |
| `POST /api/config-revisions` | Version edited input JSON and rebuild its affected branches |

JSON errors use an `error` string. Launch/resume/stop retain HTML responses for compatibility;
the React request helper extracts their notice text and presents it as a toast/inline error.

## Extending the panel

### Add or change a launch setting

1. Add the field to the correct group in `scripts/panel_contract.py`.
2. Parse and validate it in the `/launch` handler.
3. Persist it in the job record, creative brief, or voice profile.
4. Add it to `pipeline_command()` when it changes executor arguments.
5. If existing runs can revise it, map the delta to a safe DAG root in
   `handle_config_revision()`.
6. Update the schema/default and endpoint tests.

The React form supports `text`, `textarea`, `number`, `select`, `toggle`, `priority`, and
`readonly`. `width="half"`, `advanced=true`, and group `collapsed=true` control presentation
without duplicating form logic.

### Add a pipeline node

1. Add a `NodeSpec` to `NODE_SPECS` with title, kind, dependencies, required artifacts,
   optional artifacts, and phase.
2. Make the executor write a durable stage event using the exact node ID.
3. Ensure the node's artifacts are exclusively owned or intentionally shared.
4. Add a graph test for its dependency closure and invalidation paths.

The board, dependency graph, artifact pane, status totals, regeneration preview, and
invalidation planner all consume this registry automatically. No JSX change is required for
a standard node.

### Add a new media provider filename

Write the selected relative file into `MUSIC_SELECTION.json` or each segment into
`MUSIC_PLAN.json`. Do not add a provider-specific filename to the panel. For a new audio
suffix, update both `MEDIA_SUFFIXES` in `run_graph.py` and the media allowlists in
`video_control_panel.py`/the wrapper.

## Development and deployment

Build the UI after any source change:

```bash
npm --prefix control_panel/ui install
npm --prefix control_panel/ui test
npm --prefix control_panel/ui run build
```

Run focused and full tests:

```bash
.venv/bin/python -m pytest -q tests/test_run_graph.py tests/test_panel_contract.py \
  tests/test_completion_events.py tests/test_control_panel_api.py
.venv/bin/python -m pytest -q tests
```

Start an isolated local instance:

```bash
.venv/bin/python scripts/video_control_panel.py --host 127.0.0.1 --port 4152
```

Deploy the built UI and backend code by restarting the service:

```bash
systemctl restart video-control-panel
systemctl status --no-pager video-control-panel
curl -fsS http://127.0.0.1:4142/api/status
```

The unit is defined in `deploy/video-control-panel.service`. nginx must remain the only
public listener and is documented in `docs/SERVER_DEPLOYMENT.md`.

## Troubleshooting

- **Music says unavailable:** inspect `music/MUSIC_SELECTION.json` and
  `music/MUSIC_PLAN.json`; the referenced project-relative file must exist and be non-empty.
  The Studio no longer assumes `background.mp3`.
- **Audio/video cannot seek:** verify the artifact request returns `206`, `Accept-Ranges:
  bytes`, and a matching `Content-Range` for a `Range: bytes=0-99` request.
- **A node says `MISSING`:** its runtime state claimed `DONE`/`REUSED`, but a required artifact
  is absent. Regenerate that node or restore the artifact; the warning is intentional.
- **Regeneration button is disabled:** another job is live, or the run was discovered outside
  Studio and is read-only.
- **Run appears stuck:** compare the job PID and exit code with the three runtime-state files
  and the incremental log. The reconciler normally settles a dead PID within 30 seconds.
- **Flow is unavailable:** expect `WAITING_FOR_FLOW`, not `FAILED`; inspect the watcher record
  and provider health before forcing a resume.
- **UI says it is not built:** run the Vite build command and confirm
  `control_panel/dist/index.html` exists.

Security headers disable framing, MIME sniffing, browser device APIs, external scripts, and
cross-origin resource loading. Basic authentication is still enforced by nginx, not by the
loopback Python server.

The UI labels `/delete` as **Archive**. Records and logs move to
`control_panel/jobs/archived/`; they can be restored by moving them back to
`control_panel/jobs/`. Archived project paths are excluded from external-run discovery, so a
failed archived run does not immediately reappear in history.
