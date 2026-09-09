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
    assert [group["id"] for group in schema["groups"]] == ["episode", "format", "visual", "audio", "sfx", "motion", "publish", "providers"]
    names = {field["name"] for group in schema["groups"] for field in group["fields"]}
    assert {"topic", "min_duration_seconds", "voice", "music_providers", "sfx_enabled", "motion_enabled", "motion_supersample", "telegram_original"} <= names


def test_schema_defaults_match_the_server_launch_contract() -> None:
    values = defaults(launch_schema([{"value": "question_harvest", "label": "Question Harvest"}], []))
    assert values["min_duration_seconds"] == 40
    assert values["max_duration_seconds"] == 60
    assert values["music_providers"] == ["freesound", "mixkit", "pixabay"]
    assert values["word_highlight"] is True
    assert values["reserve_subtitle_space"] is True
    assert values["motion_enabled"] is True
    assert "locked_text" not in values


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
