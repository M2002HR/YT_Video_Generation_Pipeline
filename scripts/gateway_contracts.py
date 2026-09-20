"""Versioned, provider-independent visual and entry-motion contracts.

These are acceptance requirements, not image generators. Geometry is checked against
actual pixels by the existing multimodal reviewer; Python validates the review schema
and refuses missing/failed checks. No provider fallback, artwork, or receipt is invented.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any

WORLD_LAYOUT = "full_bleed_topic_world_v2"
WORLD_FRAME = (
    "Full-bleed subject-world composition, extending naturally to all four image edges; "
    "consistent medium, palette, lighting and spatial depth, with fresh composition per beat."
)
WORLD_RULE = (
    "[VISUAL_CONTRACT:topic_world_v2] NON-NEGOTIABLE TOPIC-WORLD LAYOUT: "
    "The viewer is inside the explanatory world, not looking at an illustration mounted on a page. "
    "Fill the entire 9:16 canvas with the scene. No enclosing book/page/card, visible paper edge, "
    "deckled or parchment border, gutter, binding, decorative outer frame, inset illustration window, "
    "persistent doorway or circular lens mask. Paper grain, ink, collage and other chosen media "
    "remain valid as edge-to-edge rendering textures, not a physical sheet around the scene. "
    "A book or doorway may be a genuine in-world subject when the factual beat requires one, "
    "but must never become the enclosing layout. A reference's obsolete border, margins, labels, "
    "swatches or composition are not continuity requirements. Preserve its medium and palette only. "
)

CONTRACTS: dict[str, dict[str, str]] = {
    "topic_world_v2": {
        "full_bleed": "The subject-world scene reaches all four edges; no enclosing physical page/card/book, decorative frame, gutter, inset window or persistent entry-object mask. Grain is allowed; an actual topic-relevant book as a scene object is allowed.",
    },
    "material_anchor_v2": {
        "neutral_material": "A neutral edge-to-edge material/palette/line sample, not an open book, framed page, doorway, spyglass, character, location or illustrated inset. Palette swatches may appear on a style sheet only.",
    },
    "spyglass_identity_v2": {
        "unequal_optical_ends": "The SAME straight telescope has a physically small narrow rear eyepiece and a distinctly wider front objective. Both ends are visible in side view and agree in every view; perspective alone is not evidence of reversed physical diameters.",
    },
    "spyglass_entry_v2": {
        "small_end_at_eye": "The small rear eyepiece is next to the captain's visible, unpatched eye. The large objective is NOT touching or pointing back toward his face. The eye relationship is actually visible, not guessed from a cuff.",
        "objective_outward": "The barrel extends away from the captain toward the observed subject, ending in the wider objective. Both endpoints and their connection are legible in an oblique side/rear-three-quarter view; no reversed telescope, swapped ends or face inside the tube.",
        "identity_and_grip": "One canonical captain holds one canonical spyglass with a plausible support grip, keeping his sheet's eye patch, face, beard and blue cuff. No floating scope or extra limb.",
        "scene_not_page": "The opening scene fills the image; no enclosing page, parchment frame, reference-sheet grid or circular full-image mask.",
    },
    "red_door_identity_v1": {
        "canonical_door": "One consistent solid red, narrow round-shouldered rectangular door with charcoal frame, two vertically stacked recessed panels, a small brass ring handle on the front right and hinges on the front left. No text, portal energy ring or changing hardware between views.",
    },
    "red_door_entry_v1": {
        "actor_and_threshold": "The canonical red host is clearly recognizable, including both horns, body and feet, beside ONE human-scale door. There is enough clearance for horns and a readable route through its threshold, not a hand-only cue or an already-empty world.",
        "door_start_state": "The canonical red hinged door is almost closed or just starting to open; it has not already completed the opening/crossing. A narrow real aperture reveals a topic-world clue with the target medium/texture, not a pasted poster, red painted texture, white void or opaque solid door.",
        "surface_and_route": "The declared supporting plane, hinge clearance and actor route agree: a wall door permits stepping through; a floor hatch has visible steps or another explicitly supported descent. The host is not walking on air, falling accidentally or intersecting a solid leaf.",
        "scene_not_page": "The door belongs to a full-scene composition, not a book spread, reference grid or ornamental outer page frame.",
    },
}
_MARKER = re.compile(r"\[VISUAL_CONTRACT:([a-z0-9_]+)\]")


def requirements(prompt: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for contract in dict.fromkeys(_MARKER.findall(prompt)):
        if contract not in CONTRACTS:
            raise ValueError(f"Unknown visual contract: {contract}")
        result.update({f"{contract}.{key}": value for key, value in CONTRACTS[contract].items()})
    return result


def signature(prompt: str) -> str:
    required = requirements(prompt)
    if not required:
        return ""
    return hashlib.sha256(json.dumps(required, sort_keys=True).encode()).hexdigest()


def review_instructions(prompt: str) -> str:
    required = requirements(prompt)
    if not required:
        return ""
    return (
        "\nMANDATORY VISUAL CONTRACT REVIEW overrides the generic permissive framing rule. "
        "Inspect the candidate pixels, not merely the prompt. Also return contract_checks as an object "
        "with EVERY key below, each containing {passed: boolean, evidence: non-empty concise string}. "
        "Evidence must describe visible relationships. Occluded, ambiguous or uncheckable requirements "
        "are NOT a pass. A failed required check is fundamental, even when ordinary framing polish is not. "
        "Do not mark an inherited page border as desirable style continuity.\n"
        + json.dumps(required, ensure_ascii=False)
    )


def enforce_review(check: dict[str, Any], prompt: str) -> dict[str, Any]:
    """Convert missing/ambiguous geometry and layout checks into hard failures."""
    required = requirements(prompt)
    if not required:
        return check
    if not isinstance(check, dict):
        raise ValueError("Visual review must be an object.")
    result = dict(check)
    observed = check.get("contract_checks")
    observed = observed if isinstance(observed, dict) else {}
    failures = []
    for key in required:
        item = observed.get(key)
        if (not isinstance(item, dict) or type(item.get("passed")) is not bool
                or not isinstance(item.get("evidence"), str) or not item["evidence"].strip()):
            failures.append(f"visual contract violation: {key}: missing boolean check or visible evidence")
        elif not item["passed"]:
            failures.append(f"visual contract violation: {key}: {item['evidence'][:600]}")
    for key in ("violations", "blocking_violations"):
        prior = result.get(key, [])
        if not isinstance(prior, list) or any(not isinstance(item, str) for item in prior):
            raise ValueError(f"Visual review {key} must be an array of strings.")
        result[key] = list(dict.fromkeys([*prior, *failures]))
    if failures:
        result["passed"] = False
    result["visual_contract_signature"] = signature(prompt)
    return result


def review_matches(check: Any, prompt: str) -> bool:
    if not requirements(prompt):
        return True
    if not isinstance(check, dict) or check.get("visual_contract_signature") != signature(prompt):
        return False
    validated = enforce_review(check, prompt)
    return validated.get("passed") is True and not validated.get("blocking_violations")


def topic_style(plan: dict[str, Any]) -> dict[str, Any]:
    """Non-mutating rendering projection, also for old catalog entries."""
    allowed = (
        "style_id", "decision", "reuse_of", "medium", "secondary_treatment", "texture_family",
        "palette_summary", "line_treatment", "lighting", "subject_constraints",
        "historical_accuracy_note", "hero_rendering_in_world", "negative_constraints",
        "reserve_subtitle_space", "operator_style_reference",
    )
    result = {key: plan[key] for key in allowed if key in plan}
    result["frame_language"] = WORLD_FRAME
    result["layout_policy"] = WORLD_LAYOUT
    result["subtitle_reserve"] = (
        "Calm natural atmosphere only in the bottom 8-10%; no separate panel or printed text."
        if plan.get("reserve_subtitle_space", True)
        else "No reserved caption field; continue the scene through the full height."
    )
    return result


def style_catalog_context(catalog: dict[str, Any]) -> dict[str, Any]:
    """Return the compact, selection-only view needed by the style director.

    The style director needs to compare available media and return an exact ID;
    it does not need anchor paths or the repeated full-bleed layout contract.
    Keeping that contract in the stage prompt once (rather than once per
    catalog entry) leaves room for a growing production style catalog while
    staying below Ordak's request-size limit.
    """
    result = dict(catalog)
    if isinstance(catalog.get("styles"), list):
        result["styles"] = [
            {
                key: entry.get(key)
                for key in (
                    "style_id", "medium_family", "texture_family",
                    "palette_summary", "status", "usage_count",
                )
                if entry.get(key) is not None
            }
            for entry in catalog["styles"] if isinstance(entry, dict)
        ]
    return result


def factual_world_script(plan: dict[str, Any]) -> str:
    """Narration facts without gateway choreography/CTA; no anatomy is injected."""
    if "body" not in plan:
        return str(plan.get("full_narration") or "")
    return " ".join(str(part).strip() for part in [*plan.get("body", []), plan.get("optional_closing", "")] if str(part).strip())


def body_character_context(character: Any) -> str:
    return json.dumps({
        "id": character.id, "display_name": character.display_name,
        "appearance": character.appearance_full, "reference_mode": character.reference_mode,
        "instruction": "Use the supplied sheet for identity only. No habitual accessory, opening location or gateway is required in the subject world; follow this beat's actual action.",
    }, ensure_ascii=False)


DOOR_TRANSITIONS = ("follow_through", "threshold_dissolve", "texture_takeover")
ENTRY_FIELDS = ("attention_cue", "opening_action", "crossing_action", "camera_path", "world_reveal")


def validate_entry_camera(episode: dict[str, Any], presentation: Any) -> dict[str, Any]:
    """Profile-scoped structural checks before independent story review and paid media."""
    if getattr(presentation, "motion_contract", "") != "door_crossing_v1":
        return episode
    camera = episode.get("entry_camera")
    if not isinstance(camera, dict):
        raise ValueError("Door episode requires entry_camera with surface, transition, attention_cue, opening_action, crossing_action, camera_path and world_reveal.")
    if camera.get("surface") not in {"wall", "floor", "freestanding", "other"}:
        raise ValueError("entry_camera.surface must be wall, floor, freestanding or other.")
    if camera.get("transition") not in DOOR_TRANSITIONS:
        raise ValueError("Choose exactly one supported doorway transition, not a montage.")
    for key in ENTRY_FIELDS:
        value = camera.get(key)
        if not isinstance(value, str) or not value.strip() or len(value) > 400:
            raise ValueError(f"entry_camera.{key} must describe one readable action in 1-400 characters.")
    variant = episode.get("entry_variant")
    expected_surface = {"wrong_wall": "wall", "recessed_door": "wall", "existing_exit": "wall",
                        "freestanding_door": "freestanding", "floor_hatch": "floor"}.get(variant)
    if expected_surface and camera["surface"] != expected_surface:
        raise ValueError(f"{variant} requires the {expected_surface} surface and a matching supported route.")
    return episode


def validate_entry_duration(presentation: Any, seconds: float) -> None:
    minimum = float(getattr(presentation, "min_entry_seconds", 0.0))
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("Entry duration must be a finite positive number.")
    if minimum and seconds < minimum:
        raise ValueError(
            f"{presentation.id} needs at least {minimum:g}s of measured entry narration for opening, "
            f"visible host crossing and camera arrival, but has {seconds:.3f}s. Revise the entry narration "
            "before paid visual media; a longer source alone cannot fix an edit that trims the crossing."
        )


def read_cache(path: Any) -> dict[str, Any]:
    """A truncated cache is a cache miss, never permission to reuse an artifact."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}
