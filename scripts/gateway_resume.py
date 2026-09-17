"""Narrow rollout compatibility for approved pre-gateway creative contexts.

Retaining a frozen premise never certifies old image geometry or layout. Changed
editorial inputs, identity, gateway, selector prompts or tampered hashes still require
explicit Revise. New contexts never use this pre-rollout compatibility path.
"""
from __future__ import annotations

from typing import Any
from opening_runtime import fingerprint

INPUTS_VERSION = 1
_BASE_KEYS = ("policy_version", "brief", "character", "presentation", "writer_sha256", "reviewer_sha256", "language_policy_version")
_CHAR_PROSE = {"behavior", "negative_constraints"}
_PRESENTATION_PROSE = {"script_rules", "episode_rules", "entry_frame_character_presence", "motion_contract", "min_entry_seconds", "min_entry_words"}


def retains_approved_concept(frozen: Any, current: dict[str, Any], concept: dict[str, Any]) -> bool:
    if not isinstance(frozen, dict) or "gateway_inputs_version" in frozen:
        return False
    if current.get("gateway_inputs_version") != INPUTS_VERSION or not all(key in frozen for key in _BASE_KEYS):
        return False
    old_hash = fingerprint({key: frozen[key] for key in _BASE_KEYS})
    if frozen.get("input_fingerprint") != old_hash or concept.get("input_fingerprint") != old_hash:
        return False
    selected = concept.get("selected")
    if not isinstance(selected, dict) or concept.get("concept_id") != fingerprint({"input": old_hash, "selected": selected})[:20]:
        return False
    for key in ("policy_version", "brief", "writer_sha256", "reviewer_sha256", "language_policy_version"):
        if frozen.get(key) != current.get(key):
            return False
    for key, excluded in (("character", _CHAR_PROSE), ("presentation", _PRESENTATION_PROSE)):
        before, after = frozen.get(key), current.get(key)
        if not isinstance(before, dict) or not isinstance(after, dict):
            return False
        if {k: v for k, v in before.items() if k not in excluded} != {k: v for k, v in after.items() if k not in excluded}:
            return False
    profile_id = current["presentation"].get("profile_id")
    return (
        profile_id in {"book_portal", "orb_portal", "spyglass_portal"}
        and concept.get("presentation_id") == profile_id
        and concept.get("character_id") == current["character"].get("id")
    )
