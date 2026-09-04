#!/usr/bin/env python3
"""Resume-safe, no-SFX completion path from timing data to Telegram publish.

Every stage reports to Telegram at the same level of detail as the Question Harvest
orchestrator (T9.3): start, finish, duration, artifact, and the failure text when a stage
stops. The final message carries the polished file itself plus a summary built from the
artifacts — duration, beat counts, the models each provider confirmed, and what the render
actually cost in wall time and memory (T9.4).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from episode_summary import build_summary, format_caption  # noqa: E402
from pipeline_notifier import PipelineNotifier, format_duration  # noqa: E402


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def save(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def execute(
    name: str,
    command: list[str],
    state: dict[str, Any],
    path: Path,
    *,
    notifier: PipelineNotifier | None = None,
    artifact: Path | None = None,
    video: Path | None = None,
    position: str = "",
) -> None:
    """Run one stage, persist the transition, and report both ends of it to Telegram."""
    human = name.replace("_", " ").title()
    title = f"{position} · {human}" if position else human
    started_wall, started = now(), time.perf_counter()
    event: dict[str, Any] = {"stage": name, "started_at": started_wall, "command": command}
    print(f"▶ {name}", flush=True)
    if notifier is not None:
        notifier.send(title, ["▶ Stage started"])
    try:
        subprocess.run(command, cwd=ROOT, check=True)
    except subprocess.CalledProcessError as exc:
        elapsed = round(time.perf_counter() - started, 3)
        event.update({"status": "FAILED", "ended_at": now(), "elapsed_seconds": elapsed, "returncode": exc.returncode})
        state["events"].append(event)
        state["status"] = "FAILED"
        save(path, state)
        print(f"✘ {name} exited {exc.returncode}", flush=True)
        if notifier is not None:
            notifier.failure(title, elapsed, f"{name} exited with code {exc.returncode}")
        raise
    elapsed = round(time.perf_counter() - started, 3)
    event.update({"status": "DONE", "ended_at": now(), "elapsed_seconds": elapsed})
    if artifact is not None and artifact.is_file():
        event["artifact"] = str(artifact.relative_to(video)) if video else str(artifact)
        event["artifact_bytes"] = artifact.stat().st_size
    state["events"].append(event)
    state["status"] = "RUNNING"
    save(path, state)
    print(f"✔ {name} in {format_duration(elapsed)}", flush=True)
    if notifier is not None:
        notifier.stage_complete(title, elapsed, artifact=str(event.get("artifact") or ""))


def main() -> None:
    parser = argparse.ArgumentParser(description="Complete a prepared video from beat timings through Telegram publication.")
    parser.add_argument("video_dir", type=Path)
    parser.add_argument("--publish", action="store_true", help="Send the passing polished output to Telegram.")
    parser.add_argument("--allow-sfx", action="store_true", help="Keep explicitly configured SFX; default is no SFX.")
    parser.add_argument("--skip-render", action="store_true", help="Resume from an existing baseline render after an externally monitored render job.")
    parser.add_argument("--commit", action="store_true", help="Commit and push the finished artifacts after QC (§76, §111).")
    parser.add_argument("--no-notify", action="store_true", help="Run without Telegram stage reports.")
    parser.add_argument(
        "--resource-budget",
        type=float,
        default=float(os.getenv("YT_RENDER_RESOURCE_BUDGET", "0.8")),
        help="Share of the machine the render may use (default 0.8).",
    )
    args = parser.parse_args()
    video = args.video_dir.expanduser().resolve()
    if not (video / "timing" / "BEAT_TIMINGS.json").is_file():
        raise FileNotFoundError("Beat timings are required before completion.")
    profile = video / "audio_mix" / "AUDIO_MIX_PROFILE.json"
    if not profile.is_file():
        raise FileNotFoundError("AUDIO_MIX_PROFILE.json is required before completion.")
    if not args.allow_sfx:
        data = json.loads(profile.read_text(encoding="utf-8"))
        data.setdefault("sfx", {})["enabled"] = False
        data["sfx"]["events"] = []
        profile.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    state_path = video / "pipeline" / "FINALIZATION_RUNTIME_STATE.json"
    state: dict[str, Any] = {"schema_version": 1, "video": video.name, "started_at": now(), "status": "RUNNING", "events": []}
    save(state_path, state)
    topic = ""
    try:
        topic = str(json.loads((video / "launch" / "LAUNCH_REQUEST.json").read_text(encoding="utf-8")).get("topic") or "")
    except (OSError, ValueError):
        pass
    notifier = None if args.no_notify else PipelineNotifier(video_id=video.name, topic=topic)
    #: The completion half, in order, so each notification says where the run is.
    sequence = ["build_timeline", "render_baseline", "qc_baseline", "polish_audio", "qc_polished"]
    if args.commit:
        sequence.append("git_commit_push")
    if args.publish:
        sequence.append("publish_telegram")

    def step(name: str, command: list[str], **kw: Any) -> None:
        position = f"step {sequence.index(name) + 1}/{len(sequence)}" if name in sequence else ""
        execute(
            name, command, state, state_path,
            notifier=notifier, video=video, position=position, **kw,
        )

    managed_python = ROOT / ".venv" / "bin" / "python"
    py = str(managed_python) if managed_python.is_file() else sys.executable
    step("build_timeline", [py, "scripts/build_timeline.py", str(video)],
         artifact=video / "timeline" / "TIMELINE.json")
    baseline = video / "assets" / "renders" / "final.mp4"
    if args.skip_render:
        if not baseline.is_file() or baseline.stat().st_size == 0:
            raise FileNotFoundError("--skip-render requires a non-empty assets/renders/final.mp4.")
        state["events"].append({"stage": "render_baseline", "status": "REUSED", "ended_at": now(), "artifact": str(baseline.relative_to(video))})
        save(state_path, state)
        if notifier is not None:
            notifier.send("Render Baseline", ["↻ Reused existing baseline render", baseline.name])
    else:
        # render_video applies its own nice/ionice and thread budget, so the stage just
        # passes the budget through instead of wrapping the command again.
        step(
            "render_baseline",
            [py, "scripts/render_video.py", str(video), "--output", str(baseline),
             "--resource-budget", f"{args.resource_budget:.3f}"],
            artifact=baseline,
        )
    step("qc_baseline", [py, "scripts/qc_render.py", str(video), "--input", str(baseline), "--decode"],
         artifact=video / "render" / "QC_REPORT.json")
    polished = video / "assets" / "renders" / "polished.mp4"
    step("polish_audio", [py, "scripts/polish_audio.py", str(video), "--output", str(polished)],
         artifact=polished)
    step("qc_polished", [py, "scripts/qc_render.py", str(video), "--input", str(polished), "--decode"],
         artifact=video / "render" / "QC_REPORT_polished.json")

    # Git publication runs only after both QC gates passed, and re-running it is a no-op
    # when nothing changed (§76, §111).
    if args.commit:
        step(
            "git_commit_push",
            [py, "scripts/commit_video_artifacts.py", str(video),
             "--full-state", str(state_path), "--started-at", state["started_at"]]
            + ([] if os.getenv("YT_GIT_PUSH_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"} else ["--no-push"]),
            artifact=video / "pipeline" / "GIT_PUBLISH_STATE.json",
        )
        state = json.loads(state_path.read_text(encoding="utf-8"))

    if args.publish:
        step("publish_telegram",
             [py, "scripts/publish_to_telegram.py", str(video), "--input", str(polished)],
             artifact=video / "publish" / "TELEGRAM_PUBLISH_STATE.json")

    state["status"] = "DONE"
    state["completed_at"] = now()
    state["total_elapsed_seconds"] = round(sum(float(x.get("elapsed_seconds", 0)) for x in state["events"]), 3)
    summary = build_summary(video, artifact=polished)
    state["summary"] = summary
    save(state_path, state)
    if notifier is not None:
        notifier.send(
            "Completion pipeline finished",
            [
                format_caption(summary),
                f"⏱ Completion stages: {format_duration(state['total_elapsed_seconds'])}",
            ],
        )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("COMPLETION PIPELINE: PASS")


if __name__ == "__main__":
    main()
