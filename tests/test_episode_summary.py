from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from episode_summary import build_summary, format_caption, verified_models  # noqa: E402


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_compact_delivery_inherits_the_polished_qc_gate(tmp_path: Path) -> None:
    video = tmp_path / "videos" / "007_topic"
    write_json(video / "timeline/TIMELINE.json", {"duration": 60, "beats": []})
    write_json(video / "render/QC_REPORT_polished.json", {"passed": True})

    summary = build_summary(video, artifact=video / "assets/renders/telegram_low.mp4")

    assert summary["qc"] == {"report": "QC_REPORT_polished.json", "passed": True}
    assert "🔍 QC: passed" in format_caption(summary)


def test_verified_model_caption_uses_a_human_model_name(tmp_path: Path) -> None:
    video = tmp_path / "video"
    write_json(
        video / "pipeline/provider_receipts/gemini_beat_001.json",
        {
            "provider": "gemini",
            "model_verified": True,
            "requested_model": "nano_banana_2",
            "actual_model_label": "Open mode picker, currently Flash",
        },
    )

    assert verified_models(video)["gemini"] == ["Nano Banana 2"]
