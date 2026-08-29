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
- Use ChatGPT for script writing, visual planning, and AI image generation.
- Build similar browser automation for **ElevenLabs** for voice generation, either integrated with ordak or closely connected to it.
- Use a structured pipeline so every narration segment maps to a visual beat.
- Prefer **visual beats** over a strict “one sentence = one image” rule.
- Test generating multiple scenes in one image as a **2x2 storyboard sheet**, then crop the four panels automatically.
- Keep prompts, project decisions, schemas, workflow notes, and later code in this repository so the project can continue across new ChatGPT conversations and other agents.

## Target pipeline

Topic
→ Script
→ Retention edit
→ Visual beats
→ Visual prompts
→ Storyboard/image generation
→ Crop/process images
→ ElevenLabs narration
→ Timing/alignment
→ Timeline
→ Subtitles / motion / audio
→ Render
→ Human QC
→ Final video

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

ordak currently provides local browser-backed automation for ChatGPT and Gemini using an existing authenticated Chrome session, including persisted jobs, retries, browser interaction, text extraction, and generated-image extraction.

## Current status

Repository initialized.

Next step: create **Video 001** and define its topic/angle before building the next project artifact.
