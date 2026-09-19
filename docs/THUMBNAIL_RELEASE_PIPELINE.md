# Release thumbnail pipeline

Release is a post-render operation. It never changes narration, body images, timeline,
subtitle settings, audio, or `assets/renders/polished.mp4`.

Release is also a first-class Studio pipeline. `/releases` lists only source videos that
currently pass the server-side Release gate, followed by the complete audit history of
Release runs.  Each run has its own board, dependency graph, activity, log and artifacts.
The graph contract lives in `scripts/release_graph.py`; it is intentionally independent of
the episode graph.

Resume keeps the same `release_id` and reuses valid checkpoints.  Revise creates an immutable
child with `parent_release_id`, copies reusable evidence, removes only the selected node's
dependency closure, and starts the normal worker. Candidate artwork, composition and final
review are separate nodes, so revising one candidate does not spend credits on its siblings.

## Contract

`GET /api/release-schema` is the source of truth for the Release modal defaults and
capabilities. `POST /api/releases` validates the same schema again in
`scripts/release_settings.py`. Unknown fields, non-finite numbers, unsupported ratios,
unknown fonts/profiles/assets, invalid nested objects, unsafe coordinates, and budget
settings that cannot cover the requested candidate count are rejected before a provider
is opened. Only native 9:16 is currently advertised because that is the supported
release adapter.

Artwork and final thumbnails are intentionally separate:

1. ChatGPT `image_generate` through `OrdakJobs` receives the episode character sheet as the
   mandatory identity attachment. An approved current thumbnail may be attached separately
   as an optional series-style reference.
2. Headline mode is selected in Basic settings: ChatGPT chooses a short factual headline,
   the original episode title is used, or the operator supplies exact manual text. The resolved
   headline is injected verbatim into every image prompt. ChatGPT creates the finished artwork;
   the pipeline validates, crops without distortion, and normalizes it to an exact 1080×1920 PNG.
   It never adds a second text layer later.
3. The final PNG and its small preview go to the final reviewer. The reviewer recommendation
   is an editorial score, not a CTR estimate or a YouTube A/B result.

The Advanced **Run thumbnail QC and final visual review** switch is on by default. When an
operator turns it off, the final composed-file reviewer is not called. Decode/dimension checks,
canonical-reference preflight, attachment hashes, decoding, dimensions, and final-file
integrity checks remain mandatory. The persisted candidate review explicitly says
`SKIPPED_OPERATOR`; its recommendation score is zero, rather than pretending a visual review ran.

Release artwork is locked to ChatGPT. There is no Gemini primary path or provider fallback.
The candidate receipt records `generated_provider=chatgpt`, Ordak job ID, provider receipt,
attachment roles and SHA-256 hashes, original download information, and normalization details.
Unreadable, undersized, or non-vertical output stops the branch; no placeholder is created.

Thumbnail files contain no words, numbers, pseudo-text, caption, badge, or pipeline-added logo.
The Studio exposes only the candidate count, QC switch, optional approved style, and a concise
art-direction field; the previous advanced typography/placement controls are not shown.

The character is loaded through `character_runtime.load_character_registry`; a missing,
corrupt, or escaped canonical sheet stops preflight. `hero_presence_mode=opener_only`
does not remove the resolved episode host from this Release-only operation.

Each request has `release_id` and writes under:

```text
publish/youtube_short/releases/<release_id>/
  RELEASE_REQUEST.json  RELEASE_STATE.json  THUMBNAIL_CONTEXT.json
  THUMBNAIL_PLAN.json THUMBNAIL_REVIEW.json THUMBNAIL_SELECTION.json
  thumbnail_candidates/<candidate_id>/{concept.json,artwork.png,final.png,layout.json,review.json}
  comparison.jpg
```

New runs additionally persist `SOURCE_SNAPSHOT.json`, `RELEASE_CONTEXT.json`,
`METADATA_DRAFT.json`, `METADATA_REVIEW.json`, and a per-candidate `candidate.json`
checkpoint. Process ownership is separate from episode jobs under
`control_panel/release_jobs/<release_id>.json`; episode job files retain only a compatibility
summary of the newest Release.

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
      "layout_mode": "stacked_brand",
      "allowed_layouts": ["stacked_brand"],
      "topic_mode": "episode",
      "video_title_mode": "metadata",
      "text_mode": "auto",
      "aspect_ratio": "9:16",
      "image_model": "chatgpt",
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
by this implementation. A local receipt records each confirmed message ID and content hash
immediately. Resume skips those confirmed items and continues at the first unsent item;
an ambiguous network outcome still requires operator reconciliation rather than a blind resend.

Progress notification is separate from `send_telegram`: when pipeline notifications are enabled,
Release reports every medium-granularity graph stage (including each candidate's artwork,
headline-bearing finalization and review) by editing one durable message per stage. Review-needed
and failure states update that same message rather than flooding the chat.

## Preflight and dry-run

`thumbnail_runtime.preflight(video, content_project, settings)` is provider-free: it
checks the registry/sheet, ratio, count, and submission ceiling. Use
`python3 scripts/release_youtube_short.py videos/<episode> --request-file <request.json> --dry-run`
to validate the limited Release plan and print possible provider-call counts without generation,
login, or Telegram delivery. Normal automated tests use fakes and must not consume credentials.

## YouTube upload guidance

## Metadata and search contract

The primary title core is the exact episode title stored in `LAUNCH_REQUEST.json`; Release does
not rewrite it or force uppercase. It appends one relevant emoji and then `#shorts`. ChatGPT also
returns three factual alternatives, a unique three-line description, compact tags, and a persisted
`seo_strategy` containing the primary query, intent, close queries, and useful spelling variants.

The prompt follows current official guidance rather than promising rankings: YouTube search uses
the match between title, description, tags, and actual video content together with engagement and
quality; title and description are more important than tags; tags mainly help with misspellings;
and one or two main phrases should appear naturally in both title and description. Google likewise
recommends unique, descriptive video titles/descriptions and consistent factual metadata.

References:

- https://support.google.com/youtube/answer/16090438
- https://support.google.com/youtube/answer/12948449
- https://support.google.com/youtube/answer/146402
- https://support.google.com/youtube/answer/12340300
- https://developers.google.com/search/docs/appearance/video

The upload guide describes the PNG as a finished separate file. It never appends a frame,
re-encodes the master, or promises that every Shorts account can set a custom thumbnail.
At upload time, check the current official [YouTube Studio thumbnail guidance](https://support.google.com/youtubecreatorstudio/answer/72431?co=GENIE.Platform%3DDesktop&hl=en)
and the account's mobile/Studio capability. Use a supported custom-thumbnail flow when it
is available; otherwise select an existing frame and document the limitation.
