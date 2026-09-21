from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from body_asset_schedule import build_schedule, valid_schedule


def test_semantic_plan_expands_to_independent_dense_assets() -> None:
    visual_plan = {
        "beats": [
            {"beat_id": 1, "narration_slice": "first short spoken unit", "visual": "a valve"},
            {"beat_id": 2, "narration_slice": "second spoken unit with more explanatory words", "visual": "airflow"},
            {"beat_id": 3, "narration_slice": "third unit", "visual": "masks"},
        ]
    }
    schedule = build_schedule(visual_plan, body_seconds=24)

    assert schedule["target_image_count"] == 30
    assert [asset["beat_id"] for asset in schedule["assets"]] == list(range(1, 31))
    assert {asset["semantic_beat_id"] for asset in schedule["assets"]} == {1, 2, 3}
    assert all("genuinely new composition" in asset["asset_instruction"] for asset in schedule["assets"])
    assert valid_schedule(schedule, visual_plan)


def test_manual_target_is_an_explicit_operational_control() -> None:
    plan = {"beats": [{"beat_id": 1, "narration_slice": "one", "visual": "one"}]}
    assert build_schedule(plan, body_seconds=1, configured_target=42)["target_image_count"] == 42
