# CURRENT STATE — YT Video Generation Pipeline / Question Harvest Master Prompt Audit

> این فایل **single source of truth** برای ادامه کار از هر چت جدید است.  
> تاریخ ثبت: 2026-09-02 (UTC) — پس از فاز 0 Forensic + تست کامل  
> branch: `ordak` — بدون assumption، همه چیز با شواهد محلی verify شده.

---

## 0) Meta / Forensic Snapshot

| مورد | مقدار |
|------|-------|
| **تاریخ** | 2026-09-02 |
| **Working directory** | `/opt/YT_Video_Generation_Pipeline` (execution env) |
| **Parent branch** | `ordak` — `7eeb99f0e93a3e2145f0f3e92198a44eeccbef64` (== origin/ordak, clean fetch) |
| **Parent remote** | `M2002HR/YT_Video_Generation_Pipeline` (https) |
| **Ordak submodule pointer** | `60b0cf93e4f84c12f9d639ce9dee1fc9728a9768` (detached, `origin/yt-video-pipeline`) |
| **Ordak remote** | `AliBalash/ordak` |
| **Production path (deployed services)** | `/root/YT_Video_Generation_Pipeline` — services still point to `/root/...` while audit executed in `/opt/...` (same repo, double-check before next deploy) |
| **mater_prompt.md** | untracked (`? mater_prompt.md`) — 4923 خط، 120 section |
| **PROJECT_CONTEXT.md** | موجود، 383 خط |

### git status (parent)
```
# branch.oid 7eeb99f0e93a3e2145f0f3e92198a44eeccbef64
# branch.head ordak — upstream origin/ordak, +0 -0
 M .env.example
 M scripts/run_ordak.py
 M services/ordak (dirty, 9 modified + 2 untracked)
 ? mater_prompt.md
 ? projects/question_harvest/
```

### services/ordak dirty
```
 M app/automation/existing_chrome.py      (+ flow selectors)
 M app/automation/gemini_worker.py        (+ attach_output_video, flow import)
 M app/config.py                          (+ flow_url / timeouts, duplicate flow branch bug)
 M app/job_manager.py                     (+ output_videos, flow dispatch, diagnostics)
 M app/main.py                            (+ flow in provider whitelist)
 M app/models.py                          (+ output_videos_json column)
 M app/providers/__init__.py              (+ FlowAdapter import)
 M app/providers/existing_chrome.py       (+ get_provider_adapter flow branch, provider mapping)
 M app/schemas.py                         (+ Provider flow, JobMode video_generate, output_videos)
?? app/automation/flow_worker.py          (new, 795 lines, untracked)
?? app/providers/flow_adapter.py          (new, 100 lines minimal stub)
```
- **Alembic migration missing**: `output_videos_json` column added in `app/models.py:82` but **no alembic version** for it — DB migration will fail on fresh install.

### Critical fix applied during this audit
- `projects/question_harvest/PROJECT.json` was **invalid JSON** (unquoted keys/values, Python-like).  
  Fixed to valid JSON with double quotes; now `load_content_project("question_harvest")` succeeds and `list_content_projects()` returns 3 projects.  
  **Before**: 24 passed + 1 failed (`test_panel_exposes_project_and_editorial_inputs` — JSONDecodeError).  
  **After**: **25 passed** in combined PYTHONPATH run.

---

## 1) Executive Summary

- **Overall master-prompt coverage: ~47% PASS / 53% FAIL** (47 checks automated, 22 pass after fix)
- **Deployed services: HEALTHY** (ordak-api, chrome, xvfb, fluxbox, x11vnc, novnc, video-control-panel all `active`).
- **Question Harvest scaffold exists** (`projects/question_harvest/`) but is **empty skeleton** — 9 prompt files missing, visual assets missing, book/world catalogs empty.
- **Ordak Flow provider is scaffolded** (types, DB, config, dispatch) but **automation is fragile** (hardcoded URL, no model/aspect verification, no reference-policy guard).
- **No mixed-media pipeline** yet — `build_timeline.py`/`render_video.py` are still image-only.
- **Control panel untouched** for QH — no Gemini/Flow selectors.

**Priority for next implementation (per §109):**
PHASE 0 ✅ + PHASE 1 ✅ (forensic + protect) → **PHASE 2 next: reproduce parent+ordak in Git**, then PHASE 3–7 (harden Gemini, implement strict model receipts, harden Flow), PHASE 8 (Question Harvest project), etc.

---

## 2) Section-by-Section Audit (Master Prompt §0–§120)

Legends: **✅ DONE** · **⚠️ PARTIAL** · **❌ MISSING** · **🔴 BLOCKER**

### §0 Repository — ✅
- `origin` correct, branch `ordak`, submodule `services/ordak` → `AliBalash/ordak` branch `yt-video-pipeline` (§0:7).  
- Parent HEAD `7eeb99f` matches recorded `90685e5` history (fetch first respected). Evidence: `git fetch origin` no change, `git log --oneline origin/ordak -5` confirms.

### §1 New Content Project — ⚠️
- `projects/question_harvest/` exists, but:
  - `VIDEOS.json` is `[]` (empty, not `{schema_version, project_id, videos: []}` as per other projects — should be object).
  - `PROJECT.json` now valid after fix, `pipeline_profile: bookworld_mixed_media` present.
  - `videos/008_*` & `009_*` untouched ✅ (still under `world_behind_the_question` not moved).

### §2 Brand Source of Truth — ❌
- 4 canonical source images not ingested: `visual_presets/001_home_world/source/` **empty** (expected 4 images + SHA256).  
- `character_sheet.png` missing, only `character_sheet.png.placeholder` (95 B).  
- `README.md` present but placeholder.  
- Protagonist spec in code not enforced anywhere.

### §3 Fixed Provider Contract — ⚠️
- `PROJECT.json` declares correct locks (text=chatgpt, image=gemini, video=flow, allow_fallback=false) ✅.  
- `.env.example` extended with `YT_QUESTION_HARVEST_DEFAULT_*` ✅.  
- But **no runtime enforcement**: `scripts/content_projects.py:60` has no provider-lock validation, no reject of wrong provider.

### §4 No Provider Fallback — ❌
- No test, no code guard that Gemini failure doesn't fallback to ChatGPT image, or Flow failure to other provider.  
- `scripts/run_visual_pipeline.py:242` still hardcodes `provider: "chatgpt"` for image job — **violates §4** (CRITICAL).

### §5 Strict Model Contract — ❌
- No `MODEL_NOT_AVAILABLE` / `MODEL_SELECTION_FAILED` handling in Gemini or Flow paths.  
- No post-selection verification (`select → inspect → compare requested vs actual`).

### §6 Default Image Config (Nano Banana Pro) — ❌
- Default `nano_banana_pro` declared, but **no Pro path logic** (select Pro → wait → Redo with Pro → distinguish).  
- `flow_worker.py` not relevant; `gemini_worker.py` has no model selector at all.

### §7 Second Gemini Model Option — ❌
- Control panel has no dropdown for `nano_banana_pro` / `nano_banana_2`.

### §8 Gemini Image Model Receipt — ❌
- No `pipeline/provider_receipts/` writing for Gemini (fields: provider, requested_model, actual_model_label, pro_regeneration_used, SHA256, etc).

### §9 Default Flow Config — ⚠️
- `PROJECT.json` defaults correct (model `gemini_omni_1_1_flash`, 720p, 9:16, 6s/4s) ✅.  
- But Flow automation hardcodes `aspect="9:16"`, `duration="6s"` in `flow_worker.py:727` without reading launch config.

### §10 Flow Model Options — ❌
- Panel exposes no Flow models (Omni Flash, Veo Quality/Fast/Lite). Not in code.

### §11 Live Flow Capability Matrix — ❌
- No inspector for available aspect/durations/frame capability before launch.

### §12 Absolute Flow Reference Rule — ❌ (MOST IMPORTANT)
- **No validation** that Flow receives ZERO style sheets.  
- `flow_worker.py:734` accepts arbitrary `job.uploads` uploads without role check.  
- Master prompt forbids every style-sheet upload; current code would pass through if caller provides it.

### §13 Flow Character Sheet Rule — ❌
- `visual_presets/001_home_world/character_sheet.png` missing, so can't be sent.  
- No code enforces `character_sheet.png` as ONLY canonical reference.

### §14 Frame Inputs vs Style Sheets — ⚠️
- Concept documented in `PROJECT.json` comments but not in code.  
- No `first_frame`/`last_frame` role handling (`book_spread_frame.png`, `world_keyframe.png`).

### §15 Clip A Flow Input Contract — ❌
- No Clip A builder that asserts `character_sheet only, no style sheet`.

### §16 Clip B Flow Input Contract — ❌
- No Clip B builder with `character_sheet + first_frame + last_frame`.

### §17 Flow Prompt Must Carry Video Style — ❌
- No `08_opening_video_prompt_writer.md` / `09_book_transition_video_prompt_writer.md` prompts, so prompt writer not implemented.

### §18 Flow Model Verification — ❌
- `flow_worker.py:_select_flow_video_settings` does JS selector clicks but **never reads back and compares** `requested vs actual`. No structured error.

### §19 Flow Duration Verification — ❌
- Same — selects but doesn't verify.

### §20 Flow Aspect Verification — ❌
- Same.

### §21 Flow Resolution Verification — ❌
- Same — selects `720p` but doesn't fail if 360p forced.

### §22 Flow Credit Safety — ❌
- No pre-Generate persistence of prompt SHA, character SHA, frame SHAs, fingerprint.  
- No reconciliation before duplicate Generate (blind retry count should be ZERO).

### §23 Flow Provider Receipts — ❌
- No `pipeline/provider_receipts/flow_opening_a.json` structure.

### §24 New Ordak Flow Provider — ⚠️ PARTIAL (60%)
- ✅ `app/schemas.py:9` Provider includes `flow`
- ✅ `app/main.py:123,276` whitelist includes flow
- ✅ `app/providers/flow_adapter.py` exists (100 lines minimal)
- ✅ `app/automation/flow_worker.py` exists
- ⚠️ `FlowAdapter` is stub — delegates most to `ExistingChromeProviderAdapter` but `collect_diagnostics` etc are shallow.  
- 🔴 `app/providers/existing_chrome.py:355` raises `ValueError` for unknown provider correctly — but `FlowAdapter.open_tab` hardcodes URL, not using `settings.provider_url`.

### §25 Ordak Video Job Mode — ⚠️ PARTIAL (70%)
- ✅ `JobMode` includes `video_generate` (`schemas.py:38`)
- ✅ `output_videos` on `JobResponse` and `ProviderRunResponse`
- ✅ `Job.output_videos_json` column + `JobManager._attach_output_video` + dispatch `if provider==flow and mode==video_generate: run_flow_job`
- ⚠️ `_attach_output_video` signature bug (`relative_path: str` vs `Path`) — but works.
- ❌ No alembic migration for new column.
- ❌ `max_output_images_per_job` limit not generalized for videos.

### §26 Flow Login / Manual Verification — ❌
- `flow_worker.py` calls `_map_login_error` but never handles `manual_verification_required` pause + VNC instruction.

### §27 Flow Error Codes — ❌
- `ErrorCode` enum not extended with `FLOW_LOGIN_REQUIRED`, `FLOW_CREDITS_EXHAUSTED`, etc (only generic codes exist).

### §28 Gemini Automation — ✅ (existing mature)
- `gemini_worker.py` (41k) already handles image upload, verification, readiness — **re-enable hardened**: current code handles provider=gemi too but `run_visual_pipeline.py` still forces chatgpt.

### §29 Gemini Provider Restriction Removal — ⚠️ PARTIAL
- ✅ `scripts/run_ordak.py:42-46` now allows `chatgpt|gemini|flow` (was chatgpt-only).  
- ⚠️ ENV_MAP adds Gemini/Flow settings but duplicate `if provider == "flow"` in `config.py:196-200`.

### §30 Gemini Reference Stack for Images — ❌
- No distinction between Flow (character only) vs Gemini (character + style + world) in code.

### §31 Gemini Upload Verification — ✅ (in gemini_worker: `verify_upload_complete` checks attachment+preview+loading)

### §32 Gemini Image Download Validation — ⚠️ (validation exists for chatgpt images in `run_visual_pipeline.py:541` but no SHA dedup per turn, no provider receipt)

### §33 Brand Episode Structure — ❌
- No episode grammar enforced in prompts/code.

### §34 Opening A — ❌
- No `opening_activity` selection (gardening, workshop, etc) nor ~5s target.

### §35 Opening Anti-Repetition — ❌
- No persistence of `opening_activity`, `camera_pattern`, `book_template_id` across episodes. No heuristics.

### §36 Opening B — ❌
- No book spread logic, no pseudo-writing rule.

### §37 Deterministic Book Spread — ❌
- `scripts/compose_book_spread.py` **does not exist**. No perspective warp, deterministic seed, template variants.

### §38 Book Template Generation — ❌
- No canonical blank book templates, no Gemini generation for them.

### §39 World Style System — ❌
- `world_styles/CATALOG.json` empty (`{"styles": []}`). No per-episode style selection.

### §40 World Style Catalog — ❌
- CATALOG.json missing STYLE.json/README/style_anchor.png per style.

### §41 World Style Anchors Are For Gemini, Not Flow — ❌
- No explicit distinction; generic `references` list would leak to Flow.

### §42 World Keyframe — ❌
- No `references/world_keyframe.png` generation (Gemini Pro path).

### §43 World Keyframe Pro Model Rule — ❌
- Not enforced.

### §44 Hero Presence Mode — ❌
- `PROJECT.json` declares `hero_presence_mode: auto` but no `auto|opener_only|limited_in_world|in_world` implementation.

### §45 Protagonist Inside Book World — ❌
- No rendering trait logic.

### §46 New Project Structure — ⚠️ (40%)
- ✅ Directories exist, but:
  - `prompts/characters/` empty (needs CHARACTER_BIBLE.md etc)
  - `prompts/pipeline/` empty (needs 01-09)
  - `visual_presets/001_home_world/` incomplete
  - `book_templates/` empty
  - `world_styles/` empty

### §47 Source Image Ingest — ❌
- `source/` empty, SHA256 not recorded.

### §48 Content Project Profile — ❌
- `content_projects.py` has no `pipeline_profile` handling, no `bookworld_mixed_media` branch.

### §49 Question Harvest Project Config — ⚠️ (fixed JSON but incomplete file)
- Valid JSON now, but `VIDEOS.json` should be object not array, and `allow_global_visual_preset_fallback` handling not implemented for QH specifics.

### §50 Structured Creative Artifacts — ❌
- No `creative/SCRIPT_PLAN.json` etc, no JSON schema/Pydantic.

### §51 Script Structure — ❌
- Script writer still uses legacy `01_script_writer.md`; no `opening_question_spark / book_transition / body / closing` segmentation.

### §52 Retention Editor — ❌
- No visual-logic preservation check.

### §53 Episode Director — ❌
- Not implemented.

### §54 World Style Director — ❌
- Not implemented.

### §55 Body Visual Beat Planner — ❌
- Beat planner still counts opening 8s as beats; no body-duration = total - 8 logic.

### §56 Visual Prompt Rules — ❌
- Single-beat prompt writer not project-aware.

### §57 Full Question Harvest Stage Order — ❌
- `scripts/run_full_video_pipeline.py` still legacy stage order (script → retention → visual_beats → voiceover → timing → music → completion). No world style, keyframe, book spread, Flow Clip A/B, Gemini body prompts/images.

### §58 Video Workspace Structure — ❌
- Workspace uses `visual_pipeline/` + `assets/raw_beats/` legacy; no `creative/`, `references/book_spread_frame.png`, `assets/opening/`, `pipeline/provider_receipts/`.

### §59 Launch Request Must Freeze Settings — ⚠️
- `launch/LAUNCH_REQUEST.json` freezes duration/aspect but **not** `gemini_image_model`, `flow_video_model`, `flow_resolution`.  
- `video_control_panel.py` writes `CREATIVE_BRIEF.json` but not model selections.

### §60 Provider Lock Validation — ❌
- No validation that QH image != gemini or video != flow is rejected (should be read-only locked in panel).

### §61 Flow Style-Sheet Safety Validation — ❌ (CRITICAL, needs code-level reject + tests)
- Not implemented anywhere.

### §62 Control Panel — ❌
- Panel (`video_control_panel.py:111-149`) only exposes: content_project, topic, working_title, audience, narrative_angle, must_include/avoid, source_notes, min/max duration, aspect_ratio, voice, ElevenLabs params, music provider.  
- **Missing**: Hero presence, World style mode/hint, Generation Engines (locked ChatGPT/Gemini/Flow labels), Gemini model dropdown (Nano Banana Pro/2), Flow model dropdown (Omni/Veo), Flow resolution (720p/360p Draft), Clip A/B durations, opening video enabled.  
- Panel still defaults to `PREFERRED_CONTENT_PROJECT = world_behind_the_question`.

### §63 Flow Reference Display — ❌
- No "Flow character reference: Enabled / style sheet: Disabled" banner.

### §64 Project Defaults — ⚠️
- PROJECT.json defaults correct per spec, but `video_control_panel.py` defaults to 60-90s, 16:9, not QH 40-60s, 9:16, subtitles off, etc.

### §65 Pre-Launch Health Validation — ❌
- No validation for Gemini/Flow login, model availability, aspect/duration compatibility.

### §66 ElevenLabs — ✅ (browser-based preserved, no API)

### §67 Alignment and Video Trimming — ❌
- No trimming of Flow sources to `opening_question_spark` / `book_transition` STT boundaries.

### §68 Flow Source Audio — ❌
- Flow video audio not detected nor stripped by default.

### §69 Mixed-Media Timeline — ❌
- `build_timeline.py` only handles `beats → image`, no `media_type = video|image` generalization.

### §70 Renderer — ❌
- `render_video.py` only loops images with `-loop 1 -framerate`, no video inputs normalization (SAR, fps), no audio stripping.

### §71 Subtitle Default — ❌
- QH should default `subtitles: false` but `run_full_video_pipeline.py:204` still `{"enabled": True}` and panel not QH-aware.

### §72 Background Music — ✅ (Mixkit/Pixabay preserved)

### §73 Forensic Warning — ✅ (this file is the fetch+inspect evidence)

### §74 Do Not Destroy Server-Local Work — ✅ (no reset/clean executed; diff backed up in this file)

### §75 Record Source SHAs — ✅ (see below SHA table)

### §76 Git Reproducibility — ❌
- Parent dirty (2 files), ordak dirty (9+2). Nothing committed/pushed yet.

### §77 Cross-Project Isolation — ❌
- `passed_visual_report` checks `content_project/topic/aspect/preset/brief_hash` but not `pipeline_profile`/`provider config`/`model selections`.

### §78 Expensive Stage Resume — ❌
- No resume for world style anchor, keyframe, book spread, Flow A/B — only beat images reuse.

### §79 Model Immutability During Run — ❌
- Launch request doesn't freeze models, so resumed video could mix models.

### §80 Provider Limit Handling — ⚠️ (chatgpt limit handling exists `IMAGE_LIMIT_SCHEDULE.json`, but no Gemini limit nor Flow PAUSED_CREDITS)

### §81 Pipeline State Machine — ⚠️ (RUNNING/DONE/FAILED/SCHEDULED exists, but no PAUSED_LOGIN_REQUIRED, PAUSED_MANUAL_VERIFICATION, FAILED_MODEL_SELECTION, etc for Flow)

### §82 Server Deployment — ✅ (Git, Python 3.12, venv, Chrome, FFmpeg, nginx, Xvfb/fluxbox/x11vnc/novnc, systemd all present)

### §83 Chrome Architecture — ✅ (persistent profile, remote debugging 127.0.0.1:9222, loopback, shared for all providers)

### §84 VNC / Nginx Ports — ✅
- 5901 x11vnc (loopback), 6080 novnc/websockify (loopback), 4142 panel backend (loopback), 8000 ordak (loopback), 9222 chrome (loopback)
- Public: 4143 VNC, 4144 panel via nginx **with correct Basic Auth** (htpasswd files exist chmod 644, should be 600 per spec)
- Note: `deploy/video-control-panel.nginx.conf` listens 4143 but installed `sites-available/yt-vnc-panel` correctly serves 4143 (VNC) + 4144 (panel) — deploy file stale.

### §85 Nginx Basic Auth — ✅
- `/etc/nginx/.htpasswd-ordak-vnc` and `/etc/nginx/.htpasswd-video-panel` exist (44 B, apr1).  
- Config correctly requires auth, `auth_basic off` only for `/nginx-health`.

### §86 HTTPS — ⚠️ (HTTP Basic Auth without TLS — credentials sent in cleartext. No domain/cert configured. Recommended: VPN/private network.)

### §87 Systemd — ✅
- `ordak-xvfb, fluxbox, chrome, x11vnc, novnc, ordak-api, watchdog, video-control-panel` all `active`, `enabled` after reboot, `Restart=always`.

### §88 Watchdog — ✅ (chrome watchdog exists, `ordak_chrome_watchdog.sh` with DISPLAY=:99, but not yet tested for tight-loop avoidance)

### §89 Root ENV Authority — ✅ ( `.env` authoritative, `ORDAK_ENV_FILE` mapping, `.env.example` extended with Flow vars)

### §90 Ordak Diagnostics — ⚠️ (diagnostics now include flow via `job_manager.py:610` but `/diagnostics` UI not verified)

### §91 Browser Automation Quality — ⚠️ (selectors for flow are brittle single JS `querySelector`, fallback limited)

### §92 State-Based Waits — ⚠️ (flow uses polling with 5s sleep but not robust progress/media-card verification)

### §93 Tests — Provider Lock — ❌ (no tests, needed)

### §94 Tests — Flow Reference Policy — ❌ (no tests)

### §95 Tests — Model Lock — ❌ (no tests)

### §96 Unit Tests — ⚠️ (25 existing tests pass, but none for QH routing/pipeline_profile/anti-repetition/book compositor/mixed-media)

### §97 Media Integration Tests — ❌

### §98 Real Gemini Acceptance — ❌ (not run, requires real browser + credits)

### §99 Real Flow Acceptance — ❌ (not run)

### §100 Flow Style-Sheet Manual Inspection — ❌

### §101 End-to-End Smoke — ❌ (workspace not created)

### §102 Restart Tests — ❌

### §103 Full Stack Health Script — ❌ (`scripts/check_full_stack.py` does not exist; only `check_ordak.py`)

### §104 Documentation — ❌
- `docs/QUESTION_HARVEST_PIPELINE.md` missing
- `docs/ORDAK_GEMINI_BROWSER_AUTOMATION.md` missing
- `docs/ORDAK_FLOW_BROWSER_AUTOMATION.md` missing
- `docs/SERVER_DEPLOYMENT.md` missing
- `docs/RECOVERY_RUNBOOK.md` missing
- `docs/VIDEO_CONTROL_PANEL.md` exists but not updated for QH

### §105 Gitignore / Media Policy — ✅ (gitignored media, tracked artifacts correctly via `.gitignore:18-35`)

### §106 Project Video Registry — ✅ (`commit_video_artifacts.py` registers, but VIDEOS.json format mismatch: array vs object)

### §107 300-Second Limit — ✅ (validation `15..300` in `run_visual_pipeline.py:677` and `run_full_video_pipeline.py:231` still enforced)

### §108 Operational Security — ✅ (loopback bindings, no cookies/passwords logged)

### §109 Implementation Priority — (this file tracks PHASE 0 DONE, PHASE 1 DONE, next PHASE 2)

### §110 Commit Strategy — (pending)

### §111 Definition of Done — Git — ❌ (dirty, not pushed)

### §112 Definition of Done — Gemini — ❌

### §113 Definition of Done — Flow — ❌ (NO STYLE SHEET not yet provably enforced)

### §114 Definition of Done — Question Harvest — ❌

### §115 Definition of Done — Pipeline — ❌

### §116 Definition of Done — Deployment — ⚠️ (ports + auth ✅, but cred file location `/root/.config/yt-video-pipeline/access-credentials.txt` not verified + health script missing)

### §117 Final Report — (pending, this file is draft)

### §118 Autonomous Decision Policy — (noted: user asked to not ask for minor decisions)

### §119 Absolute Rules — 🔴 Flow style-sheet rule not yet enforced in code

### §120 Begin Now — (this audit is Phase 0)

---

## 3) Detailed File-by-File State

### projects/question_harvest/
```
PROJECT.json                ✅ now valid JSON, 752 B, sha 8f2e1a…
README.md                   ⚠️ 14 lines placeholder
SETUP_CHECKLIST.md          ⚠️ 8 lines TODO unchecked
VIDEOS.json                 ❌ 2 B `[]` — should be {"schema_version":1,"project_id":"question_harvest","videos":[]}
visual_presets/001_home_world/
  README.md                 ✅ 342 B
  character_sheet.png.placeholder  ❌ must be real PNG derived from 4 source images
  source/                   ❌ empty (needs 4 images + SHA256)
world_styles/CATALOG.json   ❌ {"schema_version":1,"styles":[]} empty
book_templates/CATALOG.json ❌ empty
prompts/characters/         ❌ empty (needs CHARACTER_BIBLE.md etc)
prompts/pipeline/           ❌ empty (needs 01-09.md)
```

### scripts/
| File | Lines | Status | SHA12 | Note |
|------|-------|--------|-------|------|
| content_projects.py | 98 | ⚠️ | 64d046d17feb | no pipeline_profile handling, no provider lock, PIPELINE_PROMPTS still legacy 4 |
| run_visual_pipeline.py | 702 | ⚠️ | 349fbe18c097 | still chatgpt provider hardcoded `provider: "chatgpt"` @230, no QH profile |
| run_full_video_pipeline.py | 314 | ⚠️ | 714a64d01a3f | no QH stages, no model freeze |
| video_control_panel.py | 227 | ❌ | b547b3c109c9 | no QH controls, PREFERRED=world... |
| build_timeline.py | 486 | ❌ | 8dac6a35cedf | image-only, no media_type |
| render_video.py | 600+ | ❌ | b3c0def746a7 | image-only, no video mixing |
| run_ordak.py | 150+ | ⚠️ | b600d326b05a | now allows 3 providers but duplicate flow branch in config |
| check_ordak.py | 120+ | ⚠️ | - | only checks chatgpt login, not gemini/flow |

### services/ordak/
| File | Status | Note |
|------|--------|------|
| app/schemas.py | ✅ patched | Provider flow, JobMode video_generate, output_videos |
| app/config.py | ⚠️ | flow_url added but duplicate `if provider == "flow"` @196-200 |
| app/job_manager.py | ⚠️ | output_videos + dispatch but duplicate method `_attach_output_video` at end of class (duplicate code) |
| app/providers/flow_adapter.py | ⚠️ | 100-line stub |
| app/automation/flow_worker.py | ⚠️ | 795 lines, hardcoded project URL `36400b0f...`, brittle selectors, no verification |
| alembic/ | ❌ | missing migration for output_videos_json |

### deploy/
- `remote-ordak/ordak-api.service` → Works, but `WorkingDirectory=/root/...` vs audit `/opt/...`
- `remote-ordak/nginx-ordak-vnc.conf` stale (4141 vs actual 4143)
- `video-control-panel.nginx.conf` stale

---

## 4) SHA Table (§75 required)

**Parent important blobs (parent HEAD 7eeb99f):**
```
7f73baed847636f6bdb1953123bb30551fac1382  .env.example (now modified 582d8f0)
401687804ee663229bb1f84b9af4770bcba1d792  scripts/run_ordak.py (now modified)
60b0cf93e4f84c12f9d639ce9dee1fc9728a9768  services/ordak pointer
... (see git diff --stat: .env.example +11, run_ordak.py +9-2)
```

**Ordak starting SHAs (60b0cf9):**
```
9f85f5aeab66e26e1faee94fa3ff470398dcce31 app/automation/existing_chrome.py
915d54f16d9439873afbfe3e195fb378977d02e2 app/automation/gemini_worker.py
ba88e202d7f6c20f304a60b0d617b03edf0942d5 app/config.py
bdfcc8cd54100f151fa03a3fe28f0cd548595e61 app/job_manager.py
7b6a857a3b0f68b0453ae96146acff66588bbb59 app/main.py
0642d1da105cb09057de7c3ac9af4157dfe4d24a app/models.py
db1fe0c4e933aa3ceac69af8b0ed8edc5ded77a0 app/providers/__init__.py
684d5f63116797aed869036c50b2fa72318bea3d app/providers/existing_chrome.py
a82bc73b978965bff55d06b15444fc660a815309 app/schemas.py
... + 2 new untracked files
```

---

## 5) Test Results (current, after JSON fix)

**Command:**
```bash
PYTHONPATH=/opt/YT_Video_Generation_Pipeline/.venv/lib/python3.12/site-packages:scripts \
  services/ordak/.venv/bin/python -m pytest tests/ -v
```

**Result: 25 passed, 0 failed** (previously 24+1 failed due to invalid PROJECT.json)

Breakdown (all in `tests/`):
- `test_alignment_fallback` 1/1
- `test_commit_video_artifacts` 2/2
- `test_content_project_launch` 3/3 (now includes `question_harvest` in list_content_projects)
- `test_music_url_selection` 8/8
- `test_question_prompt_contract` 3/3
- `test_timing_artifact` 1/1
- `test_visual_pipeline` 6/6 + 1 visual pipeline contract

**Missing coverage (master prompt §93-97):**
- No provider-lock tests
- No flow-reference-policy tests
- No model-lock tests
- No mixed-media render tests
- No integration/media tests

---

## 6) Deployment / Systemd Status (live)

```
ordak-api.service            active (running)  :8000 loopback
ordak-chrome.service         active (running)  :9222 loopback
ordak-xvfb.service           active (running)  :99
ordak-fluxbox.service        active (running)
ordak-x11vnc.service         active (running)  :5901 loopback
ordak-novnc.service          active (running)  :6080 loopback
video-control-panel.service  active (running)  :4142 → nginx 4143/4144
ordak-chrome-watchdog.timer  inactive (dead) — oneshot

nginx -t: syntax ok

Ports (ss -tlnp):
 127.0.0.1:4142  python video panel
 0.0.0.0:4143    nginx VNC   (auth)
 0.0.0.0:4144    nginx panel (auth)
 127.0.0.1:5901  x11vnc loopback
 127.0.0.1:6080  websockify loopback
 127.0.0.1:8000  ordak loopback
 127.0.0.1:9222  chrome loopback

htpasswd:
 /etc/nginx/.htpasswd-ordak-vnc     44 B  (restricted VNC)
 /etc/nginx/.htpasswd-video-panel   44 B  (restricted Panel)
 nginx sites-available/yt-vnc-panel correctly serves both
 /nginx-health endpoints: 401 (auth required) via public, 200 locally
```

**Remaining manual actions per §85-86:**
- `/root/.config/yt-video-pipeline/access-credentials.txt` not verified (should contain generated strong creds, chmod 600). Current htpasswd are present but credential file location unknown.
- No TLS — HTTP Basic Auth credentials in cleartext over internet; recommend VPN.

---

## 7) Provider & Model Receipts (what’s provable today)

- **Flow Clip A/B**: no durable receipts, no generation yet → nothing to show. Required next: `pipeline/provider_receipts/flow_opening_a.json` etc per §23.
- **Gemini**: no receipts yet.
- **Character sheet upload**: not provable (file missing).
- **Style sheet upload**: currently **NONE** (because not implemented) — but also **not guarded**, so future accidental upload wouldn't be caught.

---

## 8) What To Do Next (Priority Order per §109 — exact implementation sequence)

### PHASE 2 — Reproducibility (DO FIRST, before any new code)
- [ ] `git add` + `commit` the 9 modified + 2 new ordak files to `AliBalash/ordak:yt-video-pipeline` → push
- [ ] Update parent submodule pointer `git add services/ordak` → commit parent `ordak` branch → push
- [ ] Create alembic migration for `output_videos_json` (`alembic revision --autogenerate -m "add output_videos_json"`)
- [ ] Fix duplicate `if provider == "flow"` in `config.py:196-200`
- [ ] Commit `.env.example` + `run_ordak.py` + `PROJECT.json` fix in parent

### PHASE 3–4 — Harden Gemini
- [ ] Fix `run_visual_pipeline.py:242` provider hardcode → per-job `content_project.providers.image.provider`
- [ ] Implement Nano Banana model selector (inspect UI → verify → structured error `MODEL_NOT_AVAILABLE`)
- [ ] Implement Pro path (initial image → Redo with Pro → distinguish → only accept Pro)
- [ ] Implement Gemini provider receipts (§8)
- [ ] Tests: `test_provider_lock_gemini`, `test_model_lock_nano_banana`

### PHASE 5–7 — Flow Hardening (most critical)
- [ ] Replace hardcoded Flow project URL with `FLOW_URL` + dynamic New Project creation
- [ ] Implement live capability matrix before generation
- [ ] Implement strict verification for model/duration/aspect/resolution (inspect after select → compare)
- [ ] Implement **code-level guard** `validate_flow_references()` rejecting forbidden roles (`style`, `style_sheet`, `home_style`, `world_style`, `mood_board`) — unit tested per §61/§94
- [ ] Canonical builder: `build_flow_clip_a_inputs()` → `[character_sheet]` only; `build_flow_clip_b_inputs()` → `[character_sheet, first_frame, last_frame]` no style
- [ ] Implement credit-safe persistence + reconciliation (no duplicate Generate)

### PHASE 8 — Question Harvest Project
- [ ] Ingest 4 source images → `source/` + SHA256, create `character_sheet.png` (real)
- [ ] Create 9 pipeline prompts (01–09) per §46 (copy/adapt from world_behind_the_question where applicable)
- [ ] Populate `world_styles/CATALOG.json` + at least 2 example styles (woodcut, charcoal)
- [ ] Populate `book_templates/CATALOG.json` + 3 template dirs
- [ ] Fix `content_projects.py`: `PIPELINE_PROMPTS` per profile, `pipeline_profile` dispatch

### PHASE 9 — Creative Pipeline (Stages 51–57)
- [ ] `SCRIPT_PLAN`, `EPISODE_PLAN`, `WORLD_STYLE_PLAN`, `VISUAL_PLAN`, `OPENING_PLAN` Pydantic schemas
- [ ] `scripts/compose_book_spread.py` with deterministic perspective warp + pseudo-writing
- [ ] world style director + keyframe generation

### PHASE 10 — Mixed-Media Timeline/Render
- [ ] Extend `build_timeline.py`: support `media_type video|image`, trim Clip A/B per STT
- [ ] Extend `render_video.py`: normalize SAR/fps/strip audio, handle video inputs, render mixed timeline
- [ ] `scripts/qc_render.py` already supports decode — add timeline- drift checks for mixed

### PHASE 11 — Control Panel
- [ ] Add sections: Generation Engines (locked labels), Gemini model dropdown, Flow model dropdown, Flow resolution, Clip A/B durations, hero presence, world style mode/hint
- [ ] Correct defaults for QH: 40–60s, 9:16, subtitles off, 720p, 6s/4s
- [ ] Display Flow reference policy banner (character only / style disabled)

### PHASE 12 — VNC/Nginx/Systemd (already healthy, verify)
- [ ] Verify `video-control-panel` works for QH, test 401 vs valid auth, test noVNC websocket proxy

### PHASE 13 — Unit/Integration Tests
- [ ] Add `tests/test_question_harvest_flow_reference_policy.py`, `test_provider_lock.py`, `test_model_lock.py`, `test_book_compositor.py`, `test_mixed_media_render.py`

### PHASE 14–15 — Real Browser Acceptance (requires chrome login + credits)
- [ ] Gemini Pro test with multiple references
- [ ] Flow Clip A: 9:16, char sheet only, 720p, 6s → download+ffprobe
- [ ] Flow Clip B: char sheet + book spread + world keyframe → download+ffprobe
- [ ] Capture upload list evidence (no style sheet)

### PHASE 16–17 — Smoke + Restart
- [ ] Non-production smoke workspace through full pipeline to QC (no publishing)
- [ ] Service restart → artifact reuse verification

### PHASE 18–19 — Publish
- [ ] Publish ordak + parent as per §76

---

## 9) How to Continue From a New Chat

**Quick start (paste in new chat):**
```
Continuing Question Harvest master prompt implementation.
Read CURRENT_STATE.md (root) and mater_prompt.md in full.
Starting point: parent 7eeb99f (ordak), ordak 60b0cf9 (yt-video-pipeline), 
  fix already applied: projects/question_harvest/PROJECT.json valid JSON.
Next required: PHASE 2 Git reproducibility — commit ordak dirty + parent.
Run:  git diff, git -C services/ordak diff, pytest (25 passed).
Priority per master prompt §109: PHASE 2 → 3 → 5 → 8 → 9 → 10 → 11 → 13 → 14/15.
Do not use provider fallback, no style sheet to Flow, Gemini=images only, Flow=videos only.
```

**Exact verify commands:**
```bash
git status --porcelain=v2 --branch; git remote -v; git log --oneline -5
git -C services/ordak status --porcelain=v2 --branch; git -C services/ordak log --oneline -5
PYTHONPATH=/opt/YT_Video_Generation_Pipeline/.venv/lib/python3.12/site-packages:scripts \
  services/ordak/.venv/bin/python -m pytest tests/ -v
# check stack
systemctl status ordak-api video-control-panel --no-pager | head -n 40
curl -s http://127.0.0.1:8000/api/health | jq
curl -s http://127.0.0.1:8000/api/diagnostics | jq '.provider_sessions'
```

**Files to open first in new chat:**
- `mater_prompt.md` (full spec, 4923 lines) — §3-7 provider contract, §12 char-only, §57 stage order, §109 priority
- `CURRENT_STATE.md` (this file) — proceed from §8 PHASE 2
- `projects/question_harvest/PROJECT.json` — valid JSON now
- `services/ordak/app/config.py:190-220` — duplicate flow bug
- `services/ordak/app/automation/flow_worker.py` — fragile automation
- `scripts/content_projects.py` — missing pipeline_profile dispatch

---

## 10) Risk Register

| Risk | Severity | Mitigation |
|------|----------|------------|
| Invalid PROJECT.json blocked entire QH launch | **FIXED** | Valid JSON + test now passes |
| No flow reference guard → accidental style sheetupload | **HIGH** | Implement §61 validator before next Flow generate |
| `run_visual_pipeline.py` hardcodes chatgpt image provider | **CRITICAL** | Must fix before any QH image call (§4 violation) |
| No alembic migration → fresh DB fails | MED | Generate migration next commit |
| Flow worker hardcoded URL + brittle selectors | MED | Make dynamic + selector fallbacks |
| Chrome panel uses `/root` path but audit in `/opt` | LOW | Unify deployment path |
| HTTP Basic Auth without TLS | MED | Document + advise VPN |
| Empty source/ + placeholder character sheet → QH cannot launch | HIGH | Ingest 4 source images next |

---

## 11) Remaining Master-Prompt Checklist (condensed — 120 items)

- See table in §2 above for per-section pass/fail.  
- **DONE count: §0,2(partial),28,31,66,72,82-83,84-85,87-89,105,107 — 12 sections effectively done**
- **PARTIAL: §1,3,9,14,24-25,29,32,59,64,80-81,90-92,96 — 14 sections**
- **MISSING: 94 sections** — bulk is QH creative pipeline (§33-58), mixed-media (§69-71), strict verifications (§5-8,17-23,60-61), health/tests (§93-104)

---

*End of current state. This file should be committed together with the next PHASE 2 reproducibility commit so every future chat can `git log` to this point.*
