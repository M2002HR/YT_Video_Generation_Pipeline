# Plain-English upgrade verification - 2026-09-16

## Source and scope

User's starting dev commit: `bd1a2ac28d224e751c425456fa563494ebf5a01e`.
Verified implementation commit: `359af5a2dddebbff06047adfdaf37d7dfd297226`.
The implementation is a fast-forward descendant of the user's source; main is not changed.
No generated episode, subtitle/voice setting, renderer, provider or production dependency is changed.

## Executed verification

Integration run:
https://github.com/M2002HR/YT_Video_Generation_Pipeline/actions/runs/35105227856

| Check | Observed result |
| --- | --- |
| Shared-policy / prompt / graph preflight | Passed |
| Python compileall on scripts | Passed |
| Full Python suite | 598 passed, 1 skipped, 0 errors, 0 failures |
| UI tests | 15 passed, 0 failures |
| Production UI build | Passed |
| Tests did not rewrite source | Passed |
| Verified fast-forward push to dev | Passed |

The skipped test is `tests/test_freesound_live.py`: it requires RUN_FREESOUND_LIVE_TESTS=1
and a local Freesound token. No paid text, audio, image or video generation was requested.
The 57 new parameterized language tests use controlled provider responses. They test real
prompt assembly, evidence validation, correction ownership, scope/qualifier feedback, bounded
retries, receipt integrity, legacy resume and CTA isolation; they are not a measurement of
real-model language quality or scientific accuracy.

The targeted local suite also passed 156 tests. Local full-suite rendering encountered an
FFmpeg xfade/time-base incompatibility, reproduced on the untouched starting source. Renderer
code was deliberately not changed. The complete suite passed in the clean GitHub runner.

The existing read-only Dev validation workflow runs again on the documentation commit that
records this evidence, so its final head can be checked independently in Actions. Transport
payloads and temporary integration/snapshot workflows are absent from the final source tree.

## Deployment and remaining verification

Follow `docs/SPOKEN_ENGLISH_POLICY.md` and deploy dev while generation is idle. Run
`python scripts/check_opening_setup.py` from the production virtual environment, then restart
the panel processes. No new API key, package, UI toggle or subtitle/voice change is required.
Existing finished videos are not rewritten. Use explicit Revise/cascade for intentional changes.

Live browser sessions, account availability/credits, generated audio and audience comprehension
have not been verified by these tests. Check a new episode's CORE_LANGUAGE_REVIEW.json and
CTA_LANGUAGE_REVIEW.json, and evaluate first-listen comprehension on actual generated narration.
