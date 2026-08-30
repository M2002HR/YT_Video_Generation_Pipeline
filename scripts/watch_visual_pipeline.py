#!/usr/bin/env python3
"""Observe a running visual pipeline and notify only state transitions."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from pipeline_notifier import PipelineNotifier


ROOT = Path(__file__).resolve().parents[1]


def read_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def done_count(state: dict) -> int:
    return sum(1 for value in state.get("beats", {}).values() if value.get("status") == "DONE")


def timestamp_seconds(value: object) -> float | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--interval-seconds", type=float, default=5.0)
    args = parser.parse_args()
    load_dotenv(ROOT / os.getenv("YT_ENV_FILE", ".env"), override=False)
    state_path = args.project / "visual_pipeline" / "RUNTIME_STATE.json"
    initial = read_state(state_path)
    notifier = PipelineNotifier(str(args.project.name.split("_", 1)[0]), str(initial.get("topic", "Visual pipeline")))
    beats = initial.get("beats", {})
    total = len(beats)
    generating = next((int(key) for key, value in beats.items() if value.get("status") == "GENERATING"), None)
    notifier.monitoring_started(done_count(initial), total, generating)
    seen_stages = {key for key, value in initial.get("stages", {}).items() if value.get("status") == "DONE"}
    seen_done = {key for key, value in beats.items() if value.get("status") == "DONE"}
    generating_started = {
        key: timestamp_seconds(initial.get("updated_at")) or time.time()
        for key, value in beats.items() if value.get("status") == "GENERATING"
    }
    started = time.perf_counter()
    while True:
        state = read_state(state_path)
        if not state:
            time.sleep(args.interval_seconds)
            continue
        beats = state.get("beats", {})
        total = max(total, len(beats))
        for key, value in beats.items():
            if value.get("status") == "GENERATING" and key not in generating_started:
                generating_started[key] = timestamp_seconds(state.get("updated_at")) or time.time()
        for key, value in state.get("stages", {}).items():
            if value.get("status") == "DONE" and key not in seen_stages:
                notifier.stage_complete(key, 0, artifact="saved artifact")
                seen_stages.add(key)
        for key, value in sorted(beats.items()):
            if value.get("status") == "DONE" and key not in seen_done:
                finished = timestamp_seconds(value.get("completed_at")) or time.time()
                elapsed = max(0, finished - generating_started.get(key, finished))
                notifier.image_complete(int(key), total, elapsed)
                seen_done.add(key)
            if value.get("status") in {"FAILED", "INVALID"}:
                marker = f"{key}:{value.get('status')}:{value.get('last_error', '')}"
                if marker not in seen_done:
                    notifier.warning(f"Beat {key} needs attention", str(value.get("last_error") or value.get("status")))
                    seen_done.add(marker)
        if total and len(seen_done & set(beats)) >= total:
            observed_count = len(notifier.image_durations)
            observed_total = sum(notifier.image_durations)
            notifier.send(
                "Live monitoring complete",
                [
                    "👀 The active runner finished",
                    f"📍 Accepted while monitored: {observed_count}/{total} images",
                    f"⏱ Observed image total: {observed_total:.0f} seconds",
                ],
            )
            return
        time.sleep(args.interval_seconds)


if __name__ == "__main__":
    main()
