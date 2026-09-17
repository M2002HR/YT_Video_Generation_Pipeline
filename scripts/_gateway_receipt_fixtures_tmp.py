# Test unchanged current receipts and both historical/current red-host revision paths.
T = 'tests/test_resume_stages.py'
edit(T, 'Restarting a run must never regenerate what was already paid for', 'Restarting with unchanged, currently verified contracts must not regenerate paid media')
edit(T, '    from image_artifacts import CONTRACT_VERSION, request_fingerprint\n    payload = {', '''    from image_artifacts import CONTRACT_VERSION, request_fingerprint
    from gateway_contracts import enforce_review, requirements
    check = enforce_review({"passed": True, "description": "Temporary test fixture, not a production visual review.", "violations": [],
        "contract_checks": {key: {"passed": True, "evidence": "Current-contract test fixture."} for key in requirements(prompt)}}, prompt)
    payload = {''')
edit(T, '"requested_model": model, "quality_check": {"passed": True}', '"requested_model": model, "quality_check": check')
edit(T, '''    image_receipt(project, target, "a prompt")
    qstation.save_json(project/'references/world_keyframe_references.json',{'prompt_sha256':qstation.sha256_text('a prompt'),'hero_present':False})''', '''    effective_prompt = "a prompt\\n" + qstation.episode_frame_contract({})
    image_receipt(project, target, effective_prompt)
    qstation.save_json(project/'references/world_keyframe_references.json',{'prompt_sha256':qstation.sha256_text(effective_prompt),'hero_present':False})''')
write(T, read(T) + '''

def test_old_permissive_review_cannot_certify_a_new_full_bleed_request(runner, project):
    prompt = "A topic scene. " + qstation.episode_frame_contract({})
    target = _png(project / "references/world_keyframe.png")
    image_receipt(project, target, prompt)
    receipt_path = project / "pipeline/provider_receipts/gemini_world_keyframe.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["quality_check"] = {"passed": True, "observations": ["A page border is present."]}
    qstation.save_json(receipt_path, receipt)
    with pytest.raises(AssertionError, match="called chatgpt"):
        qstation.reusable_image(runner, project, "world_keyframe", target, receipt_path, prompt, "nano_banana_pro", [])
''')

T = 'tests/test_control_panel_api.py'
edit(T, 'def test_character_revision_archives_old_resolution_and_clears_resume_authority(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:', '''@pytest.mark.parametrize("old_profile_id", ["book_portal", "red_door_portal"])
def test_character_revision_archives_old_resolution_and_clears_resume_authority(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, old_profile_id: str) -> None:''')
edit(T, "    (creative / 'PRESENTATION_RESOLUTION.json').write_text(json.dumps(registry.get('red_horned_everyman').presentation.to_resolution()), encoding='utf-8')", '''    from presentation_runtime import load_presentation_profile
    old_profile = load_presentation_profile(ROOT / f'projects/q_station/presentation_profiles/{old_profile_id}/profile.json')
    (creative / 'PRESENTATION_RESOLUTION.json').write_text(json.dumps(old_profile.to_resolution()), encoding='utf-8')''')
edit(T, "    old_entry = project / 'references/book_cover_frame.png'", "    old_entry = old_profile.artifacts.path(project, 'entry_frame')")
edit(T, "(archived / 'references/book_cover_frame.png').read_bytes()", "(archived / old_entry.relative_to(project)).read_bytes()")
print('Receipt reuse retains zero provider calls only with current verified contracts; both old book and new door revisions are covered.')
