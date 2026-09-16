"""The final CTA is an independently steerable spoken stage, not pasted operator text."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import run_question_harvest_pipeline as qh
from character_runtime import load_character_registry


def _plan() -> dict:
    body = [f"This clear body idea number {number} reveals another cause." for number in range(1, 10)]
    parts = [
        "Why does this happen?", "Her orb opens the hidden world.", *body,
        "Look again.", "Like and subscribe for more questions.",
    ]
    return {
        "opening_question_spark": parts[0], "entry_transition": parts[1], "body": body,
        "optional_closing": parts[-2], "cta": parts[-1], "full_narration": " ".join(parts),
    }


def test_cta_validator_translates_hint_into_final_narration() -> None:
    presentation = load_character_registry(ROOT / "projects/q_station/characters/registry.json").get("moss_cloaked_crone").presentation
    plan = _plan()
    final = qh.validate_cta(
        "call_to_action",
        {"cta": "Tell us which question we should explore next below."},
        "Ask viewers to say in the comments what the next question should be.",
        plan,
        qh.DurationTarget(30, 40),
        presentation,
    )
    assert final["cta"] == "Tell us which question we should explore next below."
    assert final["full_narration"].endswith(final["cta"])
    assert plan["cta"] != final["cta"]


def test_cta_validator_rejects_literal_operator_hint() -> None:
    presentation = load_character_registry(ROOT / "projects/q_station/characters/registry.json").get("moss_cloaked_crone").presentation
    hint = "Tell viewers to share their experiences in the comments."
    with pytest.raises(qh.StageFailure, match="copied the operator hint"):
        qh.validate_cta(
            "call_to_action", {"cta": "Share their experiences in the comments today."},
            hint, _plan(), qh.DurationTarget(30, 40), presentation,
        )


def test_cta_fingerprint_changes_with_hint_but_not_existing_cta() -> None:
    presentation = load_character_registry(ROOT / "projects/q_station/characters/registry.json").get("moss_cloaked_crone").presentation
    plan = _plan()
    baseline = qh.cta_input_fingerprint(plan, "", presentation)
    plan["cta"] = "A different provisional line entirely."
    assert qh.cta_input_fingerprint(plan, "", presentation) == baseline
    assert qh.cta_input_fingerprint(plan, "Invite comments", presentation) != baseline
