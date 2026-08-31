# Project-owned pipeline prompts

These templates began as a copy of the proven production baseline and are
intentionally independent from `projects/default`.

The project adds a dedicated episode-world stage:

1. script draft;
2. retention edit;
3. episode world design (`00_world_designer.md`);
4. visual-beat plan bound to that world;
5. one image prompt per beat bound to the same world and canonical anchors.

Channel-specific narration and opening contract:

- every script begins with an honest, topic-specific 6–10 second hook;
- the current image pipeline renders that hook as a coherent 2–3 beat still
  sequence, designed so a future runner can replace the block with one short
  generated video without changing narration timing;
- every script earns a topic payoff, then ends with one short spoken like-and-
  subscribe CTA; visuals close on the channel world without rendering UI text.

Edit only this directory for future channel-specific prompt changes. Changes
here must not alter legacy/default project behavior.
