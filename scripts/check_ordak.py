#!/usr/bin/env python3
"""Check Ordak API, Chrome attachment, and ChatGPT authenticated readiness."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]


def _env_file() -> Path:
    path = Path(os.getenv("YT_ENV_FILE", ".env")).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--no-require-login",
        action="store_true",
        help="Only check API/browser reachability; do not require ChatGPT login readiness.",
    )
    args = parser.parse_args()

    env_file = _env_file()
    if env_file.exists():
        load_dotenv(env_file, override=False)

    base_url = os.getenv("YT_ORDAK_BASE_URL", "http://127.0.0.1:8000").rstrip("/")

    with httpx.Client(timeout=15.0, trust_env=False) as client:
        health_response = client.get(f"{base_url}/api/health")
        print(f"GET {base_url}/api/health -> HTTP {health_response.status_code}")
        health_response.raise_for_status()
        health = health_response.json()
        print(health)

        diagnostics_response = client.get(f"{base_url}/api/diagnostics")
        print(
            f"GET {base_url}/api/diagnostics -> "
            f"HTTP {diagnostics_response.status_code}"
        )
        diagnostics_response.raise_for_status()
        diagnostics = diagnostics_response.json()

    chrome_running = bool(diagnostics.get("chrome_running"))
    sessions = diagnostics.get("provider_sessions") or {}
    chatgpt = sessions.get("chatgpt") or {}
    logged_in = bool(chatgpt.get("logged_in"))
    login_state = str(chatgpt.get("login_state") or "unknown")
    busy = bool(chatgpt.get("busy"))

    print(f"chrome_running={chrome_running}")
    print(
        "chatgpt="
        f"logged_in:{logged_in} login_state:{login_state} busy:{busy}"
    )

    if not chrome_running:
        raise SystemExit("Ordak is running, but the configured Chrome session is not attached.")

    if not args.no_require_login and (not logged_in or login_state != "ready"):
        raise SystemExit(
            "Configured Chrome session is not ChatGPT-ready. "
            "Open/attach the exact profile configured in root .env and ensure it is logged in."
        )

    print("ORDAK CHECK: PASS")


if __name__ == "__main__":
    main()
