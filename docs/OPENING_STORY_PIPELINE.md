# Topic-first openings (policy v2)

## What changes for new runs

Every new Q Station run resolves the character/presentation, then selects an opening story BEFORE
writing narration. No new provider, API key, production dependency or manual setup is required.
`main` is the pre-upgrade baseline; `dev` is the development and server branch. The Ordak service
and `services/ordak` submodule are NOT renamed: only the repository branch changes.

1. `opening_concept` generates exactly three distinct mini-stories and requests an independent
   assessment of all three. The server ranks eligible candidates deterministically. No candidate
   can pass just by giving itself a confident score or changing a camera/location.
2. Writers receive the selected premise and real character behavior, not a list of farm/workshop
   chores. They preserve source qualifications and deliver the hook's actual payoff.
3. Episode direction stages that selected story. A text-only reviewer verifies frame-zero evidence,
   character behavior, honesty, payoff, feasibility, novelty and the A/B seam. Bounded corrections
   happen before voice or visual generation; an unusable story stops clearly rather than fabricating
   a successful result. This is a quality safeguard, not a retention guarantee.
4. A/B prompt writers share the handoff. The closed-book frame stays host-free; the orb retains its
   ownership cue. The world keyframe receives only the subject-world discovery, never host anatomy.
5. Both Flow prompt writers receive measured narration duration as well as source duration. Essential
   action must complete before trimming; surplus source time is a handle, not the location of a reveal.

## Decisions and evidence

- `creative/OPENING_CONTEXT.json`: editorial inputs, character/presentation rules, prompt hashes,
  and frozen recent-history snapshot. Cosmetics, provider settings and the CTA hint are excluded.
- `creative/OPENING_CANDIDATES.json`: candidate and independent-review responses, rejected attempts,
  scores, collision evidence, effective history ids and prompt hashes.
- `creative/OPENING_CONCEPT.json`: policy version, input fingerprint, selected mini-story and concept id.
- `creative/OPENING_REVIEW.json`: actual script/staging review and input fingerprint.
- `creative/script_draft.inputs.json`, `creative/retention_edit.inputs.json`: selected concept provenance.

The concept artifact is separate from SCRIPT_PLAN: no new fields are smuggled into spoken narration.
Policy version 2 is separate from character/presentation identity versions. Existing generated media
is not migrated by configuration loading. Ordinary resume reuses the selected story; another episode
completing cannot silently change it. Editing a frozen editorial input requires explicit Revise from
`opening_concept`, with its dependent narration and media invalidated together.

## Semantic history

`episode_history.py` persists character/profile, action/tension/prop/reveal families, actual premise,
hook and entry variant in addition to the old compatible fields. A locked read/modify/write and atomic
replacement prevent concurrent registry updates from losing entries. The current video is excluded.
New selection uses global and same-character recent history. Legacy prose is provided to the reviewer
without guessing missing character ids. Optional old history can be reduced to fit the 19,000-character
request budget; factual source notes and must-include/avoid instructions are never silently truncated.

Lexical normalization and whole-premise collision checks are screening, not an embedding model or a
claim to perfect semantic understanding. The independent reviewer compares paraphrases and meanings.
A shared action alone (including sorting when the topic really concerns classification) is allowed.
A repeated camera/book/orb is not a blocking failure. The recurring character and entry ARE the brand.

## Authoring rules

Start with the supported answer, the viewer's expectation, and a visible discrepancy. Select an
activity only when it is necessary to express that discrepancy. No obligatory job, busy hands,
workshop, farm or prop retrieval ritual. One location and no more than three clear actions in A.
During the entry, narration gives a clue rather than reporting that the camera enters an object.
Facts, metaphors and thought experiments must not be presented as interchangeable evidence.
Use a concrete payoff, not a generic final sentence or a postponed answer replaced by a CTA.

## Safe integration boundaries

- `opening_concept` is a real panel/DAG stage, before `script_draft`.
- The story-consistency review is owned by `episode_director`, before voice/media.
- CTA-only changes do not invalidate concept, direction or world-style decisions.
- Changes to editorial brief, requested duration or host-presence policy invalidate the concept.
- Character changes cascade through character resolution and concept selection.
- Flow A still uses only the character ingredient; B still uses only endpoint frames.
- The existing segment keys, one-image-per-body-unit rule, optional closing beat, timestamp alignment,
  supported Flow durations, provider gates and downstream render contracts remain intact.
- Old retained runs without a concept can resume in their legacy branch. This is not a migration tool.

## Deployment on the existing Linux server

Do not deploy while a generation job is running. From the repository working directory:

```bash
git status --short
# Resolve/stash intentional local source changes first; do not discard .env or generated media.
git fetch origin --prune
git switch dev                       # first checkout may use: git switch --track origin/dev
git pull --ff-only origin dev
.venv/bin/python scripts/check_opening_setup.py
.venv/bin/python -m pytest -q tests/test_opening_concept_pipeline.py tests/test_episode_history.py tests/test_presentation_profiles.py tests/test_run_graph.py
sudo systemctl restart video-control-panel.service video-control-panel-websocket.service
```

The service unit templates use `/opt/YT_Video_Generation_Pipeline`; use your actual checkout if different.
If pytest is not installed, install it in the virtual environment first. No new production package is
needed. Do NOT rename the Ordak service, alter its browser login, or change its submodule branch.
The final patch does not require an API contract change in the React UI.

If the local branch is still named ordak and no local dev exists, an alternative is `git branch -m
ordak dev`, followed by `git branch --set-upstream-to=origin/dev dev`. Do not force-reset local work.
`main` was explicitly synchronized to the old dev baseline; it may therefore have diverged from an
old local main checkout. Deploy dev, not a blind pull/merge into that old main.

## Verification and limitations

Provider-free regression tests cover candidate validation/ranking, bounded retries, frozen history,
source preservation, semantic repetition evidence, profile-specific narration, state reuse, DAG
cascades, review persistence, CTA isolation, frame-role isolation and measured Flow timing inputs.
The full Python suite and UI test/build run on GitHub Actions. Offline tests do not validate the
current browser login, account credits, provider availability, actual model output quality or the
resulting audience retention. A real end-to-end generation remains a separate paid smoke test.

## International spoken English

The shared spoken-language policy now reaches concept selection, narration and CTA. Selection
adds a validated `spoken_clarity` criterion. Retention owns its independent language review and
wording corrections; staging does not try to repair narration. The final CTA is reviewed in its
own scope without invalidating the visual story. See `SPOKEN_ENGLISH_POLICY.md` for details.
