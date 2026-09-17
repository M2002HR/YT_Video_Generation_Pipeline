"""One-shot, assertion-guarded integration. Removed before the validated commit."""
from pathlib import Path
import ast
import json
import re

ROOT = Path(__file__).resolve().parents[1]

def read(path):
    return (ROOT / path).read_text(encoding='utf-8')

def write(path, text):
    p = ROOT / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text.rstrip() + '\n', encoding='utf-8')

def edit(path, old, new, count=1):
    text = read(path)
    actual = text.count(old)
    if actual != count:
        raise RuntimeError(f'{path}: expected {count} occurrences, found {actual}: {old[:100]!r}')
    write(path, text.replace(old, new))

def replace_function(path, name, source, owner=None):
    text = read(path)
    tree = ast.parse(text)
    parent = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == owner) if owner else tree
    node = next(n for n in parent.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    lines = text.splitlines(keepends=True)
    write(path, ''.join(lines[:node.lineno-1]) + source.rstrip() + '\n' + ''.join(lines[node.end_lineno:]))

def json_edit(path, update):
    data = json.loads(read(path))
    update(data)
    write(path, json.dumps(data, indent=2, ensure_ascii=False))

P = 'scripts/run_q_station_pipeline.py'
R = 'scripts/presentation_runtime.py'

# Additive data contract; old profiles keep their defaults/version and artifact paths.
edit(R, 'import json\n', 'import json\nimport math\n')
edit(R, '    entry_variants: tuple[str, ...] = ()', '    entry_variants: tuple[str, ...] = ()\n    motion_contract: str = ""\n    min_entry_seconds: float = 0.0\n    min_entry_words: int = 0')
edit(R, '            "entry_variants": list(self.entry_variants),', '            "entry_variants": list(self.entry_variants),\n            "motion_contract": self.motion_contract,\n            "min_entry_seconds": self.min_entry_seconds,\n            "min_entry_words": self.min_entry_words,')
edit(R, 'if presence not in {"none", "ownership_cue"}:', 'if presence not in {"none", "ownership_cue", "acting_host"}:')
edit(R, '"entry_frame_character_presence must be \'none\' or \'ownership_cue\'."', '"entry_frame_character_presence must be none, ownership_cue or acting_host."')
edit(R, '    root = path.parent\n', '''    motion_contract = str(data.get("motion_contract") or "")
    if motion_contract not in {"", "door_crossing_v1"}:
        raise PresentationProfileError("Unknown entry motion contract.")
    try:
        seconds = float(data.get("min_entry_seconds", 0))
        words = int(data.get("min_entry_words", 0))
    except (TypeError, ValueError) as exc:
        raise PresentationProfileError("Invalid entry timing requirements.") from exc
    if not math.isfinite(seconds) or not 0 <= seconds <= 8 or not 0 <= words <= 22:
        raise PresentationProfileError("Entry timing requirements exceed supported bounds.")
    if motion_contract and (presence != "acting_host" or seconds < 5 or words < 13):
        raise PresentationProfileError("Door crossing needs acting_host, at least 5 seconds and 13 words.")
    root = path.parent
''')
edit(R, '        entry_variants=tuple(variants),', '        entry_variants=tuple(variants),\n        motion_contract=motion_contract,\n        min_entry_seconds=seconds,\n        min_entry_words=words,')
replace_function(R, '_profile_revision', '''def _profile_revision(path: Path) -> tuple:
    """Track each declarative input, including replacements preserving an old mtime."""
    result = []
    for candidate in sorted({path, *path.parent.rglob("*.md")}):
        if candidate.is_file():
            stat = candidate.stat()
            result.append((str(candidate), stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size))
    return tuple(result)
''')
edit(R, 'def _load_cached(path_string: str, mtime_ns: int)', 'def _load_cached(path_string: str, revision: tuple)')
edit(R, '            persisted = candidate if isinstance(candidate, dict) else {}\n            profile_id = str(persisted.get("profile_id") or "")\n        except (OSError, ValueError):\n            profile_id = ""', '''            if not isinstance(candidate, dict) or not candidate.get("profile_id"):
                raise ValueError("Missing saved profile_id")
            persisted = candidate
            profile_id = str(persisted["profile_id"])
        except (OSError, ValueError) as exc:
            raise PresentationProfileError(f"Invalid saved presentation {resolution}: {exc}") from exc''')

json_edit('projects/q_station/characters/red_horned_everyman/character.json', lambda d: d.update(presentation_profile='red_door_portal'))
json_edit('projects/q_station/characters/registry.json', lambda d: d['characters'].append({'id':'newton_scholar','config':'newton_scholar/character.json'}))
json_edit('projects/q_station/presentation_profiles/spyglass_portal/profile.json', lambda d: (d.update(entry_frame_character_presence='acting_host'), d['identity'].update(canonical_sheet='refs/spyglass_design_sheet_v2.png')))
write('projects/q_station/characters/red_horned_everyman/behavior.md', read('projects/q_station/characters/red_horned_everyman/behavior.md') + '''

## Question-first red-door entry
For new episodes, A establishes an actual topic-specific observation or contradiction with dry, restrained acting. No obligatory chores, catchphrase or infernal setting. B owns the impossible red door: he notices its movement or topic-textured opening, opens or watches it open, then deliberately crosses. Keep both horns clear of the lintel and a supported route through the threshold. A floor hatch requires descent rather than walking on air. Never use a book, orb or telescope as his entry mechanism. Camera movement follows the chosen episode plan, not a stock flourish. The final gateway frame is host-free; later body presence is explicitly planned.
''')
write('projects/q_station/characters/sea_captain/negative.md', read('projects/q_station/characters/sea_captain/negative.md') + '''

Never put the wide objective at his eye, swap telescope ends, or aim the objective toward his face. The small narrow eyepiece goes next to the visible unpatched eye; the wider objective faces the subject. A close-up must not conceal this relationship. Keep the approved eye-patch side and a plausible supporting grip.
''')

edit(P, 'from presentation_runtime import PresentationContext', 'from presentation_runtime import PresentationContext, presentation_for_project, load_presentation_profile\nfrom dataclasses import replace as replace_dataclass\nimport gateway_contracts as visuals')
edit(P, '_IMAGE_QC_BLOCKING_MARKERS = (', '_IMAGE_QC_BLOCKING_MARKERS = (\n    "visual contract violation", "spyglass orientation appears reversed",\n    "reversed spyglass", "optical ends are reversed",')
edit(P, '    normalized["review_status"] = "passed" if not warnings else "passed_with_warnings"', '    normalized["review_status"] = "failed" if blocking else ("passed_with_warnings" if warnings else "passed")')
replace_function(P, 'episode_frame_contract', '''def episode_frame_contract(world_style_plan: dict[str, Any]) -> str:
    """The entry object never determines the enclosing layout of the topic world."""
    return visuals.WORLD_RULE + caption_layout_rule(world_style_plan)
''')
replace_function(P, 'caption_layout_rule', '''def caption_layout_rule(world_style_plan: dict[str, Any]) -> str:
    if bool(world_style_plan.get("reserve_subtitle_space", True)):
        return (
            "Reserve only the bottom 8-10% as calm natural scene atmosphere for two subtitle lines; "
            "keep faces, hands and critical details above it. Continue the scene edge-to-edge. "
            "No printed text, separate banner, page margin or UI panel."
        )
    return (
        "Do not reserve a lower caption field, blank strip or empty panel. Use the full usable height "
        "for natural scene content, with consistent medium, texture, palette and lighting. No embedded text."
    )
''')
edit(P, '        qc_disabled = skip_content_qc or self.image_qc_disabled_for(stage)', '''        # Entry geometry is never an optional polish review. Body-only opt-outs remain intact.
        if stage in {"book_design_sheet", "book_cover"} and visuals.requirements(prompt):
            skip_content_qc = False
        qc_disabled = skip_content_qc or self.image_qc_disabled_for(stage)''')
edit(P, '                if skip_content_qc:\n                    check = {', '                if skip_content_qc and not (stage in {"book_design_sheet", "book_cover"} and visuals.requirements(prompt)):\n                    check = {')
edit(P, '                          saved.get("review_contract_version") == CONTRACT_VERSION):', '                          saved.get("review_contract_version") == CONTRACT_VERSION and\n                          visuals.review_matches(check, prompt)):')
edit(P, '            f"Requested art direction:\\n{prompt}",', '            f"Requested art direction:\\n{prompt}" + visuals.review_instructions(prompt),')
edit(P, '            accepted, warnings = assess_image_content_qc(check)', '            accepted, warnings = assess_image_content_qc(visuals.enforce_review(check, prompt))')
edit(P, '            "frame language, or established visual world is a fundamental failure: set passed=false and include "', '            "or established visual world is a fundamental failure: set passed=false and include "')
edit(P, '            "scene variation or a small presentational imperfection as continuity drift. "', '            "scene variation or a small presentational imperfection as continuity drift. An obsolete reference page border, "\n            "inset layout, margins or entry-object mask must not be copied into a full-bleed topic world. "')
edit(P, '        if warnings:\n            print(f"    [image QC] accepted', '        if warnings and accepted["passed"]:\n            print(f"    [image QC] accepted')
edit(P, '            f"{stage_guard} Introduce no new text, logos, objects, anatomy problems, identity drift, "', '            f"{stage_guard} Mandatory optical direction, actor route and full-bleed layout override the previous "\n            "candidate: fix a reversed telescope or enclosing page instead of preserving that defect as continuity. "\n            "Introduce no new text, logos, objects, anatomy problems, identity drift, "')

# Frozen old red/book episodes must never silently acquire the new segment or artifact names.
edit(P, '    return registry.get(registry.legacy_default_character_id)\n', '''    character = registry.get(registry.legacy_default_character_id)
    legacy_id = str((value.config.get("presentation_profiles") or {}).get("legacy_default") or "book_portal")
    return replace_dataclass(character, presentation=load_presentation_profile(
        value.root / "presentation_profiles" / legacy_id / "profile.json"
    ))
''')
edit(P, '    context = registry.get(resolution.resolved_character_id)\n    payload = resolution.to_state()', '''    context = registry.get(resolution.resolved_character_id)
    saved_presentation = project / "creative/PRESENTATION_RESOLUTION.json"
    saved_script = project / "creative/SCRIPT_PLAN.json"
    if saved_presentation.is_file():
        context = replace_dataclass(context, presentation=presentation_for_project(project, content_project))
    elif is_legacy_run or (persisted is not None and saved_script.is_file()
                           and "book_transition" in load_json(saved_script)):
        context = replace_dataclass(context, presentation=load_presentation_profile(
            content_project.root / "presentation_profiles/book_portal/profile.json"
        ))
    payload = resolution.to_state()''')
edit(P, '    ordered = [\n        str(data.get("opening_question_spark")', '''    if presentation is not None and presentation.min_entry_words:
        if len(_plan_tokens(str(data.get(entry_key) or ""))) < presentation.min_entry_words:
            raise StageFailure(stage, "FAILED_VALIDATION", f"{presentation.id} entry narration needs at least {presentation.min_entry_words} meaningful words for visible crossing and camera arrival; do not add stage-direction filler.")

    ordered = [
        str(data.get("opening_question_spark")''')
edit(P, '            data = validate_episode_opening_contract(data)', '''            data = validate_episode_opening_contract(data)
            try:
                visuals.validate_entry_camera(data, character.presentation)
            except ValueError as exc:
                raise StageFailure(stage, "FAILED_VALIDATION", str(exc)) from exc''')

# Shared style planning is about subjects/materials, never the opening apparatus.
text = read(P)
start = text.index('def stage_world_style_director(')
end = text.index('\ndef stage_record_history(', start)
part = text[start:end]
part = part.replace('FINAL_SCRIPT=plan["full_narration"]', 'FINAL_SCRIPT=visuals.factual_world_script(plan)')
part = part.replace('STYLE_CATALOG=json.dumps(catalog, ensure_ascii=False)', 'STYLE_CATALOG=json.dumps(visuals.style_catalog_context(catalog), ensure_ascii=False)')
part = part.replace('        return data\n', '        return {**data, **visuals.topic_style(data)}\n')
write(P, text[:start] + part + text[end:])

# Add a strong neutral-anchor request and regenerate a framed old catalog sample into a neutral derivative.
edit(P, '    stage = "world_style_anchor"\n    target =', '    stage = "world_style_anchor"\n    world_style_plan = visuals.topic_style(world_style_plan)\n    target =')
edit(P, '    launch = load_json(project / "launch" / "LAUNCH_REQUEST.json")\n    model = normalize_gemini_model(launch.get("image_generation", {}).get("model") or "nano_banana_2")\n    receipt_path = project / "pipeline" / "provider_receipts" / "gemini_world_style_anchor.json"', '''    prompt += " [VISUAL_CONTRACT:material_anchor_v2] Fill the canvas with a neutral material/palette sample, not a framed page, book, landscape, gateway, inset illustration or host."
    launch = load_json(project / "launch" / "LAUNCH_REQUEST.json")
    model = normalize_gemini_model(launch.get("image_generation", {}).get("model") or "nano_banana_2")
    receipt_path = project / "pipeline" / "provider_receipts" / "gemini_world_style_anchor.json"''')
edit(P, '            check = runner.validate_image_content(stage, prompt, source)\n            target.parent.mkdir', '''            derivative = None
            try:
                check = runner.validate_image_content(stage, prompt, source)
            except StageFailure as exc:
                if exc.error_code != "image_content_rejected":
                    raise
                # Preserve the catalog and medium; remove only its unwanted enclosing layout.
                derivative = runner.image(stage, prompt, refs, model=model, destination=target)
                check = (derivative.generation_receipt or {}).get("quality_check", {})
                if check.get("passed") is not True:
                    raise StageFailure(stage, "FAILED_VALIDATION", "Catalog derivative failed visual review.")
            target.parent.mkdir''')
edit(P, '                shutil.copyfile(source, temporary)\n                temporary.replace(target)', '                if derivative is None:\n                    shutil.copyfile(source, temporary)\n                    temporary.replace(target)')
edit(P, '                "contract_version": CONTRACT_VERSION, "source_type": "catalog",', '''                "contract_version": CONTRACT_VERSION, "source_type": "catalog",
                "catalog_derivative": derivative is not None,
                "provider_receipt": (derivative.generation_receipt or {}) if derivative else None,
                "job_id": derivative.job_id if derivative else None,''')

# New image requests with mandatory contracts must not trust an old permissive QC verdict.
edit(P, '    if status["status"] == "verified":\n        return True', '''    if status["status"] == "verified":
        data = load_json(receipt)
        if not visuals.review_matches(data.get("quality_check"), prompt) and not runner.image_qc_disabled_for(stage):
            try:
                data["quality_check"] = runner.validate_image_content(stage, prompt, target, references=references)
            except StageFailure as exc:
                if exc.error_code == "image_content_rejected":
                    return False
                raise
            save_json(receipt, data)
        return True''')

edit(P, '    stage = "visual_plan"\n    target =', '    stage = "visual_plan"\n    world_style_plan = visuals.topic_style(world_style_plan)\n    target =')
edit(P, '             character.presentation.segment_key: plan[character.presentation.segment_key],\n', '')
edit(P, '    stage = "world_keyframe_prompt"\n    target =', '    stage = "world_keyframe_prompt"\n    world_style_plan = visuals.topic_style(world_style_plan)\n    target =')
# Restrict this edit to the keyframe writer, not unrelated text/CTA stages.
text = read(P)
start = text.index('def stage_world_keyframe_prompt(')
end = text.index('\ndef book_design_sheet_path(', start)
part = text[start:end]
part = part.replace('    if runner.state.done(stage) and target.is_file():', '''    cache_path = target.with_suffix(".inputs.json")
    cache_key = openings.fingerprint({"script": visuals.factual_world_script(plan), "style": world_style_plan,
        "template": resolve_prompt(content_project, "06_world_keyframe_prompt_writer.md"),
        "entry": openings.world_entry_context(load_opening_concept(project))})
    cached = load_json(cache_path) if cache_path.is_file() else {}
    if (runner.state.done(stage) and target.is_file() and cached.get("input_sha256") == cache_key
            and cached.get("output_sha256") == sha256_file(target)):''')
part = part.replace('FINAL_SCRIPT=plan["full_narration"]', 'FINAL_SCRIPT=visuals.factual_world_script(plan)')
part = part.replace('    runner.stage_done(stage, started, target.name, prompt_sha256=sha256_text(text))', '    save_json(cache_path, {"input_sha256": cache_key, "output_sha256": sha256_file(target)})\n    runner.stage_done(stage, started, target.name, prompt_sha256=sha256_text(text))')
part = part.replace('repeatable material border and caption reserve', 'full-bleed scene and optional caption reserve')
write(P, text[:start] + part + text[end:])

# Shared identity path now uses v2 for captain; old committed sheet remains for provenance.
edit(P, 'if valid_image(target) and receipt_status(project, target, receipt, fingerprint=fingerprint)["status"] == "verified":', 'if (valid_image(target) and receipt_status(project, target, receipt, fingerprint=fingerprint)["status"] == "verified"\n            and visuals.review_matches(load_json(receipt).get("quality_check"), prompt)):')

# Direction caches bind actual frame rules/camera rather than only a stage-done flag.
edit(P, '    direction_target = presentation.artifacts.path(project, "entry_direction")\n    if force or not (runner.state.done(direction_stage) and direction_target.is_file()):', '''    direction_target = presentation.artifacts.path(project, "entry_direction")
    try:
        visuals.validate_entry_camera(episode_plan, presentation)
    except ValueError as exc:
        raise StageFailure(direction_stage, "FAILED_VALIDATION", str(exc)) from exc
    direction_cache_path = direction_target.with_suffix(".inputs.json")
    direction_key = openings.fingerprint({"topic": topic, "episode": episode_plan,
        "frame_rules": presentation.entry_frame_prompt, "presentation": presentation.prompt_context()})
    saved_direction = load_json(direction_cache_path) if direction_cache_path.is_file() else {}
    if force or not (runner.state.done(direction_stage) and direction_target.is_file()
                     and saved_direction.get("input_sha256") == direction_key
                     and saved_direction.get("output_sha256") == sha256_file(direction_target)):''')
edit(P, '        direction_target.write_text(direction + "\\n", encoding="utf-8")\n        runner.stage_done', '        direction_target.write_text(direction + "\\n", encoding="utf-8")\n        save_json(direction_cache_path, {"input_sha256": direction_key, "output_sha256": sha256_file(direction_target)})\n        runner.stage_done')
edit(P, '            f"Presentation: {json.dumps(presentation.prompt_context(), ensure_ascii=False)}. "', '            f"Presentation: {json.dumps(presentation.prompt_context(), ensure_ascii=False)}. "\n            f"Mandatory frame geometry: {presentation.entry_frame_prompt}. "')
edit(P, 'f"TOPIC-WORLD STYLE: {json.dumps(load_json(project / \'creative\' / \'WORLD_STYLE_PLAN.json\'), ensure_ascii=False)}"', 'f"TOPIC-WORLD STYLE: {json.dumps(visuals.topic_style(load_json(project / \'creative\' / \'WORLD_STYLE_PLAN.json\')), ensure_ascii=False)}\\n"\n        f"ENTRY CAMERA PLAN: {json.dumps(episode_plan.get(\'entry_camera\') or {}, ensure_ascii=False)}"')
edit(P, '    if presentation.entry_frame_character_presence == "ownership_cue":', '    if presentation.entry_frame_character_presence in {"ownership_cue", "acting_host"}:')
edit(P, '        refs.append(Reference(role="character_sheet", path=character.sheet_path))\n    launch =', '''        refs.append(Reference(role="character_sheet", path=character.sheet_path))
    if presentation.entry_frame_character_presence == "acting_host":
        world_reference = project / "references/world_keyframe.png"
        if valid_image(world_reference):
            refs.append(Reference(role="world_keyframe", path=world_reference))
    launch =''')

# The new camera plan reaches B, not the world/style/body prompts.
O = 'scripts/opening_runtime.py'
edit(O, '            "entry_bridge": bridge, "payoff": selected.get("payoff", "")}', '            "entry_bridge": bridge, "payoff": selected.get("payoff", ""),\n            "entry_camera": (episode or {}).get("entry_camera") or {}}')
edit(P, '    input_hash = openings.fingerprint({\n        "template_sha256"', '''    if clip == "B":
        try:
            visuals.validate_entry_duration(presentation, measured_seconds)
            visuals.validate_entry_camera(episode_plan or {}, presentation)
        except ValueError as exc:
            raise StageFailure(stage, "FAILED_VALIDATION", str(exc)) from exc
    input_hash = openings.fingerprint({
        "rules_sha256": sha256_text(presentation.question_prompt_rules if clip == "A" else presentation.transition_prompt),
        "template_sha256"''')
edit(P, '                            (not concept or existing.get("input_fingerprint") == input_hash))', '                            existing.get("input_fingerprint") == input_hash)')
edit(P, 'and (not require_source_contract and not concept or contract_matches):', 'and contract_matches:')
# Final B instructions bind camera/geometry even if the author abridges them.
edit(P, '    target.parent.mkdir(parents=True, exist_ok=True)\n    target.write_text(text.strip() + "\\n", encoding="utf-8")\n    contract_path.write_text(', '''    if clip == "B" and (presentation.motion_contract or presentation.entry_kind == "spyglass"):
        text += "\\n\\nBINDING ENTRY MOTION: " + presentation.transition_prompt
        if episode_plan and episode_plan.get("entry_camera"):
            text += "\\nENTRY CAMERA PLAN: " + json.dumps(episode_plan["entry_camera"], ensure_ascii=False)
        text += f"\\nEssential action ends by {measured_seconds:.3f}s; hold the last frame afterward."
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text.strip() + "\\n", encoding="utf-8")
    contract_path.write_text(''')

# Persist and compare actual input hashes, so a repaired still cannot reuse an old clip.
edit(P, '        "uploaded_roles": [ref.role for ref in references],', '        "uploaded_roles": [ref.role for ref in references],\n        "references": [{"role": ref.role, "path": _receipt_path(project, ref.path), "sha256": sha256_file(ref.path)} for ref in references],')
edit(P, '    receipt_duration = None\n    receipt_prompt = None', '    receipt_duration = None\n    receipt_prompt = None\n    stored_receipt = {}')
edit(P, '    # A recovered episode may need a longer opening source', '''    expected_uploads = build_flow_uploads(clip="A", character_sheet=(character or _coerce_character_context(content_project)).sheet_path) if clip == "A" else build_flow_uploads(clip="B", entry_frame=book_spread, world_keyframe=world_keyframe)
    current_refs = [{"role": role, "sha256": sha256_file(path)} for role, path in expected_uploads]
    recorded_refs = stored_receipt.get("references")
    refs_match = recorded_refs is None or [{"role": item.get("role"), "sha256": item.get("sha256")} for item in recorded_refs] == current_refs
    # A recovered episode may need a longer opening source''')
edit(P, '        and receipt_prompt in (None, sha256_text(prompt))', '        and receipt_prompt in (None, sha256_text(prompt))\n        and refs_match')
# First-frame review is checked only before a new paid B request, never on opening an old video.
edit(P, '    started = runner.stage_start(stage)\n\n    if clip == "A":\n        character =', '''    if clip == "B" and visuals.requirements(presentation.entry_frame_prompt):
        entry_receipt = presentation.artifacts.path(project, "entry_image_receipt")
        data = load_json(entry_receipt) if entry_receipt.is_file() else {}
        if (book_spread is None or data.get("output_sha256") != sha256_file(book_spread)
                or not visuals.review_matches(data.get("quality_check"), presentation.entry_frame_prompt)):
            raise StageFailure(stage, "FAILED_VALIDATION", "The entry start frame lacks current geometry acceptance. Regenerate the entry frame before spending Flow credits.")
    started = runner.stage_start(stage)

    if clip == "A":
        character =''')

# Body prompt context keeps WHO separate from gateway HOW.
edit(P, '    if beat.get("hero_present", False):\n        character = _coerce_character_context(character or content_project)\n    beat_id =', '    world_style_plan = visuals.topic_style(world_style_plan)\n    if beat.get("hero_present", False):\n        character = _coerce_character_context(character or content_project)\n    beat_id =')
edit(P, 'else "Previous image is binding for the recurring frame language, material/edge treatment, "\n            "inner illustration window, texture, palette and lighting. Follow the explicit caption-layout "', 'else "Previous image is binding only for compatible medium, texture, palette and lighting. "\n            "Ignore any inherited page border, inset, gateway mask or physical sheet. Follow the explicit caption-layout "')
edit(P, '            _character_prompt_context(character)\n            if beat.get("hero_present", False)', '            visuals.body_character_context(character)\n            if beat.get("hero_present", False)')
# Old receipts cannot bless an unmarked stale page-layout prompt under the new inputs.
edit(P, '        if recorded.get("prompt_sha256") == sha256_text(existing):', '        if recorded.get("prompt_sha256") == sha256_text(existing) and "[VISUAL_CONTRACT:topic_world_v2]" in existing:')
# The shared preset may mention gateway assets for operators; that is not a body-image style rule.
edit(P, '        STYLE_RULES=preset_readme.read_text(encoding="utf-8"),', '        STYLE_RULES="Use the selected topic-world medium and palette in a full-bleed scene. The opening preset and entry-object design do not define the body layout.",')

# Timing preflight runs after actual narration alignment, before visual-media generation.
T = 'scripts/plan_opening_sources.py'
edit(T, 'from flow_capabilities import durations_for_model', 'from flow_capabilities import durations_for_model\nfrom presentation_runtime import presentation_for_project\nfrom gateway_contracts import validate_entry_duration')
edit(T, '    model = str(settings.get("flow_video_model") or "gemini_omni_1_1_flash")', '''    try:
        validate_entry_duration(presentation_for_project(project), transition_end - spark_end)
    except ValueError as exc:
        raise OpeningSourcePlanError(str(exc)) from exc
    model = str(settings.get("flow_video_model") or "gemini_omni_1_1_flash")''')

# Replace the shared style director's page-framing prose, retaining its creative/media choices.
W = 'projects/q_station/prompts/pipeline/04_world_style_director.md'
text = read(W)
lines = text.splitlines()
lines = [line for line in lines if not any(term in line.lower() for term in ('inner illustration window', 'inner illustration-window', 'outer material', 'deckled page', 'must persist from the world keyframe'))]
write(W, '\n'.join(lines) + '''

## Topic-world layout (binding)
Return frame_language as a FULL-BLEED scene composition extending naturally to all four edges, not a recurring physical page/card border or inset illustration. Include layout_policy: "full_bleed_topic_world_v2" in the JSON object. Keep the chosen artistic medium, line treatment, grain, palette and lighting consistent while varying subjects and composition. Paper, manuscript-like markmaking, ink, collage, clay and other media are allowed as rendering treatments, never as an enclosing sheet, binding, gutter, parchment frame, doorway rim or lens mask.

Portal identity and character costume do not determine this world's style. Catalog styles with old border metadata may inspire medium/palette but their enclosing layout must not be inherited. An operator style reference is style-only: never copy its page edges, composition, printed text or recognizable subjects. Do not use the gateway narration as style evidence. If subtitles are disabled, no empty lower field; otherwise only bottom 8-10% remains naturally quiet, not a panel. A real book may be a relevant object inside a factual scene; it must not enclose every image.
''')
for path in ('05_visual_beat_planner.md','06_world_keyframe_prompt_writer.md','07_single_beat_image_prompt_writer.md'):
    name = 'projects/q_station/prompts/pipeline/' + path
    write(name, read(name) + '''

## Binding layout isolation
The viewer is INSIDE the topic world. Every scene fills the 9:16 image edge-to-edge, including the final optional-closing image. No enclosing physical page, book spread, card, gutter, decorative border, inset illustration window, doorway rim or lens mask. Preserve artistic medium, grain, palette and lighting, not a reference's border or composition. Paper/ink/collage texture is allowed; a subject-relevant book can be an object in the scene without becoming the layout. Opening entry mechanisms must not dictate body/world composition. If returning a production image prompt, include these constraints explicitly. Respect the caption-layout rule, never insert printed labels or a blank footer.
''')
D = 'projects/q_station/prompts/pipeline/03_episode_director.md'
write(D, read(D) + '''

When the presentation declares motion_contract=door_crossing_v1, include entry_camera exactly as its episode rules require. Its acting_host first frame is intentionally different from no-host book and hand-only orb frames: the actor must be visible so he can cross in B. Keep A question-first, and give B a feasible notice/open -> visible crossing -> camera arrival route within its narration boundary. Do not use a fade to hide missing crossing. The topic-world endpoint remains host-free for every presentation.
''')
S = 'projects/q_station/prompts/pipeline/03_opening_story_reviewer.md'
write(S, read(S) + '''

For door_crossing_v1, production_feasible and entry_continuity must reject a missing physical crossing, a solid-leaf intersection, a floor hatch without supported descent, a camera path inconsistent with the surface, or a fade before the host crosses. The short route begins with the host already beside the door; no extended approach. The chosen world clue must connect to the hook and first body payoff. For the captain, reject wide-objective-at-eye or a backward passage toward his face. These are structural defects, not aesthetic taste.
''')

# Tests enforce supported data, not a permanently frozen list that rejects every new production run.
Q = 'tests/test_q_station_only_repository.py'
edit(Q, 'test_only_q_station_project_and_three_hosts_remain', 'test_only_q_station_project_and_four_hosts_remain')
edit(Q, 'expected = {"red_horned_everyman", "moss_cloaked_crone", "sea_captain"}', 'expected = {"red_horned_everyman", "moss_cloaked_crone", "sea_captain", "newton_scholar"}')
replace_function(Q, 'test_only_audited_q_station_runs_remain', '''def test_only_audited_q_station_runs_remain() -> None:
    supported = {item["id"] for item in json.loads((ROOT / "projects/q_station/characters/registry.json").read_text())["characters"]}
    runs = [p for p in (ROOT / "videos").iterdir() if p.is_dir()]
    assert runs
    for run in runs:
        launch = json.loads((run / "launch/LAUNCH_REQUEST.json").read_text())
        assert launch.get("content_project") == "q_station", run.name
        resolution_path = run / "creative/CHARACTER_RESOLUTION.json"
        resolution = json.loads(resolution_path.read_text()) if resolution_path.is_file() else launch.get("character_resolution", {})
        selected = resolution.get("resolved_character_id") or (launch.get("character") or {}).get("character_id")
        assert selected in supported, (run.name, selected)
''')

# Deployment documentation uses the current mappings without mutating any historical run.
V = 'projects/q_station/visual_presets/001_home_world/README.md'
edit(V, 'presentation used by the red host.', 'presentation used by the Newton-inspired scholar in new runs and by frozen historical book runs.')
write('PROJECT_CONTEXT.md', '''# Q Station - current architecture

Only the `q_station` content project is supported. Character identity, opening presentation,
and per-episode topic-world art direction are separate contracts.

| Character | New-run presentation |
| --- | --- |
| Red Horned Everyman | `red_door_portal` |
| Moss-Cloaked Crone | `orb_portal` |
| Curious Sea Captain | `spyglass_portal` |
| Newton-Inspired Scholar | `book_portal` |

The Newton sheet is operator-provisioned; see `docs/CHARACTER_GATEWAYS.md` for its exact PNG path,
preflight and deployment. Missing artwork does not disable ready packs. A frozen episode's
presentation remains authoritative across registry changes; explicit character Revise is the
controlled way to change both character/presentation and dependent media.

## Entry points and invariants

- `scripts/video_control_panel.py`, `control_panel/ui/`: launch, preview, revision, recovery.
- `scripts/run_full_video_pipeline_q_station_wrapper.py`: narration/alignment before visual media.
- `scripts/run_q_station_pipeline.py`: three independent opening candidates/review, text, art and media.
- `scripts/character_runtime.py`: WHO; `scripts/presentation_runtime.py`: gateway HOW.
- `scripts/gateway_contracts.py`: full-bleed layout, optical/threshold review, camera/timing requirements.
- `scripts/run_graph.py`, `scripts/pipeline_stages.py`: profile-aware dependencies and invalidation.
- `scripts/plan_opening_sources.py`: supported Flow lengths from real narration boundaries.
- `scripts/run_completion_pipeline.py`: complete/save/publish first, commit run artifacts last.
- `scripts/commit_video_artifacts.py`: owns the run and its actually-used shared style/entry assets.

Flow A has only the character ingredient; Flow B has first_frame and last_frame only. Gemini
bakes any necessary actor identity into the first frame. The endpoint is always host-free.
Body images are full-bleed topic-world scenes, never enclosing pages inherited from the gateway.
Paper grain/ink/collage remain artistic media; a book may be a factual in-world object.

Keep existing provider selection, bounded correction/alternation, user body-QC opt-out, narration,
CTA/language policies and publishing settings. Hard entry geometry cannot be waived as a minor
warning. Review actual pixels, preserve provider receipts, and never manufacture successful media.
Internal book stage IDs and historical pipeline-profile names remain compatibility identifiers,
not rendering rules. Deployment does not rewrite existing videos or operator artwork.

See `docs/Q_STATION_PIPELINE.md`, `docs/OPENING_STORY_PIPELINE.md`, `docs/RECOVERY_RUNBOOK.md`,
`docs/SPOKEN_ENGLISH_POLICY.md` and `docs/CHARACTER_GATEWAYS.md`.
''')
for path in ('projects/q_station/README.md','projects/q_station/SETUP_CHECKLIST.md','docs/Q_STATION_PIPELINE.md','docs/SEA_CAPTAIN_INTEGRATION.md'):
    write(path, read(path) + '\n\n## Gateway update\n\nFor new runs, the red host uses `red_door_portal`, the Newton-inspired scholar uses the existing `book_portal`, the crone keeps `orb_portal`, and the captain uses the corrected optical-use `spyglass_portal`. Topic-world images are full-bleed, not enclosing pages. Earlier operational examples describe frozen historical runs; current installation, camera/QC contracts and revision guidance are in `docs/CHARACTER_GATEWAYS.md`.\n')

# Ensure no source-media or existing episode was changed by this integration script.
import subprocess
changed = subprocess.check_output(['git','diff','--name-only'], cwd=ROOT, text=True).splitlines()
assert not any(path.startswith('videos/') for path in changed), changed
for path in ('scripts/run_q_station_pipeline.py','scripts/presentation_runtime.py','scripts/plan_opening_sources.py','scripts/gateway_contracts.py'):
    ast.parse(read(path))
print('Integration patches applied; existing videos and operator images were not modified.')
