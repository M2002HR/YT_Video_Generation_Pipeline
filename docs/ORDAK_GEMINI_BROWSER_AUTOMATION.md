# Ordak → Gemini, in the real browser

Every image in an episode comes from the Gemini web UI, driven through CDP in the persistent
`google-chrome-ordak` profile. Nothing here calls an API. This document records what the UI
actually looks like, because the code's needles are only as good as these observations.

**Verified against the live UI on 2026-09-04.** When Google changes the composer, re-run the
probes at the end of this file and update both the needles and this page.

## The one thing that breaks everything

`Input.dispatchMouseEvent` is delivered to a tab's render widget. **A widget that is not the
foreground tab of its window silently discards it** — the CDP call still returns
`{"result":{}}`, so the caller sees a successful click that the page never received. The
pipeline keeps one work tab, but a stale overlay or a second window is enough to lose input.

`_linux_cdp_commands` therefore prefixes any batch containing an `Input.*` method with
`Page.bringToFront` and waits `_BRING_TO_FRONT_SETTLE_SECONDS` before the first event.
`tests/test_cdp_input_focus.py` asserts the prefix, that it appears once, and that command
ids stay sequential so replies still match.

**Coordinates are CSS pixels.** Flow renders at `devicePixelRatio` 0.25 (layout viewport
7644×3952 on a 1920×1080 screen), which makes screenshots a quarter scale — but input is
unaffected. Scaling a click by the ratio lands it a quarter of the way into the page. An
instrumented `pointerdown` listener confirmed this: CSS coordinates hit the intended button,
scaled ones hit an unrelated `DIV`.

## There is no image-model picker

This is the discovery that most of the Gemini code had wrong.

* `button[data-test-id="bard-mode-menu-button"]` is the **text** mode picker. Its options are
  `3.5 Flash-Lite`, `3.8 Flash`, `3.1 Pro`, `Extended thinking`. No image model appears here.
* Image generation is a **tool**: `button[aria-label="Upload & tools"]` → menu item
  `Create image`. Once on, the composer carries a chip whose aria-label is
  `Deselect Images`, and that chip is how the code knows the tool is active.
* The only place the UI names the image model is the composer's zero-state line, in
  `span.subtitle-attribution`: **`Create with Nano Banana 2.`**
* **No Nano Banana Pro affordance exists.** A generated result offers exactly three
  controls: `Share image`, `Copy image`, `Download full size image`. There is no redo,
  regenerate, upgrade or quality control, so the `PRO_ACTION_VERBS` / `PRO_QUALITY_TOKENS`
  needles in `gemini_pro.py` have nothing to match. `find_pro_control` correctly returns
  `None`, and a `nano_banana_pro` request fails with `MODEL_NOT_AVAILABLE` quoting the
  attribution line rather than accepting a Nano Banana 2 image as if it were Pro.

The menu overlay is Angular Material, not Radix: the panel is `.cdk-overlay-pane`
containing `.mat-mdc-action-list`, and the tool entries are plain `button`s with no
`role=menuitem`. Selectors must include `.cdk-overlay-container button`; matching only
`.mat-mdc-menu-panel button` misses them. The upload rows render before the tools group, so
a cold page needs ~1.6s before `Create image` is present.

`_activate_gemini_image_tool` presses Escape first, because an overlay left open by an
earlier step turns the tools button into a close button and the click would toggle the menu
shut instead of opening it.

## Aspect ratio has to be asked for in words

The image composer has no aspect-ratio control. The requested ratio is stated in the prompt
by `_aspect_ratio_instruction` (`"a vertical 9:16 portrait frame (tall, phone-shaped …)"`)
and then **measured** on the downloaded file. A landscape answer to a 9:16 request is
rejected with `aspect_mismatch`; it is never cropped into compliance.

Observed: without the instruction, a 9:16 request produced 1024×559 and was refused. With
it, the same prompt produced 572×1024 and was accepted.

## What the receipt may claim

`GenerationReceipt` has a validator, so a claim without evidence cannot be persisted:

* `model_verified=True` requires `actual_model_label` — and that label is read from the
  attribution line, with `notes` recording `model_label_source=composer-attribution`.
* `pro_regeneration_used=True` requires a `pro_distinction=…` note proving a *new* asset id
  plus a different SHA-256 and dimensions. Nano Banana 2 can never be accepted as Pro.
* The image SHA-256 is computed on the downloaded bytes, and can also be computed in-page
  with `fetch(src)` → `crypto.subtle.digest` (`_linux_execute_javascript` runs with
  `awaitPromise: true`, so an async IIFE works).

A real completed job:

```json
{"requested_model": "nano_banana_2",
 "actual_model_label": "Create with Nano Banana 2.",
 "model_verified": true, "pro_regeneration_used": false,
 "requested_aspect_ratio": "9:16", "actual_aspect_ratio": "572:1024",
 "notes": ["model_label_source=composer-attribution",
           "image=…_output_1.png 572x1024 sha256=68655ea6…"]}
```

## Download validation (§32)

`image_validation.py` parses PNG/JPEG/WebP/GIF headers itself and asks `ffprobe` for a second
opinion. Rejections: `missing_file`, `too_small`, `undecodable`, `dimension_too_small`,
`aspect_mismatch`, `matches_uploaded_reference`, `duplicate_of_previous`, `stale_result`.
Result identity is the URL before `?`, since Gemini appends a transient query parameter.

Model labels are read only from the control or the attribution element, never from
`document.body.innerText` — the body text also contains model names sitting inside a closed
dropdown, which would "verify" a model that is not selected.

## Re-probing the UI

Run these when something stops matching. Neither spends anything.

```bash
cd /opt/YT_Video_Generation_Pipeline

# Is the image tool on, and what does the UI say the model is?
services/ordak/.venv/bin/python - <<'PY'
import sys, json; sys.path.insert(0,'services/ordak')
from app.automation.existing_chrome import ChromeTabRef, list_google_chrome_tabs
from app.automation import gemini_worker as gw
t=[x for x in list_google_chrome_tabs() if 'gemini.google.com' in (getattr(x,'url','') or '')][0]
r=ChromeTabRef(window_id=getattr(t,'window_id',0), tab_id=getattr(t,'tab_id',0), target_id=getattr(t,'target_id',None))
print(json.dumps(gw._read_image_tool_state(r), ensure_ascii=False, indent=1))
PY

# Does a Pro affordance exist yet? (expect None until Google ships one)
services/ordak/.venv/bin/python - <<'PY'
import sys; sys.path.insert(0,'services/ordak')
from app.automation.existing_chrome import ChromeTabRef, list_google_chrome_tabs
import app.automation.gemini_pro as gp
t=[x for x in list_google_chrome_tabs() if 'gemini.google.com' in (getattr(x,'url','') or '')][0]
r=ChromeTabRef(window_id=getattr(t,'window_id',0), tab_id=getattr(t,'tab_id',0), target_id=getattr(t,'target_id',None))
print('results:', [x.to_dict() for x in gp.read_result_identities(r)])
print('pro control:', gp.find_pro_control(r))
PY
```

After any change under `services/ordak/app`, run `systemctl restart ordak-api` — otherwise
the job runs the old code.
