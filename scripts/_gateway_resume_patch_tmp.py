"""Finish the rollout-compatibility audit; removed before the source commit."""
from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
def edit(path, before, after):
    target = ROOT / path
    text = target.read_text()
    assert text.count(before) == 1, (path, before[:100], text.count(before))
    target.write_text(text.replace(before, after))

P = 'scripts/run_q_station_pipeline.py'
edit(P, 'import gateway_contracts as visuals', 'import gateway_contracts as visuals\nimport gateway_resume')
edit(P, '        base_inputs = {\n            "policy_version": openings.POLICY_VERSION', '        base_inputs = {\n            "gateway_inputs_version": gateway_resume.INPUTS_VERSION,\n            "policy_version": openings.POLICY_VERSION')
edit(P, '                if not unchanged_legacy:\n                    raise StageFailure(stage, "FAILED_VALIDATION", "Opening inputs changed.', '                if not unchanged_legacy and not gateway_resume.retains_approved_concept(frozen, base_inputs, saved):\n                    raise StageFailure(stage, "FAILED_VALIDATION", "Opening inputs changed.')

G = 'scripts/gateway_contracts.py'
edit(G, '    if episode.get("entry_variant") == "floor_hatch" and camera["surface"] != "floor":\n        raise ValueError("floor_hatch requires the floor surface and a supported descent.")', '''    variant = episode.get("entry_variant")
    expected_surface = {"wrong_wall": "wall", "recessed_door": "wall", "existing_exit": "wall",
                        "freestanding_door": "freestanding", "floor_hatch": "floor"}.get(variant)
    if expected_surface and camera["surface"] != expected_surface:
        raise ValueError(f"{variant} requires the {expected_surface} surface and a matching supported route.")''')
T = 'tests/test_gateway_visual_contracts.py'
edit(T, 'episode = {"entry_variant": "floor_hatch" if surface == "floor" else "wrong_wall", "entry_camera": camera(surface, transition)}', 'episode = {"entry_variant": {"floor": "floor_hatch", "wall": "wrong_wall", "freestanding": "freestanding_door", "other": "unexpected_surface"}[surface], "entry_camera": camera(surface, transition)}')

T = ROOT / 'tests/test_opening_concept_pipeline.py'
T.write_text(T.read_text() + '''


def test_approved_pre_gateway_premise_survives_prose_rollout_without_rewriting(run, registry):
    spy, concept, char = make_concept(run, registry, "moss_cloaked_crone")
    context_path = run / "creative/OPENING_CONTEXT.json"
    frozen = json.loads(context_path.read_text())
    frozen.pop("gateway_inputs_version")
    frozen["character"]["behavior"] = "Previously approved acting prose."
    frozen["presentation"]["episode_rules"] = "Previously approved orb handoff."
    for key in ("motion_contract", "min_entry_seconds", "min_entry_words"):
        frozen["presentation"].pop(key, None)
    keys = ("policy_version", "brief", "character", "presentation", "writer_sha256", "reviewer_sha256", "language_policy_version")
    old_hash = opening.fingerprint({key: frozen[key] for key in keys})
    frozen["input_fingerprint"] = old_hash
    concept["input_fingerprint"] = old_hash
    concept["concept_id"] = opening.fingerprint({"input": old_hash, "selected": concept["selected"]})[:20]
    qstation.save_json(context_path, frozen)
    qstation.save_json(run / "creative/OPENING_CONCEPT.json", concept)
    before = context_path.read_bytes()
    count = len(spy.prompts)
    assert qstation.stage_opening_concept(spy, run, load_content_project("q_station"), "earworms", qstation.DurationTarget(30,40), char) == concept
    assert len(spy.prompts) == count and context_path.read_bytes() == before
    brief_path = run / "launch/CREATIVE_BRIEF.json"
    brief = json.loads(brief_path.read_text())
    brief["must_include"] = "A genuinely changed editorial requirement."
    qstation.save_json(brief_path, brief)
    with pytest.raises(qstation.StageFailure, match="Opening inputs changed"):
        qstation.stage_opening_concept(spy, run, load_content_project("q_station"), "earworms", qstation.DurationTarget(30,40), char)
''')

D = ROOT / 'docs/CHARACTER_GATEWAYS.md'
D.write_text(D.read_text() + '''

### Pre-rollout approved stories
An approved pre-rollout opening context can retain its existing premise when only gateway/acting
prose changes in this release. Both stored input and selected-concept hashes must verify; editorial
brief, duration, character identity, gateway identity, selector prompts and language policy must
still agree. Nothing in the frozen context is rewritten. New contexts carry a version marker and
cannot use this compatibility path. This is NOT acceptance of an old reversed or page-framed image:
regenerated media must pass the current geometry/layout review. A real editorial or character
change continues to require explicit Revise.
''')
for name in (P, G, 'scripts/gateway_resume.py', 'tests/test_opening_concept_pipeline.py'):
    ast.parse((ROOT / name).read_text())
print('Frozen-story rollout and supporting-plane consistency patches applied.')
