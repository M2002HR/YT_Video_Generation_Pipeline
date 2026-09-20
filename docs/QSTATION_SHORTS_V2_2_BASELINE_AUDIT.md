# Q Station Shorts V2.2 baseline audit

Audit ID: `C1-2026-09-20-01`
Observed at: `2026-09-20T13:48:18+04:00`
Repository: `/opt/YT_Video_Generation_Pipeline`
Branch: `dev`
HEAD: `e4cd11c5ad21d6e1fda36af2e157184aecfb2738` (`origin/dev` at audit time)

## Safety and repository state

- No applicable `AGENTS.md` exists in this repository tree.
- Main-repository work is on `dev`; `main` was not checked out or changed.
- `services/ordak` is pinned at `6456e9957e6b44eef9a99e60ab372eb258077af8` on its configured `yt-video-pipeline` branch.
- `services/ajil_uag` is pinned at `14d97f4a0e8104ae55299f82679cdf1b4db25430`.
- Pre-existing user/runtime changes were observed in video 045 launch/finalization state and YouTube release-package directories for videos 042, 043, and 045. They are outside this implementation scope and must not be edited, staged, or deleted.
- The root directive was untracked when execution began. Its canonical execution copy is now `docs/QSTATION_SHORTS_V2_2_CODEX_MASTER.md`; subsequent ledger updates belong there.

## Runtime and commands

| Capability | Observed value |
|---|---|
| Python | `.venv/bin/python`, Python 3.12.3 |
| pytest | 9.1.1 in `.venv` |
| Node | 22.23.2 |
| npm | 10.9.8 |
| FFmpeg | 6.1.1-3ubuntu5 |
| Ordak | health/database ready on `127.0.0.1:8000`; Chrome running; ChatGPT session ready |
| ElevenLabs browser session | not evaluated by the baseline command; P03 owns the non-generating capability probe |

Canonical provider-free validation commands:

```bash
.venv/bin/python -m compileall -q scripts
.venv/bin/python -m pytest -q -rs tests --junitxml=<path>
npm --prefix control_panel/ui test
npm --prefix control_panel/ui run build
git diff --check
```

CI installs Python 3.11, Node 22, FFmpeg, `requirements.txt`, pytest, and numpy. The repository's UI test script already supplies Node's test runner; do not append incompatible test-runner arguments except the CI's supported `-- --run` invocation.

## Baseline test evidence

The baseline was captured before Shorts V2 code changes:

- compile: exit `0`; `/tmp/qstation-v2-c1-baseline-compile.log`;
- Python suite: exit `1`; `782 passed`, `19 failed`, `1 skipped`; `/tmp/qstation-v2-c1-baseline-pytest.log`; JUnit `/tmp/qstation-v2-c1-baseline-pytest.xml`;
- the skip is the explicitly opt-in Freesound live test.

The 19 baseline failures are not Shorts V2 regressions. Seventeen are concentrated in pre-existing launch/schema and resume drift: the legacy HTML field `chatgpt_fallback_auto` is absent from the React/backend schema, the wrapper no longer forwards `gemini_image_model`, several cached-image receipts no longer match current prompt/reference fingerprints, and one test double does not accept the current `chatgpt_chat` argument. These failures remain visible and must be compared against post-change results; this audit does not silently repair unrelated baseline behavior.

## Existing ownership and dependency map

| Area | Current authority | Baseline constraint / V2.2 delta |
|---|---|---|
| Launch/config | `panel_contract.py`, `video_control_panel.py`, frozen creative brief and voice profile | Existing fields mix legacy motion, image-QC and generic voice sliders. V2.2 needs independent engine, model/performance, and review axes with one normalizer. |
| Creative runner | `run_q_station_pipeline.py` | Visual plan is created before audio and enforces one numbered body beat/image per spoken unit. Keep legacy frozen; new engine needs separate contracts. |
| Wrapper | `run_full_video_pipeline_q_station_wrapper.py` | Correctly places voice before measured opening sources, but alignment still requires `VISUAL_BEATS.md`; new dispatch must not import/use old Motion Director. |
| Graph/UI | `run_graph.py`, `pipeline_stages.py`, Studio API | Current Q Station graph expands numeric beat images and contains `motion_director`; a Shorts V2 registry must be the source for its own effective DAG and conditions. |
| Voice | `run_elevenlabs_voiceover.py`, `voice_profiles/` | Authenticated web transport exists, but treats every model as the same slider UI, accepts pre-existing download state as acknowledgement, refresh-resubmits without result reconciliation, and chooses a recent shared-download file. |
| Completion/render | `run_completion_pipeline.py`, `render_video.py` | Imports and executes the legacy Motion Director/compilers. Shorts V2 dispatch must remain isolated until the independent renderer arrives in P08. |
| Revision/state | `video_control_panel.py`, `run_graph.py` | Existing cascade is numeric-beat oriented and mutates current files. P02 introduces stable revision paths, leases and provider-call evidence; atomic promotion is completed in P10. |
| Provider | main-repo adapters over Ordak Chrome/CDP | Main-repo implementation is preferred; the pinned Ordak submodule already provides semantic DOM execution and trusted input primitives, so no submodule edit is justified in C1. |

## Compatibility decisions for P01–P03

1. A run with no explicit engine marker resolves to `legacy`. Merely reading or resuming an old episode never opts it into Shorts V2.
2. Shorts V2 is selected only by an explicit normalized request. It has its own registry and runner entry point; the old Motion Director is absent from their import graph.
3. `eleven_v3` and `eleven_multilingual_v2` are canonical model identifiers. Display labels are adapter data, not identifiers. Unsupported or ambiguous models fail; there is no model/provider fallback.
4. Media review, editing observation, technical validation, and human approval are independent. Technical validation cannot be disabled for a production request. Default media review is off for every visual role.
5. P03 stays in the main repository unless the pinned Ordak primitives prove insufficient. Browser fixture evidence and live browser evidence are recorded separately.

## Phase boundary

P00 is complete when this audit, the canonical directive, reconciled ledger, environment evidence, and baseline failure counts are committed together with the first coherent implementation batch. P00 does not claim that the existing product suite is green.
