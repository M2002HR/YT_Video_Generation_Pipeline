# Content projects

A content project is a long-lived channel/brand universe. It owns its own pipeline prompts, visual presets, canonical characters, style anchors, and creative rules.

Individual videos intentionally remain under the stable repository-level `videos/` directory so the mature render/publish tooling is not broken by path migration. Membership is explicit through each video's `PROJECT.md`.

Resolution order:
1. `projects/<project_id>/prompts/pipeline/`
2. `projects/<project_id>/visual_presets/`
3. legacy root fallback only when the project explicitly allows it

Current projects:
- `default` — all videos created before this split
- `world_behind_the_question` — new general-curiosity brand; no videos yet
