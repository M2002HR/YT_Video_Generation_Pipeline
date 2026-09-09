from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageStat

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from motion_camera_solver import base_viewport, compile_camera_plan, solve_camera_state
from motion_compiler import dynamic_motion_filter_v2, plan_render_units_v2
from motion_context import build_motion_context
from motion_schema import MotionPlanError
from motion_targets import resolve_target
from motion_v2_schema import MOTIONS, TRANSITIONS, settings, validate_inventory, validate_plan
from run_motion_director import plan_fingerprint, receipt_value


CFG = settings({"max_micro_shots_per_beat": 3, "min_micro_shot_duration": .5, "max_micro_shot_duration": 2.0, "supersample": 1})
TIMELINE = {
    "duration": 4.0, "fps": 15, "resolution": {"width": 320, "height": 180},
    "audio": "assets/audio/narration.m4a", "render_profile": "render/RENDER_PROFILE.json",
    "beats": [{"beat_id": 1, "media_type": "image", "start": 0.0, "end": 4.0, "duration": 4.0, "image": "assets/raw_beats/beat_001.png", "narration": "look left then right"}],
}
INVENTORY = {
    "schema_version": 2,
    "beats": [{
        "beat_id": 1, "artwork_region": {"x": .5, "y": .5, "w": 1, "h": 1},
        "composition_summary": "red block left, green block right", "visual_direction": "mixed",
        "targets": [
            {"target_id": "b01_red", "label": "red block", "kind": "object", "bbox": {"x": .3, "y": .5, "w": .25, "h": .5}, "importance": "primary", "confidence": .99, "visible_evidence": "red rectangle"},
            {"target_id": "b01_green", "label": "green block", "kind": "object", "bbox": {"x": .7, "y": .5, "w": .25, "h": .5}, "importance": "secondary", "confidence": .99, "visible_evidence": "green rectangle"},
        ], "faces": [], "hands_or_actions": [], "forbidden_regions": [], "negative_space": [], "notes": "",
    }],
}
PLAN = {
    "schema_version": 2, "duration_seconds": 4.0,
    "beats": [{
        "beat_id": 1, "start": 0.0, "end": 4.0, "attention_story": ["left", "right", "left"],
        "micro_shots": [
            {"shot_id": "b01_s01", "role": "establish", "start": 0.0, "end": 1.0, "edit_in": {"type": "establishing_cut"}, "camera": {"start": {"target_id": "b01_red", "coverage": .25, "anchor_x": .42, "anchor_y": .45}, "end": {"target_id": "b01_red", "coverage": .25, "anchor_x": .42, "anchor_y": .45}}, "motion": {"type": "hold", "easing": "gentle", "start_delay": 0, "end_hold": 0, "reason": "establish the first visible object"}, "sync": {"mode": "none"}},
            {"shot_id": "b01_s02", "role": "detail", "start": 1.0, "end": 2.3, "edit_in": {"type": "reframe_cut"}, "camera": {"start": {"target_id": "b01_green", "coverage": .8, "anchor_x": .5, "anchor_y": .45}, "end": {"target_id": "b01_green", "coverage": .8, "anchor_x": .5, "anchor_y": .45}}, "motion": {"type": "hold", "easing": "snappy", "start_delay": 0, "end_hold": 0, "reason": "hard attention change to second object"}, "sync": {"mode": "none"}},
            {"shot_id": "b01_s03", "role": "release", "start": 2.3, "end": 4.0, "edit_in": {"type": "continue"}, "camera": {"start": {"target_id": "b01_green", "coverage": .8, "anchor_x": .5, "anchor_y": .45}, "end": {"target_id": "b01_red", "coverage": .8, "anchor_x": .5, "anchor_y": .45}}, "motion": {"type": "pan", "easing": "ease_in_out", "start_delay": 0, "end_hold": .1, "reason": "return attention across the composition"}, "sync": {"mode": "none"}},
        ],
        "ending_state": {"target_id": "b01_red", "coverage": .8, "anchor_x": .5, "anchor_y": .45, "movement_direction": "left"},
        "transition_out": {"type": "cut", "duration": 0.0, "reason_code": "ending", "reason": "episode end"},
    }],
}


def make_episode(tmp_path: Path) -> tuple[Path, dict, dict, dict]:
    video = tmp_path / "episode"
    for folder in ("assets/raw_beats", "assets/audio", "timeline", "render", "motion", "timing", "launch"):
        (video / folder).mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (640, 360), (20, 20, 25))
    for x in range(110, 270):
        for y in range(90, 280): image.putpixel((x, y), (240, 20, 20))
    for x in range(370, 530):
        for y in range(90, 280): image.putpixel((x, y), (20, 240, 20))
    image.save(video / "assets/raw_beats/beat_001.png")
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", "4", "-c:a", "aac", str(video / "assets/audio/narration.m4a")], check=True, capture_output=True)
    (video / "timeline/TIMELINE.json").write_text(json.dumps(TIMELINE))
    (video / "render/RENDER_PROFILE.json").write_text(json.dumps({"resolution": {"width": 320, "height": 180}, "motion": {"enabled": True, "supersample": 1}, "subtitles": {"enabled": False}, "resource_limits": {"ffmpeg_threads": 1, "filter_threads": 1, "filter_complex_threads": 1}}))
    (video / "launch/CREATIVE_BRIEF.json").write_text(json.dumps({"_motion": {"enabled": True}}))
    context = build_motion_context(video, TIMELINE, CFG)
    inventory = validate_inventory(copy.deepcopy(INVENTORY), context["beats"])
    plan = validate_plan(copy.deepcopy(PLAN), context, inventory, CFG)
    compiled, _ = compile_camera_plan(plan, inventory, context, video, CFG)
    return video, context, inventory, compiled


@pytest.mark.parametrize("change", [
    lambda p: p.update(schema_version=8),
    lambda p: p["beats"][0]["micro_shots"][0]["motion"].update(type="shake"),
    lambda p: p["beats"][0]["micro_shots"][1].update(start=.9),
    lambda p: p["beats"][0]["micro_shots"][0]["camera"]["start"].update(target_id="invented"),
    lambda p: p["beats"][0]["micro_shots"][0]["motion"].update(easing="arbitrary_expression"),
    lambda p: p["beats"][0]["transition_out"].update(type="dissolve", duration=0),
])
def test_v2_schema_rejects_unsafe_contract(tmp_path: Path, change) -> None:
    video, context, inventory, _ = make_episode(tmp_path)
    bad = copy.deepcopy(PLAN); change(bad)
    with pytest.raises(MotionPlanError):
        validate_plan(bad, context, inventory, CFG)


def test_camera_solver_supports_arbitrary_aspects_and_clamps_velocity(tmp_path: Path) -> None:
    assert base_viewport(1600, 900, 1080, 1920) == pytest.approx((.31640625, 1.0))
    target = INVENTORY["beats"][0]["targets"][0]
    solved, changes = solve_camera_state(
            {"target_id": "b01_red", "coverage": .95, "anchor_x": .01, "anchor_y": .95},
        targets={"b01_red": target}, artwork={"x": .5, "y": .5, "w": 1, "h": 1},
        source_size=(640, 360), output_size=(320, 180), settings=CFG, subtitle_top=.72,
    )
    assert 0 <= solved["center_x"] <= 1 and 0 <= solved["center_y"] <= 1
    assert solved["width"] > 0 and solved["height"] > 0 and solved["zoom"] <= CFG["normal_max_zoom"] + .001
    assert "target_anchor_lifted_above_subtitles" in changes


def test_target_provider_chain_has_deterministic_center_fallback(tmp_path: Path) -> None:
    image = tmp_path / "source.png"
    Image.new("RGB", (100, 200), "navy").save(image)
    target, metadata = resolve_target(None, image)
    assert metadata == {"provider": "fallback_center", "fallback": True}
    assert target["bbox"] == {"x": .5, "y": .42, "w": .5, "h": .5}


def test_all_advanced_settings_are_strictly_bounded() -> None:
    configured = settings({"neighbor_context": 3, "word_sync_tolerance_ms": 125, "face_padding": .3})
    assert configured["neighbor_context"] == 3
    assert configured["word_sync_tolerance_ms"] == 125
    assert configured["face_padding"] == .3
    with pytest.raises(MotionPlanError):
        settings({"neighbor_context": 4})
    with pytest.raises(MotionPlanError):
        settings({"word_sync_tolerance_ms": 251})
    with pytest.raises(MotionPlanError):
        settings({"face_padding": .51})


def test_none_sync_drops_stale_word_metadata(tmp_path: Path) -> None:
    _, context, inventory, _ = make_episode(tmp_path)
    candidate = copy.deepcopy(PLAN)
    candidate["beats"][0]["micro_shots"][0]["sync"] = {"mode": "none", "word_id": "stale"}
    validated = validate_plan(candidate, context, inventory, CFG)
    assert validated["beats"][0]["micro_shots"][0]["sync"] == {"mode": "none"}


@pytest.mark.parametrize(("motion_type", "switch"), [
    ("drift", "allow_drift"),
    ("settle", "allow_settle"),
    ("reveal_move", "allow_reveal_move"),
])
def test_disabled_motion_primitives_are_rejected(tmp_path: Path, motion_type: str, switch: str) -> None:
    _, context, inventory, _ = make_episode(tmp_path)
    candidate = copy.deepcopy(PLAN)
    candidate["beats"][0]["micro_shots"][2]["motion"]["type"] = motion_type
    restricted = settings({**CFG, switch: False})
    with pytest.raises(MotionPlanError, match="disallowed motion"):
        validate_plan(candidate, context, inventory, restricted)


def test_disabled_editorial_operations_are_rejected(tmp_path: Path) -> None:
    _, context, inventory, _ = make_episode(tmp_path)
    match_cut = copy.deepcopy(PLAN)
    match_cut["beats"][0]["micro_shots"][1]["edit_in"] = {"type": "match_position_cut"}
    with pytest.raises(MotionPlanError, match="match-position cuts disabled"):
        validate_plan(match_cut, context, inventory, settings({**CFG, "allow_match_position_cuts": False}))

    transition = copy.deepcopy(PLAN)
    transition["beats"][0]["transition_out"] = {"type": "dissolve", "duration": .2, "reason_code": "memory"}
    with pytest.raises(MotionPlanError, match="decorative transitions disabled"):
        validate_plan(transition, context, inventory, settings({**CFG, "allow_decorative_transitions": False}))


def test_word_sync_switch_and_empty_motion_vocabulary_are_rejected(tmp_path: Path) -> None:
    video, _, inventory, _ = make_episode(tmp_path)
    (video / "timing/WORD_TIMINGS.json").write_text(json.dumps({"words": [{"word_id": "w_0001", "text": "look", "start": 0.0, "end": 0.2}]}))
    context = build_motion_context(video, TIMELINE, CFG)
    candidate = copy.deepcopy(PLAN)
    candidate["beats"][0]["micro_shots"][0]["sync"] = {"mode": "cut_on_word_start", "word_id": "w_0001"}
    with pytest.raises(MotionPlanError, match="word synchronization disabled"):
        validate_plan(candidate, context, inventory, settings({**CFG, "word_sync": False}))
    with pytest.raises(MotionPlanError, match="at least one enabled motion primitive"):
        settings({**CFG, "allow_hold": False, "allow_push": False, "allow_pull": False, "allow_pan": False,
                  "allow_tilt": False, "allow_pan_push": False, "allow_pan_pull": False, "allow_drift": False,
                  "allow_settle": False, "allow_reveal_move": False})


def test_same_image_expands_to_three_true_zero_overlap_units(tmp_path: Path) -> None:
    _, _, _, compiled = make_episode(tmp_path)
    units = plan_render_units_v2(compiled, TIMELINE["beats"])
    assert len(units) == 3
    assert sum(unit["duration"] for unit in units) == pytest.approx(4.0)
    assert all(unit["transition_in"] == "cut" and unit["transition_seconds"] == 0 for unit in units)
    assert units[1]["internal_edit_in"] == "reframe_cut"


@pytest.mark.parametrize("motion", sorted(MOTIONS))
def test_every_v2_motion_primitive_compiles_locally(tmp_path: Path, motion: str) -> None:
    _, _, _, compiled = make_episode(tmp_path)
    shot = copy.deepcopy(compiled["beats"][0]["micro_shots"][2])
    shot["motion"]["type"] = motion
    graph = dynamic_motion_filter_v2(input_index=0, label="v", width=320, height=180, fps=15, duration=1.7, motion_duration=1.7, shot=shot, supersample=1)
    assert "zoompan=" in graph and "settb=AVTB" in graph and "[v]" in graph
    assert "ffmpeg" not in graph.lower()


@pytest.mark.parametrize("transition", sorted(TRANSITIONS))
def test_every_transition_is_schema_validated(transition: str, tmp_path: Path) -> None:
    _, context, inventory, _ = make_episode(tmp_path)
    candidate = copy.deepcopy(PLAN)
    candidate["beats"][0]["transition_out"].update(type=transition, duration=0 if transition == "cut" else .2)
    validated = validate_plan(candidate, context, inventory, CFG)
    assert validated["beats"][0]["transition_out"]["type"] == transition


def test_fingerprint_changes_with_settings_and_receipt_requires_exact_match(tmp_path: Path) -> None:
    video, context, _, _ = make_episode(tmp_path)
    first = plan_fingerprint(context, CFG)
    changed_cfg = settings({**CFG, "pace": "calm"})
    changed_context = build_motion_context(video, TIMELINE, changed_cfg)
    assert plan_fingerprint(changed_context, changed_cfg) != first
    receipt = video / "motion/receipts/planning_001.json"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps({"input_fingerprint": first, "response": {"schema_version": 2}}))
    assert receipt_value(receipt, first, "response") == {"schema_version": 2}
    assert receipt_value(receipt, "stale", "response") is None


def test_v2_render_duration_and_single_source_decode(tmp_path: Path) -> None:
    video, _, inventory, compiled = make_episode(tmp_path)
    semantic = copy.deepcopy(PLAN); semantic["settings_snapshot"] = CFG; semantic["input_fingerprint"] = "fixture"
    compiled.update({"settings_snapshot": CFG, "input_fingerprint": "fixture", "compiled": True})
    (video / "motion/MOTION_PLAN.json").write_text(json.dumps(semantic))
    (video / "motion/VISUAL_INVENTORY.json").write_text(json.dumps(inventory))
    (video / "motion/COMPILED_MOTION_PLAN.json").write_text(json.dumps(compiled))
    dry = subprocess.run([sys.executable, str(ROOT / "scripts/render_video.py"), str(video), "--dry-run", "--no-telegram-progress"], capture_output=True, text=True, timeout=30)
    assert dry.returncode == 0, dry.stdout + dry.stderr
    assert dry.stdout.count(str(video / "assets/raw_beats/beat_001.png")) == 1
    assert "split=3" in dry.stdout and "concat=n=2" in dry.stdout
    output = video / "assets/renders/v2.mp4"
    result = subprocess.run([sys.executable, str(ROOT / "scripts/render_video.py"), str(video), "--output", str(output), "--no-telegram-progress"], capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(output)], capture_output=True, text=True, check=True)
    assert float(probe.stdout) == pytest.approx(4.0, abs=.08)


def test_master_motion_switch_ignores_existing_dynamic_plan_and_uses_legacy_renderer(tmp_path: Path) -> None:
    video, _, inventory, compiled = make_episode(tmp_path)
    semantic = copy.deepcopy(PLAN); semantic["settings_snapshot"] = CFG; semantic["input_fingerprint"] = "disabled"
    compiled.update({"settings_snapshot": CFG, "input_fingerprint": "disabled", "compiled": True})
    (video / "motion/MOTION_PLAN.json").write_text(json.dumps(semantic))
    (video / "motion/VISUAL_INVENTORY.json").write_text(json.dumps(inventory))
    (video / "motion/COMPILED_MOTION_PLAN.json").write_text(json.dumps(compiled))
    (video / "launch/CREATIVE_BRIEF.json").write_text(json.dumps({"_motion": {"enabled": False}}))
    dry = subprocess.run([sys.executable, str(ROOT / "scripts/render_video.py"), str(video), "--dry-run", "--no-telegram-progress"], capture_output=True, text=True, timeout=30)
    assert dry.returncode == 0, dry.stdout + dry.stderr
    assert "Dynamic motion V2" not in dry.stdout
    assert "split=3" not in dry.stdout


def test_visual_regression_reframe_moves_green_target_toward_center(tmp_path: Path) -> None:
    video, _, inventory, compiled = make_episode(tmp_path)
    semantic = copy.deepcopy(PLAN); semantic["settings_snapshot"] = CFG; semantic["input_fingerprint"] = "visual"
    compiled.update({"settings_snapshot": CFG, "input_fingerprint": "visual", "compiled": True})
    (video / "motion/MOTION_PLAN.json").write_text(json.dumps(semantic)); (video / "motion/VISUAL_INVENTORY.json").write_text(json.dumps(inventory)); (video / "motion/COMPILED_MOTION_PLAN.json").write_text(json.dumps(compiled))
    output = video / "assets/renders/visual.mp4"
    subprocess.run([sys.executable, str(ROOT / "scripts/render_video.py"), str(video), "--output", str(output), "--no-telegram-progress"], check=True, capture_output=True, timeout=90)
    frame = video / "green.png"
    subprocess.run(["ffmpeg", "-y", "-ss", "1.6", "-i", str(output), "-frames:v", "1", str(frame)], check=True, capture_output=True)
    with Image.open(frame) as image:
        center = image.crop((120, 45, 200, 135))
        mean = ImageStat.Stat(center).mean
    assert mean[1] > mean[0] * 1.5, "the planned green detail should occupy the center after the hard reframe"
