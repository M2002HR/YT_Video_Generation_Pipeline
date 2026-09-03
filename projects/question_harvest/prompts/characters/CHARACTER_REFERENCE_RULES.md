# Character Reference Rules — Question Harvest

## Gemini Image Generation (§30 — style references ALLOWED)
If protagonist absent in beat:
1. current episode world style anchor
2. world keyframe
3. recurring world/location reference if needed
4. previous accepted body image (Beat N-1 continuity)
5. prompt

If protagonist present:
1. canonical character_sheet
2. current episode world style anchor
3. world keyframe
4. recurring world/location reference if needed
5. previous accepted body image
6. prompt

## Google Flow Video Generation (§12-16 — NO STYLE SHEET EVER)
- Clip A (question spark): character_sheet ONLY (§15) — zero style sheets, via flow_reference_policy.clip_a_roles()
- Clip B (book → world): character_sheet (optional if absent harms reliability, but still ONLY canonical) + first_frame (BOOK_SPREAD_FRAME.png) + last_frame (WORLD_KEYFRAME.png) — validated via clip_b_roles(). Never style_sheet, never book_anchor as style.

## Frame Inputs Are Not Style Sheets (§14)
BOOK_SPREAD_FRAME.png and WORLD_KEYFRAME.png are scene-specific image inputs defining actual transition, not reusable style anchors. They are allowed as first_frame / last_frame via Flow frame controls.

## Enforcement
- `scripts/flow_reference_policy.py:validate_flow_roles()` must be called before any Flow upload. Forbidden roles → immediate structured error.
- Gemini prompts must still carry character identity description even though sheet is uploaded (belt-and-suspenders).

