# Prompt 04 — World Style Director (Question Harvest)

## Purpose
Select per-episode world visual style (one primary, optionally subtle secondary). Most diversity BETWEEN episodes.

## Inputs
- TOPIC: {{TOPIC}}
- FINAL SCRIPT: {{FINAL_SCRIPT}}
- EPISODE PLAN (JSON): {{EPISODE_PLAN}}
- STYLE CATALOG (JSON, available reusable styles): {{STYLE_CATALOG}}
- RECENT STYLES (JSON): {{RECENT_STYLES}}
- OPERATOR STYLE DIRECTIVE: {{STYLE_DIRECTIVE}}

## Available medium families (choose one primary)
woodcut, historical engraving, charcoal, ink wash, clay / stop-motion-like, paper cut, collage, fresco, manuscript illustration, retro educational illustration, blueprint, technical drawing, screen print, painted storybook, monochrome illustration, surreal conceptual collage

## Output — JSON ONLY (no markdown)
```json
{
  "style_id": "unique_slug e.g., charcoal_warm_001 or existing catalog id",
  "decision": "reuse|new",
  "reuse_of": "existing style_id or null if new",
  "medium": "chosen primary medium",
  "secondary_treatment": "optional subtle second medium or null",
  "texture_family": "paper grain|wood grain|smooth matte etc",
  "palette_summary": "muted natural with warm ochres, moss greens, etc",
  "line_treatment": "clean dark outlines / sketchy charcoal / crisp engraving etc",
  "lighting": "soft daylight|warm lamp|overcast etc",
  "subject_constraints": "what world vocabulary is allowed (e.g., medieval tools, cell diagrams)",
  "historical_accuracy_note": "if historical topic, constraints to stay accurate or null",
  "hero_rendering_in_world": "how protagonist should be drawn if he appears in world (e.g., same silhouette rendered in charcoal)",
  "negative_constraints": "no photorealism, no 3D CGI, no anime etc",
  "reason": "why this style fits topic and why reused or new, citing recent usage penalty"
}
```

## Rules
- The OPERATOR STYLE DIRECTIVE outranks every heuristic below. When it names a
  style_id you must answer `"decision": "reuse"` with that exact id in both
  `style_id` and `reuse_of`. When it forbids reuse you must answer `"new"`. When it
  gives a free-text steer, honour it while still choosing coherent values.
- One primary world style per Short; optionally subtle secondary; do NOT randomly mix media beat-by-beat.
- Score existing catalog vs topic affinity + recent usage (penalize overused texture_family, avoid same as last 2).
- If catalog empty or no good reuse, propose new with subject_affinities.
- Keep palette line treatment coherent.
- Ensure protagonist adaptation preserves hair silhouette + beard + overalls silhouette translated into this medium (face proportions/clothing identity per §45).

Return ONLY JSON.
