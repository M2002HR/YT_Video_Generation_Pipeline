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

from episode_summary import build_summary  # noqa: E402
from pipeline_notifier import PipelineNotifier, format_duration  # noqa: E402
from pipeline_stages import stage_title  # noqa: E402


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def completion_stage_sequence(
    *,
    motion_enabled: bool,
    sfx_enabled: bool,
    sfx_plan_enabled: bool,
    publish: bool,
    telegram_low_size: bool,
    commit: bool,
) -> list[str]:
    """Return the exact resumable stage list for the frozen launch configuration."""
    sequence = ["build_timeline"]
    if motion_enabled:
        sequence.append("motion_director")
    if sfx_plan_enabled:
        sequence.append("sfx_plan")
    sequence.extend(["render_baseline", "qc_baseline"])
    if sfx_enabled:
        sequence.append("sfx_acquire")
    sequence.extend(["polish_audio", "qc_polished"])
    if publish and telegram_low_size:
        sequence.append("telegram_compress")
    if commit:
        sequence.append("git_commit_push")
    if publish:
        sequence.append("publish_telegram")
    return sequence


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
    manages_own_progress: bool = False,
) -> None:
    """Run one stage, persist the transition, and report both ends of it to Telegram."""
    title = stage_title(name)
    started_wall, started = now(), time.perf_counter()
    event: dict[str, Any] = {"stage": name, "started_at": started_wall, "command": command, "status": "RUNNING"}
    state["events"].append(event)
    state["status"] = "RUNNING"
    save(path, state)
    print(f"▶ {name}", flush=True)
    stage_message = None
    if notifier is not None and not manages_own_progress:
        stage_message = notifier.stage_started(title)
    try:
        subprocess.run(command, cwd=ROOT, check=True)
    except subprocess.CalledProcessError as exc:
        elapsed = round(time.perf_counter() - started, 3)
        event.update({"status": "FAILED", "ended_at": now(), "elapsed_seconds": elapsed, "returncode": exc.returncode})
        state["status"] = "FAILED"
        save(path, state)
        print(f"✘ {name} exited {exc.returncode}", flush=True)
        if notifier is not None:
            notifier.failure(title, elapsed, f"{name} exited with code {exc.returncode}")
        raise
    elapsed = round(time.perf_counter() - started, 3)
    if artifact is not None and (not artifact.is_file() or artifact.stat().st_size <= 0):
        message = f"{name} returned successfully but did not produce a non-empty {artifact}"
        event.update({"status": "FAILED_VALIDATION", "ended_at": now(), "elapsed_seconds": elapsed, "error": message})
        state["status"] = "FAILED"
        save(path, state)
        print(f"✘ {message}", flush=True)
        if notifier is not None:
            notifier.failure(title, elapsed, message)
        raise RuntimeError(message)
    event.update({"status": "DONE", "ended_at": now(), "elapsed_seconds": elapsed})
    if artifact is not None and artifact.is_file():
        event["artifact"] = str(artifact.relative_to(video)) if video else str(artifact)
        event["artifact_bytes"] = artifact.stat().st_size
    state["status"] = "RUNNING"
    save(path, state)
    print(f"✔ {name} in {format_duration(elapsed)}", flush=True)
    if notifier is not None and not manages_own_progress:
        lines = ["✅ Stage complete", f"⏱ Duration: {format_duration(elapsed)}"]
        if event.get("artifact"):
            lines.append(f"📄 Saved: {event['artifact']}")
        if name == "motion_director" and video is not None:
            try:
                motion_qc = json.loads((video / "motion" / "MOTION_QC.json").read_text(encoding="utf-8"))
                lines.extend([
                    f"🎬 {motion_qc.get('beats', 0)} image beats · {motion_qc.get('micro_shots', 0)} micro-shots",
                    f"✂️ {motion_qc.get('hard_cut_count', 0)} cuts/reframes · {motion_qc.get('transition_count', 0)} transitions",
                    f"🛡 Motion QC: {'PASS' if motion_qc.get('passed') else 'WARN'}",
                ])
            except (OSError, ValueError, TypeError):
                pass
        notifier.stage_update(stage_message, title, lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Complete a prepared video from beat timings through Telegram publication.")
    parser.add_argument("video_dir", type=Path)
    parser.add_argument("--publish", action="store_true", help="Send the passing polished output to Telegram.")
    parser.add_argument("--telegram-low-size", action=argparse.BooleanOptionalAction, default=True, help="Create and send the compressed Telegram copy (default: enabled).")
    parser.add_argument("--telegram-original", action="store_true", help="Also send the original polished file to Telegram.")
    parser.add_argument("--allow-sfx", action="store_true", help="Enable SFX stages when configuration permits it.")
    parser.add_argument("--sfx-config", type=Path, help="Frozen launch/brief JSON containing the non-secret _sfx settings.")
    parser.add_argument("--motion-config", type=Path, help="Frozen launch/brief JSON containing _motion settings.")
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
    sfx_config: dict[str, Any] = {}
    if args.sfx_config:
        try:
            sfx_config = (json.loads(args.sfx_config.read_text(encoding="utf-8")).get("_sfx") or {})
        except (OSError, ValueError) as exc:
            raise ValueError(f"SFX configuration is unreadable: {args.sfx_config}") from exc
    sfx_enabled = bool(args.allow_sfx or sfx_config.get("enabled", False))
    if not sfx_enabled:
        data = json.loads(profile.read_text(encoding="utf-8"))
        data.setdefault("sfx", {})["enabled"] = False
        data["sfx"]["events"] = []
        profile.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    state_path = video / "pipeline" / "FINALIZATION_RUNTIME_STATE.json"
    previous: dict[str, Any] = {}
    try:
        previous = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    previous_status = {
        str(event.get("stage")): str(event.get("status"))
        for event in previous.get("events") or []
        if isinstance(event, dict) and event.get("stage")
    }
    state: dict[str, Any] = {"schema_version": 1, "video": video.name, "started_at": now(), "status": "RUNNING", "events": []}
    save(state_path, state)
    topic = ""
    try:
        topic = str(json.loads((video / "launch" / "LAUNCH_REQUEST.json").read_text(encoding="utf-8")).get("topic") or "")
    except (OSError, ValueError):
        pass
    notifier = None if args.no_notify else PipelineNotifier(video_id=video.name, topic=topic)
    #: The completion half, in order, so each notification says where the run is.
    motion_config: dict[str, Any] = {}
    motion_config_path = args.motion_config or (video / "launch" / "CREATIVE_BRIEF.json")
    if motion_config_path.is_file():
        try: motion_config = (json.loads(motion_config_path.read_text(encoding="utf-8")).get("_motion") or {})
        except (OSError, ValueError) as exc: raise ValueError(f"Motion configuration is unreadable: {motion_config_path}") from exc
    motion_enabled = bool(motion_config.get("enabled", True))
    sfx_plan_enabled = sfx_enabled and sfx_config.get("planner_enabled", True)
    sequence = completion_stage_sequence(
        motion_enabled=motion_enabled, sfx_enabled=sfx_enabled, sfx_plan_enabled=sfx_plan_enabled,
        publish=args.publish, telegram_low_size=args.telegram_low_size, commit=args.commit,
    )

    def step(name: str, command: list[str], **kw: Any) -> None:
        position = f"step {sequence.index(name) + 1}/{len(sequence)}" if name in sequence else ""
        artifact = kw.get("artifact")
        if (
            isinstance(artifact, Path)
            and artifact.is_file()
            and artifact.stat().st_size > 0
            and previous_status.get(name) in {"DONE", "REUSED"}
        ):
            event = {"stage": name, "status": "REUSED", "ended_at": now(), "elapsed_seconds": 0.0, "artifact": str(artifact.relative_to(video))}
            state["events"].append(event)
            save(state_path, state)
            print(f"↻ {name} reused — {event['artifact']}", flush=True)
            if notifier is not None:
                notifier.stage_reused(stage_title(name), ["↻ Reused existing artifact", f"📄 {event['artifact']}"])
            return
        execute(
            name, command, state, state_path,
            notifier=notifier, video=video, position=position, **kw,
        )

    managed_python = ROOT / ".venv" / "bin" / "python"
    py = str(managed_python) if managed_python.is_file() else sys.executable
    step("build_timeline", [py, "scripts/build_timeline.py", str(video)],
         artifact=video / "timeline" / "TIMELINE.json")
    if motion_enabled:
        step("motion_director", [py, "scripts/run_motion_director.py", str(video), "--settings", str(motion_config_path)] if motion_config_path.is_file() else [py, "scripts/run_motion_director.py", str(video)], artifact=video / "motion" / "MOTION_PLAN.json")
    if sfx_enabled and sfx_config.get("planner_enabled", True):
        step("sfx_plan", [py, "scripts/run_sfx_planner.py", str(video), "--style", str(sfx_config.get("planner_style", "restrained")), "--max-events-per-minute", str(sfx_config.get("max_events_per_minute", 4)), "--minimum-gap-seconds", str(sfx_config.get("minimum_gap_seconds", 2))], artifact=video / "sfx" / "SFX_PLAN.json")
    baseline = video / "assets" / "renders" / "final.mp4"
    if args.skip_render:
        if not baseline.is_file() or baseline.stat().st_size == 0:
            raise FileNotFoundError("--skip-render requires a non-empty assets/renders/final.mp4.")
        state["events"].append({"stage": "render_baseline", "status": "REUSED", "ended_at": now(), "artifact": str(baseline.relative_to(video))})
        save(state_path, state)
        if notifier is not None:
            notifier.stage_reused(
                stage_title("render_baseline"),
                ["↻ Reused existing baseline render", baseline.name],
            )
    else:
        # render_video applies its own nice/ionice and thread budget, so the stage just
        # passes the budget through instead of wrapping the command again.
        step(
            "render_baseline",
            [py, "scripts/render_video.py", str(video), "--output", str(baseline),
             "--resource-budget", f"{args.resource_budget:.3f}"],
            artifact=baseline,
            manages_own_progress=True,
        )
    step("qc_baseline", [py, "scripts/qc_render.py", str(video), "--input", str(baseline), "--decode"],
         artifact=video / "render" / "QC_REPORT.json")
    if sfx_enabled:
        acquire = [py, "scripts/run_sfx_acquire.py", str(video), "--local-threshold", str(sfx_config.get("local_match_threshold", .35)), "--license-policy", "cc0_by" if sfx_config.get("license_policy") == "cc0_by" else "cc0", "--candidate-count", str(sfx_config.get("candidate_count", 12)), "--max-queries-per-event", str(sfx_config.get("max_queries_per_event", 2)), "--default-gain-db", str(sfx_config.get("default_gain_db", -9)), "--min-gain-db", str(sfx_config.get("min_gain_db", -20)), "--max-gain-db", str(sfx_config.get("max_gain_db", -3))]
        if not sfx_config.get("freesound_enabled", True): acquire.append("--no-freesound-enabled")
        step("sfx_acquire", acquire, artifact=video / "sfx" / "SFX_SELECTION.json")
    polished = video / "assets" / "renders" / "polished.mp4"
    step("polish_audio", [py, "scripts/polish_audio.py", str(video), "--output", str(polished)],
         artifact=polished)
    step("qc_polished", [py, "scripts/qc_render.py", str(video), "--input", str(polished), "--decode"],
         artifact=video / "render" / "QC_REPORT_polished.json")

    compressed = video / "assets" / "renders" / "telegram_low.mp4"
    if args.publish and args.telegram_low_size:
        step("telegram_compress", [py, "scripts/compress_for_telegram.py", str(video), "--input", str(polished), "--output", str(compressed)], artifact=compressed)

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
        publish_command = [py, "scripts/publish_to_telegram.py", str(video)]
        if args.telegram_low_size:
            publish_command += ["--input", str(compressed), "--kind", "compressed"]
        if args.telegram_original:
            publish_command += ["--input", str(polished), "--kind", "original"]
        if not args.telegram_low_size and not args.telegram_original:
            raise RuntimeError("Telegram publish requested with neither delivery option enabled.")
        step("publish_telegram", publish_command,
             artifact=video / "publish" / "TELEGRAM_PUBLISH_STATE.json")

    state["status"] = "DONE"
    state["completed_at"] = now()
    state["total_elapsed_seconds"] = round(sum(float(x.get("elapsed_seconds", 0)) for x in state["events"]), 3)
    summary = build_summary(video, artifact=polished)
    state["summary"] = summary
    save(state_path, state)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("COMPLETION PIPELINE: PASS")


if __name__ == "__main__":
    main()
