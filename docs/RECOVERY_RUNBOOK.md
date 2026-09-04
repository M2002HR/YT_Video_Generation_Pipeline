# Recovery runbook

What to do when a run stops. The general shape: **read the stage, fix the cause, press
Resume.** Resume re-runs the same command, and every stage with a valid artifact plus a
recorded `DONE` state is reused — so nothing already paid for is bought twice.

```
panel → Resume on the run's row     (or)     POST /resume  job_id=<id>
```

## Where to look first

| Question | Where |
|---|---|
| Which stage stopped, and why | `videos/<id>/pipeline/QH_RUNTIME_STATE.json` → `stages` |
| The full console log | `control_panel/jobs/<job_id>.log` |
| Completion half | `videos/<id>/pipeline/FINALIZATION_RUNTIME_STATE.json` |
| What a provider actually did | `videos/<id>/pipeline/provider_receipts/*.json` |
| What Ordak saw in the browser | `GET /api/jobs/<job_id>` → `logs` |
| Live picture of the browser | noVNC on **4143** |

The Telegram thread also carries every stage start, completion and failure with its position
(`step 9/17 · World Keyframe`), so the last message before the silence names the stage.

## Failures by cause

### `FAILED_VALIDATION` on the script

```
The narration is 71 words; a 25–30s Short needs 57-75.
`body` has 6 beats; a 25–30s Short needs 5-8.
```

The word and beat ranges are derived from the requested duration, not fixed. If the range
itself looks wrong for the format, change the duration on the panel — do not widen the gate.
Resume re-asks ChatGPT for that stage only.

### `aspect_mismatch`

Gemini answered with the wrong shape. The requested ratio is stated in the prompt (Gemini has
no aspect control) and measured on the file. Resume re-asks; if it repeats, the prompt wording
in `_aspect_ratio_instruction` needs to be firmer. **Never crop to satisfy the check** — the
receipt would then describe a frame the provider did not produce.

### `MODEL_NOT_AVAILABLE`

The requested model is not what the UI names. For Gemini images the UI currently names only
Nano Banana 2; a `nano_banana_pro` request fails here by design. Set the panel's image model
to Nano Banana 2, or read `docs/ORDAK_GEMINI_BROWSER_AUTOMATION.md` and re-probe the UI.

### `MODEL_SELECTION_FAILED` / `MODEL_FEATURE_INCOMPATIBLE` (Flow)

A settings control did not change, or 720p was asked of a 360p-only model. Read the live
capabilities (free) with the probe in `docs/ORDAK_FLOW_BROWSER_AUTOMATION.md`, then set the
panel's Flow model/resolution to something the menu actually offers.

### `PROVIDER_UI_CHANGED`

A needle stopped matching. Two things cause it far more often than a real redesign:

1. **The tab was not in front.** `Input.*` is discarded for a background tab and the CDP call
   still succeeds. This is handled centrally now (`Page.bringToFront`), so if you see it in
   new code, check that the click goes through `dispatch_mouse_click` rather than a raw CDP
   batch.
2. **An overlay was left open.** A stray menu turns its opener into a close button.
   `_activate_gemini_image_tool` presses Escape first for exactly this reason.

### `login_required` / `manual_verification_required`

Open **4143**, sign in by hand in the visible Chrome, then resume. Note that Ordak keeps one
tab: the other two providers will read `idle (no tab)`, which is normal and not a problem.

### `FLOW_RECONCILIATION_REQUIRED`

A Flow generation may or may not have happened before a restart, and neither a new result nor
a downloaded file was found. **Do not resume blindly** — that risks 7 more credits. Open the
Flow project in noVNC, look at whether the clip exists, then either download it by hand into
`videos/<id>/assets/opening/` or resume knowingly.

### The stage says `RUNNING` but nothing is happening

The panel's background reconciler marks a `RUNNING` job whose pid is gone as `FAILED` within
30s, so the row settles by itself. If the pid is alive but stuck, watch 4143 — a provider
dialog waiting for a human is the usual reason.

## Narration, timing and music

* **No word timestamps** — the wrapper stops rather than trimming the opening clips against
  estimates: `alignment did not produce word-level timestamps plus OPENING_TIMING.json`.
  Re-run alignment; a beat whose tokens appear nowhere in the transcript is an error, not
  something to approximate.
* **ElevenLabs** — the narration is one continuous track (§66). If `assets/audio/narration.mp3`
  exists the wrapper reuses it and says so.
* **Music** — mixkit through the browser. A failed selection falls back to a **previously
  verified licensed local track** and says so loudly in Telegram; it never fabricates audio.

## Render and QC

`render_video.py` applies its own `nice`/`ionice` and a thread budget
(`--resource-budget`, default 0.8 of the machine) and writes `render/RENDER_STATS.json`.
Two QC gates run: baseline and polished. Publication happens only after both pass.

## Restarting the stack

```bash
systemctl restart ordak-api            # REQUIRED after any change under services/ordak/app
systemctl restart video-control-panel  # after changing the panel
systemctl restart ordak-chrome         # loses the tab, keeps the logins (profile on disk)
.venv/bin/python scripts/check_full_stack.py
```

Restarting Chrome is safe — the sessions live in `/root/.config/google-chrome-ordak`, not in
the process. Deleting that directory is what loses the logins.
