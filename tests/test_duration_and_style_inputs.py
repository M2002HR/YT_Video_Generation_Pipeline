"""The operator's length and style choices must reach the prompts that act on them.

A panel field that is stored but never forwarded is worse than a missing one: the run
looks configured and silently uses the format default.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from run_question_harvest_pipeline import DurationTarget, style_directive  # noqa: E402
from run_full_video_pipeline_qh_wrapper import qh_overrides  # noqa: E402


def test_word_range_follows_the_requested_seconds() -> None:
    short = DurationTarget(25, 30)
    assert short.duration_range == "25–30s"
    assert (short.word_min, short.word_max) == (57, 75)
    assert short.word_target == 66


def test_the_format_default_still_yields_its_documented_range() -> None:
    """40-60s => ~92-150 words is the rule the prompts were written against."""
    default = DurationTarget(40, 60)
    assert (default.word_min, default.word_max) == (92, 150)


def test_prompt_values_fill_every_new_token() -> None:
    values = DurationTarget(25, 30).as_prompt_values()
    assert set(values) == {
        "DURATION_RANGE", "WORD_RANGE", "WORD_TARGET", "BEAT_RANGE", "BEAT_MIN", "BEAT_MAX",
    }
    assert all(value for value in values.values())


def test_beat_count_scales_with_length_and_keeps_the_default() -> None:
    assert (DurationTarget(40, 60).beat_min, DurationTarget(40, 60).beat_max) == (8, 15)
    assert (DurationTarget(25, 30).beat_min, DurationTarget(25, 30).beat_max) == (5, 8)
    # However short the request, a Short still needs enough beats to cut on.
    assert DurationTarget(5, 6).beat_min == 4
    assert DurationTarget(5, 6).beat_max >= 6


def test_the_beat_gate_follows_the_requested_length() -> None:
    """Six beats is right for 25-30s and wrong for 40-60s; the gate must say so."""
    from run_question_harvest_pipeline import StageFailure, validate_script_plan

    body = [f"Beat {index} moves the story along." for index in range(6)]
    plan = {
        "opening_question_spark": "What did Disney animate first?",
        "book_transition": "The answer sits in an older book.",
        "body": body,
        "optional_closing": "And that quiet reel is where the whole studio really began today.",
        "cta": "Follow for more.",
    }
    plan["full_narration"] = " ".join(
        [plan["opening_question_spark"], plan["book_transition"], *body,
         plan["optional_closing"], plan["cta"]]
    )
    accepted = validate_script_plan("retention_edit", dict(plan), DurationTarget(25, 30))
    assert len(accepted["body"]) == 6

    with pytest.raises(StageFailure) as excinfo:
        validate_script_plan("retention_edit", dict(plan), DurationTarget(40, 60))
    assert "8-15" in str(excinfo.value.message)


def test_the_script_prompts_ask_for_the_requested_length() -> None:
    for name in ("01_script_writer.md", "02_retention_editor.md"):
        text = (ROOT / "projects" / "question_harvest" / "prompts" / "pipeline" / name).read_text()
        assert "{{DURATION_RANGE}}" in text or "{{WORD_RANGE}}" in text, name
        assert "40–60s" not in text and "92–150" not in text, f"{name} still hard-codes the default"
        assert "8 and 15" not in text, f"{name} still hard-codes the default beat count"


def test_a_named_style_is_a_binding_reuse_instruction() -> None:
    directive = style_directive("auto", "woodcut_charcoal_warm", "")
    assert "woodcut_charcoal_warm" in directive
    assert "reuse" in directive.lower()
    assert "new" not in directive.split(".")[0].lower()


def test_forcing_a_new_style_forbids_reuse() -> None:
    directive = style_directive("new", "", "charcoal warm paper")
    assert "decision='new'" in directive
    assert "charcoal warm paper" in directive


def test_auto_without_a_hint_leaves_the_choice_open() -> None:
    directive = style_directive("auto", "", "")
    assert "No operator constraint" in directive


def test_a_hint_survives_auto_policy() -> None:
    assert "ink wash" in style_directive("auto", "", "ink wash")


def test_the_word_gate_follows_the_requested_length() -> None:
    """A correct 25-30s script must not be rejected for not being a 40-60s script."""
    from run_question_harvest_pipeline import StageFailure, validate_script_plan

    body = [f"Beat {index} moves the story along." for index in range(8)]
    plan = {
        "opening_question_spark": "What did Disney animate first?",
        "book_transition": "The answer sits in an older book.",
        "body": body,
        "optional_closing": "And that quiet reel is where the whole studio really began.",
        "cta": "Follow for more.",
    }
    plan["full_narration"] = " ".join(
        [plan["opening_question_spark"], plan["book_transition"], *body,
         plan["optional_closing"], plan["cta"]]
    )
    accepted = validate_script_plan("script_draft", dict(plan), DurationTarget(25, 30))
    words = accepted["word_count"]
    assert 57 <= words <= 75, f"fixture counts {words} words; adjust it"

    with pytest.raises(StageFailure) as excinfo:
        validate_script_plan("script_draft", dict(plan), DurationTarget(40, 60))
    assert "40\u201360s" in str(excinfo.value.message)


def test_the_wrapper_forwards_length_and_style(tmp_path: Path) -> None:
    brief = tmp_path / "CREATIVE_BRIEF.json"
    brief.write_text(json.dumps({"_qh": {
        "min_duration_seconds": 25,
        "max_duration_seconds": 30,
        "world_style_id": "woodcut_charcoal_warm",
        "world_style_policy": "reuse",
        "world_style_hint": "warm paper",
        "gemini_image_model": "nano_banana_2",
    }}), encoding="utf-8")
    flags = qh_overrides(brief)
    for expected in (
        "--min-duration-seconds", "25",
        "--max-duration-seconds", "30",
        "--world-style-id", "woodcut_charcoal_warm",
        "--world-style-policy", "reuse",
        "--world-style-hint", "warm paper",
        "--gemini-model", "nano_banana_2",
    ):
        assert expected in flags, expected


def test_an_empty_brief_adds_no_flags(tmp_path: Path) -> None:
    brief = tmp_path / "CREATIVE_BRIEF.json"
    brief.write_text("{}", encoding="utf-8")
    assert qh_overrides(brief) == []
