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
