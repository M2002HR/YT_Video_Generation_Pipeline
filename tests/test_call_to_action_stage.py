"""The final CTA is an independently steerable spoken stage, not pasted operator text."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import run_q_station_pipeline as qstation
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
    final = qstation.validate_cta(
        "call_to_action",
        {"cta": "Tell us which question we should explore next below."},
        "Ask viewers to say in the comments what the next question should be.",
        plan,
        qstation.DurationTarget(30, 40),
        presentation,
    )
    assert final["cta"] == "Tell us which question we should explore next below."
    assert final["full_narration"].endswith(final["cta"])
    assert plan["cta"] != final["cta"]


def test_cta_validator_rejects_literal_operator_hint() -> None:
    presentation = load_character_registry(ROOT / "projects/q_station/characters/registry.json").get("moss_cloaked_crone").presentation
    hint = "Tell viewers to share their experiences in the comments."
    with pytest.raises(qstation.StageFailure, match="copied the operator hint"):
        qstation.validate_cta(
            "call_to_action", {"cta": "Share their experiences in the comments today."},
            hint, _plan(), qstation.DurationTarget(30, 40), presentation,
        )


def test_cta_fingerprint_changes_with_hint_but_not_existing_cta() -> None:
    presentation = load_character_registry(ROOT / "projects/q_station/characters/registry.json").get("moss_cloaked_crone").presentation
    plan = _plan()
    baseline = qstation.cta_input_fingerprint(plan, "", presentation)
    plan["cta"] = "A different provisional line entirely."
    assert qstation.cta_input_fingerprint(plan, "", presentation) == baseline
    assert qstation.cta_input_fingerprint(plan, "Invite comments", presentation) != baseline


def _presentation():
    return load_character_registry(ROOT / "projects/q_station/characters/registry.json").get("moss_cloaked_crone").presentation


def test_cta_validator_rejects_question_glued_to_ask() -> None:
    # The exact failure shape from the failed run: a hook question plus an ask
    # is two sentences, even though each half looks innocent on its own.
    with pytest.raises(qstation.StageFailure, match="exactly one sentence-ending mark"):
        qstation.validate_cta(
            "call_to_action",
            {"cta": "Could you last there? Like this video and subscribe for the next question."},
            "لایک و سابسکرایب", _plan(), qstation.DurationTarget(30, 40), _presentation(),
        )


def _tight_plan() -> dict:
    """A core of exactly 94 words against a 100-word cap: only 6 CTA words fit."""
    plan = _plan()
    plan["body"] = [entry[:-1] + " here." for entry in plan["body"]]
    plan["optional_closing"] = "Look again today."
    assert qstation.word_count(
        " ".join([plan["opening_question_spark"], plan["entry_transition"], *plan["body"], plan["optional_closing"]])
    ) == 94
    return plan


def test_cta_validator_rejects_cta_that_busts_the_episode_cap() -> None:
    # A single well-formed sentence can still fail when the core leaves no room:
    # the message must name the CTA budget, not the whole-narration total.
    with pytest.raises(qstation.StageFailure, match="only 6 fit"):
        qstation.validate_cta(
            "call_to_action",
            {"cta": "Like the video and subscribe for more survival questions."},
            "لایک و سابسکرایب", _tight_plan(), qstation.DurationTarget(30, 40), _presentation(),
        )


def test_cta_validator_accepts_tight_but_fitting_cta() -> None:
    final = qstation.validate_cta(
        "call_to_action",
        {"cta": "Like and subscribe for more questions."},
        "لایک و سابسکرایب", _tight_plan(), qstation.DurationTarget(30, 40), _presentation(),
    )
    assert final["cta"] == "Like and subscribe for more questions."
    assert final["full_narration"].endswith(final["cta"])
    assert final["word_count"] == qstation.DurationTarget(30, 40).word_max


def test_cta_word_room_matches_the_final_gate_ruler() -> None:
    presentation = _presentation()
    plan = _plan()
    room = qstation._cta_word_room(plan, qstation.DurationTarget(30, 40), presentation)
    total_if_maxed = qstation.word_count(plan["full_narration"]) - qstation.word_count(plan["cta"]) + room
    assert total_if_maxed == qstation.DurationTarget(30, 40).word_max
