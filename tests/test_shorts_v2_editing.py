from __future__ import annotations

import json
import shutil
import subprocess
import sys
import wave
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from shorts_v2.contracts import ContractError
from shorts_v2.editing import FrameClock, compile_timeline, render_timeline, solve_geometry


def _plans(count: int, duration: float = 4.0) -> tuple[dict, dict, dict, dict]:
    shots, assets, observations, decisions = [], [], {}, []
    for index in range(count):
        start = duration * index / count
        end = duration * (index + 1) / count
        shot_id, asset_id = f"shot.{index:03d}", f"asset.{index:03d}"
        shots.append({"shot_id": shot_id, "display_order": index, "start": start, "end": end})
        assets.append({"asset_id": asset_id, "shot_ids": [shot_id], "asset_spec_hash": f"{index:064x}"})
        observations[asset_id] = {"width": 1080, "height": 1920, "targets": [{"x": .5, "y": .45}]}
        decisions.append({
            "shot_id": shot_id, "asset_id": asset_id, "transition": "cut",
            "transition_frames": 0, "motion": "hold", "start_scale": 1.0,
            "end_scale": 1.0, "start_center": [.5, .5], "end_center": [.5, .5],
            "easing": "linear", "manual_locks": {},
        })
    return ({"shots": shots, "shot_schedule_hash": "a" * 64},
            {"assets": assets, "manifest_hash": "b" * 64}, observations,
            {"schema_version": 1, "decisions": decisions})


def test_t41_integer_clock_has_complete_half_open_coverage_without_rounding_drift() -> None:
    shot_plan, manifest, observations, edit = _plans(100, duration=3.337)
    timeline = compile_timeline(
        shot_plan=shot_plan, asset_manifest=manifest, observations=observations,
        edit_plan=edit, audio_samples=160176, sample_rate=48000,
        fps_num=30000, fps_den=1001, width=1080, height=1920,
    )
    assert timeline["total_frames"] == FrameClock(30000, 1001).frames_for_samples(160176, 48000)
    assert timeline["segments"][0]["start_frame"] == 0
    assert timeline["segments"][-1]["end_frame"] == timeline["total_frames"]
    assert all(a["end_frame"] == b["start_frame"] for a, b in zip(timeline["segments"], timeline["segments"][1:]))
    assert all(item["end_frame"] > item["start_frame"] for item in timeline["segments"])


def test_t42_many_transitions_never_shorten_master_clock() -> None:
    shot_plan, manifest, observations, edit = _plans(60, duration=12)
    for item in edit["decisions"][1:]:
        item["transition"], item["transition_frames"] = "dissolve", 4
    timeline = compile_timeline(
        shot_plan=shot_plan, asset_manifest=manifest, observations=observations,
        edit_plan=edit, audio_samples=576000, sample_rate=48000, fps_num=30,
        fps_den=1, width=1080, height=1920,
    )
    assert timeline["total_frames"] == 360
    assert timeline["segments"][-1]["end_frame"] == 360
    assert sum(t["duration_frames"] for t in timeline["transitions"]) == 59 * 4
    assert all(t["master_clock_effect"] == "overlay_only_no_duration_change" for t in timeline["transitions"])


def test_t44_geometry_clamps_bounds_reports_noop_and_respects_lock_conflicts() -> None:
    solved = solve_geometry(
        source_width=800, source_height=600, output_width=360, output_height=640,
        start_center=(-2, 9), end_center=(3, -4), start_scale=.2, end_scale=9,
        duration_frames=12, fps_num=30, fps_den=1, max_upscale=2.0,
        max_pan_source_fraction_per_second=.3, manual_locks={},
    )
    for viewport in (solved["start_viewport"], solved["end_viewport"]):
        assert 0 <= viewport["x"] <= 800 - viewport["width"]
        assert 0 <= viewport["y"] <= 600 - viewport["height"]
        assert 360 / viewport["width"] <= 2.0 + 1e-6
    assert solved["corrections"] and solved["pan_speed_clamped"] is True
    noop = solve_geometry(source_width=1080, source_height=1920, output_width=1080, output_height=1920,
                          start_center=(.5, .5), end_center=(.5, .5), start_scale=1, end_scale=1,
                          duration_frames=30, fps_num=30, fps_den=1, max_upscale=1,
                          max_pan_source_fraction_per_second=.3, manual_locks={})
    assert noop["is_noop"] is True
    with pytest.raises(ContractError, match="locked geometry conflict"):
        solve_geometry(source_width=200, source_height=200, output_width=1080, output_height=1920,
                       start_center=(.5, .5), end_center=(.5, .5), start_scale=1, end_scale=1,
                       duration_frames=30, fps_num=30, fps_den=1, max_upscale=1,
                       max_pan_source_fraction_per_second=.3, manual_locks={"scale": True})


@pytest.mark.parametrize("count", [1, 20, 60, 100])
def test_t47_compiler_batches_resources_for_large_shot_counts(count: int) -> None:
    shot_plan, manifest, observations, edit = _plans(count, duration=max(4, count / 4))
    timeline = compile_timeline(
        shot_plan=shot_plan, asset_manifest=manifest, observations=observations,
        edit_plan=edit, audio_samples=int(max(4, count / 4) * 48000), sample_rate=48000,
        fps_num=30, fps_den=1, width=1080, height=1920, segment_batch_size=8,
    )
    assert timeline["resource_plan"]["max_simultaneous_visual_inputs"] <= 2
    assert max(len(batch) for batch in timeline["resource_plan"]["segment_batches"]) <= 8
    assert sum(map(len, timeline["resource_plan"]["segment_batches"])) == count


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="ffmpeg required")
def test_t48_t49_t50_real_local_audiovisual_render_is_atomic_and_reuses_segments(tmp_path: Path) -> None:
    image = tmp_path / "source.png"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=0x315a7d:s=360x640", "-frames:v", "1", str(image)], check=True)
    audio = tmp_path / "audio.wav"
    with wave.open(str(audio), "wb") as handle:
        handle.setnchannels(1); handle.setsampwidth(2); handle.setframerate(48000)
        handle.writeframes(b"\0\0" * 96000)
    shot_plan, manifest, observations, edit = _plans(2, duration=2)
    observations = {key: {**value, "width": 360, "height": 640} for key, value in observations.items()}
    timeline = compile_timeline(shot_plan=shot_plan, asset_manifest=manifest, observations=observations,
                                edit_plan=edit, audio_samples=96000, sample_rate=48000,
                                fps_num=30, fps_den=1, width=360, height=640)
    sources = {f"asset.{index:03d}": image for index in range(2)}
    output = tmp_path / "render" / "preview.mp4"
    receipt = render_timeline(timeline, asset_paths=sources, narration_path=audio, output_path=output,
                              cache_dir=tmp_path / "cache", min_free_bytes=1)
    assert output.exists() and receipt["validated"] is True and receipt["audio_streams"] == 1
    assert receipt["duration_drift_frames"] <= 1 and receipt["max_simultaneous_visual_inputs"] <= 2
    second = render_timeline(timeline, asset_paths=sources, narration_path=audio, output_path=tmp_path / "render/second.mp4",
                             cache_dir=tmp_path / "cache", min_free_bytes=1)
    assert second["segments_reused"] == 2
    accepted = tmp_path / "accepted.json"; accepted.write_text(json.dumps({"revision_id": "healthy"}))
    with pytest.raises(ContractError, match="free disk"):
        render_timeline(timeline, asset_paths=sources, narration_path=audio, output_path=tmp_path / "render/fail.mp4",
                        cache_dir=tmp_path / "cache", min_free_bytes=10**18)
    assert json.loads(accepted.read_text())["revision_id"] == "healthy"
    assert not (tmp_path / "render/fail.mp4").exists()
