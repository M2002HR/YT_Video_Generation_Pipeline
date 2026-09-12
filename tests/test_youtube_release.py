from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from release_youtube_short import (  # noqa: E402
    CHANNEL_DEFAULTS,
    build_upload_markdown,
    original_image_contract,
    thumbnail_generation_prompt,
    validate_or_repair_metadata,
    validate_metadata,
    video_caption,
)

SPEC = importlib.util.spec_from_file_location("release_panel", SCRIPTS / "video_control_panel.py")
assert SPEC and SPEC.loader
panel = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = panel
SPEC.loader.exec_module(panel)


def sample_metadata() -> dict:
    return {
        "title": "Why Black Swans Break Our Forecasts",
        "title_options": [
            "The Surprise Your Model Never Saw",
            "Taleb's Black Swan in 60 Seconds",
            "The Risk No Forecast Can See",
        ],
        "description": "A Black Swan is an event outside normal expectations with an outsized impact. This short explains why hindsight makes surprise look predictable and why robust plans leave room for uncertainty. Q Station turns everyday questions into clear visual stories. #BlackSwan #DecisionMaking",
        "tags": ["black swan", "Nassim Taleb", "uncertainty", "forecasting"],
        "category": "Education",
        "category_id": "27",
        "language": "en",
        "default_audio_language": "en",
        "upload_settings": {"privacy_recommendation": "private"},
        "manual_review": [{"field": "altered content", "recommendation": "Confirm", "reason": "AI imagery needs uploader review."}],
        "thumbnail_prompt": "Create a vertical 9:16 editorial illustration of one black swan disrupting a neat field of white swans, high contrast, one clear focal subject and calm negative space above it. No written words, letters, logos, watermark, UI, border, collage, or split screen.",
        "thumbnail_overlay_text": "Plan for surprise",
        "related_video_note": "Choose a public or unlisted related video from this channel if one is relevant.",
    }


def test_metadata_contract_applies_channel_defaults_and_youtube_limits() -> None:
    metadata = validate_metadata(sample_metadata(), CHANNEL_DEFAULTS)
    assert metadata["title"] == "Why Black Swans Break Our Forecasts"
    assert metadata["upload_settings"]["category_id"] == "27"
    assert len(",".join(metadata["tags"])) < 500
    assert {item["field"].casefold() for item in metadata["manual_review"]} >= {
        "audience", "age restriction", "paid promotion", "altered or synthetic content"
    }
    assert len(video_caption(metadata, {"quality_check": {"passed": True}})) <= 1024


def test_metadata_contract_refuses_overlong_youtube_title() -> None:
    metadata = sample_metadata()
    metadata["title"] = "x" * 101
    with pytest.raises(ValueError, match="title"):
        validate_metadata(metadata, CHANNEL_DEFAULTS)


def test_metadata_contract_normalizes_common_non_array_list_formatting() -> None:
    metadata = sample_metadata()
    metadata["tags"] = "black swan, forecasting"  # type: ignore[assignment]
    metadata["title_options"] = (
        "The Surprise Your Model Never Saw\n"
        "Taleb's Black Swan in 60 Seconds\n"
        "The Risk No Forecast Can See"
    )
    normalized = validate_metadata(metadata, CHANNEL_DEFAULTS)
    assert normalized["tags"] == ["black swan", "forecasting"]
    assert len(normalized["title_options"]) == 3


def test_metadata_contract_refuses_redundant_title_option() -> None:
    metadata = sample_metadata()
    metadata["title_options"][0] = metadata["title"]
    with pytest.raises(ValueError, match="title"):
        validate_metadata(metadata, CHANNEL_DEFAULTS)


def test_metadata_schema_repair_recovers_nonrecoverable_model_shape() -> None:
    malformed = sample_metadata()
    malformed["title_options"] = "Only one title option"  # type: ignore[assignment]

    class FakeJobs:
        def run(self, *_args, **_kwargs):
            return type("Result", (), {
                "answer": json.dumps(sample_metadata()),
                "job_id": "schema-repair-job",
            })()

    metadata, repairs = validate_or_repair_metadata(FakeJobs(), malformed, CHANNEL_DEFAULTS, [])  # type: ignore[arg-type]
    assert metadata["title"] == sample_metadata()["title"]
    assert repairs == ["schema-repair-job"]


def test_thumbnail_prompt_makes_final_render_frames_primary() -> None:
    manifest = [
        {
            "role": "thumbnail_rendered_opening_frame",
            "purpose": "PRIMARY visual truth: final render texture, palette, medium and atmosphere",
        },
        {
            "role": "thumbnail_character_identity",
            "purpose": "Identity only if the episode's host is used; never copy the sheet layout",
        },
    ]
    prompt = thumbnail_generation_prompt(sample_metadata(), manifest)
    assert "rendered-frame attachments are PRIMARY" in prompt
    assert "texture, rendering medium, palette" in prompt
    assert "thumbnail_character_identity" in prompt
    assert "never copy the sheet" in prompt


def test_release_reuses_the_episode_image_contract_not_project_default(tmp_path: Path) -> None:
    video = tmp_path / "videos" / "901_release"
    (video / "launch").mkdir(parents=True)
    (video / "launch/LAUNCH_REQUEST.json").write_text(json.dumps({
        "qh": {
            "gemini_image_model": "nano_banana_2",
            "image_qc_correction_policy": "1",
            "chatgpt_fallback_mode": "auto",
        },
    }), encoding="utf-8")
    contract = original_image_contract(video, "q_station")
    assert contract == {
        "model": "nano_banana_2",
        "qc_correction_policy": "1",
        "chatgpt_fallback_mode": "auto",
    }


def test_upload_markdown_contains_copy_ready_description_and_manual_review() -> None:
    metadata = validate_metadata(sample_metadata(), CHANNEL_DEFAULTS)
    thumbnail = {"selected": {"width": 1080, "height": 1920}, "quality_check": {"passed": True}}
    context = {"run": {"duration_seconds": 60, "resolution": {"width": 1080, "height": 1920}, "aspect_ratio": "9:16"}, "music": {"license": "verify before publication"}}
    markdown = build_upload_markdown(metadata, thumbnail, context)
    assert metadata["description"] in markdown
    assert "Must confirm manually" in markdown
    assert "verify before publication" in markdown


def test_release_gate_requires_done_state_master_and_passing_qc(tmp_path: Path) -> None:
    project = tmp_path / "videos" / "901_release"
    master = project / "assets/renders/polished.mp4"
    master.parent.mkdir(parents=True)
    master.write_bytes(b"master")
    (project / "pipeline").mkdir()
    (project / "render").mkdir()
    (project / "pipeline/FINALIZATION_RUNTIME_STATE.json").write_text(json.dumps({"status": "DONE"}), encoding="utf-8")
    (project / "render/QC_REPORT_polished.json").write_text(json.dumps({"passed": True}), encoding="utf-8")
    allowed, reason = panel.release_eligibility({"status": "DONE", "external": False, "pid": None}, project)
    assert allowed is True and reason == ""
    allowed, reason = panel.release_eligibility({"status": "FAILED", "external": False, "pid": None}, project)
    assert allowed is False and "DONE" in reason
