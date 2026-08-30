#!/usr/bin/env python3
"""Observe a running visual pipeline and notify only state transitions."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
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
    started = time.perf_counter()
    while True:
        state = read_state(state_path)
        if not state:
            time.sleep(args.interval_seconds)
            continue
        beats = state.get("beats", {})
        total = max(total, len(beats))
        for key, value in state.get("stages", {}).items():
            if value.get("status") == "DONE" and key not in seen_stages:
                notifier.stage_complete(key, 0, artifact="saved artifact")
                seen_stages.add(key)
        for key, value in sorted(beats.items()):
            if value.get("status") == "DONE" and key not in seen_done:
                notifier.image_complete(int(key), total, 0)
                seen_done.add(key)
            if value.get("status") in {"FAILED", "INVALID"}:
                marker = f"{key}:{value.get('status')}:{value.get('last_error', '')}"
                if marker not in seen_done:
                    notifier.warning(f"Beat {key} needs attention", str(value.get("last_error") or value.get("status")))
                    seen_done.add(marker)
        if total and len(seen_done & set(beats)) >= total:
            notifier.images_complete(total, time.perf_counter() - started, completed=total)
            return
        time.sleep(args.interval_seconds)


if __name__ == "__main__":
    main()
