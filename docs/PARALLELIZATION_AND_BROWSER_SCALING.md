# Parallelization and Browser Scaling Plan

## Decision

The first production parallelization should use **two isolated Chrome profiles and
two Ordak instances**, with one browser job at a time per instance.  A central,
resource-aware scheduler should dispatch ready DAG nodes to those lanes.

Do not begin by running several image/video jobs in tabs of one Chrome profile.
The current Ordak manager deliberately has a single queue and global browser lock,
and Chrome download routing is browser-wide.  Concurrent downloads in one browser
can therefore change each other's destination and break artifact attribution.

The current host has 2 vCPUs, 7.6 GiB RAM, no swap, and two Chrome instances already
consume roughly 2.2 GiB RSS together.  Start with two profiles; do not add a third
browser worker until memory/CPU measurements under real load justify it.

## Evidence in the current codebase

- `scripts/run_graph.py` owns the canonical Question Harvest DAG, but pipeline
  executors still call stages manually and sequentially.
- `services/ordak/app/job_manager.py` has one `asyncio.Queue`, one consumer, and a
  `browser_lock` around a complete browser job.  Submitting jobs concurrently to a
  single instance only grows that queue.
- `services/ordak/app/automation/existing_chrome.py:download_to` uses
  `Browser.setDownloadBehavior`.  That is browser-scoped, so it cannot safely route
  simultaneous downloads from independent tabs to separate job directories.
- The body-image chain intentionally passes Beat N-1 as `previous_beat` to Beat N.
  A rejected output must not become a continuity reference; this chain therefore
  remains serial inside an episode under the current visual-consistency contract.
- `QHState` writes an atomic JSON replacement, but it is not a multi-process state
  store.  A concurrent scheduler needs a single writer or a transactional store.

## What can run in parallel

| Work | Prerequisites | Parallelization policy |
| --- | --- | --- |
| Script draft | topic/brief | Serial root |
| Retention edit | script draft | Serial |
| Character resolution | retention | Parallel with world-style direction and voiceover |
| World-style direction | retention | Parallel with character resolution and voiceover |
| Voiceover | retention | Start immediately; do not wait for images |
| Episode direction | character resolution | Parallel with style-anchor/keyframe work |
| World-style anchor | world-style direction | Gemini lane |
| World-keyframe prompt | retention + world-style direction | ChatGPT lane |
| World keyframe | prompt + style anchor | Gemini lane |
| Book-cover direction | topic | May start early |
| Book cover | direction + style anchor | Gemini lane |
| Flow prompt A | retention + episode + character | Independent from body images |
| Flow prompt B | retention + style + keyframe prompt | Independent from body images |
| Flow clips | their prompts and references | Run concurrently with body images on a separate lane/account |
| Beat prompts | visual plan and static role information | Batch after visual plan, with bounded ChatGPT concurrency |
| Beat images | visual plan + anchors + prior accepted beat | Serial within an episode |
| Alignment | voiceover + retention + visual plan | Parallel with images and Flow |
| Background music | voiceover | Parallel with alignment |
| Transition decisions | all body images | One task per boundary; bounded parallel ChatGPT work |
| Motion direction + SFX plan | timeline | Independent parallel branches |
| Git publication + Telegram compression | polished QC | Independent, but Git remains globally serialized |

## Measured bottleneck

The first full run of Video 026 recorded:

- 14 Beat-image jobs: about 30.2 minutes total.
- `body_images`, including prompt/QC overhead: about 38.6 minutes.
- `transition_direction`: about 14.4 minutes.
- Both Flow clips together: about 3.9 minutes.
- Whole recorded visual phase: about 71 minutes.

The realistic first target for one episode is a 20–35% reduction, not a 2x latency
reduction: the accepted Beat-image chain is still the critical path.  Two independent
Gemini lanes can improve multi-episode throughput much more substantially.

## Recommended worker topology

```text
                  ┌─────────────────────────────────────┐
                  │ Parent DAG scheduler                 │
                  │ dependencies + durable task state    │
                  │ account cooldowns + resource leases  │
                  └──────────────┬──────────────┬────────┘
                                 │              │
                 ┌───────────────▼───┐  ┌──────▼────────────────┐
                 │ Chrome / Ordak A  │  │ Chrome / Ordak B      │
                 │ Flow-preferred    │  │ Gemini-image-preferred│
                 │ one active job    │  │ one active job        │
                 └───────────────────┘  └───────────────────────┘
```

Each instance must have an independent Chrome user-data directory, DevTools port,
Ordak API port, job storage, and verified provider login.  Both lanes may have
ChatGPT capability, but the scheduler must route by actual readiness rather than
assuming a provider is authenticated.

Use a registry entry per browser account/profile:

```json
{
  "id": "image-a",
  "base_url": "http://127.0.0.1:8001",
  "capabilities": ["gemini", "chatgpt"],
  "google_account": "account-a",
  "chatgpt_account": "account-a",
  "max_concurrency": 1,
  "cooldown_until": null
}
```

Do not use several profiles of the same Google account as quota capacity.  They are
separate browser sessions, not independent account quotas.

## Scheduler contract

Each task needs:

- immutable input fingerprint and artifact output path;
- dependencies whose artifacts are verified, not merely present;
- required provider and optional model capability;
- one or more resource leases (`gemini account`, `flow account`, `chatgpt account`,
  `render_cpu`, `repo_writer`);
- `queued`, `leased`, `submitted`, `reconciling`, `completed`, `retryable`,
  `paused_quota`, `manual_verification`, and terminal failure states;
- submission marker before sending a paid request, followed by reconciliation before
  any retry/failover.

No task may retain a browser/account lease while it waits for another provider.  For
example, Gemini generation must release its lane before its ChatGPT visual review is
scheduled.  This prevents a Gemini-to-ChatGPT QC task and a ChatGPT-to-Gemini fallback
from deadlocking each other.

ChatGPT fallback is a new routed task, never an inline call that inherits the failed
task's browser lease.  Queue priorities should favour a task that unblocks the critical
path while preventing fallback work from starving paid image generation.

## Gemini limits, quality, and account routing

Google documents that Gemini Apps has variable compute-based limits, notifies users as
they approach/reach a limit, and can continue a conversation with Flash-Lite after a
model limit.  Google has also documented Nano Banana Pro reverting to the original Nano
Banana after a quota is exhausted in applicable product tiers.  A visible quality drop
alone is not evidence of a rate limit; model randomness, reference overload, or a UI
state change can look similar.

Every paid image job must record before and after generation:

- requested model and selected UI model label;
- visible quota/limit banner or toast, if any;
- result-time model evidence and response attribution;
- account/profile ID, reset/cooldown time, and receipt fingerprint.

If the actual model differs from the requested model, reject the output even if it looks
good.  Put that account in cooldown and require a known reset or manual check.  Do not
infer a model from image dimensions, hashes, or an aesthetic quality score.

Use a health-aware, weighted pool—not blind round robin.  Prefer a sticky account for
one Beat chain.  Fail over only before submission or after the original account has
reconciled an uncertain submission, otherwise duplicate paid generations are possible.
Multiple legitimate, independently provisioned accounts may be represented as capacity
lanes subject to provider terms; the system must not be designed as a quota-evasion
mechanism.

Relevant official references:

- [Gemini Apps limits and upgrades](https://support.google.com/gemini/answer/16275805?hl=en)
- [Nano Banana Pro availability and fallback behaviour](https://blog.google/products-and-platforms/products/gemini/where-to-use-nano-banana-pro/)
- [Google Terms of Service](https://policies.google.com/terms?hl=en-US)

## Delivery phases

1. Instrument queue wait, provider duration, account/profile, submit/reconcile outcome,
   actual model evidence, and resource contention.  Keep execution serial.
2. Move Beat-prompt batch generation, Flow, voiceover, music, alignment, and transition
   decisions onto the DAG scheduler while preserving one browser job per profile.
3. Register the two existing Ordak instances and run one Flow-preferred lane plus one
   Gemini-image-preferred lane.  Verify artifact attribution and recovery with real jobs.
4. Add durable scheduler state (SQLite or a single-writer event log), account cooldowns,
   and cross-episode locks for `VIDEOS.json`, style catalogs, shared book assets, Git, and
   Telegram rate limiting.
5. Only after download routing, tab ownership, and recovery are proven safe, evaluate
   limited text-only per-tab concurrency inside a profile.  Image/video concurrency in
   one Chrome browser remains disabled unless browser-scoped download state is removed.

## Acceptance tests

- two concurrent jobs on two Ordak instances never exchange downloads or receipts;
- Flow download and Gemini download coexist without destination cross-talk;
- restart after submission reconciles rather than blindly resubmitting;
- concurrent ChatGPT fallback and Gemini QC cannot deadlock;
- a quota notification/model mismatch creates a cooldown and never accepts the output;
- two parallel episodes preserve project history/catalog updates and serialize Git writes;
- browser load plus render remains stable on the 2-vCPU host;
- one E2E episode and then two simultaneous E2E episodes complete with verified receipts.
