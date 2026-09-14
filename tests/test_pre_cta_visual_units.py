from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from run_question_harvest_pipeline import write_visual_beats_markdown
from align_beats import parse_beats


def test_optional_closing_gets_its_own_final_pre_cta_beat(tmp_path: Path) -> None:
    plan = {
        "body": ["First body sentence.", "Second body sentence."],
        "optional_closing": "A separate final thought.",
        "cta": "Like and subscribe.",
    }
    visual = {"beats": [
        {"beat_id": 1, "visual": "one"},
        {"beat_id": 2, "visual": "two"},
        {"beat_id": 3, "visual": "closing"},
    ]}
    path = write_visual_beats_markdown(tmp_path, plan, visual)
    beats = parse_beats(path)
    assert [beat["narration"] for beat in beats] == [
        "First body sentence.", "Second body sentence.", "A separate final thought.",
    ]
    assert all("Like and subscribe" not in beat["narration"] for beat in beats)
