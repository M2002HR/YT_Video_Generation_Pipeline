#!/usr/bin/env python3
"""Commit and push one completed video's durable artifacts without touching other work."""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def git(*args: str, capture: bool = True) -> str:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, text=True, capture_output=capture, check=False
    )
    if result.returncode:
        detail = (result.stderr or result.stdout or "git command failed").strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {detail}")
    # ``subprocess.run(..., capture_output=False)`` intentionally leaves both
    # streams as None.  Commands such as ``git add``/``git push`` are still
    # successful and must not turn into an AttributeError after completion.
    return (result.stdout or "").strip()


def commit_project(project: Path, message: str) -> str | None:
    relative = project.relative_to(ROOT)
    git("add", "-A", "--", str(relative), capture=False)
    staged = subprocess.run(
        ["git", "diff", "--cached", "--quiet", "--", str(relative)],
        cwd=ROOT,
        check=False,
    )
    if staged.returncode == 0:
        return None
    if staged.returncode != 1:
        raise RuntimeError("Could not inspect the staged video artifacts.")
    git("commit", "--no-verify", "-m", message, capture=False)
    return git("rev-parse", "HEAD")


def push(branch: str, *, attempts: int = 4) -> None:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            git("push", "origin", branch, capture=False)
            return
        except RuntimeError as exc:
            last_error = exc
            if attempt == attempts:
                break
            time.sleep(min(20, 2 ** attempt))
    raise RuntimeError(f"Could not push video artifacts after {attempts} attempts: {last_error}")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Commit and push one completed video's durable Git artifacts.")
    parser.add_argument("project", type=Path)
    parser.add_argument("--full-state", type=Path, required=True)
    parser.add_argument("--started-at", required=True)
    args = parser.parse_args()
    project = args.project.expanduser().resolve()
    state_path = args.full_state.expanduser().resolve()
    if not project.is_dir() or ROOT not in project.parents:
        raise SystemExit("Project must be a directory inside this repository.")
    if not state_path.is_file() or project not in state_path.parents:
        raise SystemExit("Full-pipeline state must exist inside the selected project.")
    branch = git("branch", "--show-current")
    if not branch:
        raise SystemExit("Automatic Git publication requires a named branch, not detached HEAD.")

    first_commit = commit_project(project, f"Video {project.name}: finalized artifacts")
    push(branch)

    completed_at = now()
    elapsed = round(time.perf_counter() - float(args.started_at), 3)
    receipt = project / "pipeline" / "GIT_PUBLISH_STATE.json"
    write_json(receipt, {
        "schema_version": 1,
        "status": "DONE",
        "branch": branch,
        "remote": "origin",
        "artifact_commit": first_commit,
        "started_at": args.started_at,
        "completed_at": completed_at,
        "elapsed_seconds": elapsed,
        "scope": str(project.relative_to(ROOT)),
    })
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["events"].append({
        "stage": "git_commit_push",
        "status": "DONE",
        "started_at": args.started_at,
        "ended_at": completed_at,
        "elapsed_seconds": elapsed,
        "branch": branch,
        "remote": "origin",
        "artifact_commit": first_commit,
    })
    state.update({
        "status": "DONE",
        "completed_at": completed_at,
        "total_elapsed_seconds": round(sum(float(item.get("elapsed_seconds", 0)) for item in state["events"]), 3),
    })
    write_json(state_path, state)
    receipt_commit = commit_project(project, f"Video {project.name}: record Git publication")
    push(branch)
    print(json.dumps({"status": "GIT_PUBLISH_PASS", "branch": branch, "artifact_commit": first_commit, "receipt_commit": receipt_commit, "elapsed_seconds": elapsed}))


if __name__ == "__main__":
    main()
