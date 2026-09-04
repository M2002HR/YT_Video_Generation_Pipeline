#!/usr/bin/env python3
"""Commit and push one completed video's durable artifacts without touching other work."""
from __future__ import annotations

import argparse
import json
import re
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


def commit_paths(paths: list[Path], message: str) -> str | None:
    """Commit only these paths, preserving any unrelated staged user work."""
    relatives = [str(path.relative_to(ROOT)) for path in paths]
    git("add", "-A", "--", *relatives, capture=False)
    staged = subprocess.run(
        ["git", "diff", "--cached", "--quiet", "--", *relatives],
        cwd=ROOT,
        check=False,
    )
    if staged.returncode == 0:
        return None
    if staged.returncode != 1:
        raise RuntimeError("Could not inspect the staged video artifacts.")
    git("commit", "--no-verify", "--only", "-m", message, "--", *relatives, capture=False)
    return git("rev-parse", "HEAD")


def register_content_project_video(project: Path, state: dict[str, Any]) -> Path:
    """Add a completed video to its durable content-project registry."""
    content_project = str(state.get("content_project") or "default").strip()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", content_project):
        raise RuntimeError(f"Invalid content project in pipeline state: {content_project!r}")
    project_root = ROOT / "projects" / content_project
    config = project_root / "PROJECT.json"
    registry = project_root / "VIDEOS.json"
    if not config.is_file() or not registry.is_file():
        raise RuntimeError(f"Content-project registry is incomplete: projects/{content_project}")
    payload = json.loads(registry.read_text(encoding="utf-8"))
    if payload.get("project_id") != content_project or not isinstance(payload.get("videos"), list):
        raise RuntimeError(f"Invalid content-project video registry: {registry.relative_to(ROOT)}")
    videos = [str(value) for value in payload["videos"]]
    if project.name not in videos:
        videos.append(project.name)
        payload["videos"] = sorted(set(videos), key=lambda value: (int(value.split("_", 1)[0]) if value.split("_", 1)[0].isdigit() else 10**9, value))
        write_json(registry, payload)
    return registry


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


def elapsed_since(started_at: str) -> float:
    """Seconds since ``started_at``, whether it is an ISO stamp or a perf_counter value.

    A perf_counter value only means anything inside the process that produced it, so an ISO
    timestamp is the form callers in other processes should pass.
    """
    text = str(started_at).strip()
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        try:
            return max(0.0, round(time.perf_counter() - float(text), 3))
        except ValueError:
            return 0.0
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return max(0.0, round((datetime.now(timezone.utc) - moment).total_seconds(), 3))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Commit and push one completed video's durable Git artifacts.")
    parser.add_argument("project", type=Path)
    parser.add_argument("--full-state", type=Path, required=True)
    parser.add_argument(
        "--started-at",
        required=True,
        help="ISO timestamp, or a perf_counter value from this same process.",
    )
    parser.add_argument(
        "--no-push",
        action="store_true",
        help="Commit locally without pushing. Useful when the remote credential is not in place.",
    )
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

    state = json.loads(state_path.read_text(encoding="utf-8"))
    registry = register_content_project_video(project, state)
    first_commit = commit_paths([project, registry], f"Video {project.name}: finalized artifacts")
    if not args.no_push:
        push(branch)

    completed_at = now()
    elapsed = elapsed_since(args.started_at)
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
    receipt_commit = commit_paths([project], f"Video {project.name}: record Git publication")
    if not args.no_push:
        push(branch)
    print(json.dumps({
        "status": "GIT_PUBLISH_PASS",
        "branch": branch,
        "pushed": not args.no_push,
        "artifact_commit": first_commit,
        "receipt_commit": receipt_commit,
        "no_change": first_commit is None and receipt_commit is None,
        "elapsed_seconds": elapsed,
    }))


if __name__ == "__main__":
    main()
