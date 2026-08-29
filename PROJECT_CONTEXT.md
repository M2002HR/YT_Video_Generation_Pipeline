# Project Context

## Goal

Build an automation-first pipeline for producing English faceless YouTube videos from a topic to a finished video.

The long-term system should be able to generate videos quickly and repeatedly using a fixed workflow, with as little manual work as practical.

## Current MVP

Start with **60-second English videos** so we can discover infrastructure problems, workflow bottlenecks, prompt issues, image consistency problems, timing issues, and editing tricks quickly.

After the workflow becomes reliable, extend it to longer videos, potentially up to ~30 minutes.

## Current approach

For the MVP:

- English content only.
- No official LLM/image APIs for now.
- Use **ordak** to automate the real ChatGPT/Gemini web interfaces through an already signed-in Chrome session.
- Use ChatGPT for script writing, visual planning, and image-generation prompts.
- The user currently generates and downloads storyboard images manually; the pipeline then processes those local assets.
- Build similar browser automation for **ElevenLabs** for voice generation, either integrated with ordak or closely connected to it.
- Use a structured pipeline so every narration segment maps to a visual beat.
- Prefer **visual beats** over a strict “one sentence = one image” rule.
- Generate multiple scenes in one image as a **2x2 storyboard sheet**, then crop the four quadrants automatically.
- Keep prompts, project decisions, workflow notes, and code in this repository so the project can continue across new ChatGPT conversations and other agents.

## Visual consistency strategy

Storyboard generation is **reference-driven**, not prompt-only.

Canonical visual references:
- a **style anchor** controls rendering style, palette, lighting language, texture, and detail level
- a **character anchor** controls protagonist identity: face, hair, outfit, body proportions, and age impression
- optional dedicated environment/memory anchors control recurring locations and flashbacks

For Sheet 02 and later, the previous storyboard sheet is also supplied for short-range continuity.

Reference priority is:

1. character anchor
2. style anchor
3. dedicated recurring environment/memory anchors
4. previous storyboard sheet
5. current scene prompt

The previous sheet must never become the only character reference because cumulative visual drift can occur.

## Target pipeline

Topic
→ Script
→ Retention edit
→ Visual beats
→ Storyboard prompts
→ Canonical visual references
→ Manual/automated storyboard generation
→ Save raw storyboard sheets locally
→ Crop/process images
→ ElevenLabs narration
→ Timing/alignment
→ Timeline
→ Subtitles / motion / audio
→ Render
→ Human QC
→ Final video

## Asset policy

Canonical reference images are versioned in Git because they are part of the reproducible visual specification.

Generated media is not committed:
- raw storyboard sheets
- cropped beat images
- audio
- renders

These are stored under each video's `assets/` directory and ignored by Git.

## MVP expectations

A typical 60-second video will likely contain roughly:

- 130–160 spoken English words
- ~15–22 visual beats
- several 2x2 storyboard sheets rather than one generation per scene
- lightweight motion on still images such as zoom/pan
- a short human QC pass before final export

These numbers are starting assumptions, not fixed rules. We will revise them based on real test videos.

## Important design principle

Do not overbuild the architecture before making real videos.

We will add files, prompts, code, schemas, and automation gradually as each need becomes concrete. The first priority is to complete real end-to-end test videos and turn what we learn into reusable project rules.

## External project

ordak:
https://github.com/AliBalash/ordak

ordak provides local browser-backed automation for ChatGPT and Gemini using an existing authenticated Chrome session, including persisted jobs, retries, browser interaction, text extraction, and generated-image extraction.

## Current status

Video 001 has:
- brief
- final script
- visual beats
- storyboard prompt writer
- sheet prompts
- reference-driven storyboard workflow

Current next step:
generate and approve the canonical style and character anchors, commit those reference images, then regenerate storyboard sheets using the reference workflow.
