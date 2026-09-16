# Release thumbnail pipeline

Release is a post-render operation. It never changes narration, body images, timeline,
subtitle settings, audio, or `assets/renders/polished.mp4`.

## Contract

`GET /api/release-schema` is the source of truth for the Release modal defaults and
capabilities. `POST /api/releases` validates the same schema again in
`scripts/release_settings.py`. Unknown fields, non-finite numbers, unsupported ratios,
unknown fonts/profiles/assets, invalid nested objects, unsafe coordinates, and budget
settings that cannot cover the requested candidate count are rejected before a provider
is opened. Only native 9:16 is currently advertised because that is the supported
release adapter.

Artwork and final thumbnails are intentionally separate:

1. Gemini through `OrdakJobs` receives identity, final-render, and limited world references
   and creates text-free artwork with planned negative space.
2. `thumbnail_compositor.py` renders the exact English headline, Q Station mark, and
   styling using the resolved, hashed local font.
3. The final PNG and its small preview go to the final reviewer. The reviewer recommendation
   is an editorial score, not a CTR estimate or a YouTube A/B result.

The Advanced **Run thumbnail QC and final visual review** switch is on by default. When an
operator turns it off, `Runner.image(..., skip_content_qc=True)` prevents Gemini artwork from
being uploaded to ChatGPT for shared image QC, and the final composed-file reviewer is not
called. Decode/dimension checks, canonical-reference preflight, local font rendering, and text
bounds checks remain mandatory. The persisted candidate review explicitly says
`SKIPPED_OPERATOR`; its recommendation score is zero, rather than pretending a visual review ran.

Release always uses Gemini as its primary artwork provider and automatically falls back to one
ChatGPT `image_generate` request through Ordak when Gemini cannot produce usable artwork. Both
providers receive the same references. The candidate manifest records
`generated_provider`, the ChatGPT receipt, and the originating Gemini error. If both providers
fail, Release stops with both errors; it never creates a placeholder or silently substitutes a provider.

The character is loaded through `character_runtime.load_character_registry`; a missing,
corrupt, or escaped canonical sheet stops preflight. `hero_presence_mode=opener_only`
does not remove the resolved episode host from this Release-only operation.

Each request has `release_id` and writes under:

```text
publish/youtube_short/releases/<release_id>/
  RELEASE_REQUEST.json  RELEASE_STATE.json  THUMBNAIL_CONTEXT.json
  THUMBNAIL_PLAN.json    THUMBNAIL_REVIEW.json THUMBNAIL_SELECTION.json
  thumbnail_candidates/<candidate_id>/{concept.json,artwork.png,final.png,layout.json,review.json}
  comparison.jpg
```

`publish/youtube_short/CURRENT_RELEASE.json` points at the current revision. The legacy
`thumbnail.png` alias is copied byte-for-byte from the selected final candidate and its
hash is recorded. If no candidate is eligible, selection is null and status is
`NEEDS_REVIEW`; no previous winner is presented as this batch's winner.

The panel stores the most recently successfully started Release configuration in
`control_panel/release_last_settings.json`. It is a validated panel preference, separate
from episode files and from each immutable `RELEASE_REQUEST.json`; therefore it is offered
when opening Release for either a new or an older run. It contains no credentials or binary data.

## Example request

```json
{
  "job_id": "studio-job-id",
  "settings": {
    "generate_metadata": true,
    "generate_thumbnail": true,
    "create_upload_guide": true,
    "send_telegram": true,
    "thumbnail": {
      "count_mode": "fixed",
      "count": 3,
      "concept_count": "auto",
      "brand_profile": "q_station_v1",
      "layout_mode": "auto",
      "allowed_layouts": ["character_left", "character_right", "contrast_split", "discovery_focus"],
      "text_mode": "auto",
      "text_renderer": "local",
      "aspect_ratio": "9:16",
      "image_model": "inherit_episode",
      "corrections_per_candidate": 1,
      "max_image_generations": 6,
      "review_preset": "balanced",
      "delivery_mode": "all_final_candidates"
    }
  }
}
```

`send_telegram` delivers the untouched QC-passed master as a document, then every visible
final candidate as a document in the same reply thread. A selected candidate is marked
recommended; eligible but weaker candidates are still delivered. Raw artwork is not sent
by this implementation. A local receipt records confirmed message IDs; ambiguous network
outcomes require operator reconciliation rather than a blind resend.

## Preflight and dry-run

`thumbnail_runtime.preflight(video, content_project, settings)` is provider-free: it
checks the registry/sheet, font, ratio, count, and submission ceiling. Use
`python3 scripts/release_youtube_short.py videos/<episode> --request-file <request.json> --dry-run`
to validate the limited Release plan and print possible provider-call counts without generation,
login, or Telegram delivery. Normal automated tests use fakes and must not consume credentials.

## YouTube upload guidance

The upload guide describes the PNG as a finished separate file. It never appends a frame,
re-encodes the master, or promises that every Shorts account can set a custom thumbnail.
At upload time, check the current official [YouTube Studio thumbnail guidance](https://support.google.com/youtubecreatorstudio/answer/72431?co=GENIE.Platform%3DDesktop&hl=en)
and the account's mobile/Studio capability. Use a supported custom-thumbnail flow when it
is available; otherwise select an existing frame and document the limitation.
