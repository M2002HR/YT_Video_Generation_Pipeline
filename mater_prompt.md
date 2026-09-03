You are the senior engineer responsible for taking an existing mature
YouTube video-generation repository and turning the new Question Harvest
content project into a fully deployed, production-grade, highly reliable,
browser-automated creative pipeline.

You are responsible for:

- repository reconciliation
- implementation
- browser automation
- provider hardening
- service deployment
- systemd
- nginx
- VNC/noVNC
- control panel
- image generation
- video generation
- voiceover
- background music
- alignment
- mixed-media rendering
- QC
- resumability
- testing
- documentation
- Git publication

You are expected to work autonomously.

Do not stop for small implementation decisions.

Reliability, reproducibility, provider correctness, browser automation stability,
and safe resumability are the highest priorities.


======================================================================
0. REPOSITORY
======================================================================

Parent repository:

M2002HR/YT_Video_Generation_Pipeline

Required parent branch:

ordak


Ordak submodule:

services/ordak


Configured Ordak upstream/integration repository:

AliBalash/ordak

Expected Ordak integration branch:

yt-video-pipeline


At the time this implementation specification was written, the most recently
observed parent HEAD was:

90685e5da16cd6b7b71f47d701eb261612ead91a

DO NOT ASSUME THIS IS STILL CURRENT.

FETCH FIRST.


======================================================================
1. NEW CONTENT PROJECT
======================================================================

Create a completely separate new content project.

Internal project id:

question_harvest


Display name:

Question Harvest


Working tagline:

A question grows. A book opens. A world begins.


Do NOT repurpose:

projects/default

Do NOT repurpose:

projects/world_behind_the_question


Existing videos must remain where they are.

Do not move or rewrite:

videos/008_pandora_s_box

videos/009_vikings_history

They belong to:

world_behind_the_question


Existing legacy videos belonging to `default` must also remain untouched.


======================================================================
2. BRAND SOURCE OF TRUTH
======================================================================

Four canonical source images are supplied together with this implementation
request.

Those images define:

- the protagonist
- protagonist proportions
- protagonist turnaround
- protagonist silhouette
- protagonist clothing
- protagonist face / beard / hair
- home-world visual language
- farm/garden/workshop/orchard/greenhouse/home environments
- base hand-drawn cartoon identity

The images override descriptive text if there is any disagreement.

The new protagonist is NOT the Library Seeker from the older
world_behind_the_question project.


Recognizable identity includes:

- tall/slim simplified adult male cartoon
- prominent brown/chestnut hair silhouette
- beard / moustache / goatee
- light moss / green sweater
- dark blue overalls
- rust / orange boots
- simple bold linework
- approachable hand-drawn educational cartoon language


Do not redesign the protagonist.


======================================================================
3. FIXED PROVIDER CONTRACT
======================================================================

Provider ownership is ABSOLUTE.

There is NO provider fallback.


TEXT / CREATIVE PLANNING

Provider:
ChatGPT Web

Execution:
Ordak browser automation


IMAGE GENERATION

Provider:
Gemini Web

Execution:
Ordak browser automation

Gemini is the ONLY production image generator.


VIDEO GENERATION

Provider:
Google Flow Web

Execution:
Ordak browser automation

Google Flow is the ONLY production video generator.


VOICEOVER

Provider:
ElevenLabs Web UI

No ElevenLabs API.


BACKGROUND MUSIC

Preserve the existing approved browser-based music workflow.


TIMING / STT

Preserve the current working pipeline implementation.


RENDER

FFmpeg / ffprobe.


======================================================================
4. NO PROVIDER FALLBACK — HARD RULE
======================================================================

Question Harvest images must NEVER be generated through:

- ChatGPT image generation
- OpenAI image APIs
- Flow still generation
- Pollinations
- Vertex AI image APIs
- Gemini APIs
- any unrelated image provider


If Gemini is unavailable:

STOP or PAUSE the Gemini stage.

Do NOT use another provider.


Question Harvest videos must NEVER be generated through:

- Gemini Apps video generation
- Vertex / Veo API
- another web video generator
- ChatGPT
- a local synthetic substitute

If Google Flow is unavailable:

STOP or PAUSE the Flow stage.

Do NOT use another provider.


Selector fallback inside the SAME provider is allowed.

Provider fallback is forbidden.


Example:

Gemini selector A fails
→ try Gemini selector B

GOOD.


Gemini generation unavailable
→ use ChatGPT Image

FORBIDDEN.


======================================================================
5. STRICT MODEL CONTRACT
======================================================================

Model selection must also be explicit.

The requested model comes from:

1. persisted launch configuration
2. Control Panel input
3. project default


The automation must:

- select the requested model in the live UI
- inspect the UI after selection
- verify the requested model is active
- record the visible actual model label
- refuse to generate if verification fails


Never assume a successful click means the model changed.


Never silently substitute another model.


If the requested model cannot be used:

return a structured error such as:

MODEL_NOT_AVAILABLE

MODEL_SELECTION_FAILED

MODEL_FEATURE_INCOMPATIBLE


Do NOT substitute a different model automatically.


======================================================================
6. DEFAULT IMAGE CONFIGURATION
======================================================================

Question Harvest default:

Provider:
Gemini


Internal image model:

nano_banana_pro


Display label:

Nano Banana Pro


Quality policy:

best


Final accepted production image must be produced through the Pro-quality path.


Current Gemini product behavior may generate an initial Nano Banana 2 image and
offer a Pro regeneration / “Redo with Pro” control.

The implementation MUST inspect the real current UI.


If Nano Banana Pro is selected:

1. select the required Gemini Pro context if necessary
2. submit generation
3. wait for the initial image result
4. identify the current result
5. locate the current Pro regeneration/refinement action
6. invoke it
7. wait for the new Pro result
8. positively distinguish the Pro result from the initial result
9. download the Pro result
10. validate the downloaded result
11. accept only the Pro result


If Pro generation is unavailable:

DO NOT accept Nano Banana 2.

Return a model availability error.


======================================================================
7. SECOND GEMINI MODEL OPTION
======================================================================

Control Panel must also support:

Nano Banana 2

Internal value:

nano_banana_2


If explicitly selected:

the Nano Banana 2 output is valid.

Do not automatically redo with Pro.


The available image-model dropdown for Question Harvest should initially be:

Nano Banana Pro
Nano Banana 2


Default:

Nano Banana Pro


Provider remains locked to Gemini.


======================================================================
8. GEMINI IMAGE MODEL RECEIPT
======================================================================

Every Gemini image generation must store:

provider = gemini

requested_model

actual_model_label

model_verified

pro_regeneration_used

requested_quality

actual output dimensions

job id

conversation/tab identity where useful

reference files

reference SHA256 hashes

prompt artifact

output path

output SHA256

generation started_at

generation completed_at

retry/recovery events


Store provider receipts under something like:

videos/<video>/pipeline/provider_receipts/


======================================================================
9. DEFAULT FLOW CONFIGURATION
======================================================================

Question Harvest default video provider:

Google Flow


Default model:

Gemini Omni 1.1 Flash


Internal normalized value:

gemini_omni_1_1_flash


Default generation resolution:

720p


Default Short aspect ratio:

9:16


Default Clip A source duration:

6 seconds


Default Clip B source duration:

4 seconds


The final edit normally trims these clips to approximately:

Clip A:
~5 seconds

Clip B:
~3 seconds


Actual final clip boundaries must be determined from narration timing.


======================================================================
10. FLOW MODEL OPTIONS
======================================================================

Control Panel should expose explicit model selection.

At minimum support current Flow video model families actually available in the
authenticated UI, initially including:

Gemini Omni 1.1 Flash

Veo 3.1 Quality

Veo 3.1 Fast

Veo 3.1 Lite


Do not show:

Auto

Best available

Any model

Fallback


as production model selections.


The provider itself remains:

Google Flow

LOCKED.


Changing the model does NOT change the provider.


======================================================================
11. LIVE FLOW CAPABILITY MATRIX
======================================================================

Do not maintain a stale hard-coded capability matrix as the only truth.

Implement a live Flow capability/state inspector.

Before launch or generation, determine:

- selected model
- available aspect ratios
- available durations
- first-frame capability
- first+last-frame capability
- ingredients/reference capability
- supported draft/final resolutions
- any visible model restrictions


Normalize the live UI to internal model identifiers.


The pipeline may maintain expected capabilities for validation, but final
verification must use the real current UI.


If the user selects a model that cannot perform the requested operation:

DO NOT choose a different model.

Return:

MODEL_FEATURE_INCOMPATIBLE


======================================================================
12. ABSOLUTE FLOW REFERENCE RULE
======================================================================

THIS RULE IS EXTREMELY IMPORTANT.

For Google Flow video generation:

DO NOT UPLOAD ANY STYLE SHEET.

EVER.


Specifically forbidden as Flow reference/ingredient uploads:

- home style sheet
- farm style sheet
- environment style sheet
- visual style anchor
- world style anchor
- book style sheet
- style board
- mood board
- previous image as a style reference
- any canonical style reference sheet


The ONLY canonical recurring reference sheet Flow is allowed to receive is:

THE CHARACTER SHEET.


This is a hard project rule.


The purpose is:

- preserve protagonist identity
- avoid over-constraining Flow
- avoid style-sheet contamination
- let each video prompt define visual treatment
- keep video generation simpler and more stable


======================================================================
13. FLOW CHARACTER SHEET RULE
======================================================================

Create one canonical Flow character-reference asset derived directly from the
supplied source character sheets.

For example:

projects/question_harvest/visual_presets/001_home_world/
    character_sheet.png


This is the ONLY canonical brand reference sheet sent to Flow.


Do not send:

home_style_anchor.png

style_anchor.png

book_anchor.png

world_style_anchor.png


to Flow.


======================================================================
14. IMPORTANT DISTINCTION — FRAME INPUTS ARE NOT STYLE SHEETS
======================================================================

Clip B requires scene-specific image inputs.

These are NOT reusable reference/style sheets.

Therefore the following remain allowed:

FIRST FRAME:

BOOK_SPREAD_FRAME.png


END / DESTINATION FRAME:

WORLD_KEYFRAME.png


They are job-content inputs defining the actual transition.

They are not style references.


Therefore Flow Clip B can receive:

canonical character sheet

PLUS, through the proper Flow frame controls:

BOOK_SPREAD_FRAME.png

WORLD_KEYFRAME.png


But it must NOT receive a style sheet.


======================================================================
15. CLIP A FLOW INPUT CONTRACT
======================================================================

Clip A is:

QUESTION SPARK


Provider:

Flow


Persistent/canonical reference upload:

CHARACTER SHEET ONLY.


Exactly no style sheet.


Do not upload:

- home world style sheet
- environment sheet
- style anchor
- book anchor
- world-style anchor


The visual home-world style must instead be communicated through:

- carefully written prompt language
- known project visual rules
- protagonist identity
- natural composition instructions


The prompt may describe the home-world appearance in text.

The prompt must not require uploading the style sheet.


======================================================================
16. CLIP B FLOW INPUT CONTRACT
======================================================================

Clip B is:

BOOK OPENS → WORLD


Provider:

Flow


Canonical reference sheet:

CHARACTER SHEET ONLY.


Additionally use job-specific frame inputs:

BOOK_SPREAD_FRAME.png

WORLD_KEYFRAME.png


Do NOT upload a style sheet.


If the protagonist is completely absent from Clip B and live Flow testing proves
that uploading the character sheet harms output reliability, the implementation
may make the character-sheet ingredient optional for that specific clip.

However:

NO OTHER reference sheet becomes allowed.

The allowed persistent reference-set invariant remains:

character sheet only.


Document this behavior.


======================================================================
17. FLOW PROMPT MUST CARRY VIDEO STYLE
======================================================================

Because no style sheet is sent to Flow, the Flow prompt writer must be strong.

For Clip A the prompt must describe:

- simple hand-drawn 2D cartoon
- clean dark outlines
- warm rustic educational animation
- simplified geometry
- muted natural palette
- readable silhouettes
- protagonist design must match uploaded character sheet
- farm/home/workshop/garden environment appropriate to the selected activity
- no photorealism
- no 3D CGI
- no anime
- no high-detail semi-realistic concept art


But DO NOT copy the visual sheet as an upload.


For Clip B:

the actual first/end frames should provide most visual continuity.

The prompt should focus on:

- preserving first-frame geometry
- preserving page image
- smooth push-in
- transition toward the exact world keyframe
- no invented page elements
- no readable text
- no morphing character
- no unexpected objects


======================================================================
18. FLOW MODEL VERIFICATION
======================================================================

Before every paid generation:

requested:

<model>


Flow automation must:

1. inspect current model
2. open model selector if necessary
3. select requested model
4. wait for UI stabilization
5. inspect selected model again
6. normalize visible label
7. compare requested and actual
8. generate ONLY if they match


Do not rely on previous-job model state after:

- browser restart
- tab reopen
- project reopen
- service restart
- model-changing operation


======================================================================
19. FLOW DURATION VERIFICATION
======================================================================

Before Generate:

select requested source duration.

Then inspect selected duration.

Only continue if it matches.


For default Omni workflow:

Clip A source:

6 sec


Clip B source:

4 sec


If the selected Flow model does not support the requested duration:

DO NOT silently switch to another duration.

Fail preflight or stage validation.


======================================================================
20. FLOW ASPECT RATIO VERIFICATION
======================================================================

Before every Flow generation:

select requested aspect.

For Shorts default:

9:16


Verify the UI shows the requested aspect.

Never depend on the previous Flow project setting.


======================================================================
21. FLOW RESOLUTION VERIFICATION
======================================================================

Question Harvest panel must expose generation resolution supported by the
selected model/current Flow UI.

Default:

720p


Allow:

360p Draft

where the live model supports it.


Do not silently lower:

720p → 360p


If 720p cannot be selected:

return an error.


Any higher-resolution export/upscale feature should be separately modeled as an
optional export setting rather than silently changing generation behavior.


======================================================================
22. FLOW CREDIT SAFETY
======================================================================

Flow generation may consume credits.

Avoid duplicate jobs.


Before pressing Generate persist:

provider

requested model

verified actual model

prompt SHA

character-sheet SHA

first-frame SHA if any

end-frame SHA if any

duration

aspect ratio

resolution

workspace/project URL

submission fingerprint

timestamp


After Generate:

persist observable generation state.


If:

- browser crashes
- network disappears
- Flow times out
- Ordak restarts
- tab disappears


DO NOT automatically press Generate again.


First reconcile the same Flow workspace.


Check:

- active generation card
- previous prompt
- progress indicator
- completed clip
- failed-generation UI
- recent matching result
- downloadable result


Recover/download an existing matching generation if possible.


Blind duplicate retry count:

ZERO.


======================================================================
23. FLOW PROVIDER RECEIPTS
======================================================================

Store durable receipts for:

opening A

opening B


Example:

pipeline/provider_receipts/flow_opening_a.json


Include:

provider

requested model

actual model

model_verified

character_reference

prompt SHA

duration requested

duration actual

resolution requested

resolution actual

aspect requested

aspect actual

Flow workspace URL

generation state

output file

ffprobe data

SHA256

recovery history


======================================================================
24. NEW ORDAK FLOW PROVIDER
======================================================================

Flow must become an explicit first-class Ordak provider.


Current Ordak approximately understands:

chatgpt
gemini


Extend provider typing to:

chatgpt
gemini
flow


Unknown providers MUST fail.


Never implement:

if provider != "chatgpt":
    GeminiAdapter()


Create:

FlowAdapter


or an equally isolated implementation.


Flow and Gemini may belong to Google, but they are separate provider UIs and
must have separate:

URL matching

login detection

selectors

generation logic

output extraction

diagnostics

error handling


======================================================================
25. ORDAK VIDEO JOB MODE
======================================================================

Add first-class video job support.


Conceptually:

provider:
flow

mode:
video_generate


Add:

output_videos


Do not store MP4 outputs in:

output_images


Video artifact schema should contain:

path

filename

duration

width

height

codec

frame rate

audio stream presence

filesize

SHA256


======================================================================
26. FLOW LOGIN / MANUAL VERIFICATION
======================================================================

Detect:

ready

login_required

manual_verification_required


Do not attempt to bypass:

CAPTCHA

Google account verification

security challenge


If manual intervention is required:

pause the job

persist state

surface VNC instructions


======================================================================
27. FLOW ERROR CODES
======================================================================

Add/use structured errors such as:

FLOW_LOGIN_REQUIRED

FLOW_MANUAL_VERIFICATION_REQUIRED

MODEL_NOT_AVAILABLE

MODEL_SELECTION_FAILED

MODEL_FEATURE_INCOMPATIBLE

FLOW_UPLOAD_FAILED

FLOW_FRAME_UPLOAD_FAILED

FLOW_GENERATION_TIMEOUT

FLOW_CREDITS_EXHAUSTED

FLOW_UI_CHANGED

FLOW_TAB_LOST

FLOW_RESULT_NOT_FOUND

FLOW_DOWNLOAD_FAILED

INVALID_VIDEO_OUTPUT

FLOW_RECONCILIATION_REQUIRED


Use existing generic ErrorCode structures where appropriate.


======================================================================
28. GEMINI AUTOMATION
======================================================================

Ordak already contains substantial Gemini support.

Do not rebuild it unnecessarily.


Existing observed capabilities include:

GeminiAdapter

image_generate mode

image upload

multiple attachment sequencing

attachment verification

generated-image readiness

download extraction

asset-URL extraction

DOM fallback

job persistence

rebind/retry


Re-enable and production-harden this path for Question Harvest.


======================================================================
29. GEMINI PROVIDER RESTRICTION REMOVAL
======================================================================

The parent pipeline currently contains code that intentionally restricts the
video-pipeline Ordak integration to ChatGPT.


For example:

scripts/run_ordak.py


previously rejected non-ChatGPT provider mode.


Remove this architectural restriction.


However DO NOT replace it with a single global provider switch.


The same running Ordak service must concurrently support job-level providers:

ChatGPT for text

Gemini for images

Flow for videos


Provider is selected per job.


======================================================================
30. GEMINI REFERENCE STACK FOR IMAGES
======================================================================

For body image generation, Gemini reference behavior differs from Flow.

Gemini MAY and SHOULD receive style references.


If protagonist is absent:

1. current episode world style anchor
2. world keyframe
3. recurring world/location reference if needed
4. previous accepted body image if applicable
5. prompt


If protagonist is present:

1. canonical character sheet
2. current episode world style anchor
3. world keyframe
4. recurring world/location reference if needed
5. previous accepted body image
6. prompt


This Flow restriction:

NO STYLE SHEET

does NOT apply to Gemini image generation.


======================================================================
31. GEMINI UPLOAD VERIFICATION
======================================================================

Before submission:

expected attachment count must match provider-visible ready attachment count.


Every attachment must:

- be present
- have completed upload
- show preview or recognized attachment state
- not be loading
- not be unexpectedly duplicated


Never generate while required references are missing.


======================================================================
32. GEMINI IMAGE DOWNLOAD VALIDATION
======================================================================

Every accepted image must pass:

file exists

minimum sensible filesize

valid decoder

width/height extracted

aspect ratio tolerance

not identical SHA to previous image

belongs to current generated turn

not a user-upload thumbnail

not a stale previous result


Store:

SHA256

dimensions

file size

provider

model

references


======================================================================
33. BRAND EPISODE STRUCTURE
======================================================================

Every Question Harvest episode follows:

ordinary activity

→ curiosity trigger

→ question/hook

→ protagonist goes/reaches for a relevant book

→ book opens

→ two-page spread appears

→ world image exists on page

→ camera pushes into that image

→ body happens inside the book world

→ optional return/closing


This is the brand grammar.


The exact activity/scenario must vary.


======================================================================
34. OPENING A — QUESTION SPARK
======================================================================

Final target:

approximately 5 seconds.


The protagonist begins already doing something.


Possible home-world activities include:

gardening

digging

planting

watering

workshop repair

sorting tools

handling rope

feeding chickens

working around barn

carrying harvest

orchard work

greenhouse work

using a well

market preparation

rainy-day work

winter work

home maintenance

another believable activity


The exact activity must be chosen based on:

topic

hook

visual storytelling

recent episode history


Do not force a bizarre topic-specific object into the farm.


A normal observation creates curiosity.


The narration begins from second zero.


Avoid generic:

“Have you ever wondered…”

as a repeated opener.


======================================================================
35. OPENING ACTIVITY ANTI-REPETITION
======================================================================

Persist across completed Question Harvest episodes:

opening_activity

opening_location

trigger_object

curiosity_trigger

camera_pattern

book_retrieval_pattern

book_template_id

world_style_id

texture_family

hero_presence_mode

closing_mode


Before a new episode:

inspect recent Question Harvest history.


Suggested heuristics:

avoid identical opening activity within last 4 videos

avoid same exact opening location in consecutive videos

avoid same camera pattern consecutively

avoid same book template consecutively

penalize overused world texture


Topic relevance remains more important than novelty.


======================================================================
36. OPENING B — BOOK TRANSITION
======================================================================

Final target:

approximately 3 seconds.


The open book is visible.

Both pages are readable as page shapes.


One page:

decorative pseudo-writing.


The marks must NOT contain:

readable English

fake factual text

fake historical inscriptions

fake runes

meaningful unsupported content


Use abstract line-like marks.


Other page:

contains the exact pre-generated:

WORLD_KEYFRAME.png


Then:

gentle push-in / zoom

toward that page

and transition into the world.


======================================================================
37. DETERMINISTIC BOOK SPREAD
======================================================================

Do not ask Flow to invent the book layout from scratch every episode.


Implement:

scripts/compose_book_spread.py


or equivalent.


Inputs:

canonical blank book template

world keyframe

selected template id

episode seed

aspect ratio


Output:

videos/<video>/references/book_spread_frame.png


The compositor should:

- place the exact world image into the intended page
- perspective warp correctly
- generate decorative unreadable pseudo-writing
- preserve book geometry
- preserve requested aspect
- be deterministic


Create several reusable book-template variants when practical.


Variation can include:

camera angle

page tilt

crop

decorative marks


Core book identity remains recognizable.


======================================================================
38. BOOK TEMPLATE GENERATION
======================================================================

If canonical blank book templates do not yet exist:

they may be generated using Gemini browser image generation.


Do not use Flow to generate canonical book templates.


Do not use official image APIs.


Once created and validated:

store them under the Question Harvest project as canonical reusable assets.


======================================================================
39. WORLD STYLE SYSTEM
======================================================================

Every episode gets an episode-specific world visual style.


Examples:

woodcut

historical engraving

charcoal

ink wash

clay / stop-motion-like

paper cut

collage

fresco

manuscript illustration

retro educational illustration

blueprint

technical drawing

screen print

painted storybook

monochrome illustration

surreal conceptual collage


Do not randomly mix unrelated media beat by beat.


For a Short:

one primary world style

optionally one subtle secondary treatment


Most style diversity should happen BETWEEN episodes.


======================================================================
40. WORLD STYLE CATALOG
======================================================================

Create:

projects/question_harvest/world_styles/


Suggested:

CATALOG.json


Reusable style directories contain:

STYLE.json

README.md

style_anchor.png


Metadata:

style_id

display_name

medium_family

texture_family

palette_summary

subject_affinities

negative constraints

status

created_for_video

created_at

usage_count

recent videos

Gemini model used

anchor SHA256


Before each episode:

score existing styles

consider topic

consider recent usage

reuse when appropriate

create new when necessary


Do not generate duplicate styles endlessly.


======================================================================
41. WORLD STYLE ANCHORS ARE FOR GEMINI, NOT FLOW
======================================================================

This distinction must be explicit throughout the codebase.


WORLD STYLE ANCHOR:

Gemini image-generation reference:
YES


Google Flow reference upload:
NO


Do not accidentally pass the style anchor into Flow because a generic
“references” list happens to contain it.


Flow input construction must have its own explicit reference policy.


======================================================================
42. WORLD KEYFRAME
======================================================================

Before Flow Clip B:

generate:

videos/<video>/references/world_keyframe.png


Provider:

Gemini ONLY.


Use the launch-selected Gemini image model.


The world keyframe establishes:

world texture

palette

medium

atmosphere

visual grammar

subject vocabulary


It becomes:

book page image

Flow Clip B destination/end frame

body visual reference

preferably first body visual


This creates:

book page

→ zoom

→ exact same world frame

→ body


======================================================================
43. WORLD KEYFRAME PRO MODEL RULE
======================================================================

If launch configuration specifies:

nano_banana_pro


the accepted world keyframe MUST be a verified Pro result.


An initial Nano Banana 2 image is not sufficient.


======================================================================
44. HERO PRESENCE MODE
======================================================================

Implement:

auto

opener_only

limited_in_world

in_world


`auto` chooses based on:

topic

narrative role

visual usefulness


Historical subjects may often use:

opener_only

or:

limited_in_world


Psychology / philosophy / conceptual explanation may often benefit from:

in_world


But this is not a hard category map.


======================================================================
45. PROTAGONIST INSIDE BOOK WORLD
======================================================================

When protagonist appears inside the book world:

same identity

different current world rendering medium.


Examples:

same character in charcoal

same character in clay

same character in ink

same character in paper cut

same character in manuscript illustration


Preserve:

hair silhouette

beard

face proportions

clothing identity

body shape


World medium changes.

Character identity does not.


======================================================================
46. NEW PROJECT STRUCTURE
======================================================================

Create approximately:

projects/question_harvest/
├── PROJECT.json
├── README.md
├── VIDEOS.json
├── SETUP_CHECKLIST.md
│
├── prompts/
│   ├── characters/
│   │   ├── CHARACTER_BIBLE.md
│   │   └── CHARACTER_REFERENCE_RULES.md
│   │
│   └── pipeline/
│       ├── 01_script_writer.md
│       ├── 02_retention_editor.md
│       ├── 03_episode_director.md
│       ├── 04_world_style_director.md
│       ├── 05_visual_beat_planner.md
│       ├── 06_world_keyframe_prompt_writer.md
│       ├── 07_single_beat_image_prompt_writer.md
│       ├── 08_opening_video_prompt_writer.md
│       └── 09_book_transition_video_prompt_writer.md
│
├── visual_presets/
│   └── 001_home_world/
│       ├── README.md
│       ├── source/
│       │   ├── supplied reference sheets
│       ├── character_sheet.png
│       └── any Gemini-only canonical image assets if required
│
├── book_templates/
│   ├── CATALOG.json
│   ├── 001/
│   ├── 002/
│   └── 003/
│
└── world_styles/
    └── CATALOG.json


Do NOT create a Flow style-sheet asset.

Flow uses character_sheet.png only.


======================================================================
47. SOURCE IMAGE INGEST
======================================================================

If the four supplied images are available to the coding agent:

preserve original files under:

projects/question_harvest/visual_presets/001_home_world/source/


Do not overwrite them.


Record SHA256.


Create the canonical operational:

character_sheet.png


from the supplied character-reference material as needed.


Do not invent a replacement character.


If source images are unavailable in the coding environment:

implement infrastructure

create paths/checklist

but mark canonical asset setup incomplete.


Do not commit fake canonical placeholders.


======================================================================
48. CONTENT PROJECT PROFILE
======================================================================

Extend project architecture with a pipeline profile rather than scattering
Question Harvest conditionals throughout the repository.


Conceptually:

pipeline_profile:
bookworld_mixed_media


Default project:

legacy/default behavior


world_behind_the_question:

preserve current behavior


question_harvest:

bookworld_mixed_media


Backward compatibility required.


======================================================================
49. QUESTION HARVEST PROJECT CONFIG
======================================================================

Use a schema similar to:

{
  "schema_version": 2,

  "project_id": "question_harvest",

  "display_name": "Question Harvest",

  "pipeline_profile": "bookworld_mixed_media",

  "providers": {
    "text": {
      "provider": "chatgpt",
      "allow_fallback": false
    },

    "image": {
      "provider": "gemini",
      "allow_fallback": false,
      "default_model": "nano_banana_pro"
    },

    "video": {
      "provider": "flow",
      "allow_fallback": false,
      "default_model": "gemini_omni_1_1_flash"
    },

    "voice": {
      "provider": "elevenlabs_web",
      "allow_fallback": false
    }
  },

  "defaults": {
    "format": "short",
    "aspect_ratio": "9:16",
    "duration_min_seconds": 40,
    "duration_max_seconds": 60,
    "subtitles": false,
    "hero_presence_mode": "auto",
    "world_style_policy": "auto",

    "gemini_image_model": "nano_banana_pro",

    "flow_video_model": "gemini_omni_1_1_flash",
    "flow_resolution": "720p",
    "opening_a_source_seconds": 6,
    "opening_b_source_seconds": 4
  }
}


Adjust schema to repository conventions.

Semantics must remain.


======================================================================
50. STRUCTURED CREATIVE ARTIFACTS
======================================================================

For the new profile prefer validated structured artifacts.


Suggested:

creative/SCRIPT_PLAN.json

creative/EPISODE_PLAN.json

creative/WORLD_STYLE_PLAN.json

creative/VISUAL_PLAN.json

creative/OPENING_PLAN.json


Use JSON schema/dataclasses/Pydantic.


Allow harmless Markdown code fences from ChatGPT to be stripped before parsing.


Invalid output:

bounded correction retry.


No infinite model retry loops.


======================================================================
51. SCRIPT STRUCTURE
======================================================================

Final narration remains one continuous narration.


Internally store segments:

opening_question_spark

book_transition

body

optional_closing


The first segment targets:

~5 sec


Second:

~3 sec


Body:

remaining narration.


Script writer must:

hook from second zero

connect hook to physical opener activity

avoid generic repeated intros

preserve factual accuracy

avoid fabricated sources/statistics

avoid padding

make book transition natural


======================================================================
52. RETENTION EDITOR
======================================================================

The retention editor must NOT destroy planned visual logic.


It may sharpen:

hook

curiosity

compression

payoff


But must preserve:

opening action compatibility

book retrieval

book-transition timing

factual integrity


======================================================================
53. EPISODE DIRECTOR
======================================================================

Inputs:

topic

creative brief

final script

brand rules

recent Question Harvest history


Select:

opening activity

opening location

curiosity trigger

trigger object

reaction

book retrieval

camera pattern

book template

hero presence

closing mode


Output validated structured JSON.


======================================================================
54. WORLD STYLE DIRECTOR
======================================================================

Inputs:

topic

script

episode plan

style catalog

recent project styles


Output:

style id

reuse/new decision

medium

texture

palette

line treatment

lighting

subject constraints

historical/conceptual constraints

hero rendering treatment

negative constraints


======================================================================
55. BODY VISUAL BEAT PLANNER
======================================================================

The first approximately 8 seconds are Flow video.

Do NOT count them as still-image beats.


Beat planning must use BODY narration duration.


For a 40–60 second Short:

usually a reasonable body still count might fall around 8–15 images depending
on narration density.


Do not force one image every 3.5 seconds if it harms storytelling.


WORLD_KEYFRAME may serve as first body image.


======================================================================
56. VISUAL PROMPT RULES
======================================================================

Every Gemini body prompt should specify:

one standalone image

aspect ratio

world medium

world texture

composition

narrative moment

reference hierarchy

character identity if present

no unwanted readable text

no UI

no grid

no random panels

no farm style leakage unless deliberately relevant

continuity with previous image only as short-range support


Canonical character reference always beats previous-frame drift.


======================================================================
57. FULL QUESTION HARVEST STAGE ORDER
======================================================================

Preferred stage sequence:

preflight

workspace initialization

creative brief

script draft

retention edit

episode direction

world style selection

world style generation if needed

body visual plan

world keyframe prompt

Gemini world keyframe

book spread composition

Flow Clip A prompt

Flow Clip A

Flow Clip B prompt

Flow Clip B

Gemini body-image prompts

Gemini body images

ElevenLabs narration

STT/alignment

opening clip trim

background music

mixed-media timeline

render

audio polish where currently used

QC

publish/Telegram if configured

Git artifact publication


Every expensive stage must be resumable.


======================================================================
58. VIDEO WORKSPACE STRUCTURE
======================================================================

Use approximately:

videos/<id>_<slug>/
├── PROJECT.md
├── BRIEF.md
├── SCRIPT_DRAFT.md
├── SCRIPT_FINAL.md
│
├── creative/
│   ├── SCRIPT_PLAN.json
│   ├── EPISODE_PLAN.json
│   ├── WORLD_STYLE_PLAN.json
│   ├── VISUAL_PLAN.json
│   └── OPENING_PLAN.json
│
├── references/
│   ├── world_style_anchor.png
│   ├── world_keyframe.png
│   └── book_spread_frame.png
│
├── assets/
│   ├── opening/
│   │   ├── question_spark_source.mp4
│   │   ├── question_spark_trimmed.mp4
│   │   ├── book_transition_source.mp4
│   │   └── book_transition_trimmed.mp4
│   ├── raw_beats/
│   ├── audio/
│   ├── music/
│   └── renders/
│
├── beats/
├── voiceover/
├── timing/
├── timeline/
├── render/
└── pipeline/
    └── provider_receipts/


Improve names if current repository conventions justify it.


======================================================================
59. LAUNCH REQUEST MUST FREEZE SETTINGS
======================================================================

Persist selected settings immediately.


LAUNCH_REQUEST.json should contain conceptually:

{
  "content_project": "question_harvest",

  "providers": {
    "text": "chatgpt",
    "image": "gemini",
    "video": "flow",
    "voice": "elevenlabs_web"
  },

  "image_generation": {
    "model": "nano_banana_pro",
    "quality": "best"
  },

  "video_generation": {
    "model": "gemini_omni_1_1_flash",
    "resolution": "720p",
    "opening_a_source_seconds": 6,
    "opening_b_source_seconds": 4,
    "flow_style_sheet_upload": false,
    "flow_character_sheet_upload": true
  }
}


Resume uses this immutable launch configuration.


Do not use newly changed panel defaults during a resumed run.


======================================================================
60. PROVIDER LOCK VALIDATION
======================================================================

Question Harvest launch must reject:

image provider != gemini


Question Harvest launch must reject:

video provider != flow


These provider controls should normally be read-only in the panel.


======================================================================
61. FLOW STYLE-SHEET SAFETY VALIDATION
======================================================================

Add code-level validation preventing accidental Flow style-sheet upload.


The Flow job builder should explicitly reject reference roles such as:

style

style_sheet

home_style

world_style

mood_board


Flow canonical reference role allowed:

character_sheet


Frame-input roles separately allowed:

first_frame

last_frame


Add tests proving this.


======================================================================
62. CONTROL PANEL
======================================================================

Improve the existing panel.


Basic fields:

Content Project

Topic

Format

Minimum duration

Maximum duration

Aspect ratio

Working title

Audience

Narrative angle

Must include

Must avoid

Source notes

Voice

ElevenLabs model

Speed

Stability

Similarity

Voice style

Music provider

Show subtitles


Advanced Question Harvest fields:

Hero presence

World style mode

World style hint


Generation Engines section:

Text:
ChatGPT / Ordak
LOCKED


Images:
Gemini / Ordak
LOCKED


Gemini Image Model:
Nano Banana Pro
Nano Banana 2


Videos:
Google Flow / Ordak
LOCKED


Flow Video Model:
Gemini Omni 1.1 Flash
other verified current Flow models


Flow Resolution:
720p
360p Draft where supported


Clip A source duration

Clip B source duration


Opening video:
enabled by default


======================================================================
63. FLOW REFERENCE DISPLAY IN PANEL
======================================================================

The panel should communicate:

Flow character reference:
Enabled / required


Flow style sheet:
Disabled by project design


Do not expose a checkbox that turns Flow style-sheet upload on.


This is a fixed project rule, not an end-user preference.


======================================================================
64. PROJECT DEFAULTS
======================================================================

When selecting Question Harvest in the panel:

Format:
Short


Duration:
40–60 sec


Aspect:
9:16


Subtitles:
Off


Hero:
Auto


World style:
Auto


Gemini:
Nano Banana Pro


Flow:
Gemini Omni 1.1 Flash


Flow resolution:
720p


Clip A:
6 sec source


Clip B:
4 sec source


======================================================================
65. PRE-LAUNCH HEALTH VALIDATION
======================================================================

Before starting a Question Harvest job validate:

Git/repository state suitable

disk space

Ordak API

Chrome

DevTools

ChatGPT logged in

Gemini logged in

Flow logged in

ElevenLabs usable

selected Gemini model available

selected Flow model available

selected Flow duration compatible

selected Flow aspect compatible

selected Flow frame features compatible


Fail early with useful error.


======================================================================
66. ELEVENLABS
======================================================================

Preserve current browser-based ElevenLabs automation.


No API.


Use one continuous final narration.


VOICEOVER_INPUT must contain only narration.


Do not include metadata headings.


======================================================================
67. ALIGNMENT AND VIDEO TRIMMING
======================================================================

After ElevenLabs and STT alignment:

identify real spoken time of:

opening_question_spark

book_transition


Trim Flow sources accordingly.


Prefer trimming over playback-speed distortion.


If narration exceeds available video source materially:

fail creative/timing QC or regenerate/replan the clip.

Do not aggressively stretch Flow video.


======================================================================
68. FLOW SOURCE AUDIO
======================================================================

If Flow video contains audio:

record its existence

but mute/strip it for Question Harvest final render by default.


Final audio source:

ElevenLabs narration

+

background music


======================================================================
69. MIXED-MEDIA TIMELINE
======================================================================

Generalize timeline entries.


Support:

media_type = video

media_type = image


Video example:

{
  "media_type": "video",
  "source": "assets/opening/question_spark_trimmed.mp4"
}


Image example:

{
  "media_type": "image",
  "source": "assets/raw_beats/beat_004.png"
}


Legacy entries with no media_type must preserve old image behavior.


======================================================================
70. RENDERER
======================================================================

Extend FFmpeg rendering for mixed media.


Normalize:

dimensions

SAR

pixel format

frame rate


Strip Flow source audio.


Timeline:

Clip A

Clip B

world/body images


Mix:

ElevenLabs

background music


Optional:

subtitles


======================================================================
71. SUBTITLE DEFAULT
======================================================================

Question Harvest:

subtitles OFF by default.


Panel exposes:

Show subtitles


Default unchecked.


Do not globally change legacy behavior.


======================================================================
72. BACKGROUND MUSIC
======================================================================

Preserve current Mixkit/Pixabay browser workflow where operational.


Music selection may consider:

topic

world style

mood

narrative energy


Do not overpower narration.


======================================================================
73. CURRENT REPOSITORY FORENSIC WARNING
======================================================================

Before modifying code:

FETCH.


Inspect:

pwd

git status --porcelain=v2 --branch

git remote -v

git branch -vv

git fetch origin

git rev-parse HEAD

git rev-parse origin/ordak

git diff

git diff --staged

git log --oneline --decorate -20

git submodule status --recursive

git ls-files -s services/ordak


Inside services/ordak:

git status --porcelain=v2 --branch

git remote -v

git branch -vv

git log --oneline --decorate -20

git diff

git diff --staged


======================================================================
74. DO NOT DESTROY SERVER-LOCAL WORK
======================================================================

Known evidence shows videos 008/009 were produced using pipeline behavior not
fully reflected in the previously observed GitHub script blobs.


Evidence includes:

--creative-brief

FULL_PIPELINE_RUNTIME_STATE schema v5

visual-pipeline state v7

world_design stage


Therefore production server may contain uncommitted improvements.


Do NOT start with:

git reset --hard

git clean


Backup local differences first.


Suggested backup:

/root/yt-pipeline-backups/<timestamp>/


Save:

git diff

git diff --staged

modified source files

manifest


Reconcile useful features into Git.


======================================================================
75. RECORD SOURCE SHAS
======================================================================

Before modification record current Git blob SHAs for important parent files:

scripts/content_projects.py

scripts/run_visual_pipeline.py

scripts/run_full_video_pipeline.py

scripts/video_control_panel.py

scripts/build_timeline.py

scripts/render_video.py

scripts/run_completion_pipeline.py

scripts/run_elevenlabs_voiceover.py

scripts/run_pixabay_music.py

scripts/run_ordak.py

.env.example

.gitignore

deployment service files


And Ordak:

app/schemas.py

app/config.py

app/job_manager.py

app/main.py

app/providers/*

app/automation/gemini_worker.py

app/automation/existing_chrome.py

tests


======================================================================
76. GIT REPRODUCIBILITY
======================================================================

All production-required source must end in Git.


Do not leave:

Gemini fixes

Flow automation

provider selectors

panel changes

deployment changes


only on server disk.


If Ordak changes:

commit/push Ordak first.


Then update parent submodule pointer.


Then commit/push parent ordak.


======================================================================
77. CROSS-PROJECT ISOLATION
======================================================================

Validate project membership on reuse.


A Question Harvest video may not reuse:

default visual report

world_behind visual report


Resume must validate:

PROJECT.md

content_project

pipeline profile

relevant config hashes

provider config

model selections


Fix existing reuse holes if encountered.


======================================================================
78. EXPENSIVE STAGE RESUME
======================================================================

If completed and valid:

world style anchor:
reuse


world keyframe:
reuse


book spread:
reuse


Flow A:
reuse


Flow B:
reuse


Gemini beat image:
reuse


Do not regenerate on restart.


======================================================================
79. MODEL IMMUTABILITY DURING RUN
======================================================================

After launch:

Gemini model setting is frozen.

Flow model setting is frozen.


If user later changes defaults:

running/resumed video retains original settings.


Changing a started video's models requires explicit force/regeneration.


Do not silently mix models.


======================================================================
80. PROVIDER LIMIT HANDLING
======================================================================

Gemini limits:

if reset time is explicitly visible:

persist pause state

schedule durable resume

use small safety buffer


If reset time unclear:

pause manual.


No provider fallback.


Flow credit exhaustion:

persist:

PAUSED_CREDITS


Do not hammer Generate.


No provider fallback.


======================================================================
81. PIPELINE STATE MACHINE
======================================================================

Use structured states including:

PENDING

RUNNING

DONE

PAUSED_LOGIN_REQUIRED

PAUSED_MANUAL_VERIFICATION

PAUSED_PROVIDER_LIMIT

PAUSED_CREDITS

FAILED_MODEL_SELECTION

FAILED_MODEL_COMPATIBILITY

FAILED_UPLOAD

FAILED_UI_CHANGED

FAILED_DOWNLOAD

FAILED_VALIDATION


Persist state after every meaningful transition.


======================================================================
82. SERVER DEPLOYMENT
======================================================================

Provision/verify only what is needed.


Likely:

Git

Python 3.11+

venv

pip

Chrome

FFmpeg

ffprobe

nginx

apache2-utils

Xvfb

fluxbox

x11vnc

noVNC

websockify

pipeline Python requirements

Ordak requirements

alignment requirements

systemd


Create idempotent provisioning if practical.


======================================================================
83. CHROME ARCHITECTURE
======================================================================

Use a persistent authenticated Chrome profile.


Same browser profile is used for:

ChatGPT

Gemini

Flow

ElevenLabs

music sites


Keep:

remote debugging:

127.0.0.1:9222


Never expose DevTools publicly.


======================================================================
84. VNC / NGINX PORTS
======================================================================

Required public noVNC port:

4143


Required control-panel public port:

4144


Internal loopback:

5901 x11vnc

6080 noVNC/websockify

4142 panel backend

8000 Ordak API

9222 Chrome DevTools


Resolve existing port conflict.


======================================================================
85. NGINX BASIC AUTH
======================================================================

Protect both public web surfaces.


VNC htpasswd:

/etc/nginx/.htpasswd-ordak-vnc


Panel htpasswd:

/etc/nginx/.htpasswd-video-panel


Do not commit credentials.


If credentials do not exist:

generate strong ones.


Store locally:

/root/.config/yt-video-pipeline/access-credentials.txt


chmod 600.


Validate:

no auth → 401

valid auth → works


Verify noVNC websocket proxy.


======================================================================
86. HTTPS
======================================================================

If server already has a configured domain/certificate:

use HTTPS cleanly.


If not:

do not invent DNS.


Still deploy Basic Auth.


Document that HTTP Basic Auth without TLS does not encrypt credentials and
recommend private network/VPN/HTTPS.


======================================================================
87. SYSTEMD
======================================================================

Review/harden:

ordak-xvfb

ordak-fluxbox

ordak-chrome

ordak-x11vnc

ordak-novnc

ordak-api

ordak-watchdog

video-control-panel


Requirements:

restart reliability

correct dependency order

persistent Chrome profile

correct DISPLAY

loopback bindings

proxy env preserved if currently necessary

enabled after reboot

useful journals


======================================================================
88. WATCHDOG
======================================================================

Chrome watchdog should:

detect dead Chrome

restart only when necessary

preserve profile

avoid tight loops

avoid killing healthy active provider generation unless unavoidable


A selector failure alone must not immediately restart Chrome.


Provider reconciliation comes first.


======================================================================
89. ROOT ENV AUTHORITY
======================================================================

Root .env remains authoritative.


Do not require:

services/ordak/.env


Extend root `.env.example` for new configuration.


Examples:

YT_ORDAK_GEMINI_URL

YT_ORDAK_GEMINI_RESPONSE_TIMEOUT_MS

YT_ORDAK_FLOW_URL

YT_ORDAK_FLOW_RESPONSE_TIMEOUT_MS

YT_QUESTION_HARVEST_DEFAULT_GEMINI_MODEL

YT_QUESTION_HARVEST_DEFAULT_FLOW_MODEL

YT_QUESTION_HARVEST_FLOW_RESOLUTION

YT_VNC_PUBLIC_PORT

YT_CONTROL_PANEL_PUBLIC_PORT


Do not include secrets in `.env.example`.


======================================================================
90. ORDAK DIAGNOSTICS
======================================================================

Expose:

Chrome state

DevTools state

active job

queue depth


ChatGPT:

login

tabs

busy

last success

last error


Gemini:

login

tabs

selected model if detectable

busy

last success

last error


Flow:

login

tabs/workspace

selected model if detectable

busy/generating

last success

last error


======================================================================
91. BROWSER AUTOMATION QUALITY
======================================================================

This is a hard production requirement.


For every important UI action use:

semantic/accessible selectors

multiple provider-local fallbacks

visibility checks

post-action state verification

bounded retry

screenshots on failure

useful diagnostics


Do not depend on a single brittle class name.


======================================================================
92. STATE-BASED WAITS
======================================================================

Do not use long fixed sleeps as completion logic.


Observe:

progress indicator

enabled/disabled controls

media card

download controls

stable result

provider errors


Short sleeps between interactions are acceptable.


Completion must be state-based.


======================================================================
93. TESTS — PROVIDER LOCK
======================================================================

Mandatory tests:

Question Harvest image provider == Gemini


Question Harvest video provider == Flow


Attempt:

image provider ChatGPT

→ reject


Attempt:

video provider Gemini

→ reject


Gemini failure:

must not invoke ChatGPT Image


Flow failure:

must not invoke another video provider


======================================================================
94. TESTS — FLOW REFERENCE POLICY
======================================================================

Mandatory tests:

Clip A Flow reference builder includes:

character_sheet


and excludes:

style_sheet

home_style

world_style

book_style


Clip B Flow inputs may contain:

character_sheet

first_frame

last_frame


but MUST exclude all style-sheet reference roles.


Any accidental Flow style-sheet reference should fail validation before upload.


======================================================================
95. TESTS — MODEL LOCK
======================================================================

requested:

nano_banana_pro


only NB2 available

→ fail / wait for Pro path


requested:

gemini_omni_1_1_flash


actual:

Veo model

→ reject


requested:

720p


actual:

360p

→ reject


unsupported Flow model + frame mode:

→ reject before Generate


======================================================================
96. UNIT TESTS
======================================================================

Add tests for:

project routing

backward compatibility

Question Harvest config

structured creative artifacts

anti-repetition

world-style selection

book compositor

Gemini reference ordering

Flow reference policy

Flow provider typing

unknown provider rejection

model normalization

model verification

model compatibility

mixed-media timeline

legacy image timeline

subtitle project default

cross-project artifact prevention

provider receipts


======================================================================
97. MEDIA INTEGRATION TESTS
======================================================================

Using local synthetic test media:

test legacy image render

test video + video + image render

test portrait output

test Flow source audio stripping

test subtitles OFF

test subtitles ON

test FFmpeg transitions

test invalid MP4 rejection


======================================================================
98. REAL GEMINI ACCEPTANCE
======================================================================

Using the actual authenticated server browser:

perform at least one real Gemini image generation.


Test:

model selection

multiple references

result detection

download

validation


For Nano Banana Pro:

the test only passes if final accepted image is verified as the Pro result.


Do not count initial Nano Banana 2 as passing Pro.


======================================================================
99. REAL FLOW ACCEPTANCE
======================================================================

Using real authenticated Google Flow:

test Clip A:

9:16

character sheet as the ONLY canonical reference sheet

NO style sheet

default selected Flow model

duration selection

resolution selection

download

ffprobe


Test Clip B:

character sheet only as canonical reference

first frame = book spread

last frame = world keyframe

NO style sheet

generate

download

ffprobe


Do not publish smoke clips.


======================================================================
100. FLOW STYLE-SHEET MANUAL INSPECTION
======================================================================

During real Flow acceptance:

capture/log the upload list before Generate.


Confirm visibly/logically:

character sheet exists


No style sheet exists.


This acceptance evidence is mandatory.


======================================================================
101. END-TO-END SMOKE TEST
======================================================================

Create a non-production smoke workspace.


Demonstrate:

ChatGPT planning

Gemini world style/keyframe

book spread compositor

Flow Clip A

Flow Clip B

Gemini body images

ElevenLabs narration

alignment

music

mixed-media render

subtitles off

QC


Do not publish as a channel video.


Do not unnecessarily consume a production video ID.


======================================================================
102. RESTART TESTS
======================================================================

Verify:

service restart

Ordak restart

Chrome rebind

control-panel restart

VNC restart


Confirm:

valid Gemini artifact reused

valid Flow A reused

valid Flow B reused

partial body generation resumes


Do not spend additional Flow credits solely to simulate duplicate generation.


Use mocked/integration tests for expensive duplicate scenarios.


======================================================================
103. FULL STACK HEALTH SCRIPT
======================================================================

Create something like:

scripts/check_full_stack.py


Checks:

Git branch

Git status

submodule pointer

disk space

FFmpeg

Chrome

DevTools

Ordak API

ChatGPT login

Gemini login

Flow login

ElevenLabs reachability/state where practical

VNC

control panel

systemd


Also report Question Harvest configuration:

image provider = Gemini

video provider = Flow

Flow style sheet upload = DISABLED

Flow character reference = ENABLED


======================================================================
104. DOCUMENTATION
======================================================================

Create/update:

docs/QUESTION_HARVEST_PIPELINE.md

docs/ORDAK_GEMINI_BROWSER_AUTOMATION.md

docs/ORDAK_FLOW_BROWSER_AUTOMATION.md

docs/SERVER_DEPLOYMENT.md

docs/RECOVERY_RUNBOOK.md

docs/VIDEO_CONTROL_PANEL.md


Document in bold/unambiguous language:

QUESTION HARVEST IMAGES ARE GEMINI ONLY.

QUESTION HARVEST VIDEOS ARE GOOGLE FLOW ONLY.

FLOW RECEIVES NO STYLE SHEET.

FLOW CANONICAL REFERENCE SHEET = CHARACTER SHEET ONLY.

BOOK_SPREAD and WORLD_KEYFRAME are scene frame inputs, not style sheets.

NO PROVIDER FALLBACK.


======================================================================
105. GITIGNORE / MEDIA POLICY
======================================================================

Preserve current repository philosophy:

large generated production media ignored

durable engineering artifacts tracked

canonical project references tracked


Track:

project config

prompts

character source sheets

canonical character sheet

book templates

reusable world style anchors

JSON plans

provider receipts

QC

runtime engineering metadata


Do not accidentally commit:

rendered production MP4s

temporary downloads

browser data

credentials

.env

cookies


======================================================================
106. PROJECT VIDEO REGISTRY
======================================================================

Question Harvest production videos should automatically update:

projects/question_harvest/VIDEOS.json


after successful production/finalization at the correct stage.


PROJECT.md remains explicit membership evidence.


Smoke tests must not register as real production videos.


======================================================================
107. CURRENT 300-SECOND LIMIT
======================================================================

Question Harvest MVP target is Short.


Do not overbuild full long-form now.


But avoid new architectural assumptions that permanently require <=300 sec.


If adjusting generic duration validation:

make it project/profile-aware.


Do not simply increase 300 to 3600 while retaining an impossible thousand-beat
architecture.


Document later long-form direction:

chapter-based script

chunked TTS

batched visual planning

lower still-image cadence

chapter styles

chapter timelines


======================================================================
108. OPERATIONAL SECURITY
======================================================================

Never expose publicly:

9222

8000

6080

5901

4142


Only authenticated nginx surfaces:

4143 VNC

4144 panel


Do not log:

cookies

passwords

session tokens

.htpasswd contents


======================================================================
109. IMPLEMENTATION PRIORITY
======================================================================

Execute in this order:

PHASE 0

fetch and inspect repository/server state


PHASE 1

protect and reconcile local uncommitted production changes


PHASE 2

make parent and Ordak source reproducible


PHASE 3

re-enable and harden Gemini image automation


PHASE 4

implement strict Gemini model selection and receipts


PHASE 5

implement Flow as explicit Ordak provider


PHASE 6

implement strict Flow model/duration/aspect/resolution selection


PHASE 7

implement the strict Flow character-sheet-only reference policy


PHASE 8

create Question Harvest project


PHASE 9

implement script/director/style/keyframe/book workflow


PHASE 10

implement mixed-media timeline/render


PHASE 11

improve Control Panel


PHASE 12

deploy VNC 4143 / panel 4144 / nginx / systemd


PHASE 13

unit/integration tests


PHASE 14

real Gemini test


PHASE 15

real Flow tests


PHASE 16

full smoke render


PHASE 17

restart/resume validation


PHASE 18

commit/push Ordak


PHASE 19

update/push parent submodule pointer and parent branch


======================================================================
110. COMMIT STRATEGY
======================================================================

Prefer coherent commits such as:

Reconcile production pipeline changes

Harden Gemini browser image generation

Add strict Gemini model selection

Add Google Flow video provider to Ordak

Add Flow model and media artifact support

Enforce character-only Flow reference policy

Add Question Harvest content project

Add book-world creative pipeline

Add mixed-media rendering

Expand video control panel

Harden remote server deployment and VNC

Add recovery tests and documentation


Do not create meaningless micro-commits.


======================================================================
111. DEFINITION OF DONE — GIT
======================================================================

Done requires:

current origin/ordak fetched

starting SHA recorded

no useful local work destroyed

server-local changes reconciled

Ordak changes reproducibly pushed

parent submodule pointer updated

parent ordak branch pushed

working tree clean except intentional runtime files

no secrets committed


======================================================================
112. DEFINITION OF DONE — GEMINI
======================================================================

Done requires:

Gemini is exclusive image provider

provider lock tests pass

model selector works

requested model verified

Nano Banana Pro path works when selected

multiple references work

downloads reliable

result validation works

resume works

limits handled

real browser test passes


======================================================================
113. DEFINITION OF DONE — FLOW
======================================================================

Done requires:

Flow is exclusive video provider

FlowAdapter exists

video_generate job exists

output_videos exists

model selection works

model verification works

aspect selection works

duration selection works

resolution selection works

first/end frames work

downloads work

ffprobe validation works

credit-safe reconciliation exists

real Clip A test passes

real Clip B test passes


AND MOST IMPORTANTLY:

NO STYLE SHEET IS SENT TO FLOW.


Clip A canonical reference:

character sheet only.


Clip B canonical reference:

character sheet only,

plus job-specific first/end frames.


======================================================================
114. DEFINITION OF DONE — QUESTION HARVEST
======================================================================

Done requires:

project registered

canonical supplied character assets integrated

brand rules documented

anti-repetition exists

episode director exists

world style system exists

world keyframe exists

book compositor exists

Flow opener A exists

Flow opener B exists

Gemini body generation exists

hero presence modes exist

project isolation verified


======================================================================
115. DEFINITION OF DONE — PIPELINE
======================================================================

Done requires:

ChatGPT planning

Gemini imagery

Flow opening videos

ElevenLabs voice

STT alignment

music

mixed-media timeline

FFmpeg final render

QC

subtitle OFF default

resume behavior

Git artifact publication


======================================================================
116. DEFINITION OF DONE — DEPLOYMENT
======================================================================

Done requires:

VNC on 4143

nginx auth

Control Panel on 4144

nginx auth

internal services loopback only

systemd enabled

Chrome persistent profile

provider logins detectable

service restart tested

health script passes


======================================================================
117. FINAL REPORT
======================================================================

At completion provide:

starting parent HEAD

final parent HEAD

starting Ordak SHA

final Ordak SHA

recovered server-local changes

major source files changed

Question Harvest project structure

canonical asset status

Gemini implementation summary

Gemini default/requested model

real Gemini actual verified model

Flow implementation summary

Flow default/requested model

real Flow actual verified model

Flow resolution

Flow duration

Flow aspect


Explicitly report:

Flow Clip A uploaded canonical reference sheets:
<list>

Expected:
character sheet only


Flow Clip B uploaded canonical reference sheets:
<list>

Expected:
character sheet only


Flow style sheets uploaded:

Expected:
NONE


Also report:

book first-frame usage

world-keyframe end-frame usage

ElevenLabs status

music status

mixed-media smoke render

VNC port

Control Panel port

credentials file LOCATION

systemd service statuses

tests and results

remaining manual actions

exact command/process for launching first real Question Harvest Short


======================================================================
118. AUTONOMOUS DECISION POLICY
======================================================================

Make reasonable implementation decisions autonomously.


Optimize for:

1. reliability
2. correctness
3. provider consistency
4. model correctness
5. resumability
6. visual continuity
7. project isolation
8. reproducibility
9. operational simplicity
10. future extensibility


Do not ask the user for minor naming or implementation details.


Ask only when blocked by:

missing authentication

missing Git permission

missing canonical images required for production validation

irreversible destructive migration

major product decision not covered here


======================================================================
119. ABSOLUTE RULES TO REMEMBER
======================================================================

Images:

GEMINI ONLY.


Videos:

GOOGLE FLOW ONLY.


Flow persistent/canonical reference sheet:

CHARACTER SHEET ONLY.


Never send a style sheet to Flow.


Never send home style sheet to Flow.


Never send world style anchor to Flow.


Never send book style sheet to Flow.


BOOK_SPREAD_FRAME and WORLD_KEYFRAME are permitted because they are actual
scene-frame inputs for Clip B, not style reference sheets.


Gemini body imagery may use character and style references as required.


No provider fallback.


No model fallback.


No destructive Git reset before reconciliation.


No production completion claim without real browser smoke validation.


======================================================================
120. BEGIN NOW
======================================================================

Start with Phase 0 forensic inspection.

Fetch current origin/ordak.

Record all current SHAs.

Inspect parent and submodule local changes.

Protect server-local production code.

Reconcile source first.

Then implement the entire system in the priority order above.

Keep working autonomously until every acceptance gate that can be completed
without unavailable credentials or missing external account access is passed.

The highest priority is not merely that the pipeline works once.

The highest priority is that:

Gemini image automation,
Google Flow video automation,
browser recovery,
download recovery,
model selection,
model verification,
reference correctness,
resume behavior,
and server services

are stable enough for repeated unattended production use.
