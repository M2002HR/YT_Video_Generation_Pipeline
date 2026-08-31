# Execution timing policy

Every automated video pipeline stage must emit durable, machine-readable timing
evidence. This is a repository policy for the current Ordak/ChatGPT workflow
and all later executors (for example ElevenLabs, STT, rendering, upload and
publishing); it does not prescribe a particular provider.

For each operation record UTC start/end timestamps, elapsed seconds, video ID,
stage/beat ID, executor/job ID where applicable, retry/attempt number, input
identity and output identity. Record nested component timings whenever an
operation contains significant substeps: request creation, reference payload
read, reference upload/attachment, queue/wait, provider generation, download,
decode and QC.

Video-owned timing files live under `videos/<id>/visual_pipeline/` (or the
corresponding subsystem directory) and are **tracked in Git**. Never put
credentials, cookies, private conversation URLs, prompt secrets or raw tokens
in timing records. Generated media may remain ignored; the metadata, checksums,
paths, durations and reports must remain commit-eligible.

The visual pipeline writes `EXECUTION_TIMINGS.json` on every state save. Its
event list is append-only for a run and its aggregate totals are recalculated
from the events. Future pipeline components must follow the same schema or add
a documented schema version rather than replacing historical measurements.

`scripts/run_completion_pipeline.py` applies this policy to the post-production
path. It writes `pipeline/FINALIZATION_RUNTIME_STATE.json` after every stage:
timeline build, baseline render, baseline QC, audio polish, polished QC and
Telegram publishing. The default completion path forcibly disables SFX; use
`--allow-sfx` only for a video explicitly designed with approved SFX events.

```bash
python scripts/run_completion_pipeline.py videos/<id> --publish
```

The publish command requires a passing polished QC report and persists a
deduplicating receipt at `publish/TELEGRAM_PUBLISH_STATE.json`, so reruns never
silently send the same artifact twice.

## Final Git publication

After Telegram publishing succeeds, the full pipeline automatically commits
and pushes only the selected video's non-ignored durable artifacts. It never
stages unrelated workspace changes or credentials. `pipeline/GIT_PUBLISH_STATE.json`
records the branch, commits and exact elapsed time; the final full-pipeline
state records this as `git_commit_push`. Ignored media remains excluded by the
repository policy, while reports, prompts, timing evidence, QC and publish
receipts are committed.

## Human progress notifications

When `YT_PIPELINE_TELEGRAM_NOTIFICATIONS_ENABLED=true`, pipeline execution
also sends concise English-only Telegram progress messages through the
configured Telethon user session. Notify completion of each durable stage,
every accepted image and all actionable warnings or failures. A completed
multi-image stage must report both its total elapsed time and average accepted
image duration. Notifications are best-effort only: a Telegram outage must be
recorded locally as a warning and must never interrupt artifact production.
