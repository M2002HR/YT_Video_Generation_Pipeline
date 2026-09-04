#!/usr/bin/env python3
"""Full-stack readiness check (§103).

Every line here probes something. There are no hardcoded ``True`` reports: the Flow
style-sheet guard is checked by *asking it to accept a style sheet* and requiring a
refusal, provider readiness requires ``logged_in is True`` rather than merely "the API
answered", and a dirty working tree is reported as such instead of being reduced to
"the git command ran".

Exit codes:
  0  every required check passed
  1  at least one required check failed
  2  the checker itself could not run

Advisory checks print ``⚠`` and never change the exit code; they exist so the report
can say something without pretending it is fatal.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

PROVIDERS = ("chatgpt", "gemini", "flow")

#: Ports the stack must expose, with what listens there.
REQUIRED_PORTS = {
    4141: "panel (official public address)",
    4143: "noVNC through nginx",
    4142: "panel backend (loopback)",
    8000: "Ordak API (loopback)",
    6080: "noVNC (loopback)",
    5901: "x11vnc (loopback)",
}
ADVISORY_PORTS = {4144: "legacy panel port"}

REQUIRED_UNITS = ("ordak-api.service", "ordak-chrome.service", "video-control-panel.service")


@dataclass
class Report:
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    passes: int = 0

    def check(self, name: str, ok: bool, detail: str = "", *, required: bool = True) -> bool:
        if ok:
            self.passes += 1
            mark = "✅"
        elif required:
            self.failures.append(name)
            mark = "❌"
        else:
            self.warnings.append(name)
            mark = "⚠ "
        print(f"{mark} {name}{' — ' + detail if detail else ''}", flush=True)
        return ok


def run(cmd: list[str], *, cwd: Path = ROOT, timeout: int = 15) -> tuple[bool, str]:
    try:
        out = subprocess.run(
            cmd, cwd=cwd, text=True, timeout=timeout,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
        )
        return out.returncode == 0, (out.stdout or "").strip()
    except Exception as exc:  # missing binary, timeout
        return False, f"{type(exc).__name__}: {exc}"[:200]


def port_open(port: int, host: str = "127.0.0.1", timeout: float = 2.0) -> bool:
    with socket.socket() as sock:
        sock.settimeout(timeout)
        try:
            sock.connect((host, port))
            return True
        except OSError:
            return False


def check_git(report: Report) -> None:
    ok, branch = run(["git", "branch", "--show-current"])
    report.check("git branch readable", ok and bool(branch), branch or "unknown")
    ok, porcelain = run(["git", "status", "--porcelain"])
    if not ok:
        report.check("git status readable", False, porcelain)
        return
    dirty = [line for line in porcelain.splitlines() if line.strip()]
    report.check(
        "git working tree clean",
        not dirty,
        f"{len(dirty)} uncommitted path(s): "
        + ", ".join(line.split(maxsplit=1)[-1] for line in dirty[:5])
        if dirty else "clean",
        required=False,
    )
    ok, submodules = run(["git", "submodule", "status", "--recursive"])
    stale = [line for line in submodules.splitlines() if line.startswith(("+", "-", "U"))]
    report.check(
        "submodule pointers match", ok and not stale,
        "; ".join(stale) if stale else (submodules.splitlines() or ["none"])[0],
        required=False,
    )


def check_tooling(report: Report) -> None:
    free_mb = shutil.disk_usage(ROOT).free // (1024 * 1024)
    report.check("disk free > 500 MB", free_mb > 500, f"{free_mb} MB free")
    for binary in ("ffmpeg", "ffprobe"):
        path = shutil.which(binary)
        report.check(f"{binary} on PATH", path is not None, path or "not found")
    chrome = Path("/usr/bin/google-chrome")
    report.check("Chrome binary present", chrome.is_file(), str(chrome))


def check_browser_and_api(report: Report, base_url: str) -> dict:
    try:
        import httpx
    except ImportError as exc:
        report.check("httpx importable", False, str(exc))
        return {}

    try:
        version = httpx.get("http://127.0.0.1:9222/json/version", timeout=5, trust_env=False)
        payload = version.json() if version.status_code == 200 else {}
        report.check(
            "Chrome DevTools on 9222",
            version.status_code == 200,
            str(payload.get("Browser") or f"HTTP {version.status_code}"),
        )
    except Exception as exc:
        report.check("Chrome DevTools on 9222", False, f"{type(exc).__name__}: {exc}"[:140])

    diagnostics: dict = {}
    try:
        health = httpx.get(f"{base_url}/api/health", timeout=5, trust_env=False)
        report.check(
            "Ordak /api/health",
            health.status_code == 200 and (health.json().get("status") == "ok"),
            health.text[:120],
        )
        response = httpx.get(f"{base_url}/api/diagnostics", timeout=15, trust_env=False)
        diagnostics = response.json() if response.status_code == 200 else {}
        report.check("Ordak /api/diagnostics", response.status_code == 200)
        report.check(
            "Chrome reported as running",
            bool(diagnostics.get("chrome_running")),
            f"chrome_running={diagnostics.get('chrome_running')}",
        )
    except Exception as exc:
        report.check("Ordak API reachable", False, f"{type(exc).__name__}: {exc}"[:160])
        return {}

    sessions = diagnostics.get("provider_sessions") or {}
    for provider in PROVIDERS:
        session = sessions.get(provider) or {}
        state = str(session.get("login_state") or "unknown")
        logged_in = session.get("logged_in") is True
        report.check(
            f"{provider} session authenticated",
            logged_in and state == "ready",
            f"logged_in={session.get('logged_in')} state={state} tabs={len(session.get('open_tabs') or [])}",
        )
    return diagnostics


def check_ports(report: Report) -> None:
    for port, what in REQUIRED_PORTS.items():
        report.check(f"port {port} open ({what})", port_open(port))
    for port, what in ADVISORY_PORTS.items():
        report.check(f"port {port} open ({what})", port_open(port), required=False)


def check_units(report: Report) -> None:
    for unit in REQUIRED_UNITS:
        ok, state = run(["systemctl", "is-active", unit], timeout=10)
        report.check(f"systemd {unit} active", ok and state.strip() == "active", state or "unknown")


def check_flow_reference_guard(report: Report) -> None:
    """Prove the guard refuses a style sheet instead of asserting that it does."""
    try:
        import flow_reference_policy as policy
    except Exception as exc:
        report.check("flow_reference_policy importable", False, f"{type(exc).__name__}: {exc}")
        return

    refused: list[str] = []
    accepted_wrongly: list[str] = []
    for role in ("world_style_anchor", "style_anchor", "style_sheet", "mood_board"):
        try:
            policy.validate_flow_roles([role])
        except policy.FlowReferencePolicyError:
            refused.append(role)
        else:
            accepted_wrongly.append(role)
    report.check(
        "Flow refuses every style-sheet role",
        not accepted_wrongly,
        f"refused {refused}" if not accepted_wrongly else f"WRONGLY ACCEPTED {accepted_wrongly}",
    )

    try:
        clip_a = policy.clip_a_roles()
        clip_b = policy.clip_b_roles()
    except Exception as exc:
        report.check("canonical clip roles resolve", False, f"{type(exc).__name__}: {exc}")
        return
    report.check("Clip A uses the character sheet", clip_a == ["character_sheet"], str(clip_a))
    report.check(
        "Clip B uses first+last frame only",
        clip_b == ["first_frame", "last_frame"],
        str(clip_b),
    )

    try:
        policy.assert_no_style_sheet_in_references([Path("references/world_style_anchor.png")])
    except policy.FlowReferencePolicyError:
        report.check("Flow refuses a style-sheet filename", True, "path guard active")
    else:
        report.check("Flow refuses a style-sheet filename", False, "path guard did not fire")


def check_question_harvest_assets(report: Report) -> None:
    try:
        from content_projects import load_content_project

        project = load_content_project("question_harvest")
    except Exception as exc:
        report.check("question_harvest project loads", False, f"{type(exc).__name__}: {exc}")
        return
    report.check(
        "QH image provider is gemini", project.get_provider("image") == "gemini",
        str(project.get_provider("image")),
    )
    report.check(
        "QH video provider is flow", project.get_provider("video") == "flow",
        str(project.get_provider("video")),
    )

    character = ROOT / "projects" / "question_harvest" / "visual_presets" / "001_home_world" / "character_sheet.png"
    report.check(
        "QH character_sheet.png usable",
        character.is_file() and character.stat().st_size > 5_000,
        f"{character.stat().st_size} bytes" if character.is_file() else "missing",
    )

    templates_root = ROOT / "projects" / "question_harvest" / "book_templates"
    catalog = templates_root / "CATALOG.json"
    try:
        entries = json.loads(catalog.read_text(encoding="utf-8")).get("templates") or []
    except Exception as exc:
        report.check("book template catalog readable", False, f"{type(exc).__name__}: {exc}")
        return
    missing = [
        str(entry.get("template_id"))
        for entry in entries
        if not (templates_root / str(entry.get("path") or "") / "blank_book.png").is_file()
    ]
    report.check(
        "every catalogued book template has blank_book.png",
        bool(entries) and not missing,
        f"{len(entries)} template(s)" if not missing else f"missing: {missing}",
    )

    identity = ROOT / "projects" / "question_harvest" / "prompts" / "reference" / "book_transition_reference_prompt.txt"
    report.check("locked book identity present", identity.is_file(), str(identity.name))


def check_no_synthetic_path(report: Report) -> None:
    """The production scripts must contain no synthetic-media escape hatch (§4)."""
    # This file is excluded because it has to name the patterns in order to search for them.
    ok, hits = run(
        [
            "grep", "-rnE", "--exclude=check_full_stack.py",
            r"allow_synthetic|synthetic_fallback|_dummy_|\[MODEL:", "scripts/",
        ],
    )
    # grep exits 1 with no output when nothing matches, which is the healthy case.
    offenders = [line for line in hits.splitlines() if line.strip()]
    report.check(
        "no synthetic fallback in scripts/",
        not offenders,
        "clean" if not offenders else f"{len(offenders)} hit(s): {offenders[0][:120]}",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Full-stack readiness check (§103)")
    parser.add_argument(
        "--base-url",
        default=os.getenv("YT_ORDAK_BASE_URL", "http://127.0.0.1:8000").rstrip("/"),
    )
    parser.add_argument(
        "--skip-providers",
        action="store_true",
        help="Report provider login state without letting it fail the run (local development).",
    )
    args = parser.parse_args()

    report = Report()
    print("== repository ==")
    check_git(report)
    print("\n== tooling ==")
    check_tooling(report)
    print("\n== browser and API ==")
    diagnostics = check_browser_and_api(report, args.base_url)
    if args.skip_providers:
        moved = [name for name in report.failures if name.endswith("session authenticated")]
        report.failures = [name for name in report.failures if name not in moved]
        report.warnings.extend(moved)
    print("\n== ports ==")
    check_ports(report)
    print("\n== services ==")
    check_units(report)
    print("\n== Flow reference policy ==")
    check_flow_reference_guard(report)
    print("\n== Question Harvest assets ==")
    check_question_harvest_assets(report)
    print("\n== production path ==")
    check_no_synthetic_path(report)

    print(
        f"\n{report.passes} passed, {len(report.failures)} failed, {len(report.warnings)} advisory"
    )
    if report.warnings:
        print("advisory: " + ", ".join(report.warnings))
    if report.failures:
        print("FAILED: " + ", ".join(report.failures))
        return 1
    print("Full stack ready.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # the checker itself broke
        print(f"check_full_stack could not run: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(2)
