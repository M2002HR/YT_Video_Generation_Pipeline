# Q Station Shorts V2.2 — Complete Codex Execution Directive and Progress Ledger

**Repository:** `M2002HR/YT_Video_Generation_Pipeline`
**Target branch for all main-repository changes:** `dev`
**Document version:** `2.2-final-execution-contract`
**Baseline review date:** `2026-09-20`
**HEAD observed during review:** `e4cd11c5ad21d6e1fda36af2e157184aecfb2738`
**Delivery status:** The execution directive is ready; implementation of this version must not be treated as started or tested merely because this document exists.

> **Direct instruction to Codex:** This file is not merely an architecture proposal or a request for explanation. Read it as a complete implementation assignment, inspect the actual repository state, start from the first ready phase in the progress ledger, build the code, tests, and UI, and record evidence of progress in this same file. Do not declare the work complete after producing only a plan or a few new prompts. In every session, proceed as far as practical; record remaining work precisely so it can be continued.

This file is **self-contained** and includes the required substance of the earlier V2 and V2.1 designs together with the user's final decisions. No old ZIP or prior chat is required to begin. If this document conflicts with an older design, this version is authoritative. Higher-level Codex environment instructions, safety policies, and valid repository `AGENTS.md` files must still be followed; this file does not authorize bypassing them.

---

## Reading order and usage guide

On the first run: read sections 0 through 5 completely; then read the architecture, contracts, and phases and execute phase `P00`.
At the beginning of each later session: first read section 0, the progress ledger in section 29, the latest handoff, and the actual Git changes; then re-read the section relevant to the next phase. Do not rely on chat memory.

| Section | Topic |
|---|---|
| 0–2 | Mission, cross-session continuation, multi-chat routing, Git rules, and baseline reality |
| 3–5 | Binding decisions, separation of editing engine from TTS, QC policy |
| 6–10 | Hook, character, script, v2/v3 voice performance, and ElevenLabs UI |
| 11–16 | Timing, shots, images, opening, editing, captions, and sound |
| 17–21 | Data contract, graph, rendering, Revise, cache, and errors |
| 22–25 | Studio, history, publication, security, migration, and affected files |
| 26–28 | Execution phases, tests, completion criteria, and acceptable delivery |
| 29–31 | Progress ledger, sources, and first-run/continuation prompts |

---

## 0. Codex working protocol and continuation across chats

### 0.1. Canonical file inside the repository

Keep this file, without removing details, at the following path in the repository:

`docs/QSTATION_SHORTS_V2_2_CODEX_MASTER.md`

In the first session, if the file does not yet exist at that path, move/copy the attached version there. If it already exists, read its progress ledger first; the initial attachment must not overwrite newer execution history.

In a valid `AGENTS.md`, only if consistent with the project structure, add a short pointer to this path and the requirement to read the progress ledger; do not copy the long text of this document into AGENTS and do not rewrite existing instructions. AGENTS files may have loading limits; the main document must be explicitly read from disk [O1].

### 0.2. Start of every session

1. Inspect the real repo path, branch, HEAD, working tree, and submodules.
2. Read applicable global and local AGENTS instructions.
3. Read the `EXECUTION_LEDGER`, latest Session Log, Decision Log, and Blocker Log in this document.
4. Do not assume the written status matches Git: reconcile commits, changed files, and test reports.
5. Select the first incomplete, unblocked phase. If the active phase depends only on server/auth access, continue with independent later work where safe.
6. For technical decisions inferable from code, do not ask the user again. Make the best compatible decision and record it in the Decision Log.
7. Record a clear blocker only for genuinely missing access, an irreducible choice, or an operation outside authorization; do not stop the whole project because one service is unavailable.

### 0.3. End of every work unit and every session

Update the progress ledger **before ending the response** with:

- which files changed and why;
- which requirement and phase advanced;
- the exact test command, exit code, pass/fail/skip counts, and log location;
- the relevant HEAD/commit;
- incomplete items, environment limitations, and real blockers;
- the first exact command and task for the next session.

Do not say “tests passed” unless they were actually run. `NOT_RUN`, `SKIPPED_ENV`, `FAILED`, and `PASSED` are distinct. A mock test, a real-browser experiment, and real provider generation are three different kinds of evidence.

At the end of a session, do not leave unknown processes, dev servers, renders, or provider jobs running. Record their status and terminate or checkpoint them as allowed by the environment. Do not promise background work outside the session.

### 0.4. One ledger, not multiple parallel truths

The `EXECUTION_LEDGER` in section 29 is the source of truth for execution status. The phase-description tables are the work map, not a second status ledger. Test files and logs may be separate, but their paths and summaries must be referenced in the ledger.

Do not mark a phase complete merely because a skeleton file, fake provider, TODO, or document-only implementation was created. Allowed statuses are:

`NOT_STARTED | IN_PROGRESS | BLOCKED_ENV | READY_FOR_REVIEW | DONE`

`DONE` means the phase's acceptance criteria are satisfied with evidence; full production readiness separately requires real smoke validation.

### 0.5. Multi-chat execution contract (three or four sequential chats)

The word **chat** below means a sequential Codex work session, not a parallel agent or a separate implementation branch. Use **one chat at a time** against the same `dev` checkout. Starting two chats concurrently is unsafe because both could edit the ledger, shared schemas, generated UI assets, or the same Git index. Parallel work is allowed only when one active chat explicitly coordinates isolated worktrees/agents and remains the single ledger owner.

The default and recommended plan is `FOUR_CHAT`. It creates smaller review boundaries and reduces the chance that a session ends with an incoherent cross-phase change. Use `THREE_CHAT` only when longer contexts are available. Select the plan once during P00, write it into `execution_chat_plan` in the ledger, and do not change it later merely because a phase took longer than expected.

#### Recommended `FOUR_CHAT` route

| Chat slot | Assigned phase range | Required aggregate delivery | Hard stop |
|---|---|---|---|
| `C1_FOUNDATION` | `P00–P03` | Verified baseline; canonical document; shared schemas/settings; new-engine orchestration skeleton; provider-free/DOM-fixture-ready v2/v3 ElevenLabs adapter; honest live-browser blocker if applicable | Stop after P03 is `DONE` or code-ready with only live validation explicitly deferred to P14. Do not begin P04. |
| `C2_CREATIVE` | `P04–P07` | Evidence and hook/script package; v2/v3 performance compilers; audio-authoritative alignment/rhythm; multi-shot/asset/opening path with QC off semantics | Stop after P07 meets acceptance and its tests/evidence are recorded. Do not begin P08. |
| `C3_EDIT_AND_REVISE` | `P08–P10` | Independent bounded renderer vertical slice; captions/branding/sound/audible preview; dependency-aware Revise with atomic versions and failure preservation | Stop after P10 meets acceptance and the five critical revision scenarios are evidenced. Do not begin P11. |
| `C4_PRODUCT_AND_ROLLOUT` | `P11–P14` | Complete Studio/graph; history/release/legacy compatibility; regression/security/runbooks; authorized live smoke or a precise `BLOCKED_ENV` P14 handoff | Stop only after final reporting in section 28.4 and ledger reconciliation. Never convert missing live access into a claimed production pass. |

#### Compact `THREE_CHAT` route

| Chat slot | Assigned phase range | Required aggregate delivery | Hard stop |
|---|---|---|---|
| `C1_FOUNDATION_AND_CREATIVE` | `P00–P04` | Baseline plus canonical contracts/orchestration/voice adapter and the complete evidence/hook/script package | Stop after P04 acceptance; live provider validation may remain explicitly deferred. Do not begin P05. |
| `C2_MEDIA_ENGINE` | `P05–P09` | Both performance compilers; alignment/rhythm; shot/assets/opening; new renderer; captions/branding/sound and audible preview | Stop after P09 acceptance and a real local render fixture. Do not begin P10. |
| `C3_REVISION_PRODUCT_ROLLOUT` | `P10–P14` | Targeted revision/versioning; Studio; history/release/compatibility; full regression/runbooks; authorized smoke or explicit environmental blocker | Stop only after the final report and ledger reconciliation. |

Chat ranges are scope ceilings, not permission to mark unfinished phases complete. A chat must start at the **first incomplete phase inside its assigned range**, including work left by an earlier interrupted session. It must not skip a required predecessor merely to preserve the nominal chat count. If the assigned range cannot be finished safely in one context window, stop at a coherent tested checkpoint, update the ledger, and have the next chat resume the same range before advancing. The three/four-chat count is therefore a delivery target, never a reason to fabricate evidence, squash unrelated work, or leave an invalid repository.

### 0.6. Deterministic start, delivery, and stop procedure for every chat

At the start of a chat:

1. Read this section, `execution_chat_plan`, the full phase definitions for the assigned range, the latest Session/Decision/Blocker/Test logs, and section 31.
2. Inspect the actual branch, HEAD, working tree, recent commits, and submodule state. Reconcile any difference with the ledger before editing.
3. Confirm that the chat slot matches `current_chat_slot`. If it does not, do not guess or silently advance it: resume the ledger's current slot and record the mismatch.
4. Find the first phase in the assigned range whose status is not `DONE`. Resume it from `next_action`. A phase marked `BLOCKED_ENV` does not block independent work when its acceptance text explicitly permits deferred live validation.
5. Write `active_phase`, a precise `next_action`, and the current session ID before substantial implementation begins.

Before a chat may stop, it must deliver all of the following:

- coherent code/docs/UI changes for the completed work, with no knowingly broken intermediate contract;
- the phase-specific outputs and acceptance evidence from section 26;
- exact commands, exit codes, counts, evidence levels, and log paths for tests actually run;
- a ledger update plus one append-only Session Log entry, and Decision/Blocker/Test entries where applicable;
- commit SHA and push state, or an explicit list of uncommitted files and why they remain uncommitted;
- confirmation that processes/provider jobs were stopped, completed, or durably checkpointed;
- one exact next action that names the phase, target file/module, and first command/check for the next chat.

When the final phase in the assigned range satisfies its allowed gate, advance `current_chat_slot` to the next slot and set `next_phase`/`next_action` to that slot's first phase. Then stop: do not consume the next chat's phase range. When interrupted before the range gate, keep `current_chat_slot` unchanged and hand off the exact unfinished task. The final chat sets `current_chat_slot` to `COMPLETE` only when P00–P13 are `DONE` and P14 is either `DONE` or truthfully `BLOCKED_ENV` with code-ready deployment/runbook evidence; overall production readiness must remain false until live smoke actually passes.

---

## 1. Git, environment, and change-scope rules

### 1.1. Branch

All main-repository changes must be made on `dev`. Do not change, merge, reset, or force-push `main`. The previous synchronization of dev into main is outside this mission and must not be repeated.

The SHA above is the **review baseline**, not a reset instruction. If dev has advanced, read the newer changes and adapt the design to them. Do not use `reset --hard`, `clean -fd`, hidden stash workflows, deletion of outputs, or force-push. Preserve user changes and unrelated work.

Safe, non-destructive startup commands:

```bash
pwd
git rev-parse --show-toplevel
git status --short
git branch --show-current
git rev-parse HEAD
git remote -v
git submodule status
```

Only after reviewing clean/dirty state and network access, run `git fetch origin dev` and compare with `origin/dev`. Switching/pulling must not discard user work. Create small, coherent commits on dev; stage only relevant files. Push when normal permission/access exists; otherwise record commits and unpushed state.

### 1.2. Ordak is an independent submodule

In the reviewed baseline:

- `services/ordak` → `https://github.com/AliBalash/ordak.git`
- configured tracking branch: `yt-video-pipeline`
- previously observed pin: `6456e9957e6b44eef9a99e60ab372eb258077af8`
- `services/ajil_uag` is also an independent submodule.

Re-read the actual pin in P00. “Everything on dev” refers to the main repository; do not replace Ordak with a normal folder and do not deliver uncommitted changes inside a submodule.

For ElevenLabs UI implementation, first prefer a versioned adapter in the main repository using Ordak's existing browser primitives, if those primitives are sufficient. If Ordak itself genuinely must change:

1. make a small, tested, clearly scoped change in the correct place;
2. create a reachable commit on an authorized remote/authorized fork and update the gitlink on dev;
3. do not push to another person's repository without permission;
4. if no authorized remote exists, provide a versioned patch against the exact SHA in the main repository, with a reproducible install/CI mechanism and prerequisite checks. Blind patching on a dirty server checkout is forbidden; apply it in a controlled checkout/worktree;
5. never deliver a gitlink that points to an uncloneable local commit.

Do not modify a shared service simply because it would be “cleaner.” The deployment path must reproduce all required changes from a fresh clone.

### 1.3. Services and cost

Image cost is not an artistic constraint; credentials, account state, privacy, timeout, RAM, disk, and repeated failed attempts remain real constraints.

Keep paid generation out of normal tests and CI. Run real smoke tests only in an authorized environment and only with explicit provider execution enabled. Purchasing plans, creating accounts, changing credentials, and automatic public publication are out of scope.

Do not restart production services during an active run. Discover actual service names, checkout paths, virtualenvs, sessions, and unit names from the environment; do not blindly execute sample names.

---

## 2. Baseline code realities and required re-audit notes

The following came from review of the baseline repo and must be reconciled with the actual checkout in P00 [G0–G9]:

- The current path enforces “one BODY unit = one image” in multiple layers: prompt, `write_visual_beats_markdown`, graph counting, alignment, timeline, and completion reuse. Changing only one prompt is insufficient.
- The first runner pass returns before visual media, but it creates the visual plan before audio. New target: alignment independent of visuals, with final shot planning after audio.
- `build_timeline.py` in legacy mode applies zoom-in to almost all images and zoom-out to the last. A zero motion counter does not mean there is no movement at all.
- In video 045, the first image starts at `7.333s` in the timeline and its speech starts at `8.06s`. The connection between that boundary and audience drop-off is a hypothesis; Analytics were not available in this review.
- Current Q Station provider locks: text ChatGPT, image ChatGPT, video Flow, and voice `elevenlabs_web`. Legacy “Gemini” names in parameters do not necessarily identify the actual image provider.
- `run_elevenlabs_voiceover.py` intentionally does not call the ElevenLabs API; it uses Ordak Chrome/CDP and the authenticated web UI.
- The generic voice runner currently applies v2-style sliders; genuine v3 support needs an adapter, capability probe, and tests.
- A pre-existing download/result on the page must not be treated as acknowledgement of a fresh request. Current-path guards need review.
- Picking the newest file in the shared Downloads directory is not enough to prove that a file belongs to a specific job.
- The `beat_image_qc_disabled` flag currently has broader behavior than its name suggests. The new opt-out semantics must explicitly cover all images.
- Baseline `services/ordak` accepts image/font references; ChatGPT listening to/judging audio through that path has not been proven.
- The current Revise path contains assumptions about numeric IDs and three-digit suffixes; do not repeat those assumptions for new shot/assets.
- Studio gets contracts from `panel_contract.py` and `run_graph.py`; form API, JSON API, and config revision must converge on one normalize path.
- The current generic video preview may be silent; the new edit preview must include audio.
- The current red-door B contract requires at least five measured seconds and thirteen words. Shortening must not silently violate it.
- History contains short-ID/slug duplicates and failed runs; canonicalization and outcome semantics are required.
- Read current UI/Python tests and workflow definitions; do not combine `node --test` with arguments meant for a different test runner.

**Claims explicitly not made by this delivery:** execution of repo tests, listening to ElevenLabs samples, production browser behavior, correctness of all MP4s, or improved retention. These must be tested during Codex execution.

---

## 3. Binding requirements and decision precedence

| ID | Requirement |
|---|---|
| R01 | Main repository changes only on dev; main and previous runs remain untouched |
| R02 | New engine independent of the current Motion Director; not a rename or wrapper around the same engine |
| R03 | Separate narration, shot, and asset; one sentence may own multiple independent images |
| R04 | Image cost/count must not constrain artistic choice; forced cropping for savings is forbidden |
| R05 | Hook must be intense, immediate, character-driven, topic-grounded, and have a payoff; unrelated shock is rejected |
| R06 | Spoken text must be natural, conversational, and clear while preserving correctness and uncertainty |
| R07 | Hook voice performance and visual acting must derive from one shared intent |
| R08 | Selecting Eleven v3 → expressive execution using real capabilities of that model |
| R09 | Selecting Multilingual v2 → optimized v2 path; never inject v3 tags |
| R10 | Both voice models use the full new hook/shot/editing system |
| R11 | Any missing v3 UI or required primitive must actually be implemented and tested |
| R12 | Voice uses ElevenLabs web/Ordak; no hidden API substitution or provider fallback |
| R13 | Canonical script separated from performance markup; spoken words must not silently change |
| R14 | Real generated audio and alignment are the timing authority; fabricated timestamps are forbidden |
| R15 | Nonverbal events, pauses, and vocal peaks are distinct from spoken words and carry uncertainty |
| R16 | Visual-content QC defaults off for all images and references |
| R17 | With QC off, no hidden review loop, image regeneration, or mandatory human approval gate |
| R18 | Geometry observation for editing is independent of QC, one-pass, switchable off, and cannot trigger regeneration |
| R19 | Schema, decode, provenance, clock, path safety, and bad-output prevention are always active |
| R20 | Text/hook/prompts must be accurate on the first attempt; automated text review must not require user intervention |
| R21 | Editing, captions, music, and effects follow one shared rhythm map and one primary focus at a time |
| R22 | User can revise any component after viewing output |
| R23 | Revise rebuilds only real dependencies; stable IDs and content hashes are required |
| R24 | Last healthy output survives a failed revision; promotion is atomic |
| R25 | Preview must distinguish affected/reused/conditional/conflict and prevent stale two-tab apply |
| R26 | Manual settings and locks outrank AI; replanning must not delete locks |
| R27 | Graph, Studio, CLI, executor, and revision use one shared contract |
| R28 | Resume/stop/provider retry are correct; late results or files from another run must not be consumed |
| R29 | Rendering for dozens/hundreds of shots is batched and resource-bounded |
| R30 | Video, audio, captions, and transitions use one clock; fades must not shorten the narration |
| R31 | Real, audible preview uses the same clock and layout logic as final output |
| R32 | All four characters/gateways, legacy behavior, and Release continue to work |
| R33 | History dedupes and distinguishes planned/completed/published/failed |
| R34 | Delivery/Release bind to an explicit version/hash and produce recoverable receipts |
| R35 | Prompt/schema/recipe versions and the reason for artistic decisions are recorded |
| R36 | Provider-free tests, browser fixture tests, and real smoke tests are distinct |
| R37 | Stable progress ledger and handoff support multi-session/multi-chat continuation |
| R38 | Text, code, hypotheses, and real tests are clearly separated; no fabricated success |
| R39 | Normal production must not depend on human calibration or mid-run candidate selection |
| R40 | Never claim the audience “cannot swipe” or use model scores as a substitute for Analytics |
| R41 | All required features in this document must work end-to-end, not merely exist as UI/stubs |
| R42 | No silent fallback: selected model/account/voice must not change without authorization |

**Conflict precedence:** safety and technical correctness → explicit user request/lock → this contract → versioned profile → AI decision → default.
A legitimate technical refactor may improve file/module names; no requirement may be removed or weakened without explicit rationale and evidence.

---
## 4. Three independent axes: Editing Engine, TTS Model, Review Policy

This separation must exist in code, Studio, storage, and tests.

### 4.1. Image/editing engine

- `editing_engine=legacy`: previous runs without a marker retain their existing frozen behavior.
- `editing_engine=shorts_v2`: the new engine defined by this document; new hook/shot/edit behavior.

The `shorts_v2` number is an engine name and is unrelated to “Eleven Multilingual v2.” Design version 2.2 is also separate from schema version.

### 4.2. Voice model

- `tts_model=eleven_v3` → `voice_execution=expressive_v3`
- `tts_model=eleven_multilingual_v2` → `voice_execution=optimized_v2`

Switching from v3 to v2 must not switch the editing engine back to legacy, restore one-image-per-sentence behavior, weaken the hook, or reactivate the old Motion Director. v2 is a first-class product path, not a hidden fallback or failure mode.

### 4.3. Review

Use independent, frozen settings for media review, observation, and text reviews. The following is a semantic example, not necessarily the exact names that already exist:

```json
{
  "editing_engine": "shorts_v2",
  "design_version": "2.2",
  "voice": {
    "tts_model": "eleven_v3",
    "transport": "elevenlabs_web",
    "execution_mode": "expressive_v3",
    "candidate_count": 1,
    "manual_take_selection": false
  },
  "quality": {
    "media_review": "off",
    "media_review_scope": "all_visual_assets",
    "media_auto_corrections": 0,
    "editorial_render_review": "off",
    "audio_performance_review": "off",
    "technical_validation": true,
    "text_contract_review": true,
    "editing_observation": "auto_once",
    "observation_failure_policy": "safe_geometry_fallback",
    "human_approval_required": false
  }
}
```

`technical_validation=false` is not allowed in production. A debugger mode with asset validation disabled must not be considered publishable output.

---

## 5. Final QC policy: automatic generation, human review after output

This section **explicitly supersedes** some stricter V2.1 rules.

### 5.1. In default `media_review=off` mode

For body images, style anchors, scene anchors, world keyframes, entry frames, character-derived assets, opening sources, and their candidates:

- do not run semantic/aesthetic review after generation;
- do not let an image reviewer assign scores or create hidden verdicts;
- do not regenerate images repeatedly to obtain a higher score;
- do not introduce `NEEDS_REVIEW` or mandatory manual approval in the middle of a run;
- apply identity/geometry rules precisely in prompts and generator inputs, but do not claim pixel-level verification when pixels were not reviewed;
- accept technically valid output with `acceptance_basis=technical_only`.

Correct receipt example:

```json
{
  "technical_valid": true,
  "review_status": "not_requested",
  "semantic_passed": null,
  "human_approved": false,
  "acceptance_basis": "technical_only"
}
```

The labels `QC passed=true`, `geometry_verified=true`, or `best_candidate` are forbidden for unreviewed output. Semantic beauty/acting/geometry may still be wrong; the user can Revise it later.

### 5.2. Controls that never turn off

Real decode and non-empty-file checks; file type/dimensions; sufficient source duration; schema; hash/ref/provenance; text-audio correspondence; positive timing; absence of unintended gaps/overlaps; crop bounds; no paths escaping the project; download errors; prevention of obvious clipping or invalid timestamps.

These are not “picky semantic QC.” Disabling QC is not permission to publish a broken file or audio from another run.

### 5.3. Image observation for editing, not judgment

`editing_observation=auto_once` exists only to discover subject location/text-safe areas/crop targets:

- analyze only the final existing asset pixels, once per hash/version;
- output schema contains only observations/boxes/confidence/occlusion/layout; no `passed`, aesthetic score, or regenerate directive;
- it may not reject the image, create another candidate, or trigger an artistic correction loop;
- on failure after limited transport retry, use `safe_geometry_fallback`: valid full-frame or conservative framing; never invent a bbox;
- low confidence produces only conservative framing, not image regeneration;
- `editing_observation=off` means no pixel upload for observation/review. The edit model sees metadata only and provenance is `prompt_metadata_only`.

Explain this technical observation role separately in Studio. Renaming a reviewer to “observer” must not be used to bypass opt-out. Tests must verify provider-call count and schema.

### 5.4. Optional modes

- `report`: requested review is recorded; no auto-regenerate and no aesthetic stop gate.
- `strict`: bounded review/correction, only inside selected scope. Corrections stay within the artifact owner.
- a revision of one image may request review “only for this request” without globally enabling reviews.
- policy changes affect future attempts; merely toggling policy must not regenerate already accepted output.
- voice calibration, multi-take selection, and render review are also independent opt-ins; normal generation must not wait for them.
- text/factual/schema reviews during hook/script design remain automated; do not ask the user to approve every step.

### 5.5. Acceptance and publication without mandatory interruption

By default, `accept_version` means the final file, clock, and dependencies are technically valid and atomically promoted as the current output; it **does not mean human artistic approval**.

The user can watch the video later and use Revise. A workflow mode requiring human approval before publication is optional. Preserve the user's currently enabled delivery behavior; do not add new automatic public YouTube publication.

---

## 6. Hook engine: an executable package, not a catchy sentence

### 6.1. Goal and boundary

The goal is an immediate, high-retention opening with a topic-specific event and a clear promise. “No viewer can swipe away” is not a valid engineering metric or guarantee. Model scores are editorial assessments, not statistical retention predictions.

Do not spend second zero on generic warm-up such as walking to a table, looking around, picking up a prop, and only then discovering the topic—unless that action itself is the core contradiction.

A scream, cackle, brief panic, sudden silence, whisper, wicked grin, expectation break, and consequence-first opening are allowed, but they must arise from the topic event. The new system must not start every episode with the same crone scream.

### 6.2. Hook Package

Each candidate must include at least:

- stable `hook_id`, `dramatic_mechanism`, and its narrative role;
- `frame_zero_interrupt`, `first_300ms_read` as design intent, not a guaranteed perception claim;
- `first_second_event` with at most one primary readable event;
- short natural `spoken_hook`, with no requirement that it be phrased as a question;
- `character_burst` and `vocal_burst` with a narrative cause;
- `stakes` and `curiosity_gap`;
- `claim_ids`, `truth_anchor`, and real/hypothetical/metaphorical mode;
- `payoff_debt` and approximate answer point;
- `escalation_1_3s` and the first piece of genuinely new information;
- `gateway_handoff` and presentation-feasibility constraint;
- `voice_feasibility` for the selected model/voice;
- `history_signature` covering visual, reaction, voice, syntax, and handoff.

With v2, a hook whose success depends entirely on an unsupported, tightly controllable laugh/scream must be redesigned around an achievable performance. Do not solve it by inserting v3 tags or silently switching models. Strong visual reactions remain allowed.

### 6.3. Generation and selection

Default: 6 **semantically different** candidates; configurable in Advanced, using bounded batches. Different wording or location alone is not a different scenario.

An independent text reviewer evaluates all complete candidates against a clear rubric. Honesty, payoff, readability, and feasibility gates take precedence over scores. The top two eligible candidates are compared head-to-head; input order must not decide the winner and tie-breaking must be deterministic.

If no candidate is eligible, redesign up to a bounded attempt count; infinite loops are forbidden. Keep rejected candidates and reasons. The intended condition is “no candidate is eligible,” not the ambiguous phrase “none failed a hard gate.”

This tournament is **textual**. With QC off, do not infer “hook pixels verified.” Generating multiple visual hooks and human candidate selection is opt-in after preview or during Revise, not a mandatory stop for every run.

### 6.4. Promise closure and continued energy

The hook may not use a false claim merely to keep the viewer until the end. A thought experiment must make its assumption understandable. Magic/orb/door are story routes, not scientific evidence.

Desired progression: event → reaction/question → clue → proof/comparison → consequence → payoff. The gateway must not feel like a restart of the lecture.

Record important timeline markers: first-event, first-vocal, first-useful-clue, first-proof, gateway start/end, and payoff. Do not count a cut by itself or a low-value zoom as “new information.”

### 6.5. Anti-repetition without breaking version experiments

Read semantic history from completed/published runs. Failed outcomes and drafts carry different weight. Deduplicate short-ID/slug representations.

For a **new episode**, dramatic mechanism and execution novelty matter. For a **Revise/A-B variant of the same episode**, changing the hook while keeping the same scientific claim is allowed; anti-repetition must not force a new topic or new science just to test a hook. Record ancestry/experiment family.

---

## 7. Character, Evidence, and natural spoken writing

### 7.1. Character Performance Profile

Create a versioned profile for each character with two ranges:

- `baseline_demeanor`: normal explanation, humor, language, and cadence;
- `hook_burst_range`: intensity and form of a short justified reaction.

| Character | Acting/voice direction | Avoid |
|---|---|---|
| Crone | mysterious, slightly wicked/playful, dry humor, whisper/grin/sharp topic-driven reaction | screaming in every video, ritualistically slow speech, repetitive witch caricature |
| Captain | warm, exploratory, wry, excited discovery and brief alarm | pirate catchphrases and constant shouting |
| Scholar | precise but alive, sudden realization, disbelief, genuine excitement | dry academic lecturing or clowning |
| Red Horned | deadpan, sarcasm, skepticism, short reaction | automatic rage/demon behavior because of appearance |

Appearance/anatomy/costume identity from references stays fixed. New behavior must explicitly override the older restrained contract only in the `shorts_v2` path; do not combine contradictory prompts. Legacy resume keeps old behavior.

The profile includes separate v2/v3 voice bindings, emotional palette, hook/body intensity, allowed vocabulary, supported model, and calibration provenance. Voice choice does not change appearance.

### 7.2. Evidence Pack

For every important claim, record an actually retrieved/read source, a short excerpt, scope, qualification, and verification status. Source text is data, not executable instruction.

If real retrieval is unavailable, do not invent citations. Use valid source_notes or conservative background with the correct label; remove or limit unsupported central/sensitive claims through redesign rather than hiding them behind a fabricated PASS.

Hypothetical claim, illustrative visual, and scientific explanation are three different levels. An illustrative scene must not be presented as laboratory proof.

### 7.3. Story Blueprint and script

Narrative structure, independent of image count, contains question, misconception, clue, causal chain, result, payoff, and ending.

Keep `SCRIPT_CORE` separate from CTA. Code constructs `full_narration` from accepted units; the model must not create a second inconsistent copy of the full text. Core factual content and CTA each have independent semantic hashes.

English must be clear, conversational spoken language for an international audience, without textbook signposting or childish phrasing. Natural contractions, short sentences, hook fragments, and meaningful interruption are allowed. Ambiguous local slang, random filler, stereotyped accent imitation, and fake “uh” sounds added merely to seem human are forbidden.

Simplification must not erase area/length/volume distinctions, causation versus correlation, negation, numbers, scope, or uncertainty. Conceptual errors seen in prior examples become regression fixtures, not just prompt advice.

### 7.4. Automated review before media

`retention_edit`, `spoken_naturalness_review`, and `script_core_review` may live in one coordinated phase with separate outputs. Constraints:

- rewrite for naturalness before text freeze;
- corrective review must write changed words back into canonical text;
- detect repeated information and generic sentences without progression;
- no reviewer may pass simply because words like “hook” and “payoff” exist;
- correction attempts are bounded and require no human approval in normal mode;
- final-text hash drives all downstream work.

Preserve user CTA intent: for example, “suggest the next topic in comments” must not become a repetitive question about the current topic. CTA stays short and natural; the tail image may continue but must not become a dead static screen for several seconds.

---

## 8. Shared voice design and v2/v3 separation

### 8.1. Shared outputs

- `VOICE_RESOLUTION.json`: actual voice/model, requested/effective values, profile, manual lock;
- `VOICE_CAPABILITIES.json`: canonical model plus UI/adapter controls and verified limitations;
- `VOICE_PERFORMANCE_PLAN.json`: performance intent anchored to canonical words/phrases;
- `TTS_INPUT.txt`: model execution input, not the transcript;
- `VOICE_TOKEN_MAP.json`: mapping from execution text to canonical words;
- `TTS_EXECUTION_RECEIPT.json`: effective inputs/settings, provider result identity, and output hash;
- `NARRATION_TIMING.json`: actual timing after generation.

Performance Director chooses emotion, emphasis, cadence, and pauses from the script, Hook Package, and character. These directives are **requests to the model**; until valid listening/analysis occurs, do not label their occurrence as `verified`.

`intensity=0.8` is an internal design parameter; do not claim ElevenLabs exposes that numeric control for each word. The compiler maps it only to capabilities that really exist.

### 8.2. Voice selection and calibration

`manual_override` outranks automatic choice. In `character_default`, use a real configured mapping for that character/model. Ambiguous or invented voice IDs/labels are invalid. Missing configured voice must not silently fall back to Mark.

Calibration is an independent optional tool: benchmark sample, model comparison, user approval recording, and blacklist of bad tags. Normal production must not wait for calibration.

Unlike the earlier strict rule of “only human-calibrated tags,” production may now use documented provisional vocabulary with status `documented_not_calibrated`. Do not mark an uncalibrated tag as `calibrated=true`. Unbounded experimental tags default off.

### 8.3. One continuous voice track, not TTS per image

A normal Short is generated as one continuous narration. One sentence with five shots must not become five independent TTS jobs. Preserve surrounding context for natural performance.

If the text exceeds the provider's real limit, split only at narrative units using a tested stitching contract, not because of shots. Each chunk uses the same voice/model/settings with independent provenance/offset. Do not pass a seam without tests. Multi-chunk execution is not the default shortcut.

Normal take count is 1; bounded technical retry is separate. Multi-take generation and human/automatic semantic selection are opt-in and require real capability. Do not rank downloaded audio as “best acting” without an actual listening mechanism.

### 8.4. Text invariant

Performance stage does not change spoken words. Tags, pauses, and capitalization are separate. Adding “Oh!” or removing “not” requires a revision of canonical text itself.

Build tokenizer/mapping/validation so punctuation removal, minus signs, decimals, percentages, contractions, or meaning are not destroyed. Merely `remove all punctuation` is insufficient. Numbers/units should be converted to clear spoken representation before text freeze.

Compile tags from a typed AST, not from raw model text with loose regex. For v2, emit only finite, bounded break durations. Reject unknown markup, extra XML, injected tags, and executable instructions.

Arbitrary phonetic rewrites are forbidden in the base version. If a pronunciation dictionary is later needed, alias-to-canonical mapping and actual capability must be separate and tested; subtitles preserve the correct displayed word.

---

## 9. Two first-class voice compilers

### 9.1. `expressive_v3`

Eleven v3 supports audio tags for emotion/delivery/nonverbal behavior plus punctuation; SSML break is not the path for this model [E1–E3].

- initial tags come from documented palettes such as whisper, laugh, sarcastic, curious, and mischievously, used sparingly and only where suitable for the selected voice;
- the goal is “emotion on the right passage,” not a tag on every word;
- stability modes such as Natural/Creative/Robust are mapped by the adapter to real UI controls and verified by read-back; do not hard-code a numeric/label assumption without validation;
- do not assume the label “Eleven v3” is the same as newer conversational/realtime model families; verify the correct canonical model;
- legacy v2 controls must not be forced onto v3; a versioned capability table plus observed UI state are authoritative;
- unsupported style controls remain inactive; when a model/UI does expose style, the recommended baseline is zero unless explicitly overridden;
- local word-level perceived speed is shaped through wording/punctuation/supported tags, not an imaginary per-clause speed parameter;
- behavior tags do not have exact guaranteed durations. `[short pause]` does not equal a guaranteed 300 ms; measure only after generation;
- planned laugh/scream/breath belongs to the nonverbal channel, not subtitle words.

Illustrative example only; it is not a generated or listened-to sample:

```text
Canonical:
You think that's the dangerous part. It isn't.

Compiled for v3:
[mischievously] You think THAT'S the dangerous part... [short pause] It isn't.
```

Natural mode is the initial design baseline; Creative is allowed for a highly expressive hook when the voice/profile supports it. Blindly lowering stability or filling the text with tags is not a universal solution.

### 9.2. `optimized_v2`

v2 uses the same new story and hook system, but voice execution uses actual v2 capabilities:

- character-appropriate voice;
- continuous context and genuinely conversational text;
- limited punctuation/emphasis;
- controlled break for required pauses;
- speed/stability/similarity/style/speaker boost only when supported and verified by read-back;
- calibrated profile or explicit user override takes precedence;
- never send `laughs`, `mischievously`, `short pause`, or other v3 bracket tags to v2;
- do not append narrative phrases like “she said angrily” to control emotion; they may be spoken aloud;
- do not assume all SSML is supported. Only use a validated, bounded `<break time="...s" />`; do not emit `prosody`, `emotion`, `emphasis`, or `phoneme` without proven support.

According to ElevenLabs guidance, break is available for Multilingual v2 and overuse can harm quality; actual output must still be measured [E2].

Illustrative example with the same spoken words:

```text
Compiled for v2:
You think THAT'S the dangerous part. <break time="0.2s" /> It isn't.
```

An initial experimental preset for a **new run with no lock** may be around speed 1.05, stability 0.40, similarity 0.75, and style zero; these values are neither a quality guarantee nor an instruction to overwrite an existing profile. If a control does not exist, follow capability data.

Do not promise v3-level control of a precise wicked laugh or scream in v2. The base hook/visual performance must remain effective without it. A separate reaction-audio asset is allowed only with explicit source/voice identity/license and explicit permission in sound design; `SFX off` must not be bypassed by sneaking in effect-like auxiliary audio.

### 9.3. Switching models in Studio

Keep two subprofiles separate:

- when moving from v2 to v3, keep v2 values but make them inactive and exclude them from effective request/fingerprint;
- returning to v2 restores valid values from that profile;
- distinguish `requested`, `effective`, `unsupported`, `inactive`, and `locked`;
- unrelated hidden fields must not fail validation or cause unnecessary regeneration;
- an unsupported model or ambiguous selected name is a real error, not silent fallback;
- switching v2/v3 invalidates TTS compilation, generation, timing, and real dependents—not the entire world or independent image assets.

### 9.4. Important provider-documentation note

The official product page's v3-specific section describes Speed/Similarity/Speaker Boost as unavailable, while a general FAQ section on the same page uses broader language about speed [E1]. Therefore do not infer universal model behavior from a generic sentence or old DOM knowledge.

In P03, establish **actually observed model/control capability** with adapter tests. UI drift after deployment must fail transparently with evidence, not silently disable a requested setting.

---
## 10. Complete ElevenLabs UI implementation and Ordak integration

This is one of the most important mandatory phases. Merely adding `Eleven v3` to a dropdown or leaving a TODO for a later Codex session is not acceptable.

### 10.1. Required state machine

```text
OPEN
 -> VERIFY_SESSION
 -> SELECT_MODEL
 -> SELECT_VOICE
 -> PROBE_CAPABILITIES
 -> APPLY_EFFECTIVE_SETTINGS
 -> VERIFY_SETTINGS
 -> ENTER_COMPILED_TEXT
 -> VERIFY_TEXT
 -> CAPTURE_RESULT_BASELINE
 -> SUBMIT_ONCE
 -> ACKNOWLEDGED
 -> WAIT_FOR_BOUND_RESULT
 -> DOWNLOAD_BOUND_RESULT
 -> VERIFY_DECODE_AND_IDENTITY
 -> COMMIT_RECEIPT
```

Every stage must have an explicit checkpoint and error code. Tab/session/process, parent run/revision, and attempt owner must be explicit.

### 10.2. UI selection and control

- Read valid accessible roles/labels/test IDs; fixed screen coordinates are forbidden.
- A numeric control may be a slider, while v3 stability may be implemented as radio/button/slider; never assume `[role=slider]` always exists.
- Select the model first, then the voice, then probe capabilities. If model/voice selection resets settings, verify them again.
- Read control min/max/step from valid DOM state and verify the effect of key/click actions.
- An unrelated inactive control is not a failure; a requested/expected control that is absent is recorded as UI drift.
- Exact normalized label matching is insufficient when two voices have the same name: include observable ID/metadata in matching.
- The editor may be textarea or contenteditable/chip-based. Tag preservation, newlines, and text read-back must be tested against real layouts.
- String length alone is not enough. The read-back text hash, under bounded documented normalization, must equal the compiled input.
- UI-native Enhance/Rewrite features that mutate text without control are not used by default.
- Do not bypass verification/CAPTCHA; a real need for user intervention becomes `PAUSED_*`.

### 10.3. Result ownership and preventing the wrong audio from being consumed

Before Submit, record current result/history/URL/elements and a baseline snapshot. The mere presence of `Download latest` or an old result is not acknowledgement of a new request.

After Submit, the system must observe evidence that belongs to this request: a provider generation ID if exposed, a new matchable history row, or another explicit stable evidence bundle. Do not attribute an older generation's audio to the new request.

Download from the bound result using browser download event/GUID and a dedicated run/attempt path. A fresh mtime in shared Downloads is not sufficient. Never consume `.crdownload`/partial files; final writes are atomic.

If result identity truly cannot be proven in the current UI, fail explicitly; do not choose “the newest MP3 available.”

### 10.4. Stop and resume

After disconnect/timeout, first reconcile any generation already in progress. Immediate refresh and resubmit may produce duplicates. Exactly-once provider semantics may be claimed only if the provider actually supports them; otherwise record submission uncertainty and reconcile conservatively.

At minimum, the voice execution receipt records: canonical script hash, compiled input hash, effective settings, observed model/voice, capability schema version, browser result evidence, original/normalized audio hash, attempt/revision, and timestamps.

Do not reuse an otherwise valid output file solely because it exists if the matching receipt is absent.

### 10.5. Do not merely claim UI capability

Required fixture/adapter tests: v2 sliders; v3 modes without sliders; changed layout; half-open voice picker; lazily rendered control; exact identity mismatch; text disappearing after React rerender; old result already on page; wrong download; duplicate-submission recovery; and auth challenge.

At least one real v2 and one real v3 test on an authorized server are required. If Codex does not have browser/account access, implement the code and mock tests and record smoke as `BLOCKED_ENV`; do not reduce the whole task to “the user manually downloads from the website.”

### 10.6. Audio review and Ordak

For base-scope voice generation, use the existing/completed web transport. Do not infer that ChatGPT can upload and **listen to** audio merely because file upload or transcript handling exists.

Automated semantic audio review is off by default. Add it only after real capability and payload/result tests, under a separate status. It is not required to execute this document; an audible preview plus human Revise after output is sufficient.

---

## 11. Independent alignment, nonverbal performance, and Rhythm Map

### 11.1. Real source of truth

The new alignment path works only from canonical narration, the real audio file, and token map. `VISUAL_BEATS.md` must not be a prerequisite.

For every token store: `word_id`, `unit_id`, canonical-text index/offset, observed token(s), start/end, confidence, and method. Word identity remains stable when only the voice changes and text is unchanged; text changes require explicit reconciliation/lineage.

Word-level backend output and segment-interpolated output are not the same thing. Do not label interpolation or proportional timing as `measured_word`. Critical unaligned boundaries require bounded retry using a valid backend or a clear error; fabricated timestamps for the whole video are not a normal fallback.

### 11.2. Text/audio mismatch

ASR itself can be wrong. Transcript mismatch alone does not prove broken TTS. Proper names, spoken numbers, contractions, and repeated words require precise mapping.

Use stronger technical confidence/coverage gates for critical negation/number tokens and the hook region. If a tag is spoken aloud as a word or the spoken text genuinely changes, that is a defect; do not hide broken audio by simply removing the token from subtitles.

### 11.3. Nonverbal events

Store laugh, gasp, scream, breath, and pause with separate `performance_event_id`s. Planned occurrence is not the same as observed occurrence.

A gap between words may contain laughter, breathing, silence, or alignment error. Record it with a label such as `candidate_event_window` plus actual evidence. Laughter may overlap speech and need not occupy only a gap.

In the default mode without a listening critic:
- exact emotional occurrence remains unverified;
- approximate windows may come from timing and non-semantic analysis;
- captions must never print `[laughs]` or performance instructions;
- accessible sound captions require a separate option and correct mapping;
- audio before the first word must not be blindly trimmed as redundant silence.

### 11.4. Pacing gate

Before visual media, compare actual audio duration with the user's requested range. Word-count targets are not a substitute for real duration.

Default bounded technical correction:
- missing/truncated audio or wrong spoken text → regenerate audio for an explicit reason;
- duration above the cap → bounded text rewrite or a supported setting change under the frozen policy;
- text changes require new review and freeze;
- avoid hidden global audio retiming, pitch-shifting to fake a character, or deleting meaningful breaths;
- if explicit audio processing is performed, preserve the original, record recipe/hash, and realign.

Artistic disagreement about excitement or pauses is not a blocker with QC off. Produce technically valid output and let the user Revise later.

### 11.5. Rhythm Map

Build it from script role, hook plan, performance intent, and measured timing. Every event includes:

`event_id`, `word_ids`, `performance_event_ids`, `role`, `time_evidence`, `start/end`, `primary_attention`, `supporting_layers`, `purpose`.

Roles include hook_peak, clue, contrast, consequence, proof, pause, payoff, and CTA. There is one primary focus at a time; captions, SFX, and camera support it.

In default mode, music rhythm follows the edit. Only when `music_driven=true` should music rhythm features enter the pipeline before editing, in a way that does not create a cycle with sound planning.

---

## 12. Opening/Gateway in the new architecture

### 12.1. Preserve gateway identity, remove information-free time

Support all four profiles: book, orb, spyglass, and red door. Read character→gateway mapping from the registry, not repeated name conditions across files.

First/last frame, ownership, and geometry rules remain part of prompt/source contracts:
- book: closed, top-down, host-free under the current profile;
- orb: clear ownership by character/hand;
- spyglass: eyepiece by the unobstructed eye, objective toward the subject;
- red door: opening, actual crossing, arrival in the world, and ending without the door frame.

With QC off, these are **generation requirements**, not claims of observed pixel verification.

### 12.2. Compatible timing

Choose source duration from provider capability, measured target, and transition handles. Source duration is not the same as the portion ultimately used in the edit.

Do not force a four-second total opening onto a profile that genuinely requires more time. If a compact profile is needed, create a versioned one with its own contract and tests; do not silently relax old criteria.

A/B may connect with a strong cut or match cut; a soft fade is not the universal default. Important movement must finish before the out-point, not in a tail that gets trimmed.

### 12.3. Voice and visual synchronization

Flow prompts consume the Hook Package plus voice performance/timing, including coarse face/body behavior and event windows. Do not demand or claim exact lip-sync without a real lip-sync mechanism.

In the base path, **ElevenLabs is the authoritative character voice**. Native Flow audio is muted by default in assembly to avoid duplicate dubbing, conflicting accent/tone, or unwanted music. Native ambience may be used only as an explicitly separate track under a clear policy—not by automatically mixing all Flow audio.

The Flow→image boundary must continue with a first shot containing strong new information and matching energy. Cutting to a fresh image while narration repeats the same idea is not real progression.

### 12.4. Optional body video

If a story truly requires physical object motion, a body-video asset may be added to the same asset system only when capabilities, reference policy, duration, and receipt for that role are implemented. Do not borrow the raw Flow A/B path for body video without validation. When capability is absent, prefer multiple precise images/explicit comparison; do not pretend camera motion is physical motion of the subject.

---

## 13. Shot Planner and asset generation

### 13.1. Split into shots

Leave natural spoken text intact and divide the real timeline into meaningful shots. A shot is not required to equal one sentence or one word.

Required fields:
`shot_id`, `display_order`, `unit_ids`, `word_span_ids`, `role`, `new_information`, `focus`, `scene_group`, `asset_requirements`, `reading_complexity`, `timing_constraints`, `cut_reason`, `manual_locks`.

Narrative and visual boundaries remain separate. One shot may support multiple related units; one unit may have multiple shots.

### 13.2. Experimental rhythm preset

These values are initial design hypotheses and must be configurable; do not turn them into mechanical rules for every topic:

| Item | Suggested starting point |
|---|---|
| hook | primary event in the first second; readable information before switching away |
| simple shot | about 0.8–1.4 seconds |
| complex comparison/diagram | about 1.4–2.4 seconds |
| detail burst | about 0.35–0.6 seconds, bounded and justified |
| long hold | only for narrative/readability reasons; may be appropriate for a complex diagram |
| images in a 45–60 second Short | about 30–60 or more when needed, not a mandatory quota |

Do not reduce shot/image count for cost reasons. Solve resource/context limits with batching/serial execution. If a hard operational ceiling is necessary, make it explicit, configurable, and error-producing; never silently truncate the design.

### 13.3. Independent Asset Manifest

`asset_id` is not the same as `shot_id`. Asset semantic spec includes subject, action, state, composition, medium, identity reference, scene group, reference roles, and generator.

More shots do not always require the exact same number of images, but the default is allowed to choose a **new precise image** whenever that is artistically better. Reuse/crop only when it is genuinely better and record the reason.

Do not force the world keyframe to substitute for body imagery, and do not count a barely changed previous image as a new image.

### 13.4. References and continuity

Separate style, identity, composition, and temporal state. Do not copy frame/scenery/border from a style reference.

The body world fills the entire 9:16 frame; page, book spread, lens rim, border, and blank footer from the opening must not leak into body visuals. A book/door may appear as a relevant object inside a scene, not as the mandatory frame around every image.

Use stable scene and identity references; do not make all images a 60-image chain where each depends on the previous image. Record real reference dependencies with SHA and role.

### 13.5. Accurate generation on the first attempt

The Prompt Writer for each asset receives only the information required for that shot: claim, medium, camera, action state, focus, reference roles, and forbidden changes. One generic instruction for the entire video is insufficient.

Connect caption or critical-overlay space to layout intent, but do not create a blank footer inside the image unless the user requested it. Important numbers/labels should be rendered by the compositor, not inside an uncontrolled text-generating image model.

With QC off: select one technically valid output; additional candidates or corrections only happen because of explicit user request or a recoverable technical error. The model may not regenerate merely because it prefers another aesthetic.

### 13.6. Plan diff instead of global regeneration

After replanning:
- reuse assets whose semantic specification plus identity/style/ref hashes are unchanged;
- generate new assets;
- remove deleted assets from the active manifest but retain old versions;
- do not overwrite a similar-but-different replacement under “the same ID”; give it correct ID/version/provenance;
- timing-only display changes must not change the image-generation hash.

---

## 14. New edit direction; old Motion Director is forbidden

### 14.1. Real independence

No normal `shorts_v2` path may depend on these for decision-making or the new compiler/renderer:

`run_motion_director.py`, `motion_schema`, `motion_v2_schema`, `motion_compiler`, retained `MOTION_PLAN`.

Legacy renderer top-level imports also must not accidentally make the new engine depend on them. Dispatch before imports or a separate module is required. A low-level generic utility may be shared only when it is independent, healthy, and tested.

The `_motion.enabled` setting and old artifacts must not affect new-engine output. Tests using import traps and poisoned legacy plans must prove this.

### 14.2. Vocabulary and decisions

Edit Director takes shot plan, honest asset observation or metadata, rhythm map, and layout constraints, then selects:

- cut, detail/match/smash cut with an explicit destination;
- short fade/dissolve where appropriate;
- pan/tilt/push/pull/reframe/hold;
- limited readable scale emphasis;
- multi-asset comparison only when the compositor truly supports it;
- easing, in/out holds, and relevant word anchors;
- intentional visual breathing room.

A cut is the normal default for a fact/action change; the model must not create random transitions “for variety.” Preserve gaze direction, screen direction, and subject location. Information-free image swaps and repeated identical zooms must not score as valuable events.

### 14.3. Reliable compiler

The model returns typed JSON only; never execute shell, FFmpeg expressions, JS, arbitrary paths, eval, or arbitrary shaders from model output.

Local solver enforces:
- viewport inside source bounds and correct aspect ratio;
- maximum upscale from actual resolution;
- observed target or full-frame safe fallback;
- pan/zoom speed limits and jitter avoidance;
- explicit recording of no-ops and corrections;
- disabled primitives are never executed;
- locally correctable geometry errors clamp explicitly instead of generating a new asset;
- manual locks take precedence; if incompatible with a hard constraint, emit a visible conflict rather than silently changing the lock.

### 14.4. Avoid feedback cycles

Build initial `LAYOUT_CONSTRAINTS` from dimensions, text, fonts, and locks before edit planning. Edit Director knows fixed overlay space. Caption/Layout then resolves final placement and bounded conflicts after editing.

If a re-edit is needed, create a bounded owner attempt/revision; do not create permanent back-edges in the DAG. A caption-color-only change must not cause every planner to run again.

---

## 15. Captions, title, watermark, and shared preview

### 15.1. Text and timing

- captions come from verified canonical/observed mapping, never `TTS_INPUT.txt`;
- emotion tags, SSML, and scene directions are never subtitles;
- captions may span multiple cuts; shot end is not a required caption boundary;
- short phrase + keyword emphasis is the initial mode; one-word, manual, and off modes are also supported;
- grouping must not mutate the text; punctuation/normalization follows canonical display text;
- emphasis on a negation/number must not invert the sentence meaning.

### 15.2. AI role and user control

AI may choose grouping, emphasis, and placement only inside configured bounds. User-locked font, color, size, position, maximum words, outline, title, and logo are authoritative pins.

`subtitle_enabled=false` means no burned-in captions in preview or final. Any explanatory overlay must have an independent key and permission, not bypass subtitle-off.

The title may appear only at the beginning, during a selected range, or for the whole video; do not automatically impose a huge full-video title. Watermark/brand must coexist with focus and readability.

### 15.3. Layout

Safe area is not one universal permanent number; use versioned configurable presets with preview. Face/object, UI-side overlays, title, subtitle, and watermark must be considered together.

Resolve the actual font from current catalog/upload. A missing font results in an explicit recorded fallback or an error for a locked font; a CSS preview using a different font is not a PASS. Test Unicode, outline, wrapping, and libass size against the real renderer.

Draw overlays after visual composition/transitions so a crossfade does not duplicate them. Caption animation scale/timing must be executable by the same renderer, not merely demonstrated in the browser.

### 15.4. Preview

Edit preview must be audible, seekable, byte-range capable, and generated from the same compiled timeline. Bitrate/resolution may be lower; clock/cut/crop/text/font/layout must not differ logically.

Provide four clearly labeled views: source asset, unbranded composition, branded edit preview, accepted final. Do not re-apply title/captions to an already branded preview.

---

## 16. Sound Design and final mix

Narration is the timing reference and mix focus. SFX must not be added to every cut. The “one primary attention event” rule must be enforced across image/audio/caption, not merely written in a prompt.

- User-selected music from library/upload with hash has definitive priority.
- Record license, source, actual file, and duration for music/effects.
- Implement ducking, transients, gain, audio fades, and intentional silence within explicit limits.
- A scream/cackle must not become overdrive/clipping in perceived loudness.
- Gain-only changes require no new TTS or image; preserve original raw audio.
- `sfx_enabled=false` means no SFX download/search/generation and no hidden effect. Character nonverbal performance belongs to performance, not musical SFX.
- If an effect cannot be found, follow explicit optional/required policy; no placeholder file or fabricated license.
- Automated audio analysis proves only amplitude/duration/technical properties, not natural acting.
- Music-driven mode is optional; by default changing music must not regenerate image cuts.
- Best intelligibility outranks maximum speed; default output must not use constant loudness pressure or extreme volume jumps.

A render without music/SFX must still be complete and valid. Disabled dependencies must not create permanently pending nodes.

---
## 17. Data contract and single source of truth

Names in this section are **logical** paths; working files are written under the revision root, not by overwriting previously accepted output.

### 17.1. Suggested version structure

```text
videos/<episode>/
  shorts_v2/
    ACCEPTED_VERSION.json
    versions/<revision_id>/
      REQUEST.json
      REVISION.json
      creative/
      voiceover/
      timing/
      planning/
      editing/
      render/
      receipts/
      diagnostics/
  assets/shorts_v2/
    <asset_id>/<attempt_id>/<content-hash>.<ext>
```

An active revision is writable only by its owner. After acceptance, manifests become immutable. Prior source/attempt files remain safe until GC.

Artifacts have logical paths in the registry; a runtime resolver binds them to the selected version and immutable media. Legacy compatibility exports are produced only during promotion as derived outputs, never as a second editable source of truth.

### 17.2. Shared envelope

Every new plan/receipt must include at least:

```json
{
  "schema_version": 1,
  "design_version": "2.2",
  "editing_engine": "shorts_v2",
  "episode_id": "example_episode",
  "revision_id": "example_revision",
  "artifact_type": "example_only",
  "producer_stage": "example_stage",
  "producer_version": "example_version",
  "input_fingerprint": "example_hash_not_a_real_receipt",
  "created_at": "example_timestamp",
  "provenance": {
    "kind": "example",
    "observed": false
  }
}
```

This JSON is an example, not a real receipt. Runtime writes real hashes/timestamps. Typed schemas must define required fields, explicit unknown-field handling, finite numbers, and migration version. `NaN/Infinity`, unknown IDs, and incomplete arrays are invalid.

### 17.3. Core artifacts and ownership

| Artifact | Content / owner |
|---|---|
| `REQUEST.json` | normalized request, frozen defaults, model/engine/quality/locks |
| `CHARACTER_RESOLUTION.json` | frozen identity and presentation |
| `CHARACTER_PERFORMANCE.json` | acting/voice profile snapshot |
| `VOICE_RESOLUTION.json`, `VOICE_CAPABILITIES.json` | actual voice and adapter capabilities |
| `EVIDENCE_PACK.json` | claims and source scope |
| `HOOK_CANDIDATES.json`, `HOOK_REVIEW.json`, `HOOK_BLUEPRINT.json` | textual tournament and selected hook |
| `STORY_BLUEPRINT.json` | narrative order and payoff debt |
| `SCRIPT_CORE.json`, `CALL_TO_ACTION.json`, `SCRIPT_PLAN.json`, `SCRIPT_FINAL.md` | script and reviewed versions |
| `VOICE_PERFORMANCE_PLAN.json`, `TTS_INPUT.txt`, `VOICE_TOKEN_MAP.json` | intent and compiled execution text |
| `TTS_EXECUTION_RECEIPT.json` | precise ownership of voice output |
| `NARRATION_TIMING.json` | actual words and nonverbal windows/limitations |
| `NARRATION_PACING_REPORT.json`, `RHYTHM_MAP.json` | timing quality and rhythm structure |
| `WORLD_STYLE_PLAN.json`, `SCENE_MANIFEST.json` | medium/identity/anchors |
| `OPENING_SOURCE_PLAN.json`, `OPENING_PLAN.json` | targets, sources, trim, and handoff |
| `SHOT_PLAN.json` | shot meaning + schedule, with separate projections |
| `ASSET_MANIFEST.json` | spec/hash/role/reference/selected attempts |
| `ASSET_OBSERVATIONS.json` | bbox/metadata and evidence type; not a QC verdict |
| `MEDIA_REVIEW.json` | only when requested; scope and selected corrections |
| `LAYOUT_CONSTRAINTS.json`, `EDIT_PLAN.json` | framing constraints and edit decisions |
| `CAPTION_PLAN.json`, `OVERLAY_PLAN.json` | text and layout independent of cuts |
| `MUSIC_SELECTION.json`, `SOUND_PLAN.json`, `SFX_SELECTION.json` | actual files and cue timing |
| `COMPILED_TIMELINE.json` | deterministic render instructions, clock, and geometry |
| `RENDER_RECEIPT.json`, `TECHNICAL_QC.json` | actual technical output |
| `EDITORIAL_REVIEW.json` | opt-in only; review-method limits stated explicitly |
| `ACCEPTED_VERSION.json` | pointer with hashes and separate technical/artistic acceptance |
| delivery/release receipts | external IDs and exact accepted content hashes |

Every artifact has exactly one owner stage. Other stages do not mutate it in place. A change is produced by a new owner attempt/revision.

### 17.4. Identity and dependency

`unit_id`, `word_id`, `shot_id`, `asset_id`, `boundary_id`, `event_id`, `revision_id` are stable and independent of display order. `display_order` exists only for UI ordering.

Do not store feedback against “shot 12,” because insertion would retarget it. A boundary ID binds to versioned endpoints; moving, deleting, or splitting it requires explicit reconciliation.

### 17.5. Semantic versus timing hash boundaries

- `script_core_hash` is separate from CTA;
- `script_spoken_hash` includes the complete TTS text;
- `performance_hash` includes performance intents;
- `tts_effective_hash` includes compiled input and real settings for the chosen model;
- `asset_spec_hash` includes visual content and reference hashes, not whole-video timing;
- `shot_schedule_hash` includes timing;
- keep `edit_geometry_hash` and `caption_style_hash` separate where practical;
- acceptance receipts are separate from generated content; changing QC policy must not automatically change the image hash.

Include prompt/key version in cache keys; deploying a newer prompt version alone must not trigger unrequested media work during old-run Resume. Freeze the run's recipe version; upgrades are explicit.

### 17.6. Voice Performance contract

Events bind to actual `word_id`/span and a specific occurrence; a vague `before_token="you"` is insufficient when “you” appears multiple times.

```json
{
  "artifact_type": "voice_performance_example",
  "model_family": "eleven_v3",
  "events": [
    {
      "event_id": "vp_example_01",
      "anchor": {"position": "before", "word_id": "u_hook_w001"},
      "kind": "delivery",
      "intent": "mischievous",
      "implementation": {"type": "audio_tag", "value": "mischievously"},
      "calibration_status": "documented_not_calibrated",
      "required": false
    }
  ],
  "spoken_text_mutation_allowed": false
}
```

The matching v2 implementation may use context/punctuation/settings or break; unmet requests are recorded in `unfulfilled_intents`. An unsupported optional event is dropped with a recorded reason; a required event must be resolved before generation through compatible redesign or an explicit validation error.

---

## 18. New execution graph and activation conditions

### 18.1. One registry

`run_graph.py`, or a new registry consumed by it, must be the common source for executor, UI, revision, artifact ownership, and stage title. A decorative graph separate from the real execution path is forbidden.

For every stage define:
`id`, `title`, `phase`, `requires_data`, `requires_gate`, `condition`, `owned_artifacts`, `fingerprint_projection`, `revision_policy`, `runtime_capabilities`.

Do not assume execution-order edges are identical to semantic invalidation edges. Reading an artifact for context does not necessarily mean regenerating all descendants when that artifact changes.

### 18.2. Macro path

```text
preflight
  -> character/presentation + performance + voice resolution/capabilities
  -> evidence + history
  -> hook candidates -> text review -> hook selection
  -> story -> draft -> retention/naturalness/factual review -> final core + CTA
  -> voice performance -> model-specific compile -> ElevenLabs UI
  -> narration alignment -> technical pacing -> rhythm map
  -> opening plan + shot plan + world/scene/asset plan
  -> image assets / opening media
  -> optional media review + optional one-pass observation
  -> edit direction + caption/layout + music/sound/SFX
  -> deterministic compile -> preview/final render -> technical QC
  -> automatic accept-version (default)
  -> enabled delivery + history + Git publication
```

This macro is a conceptual ordering diagram; execution may advance independent branches. A specific number such as “43 nodes” is not a requirement. The exact graph must be derived from the real registry.

### 18.3. Rules that topology tests must prove

1. `narration_alignment` does not require images, `VISUAL_BEATS.md`, or `SHOT_PLAN`.
2. Shot scheduling derives from real audio.
3. Opening duration/source selection happens after real timing.
4. World/identity specs do not depend unnecessarily on CTA or gain.
5. `voice_compile` is a stable stage with model-specific adapter; v2 and v3 branches do not execute simultaneously.
6. Reviews that are off either disappear from the effective graph or deterministically become `SKIPPED_CONFIG`; final stages do not wait for absent artifacts.
7. Observation-off has a valid metadata/full-frame path.
8. Disabled music/SFX/publish/Git do not create orphan consumers or pending stages.
9. Music-driven mode introduces music feature extraction before edit only; sound planning after edit must not create a cycle.
10. There is no permanent critic→generator back-edge; repair attempts are versioned.
11. Asset groups expand dynamically after planning; added/removed nodes reconcile during Revise.
12. Aggregate `assets_ready` succeeds only when every active manifest asset is usable.
13. A Flow outage blocks only the Flow branch; independent work can continue and checkpoint.
14. A single shared browser/provider lock must not be confused with logical graph parallelism.
15. State `creative DONE` is not the same as run DONE.

### 18.4. Dynamic asset nodes

For each asset, logical stages such as generate, technical-validation, optional-review, ready, and optional-observation must be inspectable. They need not all appear expanded in the default graph view; ownership/status must remain traceable.

Independent images must not have blind continuity edges to each other. If an asset truly references another asset, record that exact dependency.

---

## 19. New compiler and renderer

### 19.1. One clock

Represent all visual intervals as half-open integer-frame ranges `[start_frame, end_frame)`; keep audio at sample precision. Store fps as rational `num/den`, even when the preset is 30.

Determine total frame count once from final audio duration. Do not independently round each duration and accumulate drift. Any residual distribution must follow an explicit documented policy.

Timeline requirements:
- complete ordered coverage;
- no zero/negative shots;
- intentional overlap only in defined layer/transition windows;
- original source in/out consistent with actual duration;
- audio and captions preserved without hidden mutation.

### 19.2. Transitions

A cut has zero duration; dissolve/fade uses an exact window on the fixed clock. Input/output source handles must be sufficient. A simple xfade chain that shortens total runtime for every transition is not allowed.

The renderer must normalize and respect real FFmpeg requirements for format/timebase/fps/input dimensions [F1]. Prove implementation with golden frame/timing tests, not merely by eyeballing a short sample.

Overlays and audio must not duplicate or shift at segment boundaries. Targeted movement and end-state must remain valid in compositing.

### 19.3. Bounded-memory rendering

For dozens to hundreds of assets, do not build one unbounded graph of looped image inputs. Segment/scene rendering plus transition windows, with bounded memory, local cache, and precise assembly, is appropriate.

Cache keys must include asset hash, frame range, geometry/easing, fps/resolution, renderer version, and effective settings. Filename or mtime alone is insufficient.

Render interruption, low disk, non-zero process exit, and partial files:
- must not change the final pointer;
- healthy segments may be reused;
- incomplete segments are cleaned up in a controlled way or quarantined;
- final output is first written to temp, then decoded/validated, then atomically renamed.

### 19.4. Quality and resources

Read actual host/cgroup resources and bound threads, RAM, temp disk, and supersampling. Resource pressure is not permission to silently reduce shot count or drop content.

Intermediate quality and final encoding are configurable; do not silently recompress multiple times. Receipts record actual quality/resolution/codec. Size and frame-rate constraints come from the frozen request.

Final visual duration relative to audio master/alignment must fit an explicit tolerance; target acceptance drift is at most one frame, with audio padding/encoder delay recorded. This tolerance is not a substitute for checking actual A/V synchronization.

### 19.5. Render and audio-mix ordering

Define a clear dependency contract for raw render, mix, and polished output. Gain/music-only changes must be able to preserve a valid video stream and remix/remux only audio unless filters truly modify video.

Preview and final point to the same compile hash. A QC report is valid only for the exact output hash it reviewed; never reuse an old report for a new file.

---

## 20. Dependency-aware Revise for every component

### 20.1. API and operations

Every change request includes at least:

`episode_id`, `base_revision_id`, `base_config_hash`, `base_manifest_hash`, `scope`, `target_ids`, `patch_or_feedback`, `lock_policy`, `execution_policy`.

Supported operations:
- revise hook/premise/wording/acting;
- revise script core or CTA;
- revise voice/model/performance/pause;
- revise shot plan/density/split/merge/order;
- regenerate/replace only the selected asset;
- revise framing/motion/scale;
- revise boundary/transition;
- revise subtitle/branding;
- revise music/SFX/gain;
- accept a candidate or roll back to a previous accepted version.

### 20.2. Accurate preview

Before execution, Studio and backend display one shared plan:

| Category | Meaning |
|---|---|
| `affected` | definitely recalculated/rebuilt |
| `reused` | unchanged hash/contract and usable |
| `conditional_reuse` | known only after replan or timing |
| `new` | new artifact required |
| `removed_from_active` | removed from the new version while old version is preserved |
| `disabled` | disabled by config |
| `conflicts` | lock/deleted target/stale base issues |
| `provider_calls` | known/estimated/unknown; never invent a final count |

Model-plan output may change the dynamic graph; do not present a possible reuse list as certain before that output exists.

Store preview with a plan hash/ETag. Apply must compare-and-swap against the same base. Two tabs using stale bases receive `409` plus refresh guidance. Immutable request inputs do not mutate during execution.

### 20.3. Mandatory invalidation matrix

| Change | Required owner/downstream work | Must remain preserved |
|---|---|---|
| caption color | caption style/layout/compile/render | TTS, Flow, images, script |
| caption font/size/position | layout; framing only on conflict; render | assets and audio |
| narration gain | mix/mux/QC/delivery | TTS, timing, suitable video stream |
| music | selection/sound/mix | shots/images, unless music-driven is enabled |
| SFX cue | sound/mix | image generation and narration |
| one shot's motion/scale | edit geometry and dependent pieces | source image and audio |
| one boundary cut/fade | that boundary, handles, compile/render | images and narration |
| replace one image | that asset, optional observation, consuming edits and adjacent boundaries | independent images, script, audio |
| regenerate one image prompt | only corresponding semantic asset spec/attempt | independent units |
| shot density/split | shot plan/schedule and manifest diff | TTS; still-valid semantic assets |
| tone/tag/pause | performance/compile/TTS/alignment/rhythm/schedule | canonical text and suitable images |
| v3↔v2 | model compiler/UI/TTS/timing and required performance feasibility | new editing engine, evidence/world/independent assets |
| new voice, same character | voice/performance/TTS/timing | visual identity unless related acting changes |
| CTA | CTA/TTS/timing/tail schedule | hook/core/style and independent assets |
| factual word | text/review and related semantic shots | only data that truly remains stable |
| new hook | hook/story consistency, text/audio if changed, opening and related shots | body factual assets that remain contract-valid |
| new character or style | identity/style and real consumers | independent sources/claims |
| new topic | new run with ancestry | entire previous run |
| QC policy only | future policy; no immediate generation | all current outputs |
| enable observation | observation and conditional edit | asset generation |

**Changing CTA with continuous TTS may change timing across the whole file.** Do not assume prefix audio/timing remains stable. An image whose meaning is unchanged may still be reused, but its display schedule is recalculated.

**Voice-only changes must not blanket-invalidate images.** If new duration requires an extra shot, generate only missing assets. If an opening source still has adequate duration/behavior, conditional reuse is allowed; an acting change may require a new source.

### 20.4. Multiple feedback levels, not one textarea for everything

Feedback like “don't scream, grin” belongs to acting/performance; “this orb is facing the wrong way” belongs to an asset; “make this fade a cut” belongs to a boundary; “say this sentence more clearly” may require text or performance diagnosis.

AI may translate feedback into a patch, but without allowed scope it must not rewrite core text or all assets. Preview must show semantic change. Explicit user intent outranks AI suggestion.

### 20.5. Locks and structural changes

Manual overrides bind to stable target and scope. During split/merge:
- lineage and migration must be explainable;
- transferable locks move only with evidence;
- untransferable locks create a conflict;
- no manual edit disappears silently.

Isolated regeneration means bytes of independent images do not change. If downstream content genuinely references the changed image, the user chooses explicit continuity cascade or preserve; preserve records possible provenance mismatch rather than fabricating a matching receipt.

### 20.6. Transaction and last healthy version

For a new revision:
1. freeze request and bases;
2. plan/store staging;
3. reuse through refs to immutable blobs;
4. execute and write receipts;
5. run technical QC on the exact hash;
6. run optional requested reviews;
7. atomically update accepted pointer;
8. create compatibility exports and delivery from the accepted manifest.

Failure/stop/pause preserves the previous version. Partial promotion must not create a mixture of old and new files. `ACCEPTED_VERSION.json` is the source of truth for selected output.

A late result from an older attempt/revision may not change active head or accepted version. Completion accepts only the current owner/lease.

### 20.7. Rollback

Rollback to an immutable accepted version requires no regeneration; only pointer and delivery intent change. Rollback must not automatically resend public output unless the delivery request explicitly asks for it.

---

## 21. Cache, recovery, concurrency, and error semantics

### 21.1. Resume

Reuse requires more than a non-empty artifact: provenance, input fingerprint, valid terminal status, and compatible output hash/contract must all match.

Old `RUNNING` state without a live process/job becomes `INTERRUPTED/RECONCILE_REQUIRED`, not success. Parent and Ordak jobs checkpoint separately. A stage that can be rerun must not be confused with an entire run that can be blindly resubmitted.

### 21.2. Retry

Distinguish:
- transport retry without definite regeneration;
- bounded JSON/schema repair;
- content correction only when review policy allows it;
- user-requested regenerate as a fresh revision/attempt.

Do not turn truncated raw output into “semantic success” by appending `}`. Independently validate item counts, required IDs, coverage, and verdict fields. Preserve raw and repaired text for audit.

### 21.3. Concurrency

A shared Ordak/Chrome session may safely support only one concurrent interaction. The queue/lease for that resource must be globally coordinated; a launch lock around one process is not browser coordination.

Local rendering may run independently within resource budget. Cancellation releases leases and prevents zombie children. Record heartbeat and owner epoch.

### 21.4. Statuses

At minimum, distinguish:
`QUEUED`, `RUNNING`, `REUSED`, `STALE`, `SKIPPED_CONFIG`, `DONE`, `PAUSED_AUTH`, `WAITING_PROVIDER`, `FAILED_TECHNICAL`, `FAILED_CONTRACT`, `INTERRUPTED`, `CONFLICT`.

Review-off must never create a state requiring manual approval. Semantic failure belongs only to requested review or planning contracts, not hidden image review.

### 21.5. Artifact cleanup

Run GC only after considering accepted versions, active/pending revisions, and external release references. Do not broadly delete unknown temp/output files with a loose pattern.

Source hashes, user data, sessions, generated media, and caches each need separate retention policies. Do not delete full source assets merely to free space in the middle of an active run.

---
## 22. Studio: forms, graph, timeline, and human revision

### 22.1. One schema source

New Run, Revise, JSON API, legacy form, and CLI must all converge on shared normalize/validate logic. Do not duplicate defaults across multiple React/Python files. The launch snapshot freezes all effective defaults and the schema version.

Suggested settings live under independent namespaces such as `_shorts_edit`, `_voice_performance`, and `_quality`; do not mix them into legacy `_motion`.

### 22.2. Required controls

| Group | Required controls |
|---|---|
| engine | legacy/new while preserving frozen engine; rhythm preset |
| hook | intensity, burst permission, candidate count, history policy |
| character | auto/manual, performance profile, actual gateway |
| voice | v2/v3, character-default/manual, real voice, model-specific settings |
| voice performance | hook/body intensity, pause/emphasis, allowed tags, optional candidate/selection |
| shots | auto/manual density, shot-duration policy, independent images and supported body video |
| editing | allowed primitives, cut/fade/dissolve, scale/pan bounds and overrides |
| captions | auto/manual/off, font/color/outline/position/grouping/emphasis and locks |
| brand | logo/title/watermark and display timing |
| audio | music library/upload, gain, ducking, SFX, music-driven mode |
| quality | media review off/report/strict, scope, correction budget, separate observation |
| output | format, fps, resolution, duration, preview |
| delivery | existing Telegram/Git/Release options with real behavior |

A high “intensity” input does not imply a native provider parameter; labels must not be misleading.

### 22.3. Voice model in UI

When v3 is selected, unrelated v2 fields become inactive and are excluded from the effective request; keep their values for returning later. Unknown capability is displayed as pending probe, not fabricated support.

With v2, show the controls it actually has and make expression limitations clear; the rest of the new product design remains unchanged. Selecting a model must not automatically revert to legacy editing.

Show canonical text and `TTS_INPUT` separately in the Inspector. The user must understand that a tag is a performance instruction, not a subtitle.

### 22.4. Review-off in UI

Show states such as “Generated — content review not requested,” not a fake green QC checkmark. No image/audio approval modal is mandatory in the default workflow.

A “review/revise this item” action is opt-in and scoped; temporarily enabling it must not silently mutate global config.

### 22.5. Workspace

Grouped views:
- narrative/script with word/performance markers;
- shot track;
- assets and sources;
- caption/branding;
- sound/SFX;
- versions and accepted output.

Selecting a unit highlights supporting shots; selecting a shot shows the asset, words/frames, and edit reason; selecting an event shows linked voice/caption information.

For 60–100+ shots use scene grouping, collapse, lazy loading, thumbnail cache, and virtualization. Polling must not reset selection, scroll, open forms, or typed feedback. Disabled stages must not leave the graph orange/pending.

### 22.6. Human actions after output

- play accepted or draft preview with real audio;
- click a shot and give feedback on that asset;
- change only one passage's tone, only captions, only a cut boundary, or only gain;
- compare before/after between two immutable revisions;
- see dependency cost as count/unknown, without approving every provider job;
- lock good choices;
- rollback and resume;
- choose a take/candidate only when explicitly requested.

If the user selected image scope, feedback like “make it more exciting” must not arbitrarily rewrite TTS and script too.

### 22.7. Endpoints

Preserve current routes or extend them in a version-aware way. The following are **suggested route families**; choose final names from the existing contract and document them:

- schema/capabilities;
- run graph/activity/config;
- revision preview/apply with base hashes;
- typed artifact/preview access;
- accept/rollback version;
- targeted asset/performance/boundary revision;
- opt-in calibration/candidate jobs.

All mutations need proper auth, validation, body limits, and concurrency behavior. UI-only implementation is not acceptable; backend enforces the same constraints.

---

## 23. History, delivery, and YouTube Release

### 23.1. Episode/Hook history

Use a canonical episode ID plus ancestry. Short ID and slug identify the same episode. Hook versions of the same episode must not appear as multiple independent publications in history.

Outcomes: planned, generated, technically accepted, human reviewed, completed, published, failed. Record `published` only with the corresponding receipt; automatic technical acceptance is not human approval.

Normal history weighting should emphasize valid completed/published work; a failed run must not block new ideas as if it were a public release. Weighting policy is versioned and deterministic.

### 23.2. Telegram/Git

Delivery uses one explicit accepted version/hash. Idempotency key includes episode, accepted output hash, destination, and delivery type; resume must not resend already confirmed deliveries.

A disconnect after send may create uncertainty; without receipt or reconciliation, do not claim exactly-once. Progress messages are independent of media delivery and can be disabled.

Git is last in the path and includes only allowed run/shared-catalog files. Never commit secrets, sessions, browser state, temporary downloads, oversized videos outside policy, or render cache.

Disabled Git/Telegram stages disappear from the effective DAG. Do not break an existing compatibility rule requiring at least one Telegram output without an explicit migration decision; test mode must work without external sends.

### 23.3. Release

Keep the existing Release flow independent from generation; bind it to an explicit accepted version/hash. Subtitle/script/facts/thumbnail are read from that selected version, not mutable “latest” paths.

A later video revision must not silently rewrite prior metadata/thumbnail. The existence of an old `polished.mp4` alone is not permission to release an incomplete revision.

Automatic public YouTube upload is outside this mission. Preserve existing manual-package capability.

### 23.4. Audience measurement

Export hook/first-proof/gateway/payoff markers plus actual shot display times so they can later be compared against retention. Image count, cut count, and model scores are not definitive success KPIs.

In future analysis, record Stayed to watch, engaged views, AVD/APV, and retention curve separately with the correct definitions and denominators; raw view count is not a substitute [Y1–Y2]. Choosing a winner from one published video without controlling for topic/audience/timing is not a definitive causal result.

---

## 24. Security, robustness, and truth boundaries

- Never print/commit secrets, API keys, cookies, tokens, or session files.
- Validate paths, symlink resolution, extension/MIME/signature, upload size, and archive extraction.
- Escape caption/overlay text against ASS/HTML/script injection.
- The model may not execute shell, modify locked settings, or introduce paths outside the repo.
- Content prompts and source_notes are data; source text must not override system instructions.
- UI snapshots/logs may contain account information; sanitize and limit retention.
- Face/character images and voice assets require existing authorization/ownership; unauthorized cloning of a real person's voice is not part of the design.
- “Natural and conversational” is a quality target, not a guarantee of undetectable AI or a way to bypass required disclosure.
- Do not use strobe or painful audio jumps as retention tactics; hook intensity comes from event/contrast.
- Model/provider availability changes; record observed UI schema and test date.
- Unobserved output is never “observed,” unreviewed is never “approved,” and mocked is never “production tested.”
- A missing optional service must not block independent work; a missing required contract must not be replaced with placeholder success.

---

## 25. Affected files, compatibility, and code organization

### 25.1. Mandatory re-audit

In P00, locate the real paths and inspect callers for these categories:

| Area | Baseline file/path |
|---|---|
| runner | `scripts/run_q_station_pipeline.py` |
| wrapper | `scripts/run_full_video_pipeline_q_station_wrapper.py` |
| completion | `scripts/run_completion_pipeline.py` |
| timing/source | `scripts/align_beats.py`, `plan_opening_sources.py`, `trim_opening_clips.py` |
| timeline/render | `scripts/build_timeline.py`, `render_video.py`, `qc_render.py` |
| voice | `scripts/run_elevenlabs_voiceover.py`, `voice_profiles/` |
| registry/graph | `scripts/run_graph.py`, `pipeline_stages.py`, `content_projects.py` |
| panel | `scripts/panel_contract.py`, `video_control_panel.py` |
| identity/presentation | `character_runtime.py`, `presentation_runtime.py`, character/profile catalogs |
| provider | `scripts/ordak_jobs.py`, `services/ordak`, `services/ajil_uag` |
| history/release | `episode_history.py`, notifier, summary, commit and release modules |
| UI | `control_panel/ui/src/main.jsx`, `studio-utils.js`, `studio.css` |
| contracts/prompts | `projects/q_station/PROJECT.json`, characters and prompts |
| tests/CI | `tests/`, UI tests, package.json, lockfiles, `.github/workflows/` |

Do not rely only on docs; runtime code and tests take precedence. Use `rg` to locate all callers relying on `len(body)`, numeric beat IDs, `VOICE_FIELDS`, `_motion`, final-QC existence, and hard-coded paths.

### 25.2. Suggested isolation

A new package such as `scripts/shorts_v2/` may contain clear responsibilities:
contracts/settings, stage registry, story/hook, voice/performance, alignment/rhythm, assets, editing/layout, captions, sound, compiler/render, revisions/state, and quality policy.

This does not require every file to use exactly those names. Avoid one giant God module and avoid multiple parallel frameworks. Share contracts first; generators and UI consume the same definitions.

### 25.3. Legacy

A run without an engine marker resolves to legacy, not new V2. Preserve frozen config on resume. Changing engine for an existing run is an explicit fork/new-version operation with preservation.

Do not silently overwrite legacy prompts to gain new behavior. New-run default switches to shorts_v2 only after rollout acceptance; freeze its recipe/version.

Compatibility adapters for summary/release are required. Enforce one-image-per-body only in legacy. A derived visual-beats Markdown file must not become V2 timing authority again.

### 25.4. Defaults and migration

- new default: QC off and automatic production with no human gate;
- a new voice preset may default to v3, but explicit v2 selection takes precedence and remains fully supported;
- existing-run defaults do not change;
- missing new fields resolve through pure/read-compatible migration; merely opening Revise must not cause hidden generation changes;
- `_qh` or other unknown old fields are migrated/namespaced only after provenance audit; do not blindly delete them, and ensure refactoring still tests legacy decoding;
- schema downgrade/upgrade and incompatible model changes must be explicit and rollbackable.

---

## 26. Execution phases and outputs for each phase

These phases are **all mandatory**. Some independent work can proceed in parallel, but there must be one shared checkout/contract owner. Do not let multiple agents independently rewrite shared schema/registry/Studio code without coordination.

### P00 — inventory, baseline, and durable memory

**Work:** copy this document into docs; read AGENTS; audit Git/submodules; determine runtime/commands and baseline tests; report current contracts and delta from this design.
**Output:** baseline audit, SHAs, dependency map, test command list, initialized ledger.
**Acceptance:** no destructive change or main write; work remains continuable; baseline failures are separated from later regressions.
**Tests:** `T01`, `T02`, `T70`.

### P01 — schemas, settings, and versioned contracts

**Work:** separate engine/model/QC; typed schemas; canonical text/tokens/IDs; receipt/provenance; quality policy and field precedence.
**Output:** schema registry, fixtures, validators, shared config normalization, initial artifact ownership.
**Acceptance:** incomplete schema/NaN/invalid IDs rejected; v2↔v3 never falls back to legacy; no hidden QC.
**Tests:** `T03–T10`, `T20`, `T21`.

### P02 — orchestration skeleton, state, and dispatch without breaking legacy

**Work:** runtime registry and effective DAG; logical artifact/revision resolver; provider-call spies; enable/disable nodes; single-writer/leases.
**Output:** new-engine path with fake fixtures explicitly marked test-only; healthy legacy dispatch.
**Acceptance:** DAG acyclic and resumable; old Motion Director has no runtime import in the new path; do not yet claim production readiness.
**Tests:** `T11`, `T12`, `T22`, `T23`, `T54`.

### P03 — model-aware ElevenLabs UI in Ordak/adapter

**Work:** audit current UI; complete v2/v3 adapter, capability probe, text verification, bound result/download and recovery; modify submodule only if necessary with reproducible deployment.
**Output:** runnable real transport + DOM fixtures + structured errors.
**Acceptance:** not merely a dropdown; v3 works without v2 sliders; stale result is not consumed; lack of server recorded as BLOCKED_ENV separately from code.
**Tests:** `T13–T19`, `T51–T53`; live evidence for `T68` also attaches to this adapter.
**Readiness separation:** code completion and fixture tests in this phase may allow P05 to proceed even if real smoke is deferred to P14. In that case record phase `code_ready` and `live_validation_pending` in evidence instead of claiming live PASS. Missing external smoke alone must not block the independent work chain.

### P04 — Evidence, character performance, Hook Engine, and script

**Work:** 4 versioned profiles; six Hook Packages; text reviewer/tournament; story/retention/naturalness/factual review; separate CTA; source provenance.
**Output:** complete prompts with input/output contracts, context builders, schemas, and accept/reject fixtures.
**Acceptance:** irrelevant scream hook rejected; real payoff; scientific qualifiers preserved; selected model's voice feasibility considered.
**Tests:** `T24–T28`, `T65`.

### P05 — Performance Director and v2/v3 compilers

**Work:** canonical/compiled separation; typed tag/break AST; word anchors; palette and optional calibration; profiles/manual locks; TTS hash/provenance.
**Output:** v3 expressive and v2 optimized end-to-end through UI input; no extra spoken words.
**Acceptance:** v2 receives no v3 tags; v3 receives no SSML break; defaults continue without human take approval; configured voices are real and available.
**Tests:** `T03–T09`, `T13`, `T20`, `T29–T31`.

### P06 — independent alignment, pacing, and rhythm

**Work:** timing from clean text+audio; ID mapping; nonverbal uncertainty; bounded technical correction; actual-duration cap; rhythm markers.
**Output:** `NARRATION_TIMING`/`RHYTHM_MAP` independent of visuals and with clean subtitles.
**Acceptance:** a laugh before the first word is not cut off; voice change does not reuse old timestamps.
**Tests:** `T32–T36`, `T45`.

### P07 — shot plan, manifest, and media with QC off

**Work:** multi-shot scheduling; world/scene anchors; independent asset-spec hashes; precise image generation; opening profiles/timing; centralized review policy and one-pass observation.
**Output:** distinct assets with provenance and no default loop; body video only for supported roles.
**Acceptance:** one sentence can have multiple images; 30–60+ images without economic ceiling; QC off includes entry/reference assets; observation cannot regenerate.
**Tests:** `T20–T23`, `T37–T40`, `T46`, `T66`.

### P08 — new editing and compiler/renderer vertical slice

**Work:** Edit Director, geometry solver, integer clock, cuts/fades/scale/pan, segment cache, and real fixture render.
**Output:** first audiovisual vertical slice from the new engine with no old motion module.
**Acceptance:** transitions do not change the master clock; safe crop; 100 shots without one monolithic unbounded input graph.
**Tests:** `T11`, `T41–T44`, `T47–T50`.

### P09 — captions, branding, music/SFX, and audible preview

**Work:** shared layout, keyword emphasis, locks, title timing, music override, sound plan, mix/mux, preview parity.
**Output:** complete audiovisual preview from one compile; disabled branches remain valid.
**Acceptance:** caption-off is real; title/voice do not duplicate; gain-only does not regenerate narration.
**Tests:** `T23`, `T42`, `T43`, `T55–T58`, `T62`.

### P10 — Revise, version staging, plan diff, and promotion

**Work:** stable scope/targets; preview/apply CAS; semantic asset reuse; late-result guard; lock reconciliation; accepted rollback.
**Output:** every revision type in section 20, not only image regeneration.
**Acceptance:** five critical tests: caption-only, gain-only, asset-only, voice/model-only, failed-revision preservation.
**Tests:** `T45–T46`, `T54–T61`.

### P11 — complete Studio and real graph

**Work:** shared-schema forms; model-aware controls; clear QC/observation; tracks; node grouping; versions; feedback/compare; audible preview; APIs.
**Output:** usable production UI, build/dist according to repo policy, and browser E2E.
**Acceptance:** user can complete core scenarios without manual JSON; polling and 100-shot UI remain usable; legacy read-only behavior is appropriate.
**Tests:** `T60–T64`, `T69`.

### P12 — history, Release, delivery, and compatibility

**Work:** ID dedupe, outcome/ancestry, release-version pinning, notifications, Git artifact allowlist, legacy exports, migration tests.
**Output:** new engine represented in all consumers while legacy remains healthy.
**Acceptance:** main unchanged; technically accepted is not conflated with human-approved; resume does not duplicate confirmed delivery.
**Tests:** `T01–T02`, `T59`, `T65–T67`.

### P13 — full regression, robustness, and runbooks

**Work:** complete test suite and UI build/E2E; property-based invariants; resource/chaos tests; prompt fixtures; dependency security; deployment/rollback runbook.
**Output:** real logs and complete R→code→test traceability; remaining blocker list.
**Acceptance:** lint/build/test recorded; mocks clearly identified; tests do not mutate real source-pack files.
**Tests:** all `T01–T70` at the evidence level available in the environment; `T68` remains separate until server access.

### P14 — real smoke, rollout acceptance, and final handoff

**Work:** in an authorized/idle environment, test browser v2 and v3, all four character/gateways, QC off, major Revise paths, preview/final, and pause/resume; pin/update necessary services with backup.
**Output:** real sample with hashes, screenshots/logs, and human post-output report; no approval gate between every stage.
**Acceptance:** provider-free tests do not substitute for smoke; artistic quality human-pending is explicit; after readiness, new-run default is activated while legacy history remains intact.
**Tests:** `T68`, `T69`, `T70` plus user-scenario tests.
**Limitation:** without server/credentials, keep P14 `BLOCKED_ENV` and provide a complete deployment runbook; do not claim production readiness.

### 26.1. Execution order and incremental delivery

Start with P00–P02, then voice UI P03 and creative core P04; then P05–P09, P10–P12, and P13–P14. Revision skeleton and provider-call spying must already exist in P02; P10 is not the point to introduce revision architecture for the first time.

Every phase gets a coherent commit, tests, and ledger update. Do not move to the next phase without easy rollback. “It takes a long time” is not a reason to omit a phase; if context ends, provide a precise handoff.

The phase order above is also constrained by the selected multi-chat route in section 0.5. Finishing early does not authorize a chat to cross its hard stop. Finishing late does not authorize the next chat to skip the unfinished phase. Phase acceptance controls technical progress; `current_chat_slot` controls the session boundary.

### 26.2. Prompt package Codex must actually build

For each row, build a versioned template, context builder, strict schema, valid few-shot examples, and failing fixtures; all placeholders must resolve completely:

| Prompt/role | Output and key prohibition |
|---|---|
| evidence/source assessor | claim scope; fabricated citations forbidden |
| character-performance context | baseline+burst while preserving identity |
| hook candidate director | 6 distinct packages; truth/payoff mandatory |
| hook independent reviewer | real gates; score ≠ retention probability |
| hook top-two tournament | eligible only; reasoned selection |
| story architect | causal progression and first proof |
| natural script writer | spoken text independent of image count |
| retention/naturalness editor | preserve mechanism and uncertainty |
| factual/script critic | causal errors and repetition, not merely JSON validity |
| CTA writer | user intent, short and conversational |
| performance director | intent only on tokens; no word mutation |
| rhythm/shot director | real clock and new information for each shot |
| asset specification/prompt writer | compositional intent + exact reference roles |
| observation | geometry/metadata only, with no verdict or regenerate |
| opening prompt writer | gateway/acting/timing under source contract |
| edit director | typed decisions, not executable expressions |
| caption/layout director | clean words, locks, safe bounds |
| sound director | justified cues, no whoosh-per-cut |
| optional media/editorial critic | requested scope only, with real evidence |
| revise feedback interpreter | patch within user scope, no unintended changes |

This table does not require 20 separate provider requests in every run. Combining stages with the same responsibility is allowed for reliability, provided artifact ownership, tests, and revision semantics remain explicit.

---
## 27. Acceptance matrix and mandatory tests

Every Test ID must be traceable to a real test file/command/report. Provider-behavior tests use spies/mocks in CI; fake outputs must never enter production directories.

| ID | Scenario | Expected |
|---|---|---|
| T01 | branch/file restrictions | no write/merge/reset on main or unrelated files |
| T02 | old run without engine marker | legacy/frozen behavior, no migration or unintended spend |
| T03 | separation of three axes | TTS v2/v3 independent of engine and QC |
| T04 | compile v3 | allowed tags, no SSML break, no spoken-word mutation |
| T05 | compile v2 | no v3 tags; bounded breaks and valid punctuation |
| T06 | canonical tokens | numbers, decimals, percentages, contractions, and negation preserved |
| T07 | capability-aware settings | unsupported control not forced; real mismatch fails clearly |
| T08 | switch v2→v3→v2 | profile values preserved and inactive fields excluded from execution |
| T09 | effective fingerprint | disabled/unrelated field does not invalidate generation |
| T10 | schema/JSON | reject truncation, missing IDs, duplicate IDs, NaN, and unsafe unknown data |
| T11 | independence from Motion Director | import trap and poisoned MOTION_PLAN have no effect |
| T12 | effective DAG | acyclic, with no missing dependencies for valid configs |
| T13 | v3 UI | real modes, no v2 sliders, correct model read-back |
| T14 | v2 UI | slider min/max/step/read-back and correct text output |
| T15 | text editor | textarea/contenteditable, newline/tag preservation, read-back hash |
| T16 | old UI result | previous Download must not acknowledge a new request |
| T17 | concurrent/wrong download | file from another job or partial file is not consumed |
| T18 | login/CAPTCHA | real human pause, no bypass or blind retry |
| T19 | ambiguous voice/model | wrong/same-name/unavailable selection reported explicitly |
| T20 | QC off for all visual assets | zero content-review calls, zero content-correction, zero human gate |
| T21 | review provenance | `not_requested`/null instead of fake approved/pass |
| T22 | observation | auto_once without verdict/regenerate; off means zero uploads; failure uses safe fallback |
| T23 | disabled branches | disabled SFX/music/review/publish create no pending dependency |
| T24 | six hooks | semantic differences, ID coverage, top-two eligible selection |
| T25 | unrelated scream | rejected even with high score; topic-driven shock allowed |
| T26 | correctness | reject unpaid promise, fabricated number, erased qualification, causal confusion |
| T27 | character tone | 4 profiles with baseline+burst; no contradictory prompt or forced caricature |
| T28 | hook feasibility under v2 | unsupported vocal effect cannot be essential; model does not silently change |
| T29 | calibration | lack of human approval does not stop normal production; no fake provenance |
| T30 | nonverbal/caption | tags, breaks, and sound directions never become spoken subtitles |
| T31 | take policy | default one take and automatic technical acceptance; no “best acting” claim |
| T32 | alignment without visuals | removing VISUAL_PLAN/VISUAL_BEATS does not block new timing |
| T33 | confidence/backend | interpolated timing is not relabeled measured; critical mismatch is explicit |
| T34 | laugh before first word | timeline starts from real audio; blind trim does not delete it |
| T35 | real duration | script estimate insufficient; bounded technical correction and realign |
| T36 | word IDs | stable for voice-only changes; correct occurrence/lineage with repeated text |
| T37 | 1 unit, 4+ assets | same sentence/audio can own multiple independent images |
| T38 | asset semantic hash | timing/order-only changes do not regenerate a healthy asset |
| T39 | reference policy | identity/style/composition separated; full-bleed/no-page-leakage prompt contract |
| T40 | opening source | real source/trim lengths; red-door contract remains intact |
| T41 | integer clock | total frames determined once; no gaps/negative slots |
| T42 | transition stress | many fades do not shorten duration/narration |
| T43 | caption across cut | continuous text/timing, tags removed, overlay not duplicated |
| T44 | geometry | viewport bounds, upscale limits, locks, no-op, fast-move safety |
| T45 | voice/model/performance revise | TTS/timing change, independent images preserved, opening reuse conditional |
| T46 | asset-only revise | independent image bytes/hashes and audio remain fixed; relevant consumers rebuild |
| T47 | resources | 1/20/60/100 shots with bounded usage and real logs |
| T48 | renderer interruption | healthy segments reused; partial final never accepted |
| T49 | corrupt file/low disk | real error, last accepted preserved, no fake successful artifact |
| T50 | A/V drift | at most one frame with clock/encoder-delay evidence |
| T51 | provider disconnect | reconcile before resubmit; uncertainty recorded |
| T52 | late result | old revision cannot overwrite new head |
| T53 | job ownership | owner/run/attempt/lease bound to browser result; duplicate process controlled |
| T54 | revision failure/stop | last accepted remains playable/selectable |
| T55 | caption-only | zero TTS/image/Flow generation calls |
| T56 | gain-only | zero TTS/image/Flow calls; suitable stream reused |
| T57 | music-only | default image/cuts unchanged; music-driven dependencies correct |
| T58 | SFX off | zero acquire/generate and no hidden effect; narration remains |
| T59 | release/delivery | fixed accepted hash, no stale master, send checkpoints |
| T60 | two tabs/stale base | 409; patch not applied to wrong version |
| T61 | locks across split/merge/reorder | lineage or conflict; silent deletion forbidden |
| T62 | preview/final parity | matching cut/clock/crop/font/layout and audible preview |
| T63 | New Run/Revise/API/CLI | shared normalization, round-trip, correct disabled controls |
| T64 | 100-shot UI | grouping/virtualization; selection/scroll/feedback survive polling |
| T65 | history | short-id/slug dedupe, outcome, failed weighting, A/B ancestry |
| T66 | four gateways | first/last/source/timing contracts; QC off preserves “unreviewed” semantics |
| T67 | legacy/release adapters | consumers read correct engine; old output preserved |
| T68 | real Eleven smoke | web generation v2 and v3 with provable read-back/download/receipt |
| T69 | real product E2E | launch→output→human feedback→targeted revise; usable Studio/audio |
| T70 | handoff/CI integrity | honest logs/ledger, tests do not mutate source, continuation works in a fresh session |

### 27.1. Important content fixtures

Use negative fixtures for dry/misleading science, thickness-vs-area confusion, unrelated analogy, a scene that is only “visible” because prose explains it, and weak storyboard. These fixtures must not turn scientifically wrong data into an approved production example.

A correct fixture must come from a specific claim/source. A review is not credible merely because the model reports high confidence.

### 27.2. Evidence levels

For every Test ID record the evidence level:

- `UNIT`: validator/data logic;
- `INTEGRATION_FAKE_PROVIDER`: calls and stage behavior without real provider media;
- `RENDER_FIXTURE`: real FFmpeg with local fixture;
- `BROWSER_FIXTURE`: mocked DOM/controller or controlled local page;
- `BROWSER_LIVE`: real provider UI;
- `PRODUCT_LIVE`: real end-to-end video;
- `HUMAN_POST_OUTPUT`: human review after output, not a normal mid-pipeline stop.

Without an audio critic, UNIT or ASR cannot substitute for HUMAN_POST_OUTPUT when judging whether acting sounds natural.

### 27.3. Test commands

Determine real repository commands in P00. Adapt the following execution pattern to the actual package.json/venv; do not assume an unavailable tool is installed:

```bash
python -m compileall -q scripts
python -m pytest -q -rs tests
npm --prefix control_panel/ui ci
npm --prefix control_panel/ui test
npm --prefix control_panel/ui run build
git diff --check
git status --short
```

Ensure new test files are discoverable by the full suite; running only one selected test file is insufficient. Install/configure a real E2E browser runner or record a documented blocker; helper tests are not a substitute.

Use the project's actual venv/Node version. Frontend builds may update tracked dist; review/commit according to repo policy. Captured test output must preserve the original pipeline exit code; `tee` must not hide a failing test.

CI must not require provider login, paid media production, or real secrets. Tests use temporary fixtures and must not overwrite `projects/q_station/characters/.../refs`.

### 27.4. Suggested property tests

Generate varied cases for interval coverage, rounding distribution, repeated words, ID reconciliation, conditional DAGs, many boundaries, Unicode subtitles, path traversal, atomic promotion, and manifest diff.

Minimum configuration combination:
`2 voice models × 3 review policies × 2 observation modes × 2 subtitles states × SFX on/off`
should be covered by cheap logic tests; paid generation for every combination is unnecessary.

### 27.5. Initial requirement traceability

This table defines expected design/test coverage, not implementation status. Codex must add actual code paths and real test evidence for each row in the ledger or traceability report. No requirement is DONE merely because it appears here.

| Requirement | Design section | Execution phase | Expected test |
|---|---|---|---|
| R01 | 1, 25 | P00, P12 | T01, T02 |
| R02 | 14 | P02, P08 | T11 |
| R03 | 13, 17 | P01, P07 | T32, T37 |
| R04 | 13, 19 | P07, P08 | T37, T47 |
| R05 | 6 | P04 | T24, T25, T28 |
| R06 | 7 | P04 | T26, T27 |
| R07 | 6, 8, 12 | P04, P05, P07 | T27, T28, T34 |
| R08 | 9, 10 | P03, P05 | T04, T13, T68 |
| R09 | 9, 10 | P03, P05 | T05, T14, T68 |
| R10 | 4, 9 | P01, P05 | T03, T08, T45 |
| R11 | 10 | P03 | T13–T19, T68 |
| R12 | 1, 10 | P03, P14 | T18, T19, T68 |
| R13 | 8, 17 | P01, P05 | T04–T06, T30 |
| R14 | 11 | P06 | T32, T33, T50 |
| R15 | 11 | P06 | T30, T34, T36 |
| R16 | 5 | P01, P07 | T20, T21 |
| R17 | 5 | P02, P07 | T20, T22, T31 |
| R18 | 5, 14 | P07, P08 | T22, T44 |
| R19 | 5, 19, 24 | P01, P08, P13 | T10, T41, T44, T49 |
| R20 | 6, 7, 26.2 | P04, P07 | T24–T28, T39 |
| R21 | 11, 14–16 | P06, P08, P09 | T36, T43, T57, T58 |
| R22 | 20, 22 | P10, P11 | T45, T46, T55–T61, T69 |
| R23 | 17, 20 | P01, P10 | T38, T45, T46, T55–T58 |
| R24 | 20, 21 | P02, P10 | T48, T49, T54 |
| R25 | 20, 22 | P10, P11 | T60, T61 |
| R26 | 14, 15, 20 | P08, P09, P10 | T44, T61, T63 |
| R27 | 18, 22 | P02, P11 | T12, T63 |
| R28 | 10, 21 | P03, P10 | T16–T18, T48, T51–T54 |
| R29 | 13, 19 | P07, P08, P13 | T47, T48, T64 |
| R30 | 11, 19 | P06, P08 | T41–T43, T50 |
| R31 | 15, 22 | P09, P11 | T62 |
| R32 | 12, 23, 25 | P07, P12 | T02, T40, T66, T67 |
| R33 | 6, 23 | P12 | T65 |
| R34 | 20, 23 | P10, P12 | T54, T59 |
| R35 | 17, 21 | P01, P02, P13 | T09, T10, T38, T53 |
| R36 | 27 | P03, P13, P14 | T68–T70 and evidence levels for all tests |
| R37 | 0, 29, 31 | P00 and all phases | T70 |
| R38 | 2, 5, 24, 28 | all phases | T21, T29, T33, T70 |
| R39 | 5, 8 | P05, P07 | T20, T29, T31 |
| R40 | 6, 23, 30 | P04, P14 | T24, T26, T70 |
| R41 | 26, 28 | all phases | T69 and each phase's acceptance criteria |
| R42 | 4, 9, 10 | P01, P03, P05 | T07, T19, T28 |

---

## 28. Definition of Done and acceptable delivery

### 28.1. Code completion

All R01–R42 are connected to implementation/tests; runnable v2 and v3 voice paths exist under the new editing engine; no TODO remains on the critical path; no dummy receipt; quality-off behavior is correct; Revise and Studio are complete; legacy regressions are covered; build plus unit/integration/render tests exist.

“Backend only,” “prompts only,” “v3 dropdown,” “legacy motion under a new name,” or “regenerate every image for every Revise” does not count as complete.

### 28.2. Operational completion

Clone/deploy is reproducible; submodule/patch is reachable; real browser capability is known; source/result binding works; resource bounds and rollback exist. Executed production smoke is recorded as separate evidence.

Lack of real access allows a code-ready delivery with an explicit blocker, but not a production-ready claim. Independent phases must not stop because of that missing access.

### 28.3. Product acceptance

Without mandatory QC interruption, the user can:
1. choose topic, character, and v2 or v3;
2. receive a strong hook and fast, information-bearing shots;
3. watch the complete output with audio;
4. Revise one passage's tone, one image, one caption, or one transition;
5. rebuild only real dependencies;
6. preserve the previous healthy version and compare it against the new version.

Final artistic quality and retention impact are judged after output by humans/audience; automation alone cannot guarantee the quality of every generation.

### 28.4. Final Codex report

- dev commit SHAs and push state;
- completed/incomplete phases and related Test IDs;
- commands and real results;
- launch/revise/preview paths and schemas;
- Ordak version/patch and deployment/rollback commands;
- real v2/v3 sample hashes if smoke was executed;
- all blockers and degraded behaviors transparently;
- exact `next_action` for remaining work, with no promise of background execution.

### 28.5. Allowed design changes

After inspecting the code, Codex may improve module/stage partitioning, route names, compiler algorithms, and chunking strategy. Conditions: requirements remain intact, migration/invalidation/tests are updated, rationale is recorded in the Decision Log, and graph/schema remain coherent.

Product changes such as turning QC on by default, requiring human calibration, reverting v2 to the old slideshow, removing a gateway, using an API fallback, breaking privacy, or reusing the old Motion Director **are not silently allowed changes**.

---
## 29. Progress ledger — the single source for continuing Codex execution

### 29.1. How to update it

Update the JSON between the markers below after every batch. It represents the reconciled execution state and the next safe continuation point.

The `evidence` list must contain real paths and outcomes, not empty assertions. Prefer recording the latest test run and plan version in commits. Write `last_verified_head` only after inspecting Git, not from chat memory.

<!-- EXECUTION_LEDGER_START -->
```json
{
  "schema_version": 2,
  "design_version": "2.2-final-execution-contract",
  "repository": "M2002HR/YT_Video_Generation_Pipeline",
  "target_branch": "dev",
  "baseline_reviewed_commit": "e4cd11c5ad21d6e1fda36af2e157184aecfb2738",
  "last_verified_head": "16d5c98aea8540c0bc7f8cc9db230469c5105d01",
  "last_session_id": "C2-2026-09-20-01",
  "overall_status": "IN_PROGRESS",
  "code_ready": false,
  "production_smoke_passed": false,
  "human_artistic_acceptance": "NOT_REQUESTED",
  "active_phase": "P05",
  "next_phase": "P05",
  "next_action": "C2_CREATIVE: implement P05 canonical-to-execution separation, typed performance AST, model-specific v2/v3 compilers, word anchors and TTS fingerprints using the P04 script/profile contracts; run T03-T09, T13, T20 and T29-T31; do not redo P04 or begin P08.",
  "execution_chat_plan": {
    "mode": "FOUR_CHAT",
    "selected_during_phase": "P00",
    "selection_status": "CONFIRMED",
    "current_chat_slot": "C2_CREATIVE",
    "routes": {
      "FOUR_CHAT": [
        {
          "slot": "C1_FOUNDATION",
          "phases": ["P00", "P01", "P02", "P03"],
          "stop_after": "P03_CODE_READY_OR_DONE"
        },
        {
          "slot": "C2_CREATIVE",
          "phases": ["P04", "P05", "P06", "P07"],
          "stop_after": "P07_DONE"
        },
        {
          "slot": "C3_EDIT_AND_REVISE",
          "phases": ["P08", "P09", "P10"],
          "stop_after": "P10_DONE"
        },
        {
          "slot": "C4_PRODUCT_AND_ROLLOUT",
          "phases": ["P11", "P12", "P13", "P14"],
          "stop_after": "FINAL_REPORT_AND_LEDGER_RECONCILED"
        }
      ],
      "THREE_CHAT": [
        {
          "slot": "C1_FOUNDATION_AND_CREATIVE",
          "phases": ["P00", "P01", "P02", "P03", "P04"],
          "stop_after": "P04_DONE"
        },
        {
          "slot": "C2_MEDIA_ENGINE",
          "phases": ["P05", "P06", "P07", "P08", "P09"],
          "stop_after": "P09_DONE_WITH_LOCAL_RENDER_FIXTURE"
        },
        {
          "slot": "C3_REVISION_PRODUCT_ROLLOUT",
          "phases": ["P10", "P11", "P12", "P13", "P14"],
          "stop_after": "FINAL_REPORT_AND_LEDGER_RECONCILED"
        }
      ]
    }
  },
  "environment": {
    "checkout": "/opt/YT_Video_Generation_Pipeline",
    "python": ".venv/bin/python 3.12.3",
    "node": "22.23.2",
    "ffmpeg": "6.1.1-3ubuntu5",
    "browser_access": "ORDAK_HEALTHY_CHROME_RUNNING_CHATGPT_AND_ELEVENLABS_LOGGED_IN",
    "elevenlabs_session": "HEALTHY_NON_GENERATING_V2_V3_CAPABILITY_PROBE_PASS",
    "ordak_commit": "6456e9957e6b44eef9a99e60ab372eb258077af8"
  },
  "phases": [
    {
      "id": "P00",
      "title": "inventory_baseline_handoff",
      "requires": [],
      "status": "DONE",
      "commits": [
        "57aa33ad893c1723da5d2c41069640f0efbb0622"
      ],
      "evidence": [
        "Baseline compile: exit 0, /tmp/qstation-v2-c1-baseline-compile.log",
        "Baseline pytest: 782 passed, 19 failed, 1 skipped, exit 1, /tmp/qstation-v2-c1-baseline-pytest.log and /tmp/qstation-v2-c1-baseline-pytest.xml",
        "Ordak health: PASS; Chrome running and ChatGPT logged in",
        "Baseline audit and protected-dirty-work inventory: docs/QSTATION_SHORTS_V2_2_BASELINE_AUDIT.md"
      ],
      "blockers": []
    },
    {
      "id": "P01",
      "title": "schemas_settings_contracts",
      "requires": [
        "P00"
      ],
      "status": "DONE",
      "commits": [
        "bf73ad4ec0ad72f3570911a9b7376eadaa012420"
      ],
      "evidence": [
        "Strict engine/model/quality/artifact schemas and precedence: scripts/shorts_v2/contracts.py",
        "Canonical unit/token identities: scripts/shorts_v2/canonical_text.py",
        "Schema and canonical-text tests: tests/test_shorts_v2_contracts.py"
      ],
      "blockers": []
    },
    {
      "id": "P02",
      "title": "orchestration_state_engine_dispatch",
      "requires": [
        "P01"
      ],
      "status": "DONE",
      "commits": [
        "95a6183a24cffedc71257ebc5dc06b3dec650506"
      ],
      "evidence": [
        "Independent effective DAG, artifact resolver, resumable state, leases and fixture-only provider spy: scripts/shorts_v2/",
        "Explicit dispatch and plan-only executable path: scripts/run_shorts_v2_pipeline.py, scripts/run_graph.py, scripts/run_full_video_pipeline_q_station_wrapper.py",
        "No legacy Motion Director imports in the new runtime path; plan-only integration and routing tests pass"
      ],
      "blockers": []
    },
    {
      "id": "P03",
      "title": "elevenlabs_web_v2_v3_adapter",
      "requires": [
        "P00",
        "P01",
        "P02"
      ],
      "status": "READY_FOR_REVIEW",
      "commits": [
        "bea5c6732c2b4cd74ba3fbc7a985358bb196f630",
        "ce554cfa54371f9d2e55955c08dd1a45635e390e"
      ],
      "evidence": [
        "code_ready=true; live_validation_pending=true for paid Generate/result/download smoke owned by P14",
        "Authenticated live non-generating probe PASS: v2 exposes textarea plus speed/stability/similarity/style; v3 exposes contenteditable plus native Stability=0.5 categorical mapping; final UI restored to Eleven v3 / Liam - Energetic, Social Media Creator",
        "Attempt state machine, exact text readback hash, pre-submit result baseline, bound new-result identity, dedicated attempt download, ffprobe validation and structured receipt implemented",
        "Provider-free adapter tests: tests/test_elevenlabs_v2_v3_adapter.py"
      ],
      "blockers": []
    },
    {
      "id": "P04",
      "title": "evidence_character_hook_script",
      "requires": [
        "P01",
        "P02"
      ],
      "status": "DONE",
      "commits": [
        "16d5c98aea8540c0bc7f8cc9db230469c5105d01"
      ],
      "evidence": [
        "Four strict versioned character performance profiles with separate v2/v3 bindings and Shorts-only behavior scope: scripts/shorts_v2/creative_profiles.json",
        "Evidence/source provenance, six-package hook validation, independent hard-gate review, deterministic top-two tournament, story/script/CTA contracts, semantic history and ten versioned prompt/context builders: scripts/shorts_v2/creative.py",
        "Provider-free T24-T28/T65 accept/reject fixtures plus artifact ownership coverage: tests/test_shorts_v2_creative.py and tests/test_shorts_v2_orchestration.py",
        "Targeted P04 regression: 50 passed, exit 0, /tmp/qstation-v2-c2-p04-targeted.log",
        "Full Python regression: 827 passed, 19 failed, 1 skipped, exit 1; exact same 19 baseline failures, /tmp/qstation-v2-c2-p04-full.log and /tmp/qstation-v2-c2-p04-full.xml"
      ],
      "blockers": []
    },
    {
      "id": "P05",
      "title": "performance_compilers",
      "requires": [
        "P03",
        "P04"
      ],
      "status": "NOT_STARTED",
      "commits": [],
      "evidence": [],
      "blockers": []
    },
    {
      "id": "P06",
      "title": "alignment_pacing_rhythm",
      "requires": [
        "P05"
      ],
      "status": "NOT_STARTED",
      "commits": [],
      "evidence": [],
      "blockers": []
    },
    {
      "id": "P07",
      "title": "shot_assets_opening_qc_off",
      "requires": [
        "P04",
        "P06"
      ],
      "status": "NOT_STARTED",
      "commits": [],
      "evidence": [],
      "blockers": []
    },
    {
      "id": "P08",
      "title": "new_edit_compiler_renderer",
      "requires": [
        "P02",
        "P07"
      ],
      "status": "NOT_STARTED",
      "commits": [],
      "evidence": [],
      "blockers": []
    },
    {
      "id": "P09",
      "title": "captions_branding_sound_preview",
      "requires": [
        "P06",
        "P08"
      ],
      "status": "NOT_STARTED",
      "commits": [],
      "evidence": [],
      "blockers": []
    },
    {
      "id": "P10",
      "title": "targeted_revisions_atomic_versions",
      "requires": [
        "P02",
        "P07",
        "P09"
      ],
      "status": "NOT_STARTED",
      "commits": [],
      "evidence": [],
      "blockers": []
    },
    {
      "id": "P11",
      "title": "studio_graph_timeline_ui",
      "requires": [
        "P03",
        "P10"
      ],
      "status": "NOT_STARTED",
      "commits": [],
      "evidence": [],
      "blockers": []
    },
    {
      "id": "P12",
      "title": "history_release_delivery_legacy",
      "requires": [
        "P10",
        "P11"
      ],
      "status": "NOT_STARTED",
      "commits": [],
      "evidence": [],
      "blockers": []
    },
    {
      "id": "P13",
      "title": "regression_robustness_runbooks",
      "requires": [
        "P12"
      ],
      "status": "NOT_STARTED",
      "commits": [],
      "evidence": [],
      "blockers": []
    },
    {
      "id": "P14",
      "title": "live_smoke_rollout_handoff",
      "requires": [
        "P13"
      ],
      "status": "NOT_STARTED",
      "commits": [],
      "evidence": [],
      "blockers": []
    }
  ],
  "open_blockers": [
    "P14 must run an authorized paid v2/v3 Generate-to-bound-download smoke; C1 deliberately performed no paid generation and does not claim production smoke."
  ],
  "design_decisions": [
    "D-C1-01: Missing editing_engine remains legacy; only an explicit valid shorts_v2 marker can enter the new runtime, and malformed explicit markers fail closed.",
    "D-C1-02: Shorts V2 owns an isolated DAG/revision namespace and imports no legacy Motion Director runtime modules.",
    "D-C1-03: Current ElevenLabs v3 Stability slider values 0/0.5/1 are adapted as categorical Creative/Natural/Robust; arbitrary v2 numeric settings stay inactive for v3.",
    "D-C1-04: Pre-existing enabled downloads never acknowledge a new submit; consumption requires one new bound result identity and a fresh file inside its dedicated attempt directory.",
    "D-C1-05: Ordak already provides sufficient authenticated CDP primitives, so its pinned submodule was not modified.",
    "D-C2-01: Hook selection uses explicit independent hard gates before editorial scores; deterministic score/hook-id ordering prevents input order and a high score from rescuing an untruthful, ungrounded, unpaid or infeasible hook.",
    "D-C2-02: Character behavior overrides are scoped to shorts_v2 and retain the frozen visual identity contract; available Mark/Liam bindings are recorded as documented_not_calibrated rather than fabricated character calibration.",
    "D-C2-03: Evidence provenance accepts honest retrieved sources, source notes or conservative background, but central claims cannot pass on unverified or background-only support."
  ],
  "test_evidence": [
    "Targeted C1: 69 passed, exit 0, /tmp/qstation-v2-c1-final-targeted.log",
    "Full Python post-change: 818 passed, 19 failed, 1 skipped, exit 1, /tmp/qstation-v2-c1-final-pytest.log and /tmp/qstation-v2-c1-final-pytest.xml; the same 19 baseline failures remain and no new failure was introduced",
    "UI unit tests: 15 passed, exit 0, /tmp/qstation-v2-c1-ui-test.log",
    "UI production build: exit 0, /tmp/qstation-v2-c1-ui-build.log",
    "Python compileall and git diff --check: exit 0",
    "P04 targeted provider-free: 50 passed, exit 0, /tmp/qstation-v2-c2-p04-targeted.log",
    "P04 full Python regression: 827 passed, 19 failed, 1 skipped, exit 1, /tmp/qstation-v2-c2-p04-full.log and /tmp/qstation-v2-c2-p04-full.xml; exact same pre-existing baseline failures and 9 additional passing tests"
  ],
  "uncommitted_work": [
    "PROTECTED PRE-EXISTING: videos/045_what_if_a_human_grew_to_the_size_of_an_elephant/launch/LAUNCH_REQUEST.json",
    "PROTECTED PRE-EXISTING: videos/045_what_if_a_human_grew_to_the_size_of_an_elephant/pipeline/FINALIZATION_RUNTIME_STATE.json",
    "PROTECTED PRE-EXISTING: untracked publish/youtube_short packages for videos 042, 043 and 045"
  ],
  "unpushed_commits": [],
  "running_processes_or_provider_jobs": []
}
```
<!-- EXECUTION_LEDGER_END -->

### 29.2. Session Log — append-only execution summary

Execution entries are append-only. Template for later sessions:

```text
Session ID:
Started/ended at:
Actual branch and HEAD:
Phase(s):
Requirements addressed:
Files changed:
Decisions and reasons:
Commands/tests:
Results and evidence paths:
Commits / push state:
Remaining work:
Blockers:
Running jobs/processes reconciled:
Next action (exact):
```

```text
Session ID: C1-2026-09-20-01
Started/ended at: 2026-09-20T13:48:18+04:00 / 2026-09-20T14:15:43+04:00
Actual branch and tested implementation HEAD: dev / bea5c6732c2b4cd74ba3fbc7a985358bb196f630; profile-identity metadata correction ce554cfa54371f9d2e55955c08dd1a45635e390e
Phase(s): P00 DONE; P01 DONE; P02 DONE; P03 READY_FOR_REVIEW with code_ready=true and paid live_validation_pending=true
Requirements addressed: baseline/durable memory; strict schemas/settings/canonical IDs; isolated DAG/state/artifacts/leases/dispatch; model-aware ElevenLabs v2/v3 UI, exact text and bound-result/download safety
Files changed: canonical/master/audit docs; scripts/shorts_v2/*; new runner; wrapper/graph dispatch; ElevenLabs runner; v3 profile; three new test modules
Decisions and reasons: explicit engine selection fails closed; legacy remains default; new runtime is Motion-Director-free; v3 categorical stability maps onto the observed provider slider; stale downloads cannot prove submission
Commands/tests: compileall; 69-test targeted suite; full Python suite; UI tests/build; git diff --check; authenticated non-generating live v2/v3 capability and control probes
Results and evidence paths: targeted 69 passed; full 818 passed/19 failed/1 skipped with the same 19 baseline failures; UI 15 passed and build passed; logs under /tmp/qstation-v2-c1-*
Commits / push state: 57aa33a P00, bf73ad4 P01, 95a6183 P02, bea5c67 and ce554cf P03, 448fecc initial handoff; pushed with the final C1 ledger handoff to origin/dev
Remaining work: P04-P14; P14 paid end-to-end v2/v3 Generate/result/download smoke; resolve the unrelated legacy 19-failure baseline in its owning scope
Blockers: no blocker to C2; paid provider smoke intentionally deferred to P14 and production_smoke_passed remains false
Running jobs/processes reconciled: no provider generation or background job started; Chrome remains running by pre-existing service ownership; ElevenLabs UI restored to Eleven v3 and Liam
Next action (exact): C2 reads this ledger, protects the listed dirty video outputs, implements P04-P07 only, starts with P04 profiles/Hook Packages/evidence provenance/fixtures, and stops before P08
```

```text
Session ID: C2-2026-09-20-01
Started/ended at: 2026-09-20 (continued from the reconciled C2 handoff) / 2026-09-20T15:09:15+04:00
Actual branch and tested implementation HEAD: dev / 16d5c98aea8540c0bc7f8cc9db230469c5105d01
Phase(s): P04 DONE; C2_CREATIVE remains active at P05
Requirements addressed: evidence/source provenance; four versioned character baseline/burst profiles; six semantically distinct Hook Packages; hard-gate independent review and deterministic top-two tournament; model feasibility; story/payoff; natural canonical script; separate CTA; semantic history and A/B ancestry
Files changed: scripts/shorts_v2/creative.py, creative_profiles.json, artifacts.py, registry.py and __init__.py; tests/test_shorts_v2_creative.py and test_shorts_v2_orchestration.py
Decisions and reasons: gate hooks before scoring so an irrelevant scream cannot win; keep new behavior Shorts-only and fixed identity unchanged; label current real voice bindings documented_not_calibrated; refuse central claims supported only by unverified/background evidence
Commands/tests: targeted P04/contracts/orchestration/history pytest; full Python suite with JUnit; compileall; git diff --check
Results and evidence paths: targeted 50 passed, exit 0, /tmp/qstation-v2-c2-p04-targeted.log; full 827 passed/19 failed/1 skipped, exit 1, /tmp/qstation-v2-c2-p04-full.log and /tmp/qstation-v2-c2-p04-full.xml; all 19 failures match the C1 baseline categories and no new failure appeared
Commits / push state: 16d5c98 P04 implementation plus this ledger handoff; pushed to origin/dev at session close
Remaining work: P05-P14; this C2 slot still owns P05-P07 and must stop before P08
Blockers: no P05 blocker; paid ElevenLabs Generate-to-bound-download smoke remains deferred to P14
Running jobs/processes reconciled: full pytest completed; no provider generation, render, or background process was started
Next action (exact): implement P05 typed performance AST and separate expressive_v3/optimized_v2 compilers in scripts/shorts_v2, anchored to P04 SCRIPT_CORE units and actual P03 capability data; start by adding failing T29-T31 fixtures
```

### 29.3. Decision Log

`D-C1-01 | 2026-09-20 | P01/P02 | Old episodes have no engine marker | infer from old fields vs require explicit selection | missing marker is legacy; explicit malformed shorts_v2 fails closed | no accidental migration or silent fallback | targeted dispatch/contracts tests`

`D-C1-02 | 2026-09-20 | P02 | Existing Q Station graph imports Motion Director | condition old graph vs isolated registry | independent scripts/shorts_v2 registry and revision namespace | later phases can replace nodes without coupling legacy | DAG/import/plan-only tests`

`D-C1-03 | 2026-09-20 | P03 | Current v3 UI presents Stability as a numeric slider although v3 semantics are categorical | send arbitrary numeric v2 value vs semantic adapter | map Creative/Natural/Robust to observed 0/0.5/1; keep other v2 controls inactive | model semantics remain explicit under UI drift | adapter tests plus authenticated live control probe`

`D-C1-04 | 2026-09-20 | P03 | Existing Download latest can predate the current request | accept any enabled download vs bind a new result | baseline result identities before submit and require exactly one new identity plus attempt-local fresh file | ambiguous/stale output fails loudly | result/download ownership tests`

`D-C1-05 | 2026-09-20 | P03 | Determine whether Ordak must change | modify submodule vs use pinned primitives | keep Ordak pinned and implement model semantics in main repo | no unreachable gitlink or service deployment needed | live Chrome/CDP probes`

`D-C2-01 | 2026-09-20 | P04/R05/R20 | High editorial scores could mask a failed truth/topic/payoff gate | select by score vs gate then score | require all explicit gates before deterministic total-score/hook-id tournament | irrelevant shock and unpaid promises remain rejected regardless of score | T24/T25 fixtures`

`D-C2-02 | 2026-09-20 | P04/R07/R08/R09 | Creative behavior must expand without mutating identity or inventing calibrated voices | merge legacy behavior blindly vs versioned Shorts-only layer | preserve fixed identity and scope baseline/burst override to shorts_v2; bind observed Mark/Liam profiles as documented_not_calibrated | legacy remains frozen and P05 gets honest model-specific input | T27/T28 fixtures`

`D-C2-03 | 2026-09-20 | P04/R20/R35 | Retrieval can be absent or limited | fabricate citation/PASS vs honest source tiers | permit retrieved/source_note/conservative_background provenance but reject unverified or background-only central support | unsupported central science must be redesigned or removed | T26 fixtures`

For every later meaningful change:

`decision_id | date | requirement | observed problem | options | chosen approach | consequences | tests`

Recording something here does not legitimize deleting a requirement, reducing scope, or hiding a workaround; changes must stay within section 28.5.

### 29.4. Blocker Log

`B-C1-01 | P14 (not blocking P03 code readiness or C2) | authorized paid ElevenLabs generation smoke | authenticated v2/v3 settings/editor probes pass, but C1 did not click Generate or consume credits | verified login, exact model/voice retention, model-specific controls, editor types and trusted slider interaction | all provider-free P00-P03 work completed | during P14 run one authorized v2 and one v3 request through new-result binding, attempt-local download and ffprobe receipt`

`B-C1-02 | baseline/legacy owner (not a Shorts V2 blocker) | clean pre-existing Python suite | baseline and post-change runs both contain the same 19 failures | captured baseline before edits and compared exact post-change count/categories | targeted C1, UI and build suites are green | repair chatgpt_fallback_auto schema drift, legacy gemini flag, resume fingerprints and stale test double in their owning scope`

`blocker_id | phase | capability/access missing | evidence | attempted checks | independent work continued | exact unblock action`

### 29.5. Test Evidence Log

For every run:

`test_id(s) | level | command | date | commit | exit_code | passed/failed/skipped | log_path | limitation`

`T01,T02,T70 | baseline | .venv/bin/python -m compileall -q scripts; .venv/bin/python -m pytest -q -rs tests --junitxml=/tmp/qstation-v2-c1-baseline-pytest.xml | 2026-09-20 | e4cd11c | compile 0 / pytest 1 | 782 passed, 19 failed, 1 skipped | /tmp/qstation-v2-c1-baseline-compile.log; /tmp/qstation-v2-c1-baseline-pytest.log | pre-change baseline`

`T03-T23,T51-T54 | provider-free targeted | .venv/bin/python -m pytest -q tests/test_shorts_v2_contracts.py tests/test_shorts_v2_orchestration.py tests/test_elevenlabs_v2_v3_adapter.py tests/test_elevenlabs_output_format.py tests/test_voiceover_input_sync.py tests/test_run_graph.py tests/test_q_station_wrapper_artifacts.py | 2026-09-20 | bea5c67 | 0 | 69 passed | /tmp/qstation-v2-c1-final-targeted.log | DOM/result behavior is fixture-level except separately recorded live probe`

`T68-partial | authenticated live non-generating | select/probe/read back Eleven Multilingual v2 and Eleven v3 controls and editors; exercise trusted Stability/Style minimum controls; restore v3/Liam | 2026-09-20 | bea5c67 | 0 | v2 and v3 capability/control PASS | session output summarized in P03 evidence | no Generate, result binding or download; those remain P14`

`T70 | full Python regression | .venv/bin/python -m pytest -q -rs tests --junitxml=/tmp/qstation-v2-c1-final-pytest.xml | 2026-09-20 | bea5c67 | 1 | 818 passed, 19 failed, 1 skipped | /tmp/qstation-v2-c1-final-pytest.log | exact same 19 pre-existing baseline failures; 36 additional passing tests and no new failure`

`T70 | UI unit/build | npm --prefix control_panel/ui test; npm --prefix control_panel/ui run build | 2026-09-20 | bea5c67 | 0/0 | 15 passed; Vite production build passed | /tmp/qstation-v2-c1-ui-test.log; /tmp/qstation-v2-c1-ui-build.log | no new UI surface is required until P11`

`T24-T28,T65 | provider-free targeted | .venv/bin/python -m pytest -q tests/test_shorts_v2_creative.py tests/test_shorts_v2_contracts.py tests/test_shorts_v2_orchestration.py tests/test_episode_history.py | 2026-09-20 | 16d5c98 | 0 | 50 passed | /tmp/qstation-v2-c2-p04-targeted.log | validates contracts/prompts and accept/reject fixtures; no provider content generation`

`T70 | full Python regression | .venv/bin/python -m pytest -q -rs tests --junitxml=/tmp/qstation-v2-c2-p04-full.xml | 2026-09-20 | 16d5c98 | 1 | 827 passed, 19 failed, 1 skipped | /tmp/qstation-v2-c2-p04-full.log; /tmp/qstation-v2-c2-p04-full.xml | exact same 19 pre-existing baseline failures; 9 additional passing tests and no new failure`

### 29.6. Handoff to the next session

First reconstruct current state from the ledger and Git. The latest Session Log must not contain vague wording such as “almost finished.” Appropriate example:

```text
Next phase: P06
Next operation: implement stable canonical-word mapping in <actual module>.
Existing contract: <actual schema path/version>.
Last passing tests: <actual commands + logs>.
Do not redo: <completed tasks and commits>.
Open blocker: <real missing environment capability, or none verified>.
```

Current exact handoff:

```text
Next phase: P05
Next operation: implement typed performance AST, stable word anchors and separate expressive_v3/optimized_v2 compilers under scripts/shorts_v2, using P04 SCRIPT_CORE and character performance artifacts.
Existing contract: scripts/shorts_v2/contracts.py schema_version=1/design_version=2.2; scripts/shorts_v2/registry.py is the shared DAG authority.
Last passing tests: P04 targeted 50 passed (/tmp/qstation-v2-c2-p04-targeted.log); full suite 827 passed/19 unchanged baseline failures/1 skipped (/tmp/qstation-v2-c2-p04-full.log).
Do not redo: P00-P04; P03 adapter and P04 creative contracts/profiles/tournament/script validators are committed inputs to P05.
Open blocker: paid Generate-to-bound-download smoke is explicitly deferred to P14 and does not block P04-P13.
Selected chat plan: FOUR_CHAT
Current chat slot and assigned phase range: C2_CREATIVE / P04-P07
Range gate reached: NO; P04 is DONE but P05-P07 remain in C2.
Next chat slot: unchanged C2_CREATIVE
Reason this is a safe stopping point: P04 is a coherent tested commit with explicit artifact ownership; P05 can consume frozen canonical script/profile contracts without revisiting creative selection.
```

The handoff must additionally state:

```text
Selected chat plan: FOUR_CHAT or THREE_CHAT
Current chat slot and assigned phase range:
Range gate reached: YES/NO
Next chat slot (only when gate reached):
Reason this is a safe stopping point:
```

`current_chat_slot` is advanced only after the range gate defined in section 0.5. A new chat always trusts reconciled Git evidence first, then this field; a chat number written only in the user's message is not sufficient to skip unfinished work.

---

## 30. Sources, review provenance, and claim boundaries

This document is based on the V2/V2.1 design content provided in the conversation, code read from the repository, and the official sources below. Code/docs may advance; re-check the actual state in P00/P03.

### 30.1. Internal GitHub sources

The relative links below are based on commit `e4cd11c5ad21d6e1fda36af2e157184aecfb2738`; do not rely on latest main.

- **G0 — repository snapshot / provider locks:**
  `https://github.com/M2002HR/YT_Video_Generation_Pipeline/tree/e4cd11c5ad21d6e1fda36af2e157184aecfb2738`
  `projects/q_station/PROJECT.json`
- **G1 — voice web automation and settings/receipt:**
  `scripts/run_elevenlabs_voiceover.py`, `voice_profiles/elevenlabs_mark_default.json`
- **G2 — runner and one-to-one contract:**
  `scripts/run_q_station_pipeline.py`, `projects/q_station/prompts/pipeline/05_visual_beat_planner.md`
- **G3 — timing and rendering:**
  `scripts/align_beats.py`, `build_timeline.py`, `render_video.py`, `run_completion_pipeline.py`
- **G4 — Studio/graph/revision:**
  `scripts/panel_contract.py`, `video_control_panel.py`, `run_graph.py`, `control_panel/ui/src/`
- **G5 — character and gateway:**
  `projects/q_station/characters/`, `docs/CHARACTER_GATEWAYS.md`, `scripts/character_runtime.py`
- **G6 — history and actual timeline example:**
  `scripts/episode_history.py`, `projects/q_station/VIDEOS.json`, `videos/045_what_if_a_human_grew_to_the_size_of_an_elephant/timeline/TIMELINE.json`
- **G7 — submodule contract:**
  `.gitmodules`, `services/ordak`; observed ref `6456e9957e6b44eef9a99e60ab372eb258077af8`
- **G8 — Ordak reference upload:**
  `https://github.com/AliBalash/ordak/blob/6456e9957e6b44eef9a99e60ab372eb258077af8/app/uploads.py`
- **G9 — CI and frontend:**
  `.github/workflows/dev-validation.yml`, `control_panel/ui/package.json`

Current voice-control code around baseline lines 744–830 applies/verifies generic settings; submit/download guards must be re-audited in P03 and made safe against previous-request results. These line numbers are baseline locators only and must not be assumed valid after code changes.

### 30.2. Official external sources — reviewed September 20, 2026

- **E1 — ElevenLabs Text-to-Speech product guide, controls and model limitations:**
  `https://elevenlabs.io/docs/eleven-creative/playground/text-to-speech`
- **E2 — model-specific pause behavior:**
  `https://elevenlabs.io/docs/help-center/product/core-capabilities/text-to-speech/how-can-i-add-pauses`
- **E3 — v3 prompting and best practices, voice/tag dependence:**
  `https://elevenlabs.io/docs/overview/capabilities/text-to-speech/best-practices`
- **E4 — technical pause/phoneme API information for capability comparison, not authorization to change transport:**
  `https://elevenlabs.io/docs/help-center/technical/do-pauses-and-ssml-phoneme-tags-work-with-the-api`
- **F1 — FFmpeg filters, including xfade and normalization:**
  `https://ffmpeg.org/ffmpeg-filters.html`
- **O1 — project instructions in AGENTS.md:**
  `https://developers.openai.com/codex/guides/agents-md`
  During review this address redirected to `https://learn.chatgpt.com/docs/agent-configuration/agents-md`.
- **Y1 — YouTube performance-metric definitions:**
  `https://support.google.com/youtube/answer/12220281?hl=en`
- **Y2 — retention markers and dip analysis:**
  `https://support.google.com/youtube/answer/9314415?hl=en`

Generic provider statements may differ from model-specific sections or the active UI; adapter capability and real tests must record uncertainty. A documented feature is not proof that Ordak currently implements the corresponding UI control.

### 30.3. Design hypotheses, not sourced guarantees

Six candidates, the proposed shot-duration ranges, 30–60+ images, hook intensity, and the v2 starting presets are initial product design decisions. No source in this document guarantees that these numbers will improve retention.

All JSON/text examples are illustrative. No “calibrated” tag, downloaded voice, observed bbox, or production test has been fabricated in them.

---

## 31. Start and continuation text for Codex

Use the four-chat route unless the user explicitly chooses the compact three-chat route before P00 begins. Replace `<CHAT_SLOT>` and `<N>` in the launcher text. The slot is a scope boundary; repository/ledger evidence still determines the actual first unfinished phase.

### 31.1. First run

```text
Read the entire QStation_Shorts_V2_2_Codex_Master_Plan_EN.md file and use its contents as the execution directive for the project.
Keep the canonical copy at docs/QSTATION_SHORTS_V2_2_CODEX_MASTER.md; if a version containing execution progress already exists, do not overwrite it.
First inspect applicable AGENTS.md files, branch, HEAD, working tree, and submodules.
All main-repository changes must be made on dev; do not modify main or existing generated data.
Start with P00 and do not stop at planning: progressively implement code, tests, UI, revision behavior, and evidence.
v3 and v2 are two first-class voice paths under the same new editing engine; visual-content QC defaults off and normal production must not require manual approvals in the middle.
Do not use the old Motion Director for the new path.
After every batch and before ending a session, update the EXECUTION_LEDGER and Session Log.
Whenever the real server/browser environment is unavailable, do not claim tests were executed; record a precise blocker and continue independent work.
Use the FOUR_CHAT route from section 0.5 unless I explicitly selected THREE_CHAT. You are chat slot C1. Execute only that slot's assigned phase range. When its range gate is reached, prepare the exact handoff, advance current_chat_slot, and stop before the next range.
```

### 31.2. Continue in a later chat

```text
Continue Q Station execution from docs/QSTATION_SHORTS_V2_2_CODEX_MASTER.md.
First read the EXECUTION_LEDGER, latest Session Log, applicable AGENTS.md files, and git status/HEAD and reconcile them.
Do not redo completed work; execute the first incomplete phase without a blocker.
All main-repository changes remain on dev. Preserve the v2/v3 rules, QC-off default, Motion independence, and dependency-aware Revise behavior.
At the end, record real test results, commits, blockers, and an exact next_action in the same file.
Read execution_chat_plan and act as chat slot <CHAT_SLOT> of <N>. If that label conflicts with the reconciled ledger, resume the ledger's unfinished slot instead of skipping work. Execute only the current slot's assigned range; advance the slot only after its range gate, then stop before the next range.
```

### 31.3. Copy/paste launchers for the recommended four-chat route

For chat 1, paste section 31.1 exactly. For chats 2–4 use section 31.2 and replace the placeholders as follows:

| New chat | `<CHAT_SLOT>` | `<N>` | Expected range if prior gate was reached |
|---|---|---:|---|
| Chat 2 | `C2_CREATIVE` | `4` | `P04–P07` |
| Chat 3 | `C3_EDIT_AND_REVISE` | `4` | `P08–P10` |
| Chat 4 | `C4_PRODUCT_AND_ROLLOUT` | `4` | `P11–P14` |

The user may use this shorter launcher after the canonical file exists:

```text
Continue the Q Station V2.2 implementation from docs/QSTATION_SHORTS_V2_2_CODEX_MASTER.md as <CHAT_SLOT> of 4. Read section 0, the reconciled ledger and latest logs first. Resume the ledger's first unfinished phase, deliver everything required for the current slot, update all evidence and handoff fields, and stop at this slot's hard boundary. Do not start the next slot.
```

### 31.4. Copy/paste launchers for the compact three-chat route

Before starting P00, change `execution_chat_plan.mode` to `THREE_CHAT`, set `selection_status` to `CONFIRMED`, and set `current_chat_slot` to `C1_FOUNDATION_AND_CREATIVE`. The machine-readable ranges already exist under `execution_chat_plan.routes.THREE_CHAT`. Then use:

```text
Read the entire QStation_Shorts_V2_2_Codex_Master_Plan_EN.md and execute it as C1_FOUNDATION_AND_CREATIVE of 3 using the THREE_CHAT route. Initialize/reconcile the canonical copy and ledger, execute P00–P04 only, meet every phase gate with real evidence, prepare the next-chat handoff, advance the slot only after P04 is accepted, and stop before P05.
```

```text
Continue from docs/QSTATION_SHORTS_V2_2_CODEX_MASTER.md as C2_MEDIA_ENGINE of 3. Reconcile Git and the ledger, resume any unfinished predecessor, otherwise execute P05–P09 only. Record real evidence and the exact handoff, advance the slot only after P09 is accepted, and stop before P10.
```

```text
Continue from docs/QSTATION_SHORTS_V2_2_CODEX_MASTER.md as C3_REVISION_PRODUCT_ROLLOUT of 3. Reconcile Git and the ledger, resume any unfinished predecessor, then complete P10–P14 within their real acceptance limits. Produce the section 28.4 final report; never claim live or production success without evidence.
```

### 31.5. Final instruction

**Turn this document into a real, testable implementation.** Success means the product works correctly from Studio to output and from human feedback to Revise—not that the number of files, agents, or stages has increased.

<!-- END_QSTATION_CODEX_MASTER_V2_2 -->
