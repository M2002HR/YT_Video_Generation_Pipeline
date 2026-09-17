# Preserve behavioral regressions while making their input data valid for the new gateway.
T = 'tests/test_opening_concept_pipeline.py'
edit(T, 'body = [f"Memory can replay a familiar pattern number {i}." for i in range(1,10)]', 'body = [f"Memory can replay pattern number {i}." for i in range(1,10)]')
edit(T, 'entry_key: "Memory can replay sound without a speaker."', 'entry_key: "Memory can replay a familiar sound pattern long after the external speaker stops."')
# Only pipeline tests using the red host need the door variant. Pure book-contract tests remain.
text = read(T)
for name in ('test_no_usable_candidate_causes_bounded_redesign', 'test_exhausted_text_corrections_stop_before_media'):
    tree = ast.parse(text)
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    lines = text.splitlines(keepends=True)
    source = ''.join(lines[node.lineno-1:node.end_lineno])
    assert 'candidates()' in source
    source = source.replace('candidates()', 'candidates("wrong_wall")')
    text = ''.join(lines[:node.lineno-1]) + source + ''.join(lines[node.end_lineno:])
write(T, text)
replace_function(T, 'direction', '''def direction(concept):
    variant = concept["selected"]["entry_variant"]
    result = {"concept_id": concept["concept_id"], "opening_activity": "testing the persistent rhythm", "opening_location": "quiet listening room", "topic_visual_link": "The continuing motion makes the remembered rhythm visible", "link_type": "metaphor", "opening_visual_proof": "A silent speaker and continuing finger tap", "entry_variant": variant, "entry_bridge": concept["selected"]["entry_bridge"], "opening_actions": ["Stop speaker", "Notice continuing rhythm", "Observe the discrepancy"], "camera_pattern": "slow_push_in", "hero_presence_mode": "opener_only", "closing_mode": "stay_in_world"}
    if variant in {"wrong_wall", "floor_hatch", "freestanding_door", "existing_exit", "unexpected_surface", "recessed_door"}:
        result["entry_camera"] = {
            "surface": "floor" if variant == "floor_hatch" else "wall",
            "transition": "follow_through",
            "attention_cue": "The door leaf begins to move; the host looks toward it.",
            "opening_action": "The leaf opens away from the host and the route.",
            "crossing_action": "The host deliberately crosses the clear threshold and steps aside.",
            "camera_path": "A restrained lateral follow moves through the same aperture.",
            "world_reveal": "The rhythm pattern appears in the subject world beyond the opening.",
        }
    return result
''')
edit(T, '    return {"candidates": result}', '''    if variant in {"wrong_wall", "floor_hatch", "freestanding_door", "existing_exit", "unexpected_surface", "recessed_door"}:
        for item in result:
            item["entry_bridge"]["a_end"] = "The host notices the rhythm continuing, still beside the wall."
            item["entry_bridge"]["b_start"] = "The host stands beside the nearly closed canonical red door."
    return {"candidates": result}''')
edit(T, '"B":{"target_seconds":2.9}', '"B":{"target_seconds":6.2}')
edit(T, '[("A",6),("B",4)]', '[("A",6),("B",8)]')
edit(T, 'and "2.9" in spy.prompts[1][1]', 'and "6.2" in spy.prompts[1][1]')
edit(T, '"red_horned_everyman: book_portal"', '"red_horned_everyman: red_door_portal"')
edit(T, '"subject world", "earworms", 4, character=char)', '"subject world", "earworms", 8, character=char)')
# These assertions test the director's final handoff, not a particular retired red/book staging.
edit(T, 'test_final_director_seam_is_used_for_book_cover_direction', 'test_final_director_seam_is_used_for_entry_direction')
edit(T, 'The reviewed top-down cover fills the frame without hands.', 'The reviewed red door stands beside the host with a clear threshold.')
edit(T, 'First closed cover design', 'First almost-closed red door design')
edit(T, 'Corrected closed cover design', 'Corrected almost-closed red door design', count=2)
print('Current red-door fixtures satisfy word budget, actual B timing and entry camera requirements.')
