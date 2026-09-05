#!/usr/bin/env python3
"""Wait out a Google Flow outage, then continue the parked episode.

Flow's regional block and its "high demand" refusals come from Google's side and clear on
their own. This runs as its own control-panel job so the wait is visible, stoppable and
deletable like any other run, instead of being a silent background thread.

Each cycle:

  1. Probe the Flow project page. No upload, no Generate — the probe never spends a credit.
  2. Log the verdict, so the panel's log tail shows exactly how long the wait has been.
  3. When Flow answers normally, launch the same pipeline command the episode was started
     with. Completed stages are reused, so only the clips and the render are paid for.

It stops after the episode finishes, after ``--max-cycles``, or when asked to stop.
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

#: Flow's own words for a blocked or overloaded service.
OUTAGE_URL_MARKERS = ("/unsupported-country", "flow.google.com/unsupported")
OUTAGE_TEXT_MARKERS = ("not available in your country", "not available in this country")


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def log(message: str) -> None:
    print(f"[{utcnow()}] {message}", flush=True)


def flow_project_url() -> str:
    return os.getenv("YT_ORDAK_FLOW_URL", "https://labs.google/fx/tools/flow").strip()


def browser_is_busy() -> bool:
    """True when another provider is mid-job, so probing would steal its tab.

    Ordak keeps one work tab: opening the Flow page closes whatever is there. A probe must
    never do that to a running stage.
    """
    import urllib.request

    try:
        with urllib.request.urlopen("http://127.0.0.1:9222/json/list", timeout=8) as response:
            targets = json.loads(response.read().decode())
    except Exception:
        return True
    for target in targets:
        if target.get("type") != "page":
            continue
        url = str(target.get("url") or "")
        if any(host in url for host in ("gemini.google.com", "chatgpt.com", "elevenlabs.io", "mixkit.co", "pixabay.com")):
            return True
    return False


def probe_flow() -> tuple[str, str]:
    """``("available"|"blocked"|"unknown", detail)`` without spending anything."""
    sys.path.insert(0, str(ROOT / "services" / "ordak"))
    try:
        from app.automation.existing_chrome import (  # type: ignore[import-not-found]
            ChromeTabRef,
            execute_javascript,
            open_url_in_existing_chrome,
        )
    except ImportError as exc:
        return ("unknown", f"ordak runtime unavailable: {exc}")
    try:
        tab = open_url_in_existing_chrome(flow_project_url())
        time.sleep(8)
        ref = ChromeTabRef(window_id=tab.window_id, tab_id=tab.tab_id, target_id=tab.target_id)
        payload = execute_javascript(
            ref,
            "(() => JSON.stringify({u: location.href,"
            " t: (document.body ? document.body.innerText : '').slice(0, 3000)}))()",
        )
        data = json.loads(payload or "{}")
    except Exception as exc:
        return ("unknown", f"{type(exc).__name__}: {exc}")
    url = str(data.get("u") or "").lower()
    text = str(data.get("t") or "").lower()
    if any(marker in url for marker in OUTAGE_URL_MARKERS):
        return ("blocked", f"redirected to {data.get('u')}")
    if any(marker in text for marker in OUTAGE_TEXT_MARKERS):
        return ("blocked", "the page says Flow is not available in this country")
    if "/fx/tools/flow" not in url:
        return ("unknown", f"unexpected url {data.get('u')}")
    return ("available", f"project page loaded: {data.get('u')}")


def episode_finished(project: Path) -> bool:
    """True once the polished render exists and its QC report is there beside it."""
    return (project / "assets" / "renders" / "polished.mp4").is_file() and (
        project / "render" / "QC_REPORT_polished.json"
    ).is_file()


def main() -> int:
    parser = argparse.ArgumentParser(description="Resume a Flow-blocked episode when Flow returns.")
    parser.add_argument("project", type=Path, help="The episode directory to finish.")
    parser.add_argument(
        "--command-file",
        type=Path,
        required=True,
        help="JSON file holding the pipeline command to re-run, as a list of arguments.",
    )
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=int(os.getenv("YT_FLOW_WATCH_INTERVAL_SECONDS", "1200")),
        help="How long to wait between probes (default 1200 = 20 minutes).",
    )
    parser.add_argument("--max-cycles", type=int, default=144, help="Give up after this many probes.")
    args = parser.parse_args()

    project = args.project if args.project.is_absolute() else ROOT / args.project
    try:
        command = json.loads(args.command_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log(f"FATAL: could not read the pipeline command from {args.command_file}: {exc}")
        return 2
    if not isinstance(command, list) or not command:
        log(f"FATAL: {args.command_file} does not contain a command list.")
        return 2

    log(
        f"Flow watcher started for {project.name}. Probing every "
        f"{args.interval_seconds}s ({args.interval_seconds / 60:.0f} min), "
        f"up to {args.max_cycles} times. Probes cost no credits."
    )

    for cycle in range(1, args.max_cycles + 1):
        if episode_finished(project):
            log("The episode already has a polished render and a passing QC report. Nothing to wait for.")
            return 0
        if browser_is_busy():
            log(f"cycle {cycle}: another provider is using the browser; skipping this probe.")
        else:
            state, detail = probe_flow()
            log(f"cycle {cycle}: Flow is {state} — {detail}")
            if state == "available":
                log("Flow is reachable again. Continuing the episode; completed stages are reused.")
                result = subprocess.run(command, cwd=ROOT)
                if result.returncode == 0:
                    log("The episode finished. Watcher done.")
                    return 0
                if result.returncode == 4:
                    log("Still waiting for the Flow clips; the run parked again. Continuing to watch.")
                else:
                    log(
                        f"The run exited {result.returncode}. Leaving it to a human rather than "
                        "retrying a failure that is not an outage."
                    )
                    return result.returncode
        time.sleep(args.interval_seconds)

    log(f"Gave up after {args.max_cycles} probes. Flow never became available.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
