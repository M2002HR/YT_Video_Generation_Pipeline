# Content projects

A content project owns its provider locks, prompts, characters, presentation formats, visual presets,
world-style catalog and publication defaults. Videos remain under repository-level `videos/` for
render/publish compatibility and identify membership through their launch/PROJECT metadata.

Prompt resolution is `projects/<project_id>/prompts/pipeline/` only unless a project explicitly enables
legacy fallback. The repository no longer carries duplicate root prompt copies.

Current canonical projects are `default`, `q_station`, and `world_behind_the_question`.
`projects/question_harvest` is a compatibility symlink to `q_station`, not a separate project.
