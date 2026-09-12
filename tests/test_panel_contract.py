from __future__ import annotations

import sys
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from panel_contract import defaults, launch_schema
from panel_page import launch_form


def test_schema_exposes_every_launch_configuration_group() -> None:
    schema = launch_schema([{"value": "question_harvest", "label": "Question Harvest"}], ["ink_001"])
    assert [group["id"] for group in schema["groups"]] == [
        "episode", "format", "branding", "character", "visual", "opening", "voice", "music",
        "subtitles", "transitions", "motion", "sfx", "delivery", "providers",
    ]
    names = {field["name"] for group in schema["groups"] for field in group["fields"]}
    assert {"topic", "min_duration_seconds", "voice", "music_providers", "sfx_enabled", "motion_enabled", "motion_supersample", "telegram_original"} <= names


def test_subtitle_controls_are_colocated_and_gated() -> None:
    schema = launch_schema([{"value": "q_station", "label": "Q Station"}], [])
    group = next(item for item in schema["groups"] if item["id"] == "subtitles")
    fields = {field["name"]: field for field in group["fields"]}
    assert {"show_subtitles", "word_highlight", "reserve_subtitle_space", "motion_subtitle_avoidance"} <= set(fields)
    assert fields["word_highlight"]["requires"] == {"field": "show_subtitles", "value": True}
    assert fields["reserve_subtitle_space"]["requires"] == {"field": "show_subtitles", "value": True}
    assert fields["subtitle_font_size"]["max"] == 300


def test_schema_defaults_match_the_server_launch_contract() -> None:
    values = defaults(launch_schema([{"value": "question_harvest", "label": "Question Harvest"}], []))
    assert values["min_duration_seconds"] == 40
    assert values["max_duration_seconds"] == 60
    assert values["music_providers"] == ["freesound", "mixkit", "pixabay"]
    assert values["word_highlight"] is True
    assert values["reserve_subtitle_space"] is True
    assert values["beat_image_qc_disabled"] is False
    assert values["image_qc_correction_policy"] == "0"
    assert values["motion_enabled"] is True
    assert "locked_text" not in values


def test_branding_defaults_put_the_question_below_a_top_right_logo() -> None:
    schema = launch_schema([{"value": "q_station", "label": "Q Station"}], [])
    group = next(item for item in schema["groups"] if item["id"] == "branding")
    fields = {field["name"]: field for field in group["fields"]}
    assert fields["show_logo"]["default"] is False
    assert fields["logo_upload_id"]["default"] == ""
    assert fields["logo_position"]["default"] == "top_right"
    assert fields["show_title"]["default"] is True
    assert fields["title_position"]["default"] == "below_logo"
    assert fields["title_max_words_per_line"]["default"] == 7
    assert fields["title_max_words_per_line"]["max"] == 100
    assert fields["title_line_spacing"]["default"] == 6
    assert {option["value"] for option in fields["title_font"]["options"]} >= {"Roboto", "Rubik", "DejaVu Sans"}
    assert fields["logo_custom_x_percent"]["requires"][1] == {"field": "logo_position", "value": "custom"}


def test_visual_group_exposes_stage_aware_image_qc_policy() -> None:
    schema = launch_schema([{"value": "q_station", "label": "Q Station"}], [])
    visual = next(group for group in schema["groups"] if group["id"] == "visual")
    fields = {field["name"]: field for field in visual["fields"]}
    assert fields["beat_image_qc_disabled"]["default"] is False
    policy = fields["image_qc_correction_policy"]
    assert policy["default"] == "0"
    assert [option["value"] for option in policy["options"]] == ["0", "1", "2", "strict"]
    assert policy["requires"] == {"field": "beat_image_qc_disabled", "value": False}
    assert policy["hideWhenGated"] is True


def test_react_schema_keeps_every_legacy_launch_control() -> None:
    """Moving the form into React must not silently drop an existing pipeline input."""
    legacy = set(re.findall(r"name=[\"']?([a-zA-Z0-9_]+)", launch_form("", "")))
    schema = launch_schema([{"value": "question_harvest", "label": "Question Harvest"}], [])
    current = {
        field["name"]
        for group in schema["groups"]
        for field in group["fields"]
        if field["type"] != "readonly"
    }
    assert current == legacy


def test_subtitle_offset_fields_stay_gated_on_custom_and_fonts_starred() -> None:
    schema = launch_schema([{"value": "q_station", "label": "Q Station"}], [])
    fields = {
        field["name"]: field
        for group in schema["groups"]
        for field in group["fields"]
    }
    expected_requirements = [
        {"field": "show_subtitles", "value": True},
        {"field": "subtitle_position", "value": "custom"},
    ]
    assert fields["subtitle_offset_value"]["requires"] == expected_requirements
    assert fields["subtitle_offset_unit"]["requires"] == expected_requirements
    options = fields["subtitle_font"]["options"]
    assert [option["value"] for option in options[:3]] == ["Roboto", "Open Sans", "Lato"]
    assert all(option.get("recommended") is True for option in options[:17])
    assert all(option["label"] == option["value"] for option in options)
    assert not any(option.get("recommended") for option in options[17:])
    assert len(options) >= 24
