# Ordak → Google Flow, in the real browser

Every video clip in an episode comes from the Flow web UI (`labs.google/fx/tools/flow`),
driven through CDP in the persistent `google-chrome-ordak` profile. **Each generation costs
7 credits**, which is why almost every rule below exists.

**Verified against the live UI on 2026-09-04.**

## Cost discipline

* `YT_ORDAK_FLOW_URL` is pinned to a **project** URL
  (`.../flow/project/36400b0f-…`), not the tool root, so a job joins the existing project
  instead of creating a new one — and the result baseline stays meaningful.
* Before clicking Generate the worker arms a credit guard: a submission fingerprint plus the
  number of results already present. `_reconcile_pending` uses that on restart to decide
  whether a generation already happened.
* If a restart finds neither a new result nor a downloaded file, the job fails with
  `FLOW_RECONCILIATION_REQUIRED` — a human looks. It never clicks Generate again on a
  maybe. **Blind duplicate Generate is zero.** `tests/test_flow_credit_safety.py` covers
  every restart shape.
* `outputs=x1` is mandatory, and the setting is verified after being applied.
* Nothing in `stage_flow_clip` retries. A retry is money, so recovery is the worker's
  reconciliation path, not a loop.

## Input focus, before anything else

`Input.dispatchMouseEvent` is dropped for a tab that is not in front of its window, and the
CDP call still succeeds. `_linux_cdp_commands` prefixes every input batch with
`Page.bringToFront`. Without it, `open_settings_menu` reports
`Could not open the Flow generation-settings menu` even though the button was located and
"clicked" — which is exactly what happened before this was fixed.

Coordinates are **CSS pixels**. Flow runs at `devicePixelRatio` 0.25 with a 7644×3952 layout
viewport, so a screenshot is a quarter of the CSS scale — but input is not. Do not scale
click coordinates by the ratio.

## The settings menu

The composer summary button reads like `Video · 720p · 4s crop_9_16 x1`. Clicking it opens a
`[data-radix-popper-content-wrapper]` containing one `[role="tablist"]` per setting group.
Groups are identified by **the content of their options** (`GROUP_SIGNATURES`), never by
index, because the order changes.

A live capability read (no credits spent):

```
mode        Frames | Ingredients        active: Ingredients
aspect      9:16 | 16:9                active: 9:16
resolution  360p | 720p                active: 720p
duration    4s | 6s | 8s | 10s         active: 4s
outputs     x1 | x2 | x3 | x4          active: x1
model       Omni 1.1 Flash  ->  gemini_omni_1_1_flash
credits_required: 7
```

Model labels carry a hyphen: `Omni 1.1 Flash`, `Veo 3.1 - Lite`, `Veo 3.1 - Fast`,
`Veo 3.1 - Quality`. A control that does not change raises `MODEL_SELECTION_FAILED`; a model
the UI does not list raises `MODEL_NOT_AVAILABLE`; 720p on a 360p-only model raises
`MODEL_FEATURE_INCOMPATIBLE`. `tests/test_flow_settings_verification.py` mocks the composer
and asserts each one.

## References: what each clip may receive

**Flow never receives a style sheet.** `flow_reference_policy` refuses the roles
`world_style_anchor`, `style_anchor`, `style_sheet` and `mood_board`, refuses a file merely
*named* like one, and the Ordak side enforces it again at the upload boundary.

| Clip | Allowed roles | Flow mode |
|---|---|---|
| A — question spark | `character_sheet` | Ingredients |
| B — book transition | `first_frame`, `last_frame` | Frames |

Frames and Ingredients are **exclusive**: one tablist, one active tab. That is why Clip B
carries only the two frames.

### Frames mode DOM

The slot row is the `parent` of the `Swap first and last frames` button; its children are
`[start, swap, end]`. An empty slot shows the text `Start`/`End` and contains no `<img>`; a
filled one contains an `<img>` whose `src` is a `media.getMediaUrlRedirect` URL, with a
`cancel` label.

### Ingredients mode DOM

The `add_2` button in the composer.

### Uploading

Click the target → a `[role="dialog"]` appears → `DOM.setFileInputFiles` on the single
`input[type="file"][accept*="image"]` → the new asset is **auto-selected** and
`Add to Prompt` becomes enabled → click confirm.

⚠ In this state, clicking the row **cancels** the selection. Don't.

## Results and download

Each result's `video.src` has a unique id, so "which result is new" is a set difference
against the armed baseline — never "the last one".

`Browser.setDownloadBehavior` works **only on the browser endpoint** and **only while that
same websocket is open**; `behavior=allowAndName` writes the file under a GUID. The worker
therefore holds the connection open across the download and renames afterwards.

Output is validated against the contract: duration and resolution are re-measured with
ffprobe and recorded in the receipt as observations, e.g.
`duration 4.01s vs requested 4s`, `resolution 720x1280 vs 720p`.

A real completed job:

```json
{"requested_model": "gemini_omni_1_1_flash", "actual_model_label": "Omni 1.1 Flash",
 "model_verified": true, "requested_aspect_ratio": "9:16", "actual_aspect_ratio": "9:16",
 "requested_duration_seconds": 4, "actual_duration_seconds": 4,
 "reference_roles": ["character_sheet"],
 "notes": ["credits_required=7", "outputs=x1", "reference_mode=Ingredients",
           "pixels=720x1280", "duration 4.01s vs requested 4s"]}
```

## Trimming

Flow sources are generated **one second longer** than the planned narration segment
(`--opening-a-seconds 6` for a ~5s spark, `--opening-b-seconds 4` for a ~3s transition).
`trim_opening_clips.py` then cuts them to the *measured* end of each narration segment from
`timing/WORD_TIMINGS.json` (§67). The source clip's own audio is never mapped into the
render.

## Re-probing (free)

```bash
cd /opt/YT_Video_Generation_Pipeline
services/ordak/.venv/bin/python - <<'PY'
import sys, json; sys.path.insert(0,'services/ordak')
from app.automation.existing_chrome import ChromeTabRef, list_google_chrome_tabs
import app.automation.flow_settings as fs
t=[x for x in list_google_chrome_tabs() if 'flow/project/' in (getattr(x,'url','') or '')][0]
r=ChromeTabRef(window_id=getattr(t,'window_id',0), tab_id=getattr(t,'tab_id',0), target_id=getattr(t,'target_id',None))
print(json.dumps(fs.read_capabilities(r).to_dict(), indent=1)); fs.close_settings_menu(r)
PY
```

Restart `ordak-api` after any change under `services/ordak/app`. A stale worker once cost
7 credits.
