# Codex Goal — Stabilize Ordak and Prove the Topic-to-Images Video Pipeline

## Mission

Work autonomously inside this repository until the **ChatGPT-browser-based visual pipeline is actually working end to end on the real machine**, not merely implemented on paper.

The success target is intentionally narrow:

> Given a new English ~60-second video topic, the pipeline must use the existing Ordak browser-automation submodule and the user's configured authenticated Chrome profile to generate the script/planning artifacts and then generate **all visual beat images sequentially through the real ChatGPT web UI**, with robust recovery from slow/stalled browser/network states.

Stop the implementation at the completed-image stage.

**Do not implement ElevenLabs, voiceover, STT, timing, rendering, music, SFX, publishing, Gemini, or other unrelated pipeline work in this goal.**

This is a reliability/stabilization goal for the core text + image workflow only.

---

# 1. Read this context before changing code

Read these files first:

- `PROJECT_CONTEXT.md`
- `docs/ORDAK_INTEGRATION.md`
- `docs/ORDAK_BEAT_AUTOMATION.md`
- `services/ordak/README.md`
- `services/ordak/docs/browser-automation.md`
- `services/ordak/docs/development-and-testing.md`
- `prompts/01_script_writer.md`
- `prompts/02_retention_editor.md`
- `prompts/03_visual_beats.md`
- `prompts/04_single_beat_image_prompt_writer.md`
- `visual_presets/001_cinematic_storybook_green_hoodie/README.md`
- Video 001's `VISUAL_PRESET.md`, `VISUAL_BEATS.md`, beat prompts, and workflow docs

Treat Video 001 as a read-only reference implementation. Do not damage or overwrite it.

---

# 2. Repositories and branch discipline

Parent repository:

`M2002HR/YT_Video_Generation_Pipeline`

Ordak submodule:

`services/ordak`

Ordak upstream:

`AliBalash/ordak`

Ordak branch dedicated to this project:

`yt-video-pipeline`

Rules:

1. Make Ordak-specific browser/runtime changes on `yt-video-pipeline`, not on Ordak `master`.
2. If the submodule is detached, check out the dedicated branch and make sure it tracks the correct remote branch.
3. Commit Ordak changes inside the submodule first.
4. Then update the parent repository's submodule gitlink to the final Ordak commit.
5. Do not rewrite unrelated Ordak features.
6. Do not push to remote unless the user explicitly asks for a push. Local commits are fine and preferred for a clean handoff.
7. Generated beat images remain local/Git-ignored.

---

# 3. Hard scope boundaries

## In scope

- fixing Ordak startup on this machine
- root-controlled Ordak runtime configuration
- opening/attaching to the user's exact configured Chrome profile
- verifying ChatGPT login/session readiness
- ChatGPT text jobs through the real web UI
- ChatGPT multi-reference image generation through the real web UI
- reliable upload/submission/wait/download behavior
- timeout/stall/recovery state machine
- retry/reconcile/resubmit behavior
- parent-side Ordak client/orchestrator
- persistent/resumable pipeline state
- deterministic file naming
- technical image validation
- automated tests
- real-browser E2E tests
- one complete new Video 002 run from topic to all beat images
- repeated smoke/recovery tests proving the workflow is reusable

## Explicitly out of scope

Do **not** spend time on:

- Gemini
- direct OpenAI/ChatGPT APIs
- any official image-generation API
- ElevenLabs
- narration
- STT
- timing
- subtitles
- FFmpeg rendering
- music/SFX
- YouTube upload
- Docker/container redesign
- frontend redesign
- generalized multi-provider framework work
- concurrency or multi-video parallelism
- unrelated Ordak Agent/Ordex features
- replacing the existing visual preset
- creating new style/character anchors

If a change does not directly help the ChatGPT topic-to-images workflow become reliable, do not do it.

---

# 4. No shortcuts

The purpose is to validate the production workflow, not merely produce files.

Therefore:

- Do not manually write Video 002's final script/prompts as a substitute for browser automation.
- Do not generate Video 002 images with Codex itself.
- Do not use a direct model/image API.
- Do not copy Video 001 images.
- Do not fake successful Ordak jobs.
- Do not mark a browser E2E test passed based on mocks.
- Do not declare success after unit tests only.

Codex may inspect/edit code and test artifacts, but the production Video 002 text/image artifacts must be produced through **Ordak -> real ChatGPT web UI**.

---

# 5. Known startup blocker that must be fixed first

The current machine invoked Ordak with Python 3.10.19 and failed with:

```text
ImportError: cannot import name 'StrEnum' from 'enum'
```

Ordak documents Python 3.11+.

Do not paper over this by adding random compatibility hacks unless there is a strong reason.

Preferred solution:

1. inspect available pyenv/system Python interpreters
2. use Python 3.11+ for Ordak in an isolated environment
3. create a deterministic Ordak virtualenv if needed
4. make setup/run scripts consistently use that interpreter
5. fail early with a clear actionable message if a compatible interpreter is unavailable

The parent pipeline may remain on its existing Python where possible. Ordak can have its own supported interpreter.

A good design may introduce something like:

```env
YT_ORDAK_PYTHON=...
```

or auto-detect a local Ordak venv, but the exact implementation is up to you.

Acceptance:

- `python scripts/run_ordak.py` must successfully start Ordak from the parent repository
- no `StrEnum` crash
- setup must be repeatable on a clean initialized checkout
- the required Python version must be clearly validated/documented

---

# 6. Root .env is authoritative

The parent root `.env` is the only authoritative runtime configuration for this integration.

Do not require the user to maintain a separate runtime `.env` in `services/ordak`.

Ordak already has support for `ORDAK_ENV_FILE`; preserve/improve that behavior.

Current real browser selection is configured in root env and must be honored exactly:

```text
YT_ORDAK_BROWSER_USER_DATA_DIR=/home/mhr/.config/google-chrome
YT_ORDAK_BROWSER_PROFILE_NAME=Profile 1
```

Do not hardcode these values into source code. Read them from root env.

Do not print the complete root env or secret API keys into logs.

---

# 7. Browser/profile requirement — critical

Codex/Ordak must operate against the user's **actual configured Chrome profile**, which is already authenticated to ChatGPT.

It must not silently fall back to:

- a fresh Playwright profile
- a new temporary Chrome profile
- `Default` when `Profile 1` was configured
- a logged-out profile
- Chromium instead of the configured Chrome profile unless explicitly required and still using the exact authenticated profile data

The runtime must be able to prove which profile it is using.

At minimum diagnostics/logs should show sanitized:

- Chrome executable
- user-data-dir
- profile directory/name
- automation attachment/control method
- ChatGPT login state

## Safe launch/attach behavior

Determine the most reliable Linux strategy on the real installed Chrome version.

Preferred order:

1. attach to a controllable already-running configured Chrome session
2. if Chrome is not running, safely launch the configured Chrome executable with the exact configured user-data-dir/profile and the required automation interface
3. if Chrome is running but cannot be controlled, do **not** silently launch another unrelated profile

Do not kill the user's unrelated Chrome processes without explicit permission.

If Chrome profile locking or modern Chrome remote-debugging restrictions require a different control technique, solve it inside the narrow Ordak browser layer and document the exact reason.

CDP/DevTools or Playwright are preferred over brittle screen-coordinate automation.

Do not broaden X11/desktop automation unless necessary to make this exact workflow stable.

---

# 8. ChatGPT-only provider scope

For this goal:

```text
provider = chatgpt
```

Gemini must not be used as fallback.

All production text/image generations for the E2E proof must occur at:

`https://chatgpt.com/`

or the configured `YT_ORDAK_CHATGPT_PROJECT_URL` if one is explicitly set.

The ChatGPT session must be verified as authenticated before starting expensive work.

If login expires, or ChatGPT shows a CAPTCHA/manual verification wall:

- do not attempt to bypass it
- mark the job as manual verification required
- preserve state
- exit with a precise message explaining what the user must do
- resume cleanly afterward

This should be the only normal class of blocker requiring user interaction.

---

# 9. Required browser reliability state machine

This section is mandatory.

The current environment can have unstable internet or a temporarily stale ChatGPT page. The automation must distinguish **slow active work** from a **real stall**.

A long-running image generation must not be killed merely because it has taken several minutes.

Implement/test a state model equivalent to:

```text
BROWSER_STARTING
ATTACHING
CHATGPT_LOADING
READY
UPLOADING_REFERENCES
READY_TO_SUBMIT
SUBMITTED
ACTIVE_GENERATION
RESULT_READY

STALLED
REFRESHING
RECONCILING
RESUBMITTING

COMPLETED
FAILED_RETRYABLE
FAILED_TERMINAL
MANUAL_VERIFICATION
```

Exact names can differ, but semantics must be explicit.

## Progress signals

Use multiple resilient signals instead of one brittle selector.

Examples:

- ChatGPT stop-generation control is visible
- busy/loading/progress indicators
- new assistant turn appeared
- assistant turn count changed
- response text length/content changed
- image-generation placeholder appeared/changed
- generated image count/source changed
- generation status text changed
- DOM state changed meaningfully

Use semantic/accessibility/data-testid selectors where possible. Avoid fragile deep CSS/nth-child selectors.

## Core rule

> **Active generation is not a stall.**

If ChatGPT is clearly still generating, keep waiting.

A stall timer should represent **no meaningful progress**, not elapsed wall-clock time alone.

## Suggested configurable starting values

The existing root defaults are:

```text
browser timeout                 180s
ChatGPT response timeout        600s
stable response                 5s
stall refresh window            90s
max stall refreshes             3
parent job wait                 900s
poll interval                   2s
```

You may tune these after real observation.

Add separate concepts if needed, for example:

- active-progress poll interval
- no-progress stall window
- refresh/reconcile timeout
- max resubmits
- very generous hard safety limit for one active generation

Do not use one timeout for all of these different meanings.

A reasonable hard safety limit can be 20–30 minutes per image, but an actively progressing generation should not be treated like a 90-second stall.

---

# 10. Refresh -> reconcile -> resubmit rule

This order is mandatory.

When a no-progress stall is detected:

## Step 1 — preserve context

Persist:

- job ID
- stage/beat
- attempt
- exact conversation URL if available
- baseline assistant turn count
- baseline generated image identities/count
- prompt/reference manifest
- timestamp
- error/recovery reason

## Step 2 — refresh/reopen same conversation

Refresh the current ChatGPT conversation or reopen the exact saved conversation URL.

Wait for the page/composer/session to become ready again.

## Step 3 — reconcile before resubmitting

The original request may have completed server-side while the local page was stale.

After refresh, inspect the conversation.

If the expected new assistant result/image now exists:

- extract/download it
- mark the exchange completed
- **do not submit the prompt again**

If ChatGPT is still actively generating:

- continue waiting
- **do not resubmit**

## Step 4 — only resubmit when truly idle and incomplete

Only if all of these are true:

- page is healthy
- ChatGPT is idle
- composer is ready
- no new valid result exists relative to the saved baseline
- the previous exchange is not visibly active

then resubmit the exact same logical job.

Resubmission must use the same prompt and same reference set.

Bound refreshes/resubmissions and preserve diagnostics when the limit is exceeded.

This avoids duplicate generations caused by blindly retrying a request that was merely slow.

---

# 11. Browser disconnect / network instability behavior

The workflow must survive recoverable failures such as:

- temporary internet loss
- ChatGPT page becomes stale
- browser tab disappears
- browser/CDP connection resets
- input selector temporarily disappears
- upload preview takes a long time
- submit button is temporarily disabled
- image generation takes unusually long
- download control becomes available late

Expected behavior:

1. do not corrupt pipeline state
2. do not mark a beat done without a validated image
3. reattach/reopen exact conversation when possible
4. reconcile before resubmission
5. retry only the current stage/beat
6. keep previously accepted beats untouched
7. preserve screenshots/HTML/logs on terminal failure

Backoff should prevent rapid refresh loops.

---

# 12. Ordak multi-reference image generation must work

This is a core deliverable.

Current Video 001's visual consistency policy must be implemented for browser generation.

Use this existing preset:

`visual_presets/001_cinematic_storybook_green_hoodie`

Canonical references:

```text
visual_presets/001_cinematic_storybook_green_hoodie/style_anchor.png
visual_presets/001_cinematic_storybook_green_hoodie/character_anchor.png
```

## Beat 001 reference order

```text
1. style anchor
2. character anchor
3. optional video-specific recurring anchors
4. current beat prompt
```

## Beat 002+

```text
1. style anchor
2. character anchor
3. optional video-specific recurring anchors
4. previous ACCEPTED beat image
5. current beat prompt
```

The canonical anchors always outrank the previous beat for identity/style.

A rejected, incomplete, broken, or technically invalid image must never become the next beat's previous-image reference.

## Multiple uploads

Extend Ordak and its HTTP API/client as needed so one image-generation job can upload **multiple reference images** reliably.

Maintain backward compatibility where easy, but do not waste time on unrelated API generalization.

The worker must confirm that all expected reference attachments are present/ready before submitting.

If useful, stage references with deterministic descriptive filenames so their intended role is clear.

---

# 13. Generated image extraction/download requirements

Do not use a browser screenshot as the generated beat output.

Prefer the highest-quality generated asset that ChatGPT exposes, for example:

- real download action
- original image resource
- blob/resource extraction through the browser session

The saved output must be an actual generated image file.

For every accepted image validate:

- file exists
- file size is non-trivial
- image decodes successfully
- width/height are recorded
- landscape aspect is approximately 16:9
- it is not an exact duplicate of the previous accepted beat
- SHA-256 is recorded in runtime state
- only one canonical output is accepted for that beat

If ChatGPT returns several artifacts, select exactly one according to a documented deterministic rule or explicitly fail/retry if the intended artifact cannot be determined safely.

Do not crop a storyboard/grid into a beat. The requested output is one standalone image.

---

# 14. Parent pipeline must own workflow state

Ordak is the browser executor.

The parent repository must own video-domain state and sequencing.

Implement a small reusable parent-side Ordak client/orchestrator instead of importing Ordak's internal automation modules directly.

Use the Ordak local HTTP/job API.

The orchestration must be resumable.

A state record should contain enough information to reconstruct work, conceptually:

```json
{
  "beat_id": 7,
  "status": "DONE",
  "prompt_path": "beats/BEAT_007_PROMPT.md",
  "references": [
    ".../style_anchor.png",
    ".../character_anchor.png",
    "assets/raw_beats/beat_006.png"
  ],
  "attempts": 2,
  "output_path": "assets/raw_beats/beat_007.png",
  "output_sha256": "...",
  "ordak_job_id": "...",
  "last_error": null
}
```

Do not commit secrets or private ChatGPT conversation URLs in permanent project metadata.

Transient state/logs may be local/Git-ignored.

---

# 15. Resume/idempotency requirements

The pipeline must behave like a build system.

If beats 001–006 are complete and the process dies on 007:

- restart must detect 001–006 are already valid
- do not regenerate or overwrite them
- resume 007
- beat 008 must wait until 007 is accepted

Running the same command again after full success must be effectively idempotent:

- validate existing outputs
- skip completed beats
- do not create duplicate files
- do not spend browser generations unnecessarily

Provide an explicit force/regenerate mechanism for intentional replacement, but default behavior must preserve accepted work.

---

# 16. Text pipeline to automate

For a new topic the pipeline must use ChatGPT through Ordak to produce the planning artifacts.

Use the existing prompt templates rather than replacing them with hardcoded one-off prompts.

Required logical stages:

```text
TOPIC
  -> script draft/final
  -> retention edit
  -> visual beats
  -> per-beat image prompts
  -> sequential images
```

Keep all important state in files.

Do not rely on old ChatGPT conversation memory for correctness.

Each stage should be self-contained enough to run in a new conversation if necessary.

## Parsing/validation

Text responses must be parsed and validated.

For example:

- final script is non-empty and approximately one minute of English narration
- visual beats have unique sequential IDs
- expected beat count is consistent
- each beat has narration meaning + visual direction
- every beat gets exactly one prompt file
- prompt files explicitly request one standalone landscape image
- prompt files preserve the selected style/character continuity rules

If a text batch is malformed, retry that text stage/batch rather than continuing with corrupt state.

---

# 17. Required generic CLI

Create one clear reusable command for running from a topic to completed images.

The exact filename may differ, but the user should end up with an interface equivalent to:

```bash
python scripts/run_visual_pipeline.py \
  --topic "Why You Forget Why You Walked Into a Room" \
  --video-id 002 \
  --preset 001_cinematic_storybook_green_hoodie
```

The command must:

1. verify Ordak/Chrome/ChatGPT readiness
2. create the video project directory
3. generate the script through ChatGPT/Ordak
4. retention-edit it through ChatGPT/Ordak
5. generate visual beats
6. generate per-beat image prompts
7. generate all beat images sequentially
8. validate outputs
9. persist progress
10. resume correctly after interruption
11. produce a final visual-pipeline verification report

Do not require manual browser clicking during a healthy run.

---

# 18. Video 002 — mandatory real E2E proof

After implementation and smoke tests, prove the system by creating a new project from scratch.

Use this exact test topic:

> **Why You Forget Why You Walked Into a Room**

Use English.

Target narration length:

- approximately 55–65 seconds
- roughly 125–155 spoken words
- engaging psychology/neuroscience short
- no medical diagnosis/medical advice

Use the same existing visual preset and protagonist as Video 001:

`001_cinematic_storybook_green_hoodie`

Expected project slug:

`videos/002_why_you_forget_why_you_walked_into_a_room`

The orchestrator may create the directory.

The final image-stage project should contain artifacts equivalent to:

```text
videos/002_why_you_forget_why_you_walked_into_a_room/
  BRIEF.md
  SCRIPT_FINAL.md
  VISUAL_BEATS.md
  VISUAL_PRESET.md
  beats/
    BEAT_001_PROMPT.md
    ...
  assets/
    raw_beats/
      beat_001.png
      beat_002.png
      ...
```

Three-digit beat naming is preferred for new automated projects because this pipeline will later scale to 100–300+ beats.

The exact number of beats may be selected by the visual-beat planner, but for a ~60-second short it should normally be in a sensible range such as 14–20 beats.

Do not create audio or render output for Video 002 in this goal.

**The primary E2E success point is: every planned beat has one valid locally saved image generated through the real ChatGPT UI.**

---

# 19. Automated test requirements

Do not rely only on manual E2E testing.

Add/extend focused automated tests for the failure-prone parts.

At minimum test:

- Python/runtime selection for Ordak
- root env mapping
- exact browser profile configuration
- multi-reference upload handling
- attachment readiness verification
- submit retry
- active-generation detection
- no-progress stall detection
- refresh behavior
- reconcile-before-resubmit
- resubmit only when idle/incomplete
- bounded recovery attempts
- browser/tab rebind
- text result baseline detection
- generated-image baseline/delta detection
- output extraction validation
- parent pipeline resume
- skip already completed beats
- failed beat blocks next beat
- rejected/invalid image is not used as previous reference

Use mocks/fakes for deterministic regression coverage, but these do not replace real-browser tests.

Run the full relevant Ordak and parent test suites after changes.

---

# 20. Real-browser test matrix — mandatory

Before the full Video 002 run, perform real browser tests against the configured authenticated profile.

## Test A — readiness

- start Ordak using parent launcher
- Chrome is controlled using exact configured profile
- ChatGPT is logged in
- `scripts/check_ordak.py` passes

## Test B — text smoke

Submit a harmless deterministic text request through Ordak.

Verify:

- new assistant turn detected
- response extracted
- no manual clicking
- job reaches terminal success

## Test C — single image smoke

Generate one simple disposable landscape image through ChatGPT UI.

Verify:

- request submitted
- active generation is detected
- actual generated image downloaded
- image decodes
- not a screenshot artifact

## Test D — multi-reference image smoke

Use the real style + character anchors in one generation request.

Verify both attachments are ready before submit and one generated output is downloaded.

## Test E — 3-beat sequential continuity smoke

Generate a temporary 3-beat chain:

- Beat 1 uses style + character
- Beat 2 uses style + character + Beat 1
- Beat 3 uses style + character + Beat 2

Verify the reference manifest is correct and outputs are distinct/valid.

## Test F — interrupted/restart resume

Interrupt a multi-beat smoke after at least one accepted beat, restart the runner, and verify it resumes without regenerating completed beats.

## Test G — unstable/stalled connection recovery

Exercise the recovery logic in a controlled manner.

Prefer a tab-scoped/devtools network throttle/offline injection if safely available rather than disrupting the entire machine.

Prove at least one real browser job can survive a temporary stale/offline condition and recover.

Verify from logs that it follows:

```text
stall
-> refresh/reopen
-> reconcile
-> continue or resubmit only if needed
-> success
```

Do not claim this test passed if only a mocked timeout test was run.

If the exact Chrome control method cannot safely inject network failure, use the closest real-browser failure injection possible and document the limitation precisely.

---

# 21. Reliability repetition requirement

One successful run is not enough.

Before declaring the system stable:

1. run the 3-beat sequential smoke successfully
2. run it again from a clean temporary project/conversation
3. run it a third time

All three should complete without manual browser intervention under normal connectivity.

Then run the full Video 002 topic-to-images workflow.

After Video 002 completes, rerun the same command and verify idempotent skip/resume behavior without regenerating accepted images.

---

# 22. Technical image QC report

Produce a machine-readable final report for Video 002, for example:

`videos/002_why_you_forget_why_you_walked_into_a_room/visual_pipeline/VISUAL_QC_REPORT.json`

It should include at least:

- passed
- topic
- total planned beats
- total valid images
- missing beats
- invalid beats
- per-image path
- dimensions
- aspect ratio
- file bytes
- SHA-256
- generation attempt count
- whether previous-beat reference was required/present
- overall completion status

Do not include secrets or sensitive browser/session tokens.

A small Markdown run summary is also useful.

---

# 23. Failure artifacts / observability

On terminal browser failures, preserve enough evidence to debug without guessing:

- timestamp
- stage/beat
- job ID
- recovery attempt number
- sanitized current URL
- screenshot
- relevant DOM/HTML snapshot if safe
- browser/ChatGPT detected state
- last meaningful progress timestamp
- last error
- exact next recommended action

Do not let storage grow without bound; use Ordak's retention conventions.

---

# 24. Creative continuity verification

This goal is primarily infrastructure reliability, but the full Video 002 proof should also be visually sensible.

Inspect at least:

- Beat 001
- one early continuity pair
- one middle continuity pair
- final beat

Confirm:

- same recognizable green-hoodie protagonist when protagonist is present
- same cinematic storybook rendering family
- no accidental storyboard grids
- no obvious unwanted text/captions
- previous beat is used for continuity without simply duplicating the previous scene

Do not build a large ML visual-QC subsystem for this goal.

If an output is clearly broken, regenerate only that beat and keep the last accepted previous beat as the reference.

---

# 25. Definition of Done — do not stop before this

You may declare this goal complete only when **all applicable items below are true**:

- [ ] Ordak starts successfully under a supported Python 3.11+ runtime on this machine.
- [ ] Parent root env remains authoritative.
- [ ] Exact configured Chrome user-data-dir + `Profile 1` are used.
- [ ] No silent fresh/logged-out profile fallback exists.
- [ ] Ordak health/diagnostics pass.
- [ ] ChatGPT login readiness is verified.
- [ ] ChatGPT text job succeeds through real UI.
- [ ] ChatGPT image job succeeds through real UI.
- [ ] Actual generated image is downloaded, not a screenshot.
- [ ] Multi-reference upload works.
- [ ] Style + character anchors can be uploaded together reliably.
- [ ] Previous accepted beat can be added as a third continuity reference.
- [ ] Active generation is distinguished from a stall.
- [ ] No-progress stall refresh exists.
- [ ] Refresh reconciles before resubmitting.
- [ ] Browser/tab recovery works.
- [ ] Recovery attempts are bounded/configurable.
- [ ] Parent pipeline state is resumable.
- [ ] Completed beats are not regenerated on restart.
- [ ] A failed beat blocks dependent later beats.
- [ ] Automated regression tests pass.
- [ ] Real-browser text smoke passes.
- [ ] Real-browser single-image smoke passes.
- [ ] Real-browser multi-reference smoke passes.
- [ ] Real-browser 3-beat sequential smoke passes three times.
- [ ] At least one real-browser stall/network recovery scenario is exercised.
- [ ] Video 002 is created from the specified topic through Ordak/ChatGPT.
- [ ] Video 002 has a valid ~60-second final script.
- [ ] Video 002 has valid visual beats.
- [ ] Video 002 has a prompt for every beat.
- [ ] Video 002 has one valid generated image for every beat.
- [ ] Video 002 visual QC report passes.
- [ ] Re-running Video 002 pipeline skips already accepted images.
- [ ] Ordak changes are committed on `yt-video-pipeline`.
- [ ] Parent submodule pointer references the final tested Ordak commit.
- [ ] No Video 001 artifacts were damaged.
- [ ] No ElevenLabs/Gemini/rendering scope creep was introduced.
- [ ] Final handoff report documents exact commands, test results, remaining limitations (if any), and commit SHAs.

If any real-browser acceptance item has not actually been exercised, mark it **NOT VERIFIED** and continue working rather than calling the project complete.

---

# 26. Final handoff file

At the end create:

`docs/CODEX_ORDAK_VISUAL_PIPELINE_RESULT.md`

Include:

1. final architecture
2. exact Python/browser runtime used
3. Ordak branch + commit SHA
4. parent commit SHA
5. commands to install/start/check/run
6. automated test results
7. real-browser test matrix with PASS/FAIL
8. Video 002 beat/image count
9. visual QC result
10. resume/idempotency test result
11. stall-recovery test evidence
12. any remaining known limitation

Keep it factual. Do not say "stable" or "complete" unless the Definition of Done above is satisfied.

---

# 27. Working style

Do not stop after producing a plan.

Use this loop:

```text
inspect
-> implement
-> run tests
-> start real browser workflow
-> observe actual failure
-> capture evidence
-> fix root cause
-> rerun
-> repeat until acceptance passes
```

Prefer fixing root causes over adding arbitrary sleeps.

Do not ask the user to manually test each intermediate change.

Only request human action if truly unavoidable, such as:

- ChatGPT login expired
- CAPTCHA/manual verification
- Chrome profile is locked by another process and cannot safely be controlled without closing it
- an OS-level installation needs explicit privilege/approval

When that happens, state one precise action, preserve all state, and resume after it is done.

The final target is not "the code looks correct."

The final target is:

> **A repeatable command can take a new topic and, using Ordak + the user's real authenticated ChatGPT browser profile, reliably produce all sequential visual beat images with the existing character/style and recover safely from realistic browser/network stalls.**
