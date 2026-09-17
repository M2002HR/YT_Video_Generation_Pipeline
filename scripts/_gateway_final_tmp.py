# Final separation-of-concerns audit and direct cache regression.
P = 'scripts/run_q_station_pipeline.py'
write('projects/q_station/characters/red_horned_everyman/behavior.md', '''# Red Horned Everyman - Behavior

Restrained, grounded physical acting: subtle head turns, skeptical observation, dry/deadpan curiosity and small facial changes instead of slapstick. He wants to understand why something works. He is not constantly furious, villainous, supernatural, manic or hyperactive, and does not cast spells by default. Keep actions readable in a short video.

## Dynamic environment
Infer location and activity from the actual topic, script and his observant temperament. No permanent home, city, lair, occupation or infernal scenery. Do not force chores, a workshop, sorting objects, or a catchphrase into every question.

## Story agency
He may notice a specific contradiction, make a grounded prediction, try a simple comparison or recognize an unexpected consequence. A visibly shows why the question arises, in one place and no more than three clear actions. Calm acting can accompany a strong event.

The episode's resolved presentation owns its gateway, not this identity pack. Follow that presentation's exact attention cue, prop interaction, route and camera handoff; never substitute a different gateway because of the character's appearance or an accessory in his sheet. New runs use the impossible red door. A frozen historical presentation remains authoritative when an older episode is resumed. The mechanism is an editorial route to explanation, not scientific evidence or proof of supernatural powers.
''')
# Do not feed a development README listing book assets to every character's A writer.
edit(P, '''        preset_rules = (
            content_project.root / "visual_presets" / content_project.default_visual_preset / "README.md"
        ).read_text(encoding="utf-8")''', '''        preset_rules = (
            "Preserve the supplied character sheet's canonical visual identity and readable cartoon acting. "
            "Choose the opening setting from the question. The episode's resolved presentation alone owns "
            "the gateway and handoff. Development asset lists, other characters and topic-world framing "
            "are not opening-scene instructions."
        )''')
# Keep the non-character B style input neutral even when regenerating an old saved plan.
edit(P, '    presentation = (character or _coerce_character_context(content_project)).presentation\n    stage = f"flow_prompt_', '    presentation = (character or _coerce_character_context(content_project)).presentation\n    world_style_plan = visuals.topic_style(world_style_plan)\n    stage = f"flow_prompt_')
D = 'projects/q_station/prompts/pipeline/09_entry_transition_video_prompt_writer.md'
text = read(D)
text = text.replace('Write a continuous hand-drawn 2D shot that obeys ENTRY TRANSITION CONTRACT,', 'Write a controlled shot or the single matched viewpoint/dissolve explicitly allowed by ENTRY TRANSITION CONTRACT,')
text = text.replace('ownership cue already baked into the first frame when the profile requires it.', 'ownership cue or acting host already baked into the first frame when the profile requires it. For an acting-host doorway, visibly complete the threshold crossing before the camera arrival or any dissolve. The profile camera plan is binding; do not default every gateway to a lens push.')
write(D, text)

T = 'tests/test_gateway_visual_contracts.py'
write(T, read(T) + '''


def test_b_prompt_cache_reuses_identical_inputs_and_invalidates_camera_changes(environment):
    content, registry, run = environment
    red = registry.get("red_horned_everyman")
    save(run / "timing/OPENING_SOURCE_PLAN.json", {"clips": {"B": {"target_seconds": 6.2}}})
    spy = Spy()
    episode = {"entry_variant": "wrong_wall", "entry_camera": camera()}
    args = (spy, run, content, "B", "A factual clue accompanies the crossing.", episode,
            {"medium": "ink"}, "The host-free world", "topic", 8)
    first = pipeline.stage_flow_prompt(*args, character=red, require_source_contract=True)
    count = len(spy.prompts)
    assert pipeline.stage_flow_prompt(*args, character=red, require_source_contract=True) == first
    assert len(spy.prompts) == count
    episode["entry_camera"]["transition"] = "texture_takeover"
    updated = pipeline.stage_flow_prompt(*args, character=red, require_source_contract=True)
    assert len(spy.prompts) > count and "texture_takeover" in updated


def test_red_identity_behavior_does_not_assign_the_book(environment):
    _, registry, _ = environment
    behavior = registry.get("red_horned_everyman").behavior
    assert "His book is a fixed bridge" not in behavior
    assert "resolved presentation" in behavior


def test_visual_planner_has_no_entry_behavior_context(environment):
    content, registry, run = environment
    red = registry.get("red_horned_everyman")
    beat = {"beat_id": 1, "narration_slice": "A clear factual answer.", "visual_fingerprint": "distinct_subject", "hero_present": False}
    spy = Spy([{"beats": [beat]}])
    plan = {"opening_question_spark": "Why?", "entry_transition": "Gateway-only sentinel.",
            "body": [beat["narration_slice"]], "optional_closing": "", "cta": "Subscribe."}
    pipeline.stage_visual_plan(spy, run, content, plan, {"entry_camera": camera()}, {"medium": "ink"}, 20, red)
    prompt = spy.prompts[0][1]
    assert "Gateway-only sentinel" not in prompt
    assert "door_crossing_v1" not in prompt and "entry_camera" not in prompt
    assert "A clear factual answer." in prompt
''')
print('Final prompt isolation and cache regression added.')
