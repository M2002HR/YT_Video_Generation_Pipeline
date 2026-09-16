# International spoken-English policy

Q Station uses one shared language policy for NEW generated narration, including hooks,
entry clues, body, closing and the independently generated CTA. It aims at B1 first-listen
comprehension for international teens/adults using familiar everyday words. This is an
editorial goal, not a certified CEFR score, a word blacklist or a promise of audience retention.

## Source of truth and actual wiring

`projects/q_station/prompts/pipeline/PLAIN_ENGLISH_POLICY.md` is the source of truth.
The runtime expands its explicit `{{LANGUAGE_POLICY}}` include BEFORE sending/hashing a prompt.
It is required by project preflight. Merely documenting the policy would not affect generation.

The shared text reaches:

- Opening concept designer and independent candidate reviewer. `spoken_clarity` is a scored
  criterion with the same validated integer schema as the other criteria. A usable candidate
  needs at least 3/4; this is an editorial assessment, not a language proficiency measurement.
- Script writer and retention editor. The selected premise is preserved, not its exact phrasing.
  The editor favors clear familiar wording over shorter but more abstract/formal wording.
- CTA writer and the independent spoken-language reviewer.

Technical direction for Gemini/Flow is NOT simplified or passed through this review. Character
identity, entry mechanisms, providers, subtitles, font/title settings, voice speed, narration
segment keys and the one-image-per-unit contract are unchanged. No new production dependency,
API key, UI setting or service is needed. A blank audience field still gets the default policy.

## Where corrections happen

`retention_edit` now owns a text-only edit/review loop before it commits SCRIPT_CORE_PLAN.
The reviewer inspects the actual spoken segments and compares them against the original draft,
source notes and selected promise. It can flag everyday vocabulary, abstract/dense sentences,
unexplained necessary terms, first-listen clarity and meaning preservation. Each rejection
must name a segment and quote text actually present there, with a specific correction.
The normal script validator still verifies word/beat limits and exact narration concatenation.

A language failure goes back to the NARRATION editor, not the episode director: a staging-only
retry cannot fix spoken words. The existing opening story reviewer still owns visual/story
consistency; plain rephrasing does not invalidate an otherwise identical premise.

`call_to_action` performs the same review on ONLY the final CTA. The approved core is read-only
context. CTA-only revision never rewrites the core, its review, opening or body images. Both
loops allow at most three edited candidates. Invalid reviewer schemas get bounded correction;
provider/login/credit failures retain the normal failure/approval path. Nothing is silently
accepted when review fails, and no paid audio/visual generation starts with a rejected core.

The ordinary successful path adds one language-review call at retention and one at CTA. More
text calls occur only on validation/correction. There is no new standalone DAG stage.

## Evidence and resume

- `creative/CORE_LANGUAGE_REVIEW.json`: exact core segments per attempt, checks, quoted issues,
  proposed corrections, non-blocking notes, policy/reviewer hashes and content/reference hashes.
- `creative/CTA_LANGUAGE_REVIEW.json`: the same evidence, scoped only to the final CTA.
- `creative/retention_edit.inputs.json` and `creative/CALL_TO_ACTION.json` mark new work as
  requiring its language-review receipt. The panel graph owns and invalidates these receipts
  with their existing parent stages. Missing/stale new receipts require explicit Revise.

The policy is separate from opening/character/presentation versions. Completed legacy outputs
are not rewritten or falsely labeled language-reviewed. Pre-policy opening concepts can resume
with their old prompt hashes only if their frozen original input fingerprint verifies and their
editorial, character and presentation inputs still match. Actual editorial changes still require
cascade revision. New decisions record the language policy version in their frozen context.

Do not manually edit SCRIPT_FINAL.md after audio/images exist. For a deliberate upgrade of an
existing run, use the panel's Revise/cascade from `retention_edit` (or `opening_concept` to redesign
its premise). All timed descendants must be rebuilt from the newly accepted spoken words.

## Editorial boundaries

Keep may/can/often/some, quantities, units, negation, scope and comparisons accurate. Do not
replace 'may make you more likely' with 'will make you'. Keep essential terms and proper names;
explain unfamiliar concepts in context rather than deleting the science. Simple does not mean
childish, oversimplified, culturally specific slang or a forced stock phrase.

Examples of direction, not mandatory substitutions:

| Avoid unnecessary compression | Prefer a concrete explanation |
|---|---|
| Chosen privacy differs from unexpected exposure. | Being seen when you want privacy can feel embarrassing. |
| Changing booths usually signal concealment from strangers. | In a changing room, we expect other people not to look. |
| The exact mechanism remains unsettled. | Scientists still do not know exactly how it works. |

The appropriate rewrite depends on the original claim and context. Tests in
`tests/test_narration_language.py` verify the actual calls, evidence schema, correction ownership,
uncertainty preservation feedback, candidate eligibility, resume and CTA isolation. They do NOT
prove that a live model will always produce simple or scientifically correct prose.

## Deployment and checks

Use the existing `dev` deployment procedure when no generation is in progress. After updating:

```bash
.venv/bin/python scripts/check_opening_setup.py
.venv/bin/python -m pytest -q tests/test_narration_language.py tests/test_opening_concept_pipeline.py tests/test_call_to_action_stage.py
```

Restart the running panel processes so they load updated Python. Existing launch/subtitle/voice
settings need no changes. Full Python and UI regression remain in `.github/workflows/dev-validation.yml`.

For actual language quality, listen once to a newly generated hook and body without reading the
script. Ask a non-native listener to restate the question and answer. Inspect both language
reports if a sentence still needs decoding. Necessary technical names, natural contractions or
sentence length alone are not grounds for rejection; comprehension and preserved meaning are.
