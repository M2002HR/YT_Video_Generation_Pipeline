"""Versioned, content-agnostic prompts for Motion Director V2."""
from __future__ import annotations
import json
from typing import Any

PROMPT_VERSION = "motion-director-v2.0"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _editorial_settings(settings: dict[str, Any]) -> dict[str, Any]:
    keep = ("pace", "style", "intensity", "image_zoom_strength", "image_transition_style", "image_transition_seconds", "max_micro_shots_per_beat", "min_micro_shot_duration", "max_micro_shot_duration", "target_interval_min", "target_interval_max", "allow_hold", "allow_push", "allow_pull", "allow_pan", "allow_tilt", "allow_pan_push", "allow_pan_pull", "allow_drift", "allow_settle", "allow_reveal_move", "allow_punch_cuts", "allow_hard_reframes", "allow_match_position_cuts", "allow_decorative_transitions", "allow_directional_transitions", "allow_reveal_transitions", "transition_preference", "word_sync")
    return {key: settings.get(key) for key in keep}

BASE = """You are the Motion Director for a professional short-form video pipeline.
You are an editor, cinematographer, motion designer, and attention director.
Never add movement for movement's sake. Narrative meaning comes first, then viewer
attention, visible subjects, speech emphasis, composition, continuity, rhythm, variety,
and decorative style last. A hold is valid. A hard cut is often stronger than an effect.
Do not invent visible objects. Use only evidence in the attached image and supplied visual
inventory. Never output FFmpeg, expressions, code, Markdown, or commentary. Output one raw
JSON object matching the requested contract exactly."""


def observation_prompt(batch: list[dict[str, Any]]) -> str:
    manifest=[{"beat_id":b["beat_id"],"filename":b["media"].split("/")[-1],"sha256":b.get("media_sha256"),"source_size":[b.get("media_width"),b.get("media_height")],"narration":b["narration"],"spoken_text_in_slot":b["spoken_text_in_slot"],"visual_description":b["visual_description"]} for b in batch]
    contract={"schema_version":2,"beats":[{"beat_id":"same ID from manifest","artwork_region":{"x":"0..1 center","y":"0..1 center","w":"0..1","h":"0..1"},"composition_summary":"what is actually visible","visual_direction":"left|right|up|down|center|mixed|none","targets":[{"target_id":"unique stable bNN_target_name","label":"specific visible element","kind":"face|person|hand|object|place|context|text|group|detail","bbox":{"x":"center 0..1","y":"center 0..1","w":"0..1","h":"0..1"},"importance":"primary|secondary|context","confidence":"0..1","visible_evidence":"short literal evidence"}],"faces":["target_id values that are faces"],"hands_or_actions":["target_id values"],"forbidden_regions":[{"type":"blank|embedded_text|frame_border|subtitle_collision_risk|low_detail","bbox":{"x":.5,"y":.5,"w":.1,"h":.1}}],"negative_space":[{"x":.5,"y":.5,"w":.1,"h":.1}],"notes":"crop and attention constraints"}]}
    return BASE+"""

TASK: VISUAL OBSERVATION ONLY. Inspect every attached image carefully. The attachment order
matches the manifest order and filenames include the beat number. Report only elements you
can visibly verify. Coordinates use the full source image, with x/y as bbox center and w/h
as bbox size. Include the complete artwork area and blank card/caption panels as forbidden
regions. Identify faces, hands/actions, important objects, gaze/screen direction, and useful
context. If a narrated object is not visible, do not create it. Provide at least one verified
target per image. Target IDs must be unique within the episode.

CONTRACT:
"""+_json(contract)+"\nMANIFEST:\n"+_json(manifest)


def direction_prompt(episode: dict[str, Any], beats: list[dict[str, Any]], inventory: dict[str, Any]) -> str:
    compact_inv=[{"beat_id":b["beat_id"],"summary":b.get("composition_summary"),"direction":b.get("visual_direction"),"targets":[{"id":t["target_id"],"label":t["label"],"kind":t.get("kind"),"importance":t.get("importance"),"xy":[round(t["bbox"]["x"],3),round(t["bbox"]["y"],3)]} for t in b["targets"][:4]],"forbidden_types":[x.get("type") for x in b.get("forbidden_regions",[])]} for b in inventory["beats"]]
    context={"duration":episode["duration"],"aspect_ratio":episode["aspect_ratio"],"subtitle_safe_region":episode["subtitle_safe_region"],"settings":_editorial_settings(episode["settings"]),"script":episode["script"],"beats":[{"beat_id":b["beat_id"],"media_type":b["media_type"],"start":b["start"],"end":b["end"],"spoken_text":b["spoken_text_in_slot"],"words":[[w["word_id"],w["text"],w["start"],w["end"]] for w in b["spoken_words"]]} for b in beats],"visual_inventory":compact_inv}
    contract={"schema_version":2,"pace":"calm|balanced|fast|very_fast","sections":[{"name":"hook|setup|body|climax|ending|cta","start":0,"end":1,"energy":"0..1","attention_velocity":"0..1"}],"emphasis_words":[{"word_id":"w_0001","reason":"name|number|reveal|contrast|emotion|object|location"}],"rhythm_notes":["..."],"transition_philosophy":["..."],"motion_contrast_plan":["..."],"ending_strategy":"...","prohibited_patterns":["..."]}
    return BASE+"\nTASK: Design the coherent editorial direction for the WHOLE episode after studying its verified visual inventory. Fast means attention shifts and timing contrast, not effect spam. The opening may be faster; emotional moments may breathe. Select emphasis word IDs only when present in the supplied beat word context. Use energy values from 0 to 1.\nCONTRACT:\n"+_json(contract)+"\nEPISODE CONTEXT:\n"+_json(context)


def planning_prompt(*, episode: dict[str, Any], batch: list[dict[str, Any]], inventory: list[dict[str, Any]], direction: dict[str, Any], previous_state: dict[str, Any] | None, previous_neighbor: list[dict[str, Any]], next_neighbor: list[dict[str, Any]]) -> str:
    compact_beats=[{key:b.get(key) for key in ("beat_id","media_type","start","end","duration","narration","spoken_text_in_slot","spoken_words","visual_description","media_width","media_height")} for b in batch]
    compact_inventory=[{"beat_id":b["beat_id"],"artwork_region":b["artwork_region"],"composition_summary":b.get("composition_summary"),"visual_direction":b.get("visual_direction"),"targets":[{key:t.get(key) for key in ("target_id","label","kind","bbox","importance","confidence")} for t in b["targets"]],"faces":b.get("faces",[]),"hands_or_actions":b.get("hands_or_actions",[]),"forbidden_regions":b.get("forbidden_regions",[])} for b in inventory]
    payload={"episode":{"duration":episode["duration"],"aspect_ratio":episode["aspect_ratio"],"width":episode["width"],"height":episode["height"],"subtitle_safe_region":episode["subtitle_safe_region"],"settings":_editorial_settings(episode["settings"])},"global_direction":direction,"previous_camera_state":previous_state,"previous_neighbors":previous_neighbor,"current_beats":compact_beats,"verified_visual_inventory":compact_inventory,"next_neighbors":next_neighbor}
    contract={"schema_version":2,"duration_seconds":episode["duration"],"beats":[{"beat_id":"exact input ID","start":"exact beat start","end":"exact beat end","attention_story":["ordered attention logic"],"micro_shots":[{"shot_id":"bNN_sNN","role":"establish|primary|detail|reaction|context|release|hold","start":"seconds","end":"seconds","edit_in":{"type":"continue|cut|reframe_cut|punch_cut_in|punch_cut_out|match_position_cut|detail_cut|establishing_cut"},"camera":{"start":{"target_id":"verified inventory ID","coverage":"0.08..0.95","anchor_x":"0..1","anchor_y":"0..1"},"end":{"target_id":"verified inventory ID","coverage":"0.08..0.95","anchor_x":"0..1","anchor_y":"0..1"}},"motion":{"type":"hold|push_in|pull_out|pan|tilt|pan_push|pan_pull|drift|settle|reveal_move","easing":"linear|ease_in|ease_out|ease_in_out|snappy|gentle|hold_then_move|impact_then_settle","start_delay":0,"end_hold":0,"reason":"specific editorial reason"},"sync":{"mode":"none|cut_on_word_start|movement_start_on_word|impact_apex_on_word|reveal_complete_on_word|settle_on_word_end","word_id":"required unless none"}}],"ending_state":{"target_id":"verified inventory ID","coverage":.5,"anchor_x":.5,"anchor_y":.45,"movement_direction":"left|right|up|down|in|out|none"},"transition_out":{"type":"cut|dissolve|fade|smoothleft|smoothright|smoothup|smoothdown|wipeleft|wiperight|wipeup|wipedown|slideleft|slideright|slideup|slidedown|revealleft|revealright|revealup|revealdown|zoomin","duration":0,"reason_code":"new_fact|contrast|time_shift|location_shift|memory|emotional_continuity|directional_match|reveal|ending|cta|continuity","reason":"specific reason"}}]}
    rules="""
TASK: Direct each current image as one to several meaningful visual states. Use ONLY target IDs
from verified_visual_inventory. Base every timing decision on exact spoken word timestamps.
If an event emphasizes a word, select its word_id and align the event semantically: cut at
word start, begin movement on word, place punch apex on word, or complete reveal on word.
Do not merely write a trigger label. Cover every beat exactly with ordered non-overlapping
micro-shots. Respect all allow/disable settings and duration limits. For edit_in=continue,
the target_id, coverage, anchor_x and anchor_y of camera.start MUST exactly copy the previous
shot camera.end; otherwise select a cut/reframe edit. A hold MUST use identical start/end
camera states and MUST use sync.mode=none; a hold cannot claim a movement/impact/reveal event.
Easing is never "hold" (use linear for a hold). Use a hard reframe only for a meaningful
attention jump. Avoid repetitive move shapes across neighboring beats. Preserve faces,
hands/actions, artwork bounds, and subtitle safety. Prefer a stable hold when movement has no
narrative purpose. Transition out defaults to cut and decorative transitions require geometry
and semantic justification. NON-NEGOTIABLE IMAGE TRANSITION POLICY: transition_out may use
only the types selected by image_transition_style: cuts are duration 0; fade/dissolve use
exactly image_transition_seconds. Do not use wipe, slide, cover, reveal, radial, zoom or any
other display-style effect. There is no quota for semantically justified soft transitions.
NON-NEGOTIABLE IMAGE ZOOM POLICY: every micro-shot in every body
image except the episode's final image must be a continuous inward move (`push_in`, `pan_push`,
or `reveal_move`) and the beat must end with `movement_direction: "in"`. The final image is the
one release: every one of its micro-shots must be `pull_out` or `pan_pull`, ending with
`movement_direction: "out"`. Use image_zoom_strength as the minimum perceptible zoom change.
Return decisions for current_beats only.
"""
    return BASE+rules+"\nCONTRACT:\n"+_json(contract)+"\nCONTEXT:\n"+_json(payload)


def critic_prompt(plan: dict[str, Any], inventory: dict[str, Any], direction: dict[str, Any], settings: dict[str, Any]) -> str:
    contract={"schema_version":2,"approved":True,"issues":[{"severity":"warning|error","beat_id":1,"shot_id":"b01_s01","code":"hallucinated_target|bad_crop|bad_sync|repetition|unmotivated_cut|transition_spam|face_risk|subtitle_risk|dead_tail|dead_tail","message":"specific finding"}],"replacement_beats":["complete corrected beat objects only when an error requires replacement"]}
    return BASE+"\nTASK: Act as a strict senior editor. Audit this ordered episode segment against verified inventory, whole-episode direction and settings. Reject invented targets, weak word synchronization, repetitive camera trajectories, unmotivated cuts, transition spam, face/subtitle risk and dead ending behavior. replacement_beats must be empty when approved. If approved=false, provide one COMPLETE corrected beat object in replacement_beats for EVERY beat that has an error. A diagnosis without its replacement is invalid.\nCONTRACT:\n"+_json(contract)+"\nSETTINGS:\n"+_json(_editorial_settings(settings))+"\nDIRECTION:\n"+_json(direction)+"\nINVENTORY:\n"+_json(inventory)+"\nPLAN:\n"+_json(plan)
