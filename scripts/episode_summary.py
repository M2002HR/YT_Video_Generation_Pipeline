#!/usr/bin/env python3
"""One place that answers "what did this episode actually turn out to be?" (T9.4).

Reads only artifacts the pipeline already wrote — the timeline, the provider receipts, the
QC reports and the render stats — so the summary cannot claim something no stage produced.
A field with no artifact behind it is reported as unknown rather than filled in.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _load(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def format_duration(seconds: float | int | None) -> str:
    total = max(0, round(float(seconds or 0)))
    minutes, secs = divmod(total, 60)
    return f"{minutes:d}:{secs:02d}"


def verified_models(video_dir: Path) -> dict[str, list[str]]:
    """Which model each provider confirmed in its own UI, from the receipts (§8, §18).

    A receipt without ``model_verified`` is listed under ``unverified`` — the summary
    reports what was proven, not what was requested.
    """
    verified: dict[str, set[str]] = {}
    unverified: list[str] = []
    receipts = sorted((Path(video_dir) / "pipeline" / "provider_receipts").glob("*.json"))
    for path in receipts:
        payload = _load(path)
        provider = str(payload.get("provider") or "unknown")
        label = str(
            payload.get("actual_model_label")
            or (payload.get("provider_receipt") or {}).get("actual_model_label")
            or payload.get("requested_model")
            or ""
        ).strip()
        if payload.get("model_verified") and label:
            verified.setdefault(provider, set()).add(label)
        else:
            unverified.append(path.stem)
    result = {provider: sorted(labels) for provider, labels in sorted(verified.items())}
    if unverified:
        result["unverified"] = sorted(unverified)
    return result


def build_summary(video_dir: Path, *, artifact: Path | None = None) -> dict[str, Any]:
    video_dir = Path(video_dir)
    timeline = _load(video_dir / "timeline" / "TIMELINE.json")
    stats = _load(video_dir / "render" / "RENDER_STATS.json")
    opening = _load(video_dir / "timing" / "OPENING_TIMING.json")
    timings = _load(video_dir / "timing" / "BEAT_TIMINGS.json")
    stt = timings.get("stt") or {}

    qc_name = "QC_REPORT.json"
    if artifact is not None and Path(artifact).name != "final.mp4":
        qc_name = f"QC_REPORT_{Path(artifact).stem}.json"
    qc = _load(video_dir / "render" / qc_name)

    beats = timeline.get("beats") or []
    video_beats = [beat for beat in beats if str(beat.get("media_type") or "image") == "video"]
    resolution = timeline.get("resolution") or {}

    return {
        "video": video_dir.name,
        "duration_seconds": round(float(timeline.get("duration") or 0.0), 3),
        "beat_count": len(beats),
        "video_beat_count": len(video_beats),
        "image_beat_count": len(beats) - len(video_beats),
        "resolution": (
            f"{resolution.get('width')}x{resolution.get('height')}" if resolution else None
        ),
        "fps": timeline.get("fps"),
        "subtitles": bool(stats.get("subtitles")) if stats else None,
        "opening": {
            "spark_end": opening.get("spark_end"),
            "transition_end": opening.get("transition_end"),
        } if opening else {},
        "stt": {
            "backend": stt.get("backend"),
            "timestamp_source": stt.get("timestamp_source"),
        },
        "verified_models": verified_models(video_dir),
        "qc": {
            "report": qc_name if qc else None,
            "passed": qc.get("passed") if qc else None,
        },
        "resources": {
            "wall_seconds": stats.get("wall_seconds"),
            "realtime_factor": stats.get("realtime_factor"),
            "peak_child_rss_mb": stats.get("peak_child_rss_mb"),
            "threads": (stats.get("threads") or {}).get("encoder"),
            "resource_budget": stats.get("resource_budget"),
            "cpus_available": stats.get("cpus_available"),
        } if stats else {},
    }


def format_caption(summary: dict[str, Any], *, artifact_marker: str = "") -> str:
    """A compact, readable Telegram caption. Unknown values are simply left out."""
    lines = [
        "✅ Video pipeline complete",
        f"🎬 {summary.get('video')}",
        f"⏱ Duration: {format_duration(summary.get('duration_seconds'))}",
    ]
    if summary.get("beat_count"):
        lines.append(
            f"🎞 Beats: {summary['beat_count']} "
            f"({summary.get('video_beat_count', 0)} video · {summary.get('image_beat_count', 0)} image)"
        )
    if summary.get("resolution"):
        lines.append(f"📐 {summary['resolution']} @ {summary.get('fps')}fps")

    models = summary.get("verified_models") or {}
    confirmed = [
        f"{provider}: {', '.join(labels)}"
        for provider, labels in models.items()
        if provider != "unverified"
    ]
    if confirmed:
        lines.append("🔒 Verified models — " + " · ".join(confirmed))
    if models.get("unverified"):
        lines.append(f"⚠️ Unverified receipts: {len(models['unverified'])}")

    stt = summary.get("stt") or {}
    if stt.get("backend"):
        lines.append(f"🗣 Timing: {stt['backend']} / {stt.get('timestamp_source')}")

    qc = summary.get("qc") or {}
    if qc.get("passed") is not None:
        lines.append(f"🔍 QC: {'passed' if qc['passed'] else 'FAILED'}")

    resources = summary.get("resources") or {}
    if resources.get("wall_seconds"):
        detail = f"🧮 Render: {format_duration(resources['wall_seconds'])} wall"
        if resources.get("realtime_factor"):
            detail += f" ({resources['realtime_factor']}x realtime)"
        if resources.get("threads"):
            detail += f" · {resources['threads']} thread(s)"
        if resources.get("peak_child_rss_mb"):
            detail += f" · peak {resources['peak_child_rss_mb']} MB"
        lines.append(detail)

    if artifact_marker:
        lines.append(artifact_marker)
    return "\n".join(lines)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Print the episode summary used for publication.")
    parser.add_argument("video_dir", type=Path)
    parser.add_argument("--caption", action="store_true", help="Print the Telegram caption instead of JSON.")
    args = parser.parse_args()
    summary = build_summary(args.video_dir.expanduser().resolve())
    print(format_caption(summary) if args.caption else json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
